"""Tree-sitter AST index for Hamster.

Builds a lightweight, repo-wide symbol graph from parsed Python source code
using the ``tree-sitter`` library.  Falls back transparently to a fast regex
scanner when ``tree-sitter`` / ``tree-sitter-python`` are not installed,
providing equivalent (but less precise) results with no crash and no import
error.

Public API
----------
::

    index = ASTIndex.from_file("hamster/agent.py")
    index = ASTIndex.from_directory("/path/to/project")

    defs:    list[SymbolDef] = index.definitions("run_agent_turn")
    callers: list[CallSite]  = index.callers("confirm")
    imports: list[ImportInfo] = index.imports()
    print(index.summary())

To install the optional Tree-sitter backend::

    pip install tree-sitter tree-sitter-python
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public data-classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolDef:
    """A function / class / constant definition found in source."""
    name: str
    path: str
    line: int           # 1-indexed
    column: int         # 0-indexed character offset within the line
    kind: str           # "function" | "class" | "assignment"
    docstring: str = ""


@dataclass
class CallSite:
    """A location in source where a given symbol is called."""
    callee: str
    path: str
    line: int
    column: int


@dataclass
class ImportInfo:
    """A single import statement."""
    module: str
    names: list[str] = field(default_factory=list)
    path: str = ""
    line: int = 0


# ---------------------------------------------------------------------------
# Main index class
# ---------------------------------------------------------------------------

class ASTIndex:
    """Repository-wide symbol index.

    Automatically selects the Tree-sitter backend when available; otherwise
    uses the built-in regex scanner.

    Usage::

        # Single file
        idx = ASTIndex.from_file("hamster/agent.py")

        # Entire project (skips ignored dirs, caps at max_files)
        idx = ASTIndex.from_directory("/path/to/project")

        # Query
        for d in idx.definitions("run_agent_turn"):
            print(f"{d.path}:{d.line}  [{d.kind}]  {d.docstring[:80]}")
    """

    # Default directories to skip when walking a project
    IGNORE_DIRS: frozenset[str] = frozenset({
        ".git", ".hg", ".svn",
        ".venv", "venv",
        "__pycache__",
        ".mypy_cache", ".ruff_cache", ".pytest_cache",
        "node_modules", "dist", "build", "sandbox",
    })

    def __init__(self) -> None:
        self._defs: dict[str, list[SymbolDef]] = {}
        self._calls: dict[str, list[CallSite]] = {}
        self._imports: list[ImportInfo] = []
        self._files_indexed: int = 0
        self._backend: str = "none"

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> "ASTIndex":
        """Build an index for a single source file."""
        idx = cls()
        idx._index_file(Path(path))
        return idx

    @classmethod
    def from_directory(
        cls,
        root: str | Path,
        *,
        max_files: int = 500,
    ) -> "ASTIndex":
        """Walk *root* and index every ``*.py`` file (up to *max_files*)."""
        idx = cls()
        root_path = Path(root)
        count = 0
        for path in sorted(root_path.rglob("*.py")):
            if any(part in cls.IGNORE_DIRS for part in path.parts):
                continue
            if count >= max_files:
                break
            try:
                idx._index_file(path)
                count += 1
            except Exception:
                continue
        idx._files_indexed = count
        return idx

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def definitions(self, symbol: str) -> list[SymbolDef]:
        """Return all definition sites for *symbol*."""
        return list(self._defs.get(symbol, []))

    def callers(self, symbol: str) -> list[CallSite]:
        """Return all call sites where *symbol* is called."""
        return list(self._calls.get(symbol, []))

    def imports(self) -> list[ImportInfo]:
        """Return all import statements found across indexed files."""
        return list(self._imports)

    @property
    def files_indexed(self) -> int:
        return self._files_indexed

    @property
    def backend(self) -> str:
        """The active parsing backend: ``'tree_sitter'`` or ``'regex'``."""
        return self._backend

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary dict of the index."""
        return {
            "backend": self._backend,
            "files_indexed": self._files_indexed,
            "unique_symbols_defined": len(self._defs),
            "total_call_sites": sum(len(v) for v in self._calls.values()),
            "total_imports": len(self._imports),
        }

    # ------------------------------------------------------------------
    # Per-file dispatch
    # ------------------------------------------------------------------

    def _index_file(self, path: Path) -> None:
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            self._index_with_tree_sitter(source, path)
        except ImportError:
            self._index_with_regex(source, path)
        self._files_indexed = max(self._files_indexed, 1)

    # ------------------------------------------------------------------
    # Backend A: Tree-sitter
    # ------------------------------------------------------------------

    def _index_with_tree_sitter(self, source: str, path: Path) -> None:
        """Parse *source* with tree-sitter and walk the AST.

        Raises ``ImportError`` when ``tree-sitter`` or ``tree-sitter-python``
        are not installed (triggers regex fallback in the caller).
        """
        # Both packages are optional — propagate ImportError if absent.
        try:
            from tree_sitter import Language, Parser       # type: ignore[import]
            import tree_sitter_python as tspython          # type: ignore[import]
        except ImportError:
            raise

        py_lang = Language(tspython.language())
        parser = Parser(py_lang)

        self._backend = "tree_sitter"
        src_bytes = source.encode("utf-8")
        tree = parser.parse(src_bytes)
        self._ts_walk(tree.root_node, src_bytes, str(path))

    def _ts_walk(self, node: Any, src: bytes, filepath: str) -> None:
        """Recursively walk a Tree-sitter AST node and record symbols."""
        t = node.type

        if t == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = src[name_node.start_byte : name_node.end_byte].decode("utf-8")
                body = node.child_by_field_name("body")
                doc = self._ts_docstring(body, src)
                self._add_def(SymbolDef(
                    name=name,
                    path=filepath,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                    kind="function",
                    docstring=doc,
                ))

        elif t == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = src[name_node.start_byte : name_node.end_byte].decode("utf-8")
                body = node.child_by_field_name("body")
                doc = self._ts_docstring(body, src)
                self._add_def(SymbolDef(
                    name=name,
                    path=filepath,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                    kind="class",
                    docstring=doc,
                ))

        elif t == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                raw = src[func_node.start_byte : func_node.end_byte].decode("utf-8")
                # For attribute access (e.g. ``obj.method``), use only method name
                callee = raw.rsplit(".", 1)[-1] if "." in raw else raw
                self._add_call(CallSite(
                    callee=callee,
                    path=filepath,
                    line=node.start_point[0] + 1,
                    column=node.start_point[1],
                ))

        elif t == "import_statement":
            names = [
                src[c.start_byte : c.end_byte].decode("utf-8")
                for c in node.children
                if c.type in ("dotted_name", "aliased_import")
            ]
            self._imports.append(ImportInfo(module="", names=names, path=filepath,
                                            line=node.start_point[0] + 1))

        elif t == "import_from_statement":
            mod_node = node.child_by_field_name("module_name")
            module = (
                src[mod_node.start_byte : mod_node.end_byte].decode("utf-8")
                if mod_node else ""
            )
            names = [
                src[c.start_byte : c.end_byte].decode("utf-8")
                for c in node.children
                if c.type == "dotted_name" and c is not mod_node
            ]
            self._imports.append(ImportInfo(module=module, names=names, path=filepath,
                                            line=node.start_point[0] + 1))

        for child in node.children:
            self._ts_walk(child, src, filepath)

    @staticmethod
    def _ts_docstring(body_node: Any | None, src: bytes) -> str:
        """Extract the first string literal from a function/class body as docstring."""
        if body_node is None:
            return ""
        for child in body_node.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        raw = src[sub.start_byte : sub.end_byte].decode("utf-8", errors="replace")
                        return raw.strip("\"' \t\n")
        return ""

    # ------------------------------------------------------------------
    # Backend B: Regex (fallback)
    # ------------------------------------------------------------------

    # Match ``def name`` and ``class name``
    _DEF_RE = re.compile(
        r"^(?P<indent>\s*)(?P<kind>def|class)\s+(?P<name>\w+)\s*[:(]",
        re.MULTILINE,
    )
    # Match SCREAMING_SNAKE_CASE module-level constants
    _CONST_RE = re.compile(r"^(?P<name>[A-Z_][A-Z0-9_]{2,})\s*=\s*", re.MULTILINE)
    # Match any call expression ``word(``
    _CALL_RE = re.compile(r"\b(?P<name>[a-zA-Z_]\w*)\s*\(")
    # Match import / from…import lines
    _IMPORT_RE = re.compile(
        r"^(?:from\s+(?P<module>[\w.]+)\s+)?import\s+(?P<names>[^\n#]+)",
        re.MULTILINE,
    )

    # Keywords that look like calls but are control-flow
    _KEYWORD_CALLS: frozenset[str] = frozenset({
        "if", "while", "for", "with", "return", "print", "raise", "assert",
        "del", "yield", "lambda", "not", "and", "or", "in", "is",
        "True", "False", "None",
    })

    def _index_with_regex(self, source: str, path: Path) -> None:
        """Regex-based symbol extraction (fallback when tree-sitter is absent)."""
        if self._backend not in ("tree_sitter",):
            self._backend = "regex"
        filepath = str(path)

        # --- Definitions ---
        for m in self._DEF_RE.finditer(source):
            kind = "function" if m.group("kind") == "def" else "class"
            line = source[: m.start()].count("\n") + 1
            self._add_def(SymbolDef(
                name=m.group("name"),
                path=filepath,
                line=line,
                column=len(m.group("indent")),
                kind=kind,
            ))

        for m in self._CONST_RE.finditer(source):
            line = source[: m.start()].count("\n") + 1
            self._add_def(SymbolDef(
                name=m.group("name"),
                path=filepath,
                line=line,
                column=0,
                kind="assignment",
            ))

        # --- Call sites ---
        for line_no, line_text in enumerate(source.splitlines(), start=1):
            # Strip comments and strings for a rough approximation
            stripped = re.sub(r"#.*", "", line_text)
            for m in self._CALL_RE.finditer(stripped):
                name = m.group("name")
                if name in self._KEYWORD_CALLS:
                    continue
                self._add_call(CallSite(
                    callee=name,
                    path=filepath,
                    line=line_no,
                    column=m.start(),
                ))

        # --- Imports ---
        for m in self._IMPORT_RE.finditer(source):
            line = source[: m.start()].count("\n") + 1
            names_raw = m.group("names") or ""
            names = [n.strip().split(" as ")[0].strip() for n in names_raw.split(",") if n.strip()]
            self._imports.append(ImportInfo(
                module=m.group("module") or "",
                names=names,
                path=filepath,
                line=line,
            ))

    # ------------------------------------------------------------------
    # Internal accumulator helpers
    # ------------------------------------------------------------------

    def _add_def(self, sym: SymbolDef) -> None:
        self._defs.setdefault(sym.name, []).append(sym)

    def _add_call(self, call: CallSite) -> None:
        self._calls.setdefault(call.callee, []).append(call)


# ---------------------------------------------------------------------------
# Convenience module-level functions
# ---------------------------------------------------------------------------

def index_file(path: str | Path) -> ASTIndex:
    """Build an :class:`ASTIndex` for a single Python file."""
    return ASTIndex.from_file(path)


def index_directory(root: str | Path, *, max_files: int = 500) -> ASTIndex:
    """Build an :class:`ASTIndex` for all Python files under *root*."""
    return ASTIndex.from_directory(root, max_files=max_files)
