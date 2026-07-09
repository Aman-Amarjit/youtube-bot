from datetime import datetime, timedelta, timezone
from croniter import croniter
from bot.exceptions import PipelineExit
from bot.config_loader import GameConfig

def check(config: GameConfig, now_utc: datetime = None) -> None:
    """
    Check if the current UTC time matches the config schedule cron expression
    within a ±10 minute window. Raises PipelineExit if it does not match.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
        
    cron_expr = config.schedule
    
    # We walk the ±10 minute window relative to now_utc
    # Generate all expected execution times for the cron expression
    # within [now_utc - 10 min, now_utc + 10 min].
    
    start_time = now_utc - timedelta(minutes=10)
    end_time = now_utc + timedelta(minutes=10)
    
    # croniter matches times using float seconds or datetime.
    # To check if cron fires in the window:
    # We can get the next fire time after start_time - 1 second.
    # If that fire time is <= end_time, then it fires inside the window!
    try:
        # We initialize croniter at (start_time - 1 second)
        base = start_time - timedelta(seconds=1)
        iter = croniter(cron_expr, base)
        next_fire = iter.get_next(datetime)
        
        if next_fire <= end_time:
            # Match found!
            return
    except Exception as e:
        # Fallback or invalid cron pattern error
        raise PipelineExit(
            "schedule-not-matched",
            should_alert=False,
            message=f"Failed to parse cron '{cron_expr}' or evaluate schedule window: {e}"
        )
        
    # If no trigger time fell in the window
    raise PipelineExit(
        "schedule-not-matched",
        should_alert=False,
        message=f"Current time {now_utc.isoformat()} does not match cron schedule '{cron_expr}' (±10 min window)"
    )
