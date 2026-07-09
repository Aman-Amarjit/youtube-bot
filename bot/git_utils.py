import os
import json
import subprocess

class GitResult:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.success = (returncode == 0)
        self.stdout = stdout.strip()
        self.stderr = stderr.strip()

def run_git(args: list) -> GitResult:
    """Run a git command in the current directory and return the result."""
    res = subprocess.run(["git"] + args, capture_output=True, text=True)
    return GitResult(res.returncode, res.stdout, res.stderr)

def read_from_remote_head(path: str) -> dict:
    """
    Read a state file from the origin/main remote HEAD.
    If not found on remote, falls back to local file or empty dict.
    """
    # Fetch origin main to ensure we have the latest remote tracking branch
    run_git(["fetch", "origin", "main"])
    res = run_git(["show", f"origin/main:{path}"])
    if res.success:
        try:
            return json.loads(res.stdout)
        except Exception:
            pass
            
    # Fallback to local file if remote fetch failed or file doesn't exist on remote
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
            
    return {}
