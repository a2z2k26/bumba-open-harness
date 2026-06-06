"""Tests for main module."""

from src.main import main


def test_main(capsys) -> None:
    """Test main function runs without errors."""
    main()
    captured = capsys.readouterr()
    assert "Hello from" in captured.out
