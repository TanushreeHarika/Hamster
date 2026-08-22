import argparse
import json
import sys
from pathlib import Path

from hamster.agent import initial_messages, run_agent_turn
from hamster.checkpoint import CheckpointStore
from hamster.config import load_config
from hamster.openrouter import OpenRouterClient
from hamster.session_store import SessionStore
from hamster.tools import (
    cleanup_sandbox,
    configure_sandbox,
    discard_sandbox_changes,
    has_pending_sandbox_changes,
    init_session_state,
    list_sandbox_files,
    pending_change_diff,
    pending_change_summary,
    review_changes,
    run_sandbox_command,
    apply_sandbox_to_root,
    get_session_state,
    sync_workspace_to_sandbox,
    undo_workspace,
)
from hamster.ui import (
    clear_screen,
    print_exit_logo,
    print_help,
    print_login_success,
    print_logo,
    print_session_resumed,
    print_sessions_table,
    print_undo_result,
    print_whoami,
    prompt_user,
    request_save_changes,
)
from hamster.rpc import SessionManager, RPCGateway
from src.sandbox import TempSandbox
from src.transactions import snapshot_files, rollback_snapshot, FileSnapshot


def _ensure_foundation(project_root: Path) -> None:
    env_path = project_root / ".env"
    if not env_path.exists():
        env_path.write_text(
            "OPENROUTER_API_KEY=\nMAX_TOKENS=4096\nMAX_FAILURES=3\n",
            encoding="utf-8",
        )


def main(resume_messages: list | None = None, resume_session_id: str | None = None) -> None:
    """Run the interactive Hamster session.

    Args:
        resume_messages:   Pre-populated message list when resuming a saved session.
        resume_session_id: Existing session_id to continue persisting into.
    """
    project_root = Path.cwd()
    _ensure_foundation(project_root)

    def start_sandbox() -> TempSandbox:
        sandbox = TempSandbox(project_root=project_root)
        configure_sandbox(sandbox)
        return sandbox

    sandbox = start_sandbox()
    init_session_state()
    session_manager = SessionManager()
    rpc_gateway = RPCGateway(session_manager)
    interactive_session_id = rpc_gateway.open_session("interactive")
    print_logo()

    # --- Session persistence setup ---
    store = SessionStore()
    ckpt_store = CheckpointStore()
    if resume_session_id:
        persist_session_id = resume_session_id
        # Resume the turn counter from how many checkpoints already exist
        turn_index = len(store.list_checkpoints_for_session(resume_session_id))
    else:
        persist_session_id = store.create_session(working_dir=str(project_root))
        turn_index = 0

    try:
        config = load_config(project_root)
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(1)

    client = OpenRouterClient(config)
    # Use pre-populated messages when resuming, otherwise start fresh
    messages = resume_messages if resume_messages is not None else initial_messages()

    print("Type /help for commands. Changes are reviewed once at the end of each task.\n")
    while True:
        try:
            user_input = prompt_user("[bold gold3]hamster>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print_exit_logo()
            cleanup_sandbox()
            return

        if not user_input:
            continue
        if user_input == "/exit":
            print_exit_logo()
            cleanup_sandbox()
            return
        if user_input == "/help":
            print_help()
            continue
        if user_input == "/clear":
            clear_screen()
            print_logo()
            continue
        if user_input == "/files":
            files = list_sandbox_files()
            print(f"{files}\n")
            continue
        if user_input == "/pending":
            print(f"{review_changes()}\n")
            continue
        if user_input == "/apply":
            print(f"{apply_sandbox_to_root()}\n")
            sandbox = start_sandbox()
            continue
        if user_input == "/sync":
            print(f"{sync_workspace_to_sandbox()}\n")
            continue
        if user_input.startswith("/search "):
            query = user_input.removeprefix("/search ").strip()
            if not query:
                print("Usage: /search <technical docs query>")
                continue
            user_input = f"Use web_search to look up technical documentation for: {query}"

        if user_input.startswith("/consent "):
            parts = user_input.split(maxsplit=2)
            if len(parts) >= 2 and parts[1] == "list":
                reqs = rpc_gateway.consent.list_requests()
                if not reqs:
                    print("No consent requests.")
                else:
                    for r in reqs:
                        print(f"{r.request_id}: session={r.session_id} status={r.status} command={r.command}")
                continue
            if len(parts) >= 3 and parts[1] == "approve":
                cid = parts[2]
                ok = rpc_gateway.consent.approve(cid)
                print("Approved." if ok else "Request not found.")
                continue
            if len(parts) >= 3 and parts[1] == "deny":
                cid = parts[2]
                ok = rpc_gateway.consent.deny(cid)
                print("Denied." if ok else "Request not found.")
                continue

        if user_input.startswith("/execgw "):
            cmd = user_input.removeprefix("/execgw ").strip()
            if not cmd:
                print("Usage: /execgw <command>")
                continue
            res = rpc_gateway.execute_command(interactive_session_id, cmd)
            print(res)
            continue

        if user_input == "/login":
            from hamster.auth.oauth  import AuthFlow
            from hamster.auth.store  import SecureTokenStore
            from hamster.auth.user   import get_profile
            import os

            client_id     = os.environ.get("GOOGLE_CLIENT_ID",     "").strip()
            client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

            env_path = Path.cwd() / ".env"
            if env_path.exists() and (not client_id or not client_secret):
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key == "GOOGLE_CLIENT_ID"     and not client_id:
                        client_id = val
                    elif key == "GOOGLE_CLIENT_SECRET" and not client_secret:
                        client_secret = val

            try:
                flow = AuthFlow(client_id=client_id, client_secret=client_secret)
                token_data = flow.run()
                profile    = get_profile(token_data)
                payload = {
                    **token_data,
                    "email":   profile.email,
                    "name":    profile.name,
                    "picture": profile.picture,
                    "sub":     profile.sub,
                }
                SecureTokenStore().save(payload)
                print_login_success(profile.email)
            except Exception as exc:
                print(f"\n❌  Login failed: {exc}")
            continue

        if user_input == "/logout":
            from hamster.auth.store import SecureTokenStore
            from rich.console import Console
            SecureTokenStore().delete()
            Console().print("[bold gold3]🐹  Logged out.[/] Credentials cleared from all storage backends.")
            continue

        if user_input == "/whoami":
            from hamster.auth.store import SecureTokenStore
            from rich.console import Console
            payload = SecureTokenStore().load()
            if not payload or not payload.get("email"):
                Console().print("[yellow]⚠️  Not logged in.[/] Run [bold cyan]/login[/] first.")
            else:
                print_whoami(payload)
            continue

        if user_input.startswith("/undo"):
            parts = user_input.split(maxsplit=1)
            steps = 1
            if len(parts) == 2:
                try:
                    steps = int(parts[1].strip())
                except ValueError:
                    print("Usage: /undo [N]  (N must be a positive integer)")
                    continue
            success, msg = undo_workspace(steps, persist_session_id, store)
            print_undo_result(msg, success=success)
            if success:
                # Sync the restored draft workspace back to the real project root
                # so that files added/modified/deleted since that turn are reverted on disk.
                apply_sandbox_to_root(project_root=project_root)
                sandbox = start_sandbox()
            continue

        # --- Take a workspace checkpoint before every agent turn ---
        ckpt_id = ckpt_store.create_checkpoint(
            sandbox.workspace,
            session_id=persist_session_id,
            turn_index=turn_index,
        )
        store.save_checkpoint(persist_session_id, ckpt_id, turn_index)
        turn_index += 1

        messages.append({"role": "user", "content": user_input})
        run_agent_turn(client, messages, config.max_failures)

        # --- Persist the full updated message history after every turn ---
        store.save_messages(persist_session_id, messages)
        store.update_meta(
            persist_session_id,
            last_prompt=user_input[:200],
            token_usage=len(messages),  # rough proxy; replace with real token count if available
        )

        if has_pending_sandbox_changes():
            decision = request_save_changes(pending_change_summary(), pending_change_diff())
            if decision == "accept":
                print(f"{apply_sandbox_to_root(project_root=project_root)}\n")
            else:
                print(f"{discard_sandbox_changes()}\n")
        else:
            cleanup_sandbox()
        sandbox = start_sandbox()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="hamster")
    sub = parser.add_subparsers(dest="cmd", help="sub-command help")

    sub.add_parser("start", help="Start interactive Hamster session")

    p_exec = sub.add_parser("exec", help="Run a checked shell command")
    p_exec.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")

    p_snap = sub.add_parser("snapshot", help="Snapshot one or more filesystem paths")
    p_snap.add_argument("paths", nargs="+", help="Paths to snapshot")
    p_snap.add_argument("--out", "-o", help="Output file to write snapshot (JSON)")

    p_restore = sub.add_parser("restore", help="Restore from a snapshot JSON file")
    p_restore.add_argument("snapshot_file", help="Snapshot JSON file produced by `snapshot`")

    p_diff = sub.add_parser("diff", help="Show draft file listing")
    p_diff.add_argument("--pattern", "-p", default="", help="Filter pattern")

    p_approve = sub.add_parser("approve", help="Approve read scope for the session")
    p_approve.add_argument("scope", nargs="?", default="codebase", help="Scope to approve")

    p_consent = sub.add_parser("consent", help="Manage consent requests")
    consent_sub = p_consent.add_subparsers(dest="consent_cmd")
    consent_sub.add_parser("list", help="List pending consent requests")
    p_consent_approve = consent_sub.add_parser("approve", help="Approve a consent request by id")
    p_consent_approve.add_argument("id", help="Consent request id")
    p_consent_deny = consent_sub.add_parser("deny", help="Deny a consent request by id")
    p_consent_deny.add_argument("id", help="Consent request id")

    # --- Session persistence sub-commands ---
    sub.add_parser("list-sessions", help="List all saved Hamster sessions")

    p_resume = sub.add_parser("resume", help="Resume a saved Hamster session")
    p_resume.add_argument("session_id", help="Session ID to resume (from list-sessions)")

    # --- Auth sub-commands ---
    sub.add_parser("login",  help="Log in with Google (OAuth 2.0 PKCE flow)")
    sub.add_parser("logout", help="Clear saved Google credentials")
    sub.add_parser("whoami", help="Show the currently logged-in user")

    args = parser.parse_args()

    if args.cmd in (None, "start"):
        main()
        sys.exit(0)

    if args.cmd == "list-sessions":
        store = SessionStore()
        sessions = store.list_sessions()
        print_sessions_table(sessions)
        sys.exit(0)

    if args.cmd == "resume":
        store = SessionStore()
        session_id = args.session_id.strip()
        row = store.get_session(session_id)
        if row is None:
            print(f"Session '{session_id}' not found. Run 'hamster list-sessions' to see available sessions.")
            sys.exit(1)
        saved_messages = store.load_messages(session_id)
        if not saved_messages:
            # No messages persisted yet — start fresh but keep the session_id
            saved_messages = initial_messages()
        print_session_resumed(
            session_id=session_id,
            msg_count=len(saved_messages),
            working_dir=row.get("working_dir", ""),
        )
        main(resume_messages=saved_messages, resume_session_id=session_id)
        sys.exit(0)

    # Non-interactive commands use a short-lived TempSandbox when needed
    if args.cmd == "exec":
        cmd = " ".join(args.command).strip()
        if not cmd:
            print("No command provided.")
            sys.exit(2)
        sandbox = TempSandbox(project_root=Path.cwd())
        configure_sandbox(sandbox)
        init_session_state()
        try:
            out = run_sandbox_command(cmd)
            print(out)
        finally:
            print(cleanup_sandbox())
        sys.exit(0)

    if args.cmd == "snapshot":
        snap = snapshot_files(args.paths)
        serializable = {
            k: {"path": v.path, "original_text": v.original_text, "exists": v.exists}
            for k, v in snap.items()
        }
        if args.out:
            Path(args.out).write_text(json.dumps(serializable, indent=2), encoding="utf-8")
            print(f"Wrote snapshot to {args.out}")
        else:
            print(json.dumps(serializable, indent=2))
        sys.exit(0)

    if args.cmd == "restore":
        data = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
        reconstructed: dict[str, FileSnapshot] = {}
        for k, v in data.items():
            reconstructed[k] = FileSnapshot(path=v["path"], original_text=v["original_text"], exists=v["exists"])
        res = rollback_snapshot(reconstructed)
        print(json.dumps(res, indent=2))
        sys.exit(0)

    if args.cmd == "diff":
        out = list_sandbox_files(pattern=args.pattern)
        print(out)
        sys.exit(0)

    if args.cmd == "approve":
        init_session_state()
        session = get_session_state()
        session.approve_read(args.scope)
        print(f"Approved read for scope: {args.scope}")
        sys.exit(0)

    if args.cmd == "consent":
        # Use a local in-process SessionManager + RPCGateway for consent handling
        from hamster.rpc import SessionManager, RPCGateway

        sm = SessionManager()
        gw = RPCGateway(sm)
        # handle subcommands
        if args.consent_cmd == "list":
            reqs = gw.consent.list_requests()
            if not reqs:
                print("No consent requests.")
            else:
                for r in reqs:
                    print(f"{r.request_id}: session={r.session_id} status={r.status} command={r.command}")
            sys.exit(0)

        if args.consent_cmd == "approve":
            ok = gw.consent.approve(args.id)
            print("Approved." if ok else "Request not found.")
            sys.exit(0)

        if args.consent_cmd == "deny":
            ok = gw.consent.deny(args.id)
            print("Denied." if ok else "Request not found.")
            sys.exit(0)

    # --- Auth command handlers ---
    if args.cmd == "login":
        from hamster.auth.oauth  import AuthFlow
        from hamster.auth.store  import SecureTokenStore
        from hamster.auth.user   import get_profile
        import os

        client_id     = os.environ.get("GOOGLE_CLIENT_ID",     "").strip()
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()

        # Load from .env if not already in environment
        env_path = Path.cwd() / ".env"
        if env_path.exists() and (not client_id or not client_secret):
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key == "GOOGLE_CLIENT_ID"     and not client_id:
                    client_id = val
                elif key == "GOOGLE_CLIENT_SECRET" and not client_secret:
                    client_secret = val

        try:
            flow = AuthFlow(client_id=client_id, client_secret=client_secret)
            token_data = flow.run()
            profile    = get_profile(token_data)
            # Persist tokens + profile together so whoami works offline
            payload = {
                **token_data,
                "email":   profile.email,
                "name":    profile.name,
                "picture": profile.picture,
                "sub":     profile.sub,
            }
            SecureTokenStore().save(payload)
            print_login_success(profile.email)
        except Exception as exc:  # noqa: BLE001
            print(f"\n❌  Login failed: {exc}")
            sys.exit(1)
        sys.exit(0)

    if args.cmd == "logout":
        from hamster.auth.store import SecureTokenStore
        SecureTokenStore().delete()
        from rich.console import Console
        Console().print(
            "[bold gold3]🐹  Logged out.[/] Credentials cleared from all storage backends."
        )
        sys.exit(0)

    if args.cmd == "whoami":
        from hamster.auth.store import SecureTokenStore
        payload = SecureTokenStore().load()
        if not payload or not payload.get("email"):
            from rich.console import Console
            Console().print(
                "[yellow]⚠️  Not logged in.[/] Run [bold cyan]hamster login[/] first."
            )
            sys.exit(1)
        print_whoami(payload)
        sys.exit(0)

    parser.print_help()
