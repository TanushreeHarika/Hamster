"""Tests for DockerSession persistent session, IsolationError strict mode,
self-healing container recovery, and backward-compat of existing API.

Docker-dependent tests are skipped when Docker is not available on the
current machine so the full suite still passes in CI environments without
a Docker daemon.
"""
from __future__ import annotations

import os
import subprocess
import time
import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: detect Docker at import time so @skipIf works
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    if not any(
        __import__("shutil").which(cmd) for cmd in ("docker",)
    ):
        return False
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return r.returncode == 0
    except Exception:
        return False


DOCKER_AVAILABLE = _docker_available()
_SKIP_NO_DOCKER = unittest.skipIf(
    not DOCKER_AVAILABLE,
    "Docker daemon not available — skipping Docker-dependent tests",
)


# ---------------------------------------------------------------------------
# 1. IsolationError import + env var
# ---------------------------------------------------------------------------

class TestIsolationErrorImport(unittest.TestCase):
    """IsolationError is importable and is a RuntimeError subclass."""

    def test_isolation_error_importable(self) -> None:
        from src.container import IsolationError
        self.assertTrue(issubclass(IsolationError, RuntimeError))
        # Can be instantiated and raised normally
        with self.assertRaises(IsolationError):
            raise IsolationError("test")

    def test_require_isolation_env_var_false_by_default(self) -> None:
        """REQUIRE_ISOLATION is False when env var is absent."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HAMSTER_REQUIRE_ISOLATION", None)
            # Re-evaluate the helper
            from src.container import _read_require_isolation
            self.assertFalse(_read_require_isolation())

    def test_require_isolation_env_var_true_values(self) -> None:
        """REQUIRE_ISOLATION truthy values: '1', 'true', 'yes'."""
        from src.container import _read_require_isolation
        for val in ("1", "true", "True", "TRUE", "yes", "YES"):
            with patch.dict(os.environ, {"HAMSTER_REQUIRE_ISOLATION": val}):
                self.assertTrue(_read_require_isolation(), f"Expected True for {val!r}")

    def test_require_isolation_env_var_false_values(self) -> None:
        """REQUIRE_ISOLATION falsy values: '0', 'false', 'no', ''."""
        from src.container import _read_require_isolation
        for val in ("0", "false", "False", "no", "", "off"):
            with patch.dict(os.environ, {"HAMSTER_REQUIRE_ISOLATION": val}):
                self.assertFalse(_read_require_isolation(), f"Expected False for {val!r}")


# ---------------------------------------------------------------------------
# 2. DockerSandboxBackend strict mode
# ---------------------------------------------------------------------------

class TestDockerSandboxBackendStrictMode(unittest.TestCase):

    def test_strict_mode_raises_isolation_error_when_docker_unavailable(self) -> None:
        """require_isolation=True + no Docker → IsolationError, not host exec."""
        from src.container import DockerSandboxBackend, IsolationError
        backend = DockerSandboxBackend(require_isolation=True)
        backend._available = False  # Force unavailable
        with self.assertRaises(IsolationError):
            backend.execute_command("echo hello")

    def test_lenient_mode_falls_back_to_host_when_docker_unavailable(self) -> None:
        """require_isolation=False + no Docker → host fallback, no exception."""
        from src.container import DockerSandboxBackend
        backend = DockerSandboxBackend(require_isolation=False)
        backend._available = False  # Force unavailable
        result = backend.execute_command("echo hello")
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_default_mode_is_lenient(self) -> None:
        """Default backend (no args) uses require_isolation=False."""
        from src.container import DockerSandboxBackend
        backend = DockerSandboxBackend()
        backend._available = False
        # Should not raise
        result = backend.execute_command("echo ok")
        self.assertIn("ok", result.stdout)

    @_SKIP_NO_DOCKER
    def test_strict_mode_allows_execution_when_docker_available(self) -> None:
        """require_isolation=True with real Docker should NOT raise."""
        from src.container import DockerSandboxBackend, IsolationError
        backend = DockerSandboxBackend(require_isolation=True)
        # Should NOT raise — Docker is available
        try:
            result = backend.execute_command("echo strict_ok")
            # If Docker runs successfully, stdout contains our echo
            self.assertIn("strict_ok", result.stdout)
        except IsolationError:
            self.fail("IsolationError raised even though Docker is available")


# ---------------------------------------------------------------------------
# 3. DockerSession lifecycle (Docker required)
# ---------------------------------------------------------------------------

class TestDockerSessionLifecycle(unittest.TestCase):

    @_SKIP_NO_DOCKER
    def test_start_produces_container_id(self) -> None:
        from src.container import DockerSession
        session = DockerSession()
        try:
            session.start()
            self.assertIsNotNone(session._container_id)
            self.assertGreater(len(session._container_id), 0)
            self.assertTrue(session.is_alive())
        finally:
            session.stop()

    @_SKIP_NO_DOCKER
    def test_is_alive_false_after_stop(self) -> None:
        from src.container import DockerSession
        session = DockerSession()
        session.start()
        cid = session._container_id
        session.stop()
        self.assertIsNone(session._container_id)
        # Container should no longer be running
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", cid],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        # Either the container is gone (non-zero returncode) or it's not running
        if result.returncode == 0:
            self.assertNotEqual(result.stdout.strip(), "true")

    @_SKIP_NO_DOCKER
    def test_idempotent_stop(self) -> None:
        """Calling stop() twice should not raise."""
        from src.container import DockerSession
        session = DockerSession()
        session.start()
        session.stop()
        session.stop()  # Second call — must not raise

    @_SKIP_NO_DOCKER
    def test_context_manager_starts_and_stops(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            self.assertTrue(session.is_alive())
        # After exiting the context manager, container should be stopped
        self.assertIsNone(session._container_id)


# ---------------------------------------------------------------------------
# 4. DockerSession command execution (Docker required)
# ---------------------------------------------------------------------------

class TestDockerSessionExecution(unittest.TestCase):

    @_SKIP_NO_DOCKER
    def test_execute_echo(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            result = session.execute("echo hello_hamster")
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello_hamster", result.stdout)

    @_SKIP_NO_DOCKER
    def test_execute_captures_stderr(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            result = session.execute("python3 -c \"import sys; sys.stderr.write('errout')\"")
        self.assertIn("errout", result.stderr)

    @_SKIP_NO_DOCKER
    def test_execute_nonzero_exit_code(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            result = session.execute("exit 42")
        self.assertEqual(result.returncode, 42)


# ---------------------------------------------------------------------------
# 5. cwd persistence (Docker required)
# ---------------------------------------------------------------------------

class TestDockerSessionCwdPersistence(unittest.TestCase):

    @_SKIP_NO_DOCKER
    def test_cwd_default_is_workspace(self) -> None:
        from src.container import DockerSession
        session = DockerSession()
        self.assertEqual(session.cwd, "/workspace")
        session.start()
        try:
            result = session.execute("pwd")
            self.assertIn("/workspace", result.stdout)
        finally:
            session.stop()

    @_SKIP_NO_DOCKER
    def test_cwd_change_persists_across_calls(self) -> None:
        """Updating session.cwd before the next execute uses the new directory."""
        from src.container import DockerSession
        with DockerSession() as session:
            # Create a subdirectory and switch to it
            session.execute("mkdir -p /workspace/subdir")
            session.cwd = "/workspace/subdir"
            result = session.execute("pwd")
        self.assertIn("subdir", result.stdout)


# ---------------------------------------------------------------------------
# 6. Environment variable persistence (Docker required)
# ---------------------------------------------------------------------------

class TestDockerSessionEnvPersistence(unittest.TestCase):

    @_SKIP_NO_DOCKER
    def test_env_var_forwarded_to_exec(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            session.env["MY_VAR"] = "hamster_value"
            result = session.execute("echo $MY_VAR")
        self.assertIn("hamster_value", result.stdout)

    @_SKIP_NO_DOCKER
    def test_multiple_env_vars_forwarded(self) -> None:
        from src.container import DockerSession
        with DockerSession() as session:
            session.env["FOO"] = "foo_val"
            session.env["BAR"] = "bar_val"
            result = session.execute("echo $FOO:$BAR")
        self.assertIn("foo_val", result.stdout)
        self.assertIn("bar_val", result.stdout)


# ---------------------------------------------------------------------------
# 7. Self-healing container recovery (Docker required)
# ---------------------------------------------------------------------------

class TestDockerSessionSelfHealing(unittest.TestCase):

    @_SKIP_NO_DOCKER
    def test_self_heal_after_container_stopped_externally(self) -> None:
        """If the container is killed externally, the next execute() recovers."""
        from src.container import DockerSession
        session = DockerSession()
        session.start()
        old_cid = session._container_id
        self.assertIsNotNone(old_cid)

        # Externally stop the container to simulate a crash
        subprocess.run(
            ["docker", "stop", old_cid],
            capture_output=True,
            timeout=10,
            check=False,
        )

        # Brief wait for container to fully stop
        time.sleep(0.5)

        # The next execute() call should self-heal and succeed
        try:
            result = session.execute("echo recovered")
            self.assertEqual(result.returncode, 0)
            self.assertIn("recovered", result.stdout)
            # A new container ID should have been assigned
            self.assertIsNotNone(session._container_id)
            self.assertNotEqual(session._container_id, old_cid)
        finally:
            session.stop()

    @_SKIP_NO_DOCKER
    def test_self_heal_restores_cwd(self) -> None:
        """After self-healing, cwd is restored in the new container."""
        from src.container import DockerSession
        session = DockerSession()
        session.start()

        # Set a custom cwd
        session.execute("mkdir -p /workspace/healdir")
        session.cwd = "/workspace/healdir"

        old_cid = session._container_id
        # Kill the container
        subprocess.run(
            ["docker", "stop", old_cid],
            capture_output=True,
            timeout=10,
            check=False,
        )
        time.sleep(0.5)

        # Self-healed execute should run in /workspace/healdir
        try:
            result = session.execute("pwd")
            self.assertIn("healdir", result.stdout)
        finally:
            session.stop()


# ---------------------------------------------------------------------------
# 8. Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility(unittest.TestCase):

    def test_container_result_namedtuple(self) -> None:
        """ContainerResult remains a NamedTuple with the same fields."""
        from src.container import ContainerResult
        r = ContainerResult(stdout="out", stderr="err", returncode=0)
        self.assertEqual(r.stdout, "out")
        self.assertEqual(r.stderr, "err")
        self.assertEqual(r.returncode, 0)

    def test_execute_sandboxed_callable(self) -> None:
        """execute_sandboxed() still works with no extra arguments."""
        from src.container import execute_sandboxed
        result = execute_sandboxed("echo compat_check")
        self.assertIsNotNone(result)
        # Should succeed (either via Docker or host fallback)
        self.assertIn("compat_check", result.stdout)

    def test_get_backend_returns_docker_sandbox_backend(self) -> None:
        from src.container import get_backend, DockerSandboxBackend
        backend = get_backend()
        self.assertIsInstance(backend, DockerSandboxBackend)

    def test_docker_sandbox_backend_existing_api(self) -> None:
        """DockerSandboxBackend(no args) still works exactly as before."""
        from src.container import DockerSandboxBackend
        backend = DockerSandboxBackend()
        backend._available = False  # Force fallback
        result = backend.execute_command("echo legacy")
        self.assertEqual(result.returncode, 0)
        self.assertIn("legacy", result.stdout)

    def test_docker_ephemeral_backend_alias(self) -> None:
        """DockerEphemeralBackend is an alias for DockerSandboxBackend."""
        from src.container import DockerEphemeralBackend, DockerSandboxBackend
        self.assertIs(DockerEphemeralBackend, DockerSandboxBackend)

    def test_get_session_returns_docker_session(self) -> None:
        """get_session() returns a DockerSession singleton."""
        from src.container import get_session, DockerSession
        # Reset module singleton for clean test
        import src.container as _mod
        orig = _mod._session
        _mod._session = None
        try:
            session = get_session()
            self.assertIsInstance(session, DockerSession)
            # Same object on second call
            self.assertIs(get_session(), session)
        finally:
            _mod._session = orig


if __name__ == "__main__":
    unittest.main()
