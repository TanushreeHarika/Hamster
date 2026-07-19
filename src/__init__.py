"""Optional intelligence extensions for Hamster.

These modules are intentionally isolated so the existing runtime remains stable.
"""

from .context import CompactContextManager, estimate_tokens
from .lsp import LSPBridge
from .security import PathSecurityViolation, assert_sandbox_path, canonicalize_path
from .transactions import FileSnapshot, TransactionManager

__all__ = [
    "CompactContextManager",
    "FileSnapshot",
    "LSPBridge",
    "PathSecurityViolation",
    "TransactionManager",
    "assert_sandbox_path",
    "canonicalize_path",
    "estimate_tokens",
]
