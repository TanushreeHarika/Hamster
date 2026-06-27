# Hamster Progress

## Built In This Initial Pass

- Created a `uv` virtual environment at `.venv/`.
- Added a lightweight Python package with a `hamster` console command.
- Added `.env` handling for `OPENROUTER_API_KEY`, `MAX_TOKENS`, and `MAX_FAILURES`.
- Created a dedicated `./sandbox/` directory for all agent file operations.
- Implemented exactly three model-exposed tools:
  - `search_codebase(query: str)`
  - `read_file(filepath: str)`
  - `edit_file_patch(filepath: str, target_text: str, replacement_text: str)`
- Added hard terminal `y/n` approval gates before every tool execution.
- Added path containment checks so reads and edits stay physically inside `./sandbox/`.
- Added `rg`-backed code search scoped to `./sandbox/`.
- Added a streaming OpenRouter chat loop with tool-call handling.
- Added self-healing error feedback: tool failures are returned to the model as tool results.
- Added `/help`, `/clear`, and `/exit` commands.
- Added the required Hamster Unicode splash art on CLI startup.

## Upgrades Added In The Hardening Pass

- Added `rich`-powered terminal rendering for a more polished developer UX.
- Added a startup metrics panel below the Hamster splash art.
- Added visual command help with `/help`.
- Added `/search <query>` for documentation lookup requests.
- Added `web_search(query: str)` using DuckDuckGo snippets with a hard `y/n` network approval gate.
- Added absolute-path containment via `os.path.abspath()` for sandbox file targets.
- Added pre-approval security violation returns for sandbox escape attempts.
- Added colored unified diff previews before `edit_file_patch` applies a change.
- Added files-touched summary tables before read, search, and patch approvals.
- Added live status spinners for model waits, local sandbox checks, patch application, and web searches.
- Added a terminal command blacklist guard for the sandbox command subsystem, including blocked `sudo`, `rm`, `chmod`, `chown`, and pipe-to-interpreter download patterns.
- Exposed `run_sandbox_command(command: str)` as a sandbox-only, security-filtered, approval-gated terminal tool.
- Split orchestration into `hamster/agent.py` while keeping `hamster/cli.py` as the activation entry point.

## Left To Do

- Add automated tests for path containment, patch edits, and OpenRouter tool-call parsing.
- Add richer transcript persistence and resumable sessions.
- Add package distribution docs for user-level installation with `uv tool install`.
