import os
import re
import subprocess
from PIL import Image, ImageDraw, ImageFont
from bot.config_loader import GameConfig

def derive_2_word_title(script: str) -> str:
    """Derives a 2-word title from the first sentence of the script."""
    if not script:
        return "MUST WATCH"
    # Take first sentence
    sentences = re.split(r'[.!?]', script)
    first_sentence = sentences[0].strip() if sentences else script
    # Extract alpha-numeric words
    words = [w.strip(" ,.!?\"'") for w in first_sentence.split() if w.strip(" ,.!?\"'")]
    # Clean words and return first 2
    clean_words = [w for w in words if w.isalnum()]
    if not clean_words:
        clean_words = words  # fallback to raw words if alphanumeric filtering cleared all
        
    if len(clean_words) >= 2:
        return f"{clean_words[0]} {clean_words[1]}".upper()
    elif len(clean_words) == 1:
        return clean_words[0].upper()
    return "MUST WATCH"

def get_font(size: int) -> ImageFont.ImageFont:
    """Finds a bold font on the system or falls back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "Arial.ttf"
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        # Try loading by system name
        return ImageFont.truetype("DejaVuSans-Bold", size)
    except Exception:
        pass
        
    return ImageFont.load_default()

def draw_text_with_shadow(draw: ImageDraw.ImageDraw, text: str, position: tuple, font: ImageFont.ImageFont, fill_color: str = "white", shadow_color: str = "black") -> None:
    """Draw text with a strong shadow/outline to ensure readability on arbitrary frames."""
    x, y = position
    # Draw outline/shadow offsets
    offsets = [(-2, -2), (-2, 2), (2, -2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]
    for dx, dy in offsets:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow_color)
    # Draw main text
    draw.text((x, y), text, font=font, fill=fill_color)

def generate(video_path: str, script: str, config: GameConfig) -> str:
    """
    Stage 13: Thumbnail Generation.
    Extracts frame at 25% duration, resizes to 1280x720, overlays bold game name (top)
    and 2-word title (bottom), and saves as JPEG quality 90.
    Returns path to generated JPEG, or None if failed.
    """
    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    raw_frame_path = os.path.join(temp_dir, "raw_thumb_frame.jpg")
    output_path = os.path.abspath(os.path.join(temp_dir, "thumbnail.jpg"))
    
    # Cleanup pre-existing files
    for p in [raw_frame_path, output_path]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    try:
        # 1. Extract frame at 25% duration
        # We can fetch duration using ffprobe if not set, or default to 10s mark
        duration_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        res_dur = subprocess.run(duration_cmd, capture_output=True, text=True)
        duration = 40.0
        if res_dur.returncode == 0:
            try:
                duration = float(res_dur.stdout.strip())
            except Exception:
                pass
                
        timestamp = duration * 0.25
        
        extract_cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-f", "image2",
            raw_frame_path
        ]
        res_extract = subprocess.run(extract_cmd, capture_output=True, text=True)
        if res_extract.returncode != 0 or not os.path.exists(raw_frame_path):
            print(f"WARNING: Failed to extract thumbnail frame. ffmpeg stderr: {res_extract.stderr}")
            return None
            
        # 2. Resize to 1280x720 (YouTube requirement)
        img = Image.open(raw_frame_path)
        # Handle older Pillow versions compat for ANTIALIAS
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.ANTIALIAS
            
        img_resized = img.resize((1280, 720), resample_filter)
        
        # 3. Draw overlays
        draw = ImageDraw.Draw(img_resized)
        
        # Determine fonts
        title_font = get_font(56) # Large font for bottom title
        game_font = get_font(40)  # Medium font for top game name
        
        # Overlay Game Name (Top center-aligned)
        game_text = config.game_name.upper()
        # Use text length to approximate centering
        game_w = draw.textlength(game_text, font=game_font) if hasattr(draw, "textlength") else len(game_text) * 20
        game_pos = ((1280 - game_w) // 2, 40)
        draw_text_with_shadow(draw, game_text, game_pos, game_font, fill_color="white")
        
        # Overlay 2-word title (Bottom center-aligned, yellow)
        two_word_title = derive_2_word_title(script)
        title_w = draw.textlength(two_word_title, font=title_font) if hasattr(draw, "textlength") else len(two_word_title) * 28
        title_pos = ((1280 - title_w) // 2, 580)
        draw_text_with_shadow(draw, two_word_title, title_pos, title_font, fill_color="yellow")
        
        # 4. Save as JPEG quality 90
        img_resized.save(output_path, "JPEG", quality=90)
        print(f"Thumbnail successfully generated: {output_path}")
        
        # Clean up raw frame
        try:
            os.remove(raw_frame_path)
        except Exception:
            pass
            
        return output_path
        
    except Exception as e:
        print(f"WARNING: Thumbnail generation failed: {e}. warn: thumbnail-generation-failed; continuing.")
        return None
