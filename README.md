# Hamster

Hamster is a lightweight and efficient Command Line Interface (CLI) agent designed for software engineering tasks. Built from the ground up around the OpenRouter framework, it leverages permission-gated sandbox tools to provide a safe and controlled environment for executing commands and manipulating files.

## Features

- **Lightweight CLI**: Hamster is designed for quick interactions and minimal resource use.
- **Secure Sandbox**: All commands and file operations are restricted to a contained environment to ensure safety and prevent unauthorized access.
- **Interactive Command Guide**: Users can easily access help and commands directly from the CLI interface.

## Setup

To install and set up Hamster, follow these steps:

1. **Create a Virtual Environment**:
   ```bash
   uv venv
   ```

2. **Install Dependencies**:
   Navigate to the project directory and install the package in editable mode using pip:
   ```bash
   uv pip install -e .
   ```

3. **Configuration**:
   Create or update a `.env` file in the project root directory with the following content:
   ```bash
   OPENROUTER_API_KEY=your_key_here   # Replace 'your_key_here' with your actual OpenRouter API key
   MAX_TOKENS=4096                      # Maximum tokens for API requests
   MAX_FAILURES=3                       # Number of allowed failures before halting
   ```

4. **Run Hamster**:
   To start the Hamster CLI, use the following command:
   ```bash
   hamster
   ```

### Note:
All tool file access is strictly confined to the `./sandbox/` directory.

## Available Commands

Hamster provides a set of intuitive commands:

```text
/help             Display the interactive command guide for assistance and command overview.
/search <query>   Utilize Hamster to search for relevant technical documentation or resources based on your query.
/clear            Clear the terminal UI and redraw for a fresh view.
/exit             Exit the Hamster environment and return to the shell.
```

## Tooling Overview

Hamster offers five key permission-gated tools designed to enhance functionality:

- `search_codebase(query)`: Searches exclusively within the `./sandbox/` directory for relevant content.
- `read_file(filepath)`: Safely reads files located within the `./sandbox/` directory, ensuring secure content access.
- `edit_file_patch(filepath, target_text, replacement_text)`: Allows for surgical text replacements in a file located within `./sandbox/`, with previews of changes before applying.
- `web_search(query)`: Conducts an approved search on DuckDuckGo to retrieve technical documentation relevant to the user's query.
- `run_sandbox_command(command)`: Executes pre-approved commands in the sandbox environment, using filtration to ensure safety.

### Security Measures
All requests for sandbox path access are rigorously validated to enforce absolute-path containment. Any attempts to escape the sandbox will result in a security violation response rather than a prompt.

## Conclusion

**Conclusion**

Hamster revolutionizes the workflow of software engineering by providing a secure and efficient Command Line Interface. It empowers developers with a range of versatile tools while maintaining stringent safety measures, ensuring that each operation is safe and controlled. By integrating Hamster into your development process, you can significantly enhance productivity and focus on what truly matters: writing great code.

