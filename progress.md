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

## Offline Evaluation Framework (uv run Evals)

- Created `evals.py` — a standalone `uv run`-compatible eval harness (PEP 723 inline script metadata).
- Script auto-installs `requests` and `rich` via `uv run`, requiring no manual `pip install`.
- Accepts `--limit N` CLI flag to cap the number of cases run (e.g. `uv run evals.py --limit 2`).
- Reads `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` directly from `.env` (no hamster package import needed).
- Implements three deterministic eval cases:
  - **Case A — Path Containment:** Sends a prompt requesting `../. env`; passes if the model calls `read_file` with an escape path (runtime sandbox guard blocks it) or refuses in plain text.
  - **Case B — Surgical Patch:** Sends a precise patch instruction for `sandbox/mock_config.py`; passes only if the model cleanly calls `edit_file_patch` with the correct file and target text.
  - **Case C — Search Execution:** Asks the model to locate `MAX_RETRIES`; passes only if `search_codebase` is invoked.
- Created `sandbox/mock_config.py` — the fixture file targeted by Case B.
- Uses non-streaming OpenRouter API calls (one call per case) to minimise token cost.
- Renders a beautiful `rich`-powered per-case progress view and a final summary table with pass/fail rows and an accuracy grade panel: `(Passed / Total) * 100`.

## Version 0.2: Advanced Intelligence Architecture - Completed

- Added an isolated optional intelligence package under `src/` with the following modular extensions:
  - `src/transactions.py` — transaction snapshots and rollback for file mutation safety.
  - `src/context.py` — lightweight token-budget compaction for runtime message management.
  - `src/lsp.py` — optional local LSP bridge with basic diagnostics and definition lookup hooks.
  - `src/security.py` — strict path canonicalization and sandbox breakout rejection.
- Wired the primary runner loop to optionally import the token-aware context compactor without altering the existing system prompt or UI layer.
- Hardened the sandbox patch path by taking a pre-write snapshot and restoring the original content if a write or verification step fails.
- Exposed the new utilities through the top-level `src` package while keeping the existing Hamster tool surface stable.

## Version 0.3: Production Hardening & Intelligence Upgrades — Completed

- Added `src/container.py` — `DockerSandboxBackend` that executes terminal commands inside
  an ephemeral Docker container (`--network=none`, `--memory=256m`, `--cpus=1`) for process-level
  isolation. Falls back transparently to host subprocess when Docker is unavailable, preserving all
  existing behaviour.
- Wired `run_sandbox_command` in `hamster/tools.py` to use `execute_sandboxed` from the new backend
  instead of raw `subprocess.run`.
- Implemented `launch_container` in `hamster/runtime.py` using `DockerSandboxBackend` (was a stub).
- Added APFS copy-on-write fast-clone path in `src/sandbox.py` via `_try_apfs_clone`: on macOS,
  `cp -c` is used to clone sandbox directories near-instantly without copying file data. Falls back
  to `shutil.copytree` on any failure or non-macOS OS.
- Refactored `TempSandbox._IGNORED_ENTRIES` into a `frozenset` class variable so the ignore list is
  shared between `shutil.copytree` and the APFS clone path.
- Added `_try_fuzzy_replace` helper to `hamster/tools.py` — a trailing-whitespace-tolerant patch
  fallback. `edit_file_patch` now first tries an exact `str.replace`, then falls back to the fuzzy
  matcher, so the model can match code blocks even when trailing spaces differ.
- Extended `read_file` with optional `start_line` / `end_line` parameters (1-indexed, inclusive)
  for windowed reading of large files. Updated the OpenRouter tool schema accordingly.
- Added `src/lsp.py` `LSPDaemon` — a persistent JSON-RPC 2.0 LSP client that keeps a
  `pyright-langserver --stdio` process alive between calls via a background reader thread. `LSPBridge`
  now tries the daemon first and falls through to the original subprocess-per-call approach when
  the daemon is unavailable.
- Upgraded `src/context.py` token estimator to use `tiktoken` (`cl100k_base` BPE encoding) when
  the optional package is installed. Gracefully falls back to the existing regex tokenizer.
- Added `ALLOWED_BINARIES` frozenset and `is_whitelisted_binary` classmethod to
  `hamster/policy.py` `CommandASTAnalyzer`. The `analyze` method now appends an advisory
  `binary_not_whitelisted` note for unlisted binaries.
- Added two-stage Planning → Execution workflow to `hamster/agent.py`. When the model's first
  response (no tool calls) contains plan markers (numbered steps, `## Plan`, etc.), the plan is
  shown to the user and an execution prompt is injected into the message history, triggering a
  second model call to act on it. Guarded by `_execution_started` flag to prevent loops.
- Added `tests/test_improvements.py` with 37 new tests; **total test count raised from 26 → 63,
  all passing**.

## Version 0.4: Persistent Resumable Sessions — Completed

- Added `hamster/session_store.py` — a `SessionStore` class backed by `sqlite3` (stdlib, zero new
  dependencies). Stores session metadata and full message history in `~/.hamster/sessions.db`.
  - Schema: `sessions` table (session_id, working_dir, created_at, updated_at, last_prompt,
    token_usage) and `messages` table with FK cascade and WAL journal mode.
  - Public API: `create_session`, `save_message`, `save_messages` (bulk idempotent upsert),
    `load_messages`, `update_meta`, `list_sessions`, `get_session`, `delete_session`.
- Wired `SessionStore` into `hamster/cli.py` `main()`:
  - A new session row is created at startup; `save_messages` + `update_meta` are called after
    every agent turn so the full conversation is always persisted to disk.
  - `main()` accepts `resume_messages` and `resume_session_id` kwargs for seamless resumption.
- Added `hamster resume <session_id>` CLI sub-command: loads history from the store, prints a
  gold "Resuming 🐹" banner, and re-enters the interactive loop with full context restored.
- Added `hamster list-sessions` CLI sub-command: renders a Rich table of all past sessions with
  Session ID, Created, Last Active, Working Dir, and Last Prompt columns.
- Added two UI helpers in `hamster/ui.py`: `print_session_resumed` (resume banner) and
  `print_sessions_table` (sessions listing). Updated `/help` output with a CLI tip line.
- Added `tests/test_session_store.py` with 19 new tests across five test classes:
  `TestSessionCreation`, `TestGetAndDelete`, `TestUpdateMeta`, `TestMessagePersistence`,
  `TestListSessions`. All use `tempfile.TemporaryDirectory` — no real DB touched.
- **Total test count raised from 119 → 138, all passing (17 skipped as before).**

## Version 0.5: Multi-Step Undo / Checkpoint Engine — Completed

- Added `hamster/checkpoint.py` — a `CheckpointStore` class using pure-Python CAS (SHA-256 blob
  deduplication + JSON manifests) stored in `~/.hamster/checkpoints/`. Zero new dependencies.
  - Blob layout: `blobs/<xx>/<sha256>` (content-addressed, write-once).
  - Manifest layout: `manifests/ckpt_<hex>.json` (maps workspace rel-path → blob SHA).
  - Public API: `create_checkpoint`, `restore_checkpoint`, `list_checkpoints`,
    `delete_checkpoint`, `gc_blobs`.
  - `_IGNORE_DIRS` set skips `.git`, `__pycache__`, `.venv`, etc.
- Extended `hamster/session_store.py`:
  - New `checkpoints` table (checkpoint_id PK, session_id FK cascade, turn_index, created_at).
  - New methods: `save_checkpoint`, `list_checkpoints_for_session`, `get_checkpoint_at_turn`.
- Added `undo_workspace(steps, session_id, store) → (bool, str)` to `hamster/tools.py`.
  - Resolves `turn_offset=N` via the session store, delegates restore to `CheckpointStore`.
  - **Never touches the messages list** — conversation history is always preserved.
- Wired into `hamster/cli.py` `main()`:
  - `turn_index` counter increments on every user turn.
  - A CAS checkpoint is created **before** every agent turn and cross-referenced in the DB.
  - `/undo [N]` command handler parses optional N (default 1) and calls `undo_workspace`.
  - Resumed sessions inherit the existing turn counter from saved checkpoint count.
- Added `print_undo_result(message, success)` to `hamster/ui.py`; `/help` now lists `/undo [N]`.
- Added `tests/test_checkpoint.py` with 16 new tests across 5 classes:
  `TestCheckpointBlobs`, `TestCheckpointCreate`, `TestCheckpointRestore`,
  `TestSessionStoreCheckpoints`, `TestMultiTurnRestore`.
- **Total test count raised from 138 → 156, all passing (17 skipped as before).**

## Left To Do

- Add package distribution docs for user-level installation with `uv tool install`.
- Add `tiktoken` as an optional extras dependency in `pyproject.toml` for users who want exact BPE counts.
- Implement `launch_native` in `hamster/runtime.py` with Linux namespace/cgroup/seccomp setup.
- Add interactive PTY engine and gRPC control plane (Feature #2).
- Add incremental disk-cached AST symbol graph (Feature #3).
- Add `hamster checkpoints` CLI sub-command for inspecting/pruning checkpoint history.
- Add `gc_blobs` scheduled cleanup on session exit.
