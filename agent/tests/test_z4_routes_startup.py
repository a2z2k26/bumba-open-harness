"""Test that Zone4Routes are registered before the API server starts.

This is a regression test for issue #624: all 14 /api/z4/* endpoints were
silently returning 404 because set_zone4_routes() was called AFTER
api_server.start(), which freezes the aiohttp router.
"""
from pathlib import Path


def test_set_zone4_routes_called_before_start():
    """Verify set_zone4_routes is called before _api_server.start() in app.py."""
    src = Path(__file__).parent.parent / "bridge" / "app.py"
    text = src.read_text()

    z4_pos = text.find("set_zone4_routes")
    start_pos = text.find("_api_server.start()")

    assert z4_pos != -1, "set_zone4_routes call not found in app.py"
    assert start_pos != -1, "_api_server.start() call not found in app.py"
    assert z4_pos < start_pos, (
        f"set_zone4_routes (pos {z4_pos}) must appear before "
        f"_api_server.start() (pos {start_pos}) — "
        "otherwise all 14 /api/z4/* endpoints will silently 404 (issue #624)"
    )


def test_set_zone4_routes_inside_api_enabled_block():
    """Verify set_zone4_routes is inside the api_enabled block, not after it."""
    src = Path(__file__).parent.parent / "bridge" / "app.py"
    text = src.read_text()

    # The api_enabled block starts at 'if api_enabled:'
    # and the start() call must come AFTER set_zone4_routes inside it.
    # We confirm by checking relative positions within a 2000-char window.
    api_enabled_pos = text.find("if api_enabled:")
    z4_pos = text.find("set_zone4_routes", api_enabled_pos)
    start_pos = text.find("_api_server.start()", api_enabled_pos)

    assert api_enabled_pos != -1, "'if api_enabled:' block not found in app.py"
    assert z4_pos != -1, "set_zone4_routes not found after 'if api_enabled:'"
    assert start_pos != -1, "_api_server.start() not found after 'if api_enabled:'"
    assert z4_pos < start_pos, (
        "set_zone4_routes must appear before _api_server.start() "
        "within the api_enabled block"
    )


def test_api_server_registers_zone4_during_start():
    """Verify APIServer._register_routes mounts zone4 routes if pre-registered."""
    src = Path(__file__).parent.parent / "bridge" / "api_server.py"
    text = src.read_text()

    # The _register_routes method should now call self._zone4_routes.register(app)
    # when _zone4_routes is already set — this is the forward-compat path.
    assert "_zone4_routes is not None" in text, (
        "api_server.py must check 'self._zone4_routes is not None' inside "
        "_register_routes to mount zone4 routes during start() when they were "
        "pre-registered via set_zone4_routes()"
    )


def test_set_zone4_routes_docstring_updated():
    """Verify the misleading 'Must be called after start()' docstring is gone."""
    src = Path(__file__).parent.parent / "bridge" / "api_server.py"
    text = src.read_text()

    assert "Must be called after ``start()``" not in text, (
        "The old misleading docstring 'Must be called after start()' must be "
        "removed from set_zone4_routes — it was the source of the bug (#624)"
    )
