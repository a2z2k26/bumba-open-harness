"""Phase 1 integration tests (S44): verify all 3 modules work together."""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.config import load_config
from bridge.database import Database
from bridge.formatting import format_response


class TestNoCircularImports:
    """Verify modules can all be imported together."""

    def test_import_all(self):
        from bridge import config, database, formatting
        assert config.BridgeConfig is not None
        assert database.Database is not None
        assert formatting.format_response is not None


class TestConfigToDatabase:
    """Config → Database wiring."""

    @pytest.mark.asyncio
    async def test_config_provides_db_path(self, sample_config_toml, mock_keyring, tmp_dirs):
        config = load_config(sample_config_toml)
        db_path = Path(config.data_dir) / "memory.db"

        db = Database(db_path)
        await db.connect()
        await db.migrate()

        health = await db.health_check()
        assert health["integrity_ok"] is True
        assert health["table_counts"]["knowledge"] == 0

        await db.close()

    @pytest.mark.asyncio
    async def test_config_db_size_thresholds(self, sample_config_toml, mock_keyring, tmp_dirs):
        config = load_config(sample_config_toml)
        db_path = Path(config.data_dir) / "memory.db"

        db = Database(db_path)
        await db.connect()
        await db.migrate()

        health = await db.health_check()
        assert health["db_size_bytes"] < config.db_size_warn
        assert health["db_size_bytes"] < config.db_size_alert

        await db.close()


class TestFormatRoundTrip:
    """Formatting pipeline end-to-end."""

    def test_markdown_to_chunks(self):
        md = (
            "# Status Report\n\n"
            "**All systems operational.**\n\n"
            "- Memory: `128MB` used\n"
            "- Uptime: 24h\n\n"
            "```python\ndef health():\n    return True\n```\n\n"
            "See [docs](https://example.com) for more."
        )
        chunks = format_response(md)
        assert len(chunks) >= 1
        full = " ".join(chunks)
        # Discord is markdown-native: formatting is preserved as-is
        assert "**All systems operational.**" in full
        assert "`128MB`" in full
        assert "```python" in full
        assert "[docs](https://example.com)" in full

    def test_long_response_splits_correctly(self):
        md = "**Header**\n\n" + ("Line of text. " * 400) + "\n\n```\ncode block\n```"
        chunks = format_response(md)
        assert len(chunks) > 1
        for chunk in chunks:
            # Each chunk should be under the limit (with some tolerance for tags)
            assert len(chunk) < 5000


class TestDatabaseWithFormatting:
    """Store formatted content in database."""

    @pytest.mark.asyncio
    async def test_store_formatted_response(self, migrated_db):
        md = "**Hello** from Bumba! Here's some `code`."
        chunks = format_response(md)
        formatted = "\n".join(chunks)

        await migrated_db.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("sess-001", "chat-001", "assistant", formatted),
        )
        await migrated_db.commit()

        row = await migrated_db.fetchone(
            "SELECT content FROM conversations WHERE session_id = ?", ("sess-001",)
        )
        # Discord is markdown-native: stored content preserves markdown
        assert "**Hello**" in row[0]
        assert "`code`" in row[0]
