# Hamster

Hamster is a lightweight Python CLI software engineering agent built from scratch around OpenRouter and permission-gated sandbox tools.

## Setup

```bash
uv venv
uv pip install -e .
```

Create or update `.env`:

```bash
OPENROUTER_API_KEY=your_key_here
MAX_TOKENS=4096
MAX_FAILURES=3
```

Run:

```bash
hamster
```

All tool file access is restricted to `./sandbox/`.

## Commands

```text
/help             Show the interactive command guide
/search <query>   Ask Hamster to look up technical documentation
/clear            Clear and redraw the terminal UI
/exit             Leave Hamster
```

## Tooling

Hamster exposes five permission-gated tools to the model:

- `search_codebase(query)` searches only inside `./sandbox/`.
- `read_file(filepath)` reads only files contained by `./sandbox/`.
- `edit_file_patch(filepath, target_text, replacement_text)` previews and applies one surgical replacement inside `./sandbox/`.
- `web_search(query)` performs an approved DuckDuckGo documentation lookup.
- `run_sandbox_command(command)` runs approved, filtered commands only inside `./sandbox/`.

Sandbox path requests are resolved with absolute-path containment before user approval. Escape attempts return a security violation to the model instead of prompting.
