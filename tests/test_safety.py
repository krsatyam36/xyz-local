"""Tests for xyz-local safety system."""

from xyz_local.safety import classify_command, PermissionTier, is_suspicious_pip_install


def test_auto_approve_ls():
    result = classify_command("ls -la")
    assert result.tier == PermissionTier.AUTO


def test_auto_approve_git_status():
    result = classify_command("git status")
    assert result.tier == PermissionTier.AUTO


def test_ask_rm():
    result = classify_command("rm file.txt")
    assert result.tier == PermissionTier.ASK


def test_deny_rm_rf_root():
    result = classify_command("rm -rf /")
    assert result.tier == PermissionTier.DENY


def test_suspicious_pip():
    warning = is_suspicious_pip_install("pip install pytort")
    assert warning is not None


def test_safe_pip():
    warning = is_suspicious_pip_install("pip install requests")
    assert warning is None


def test_trust_mode():
    result = classify_command("rm -rf /tmp/test", trust_mode=True)
    assert result.tier == PermissionTier.AUTO
