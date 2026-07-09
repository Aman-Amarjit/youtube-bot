import os
import base64
import shutil
import subprocess
import tempfile
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
        subprocess.run(["pip", "install", "-U", "yt-dlp"], check=True, capture_output=True)
        _yt_dlp_updated = True
        print("yt-dlp successfully upgraded.")
    except Exception as e:
        print(f"WARNING: Failed to upgrade yt-dlp: {e}. Proceeding with existing version.")

def _get_cookies_file() -> str | None:
    """
    Writes the YOUTUBE_COOKIES_B64 env var (base64-encoded Netscape cookies.txt)
    to a temporary file and returns its path. Returns None if not set.
    """
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "").strip()
    if not cookies_b64:
        return None
    try:
        cookies_bytes = base64.b64decode(cookies_b64)
        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".txt", delete=False, prefix="yt_cookies_"
        )
        tmp.write(cookies_bytes)
        tmp.flush()
        tmp.close()
        print(f"YouTube cookies written to {tmp.name}")
        return tmp.name
    except Exception as e:
        print(f"WARNING: Failed to decode YOUTUBE_COOKIES_B64: {e}. Downloading without cookies.")
        return None

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
    
    output_template = os.path.join(temp_dir, f"{video_id}.%(ext)s")
    final_path = os.path.join(temp_dir, f"{video_id}.mp4")
    
    if os.path.exists(final_path):
        try:
            os.remove(final_path)
        except Exception:
            pass
            
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    cookies_file = _get_cookies_file()
    
    # When cookies are provided, only the web client supports cookie auth.
    # ios/android clients skip cookies and fall back to image-only format lists.
    if cookies_file:
        player_client_arg = "web"
    else:
        player_client_arg = "ios,android,web"

    # Pre-flight: check if video has actual video formats (not image-only posts)
    check_cmd = [
        "yt-dlp",
        "--no-warnings",
        "--extractor-args", f"youtube:player_client={player_client_arg}",
        "-J",           # dump JSON info only, no download
        "--skip-download",
    ]
    if cookies_file:
        check_cmd += ["--cookies", cookies_file]
    check_cmd.append(url)
    
    check_res = subprocess.run(check_cmd, capture_output=True, text=True)
    if check_res.returncode == 0:
        try:
            import json as _json
            info = _json.loads(check_res.stdout)
            formats = info.get("formats", [])
            has_video = any(
                f.get("vcodec", "none") not in ("none", None) and
                f.get("ext") not in ("jpg", "jpeg", "png", "webp")
                for f in formats
            )
            if not has_video:
                raise DownloadError(f"Video {video_id} has no downloadable video formats (image-only or community post).")
        except DownloadError:
            raise
        except Exception:
            pass  # If JSON parse fails, proceed and let yt-dlp handle it

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--sleep-interval", "2",
        "--extractor-retries", "3",
        "--no-playlist",
        "--extractor-args", f"youtube:player_client={player_client_arg}",
        "-o", output_template,
    ]
    
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    
    cmd.append(url)
    
    max_attempts = 4
    cookies_cleanup_done = False
    
    try:
        for attempt in range(max_attempts):
            print(f"Downloading video {video_id} (Attempt {attempt+1}/{max_attempts})...")
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            if res.returncode == 0:
                if os.path.exists(final_path):
                    print(f"Download succeeded: {final_path}")
                    return os.path.abspath(final_path)
                else:
                    for filename in os.listdir(temp_dir):
                        if filename.startswith(video_id) and filename.endswith(".mp4"):
                            found_path = os.path.abspath(os.path.join(temp_dir, filename))
                            print(f"Download succeeded (resolved path): {found_path}")
                            return found_path
                            
                print("WARNING: yt-dlp succeeded but output file was not found.")
            else:
                print(f"Download attempt {attempt+1} failed: returncode={res.returncode}")
                print(f"yt-dlp stderr: {res.stderr[-2000:]}")
                
            if attempt < max_attempts - 1:
                time.sleep(2)
                
        raise DownloadError(f"Failed to download video {video_id} after {max_attempts} attempts.")
    finally:
        # Clean up the temporary cookies file
        if cookies_file and not cookies_cleanup_done:
            try:
                os.remove(cookies_file)
            except Exception:
                pass

def cleanup(config: GameConfig) -> None:
    """Cleans up all temp files under tmp/{game_slug}/."""
    temp_dir = f"tmp/{config.game_slug}"
    if os.path.exists(temp_dir):
        print(f"Cleaning up temp folder: {temp_dir}")
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"WARNING: Failed to clean up temp folder {temp_dir}: {e}")
