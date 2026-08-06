"""Docker/container sandbox backend for Hamster.

Provides a ``DockerSandboxBackend`` that executes commands inside an ephemeral
Docker container rather than directly on the host OS, giving process-level
isolation with:

* ``--network=none`` — no outbound network access from inside the container
* ``--memory=256m`` / ``--cpus=1`` — resource caps
* The active sandbox workspace bind-mounted at ``/workspace``

When Docker is not installed or the daemon is not running, the backend
falls back **transparently** to host-process execution (identical to the
previous behavior), so the rest of the codebase never needs to handle
Docker's absence.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from typing import NamedTuple


class ContainerResult(NamedTuple):
    """Unified result type for both container and host-fallback execution."""

    stdout: str
    stderr: str
    returncode: int


class DockerSandboxBackend:
    """Execute commands in an ephemeral Docker container.

    Uses ``docker run --rm`` so the container is automatically removed after
    each command. When Docker is unavailable the identical host-subprocess
    path is taken — callers see no behavioral difference.

    Usage::

        backend = DockerSandboxBackend()
        result = backend.execute_command("python --version", cwd="/tmp/workspace")
        print(result.stdout)
    """

    DEFAULT_IMAGE: str = "python:3.11-slim"
    TIMEOUT: int = 60  # seconds

    def __init__(self, image: str = DEFAULT_IMAGE) -> None:
        self.image = image
        self._available: bool | None = None  # Lazily cached

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` if the Docker CLI is on PATH and the daemon responds."""
        if self._available is not None:
            return self._available

        if shutil.which("docker") is None:
            self._available = False
            return False

        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            self._available = result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            self._available = False

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
        """
        if not self.is_available():
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


# ---------------------------------------------------------------------------
# Module-level singleton and public entry point
# ---------------------------------------------------------------------------

_backend: DockerSandboxBackend | None = None


def get_backend() -> DockerSandboxBackend:
    """Return the module-level :class:`DockerSandboxBackend` singleton."""
    global _backend
    if _backend is None:
        _backend = DockerSandboxBackend()
    return _backend


def execute_sandboxed(command: str, cwd: str | None = None) -> ContainerResult:
    """Public entry point: run *command* in a container (or host fallback).

    Args:
        command: Shell command string.
        cwd: Working directory (host path, bind-mounted into container).

    Returns:
        :class:`ContainerResult`.
    """
    return get_backend().execute_command(command, cwd)
