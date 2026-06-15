"""Tests for xyz-local tools."""

from xyz_local.tools import _human_size, normalize_path


def test_human_size_bytes():
    assert _human_size(0) == "0B"
    assert _human_size(100) == "100B"
    assert _human_size(1023) == "1023B"


def test_human_size_kb():
    result = _human_size(1024)
    assert "KB" in result


def test_human_size_mb():
    result = _human_size(1048576)
    assert "MB" in result


def test_normalize_path_home():
    p = normalize_path("~")
    assert str(p).startswith("/")
    assert p.exists()
