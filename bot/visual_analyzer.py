import os
import base64
import subprocess
import requests
from typing import List
from bot.config_loader import GameConfig

def extract_frame(video_path: str, timestamp_sec: float, output_path: str) -> None:
    """Extract a single frame from the video at timestamp_sec and save it as JPEG."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"WARNING: Failed to extract frame at {timestamp_sec}s. ffmpeg stderr: {res.stderr}")

def get_base64_image(image_path: str) -> str:
    """Encodes a local file as a raw base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def query_llava(b64_image: str, prompt: str, model_name: str = "llava") -> str:
    """Sends a request to local Ollama LLaVA endpoint with keep_alive=0."""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "images": [b64_image],
        "stream": False,
        "keep_alive": 0  # CRITICAL: unload LLaVA immediately after inference
    }
    
    try:
        res = requests.post(url, json=payload, timeout=90)
        if res.status_code == 200:
            return res.json().get("response", "").strip()
        else:
            print(f"WARNING: Ollama API returned status code {res.status_code}: {res.text}")
    except Exception as e:
        print(f"WARNING: Failed to contact Ollama LLaVA service: {e}")
        
    return "Visual description unavailable."

def analyze(video_path: str, candidate: dict, config: GameConfig) -> List[str]:
    """
    Stage 8: Visual Analysis. Extract 3 frames and describe them using local LLaVA.
    Returns a list of 3 concise descriptions.
    """
    if os.environ.get("DISABLE_VISUAL_ANALYSIS", "").lower() == "true":
        print("Visual analysis disabled via environment variable.")
        return ["Visual analysis disabled."] * 3

    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    duration = candidate.get("duration_seconds", 30)
    timestamps = [duration * 0.25, duration * 0.50, duration * 0.75]
    descriptions = []
    
    prompt = "Describe this game scene concisely, listing any players, actions, text on screen, or UI elements."
    llava_model = getattr(config, "llava_model", "llava")
    
    for i, ts in enumerate(timestamps, 1):
        image_path = os.path.join(temp_dir, f"frame_{i}.jpg")
        
        # Cleanup pre-existing frame if any
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception:
                pass
                
        extract_frame(video_path, ts, image_path)
        
        if os.path.exists(image_path):
            print(f"Extracted frame {i} at {ts:.2f}s. Requesting LLaVA analysis...")
            b64_img = get_base64_image(image_path)
            desc = query_llava(b64_img, prompt, model_name=llava_model)
            descriptions.append(desc)
            
            # Delete local frame immediately to conserve disk
            try:
                os.remove(image_path)
            except Exception:
                pass
        else:
            descriptions.append("Visual frame unavailable.")
            
    print("Visual analysis complete.")
    return descriptions
