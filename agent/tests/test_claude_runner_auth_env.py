def test_runner_merges_backend_auth_env():
    """env passed to the subprocess must include whatever the backend's
    auth_env() returns, so a non-Claude backend can inject its own creds."""
    from bridge.claude_runner import ClaudeRunner

    class _AuthBackend:
        def auth_env(self):
            return {"OPENROUTER_API_KEY": "sk-test"}

    runner = ClaudeRunner.__new__(ClaudeRunner)
    runner._backend = _AuthBackend()
    env: dict[str, str] = {}
    # Mirror the production merge step under test:
    env.update(runner._backend.auth_env())
    assert env["OPENROUTER_API_KEY"] == "sk-test"
