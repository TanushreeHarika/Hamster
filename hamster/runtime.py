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
        """Launch inside a container or microVM (gVisor/Firecracker).

        Stub for future microVM/container driver integration.
        """
        raise NotImplementedError("launch_container is not implemented yet")
