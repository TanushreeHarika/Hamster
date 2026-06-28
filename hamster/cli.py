import sys
from pathlib import Path

from hamster.agent import initial_messages, run_agent_turn
from hamster.config import load_config
from hamster.openrouter import OpenRouterClient
from hamster.tools import configure_sandbox
from hamster.ui import clear_screen, print_exit_logo, print_help, print_logo, prompt_user


def _ensure_foundation(project_root: Path) -> None:
    (project_root / "sandbox").mkdir(exist_ok=True)
    env_path = project_root / ".env"
    if not env_path.exists():
        env_path.write_text(
            "OPENROUTER_API_KEY=\nMAX_TOKENS=4096\nMAX_FAILURES=3\n",
            encoding="utf-8",
        )


def main() -> None:
    project_root = Path.cwd()
    _ensure_foundation(project_root)
    configure_sandbox(project_root / "sandbox")
    print_logo()

    try:
        config = load_config(project_root)
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(1)

    client = OpenRouterClient(config)
    messages = initial_messages()

    print("Type /help for commands. All tools require explicit approval.\n")
    while True:
        try:
            user_input = prompt_user("[bold gold3]hamster>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print_exit_logo()
            return

        if not user_input:
            continue
        if user_input == "/exit":
            print_exit_logo()
            return
        if user_input == "/help":
            print_help()
            continue
        if user_input == "/clear":
            clear_screen()
            print_logo()
            continue
        if user_input.startswith("/search "):
            query = user_input.removeprefix("/search ").strip()
            if not query:
                print("Usage: /search <technical docs query>")
                continue
            user_input = f"Use web_search to look up technical documentation for: {query}"

        messages.append({"role": "user", "content": user_input})
        run_agent_turn(client, messages, config.max_failures)


if __name__ == "__main__":
    main()
