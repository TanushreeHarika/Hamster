"""Small, dependency-free quality checks for staged agent output.

The checks deliberately validate observable properties of generated files rather
than trusting a model's completion message.  They are not a replacement for a
project's own test suite; they provide a fast safety net when a task creates a
new artifact and no test command is available.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


@dataclass(frozen=True)
class DraftQualityReport:
    changed_files: tuple[str, ...]
    checks: tuple[str, ...]
    issues: tuple[str, ...]
    required_commands: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if not self.changed_files:
            return "No file changes to validate."
        if self.issues:
            return "Validation needs attention: " + "; ".join(self.issues)
        if self.checks:
            return "Automated validation passed: " + "; ".join(self.checks)
        return "Draft created; no applicable automated checks were available."

    def repair_instruction(self) -> str:
        return "\n".join(
            [
                "AUTOMATED QUALITY CHECK FAILED.",
                *[f"- {issue}" for issue in self.issues],
                "Fix these issues in the draft. Do not claim completion until the checks pass.",
            ]
        )


class _HTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.labels: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "label" and attributes.get("for"):
            self.labels.add(attributes["for"] or "")


def _changed_files(workspace: Path, baseline: Path) -> list[Path]:
    def files(root: Path) -> set[Path]:
        return {
            item.relative_to(root)
            for item in root.rglob("*")
            if item.is_file()
        }

    changed: list[Path] = []
    baseline_files = files(baseline)
    workspace_files = files(workspace)
    for relative in sorted(baseline_files | workspace_files):
        before = baseline / relative
        after = workspace / relative
        if relative not in baseline_files or relative not in workspace_files:
            changed.append(relative)
        elif before.read_bytes() != after.read_bytes():
            changed.append(relative)
    return changed


def _check_html(request: str, html: str, script: str) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    issues: list[str] = []
    requested = request.lower()
    parser = _HTMLInspector()
    parser.feed(html)
    tags = {tag for tag, _ in parser.tags}
    attributes = [attrs for _, attrs in parser.tags]

    if not re.search(r"<!doctype\s+html", html, re.IGNORECASE):
        issues.append("HTML document is missing an HTML5 doctype")
    elif not {"html", "head", "body"}.issubset(tags):
        issues.append("HTML document is missing html, head, or body structure")
    else:
        checks.append("document structure")

    if "responsive" in requested:
        if not any((item.get("name") or "").lower() == "viewport" for item in attributes):
            issues.append("responsive request is missing a viewport meta tag")
        else:
            checks.append("viewport")

    billing_requested = all(word in requested for word in ("monthly", "yearly"))
    if billing_requested:
        controls = [
            attrs
            for tag, attrs in parser.tags
            if tag in {"input", "button"}
            and re.search(r"monthly|yearly|billing|annual", " ".join(str(v or "") for v in attrs.values()), re.I)
        ]
        if not controls:
            issues.append("monthly/yearly request has no identifiable billing control")
        else:
            hidden_controls = [
                control
                for control in controls
                if re.search(r"(^|\s)hidden(\s|$)", control.get("class") or "", re.I)
            ]
            if hidden_controls:
                issues.append("billing control is display-hidden and cannot receive keyboard focus")
            elif any(
                control.get("aria-label")
                or control.get("id") in parser.labels
                or control.get("type") != "checkbox"
                for control in controls
            ):
                checks.append("accessible billing control")

        script_lower = script.lower()
        updates_billing = (
            re.search(r"(?:textcontent|innertext|innerhtml).*?(?:month|year|annual|billing)", script_lower, re.S)
            or re.search(r"(?:month|year|annual|billing).*?(?:textcontent|innertext|innerhtml)", script_lower, re.S)
            or re.search(r"(?:data-|dataset\.)(?:month|year|annual|billing|period)", script_lower)
        )
        if not updates_billing:
            issues.append("billing control does not update a price or billing-period value")
        else:
            checks.append("billing-price interaction")

        if "dataset.theme" in script_lower and not updates_billing:
            issues.append("billing control is changing the theme instead of billing prices")

    if "dark mode" in requested:
        theme_signals = re.search(r"data-theme|classlist\.(?:add|remove|toggle).*dark|prefers-color-scheme", html + script, re.I)
        style_signals = re.findall(r"\[data-theme(?:=[^\]]+)?\]|\.dark\b|prefers-color-scheme", html, re.I)
        if not theme_signals or not style_signals:
            issues.append("dark-mode request has no complete theme behavior and styling path")
        elif len(style_signals) == 1 and "data-theme" in (html + script).lower():
            issues.append("dark mode changes only one selector; component colors are not fully themed")
        else:
            checks.append("dark-mode styling")

    return checks, issues


def _project_verification_commands(workspace: Path, changed: list[Path]) -> tuple[str, ...]:
    """Return relevant, non-destructive checks that the agent must request.

    Commands are only proposed here. They still go through the existing
    ``run_sandbox_command`` tool, including its approval and sandbox policy.
    """
    suffixes = {path.suffix.lower() for path in changed}
    commands: list[str] = []
    if suffixes & {".py", ".pyi"} and (workspace / "tests").is_dir():
        if (workspace / "uv.lock").exists():
            commands.append("uv run pytest -q")
        else:
            commands.append("pytest -q")

    js_files = [
        path
        for path in changed
        if path.suffix.lower() in {".js", ".mjs", ".cjs"}
        and (workspace / path).is_file()
    ]
    commands.extend(f"node --check {path}" for path in js_files)

    package_path = workspace / "package.json"
    if suffixes & {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css"} and package_path.is_file():
        try:
            scripts = json.loads(package_path.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            scripts = {}
        for name in ("test", "lint", "build"):
            if isinstance(scripts, dict) and isinstance(scripts.get(name), str):
                commands.append(f"npm run {name}")
    return tuple(dict.fromkeys(commands))


def evaluate_pending_draft(
    request: str, completed_commands: set[str] | None = None
) -> DraftQualityReport:
    """Evaluate staged, text-based artifacts for the current user request.

    A missing sandbox is intentionally reported as an unavailable check rather
    than a failure so agent unit tests and text-only tasks remain usable.
    """
    try:
        from hamster.tools import _get_sandbox

        sandbox = _get_sandbox()
    except RuntimeError:
        return DraftQualityReport((), (), ())

    changed = _changed_files(sandbox.workspace, sandbox.baseline)
    required_commands = _project_verification_commands(sandbox.workspace, changed)
    completed_commands = completed_commands or set()
    checks: list[str] = []
    issues: list[str] = []
    html_files = [path for path in changed if path.suffix.lower() in {".html", ".htm"}]

    for relative in changed:
        path = sandbox.workspace / relative
        if not path.exists() or not path.is_file():
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if path.suffix.lower() in {".js", ".mjs", ".cjs"}:
            checks.append(f"UTF-8 JavaScript: {relative}")

    for relative in html_files:
        path = sandbox.workspace / relative
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        external_script = "\n".join(
            child.read_text(encoding="utf-8", errors="replace")
            for child in sandbox.workspace.rglob("*")
            if child.is_file() and child.suffix.lower() in {".js", ".mjs", ".cjs"}
        )
        inline_script = "\n".join(
            re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, re.IGNORECASE | re.DOTALL)
        )
        script = external_script + "\n" + inline_script
        file_checks, file_issues = _check_html(request, html, script)
        checks.extend(f"{relative}: {check}" for check in file_checks)
        issues.extend(f"{relative}: {issue}" for issue in file_issues)

    for command in required_commands:
        if command in completed_commands:
            checks.append(f"verification command: {command}")
        else:
            issues.append(f"run verification command: {command}")

    return DraftQualityReport(
        tuple(str(path) for path in changed),
        tuple(dict.fromkeys(checks)),
        tuple(dict.fromkeys(issues)),
        required_commands,
    )
