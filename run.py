import sys
from bot.pipeline import run_pipeline

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run.py <path_to_game_config_yaml>")
        sys.exit(1)
        
    config_path = sys.argv[1]
    run_pipeline(config_path)
