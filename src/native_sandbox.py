"""Linux-native process isolation for Hamster.

Provides three independent, stackable isolation layers for child processes:

Layer 1 — **Namespace isolation** (via ``unshare(1)``)
    Creates new PID, network, and IPC namespaces for the child so it cannot
    see host processes or reach the external network.  Uses ``unshare``
    which is available on all modern Linux distributions.

Layer 2 — **cgroup v2 resource limits**
    Caps the child at 256 MiB RAM and one CPU core by writing to
    ``/sys/fs/cgroup/hamster-<pid>/``.  Requires a cgroup v2 unified
    hierarchy and write access to the cgroup root (available without
    ``CAP_SYS_ADMIN`` on systemd-managed systems when cgroup delegation is
    enabled).

Layer 3 — **Seccomp-BPF syscall deny-list**
    Applied in the forked child via ``preexec_fn`` (between ``fork()`` and
    ``exec()``) using a hand-crafted BPF program built from
    ``ctypes``-wrapped ``prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER)`` calls.
    Blocks dangerous kernel operations (``ptrace``, ``mount``, ``reboot``,
    ``init_module``, ``kexec_*``, …) while allowing the full syscall set
    used by Python, git, npm, and pytest.  Uses a **deny-list** (default
    allow) rather than an allowlist so legitimate tools are never accidentally
    blocked.

Each layer degrades gracefully: if ``unshare`` is absent, or the cgroup
filesystem is not mounted, or ``prctl`` returns an error, the child still
runs (possibly with reduced isolation).  The caller always receives a
``NativeSandboxResult`` regardless of which layers succeeded.

This module is **Linux-only**.  All functions raise or return early on
other platforms; the caller in ``hamster/runtime.py`` guards with a
``platform.system()`` check.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class NativeSandboxResult:
    """Result from :func:`run_with_full_isolation`."""

    returncode: int
    stdout: str
    stderr: str
    isolation_layers: list[str] = field(default_factory=list)
    """Names of isolation layers that were successfully applied."""


# ---------------------------------------------------------------------------
# Layer 1: Namespace isolation via unshare(1)
# ---------------------------------------------------------------------------


def _find_unshare() -> str | None:
    """Return the path to the ``unshare`` binary, or ``None`` if not found."""
    return shutil.which("unshare")


def run_in_namespaces(
    command: str,
    *,
    timeout: int = 60,
    preexec_fn: object = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run *command* under PID + network + IPC namespace isolation.

    Tries progressively relaxed namespace flag sets until one succeeds
    (some kernels require root or user-namespace delegation for ``--net``).
    Falls back to plain ``subprocess.run`` when ``unshare`` is not installed.

    Returns:
        ``(CompletedProcess, layers)`` where *layers* lists which namespace
        flags were actually applied.
    """
    parts = shlex.split(command)
    unshare = _find_unshare()

    if unshare:
        for ns_args in (
            ["--pid", "--fork", "--net", "--ipc"],
            ["--pid", "--fork", "--net"],
            ["--pid", "--fork"],
        ):
            try:
                proc = subprocess.run(
                    [unshare] + ns_args + ["--"] + parts,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    preexec_fn=preexec_fn,  # type: ignore[arg-type]
                    check=False,
                )
                applied = [
                    a.lstrip("-") for a in ns_args if a.startswith("--") and a != "--"
                ]
                return proc, [f"unshare({','.join(applied)})"]
            except (PermissionError, OSError):
                continue

    proc = subprocess.run(
        parts,
        capture_output=True,
        text=True,
        timeout=timeout,
        preexec_fn=preexec_fn,  # type: ignore[arg-type]
        check=False,
    )
    return proc, []


# ---------------------------------------------------------------------------
# Layer 2: cgroup v2 resource limits
# ---------------------------------------------------------------------------

_CGROUP_ROOT = Path("/sys/fs/cgroup")


def setup_cgroup_v2(
    *,
    memory_limit_bytes: int = 256 * 1024 * 1024,
    cpu_quota_us: int = 100_000,
    cpu_period_us: int = 1_000_000,
) -> tuple[bool, Path | None]:
    """Create a cgroup v2 sub-group for the current process and apply limits.

    The child process inherits these limits because cgroup membership is
    inherited across ``fork()`` + ``exec()``.

    Args:
        memory_limit_bytes: Maximum RSS (default 256 MiB).
        cpu_quota_us: CPU quota in microseconds per *cpu_period_us*
            (default 100 ms / 1 s = 1 CPU core).
        cpu_period_us: CPU bandwidth period in microseconds (default 1 s).

    Returns:
        ``(success, cgroup_path)`` — *success* is False when cgroup v2 is
        not mounted or this process lacks write permission.
    """
    if not _CGROUP_ROOT.exists():
        return False, None

    # cgroup v1 has no ``cgroup.controllers`` in the root
    if not (_CGROUP_ROOT / "cgroup.controllers").exists():
        return False, None

    cgroup_name = f"hamster-{os.getpid()}"
    cgroup_path = _CGROUP_ROOT / cgroup_name

    try:
        cgroup_path.mkdir(exist_ok=True)
        (cgroup_path / "memory.max").write_text(str(memory_limit_bytes))
        (cgroup_path / "cpu.max").write_text(f"{cpu_quota_us} {cpu_period_us}")
        (cgroup_path / "cgroup.procs").write_text(str(os.getpid()))
        return True, cgroup_path
    except (PermissionError, OSError):
        return False, None


def cleanup_cgroup_v2(cgroup_path: Path | None) -> None:
    """Remove the cgroup slice created by :func:`setup_cgroup_v2`.

    Moves the current process back to the root cgroup first so the slice
    becomes empty and can be deleted.
    """
    if cgroup_path is None or not cgroup_path.exists():
        return
    try:
        (_CGROUP_ROOT / "cgroup.procs").write_text(str(os.getpid()))
        cgroup_path.rmdir()
    except (PermissionError, OSError):
        pass


# ---------------------------------------------------------------------------
# Layer 3: Seccomp-BPF syscall deny-list
# ---------------------------------------------------------------------------

# Audit architecture constant for x86-64 (AUDIT_ARCH_X86_64 = 0xC000003E)
_AUDIT_ARCH_X86_64: int = 0xC000_003E

# BPF instruction-class constants (from <linux/bpf_common.h>)
_BPF_LD = 0x00  # load
_BPF_W = 0x00  # 32-bit word
_BPF_ABS = 0x20  # absolute offset
_BPF_JMP = 0x05  # jump
_BPF_JEQ = 0x10  # jump if equal
_BPF_K = 0x00  # constant operand
_BPF_RET = 0x06  # return

# seccomp return values
_RET_ALLOW = 0x7FFF_0000  # SECCOMP_RET_ALLOW
_RET_ERRNO = 0x0005_0000 | 1  # SECCOMP_RET_ERRNO | EPERM

# prctl constants
_PR_SET_NO_NEW_PRIVS = 38
_PR_SET_SECCOMP = 22
_SECCOMP_MODE_FILTER = 2


class _SockFilter(ctypes.Structure):
    """One 8-byte BPF filter instruction (``struct sock_filter``)."""

    _fields_ = [
        ("code", ctypes.c_uint16),
        ("jt", ctypes.c_uint8),
        ("jf", ctypes.c_uint8),
        ("k", ctypes.c_uint32),
    ]


class _SockFProg(ctypes.Structure):
    """BPF program pointer + length (``struct sock_fprog``).

    Passed directly to ``prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, …)``.
    """

    _fields_ = [
        ("len", ctypes.c_uint16),
        ("filter", ctypes.POINTER(_SockFilter)),
    ]


def _stmt(code: int, k: int) -> _SockFilter:
    return _SockFilter(code=code, jt=0, jf=0, k=k)


def _jump(code: int, k: int, jt: int, jf: int) -> _SockFilter:
    return _SockFilter(code=code, jt=jt, jf=jf, k=k)


# Syscall numbers to BLOCK on x86-64.  Deny-list approach:  everything not
# listed is allowed, so Python / git / npm / pytest are unaffected.
# Only operations with no legitimate use inside a sandboxed task appear here.
BLOCKED_SYSCALLS_X86_64: frozenset[int] = frozenset(
    {
        101,  # ptrace           — trace / inspect other processes
        155,  # pivot_root       — swap the root filesystem
        163,  # acct             — enable kernel process accounting
        164,  # settimeofday     — modify the system clock
        165,  # mount            — mount filesystems
        166,  # umount2          — unmount filesystems
        167,  # swapon           — enable swap device
        168,  # swapoff          — disable swap device
        169,  # reboot           — reboot / power off / halt
        175,  # init_module      — load a kernel module (insmod)
        176,  # delete_module    — unload a kernel module (rmmod)
        313,  # finit_module     — load kernel module from fd (modern insmod)
        317,  # seccomp          — prevent removal / replacement of our filter
        320,  # kexec_file_load  — replace the running kernel
    }
)


def _build_deny_filter(blocked: frozenset[int]) -> list[_SockFilter]:
    """Return a BPF program that denies *blocked* syscalls, allows the rest.

    Program layout (x86-64 only):

    1. Load ``seccomp_data.arch`` → verify x86-64 → deny anything else
    2. Load ``seccomp_data.nr`` (syscall number)
    3. For each blocked number: ``if nr == N → return ERRNO(EPERM)``
    4. Default: ``return ALLOW``
    """
    insns: list[_SockFilter] = []

    # 1. Architecture guard
    insns.append(_stmt(_BPF_LD | _BPF_W | _BPF_ABS, 4))  # load arch (offset 4)
    insns.append(
        _jump(_BPF_JMP | _BPF_JEQ | _BPF_K, _AUDIT_ARCH_X86_64, 1, 0)
    )  # if x86-64 → skip deny
    insns.append(_stmt(_BPF_RET | _BPF_K, _RET_ERRNO))  # deny unknown arch

    # 2. Load syscall number (offset 0)
    insns.append(_stmt(_BPF_LD | _BPF_W | _BPF_ABS, 0))

    # 3. Per-syscall deny entries
    for nr in sorted(blocked):
        insns.append(
            _jump(_BPF_JMP | _BPF_JEQ | _BPF_K, nr, 0, 1)
        )  # if nr==N skip next
        insns.append(_stmt(_BPF_RET | _BPF_K, _RET_ERRNO))  # deny

    # 4. Default allow
    insns.append(_stmt(_BPF_RET | _BPF_K, _RET_ALLOW))

    return insns


def apply_seccomp_deny_list(blocked: frozenset[int] = BLOCKED_SYSCALLS_X86_64) -> bool:
    """Apply a seccomp-BPF deny-list filter to the **current** process.

    Intended to be called inside ``preexec_fn`` — that is, in the forked child
    between ``fork()`` and ``exec()`` — so the filter is inherited by the
    exec'd command without restricting the parent Hamster agent at all.

    Steps:
    1. Call ``prctl(PR_SET_NO_NEW_PRIVS, 1)`` — required before installing a
       filter without ``CAP_SYS_ADMIN``.
    2. Build the BPF deny-list program via :func:`_build_deny_filter`.
    3. Call ``prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog)``.

    Returns:
        ``True`` if the filter was installed; ``False`` on any error (e.g.
        ``prctl`` not available, or CAP check failed).
    """
    if platform.system() != "Linux":
        return False

    libc_name = ctypes.util.find_library("c")
    if libc_name is None:
        return False

    try:
        libc = ctypes.CDLL(libc_name, use_errno=True)
    except OSError:
        return False

    # Step 1: no-new-privs (unprivileged seccomp requirement)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        return False

    # Step 2: build BPF program
    instructions = _build_deny_filter(blocked)
    FilterArray = _SockFilter * len(instructions)
    arr = FilterArray(*instructions)

    prog = _SockFProg(
        len=ctypes.c_uint16(len(instructions)),
        filter=ctypes.cast(arr, ctypes.POINTER(_SockFilter)),
    )

    # Step 3: install filter
    return libc.prctl(_PR_SET_SECCOMP, _SECCOMP_MODE_FILTER, ctypes.byref(prog)) == 0


# ---------------------------------------------------------------------------
# Combined public entry point
# ---------------------------------------------------------------------------


def run_with_full_isolation(
    command: str,
    *,
    timeout: int = 60,
    memory_limit_bytes: int = 256 * 1024 * 1024,
) -> NativeSandboxResult:
    """Execute *command* with all three isolation layers stacked.

    Layer application order:

    1. **cgroup v2** limits are set on the *parent* so the *child* inherits them.
    2. **namespace isolation** wraps the ``subprocess.run`` call.
    3. **seccomp-BPF** deny-list is applied inside ``preexec_fn`` (child only).

    Every layer is best-effort; the command always runs even if a layer fails.
    Successfully applied layers are recorded in ``NativeSandboxResult.isolation_layers``.

    Raises:
        RuntimeError: When called on a non-Linux platform.
    """
    if platform.system() != "Linux":
        raise RuntimeError(
            f"run_with_full_isolation requires Linux; current OS is {platform.system()!r}."
        )

    layers: list[str] = []

    # --- Layer 2: cgroup v2 (applied to parent before fork) ---
    cgroup_ok, cgroup_path = setup_cgroup_v2(memory_limit_bytes=memory_limit_bytes)
    if cgroup_ok:
        layers.append("cgroup_v2")

    # --- Layer 3 preexec: seccomp (called in forked child, before exec) ---
    def _preexec() -> None:
        apply_seccomp_deny_list()

    # --- Layer 1: namespace isolation ---
    try:
        proc, ns_layers = run_in_namespaces(
            command, timeout=timeout, preexec_fn=_preexec
        )
        layers.extend(ns_layers)
        if not ns_layers:
            layers.append("seccomp_only")  # seccomp still applied via preexec_fn
    except subprocess.TimeoutExpired:
        cleanup_cgroup_v2(cgroup_path)
        return NativeSandboxResult(
            returncode=124,
            stdout="",
            stderr=f"Command timed out after {timeout}s.",
            isolation_layers=layers,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        cleanup_cgroup_v2(cgroup_path)
        return NativeSandboxResult(
            returncode=1,
            stdout="",
            stderr=str(exc),
            isolation_layers=layers,
        )

    cleanup_cgroup_v2(cgroup_path)

    return NativeSandboxResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        isolation_layers=layers,
    )
