# Hamster

Hamster is a lightweight, efficient Command Line Interface (CLI) agent designed specifically for various software engineering tasks. Utilizing the OpenRouter framework, Hamster integrates permission-gated sandbox tools to create a secure and controlled environment for executing commands and manipulating files.

## Features

- **Lightweight CLI**: Hamster is optimized for fast interactions and minimal resource consumption, making it suitable for developers who require efficiency in their workflow.
  
- **Secure Sandbox**: All command executions and file operations are confined to a dedicated environment, ensuring that sensitive data remains secure and unauthorized access is prevented.

- **Interactive Command Guide**: Users have quick access to help and command overviews directly from the CLI interface, reducing the learning curve for new users.

## Setup

To install and set up Hamster, follow these comprehensive steps:

1. **Create a Virtual Environment**: Itâs recommended to use Pythonâs built-in virtual environment support.
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
All tool file access is strictly contained to a hidden OS-managed sandbox workspace. Completed, approved changes are applied back to the project incrementally.

## Available Commands

Hamster provides an intuitive interface with several helpful commands. Here are some available commands:

```text
/help             Display the interactive command guide, offering assistance and an overview of available commands.
/search <query>   Utilize Hamster to search for relevant technical documentation or resources based on your query. Ideal for finding quick answers or code examples.
/clear            Clear the terminal UI and refresh the display for a clean workspace.
/exit             Exit the Hamster environment and return to your standard shell.
```

### Tooling Overview

Hamster features five key permission-gated tools that significantly enhance its functionality while adhering to security practices:

- `search_codebase(query)`: Conducts searches exclusively within the hidden sandbox workspace, enabling users to locate files and references quickly.
  
- `read_file(filepath)`: Safely reads files located within the hidden sandbox workspace, ensuring secure content access and protection against unauthorized modification.

- `edit_file_patch(filepath, target_text, replacement_text)`: Facilitates surgical replacements in file text within the sandbox, providing previews of changes before final application for user approval.

- `web_search(query)`: Performs an authorized search on DuckDuckGo, allowing access to technical documentation relevant to user queries, thereby assisting in troubleshooting and learning.

- `run_sandbox_command(command)`: Executes pre-approved commands within the sandbox, employing filtering mechanisms to guarantee safety and prevent system alterations.

### Security Measures
Hamster implements rigorous security protocols that validate all requests for sandbox path access. Attempts to escape the sandbox environment are strictly prohibited and generate a security violation response, safeguarding the integrity of the system.

## Conclusion

**Conclusion**

Hamster transforms software engineering workflows by offering a secure, efficient Command Line Interface tailored to developer needs. By providing an array of versatile tools while enforcing stringent security measures, Hamster ensures that each operation is safe and controlled. Integrating Hamster into your development process can significantly enhance productivity, allowing you to focus on what truly matters: writing exceptional code and building quality applications.
