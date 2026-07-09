import os
import json
import subprocess
from bot.config_loader import GameConfig

def get_video_dimensions(video_path: str) -> tuple:
    """Uses ffprobe to query width and height of the video."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json",
        video_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            data = json.loads(res.stdout)
            stream = data["streams"][0]
            return int(stream["width"]), int(stream["height"])
        except Exception as e:
            print(f"WARNING: Failed to parse ffprobe JSON output: {e}")
    return 0, 0

def edit(video_path: str, config: GameConfig) -> str:
    """
    Stage 6: Trim to <= 60 seconds and crop/scale to 9:16 portrait.
    Returns the absolute path to the edited MP4 video file.
    """
    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    output_path = os.path.abspath(os.path.join(temp_dir, "trimmed.mp4"))
    
    # Cleanup pre-existing file if any
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
            
    # Get dimensions
    w, h = get_video_dimensions(video_path)
    print(f"Source video dimensions: {w}x{h}")
    
    if w == 0 or h == 0:
        # Fallback dimensions if probe failed
        w, h = 1920, 1080
        
    ratio = w / h
    target_ratio = 9.0 / 16.0
    
    # Determine the video filter for reframing to 9:16 portrait (720x1280)
    if abs(ratio - target_ratio) < 0.05:
        # Already portrait, just scale to standard 720x1280
        vf = "scale=720:1280"
        print("Video is already portrait. Applying scale only.")
    elif w > h:
        # Landscape video: crop center horizontally, then scale
        new_w = int(h * target_ratio)
        new_w = (new_w // 2) * 2  # Ensure even width for H.264
        x_offset = (w - new_w) // 2
        vf = f"crop={new_w}:{h}:{x_offset}:0,scale=720:1280"
        print(f"Landscape video detected. Applying crop {new_w}x{h} with offset {x_offset}.")
    else:
        # Fallback (e.g. square): pad with black pillars
        vf = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2"
        print("Video layout is non-standard. Applying letterbox/pad.")
        
    # Trim to 60s, crop/scale to 9:16, encode to H.264 and AAC
    cmd = [
        "ffmpeg", "-y",
        "-ss", "0", "-t", "60",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]
    
    print(f"Executing ffmpeg edit command: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if res.returncode != 0:
        print(f"ffmpeg stderr: {res.stderr}")
        raise RuntimeError(f"ffmpeg command failed with exit code {res.returncode}")
        
    if not os.path.exists(output_path):
        raise RuntimeError("ffmpeg completed successfully but trimmed.mp4 was not written.")
        
    print(f"Editing complete: {output_path}")
    return output_path
