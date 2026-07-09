import os
import subprocess
from bot.config_loader import GameConfig

def burn(video_path: str, srt_path: str, config: GameConfig) -> str:
    """
    Stage 12: Caption Burn-in.
    Uses ffmpeg 'subtitles' filter to burn SRT onto the video.
    If it fails, logs warning 'no-captions' and continues with original video.
    """
    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    output_path = os.path.abspath(os.path.join(temp_dir, "captioned.mp4"))
    
    # Cleanup pre-existing file if any
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
            
    if not srt_path or not os.path.exists(srt_path):
        print("WARNING: SRT file not found. warn: no-captions; continuing without captions.")
        return video_path
        
    # ffmpeg subtitles filter is sensitive to Windows backslashes and absolute path formats.
    # Standardizing to forward slashes and escaping is necessary.
    # A relative path works best if we execute inside the project workspace directory.
    rel_srt_path = os.path.relpath(srt_path).replace("\\", "/")
    
    # Simple and modern style: Outline, yellow/white text, large size for 9:16 vertical video
    style = "Alignment=2,Outline=2,FontSize=18,PrimaryColour=&H0000FFFF" # Yellow, bottom-centered
    vf_expr = f"subtitles={rel_srt_path}:force_style='{style}'"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", vf_expr,
        "-c:a", "copy",
        output_path
    ]
    
    print(f"Executing ffmpeg caption burn-in: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if res.returncode != 0:
        print(f"WARNING: ffmpeg caption burn-in failed: {res.stderr}")
        print("warn: no-captions; proceeding with uncaptioned video.")
        return video_path
        
    if not os.path.exists(output_path):
        print("WARNING: Captioned file not written. warn: no-captions; proceeding with uncaptioned video.")
        return video_path
        
    print(f"Caption burn-in complete: {output_path}")
    return output_path
