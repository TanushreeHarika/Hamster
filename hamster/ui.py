from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


console = Console()


HAMSTER_LOGO = """⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡿⡛⠾⢛⢿⠞⠝⠫⠯⢟⠿⢿⣿⢟⠛⡻⢿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⡿⡫⢠⡂⣿⣦⣩⣥⣴⣷⣿⢠⢀⣍⡒⣰⡖⣤⡑⠝⣿⣿⣿⣿
⣿⣿⣿⣟⠑⢰⡿⣣⣿⣿⣿⣿⣿⣿⣿⣶⣿⣿⣿⣿⣜⢿⣷⠈⢹⣿⣿⣿
⣿⣿⣿⣿⠠⢈⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡝⢠⣸⣿⣿⣿
⣿⣿⣯⢦⢁⣾⣿⣿⡟⠒⢻⣿⣿⣿⣿⣿⣿⡒⠻⣿⣿⣿⣿⡈⡼⣿⣿⣿
⣿⣿⡫⢡⣾⣟⣕⢸⡤⣦⣾⣿⣟⣋⣛⣿⣿⣤⣂⣗⠰⡽⣿⣷⡐⠝⣿⣿
⣿⠧⢡⣿⣿⣟⠿⢿⣳⣿⣿⡿⢟⡻⠿⢿⡻⣿⣟⠿⢿⣳⣿⣿⣷⠘⢹⣿
⣿⣽⠸⣿⣿⣿⣿⣿⣿⠇⣶⣥⢸⣿⢱⣿⣇⡿⣿⣿⣿⣿⣿⣿⣿⠃⢿⣿
⣿⡇⠂⣹⣿⣿⣿⣿⡏⢤⣬⢋⡅⠀⠉⢫⣶⡶⢺⣿⣿⣿⣿⣿⣿⠀⢾⣿
⣿⡇⠃⣿⣿⣿⣿⣟⠣⠶⠶⡀⠀⠀⠀⢰⣷⣯⡸⣿⣿⣿⣿⣿⣿⡐⣸⣿
⣿⠹⢸⣿⣿⣿⣿⣿⣿⢸⣼⢷⣠⡄⣦⢻⣦⣀⣼⣿⣿⣿⣿⣿⣿⡇⢁⣿
⣵⡆⣾⣿⣿⣿⣿⣭⡭⣈⣄⠌⠙⡁⣭⣤⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⢸⢻
⣿⡇⣿⣿⣿⣿⣿⡡⠴⢆⣾⠡⣀⡁⠰⡭⠽⠿⢿⣛⣿⣿⣿⣿⣿⣿⢸⢸
⣿⠃⢹⣿⣿⣿⣿⣿⣶⣦⣤⣯⣽⣶⠀⢻⣿⣿⣿⣿⣿⣿⣿⣿⣿⡏⢸⣾
⣿⡞⡈⢻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁⢈⢸
⣿⣿⣔⠀⢽⡻⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⢁⢔⣴⣿
⣿⣿⣿⣿⣄⠌⠛⣲⠾⠿⢿⣷⣶⠿⠶⠯⠭⠿⠛⠛⣻⠋⡁⢔⣵⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣕⡌⢨⣔⣶⣶⣶⣶⣬⣥⣤⣤⣢⣭⣅⣪⣾⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿"""

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def print_logo() -> None:
    console.print(Text(HAMSTER_LOGO, style="bold gold3"))
    metrics = Table.grid(padding=(0, 2))
    metrics.add_column(style="bold white")
    metrics.add_column(style="dim")
    metrics.add_row("Hamster", "sandboxed OpenRouter engineering agent")
    metrics.add_row("Tools", "search_codebase | read_file | edit_file_patch | web_search | run_sandbox_command")
    metrics.add_row("Boundary", "./sandbox only for file operations")
    metrics.add_row("Approval", "hard y/n gate before allowed tool and network actions")
    console.print(Panel(metrics, border_style="gold3", title="Ready", title_align="left"))


def print_help() -> None:
    table = Table(title="Hamster Commands", border_style="cyan")
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Action", style="white")
    table.add_row("/help", "Show this command guide")
    table.add_row("/search <query>", "Ask Hamster to search technical documentation")
    table.add_row("/clear", "Clear the terminal and redraw the splash")
    table.add_row("/exit", "Leave Hamster")
    console.print(table)


def render_action_summary(action: str, details: Mapping[str, str]) -> None:
    table = Table(title="Requested Tool Action", border_style="magenta")
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white", overflow="fold")
    table.add_row("Action", action)
    for key, value in details.items():
        table.add_row(key, value)
    console.print(table)


def render_files_summary(rows: Sequence[Mapping[str, str]]) -> None:
    table = Table(title="Files Touched", border_style="cyan")
    table.add_column("Operation", style="bold")
    table.add_column("Path", style="white", overflow="fold")
    table.add_column("Scope", style="dim")
    for row in rows:
        table.add_row(row.get("operation", ""), row.get("path", ""), row.get("scope", "sandbox"))
    console.print(table)


def render_diff(filepath: str, diff_lines: Sequence[str]) -> None:
    body = Text()
    for line in diff_lines:
        style = "white"
        if line.startswith("+") and not line.startswith("+++"):
            style = "bold green"
        elif line.startswith("-") and not line.startswith("---"):
            style = "bold red"
        elif line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
            style = "bold cyan"
        body.append(line + "\n", style=style)
    console.print(Panel(body, title=f"Patch Preview: {filepath}", border_style="cyan"))


def render_security_violation(message: str) -> None:
    console.print(Panel(message, title="Security Violation", border_style="bold red", style="red"))


def render_tool_result(name: str, content: str) -> None:
    console.print(Panel(content, title=f"tool:{name}", border_style="green"))


def render_model_error(message: str) -> None:
    console.print(Panel(message, title="Model Error", border_style="red"))


def print_assistant_delta(text: str) -> None:
    console.print(text, end="", markup=False, highlight=False)


def prompt_user(prompt: str) -> str:
    return console.input(prompt)


def status(message: str):
    return console.status(message, spinner="dots", spinner_style="gold3")


def confirm(prompt: str) -> bool:
    while True:
        answer = prompt_user(f"[bold gold3]{prompt}[/] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("Please answer y or n.", style="yellow")
