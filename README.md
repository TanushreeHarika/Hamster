# Hamster

Hamster is a lightweight, efficient Command Line Interface (CLI) agent designed specifically for software engineering tasks. Utilizing the OpenRouter framework, Hamster drafts changes safely and lets you accept or reject the whole result at the end of a task.

## Features

- **Lightweight CLI**: Optimized for fast interactions and minimal resource consumption, making it suitable for developers who require efficiency in their workflow.

- **Drafted Changes**: Works on a draft first, allowing you to decide whether to save or discard the completed result, ensuring you always have control of your changes.

- **Interactive Command Guide**: Provides quick access to help and command overviews directly from the CLI interface, reducing the learning curve for new users.

## Setup

To install and set up Hamster, follow these comprehensive steps:

1. **Create a Virtual Environment**: It's recommended to use Python's built-in virtual environment support.
   ```bash
   python -m venv venv
   ```

2. **Install Dependencies**: Change to the project directory and install the package in editable mode using pip:
   ```bash
   pip install -e .
   ```

3. **Configuration**: Create a configuration file to set the necessary API credentials and operational parameters. Create or update a `.env` file in the project root directory with the following content:
   ```bash
   OPENROUTER_API_KEY=your_key_here   # Replace 'your_key_here' with your actual OpenRouter API key
   MAX_TOKENS=4096                      # Maximum number of tokens for processing API requests
   MAX_FAILURES=3                       # Specifies the number of allowed failures before the application halts
   ```

4. **Run Hamster**: To start the Hamster CLI and access its features, use the following command:
   ```bash
   hamster
   ```

### Important Note:
Hamster prompts at the end of a task with changes: accept all to save the result, or reject all to discard it.

## Available Commands

Hamster provides an intuitive interface with several helpful commands. Here are some available commands:

```text
/help             Display the interactive command guide, offering assistance and an overview of available commands.
/search <query>   Search for relevant technical documentation or resources based on your query, ideal for finding quick answers or code examples.
/clear            Clear the terminal UI and refresh the display for a clean workspace.
/exit             Exit the Hamster environment and return to your standard shell.
```

### Tooling Overview

Hamster features five key permission-gated tools that significantly enhance its functionality while adhering to security practices:

- `search_codebase(query)`: Conducts searches across the current project draft, enabling users to locate files and references quickly.

- `read_file(filepath)`: Safely reads project files by relative path.

- `edit_file_patch(filepath, target_text, replacement_text)`: Facilitates surgical replacements in file text.

- `web_search(query)`: Performs an authorized search on DuckDuckGo, allowing access to technical documentation relevant to user queries, assisting in troubleshooting and learning.

- `run_sandbox_command(command)`: Executes pre-approved commands with filtering mechanisms to prevent unsafe operations.

### Security Measures
Hamster implements rigorous security protocols that validate all requested paths. Attempts to access files outside the allowed project scope are blocked with a security violation response, ensuring the integrity and safety of your development environment.

## Conclusion

Hamster transforms software engineering workflows by offering a secure, efficient Command Line Interface tailored to developer needs. By providing an array of versatile tools while enforcing stringent security measures, Hamster ensures each operation is safe and controlled. Integrating Hamster into your development process can significantly enhance productivity, allowing you to focus on what truly matters: writing exceptional code and building quality applications.