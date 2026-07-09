from datetime import datetime
from bot.config_loader import GameConfig
from bot.validator import load_blocklist_keywords, is_blocked
from bot import script_writer

def check(script: str, config: GameConfig, candidate: dict, transcript: str, visuals: list) -> str:
    """
    Stage 10: Content Filter. Checks generated script against case-insensitive blocklist.
    If blocked, tries up to 2 additional regenerations.
    If still blocked after 3 total attempts, falls back to the safe static template.
    """
    keywords = load_blocklist_keywords(config)
    if not keywords:
        # No blocklist keywords loaded, script is safe
        return script
        
    # Check 1st attempt (input script)
    if not is_blocked(script, keywords):
        return script
        
    print("WARNING: Generated script failed content blocklist check.")
    
    # Try up to 2 additional regenerations (attempts 2 and 3)
    for attempt in range(1, 3):
        print(f"Regenerating script (Attempt {attempt+1}/3)...")
        # Generate again
        script = script_writer.generate(config, candidate, transcript, visuals)
        if not is_blocked(script, keywords):
            print(f"Regenerated script passed blocklist check on attempt {attempt+1}.")
            return script
            
    # If all 3 attempts fail blocklist validation, fall back to safe static template
    print("WARNING: Script failed blocklist check after 3 attempts. Using safe static template.")
    published_date = candidate.get("published_at", "")
    if published_date:
        try:
            dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%B %d, %Y")
        except Exception:
            date_str = "recently"
    else:
        date_str = "recently"
        
    safe_script = f"Incredible play in {config.game_name}! Don't miss this amazing moment captured {date_str}."
    return safe_script
