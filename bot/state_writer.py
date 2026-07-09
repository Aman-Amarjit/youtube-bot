import os
import json
import random
import time
from bot.git_utils import run_git, read_from_remote_head
from bot.exceptions import PipelineExit

def deep_merge(base: dict, incoming: dict) -> dict:
    """
    Recursively merge `incoming` into `base`.
    - For nested dicts: recurse key-by-key.
    - For lists: union (deduplicated) — used for posted.json clip-ID lists.
    - For all other scalars: incoming wins.
    """
    result = dict(base)
    for key, incoming_val in incoming.items():
        if key in result:
            base_val = result[key]
            if isinstance(base_val, dict) and isinstance(incoming_val, dict):
                result[key] = deep_merge(base_val, incoming_val)
            elif isinstance(base_val, list) and isinstance(incoming_val, list):
                # Union: preserve all IDs from both sides (duplicate-safe)
                seen = set()
                result[key] = [x for x in base_val + incoming_val
                               if not (x in seen or seen.add(x))]
            else:
                result[key] = incoming_val  # incoming wins
        else:
            result[key] = incoming_val
    return result

def write_pending_posted(new_value: dict) -> None:
    """
    Fallback when state/posted.json write fails after 10 retries.
    Appends the new posted IDs to state/pending_posted.json locally.
    """
    path = "state/pending_posted.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    current = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            pass
            
    merged = deep_merge(current, new_value)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

def commit_state(filepath: str, new_value: dict, max_retries: int, backoff_type: str) -> None:
    """
    Commit non-counter state files using git fetch -> merge -> push -> retry on conflict loop.
    """
    for attempt in range(max_retries):
        run_git(["fetch", "origin", "main"])
        current = read_from_remote_head(filepath)
        merged = deep_merge(current, new_value)
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            
        run_git(["add", filepath])
        run_git(["commit", "-m", f"bot: update {filepath}", "--allow-empty"])
        
        res_push = run_git(["push", "origin", "HEAD:main"])
        if res_push.success:
            return
            
        # Conflict: reset local changes and backoff
        run_git(["reset", "--hard", "origin/main"])
        
        if backoff_type == "exponential":
            # base 2s, ±1s jitter, cap 60s
            delay = min(60.0, (2.0 ** attempt) + random.uniform(-1.0, 1.0))
            if delay < 1.0:
                delay = 1.0
        else:
            # Random jitter 1-10s
            delay = random.uniform(1.0, 10.0)
            
        time.sleep(delay)
        
    # If all retries fail
    print(f"WARNING: repository-write-conflict for {filepath}")
    if filepath == "state/posted.json":
        write_pending_posted(new_value)
        raise PipelineExit("posted-write-failed", should_alert=True)
    else:
        raise PipelineExit("repository-write-conflict", should_alert=True)
