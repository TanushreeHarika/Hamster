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

### Option 1: Using `uv` (Recommended)

1. **Clone & Navigate**:
   ```bash
   git clone https://github.com/your-repo/hamster.git
   cd hamster
   ```

2. **Create Virtual Environment & Install**:
   ```bash
   uv venv
   # On macOS/Linux:
   source .venv/bin/activate
   # On Windows (PowerShell):
   .venv\Scripts\activate

   uv pip install -e .
   ```

### Option 2: Using standard `pip`

```bash
python -m venv venv
# On macOS/Linux:
source venv/bin/activate
# On Windows (PowerShell):
venv\Scripts\activate

pip install -e .
```

---

## ⚙️ Configuration

Create or update a `.env` file in the project root directory:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=openai/gpt-4o-mini  # Optional model override
MAX_TOKENS=4096
MAX_FAILURES=3
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
| `/help` | Displays the interactive command guide and tooling overview. |
| `/files` | Lists all files currently modified or staged in the draft workspace. |
| `/pending` | Displays a summary of pending drafted changes. |
| `/apply` | Manually applies drafted changes to the real project root. |
| `/search <query>` | Triggers a DuckDuckGo documentation search. |
| `/clear` | Clears the terminal screen and refreshes the Hamster splash art. |
| `/exit` | Safely destroys the active sandbox workspace and exits. |

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