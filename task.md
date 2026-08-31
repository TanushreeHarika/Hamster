# Hamster Production-Ready Pass Tasks

- [x] Research: audit ui.py, cli.py, auth, config, tests, CI
- [x] ui.py: add print_version(), print_set_key_success(), extend print_help()
- [x] cli.py: add /version, /set-key interactive commands + version/set-key CLI sub-commands
- [x] .env: scrub live credentials → safe placeholders
- [x] .env.example: create canonical template
- [x] .gitignore: add .env.local
- [x] .github/workflows/ci.yml: create from scratch
- [x] Run full test suite — 199 passed, 17 skipped (Docker), 0 failures
