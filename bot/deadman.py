import os
from datetime import datetime, timezone, timedelta
from bot.config_loader import GameConfig
from bot.git_utils import read_from_remote_head
from bot.state_writer import commit_state
from bot.exceptions import PipelineExit

def parse_iso(dt_str: str) -> datetime:
    """Parses an ISO timestamp string into a timezone-aware datetime."""
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

def get_state_path(config: GameConfig) -> str:
    """Get the path to the deadman state file for this game."""
    return f"state/deadman/{config.game_slug}_state.json"

def load_deadman_state(config: GameConfig) -> dict:
    """Load the deadman state from remote HEAD or fallback to default."""
    path = get_state_path(config)
    state = read_from_remote_head(path)
    
    # Check if empty, populate defaults
    if not state:
        now_str = datetime.now(timezone.utc).isoformat()
        state = {
            "last_success_utc": now_str,
            "paused": False,
            "paused_since_utc": None,
            "cooldown_days": 7
        }
    return state

def check(config: GameConfig) -> None:
    """
    Stage 1: Dead-Man's Switch check.
    Evaluates pipeline health, pauses if inactive for >14 days (raising deadman-alert),
    or exits cleanly with cooldown-in-progress if paused and cooldown hasn't expired.
    Resumes automatically if cooldown has expired.
    """
    state = load_deadman_state(config)
    path = get_state_path(config)
    now = datetime.now(timezone.utc)
    
    paused = state.get("paused", False)
    cooldown_days = state.get("cooldown_days", 7)
    
    if paused:
        paused_since = parse_iso(state.get("paused_since_utc", ""))
        if paused_since:
            elapsed = now - paused_since
            if elapsed >= timedelta(days=cooldown_days):
                # Cooldown expired! Auto-resume and let pipeline run proceed
                print(f"Dead-man switch cooldown ({cooldown_days} days) elapsed. Auto-resuming...")
                state["paused"] = False
                state["paused_since_utc"] = None
                # Update last_success_utc to now to reset 14-day timer for active debugging
                state["last_success_utc"] = now.isoformat()
                
                # Commit updated state (5 retries, random jitter)
                commit_state(path, state, max_retries=5, backoff_type="jitter")
                return
            else:
                # Cooldown still in progress: exit cleanly without alerts
                remaining = timedelta(days=cooldown_days) - elapsed
                msg = f"Game switch is paused. Cooldown in progress: {remaining.days}d {remaining.seconds//3600}h remaining."
                raise PipelineExit("cooldown-in-progress", should_alert=False, message=msg)
        else:
            # Stale state where paused_since_utc is missing, heal it
            state["paused"] = False
            commit_state(path, state, max_retries=5, backoff_type="jitter")
            return
            
    # If not paused, check the 14-day inactivity limit
    last_success = parse_iso(state.get("last_success_utc", ""))
    if last_success:
        inactivity_period = now - last_success
        if inactivity_period > timedelta(days=14):
            # Inactive for >14 days: transition to paused and send alert
            print(f"CRITICAL: No successful run for {inactivity_period.days} days. Tripping dead-man switch.")
            state["paused"] = True
            state["paused_since_utc"] = now.isoformat()
            
            commit_state(path, state, max_retries=5, backoff_type="jitter")
            
            raise PipelineExit(
                "pipeline-paused",
                should_alert=True,
                message=f"Deadman switch tripped! No successful run for {config.game_name} in {inactivity_period.days} days. Cooldown active."
            )

def record_success(config: GameConfig) -> None:
    """
    Stage 17 Success: Update last_success_utc to now and reset pause states.
    Committed at the end of a happy path run.
    """
    path = get_state_path(config)
    now_str = datetime.now(timezone.utc).isoformat()
    
    state = {
        "last_success_utc": now_str,
        "paused": False,
        "paused_since_utc": None,
        "cooldown_days": 7
    }
    
    print(f"Recording pipeline success in {path}...")
    commit_state(path, state, max_retries=5, backoff_type="jitter")
