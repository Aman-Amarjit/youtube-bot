import os
import gc
from typing import Tuple

def format_srt_time(seconds: float) -> str:
    """Format float seconds to SRT timestamp format: HH:MM:SS,mmm."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def write_srt_file(segments: list, output_path: str) -> None:
    """Write Whisper transcription segments to an SRT file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, 1):
            start_str = format_srt_time(seg.get("start", 0.0))
            end_str = format_srt_time(seg.get("end", 0.0))
            text = seg.get("text", "").strip()
            f.write(f"{idx}\n{start_str} --> {end_str}\n{text}\n\n")

def transcribe(video_path: str, game_slug: str, model_name: str = "base") -> Tuple[str, str]:
    """
    Stage 7: Transcribe video using local CPU Whisper.
    Returns a tuple (plain_text_transcript, srt_file_path).
    Ensures model weights are deleted and garbage collected to stay within memory limits.
    """
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    srt_path = os.path.abspath(os.path.join(temp_dir, "transcript.srt"))
    
    # Clean up pre-existing SRT if any
    if os.path.exists(srt_path):
        try:
            os.remove(srt_path)
        except Exception:
            pass
            
    print(f"Loading Whisper model '{model_name}' on CPU...")
    # Import locally to keep dependencies scoped
    import whisper
    
    # Force CPU device explicitly
    model = whisper.load_model(model_name, device="cpu")
    
    print(f"Transcribing audio from {video_path}...")
    # Transcribe
    result = model.transcribe(video_path)
    
    transcript = result.get("text", "").strip()
    segments = result.get("segments", [])
    
    # Write segments to SRT file
    write_srt_file(segments, srt_path)
    
    # Stage 7 requirement: Release Whisper model weights from memory immediately
    print("Releasing Whisper model memory weights...")
    del model
    gc.collect()
    
    print("Whisper transcription complete.")
    return transcript, srt_path
