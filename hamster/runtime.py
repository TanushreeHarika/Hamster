"""Runtime orchestration skeleton for Hamster.

Provides an extensible `RuntimeOrchestrator` interface with simple stubs for
native and container execution drivers. These are placeholders that define the
expected surface area for launching sandboxed processes.
"""
from __future__ import annotations

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

    def launch_native(self, command: str, *, cwd: str | None = None, timeout: int | None = None) -> ExecutionResult:
        """Launch a command using the host OS primitives (namespaces/cgroups).

        This is a stub to be replaced with a proper implementation that sets up
        namespaces, seccomp, cgroups, and PTY allocation as required.
        """
        raise NotImplementedError("launch_native is not implemented yet")

    def launch_container(self, image: str, command: str, *, timeout: int | None = None) -> ExecutionResult:
        """Launch *command* inside an ephemeral Docker container.

        Delegates to :func:`src.container.execute_sandboxed` which uses
        ``docker run --rm`` with ``--network=none`` and resource caps.
        Falls back to host execution transparently when Docker is unavailable.
        """
        try:
            from src.container import DockerSandboxBackend
        except ImportError:
            raise RuntimeError("src.container module not found")

        backend = DockerSandboxBackend(image=image)
        result = backend.execute_command(command, cwd=None)
        return ExecutionResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            meta={"image": image, "docker_available": backend.is_available()},
        )
