import sys
import os
import shutil
import subprocess

import pytest

# Prepend Python's Scripts directory to PATH for headless test environments
scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
if os.path.exists(scripts_dir):
    os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")

pytestmark = pytest.mark.skipif(shutil.which("pygit") is None, reason="pygit console script not installed")


def run_pygit(cwd, *args):
    result = subprocess.run(["pygit", *args], cwd=cwd, capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return result.stdout


def test_full_workflow_init_through_log(tmp_path):
    run_pygit(str(tmp_path), "init")
    (tmp_path / "file.txt").write_text("v1\n")
    run_pygit(str(tmp_path), "add", "file.txt")
    run_pygit(str(tmp_path), "commit", "-m", "first commit")

    run_pygit(str(tmp_path), "branch", "feature")
    run_pygit(str(tmp_path), "checkout", "feature")
    (tmp_path / "file.txt").write_text("v2\n")
    run_pygit(str(tmp_path), "add", "file.txt")
    run_pygit(str(tmp_path), "commit", "-m", "second commit")

    run_pygit(str(tmp_path), "checkout", "main")
    assert (tmp_path / "file.txt").read_text() == "v1\n"

    log_output = run_pygit(str(tmp_path), "log")
    assert "first commit" in log_output

    branch_output = run_pygit(str(tmp_path), "branch")
    assert "main" in branch_output
    assert "feature" in branch_output
