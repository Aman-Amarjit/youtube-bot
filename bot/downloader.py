import os
import shutil
import subprocess
import time
from bot.config_loader import GameConfig

class DownloadError(Exception):
    """Raised when all download attempts for a candidate fail."""
    pass

_yt_dlp_updated = False

def _upgrade_yt_dlp() -> None:
    """Upgrades yt-dlp to the latest version before downloading."""
    global _yt_dlp_updated
    if _yt_dlp_updated:
        return
        
    print("Upgrading yt-dlp to the latest version...")
    try:
        # Run pip install -U yt-dlp
        subprocess.run(["pip", "install", "-U", "yt-dlp"], check=True, capture_output=True)
        _yt_dlp_updated = True
        print("yt-dlp successfully upgraded.")
    except Exception as e:
        print(f"WARNING: Failed to upgrade yt-dlp: {e}. Proceeding with existing version.")

def download(candidate: dict, config: GameConfig) -> str:
    """
    Stage 5: Download the selected candidate video.
    Returns the absolute path to the downloaded MP4 video file.
    Raises DownloadError if download fails after 4 attempts.
    """
    _upgrade_yt_dlp()
    
    video_id = candidate["video_id"]
    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    # We want to output an MP4 file at tmp/{game_slug}/{video_id}.mp4
    # yt-dlp merge-output-format guarantees it merges video/audio into mp4.
    output_template = os.path.join(temp_dir, f"{video_id}.%(ext)s")
    final_path = os.path.join(temp_dir, f"{video_id}.mp4")
    
    # Cleanup pre-existing files for this ID if any
    if os.path.exists(final_path):
        try:
            os.remove(final_path)
        except Exception:
            pass
            
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", output_template,
        url
    ]
    
    max_attempts = 4
    for attempt in range(max_attempts):
        print(f"Downloading video {video_id} (Attempt {attempt+1}/{max_attempts})...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode == 0:
            # Locate the downloaded file
            # In some cases, yt-dlp might download directly as mp4 or mkv and merge.
            # If final_path exists, we're good.
            if os.path.exists(final_path):
                print(f"Download succeeded: {final_path}")
                return os.path.abspath(final_path)
            else:
                # Find any file starting with video_id in the temp directory
                for filename in os.listdir(temp_dir):
                    if filename.startswith(video_id) and filename.endswith(".mp4"):
                        found_path = os.path.abspath(os.path.join(temp_dir, filename))
                        print(f"Download succeeded (resolved path): {found_path}")
                        return found_path
                        
            print("WARNING: yt-dlp succeeded but output file was not found.")
        else:
            print(f"Download attempt {attempt+1} failed: returncode={res.returncode}")
            print(f"yt-dlp stderr: {res.stderr}")
            
        if attempt < max_attempts - 1:
            time.sleep(2)
            
    raise DownloadError(f"Failed to download video {video_id} after {max_attempts} attempts.")

def cleanup(config: GameConfig) -> None:
    """Cleans up all temp files under tmp/{game_slug}/."""
    temp_dir = f"tmp/{config.game_slug}"
    if os.path.exists(temp_dir):
        print(f"Cleaning up temp folder: {temp_dir}")
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"WARNING: Failed to clean up temp folder {temp_dir}: {e}")
