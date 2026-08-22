"""Runtime orchestration skeleton for Hamster.

Provides an extensible `RuntimeOrchestrator` interface with simple stubs for
native and container execution drivers. These are placeholders that define the
expected surface area for launching sandboxed processes.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    meta: Dict[str, Any] | None = None


class RuntimeOrchestrator:
    def __init__(self) -> None:
        pass

    def launch_native(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Launch *command* using Linux-native namespace + cgroup + seccomp isolation.

        Stacks three independent isolation layers via :mod:`src.native_sandbox`:

        1. **cgroup v2** — caps RAM at 256 MiB and CPU at 1 core by writing to
           ``/sys/fs/cgroup/hamster-<pid>/`` (best-effort; skipped if cgroup v2
           is not mounted or write permission is denied).
        2. **Namespace isolation** (``unshare --pid --fork --net --ipc``) —
           new PID, network, and IPC namespaces prevent the child from seeing
           host processes or reaching the external network.
        3. **Seccomp-BPF deny-list** — applied in the forked child via
           ``preexec_fn``; blocks ``ptrace``, ``mount``, ``reboot``,
           ``init_module``, ``kexec_*``, and similar dangerous syscalls while
           allowing the full set needed by Python, git, npm, and pytest.

        Each layer degrades gracefully.  The command always runs; successfully
        applied layers are reported in ``ExecutionResult.meta['isolation_layers']``.

        Raises:
            NotImplementedError: On non-Linux platforms.  Use
                :meth:`launch_container` for Docker-based isolation instead.
        """
        if platform.system() != "Linux":
            raise NotImplementedError(
                f"launch_native requires Linux; current platform is {platform.system()!r}. "
                "Use launch_container() for Docker-based isolation on this OS."
            )

        try:
            from src.native_sandbox import run_with_full_isolation
        except ImportError as exc:
            raise RuntimeError(f"src.native_sandbox module not found: {exc}") from exc

        result = run_with_full_isolation(
            command,
            timeout=timeout or 60,
        )
        return ExecutionResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            meta={
                "isolation": "linux_native",
                "isolation_layers": result.isolation_layers,
            },
        )

    def launch_container(
        self,
        image: str,
        command: str,
        *,
        timeout: int | None = None,
        require_isolation: bool = False,
    ) -> ExecutionResult:
        """Launch *command* inside an ephemeral Docker container.

        Delegates to :class:`src.container.DockerSandboxBackend` which uses
        ``docker run --rm`` with ``--network=none`` and resource caps.

        Args:
            image: Docker image to run (e.g. ``'python:3.11-slim'``).
            command: Shell command string to execute inside the container.
            timeout: Command timeout in seconds (currently advisory; the
                backend's internal ``TIMEOUT`` constant governs actual limits).
            require_isolation: When ``True``, raise
                :class:`src.container.IsolationError` if Docker is unavailable
                rather than falling back to host execution.  Defaults to
                ``False`` for backward compatibility.

        Returns:
            :class:`ExecutionResult` with stdout, stderr, exit_code, and meta.
        """
        try:
            from src.container import DockerSandboxBackend
        except ImportError:
            raise RuntimeError("src.container module not found")

        backend = DockerSandboxBackend(image=image, require_isolation=require_isolation)
        result = backend.execute_command(command, cwd=None)
        return ExecutionResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            meta={
                "image": image,
                "docker_available": backend.is_available(),
                "require_isolation": require_isolation,
            },
        )
