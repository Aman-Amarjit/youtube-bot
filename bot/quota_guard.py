import os
import json
import random
import time
from datetime import datetime, timezone
from bot.exceptions import PipelineExit
from bot.config_loader import GameConfig
from bot.git_utils import run_git, read_from_remote_head

class DiscoveryQuotaLimitReached(Exception):
    """Raised when the 50-unit per-game discovery sub-budget is exceeded.
    Caught locally by discovery.py and validator.py to stop making further API calls
    and gracefully degrade, rather than halting the entire pipeline run."""
    pass

def today_utc() -> str:
    """Returns today's date in YYYY-MM-DD format (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_api_call(data: dict, date: str, cloud_project_id: str, game_slug: str, cost: int, counts_toward_discovery: bool) -> dict:
    """
    Day-rollover guard and atomic counter increments.
    """
    data.setdefault(date, {"projects": {}, "discovery": {}})
    
    # Always increment the project-level counter (real Google quota consumed)
    projects_dict = data[date]["projects"]
    projects_dict[cloud_project_id] = projects_dict.get(cloud_project_id, 0) + cost
    
    # Only increment the per-game discovery sub-budget for discovery-class calls.
    if counts_toward_discovery:
        discovery_dict = data[date]["discovery"]
        discovery_dict[game_slug] = discovery_dict.get(game_slug, 0) + cost
        
    return data

def check_pre_upload(config: GameConfig) -> None:
    """
    Stage 14 gate: raises PipelineExit if the project has fewer than 1,600 units
    remaining (required for one videos.insert call).
    """
    data = read_from_remote_head("state/quota.json")
    date = today_utc()
    data.setdefault(date, {"projects": {}, "discovery": {}})
    project_used = data[date]["projects"].get(config.cloud_project_id, 0)
    if 9500 - project_used < 1600:
        raise PipelineExit("quota-exhausted")

def check_discovery_gate(config: GameConfig, cost: int) -> None:
    """
    Pre-call gate: checks thresholds before making a discovery API call.
    Raises PipelineExit("quota-reserved-for-upload") for project-level limits (hard stop).
    Raises DiscoveryQuotaLimitReached for per-game discovery cap (graceful degrade).
    """
    data = read_from_remote_head("state/quota.json")
    date = today_utc()
    data.setdefault(date, {"projects": {}, "discovery": {}})
    project_used = data[date]["projects"].get(config.cloud_project_id, 0)
    discovery_used = data[date]["discovery"].get(config.game_slug, 0)
    
    if project_used + cost > 8400:
        raise PipelineExit("quota-reserved-for-upload")
        
    if discovery_used + cost > 500:
        raise DiscoveryQuotaLimitReached()

def commit_quota(cloud_project_id: str, game_slug: str, cost: int, counts_toward_discovery: bool, max_retries: int = 5) -> None:
    """
    Fetch -> re-apply delta -> push -> retry on conflict loop for state/quota.json.
    """
    path = "state/quota.json"
    for attempt in range(max_retries):
        # Fetch latest origin/main
        run_git(["fetch", "origin", "main"])
        data = read_from_remote_head(path)
        
        # Apply the increment
        updated = record_api_call(
            data, today_utc(), cloud_project_id, game_slug, cost,
            counts_toward_discovery=counts_toward_discovery
        )
        
        # Write local file
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2)
            
        # Commit local transaction
        run_git(["add", path])
        # Use --allow-empty in case there's no logical change (though cost > 0 ensures it)
        run_git(["commit", "-m", f"bot: quota +{cost} [{game_slug}]", "--allow-empty"])
        
        # Attempt push to remote
        # We try pushing HEAD to main to support both local branch and detached HEAD environments.
        res_push = run_git(["push", "origin", "HEAD:main"])
        if res_push.success:
            return
            
        # On push failure (conflict), reset local state to match remote origin/main and retry
        run_git(["reset", "--hard", "origin/main"])
        
        # Random backoff jitter
        jitter = random.uniform(1, 10)
        time.sleep(jitter)
        
    print("WARNING: repository-write-conflict in commit_quota")

def make_api_call(service, request, cost: int, config: GameConfig, counts_toward_discovery: bool):
    """
    Shared wrapper to perform pre-gate checking, execute the API request,
    and immediately commit the cost to state/quota.json.
    """
    if counts_toward_discovery:
        check_discovery_gate(config, cost)
        
    response = request.execute()
    
    commit_quota(
        cloud_project_id=config.cloud_project_id,
        game_slug=config.game_slug,
        cost=cost,
        counts_toward_discovery=counts_toward_discovery
    )
    
    return response
