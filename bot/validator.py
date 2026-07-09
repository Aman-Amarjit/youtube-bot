import re
import os
from typing import List, Dict, Any, Optional
from bot.config_loader import GameConfig
from bot.duplicate_guard import check_posted_state
from bot.quota_guard import make_api_call, DiscoveryQuotaLimitReached
from bot.exceptions import PipelineExit

def parse_duration_to_seconds(duration_str: str) -> int:
    """Parses an ISO 8601 duration string (e.g. PT1M15S) into total seconds."""
    if not duration_str:
        return 0
    pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    match = pattern.match(duration_str)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds

def load_blocklist_keywords(config: GameConfig) -> List[str]:
    """Loads blocklist keywords either from config.blocklist_inline or config.blocklist_path."""
    keywords = []
    if config.blocklist_inline:
        keywords = config.blocklist_inline
    elif config.blocklist_path and os.path.isfile(config.blocklist_path):
        try:
            with open(config.blocklist_path, "r", encoding="utf-8") as f:
                keywords = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"WARNING: Failed to read blocklist file {config.blocklist_path}: {e}")
    return keywords

def is_blocked(text: str, keywords: List[str]) -> bool:
    """Checks if any case-insensitive keyword from the blocklist is present in the text."""
    if not text or not keywords:
        return False
    text_lower = text.lower()
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean in text_lower:
            return True
    return False

def validate(candidates: List[Dict[str, Any]], config: GameConfig, service) -> Optional[Dict[str, Any]]:
    """
    Stage 4: Sequential candidate validation.
    Returns the first candidate that passes all checks, or raises PipelineExit if none do.
    """
    if not candidates:
        raise PipelineExit("no-valid-candidate", should_alert=False, message="No candidates discovered.")
        
    blocklist_keywords = load_blocklist_keywords(config)
    selected_candidate = None
    
    for candidate in candidates:
        video_id = candidate["video_id"]
        title = candidate["title"]
        description = candidate["description"]
        
        # Check 1: Not already in posted.json
        if check_posted_state(video_id, config):
            print(f"Candidate {video_id} failed: already in posted.json")
            continue
            
        # Check 2: Duration >= 15 seconds
        try:
            # Query videos.list to get contentDetails.duration (1 unit cost)
            request = service.videos().list(
                part="contentDetails",
                id=video_id
            )
            # counts_toward_discovery=True applies pre-call gates and commits quota post-call
            response = make_api_call(
                service, request, cost=1, config=config,
                counts_toward_discovery=True
            )
            
            items = response.get("items", [])
            if not items:
                print(f"Candidate {video_id} failed: details not found via API")
                continue
                
            duration_str = items[0].get("contentDetails", {}).get("duration", "")
            duration_sec = parse_duration_to_seconds(duration_str)
            
            if duration_sec < 15:
                print(f"Candidate {video_id} failed: duration {duration_sec}s is < 15s")
                continue
                
            # Cache duration in candidate dict for later editor/trimming stages
            candidate["duration_seconds"] = duration_sec
            
        except DiscoveryQuotaLimitReached:
            # Graceful degrade: cannot check duration for this or any remaining candidates.
            # Stop validating further.
            print("INFO: Per-game discovery quota limit hit during validation. Discontinuing validation loop.")
            break
            
        # Check 3: Content Blocklist check on title & description
        if is_blocked(title, blocklist_keywords):
            print(f"Candidate {video_id} failed: title contains blocked keywords")
            continue
            
        if is_blocked(description, blocklist_keywords):
            print(f"Candidate {video_id} failed: description contains blocked keywords")
            continue
            
        # Passed all checks!
        selected_candidate = candidate
        break
        
    if selected_candidate is None:
        raise PipelineExit("no-valid-candidate", should_alert=False, message="No candidate passed validation checks.")
        
    return selected_candidate
