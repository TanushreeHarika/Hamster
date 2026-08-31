# Hamster

**Hamster** is a lightweight, high-performance Command Line Interface (CLI) software engineering agent. Utilizing the OpenRouter API framework, Hamster drafts changes in an isolated temporary sandbox, presenting rich terminal previews and allowing you to accept or discard all changes at the end of each task.

---

## 🌟 Key Features

- **Isolated Draft Workspace**: All reads, writes, and command executions target a temporary sandbox (`/tmp/hamster-sandbox-<uuid>/`). The real project directory is touched only when you explicitly approve changes at task completion.
- **Cross-Platform Compatibility**: Fully compatible with **macOS**, **Linux**, and **Windows** (CMD, PowerShell, Git Bash, WSL2).
- **APFS Fast-Cloning**: On macOS, utilizes APFS copy-on-write (`cp -c`) for instant (<10ms) sandbox instantiation without physically duplicating file contents.
- **Ephemeral Docker Sandbox Backend**: Command execution delegates to an ephemeral, network-isolated Docker container (`--network=none`, `--memory=256m`, `--cpus=1`) when Docker is present, falling back seamlessly to host process execution.
- **Two-Stage Planning → Execution Engine**: Automatically detects structured planning responses from the model and injects an execution prompt before invoking tools.
- **Persistent LSP Integration**: Integrates a persistent JSON-RPC 2.0 language server daemon (`pyright-langserver`) for real-time code diagnostics and definition resolution.
- **Windowed File Reading & Fuzzy Patching**: Supports line-range slicing (`start_line`, `end_line`) for reading large files, and trailing-whitespace-tolerant fuzzy diff matching for edits.
- **Token Budget Context Compactor**: Built-in context compaction using `tiktoken` BPE token estimation (`cl100k_base`) to maximize context retention without overflowing model limits.
- **Strict Security Policy**: Path containment checks prevent sandbox escaping, combined with regex command filtering and strict binary allowlists (`git`, `python`, `pytest`, `npm`, etc.).

---

## 🛠️ Tooling Overview

Hamster exposes six permission-gated tools to the AI model:

| Tool | Description |
| :--- | :--- |
| `search_codebase(query)` | Conducts fast string searches across the sandbox workspace using `ripgrep` (`rg`). |
| `read_file(filepath, start_line, end_line)` | Safely reads project files by relative path with optional line-range slicing. |
| `edit_file_patch(filepath, target_text, replacement_text)` | Performs surgical replacements in file text (with exact and fuzzy whitespace-tolerant matching). |
| `write_file(filepath, content)` | Creates or overwrites a draft file, automatically scaffolding parent directories. |
| `web_search(query)` | Permission-gated DuckDuckGo search for technical documentation, APIs, and syntax lookup. |
| `run_sandbox_command(command)` | Executes pre-filtered shell commands in an isolated container or sandboxed environment. |

---

## 💻 Cross-Platform Prerequisites

Hamster requires **Python 3.11+** and **ripgrep (`rg`)** on system `PATH`.

### macOS
```bash
brew install ripgrep
```

### Linux (Ubuntu/Debian)
```bash
sudo apt update && sudo apt install ripgrep
```

### Windows
```powershell
winget install BurntSushi.ripgrep.MSVC
# Or via Chocolatey: choco install ripgrep
```

---

## 🚀 Setup & Installation

Install Hamster globally using `uv` (recommended) or `pip`:

```bash
uv tool install hamster-agent
# OR
pip install hamster-agent
```

---

## ⚙️ Configuration

Set up your OpenRouter API key using the built-in command:

```bash
hamster set-key your_openrouter_api_key_here
```

You can optionally log in with Google to enable advanced features:
```bash
hamster login
```

---

## 🎮 Usage & Available Commands

Start the interactive CLI:
```bash
hamster
```

### Interactive CLI Commands

| Command | Description |
| :--- | :--- |
| `/help` | Show the command guide and tooling overview. |
| `/version` | Show Hamster version, model, and Python info. |
| `/files` | List files in the current draft. |
| `/search <query>` | Ask Hamster to search technical documentation. |
| `/pending` | Show pending draft changes. |
| `/apply` | Save pending draft changes to disk. |
| `/sync` | Refresh draft state from disk. |
| `/undo [N]` | Revert workspace N turns (default 1), keeps conversation log. |
| `/set-key <key>` | Set or rotate the OpenRouter API key. |
| `/login` | Log in with Google (OAuth 2.0 PKCE flow). |
| `/whoami` | Show the currently logged-in user. |
| `/logout` | Clear saved Google credentials. |
| `/clear` | Clear the terminal and redraw the splash. |
| `/exit` | Leave Hamster (prints farewell graphic). |

---

## 🛡️ Security Measures

Hamster implements strict defense-in-depth security:
- **Path Canonicalization**: Resolves relative paths against the active sandbox root using `os.path.realpath`, rejecting any breakout attempts (`../../.env`).
- **Binary Allowlisting & Command Filtering**: Blocks dangerous commands (`sudo`, `rm`, `chmod`, `chown`, curl-to-shell pipes) while validating commands against an allowed binary matrix.
- **3-Way Conflict Detection**: Prevents overwriting external host edits when applying drafted changes.

---

## 🧪 Running Tests

Hamster includes a full unit test suite covering sandbox lifecycle, isolation, fuzzy patching, and policy analysis:

```bash
uv run python -m unittest discover tests
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.