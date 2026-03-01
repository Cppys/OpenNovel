"""Self-updater for OpenNovel — pulls latest code from git remote."""

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root: directory containing pyproject.toml
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_current_version() -> str:
    """Read the current version from pyproject.toml."""
    toml_path = _PROJECT_ROOT / "pyproject.toml"
    if not toml_path.exists():
        return "unknown"
    for line in toml_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version"):
            # version = "0.2.0"
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "unknown"


def _run_git(*args: str, cwd: Path = _PROJECT_ROOT) -> tuple[int, str]:
    """Run a git command and return (returncode, output)."""
    cmd = ["git"] + list(args)
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=60,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return -1, "git not found — please install git"
    except subprocess.TimeoutExpired:
        return -2, "git command timed out"


def is_git_repo() -> bool:
    """Check if the project root is a git repository."""
    rc, _ = _run_git("rev-parse", "--is-inside-work-tree")
    return rc == 0


def check_for_updates() -> dict:
    """Check if there are updates available on the remote.

    Returns dict with keys:
        has_updates (bool): True if remote has new commits.
        current_commit (str): Short hash of current HEAD.
        remote_commit (str): Short hash of remote HEAD.
        behind_count (int): Number of commits behind.
        current_version (str): Current version string.
        error (str): Error message if check failed.
    """
    result = {
        "has_updates": False,
        "current_commit": "",
        "remote_commit": "",
        "behind_count": 0,
        "current_version": get_current_version(),
        "error": "",
    }

    if not is_git_repo():
        result["error"] = "当前目录不是 git 仓库"
        return result

    # Fetch latest from remote
    rc, out = _run_git("fetch", "--quiet")
    if rc != 0:
        result["error"] = f"fetch 失败: {out}"
        return result

    # Get current branch
    rc, branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        result["error"] = f"获取当前分支失败: {branch}"
        return result
    branch = branch.strip()

    # Get current commit
    rc, current = _run_git("rev-parse", "--short", "HEAD")
    if rc != 0:
        result["error"] = f"获取当前 commit 失败: {current}"
        return result
    result["current_commit"] = current.strip()

    # Get remote commit
    remote_ref = f"origin/{branch}"
    rc, remote = _run_git("rev-parse", "--short", remote_ref)
    if rc != 0:
        result["error"] = f"获取远程 commit 失败: {remote}"
        return result
    result["remote_commit"] = remote.strip()

    # Count commits behind
    rc, count_out = _run_git("rev-list", "--count", f"HEAD..{remote_ref}")
    if rc == 0:
        try:
            result["behind_count"] = int(count_out.strip())
        except ValueError:
            pass

    result["has_updates"] = result["behind_count"] > 0
    return result


def get_update_log() -> str:
    """Get the log of incoming commits (what will be updated)."""
    rc, branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return ""
    branch = branch.strip()
    rc, log = _run_git(
        "log", "--oneline", "--no-decorate",
        f"HEAD..origin/{branch}",
    )
    return log if rc == 0 else ""


def apply_update() -> dict:
    """Pull the latest changes and reinstall dependencies.

    Returns dict with keys:
        success (bool): True if update succeeded.
        message (str): Human-readable result message.
        new_version (str): Version after update (if successful).
    """
    result = {"success": False, "message": "", "new_version": ""}

    if not is_git_repo():
        result["message"] = "当前目录不是 git 仓库"
        return result

    # Check for uncommitted changes
    rc, status = _run_git("status", "--porcelain")
    if rc != 0:
        result["message"] = f"git status 失败: {status}"
        return result

    # Pull latest
    rc, out = _run_git("pull", "--ff-only")
    if rc != 0:
        if "not possible to fast-forward" in out or "diverged" in out:
            result["message"] = (
                "本地有未合并的修改，无法自动更新。\n"
                "请手动执行: git pull --rebase"
            )
        else:
            result["message"] = f"git pull 失败: {out}"
        return result

    # Reinstall package
    rc_pip, pip_out = _pip_install()
    if rc_pip != 0:
        result["message"] = f"代码已更新但依赖安装失败: {pip_out}"
        result["success"] = True  # Code updated, just deps failed
        result["new_version"] = get_current_version()
        return result

    result["success"] = True
    result["new_version"] = get_current_version()
    result["message"] = f"更新成功！当前版本: {result['new_version']}"
    return result


def _pip_install() -> tuple[int, str]:
    """Reinstall the package in editable mode."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True, text=True, timeout=120,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "pip install timed out"
    except Exception as e:
        return -1, str(e)
