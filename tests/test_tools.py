"""Tests for xyz-local tools."""

from xyz_local.tools import (
    _human_size,
    normalize_path,
    delete_file,
    move_file,
    multi_edit,
    directory_tree,
    file_info,
    python_check,
    extract_symbols,
    which_command,
    todo_write,
)


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


def test_file_info(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a\nb\nc\n")
    info = file_info(str(f))
    assert info["type"] == "file"
    assert info["lines"] == 3
    assert "size_human" in info


def test_directory_tree(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.py").write_text("x = 1")
    (tmp_path / "top.txt").write_text("hi")
    result = directory_tree(str(tmp_path), max_depth=2)
    assert "sub/" in result["tree"]
    assert "a.py" in result["tree"]
    assert "top.txt" in result["tree"]


def test_python_check_valid(tmp_path):
    f = tmp_path / "ok.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    assert python_check(str(f))["valid"] is True


def test_python_check_invalid(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def add(a, b)\n    return a + b\n")  # missing colon
    result = python_check(str(f))
    assert result["valid"] is False
    assert "error" in result


def test_extract_symbols(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import os\n\nclass Foo:\n    def bar(self):\n        pass\n\ndef top():\n    pass\n")
    syms = extract_symbols(str(f))["symbols"]
    kinds = {(s["type"], s["name"]) for s in syms}
    assert ("class", "Foo") in kinds
    assert ("method", "Foo.bar") in kinds
    assert ("function", "top") in kinds


def test_which_command():
    result = which_command("python3")
    assert result["found"] in (True, False)  # platform-dependent but must not error
    assert "path" in result


def test_todo_write():
    result = todo_write([
        {"content": "task one", "status": "pending"},
        {"content": "task two", "status": "completed"},
    ])
    assert result["total"] == 2
    assert result["completed"] == 1


def test_multi_edit(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("alpha = 1\nbeta = 2\n")
    result = multi_edit(str(f), [
        {"old_string": "alpha", "new_string": "first"},
        {"old_string": "beta", "new_string": "second"},
    ])
    assert result["success"] is True
    assert "first = 1" in f.read_text()
    assert "second = 2" in f.read_text()


def test_multi_edit_ambiguous(tmp_path):
    f = tmp_path / "dup.txt"
    f.write_text("x x x")
    result = multi_edit(str(f), [{"old_string": "x", "new_string": "y"}])
    assert "error" in result  # 'x' appears multiple times


def test_delete_file_dangerous_path():
    assert "error" in delete_file("/etc/passwd")


def test_delete_file_with_backup(tmp_path):
    f = tmp_path / "gone.txt"
    f.write_text("bye")
    result = delete_file(str(f))
    assert result["success"] is True
    assert not f.exists()
    assert (tmp_path / "gone.txt.bak").exists()


def test_move_file_dangerous_dest(tmp_path):
    f = tmp_path / "src.txt"
    f.write_text("data")
    assert "error" in move_file(str(f), "/usr/should_not_write")
