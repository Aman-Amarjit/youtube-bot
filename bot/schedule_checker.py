from bot.config_loader import GameConfig

def check(config: GameConfig, **kwargs) -> None:
    """
    Schedule check is now a no-op.
    
    Game selection is handled at the GitHub Actions workflow level by randomly
    choosing one enabled game config per run. There is no per-game time-window
    gating needed inside the Python pipeline.
    """
    pass
