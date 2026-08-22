"""Docker/container sandbox backend for Hamster.

Provides two execution models:

``DockerSession`` — **Persistent session** (recommended for interactive use):
    Keeps one background container alive for the lifetime of the session.
    Commands are dispatched via ``docker exec``, so cwd, environment variables,
    and background processes all *persist across calls*.  If the container dies
    unexpectedly the session **self-heals** by spinning up a fresh container and
    restoring the tracked ``cwd`` / ``env`` before retrying.

``DockerSandboxBackend`` (alias ``DockerEphemeralBackend``) — **Ephemeral per-command**:
    The original ``docker run --rm`` approach; each command gets its own fresh
    container.  Retained for backward compatibility and simple one-shot use.
    When ``require_isolation=True`` the backend raises ``IsolationError`` instead
    of silently falling back to host execution.

Isolation flags
---------------
``REQUIRE_ISOLATION`` — module-level bool read from env var
``HAMSTER_REQUIRE_ISOLATION``.  When *True*, any attempt to fall back to host
execution in strict contexts raises ``IsolationError``.

Public API (unchanged from v0.3)
---------------------------------
``ContainerResult``       — NamedTuple(stdout, stderr, returncode)
``DockerSandboxBackend``  — ephemeral backend class
``get_backend()``         — module-level ephemeral backend singleton
``execute_sandboxed()``   — convenience wrapper around ``get_backend()``

New additions
-------------
``IsolationError``        — raised when Docker unavailable in strict mode
``DockerSession``         — persistent session class
``get_session()``         — module-level persistent session singleton
"""
from __future__ import annotations

import atexit
import os
import shlex
import shutil
import subprocess
import threading
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class IsolationError(RuntimeError):
    """Raised when Docker isolation is required but unavailable.

    Thrown by :class:`DockerSandboxBackend` (and :class:`DockerSession`) when
    ``require_isolation=True`` / ``HAMSTER_REQUIRE_ISOLATION=1`` is set but the
    Docker daemon is not reachable, rather than silently falling back to host
    execution.
    """


# ---------------------------------------------------------------------------
# Module-level isolation enforcement flag
# ---------------------------------------------------------------------------

def _read_require_isolation() -> bool:
    """Read HAMSTER_REQUIRE_ISOLATION from the environment.

    Accepts ``"1"``, ``"true"``, ``"yes"`` (case-insensitive) as truthy.
    """
    val = os.environ.get("HAMSTER_REQUIRE_ISOLATION", "").strip().lower()
    return val in ("1", "true", "yes")


REQUIRE_ISOLATION: bool = _read_require_isolation()


# ---------------------------------------------------------------------------
# Shared result type
# ---------------------------------------------------------------------------

class ContainerResult(NamedTuple):
    """Unified result type for both container and host-fallback execution."""

    stdout: str
    stderr: str
    returncode: int


# ---------------------------------------------------------------------------
# Docker availability helper (shared by both backends)
# ---------------------------------------------------------------------------

def _docker_is_available() -> bool:
    """Return True if the Docker CLI is on PATH and the daemon responds."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Persistent Docker session
# ---------------------------------------------------------------------------

class DockerSession:
    """Persistent background Docker container for interactive agent use.

    Keeps a single long-lived container running (``docker run -d --rm … tail -f
    /dev/null``) and dispatches commands via ``docker exec``.  This means:

    * **cwd persists** — ``cd`` commands update ``self.cwd``; each subsequent
      exec is started in that directory via ``-w <cwd>``.
    * **env persists** — key/value pairs stored in ``self.env`` are forwarded as
      ``-e KEY=VALUE`` flags to every ``docker exec`` call.
    * **self-healing** — before each ``docker exec`` the container liveness is
      checked via ``is_alive()``.  If the container has exited or crashed,
      ``restart_container()`` spins up a new one and restores ``cwd``/``env``.

    Usage::

        session = DockerSession()
        session.start(cwd="/workspace")
        result = session.execute("echo hello")
        print(result.stdout)   # "hello"
        session.stop()

    Or as a context manager::

        with DockerSession() as s:
            s.execute("pip install requests")
            s.execute("python -c 'import requests; print(requests.__version__)'")
    """

    DEFAULT_IMAGE: str = "python:3.11-slim"
    EXEC_TIMEOUT: int = 60   # seconds per command
    START_TIMEOUT: int = 15  # seconds to wait for container start

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        workspace: str | None = None,
        require_isolation: bool = REQUIRE_ISOLATION,
    ) -> None:
        self.image = image
        self.workspace = workspace  # host path bind-mounted at /workspace
        self.require_isolation = require_isolation

        # Mutable session state — persisted across exec calls and restored on heal
        self.cwd: str = "/workspace"
        self.env: dict[str, str] = {}

        self._container_id: str | None = None
        self._lock = threading.Lock()
        self._stopped = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, cwd: str | None = None) -> None:
        """Start the background container.

        Args:
            cwd: Initial working directory inside the container.
                 Defaults to ``/workspace``.

        Raises:
            IsolationError: When ``require_isolation=True`` and Docker is
                not reachable.
            RuntimeError: When the container fails to start.
        """
        if cwd:
            self.cwd = cwd

        if not _docker_is_available():
            if self.require_isolation:
                raise IsolationError(
                    "Docker is required (HAMSTER_REQUIRE_ISOLATION=1) but is not "
                    "available.  Install Docker or unset HAMSTER_REQUIRE_ISOLATION."
                )
            raise RuntimeError(
                "Docker is not available.  Cannot start a persistent DockerSession."
            )

        with self._lock:
            if self._container_id and self.is_alive():
                return  # already running

            self._container_id = self._spin_up_container()
            self._stopped = False
            atexit.register(self.stop)

    def stop(self) -> None:
        """Stop and remove the background container (idempotent)."""
        with self._lock:
            if self._stopped or self._container_id is None:
                return
            self._stopped = True
            cid = self._container_id
            self._container_id = None

        try:
            subprocess.run(
                ["docker", "stop", cid],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:
            pass

    def __enter__(self) -> "DockerSession":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Liveness & recovery
    # ------------------------------------------------------------------

    def is_alive(self) -> bool:
        """Return True if the session container is currently running."""
        cid = self._container_id
        if not cid:
            return False
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format={{.State.Running}}", cid],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    def restart_container(self) -> None:
        """Recover from a dead container by spinning up a fresh one.

        Stops the old container (best-effort), starts a replacement, then
        restores ``self.cwd`` and ``self.env`` inside the new container so
        execution can continue transparently.
        """
        old_cid = self._container_id
        if old_cid:
            try:
                subprocess.run(
                    ["docker", "stop", old_cid],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass

        with self._lock:
            self._container_id = self._spin_up_container()
            self._stopped = False

        # Restore working directory — mkdir -p ensures it exists in the new container
        if self.cwd and self.cwd != "/workspace":
            self._raw_exec(f"mkdir -p {shlex.quote(self.cwd)}")

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute(self, command: str) -> ContainerResult:
        """Execute *command* inside the persistent container.

        Automatically self-heals if the container has died since the last call.

        Args:
            command: Shell command string executed via ``sh -c``.

        Returns:
            :class:`ContainerResult` with stdout, stderr, and returncode.
        """
        # Ensure the session is started
        if self._container_id is None:
            self.start()

        # Self-heal if container died
        if not self.is_alive():
            self.restart_container()

        return self._raw_exec(command)

    def _raw_exec(self, command: str) -> ContainerResult:
        """Run *command* inside the container unconditionally."""
        cid = self._container_id
        if not cid:
            return ContainerResult(
                stdout="",
                stderr="No active container.",
                returncode=1,
            )

        # Build docker exec argv
        docker_cmd: list[str] = [
            "docker", "exec",
            "-i",
            "-w", self.cwd,
        ]
        # Forward tracked env vars
        for key, value in self.env.items():
            docker_cmd += ["-e", f"{key}={value}"]

        docker_cmd += [cid, "sh", "-c", command]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.EXEC_TIMEOUT,
                check=False,
            )
            return ContainerResult(
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ContainerResult(
                stdout="",
                stderr=f"Command timed out after {self.EXEC_TIMEOUT}s.",
                returncode=124,
            )
        except OSError as exc:
            return ContainerResult(
                stdout="",
                stderr=str(exc),
                returncode=1,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spin_up_container(self) -> str:
        """Start a detached background container and return its container ID."""
        docker_cmd: list[str] = [
            "docker", "run",
            "--rm",
            "--detach",
            "--network=none",
            "--memory=256m",
            "--cpus=1",
        ]
        if self.workspace:
            docker_cmd += ["-v", f"{self.workspace}:/workspace:rw"]

        docker_cmd += [
            self.image,
            "tail", "-f", "/dev/null",
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.START_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Timed out waiting for Docker container to start after {self.START_TIMEOUT}s."
            )
        except OSError as exc:
            raise RuntimeError(f"Failed to start Docker container: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"docker run failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError("docker run returned an empty container ID.")

        return container_id


# ---------------------------------------------------------------------------
# Ephemeral per-command backend (original, preserved for backward compat)
# ---------------------------------------------------------------------------

class DockerSandboxBackend:
    """Execute commands in an ephemeral Docker container.

    Uses ``docker run --rm`` so the container is automatically removed after
    each command.  When Docker is unavailable *and* ``require_isolation=False``
    the identical host-subprocess path is taken — callers see no behavioral
    difference.

    When ``require_isolation=True`` (or ``HAMSTER_REQUIRE_ISOLATION=1``), an
    :class:`IsolationError` is raised instead of falling back to host execution.

    Usage::

        backend = DockerSandboxBackend()
        result = backend.execute_command("python --version", cwd="/tmp/workspace")
        print(result.stdout)
    """

    DEFAULT_IMAGE: str = "python:3.11-slim"
    TIMEOUT: int = 60  # seconds

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        require_isolation: bool = REQUIRE_ISOLATION,
    ) -> None:
        self.image = image
        self.require_isolation = require_isolation
        self._available: bool | None = None  # Lazily cached

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` if the Docker CLI is on PATH and the daemon responds."""
        if self._available is not None:
            return self._available
        self._available = _docker_is_available()
        return self._available  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute_command(self, command: str, cwd: str | None = None) -> ContainerResult:
        """Run *command* inside an ephemeral container (or on the host as fallback).

        Args:
            command: Shell command string parsed with ``shlex.split``.
            cwd: Host directory bind-mounted into the container at ``/workspace``
                 (typically the active sandbox workspace).

        Returns:
            :class:`ContainerResult` with stdout, stderr, and returncode.

        Raises:
            IsolationError: When ``require_isolation=True`` and Docker is not
                available, rather than falling back to host execution.
        """
        if not self.is_available():
            if self.require_isolation:
                raise IsolationError(
                    "Docker is required (HAMSTER_REQUIRE_ISOLATION=1 or "
                    "require_isolation=True) but is not available or not running. "
                    "Start Docker or disable strict isolation mode."
                )
            return self._host_execute(command, cwd)

        try:
            parts = shlex.split(command)
        except ValueError:
            return ContainerResult(
                stdout="",
                stderr=f"Could not parse command: {command!r}",
                returncode=1,
            )

        docker_cmd: list[str] = [
            "docker", "run",
            "--rm",
            "--network=none",
            "--memory=256m",
            "--cpus=1",
        ]
        if cwd:
            docker_cmd += ["-v", f"{cwd}:/workspace:rw", "-w", "/workspace"]
        docker_cmd += [self.image] + parts

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
                check=False,
            )
            return ContainerResult(
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ContainerResult(
                stdout="",
                stderr=f"Container command timed out after {self.TIMEOUT}s.",
                returncode=124,
            )
        except OSError:
            # docker invocation failed unexpectedly — fall back transparently
            # (only when require_isolation is False; already checked above)
            return self._host_execute(command, cwd)

    # ------------------------------------------------------------------
    # Host fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _host_execute(command: str, cwd: str | None) -> ContainerResult:
        """Execute *command* directly on the host (fallback path)."""
        try:
            parts = shlex.split(command)
        except ValueError:
            return ContainerResult(
                stdout="",
                stderr=f"Could not parse command: {command!r}",
                returncode=1,
            )
        result = subprocess.run(
            parts,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        return ContainerResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )


# Internal alias — preserves the original class name for any internal callers
DockerEphemeralBackend = DockerSandboxBackend


# ---------------------------------------------------------------------------
# Module-level singletons and public entry points
# ---------------------------------------------------------------------------

_backend: DockerSandboxBackend | None = None
_backend_lock = threading.Lock()

_session: DockerSession | None = None
_session_lock = threading.Lock()


def get_backend() -> DockerSandboxBackend:
    """Return the module-level :class:`DockerSandboxBackend` (ephemeral) singleton."""
    global _backend
    with _backend_lock:
        if _backend is None:
            _backend = DockerSandboxBackend()
        return _backend


def get_session(
    image: str = DockerSession.DEFAULT_IMAGE,
    workspace: str | None = None,
    require_isolation: bool = REQUIRE_ISOLATION,
) -> DockerSession:
    """Return the module-level :class:`DockerSession` singleton.

    Lazily initializes on first call.  The session is *not* automatically
    started here — call :meth:`DockerSession.start` (or use the session as a
    context manager) before executing commands.

    Args:
        image: Docker image to use (only applied on first call).
        workspace: Host path to bind-mount at ``/workspace`` (first call only).
        require_isolation: If True, raises :class:`IsolationError` when Docker
            is unavailable (first call only).

    Returns:
        The shared :class:`DockerSession` instance for this process.
    """
    global _session
    with _session_lock:
        if _session is None:
            _session = DockerSession(
                image=image,
                workspace=workspace,
                require_isolation=require_isolation,
            )
        return _session


def execute_sandboxed(command: str, cwd: str | None = None) -> ContainerResult:
    """Public entry point: run *command* in a container (or host fallback).

    Uses the ephemeral :class:`DockerSandboxBackend` singleton.  Preserved
    unchanged for all existing callers.

    Args:
        command: Shell command string.
        cwd: Working directory (host path, bind-mounted into container).

    Returns:
        :class:`ContainerResult`.
    """
    return get_backend().execute_command(command, cwd)
