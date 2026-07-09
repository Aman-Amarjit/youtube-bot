import os
import json
from bot.git_utils import read_from_remote_head
from bot.state_writer import commit_state
from bot.quota_guard import make_api_call
from bot.exceptions import PipelineExit
from bot.config_loader import GameConfig

def merge_pending_posted_if_exists() -> None:
    """
    Check if state/pending_posted.json exists. If so, attempt to merge
    its content into state/posted.json and delete the pending file upon success.
    """
    pending_path = "state/pending_posted.json"
    posted_path = "state/posted.json"
    
    if not os.path.exists(pending_path):
        return
        
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            pending_data = json.load(f)
    except Exception as e:
        print(f"WARNING: Failed to read pending posted data from {pending_path}: {e}")
        return
        
    if not pending_data:
        # File is empty, just clean it up
        try:
            os.remove(pending_path)
        except Exception:
            pass
        return
        
    print(f"Merging pending posted video records from {pending_path} to {posted_path}...")
    try:
        # Commit the pending data into posted.json
        commit_state(posted_path, pending_data, max_retries=10, backoff_type="exponential")
        
        # Delete pending file on success
        os.remove(pending_path)
        print("Successfully merged pending posted records.")
    except Exception as e:
        print(f"WARNING: Failed to merge pending posted records: {e}")

def check_posted_state(candidate_id: str, config: GameConfig) -> bool:
    """
    Layer 1 check: returns True if candidate_id is already recorded in state/posted.json
    for this game_slug.
    """
    posted_data = read_from_remote_head("state/posted.json")
    posted_list = posted_data.get(config.game_slug, [])
    return candidate_id in posted_list

def api_check(service, candidate_id: str, config: GameConfig) -> None:
    """
    Layer 2 API-backed check (Stage 15): Query own channel's uploaded videos and search
    descriptions for 'source:{candidate_id}'.
    This cost is 1 unit and is charged solely to the project-level counter (not discovery).
    """
    # Note: uploads_playlist_id must be resolved or provided. We get it from config
    # or look it up during auth. We assume config has uploads_playlist_id.
    playlist_id = getattr(config, "uploads_playlist_id", None)
    if not playlist_id:
        # Fallback or bypass if uploads playlist ID is missing
        print("WARNING: config.uploads_playlist_id not set; skipping Layer 2 duplicate check.")
        return
        
    request = service.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    )
    
    # counts_toward_discovery=False: charged to project total only (Req 18.4)
    response = make_api_call(
        service, request, cost=1, config=config,
        counts_toward_discovery=False
    )
    
    for item in response.get("items", []):
        description = item.get("snippet", {}).get("description", "")
        if f"source:{candidate_id}" in description:
            raise PipelineExit("api-duplicate-blocked")
