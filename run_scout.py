"""
run_scout.py — Entry point for the game discovery scout.
Called by .github/workflows/scout.yml
"""
import sys
import subprocess
from bot.game_scout import run_scout
from bot.git_utils import run_git

def main():
    created = run_scout(max_new_games=5)

    if not created:
        print("No new game configs created. Exiting.")
        sys.exit(0)

    # Commit and push the new game configs
    print("\n📤 Committing new game configs to repository...")
    try:
        run_git(["add", "games/"])
        
        game_names = [p.split("/")[-1].replace(".yml", "") for p in created]
        commit_msg = f"scout: auto-add {len(created)} new game(s): {', '.join(game_names)}"
        
        run_git(["config", "user.email", "bot@youtube-bot.ai"])
        run_git(["config", "user.name", "Game Scout Bot"])
        run_git(["commit", "-m", commit_msg])
        run_git(["push", "origin", "main"])
        
        print(f"✅ Pushed {len(created)} new game config(s) to repository!")
        print(f"   Games: {', '.join(game_names)}")
    except Exception as e:
        print(f"❌ Failed to push new configs: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
