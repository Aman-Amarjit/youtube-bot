import os
import json
import subprocess
from bot.config_loader import GameConfig

def has_audio_stream(video_path: str) -> bool:
    """Uses ffprobe to check if the video contains an audio stream."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "json",
        video_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            data = json.loads(res.stdout)
            return len(data.get("streams", [])) > 0
        except Exception:
            pass
    return False

def generate_edge_tts(text: str, output_path: str) -> bool:
    """Fallback 1: Microsoft Edge TTS (remote)."""
    print("Attempting edge-tts...")
    # Clean output if exists
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
            
    # Run CLI command
    cmd = ["edge-tts", "--text", text, "--write-media", output_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print("edge-tts generation succeeded.")
            return True
    except Exception as e:
        print(f"edge-tts failed: {e}")
    return False

def generate_piper(text: str, output_path: str) -> bool:
    """Fallback 2: Piper (local offline)."""
    print("Attempting Piper...")
    # Piper expects an ONNX model file. We look in models/ or download.
    # To keep it generic and avoid giant downloads during run, we assume
    # the piper CLI and a default model might be installed, or we check for it.
    model_path = "models/en_US-lessac-medium.onnx"
    if not os.path.exists(model_path):
        print(f"Piper model not found at {model_path}. Skipping Piper.")
        return False
        
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
            
    try:
        # Run piper command, piping text to stdin
        p1 = subprocess.Popen(["echo", text], stdout=subprocess.PIPE)
        p2 = subprocess.Popen(
            ["piper", "--model", model_path, "--output_file", output_path],
            stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        p1.stdout.close()
        stdout, stderr = p2.communicate()
        if p2.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print("Piper generation succeeded.")
            return True
        else:
            print(f"Piper failed with code {p2.returncode}: {stderr.decode('utf-8')}")
    except Exception as e:
        print(f"Piper execution failed: {e}")
    return False

def generate_gtts(text: str, output_path: str) -> bool:
    """Fallback 3: Google Translate TTS (remote)."""
    print("Attempting gTTS...")
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass
            
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='en')
        tts.save(output_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print("gTTS generation succeeded.")
            return True
    except Exception as e:
        print(f"gTTS failed: {e}")
    return False

def apply(script: str, video_path: str, config: GameConfig) -> str:
    """
    Stage 11: TTS Audio generation and mixing.
    Generates audio for `script` using edge-tts -> Piper -> gTTS fallback chain.
    Ducks original audio and mixes TTS audio.
    If TTS completely fails, warns 'voiceover-unavailable' and returns original video.
    """
    game_slug = config.game_slug
    temp_dir = f"tmp/{game_slug}"
    os.makedirs(temp_dir, exist_ok=True)
    
    tts_audio_path = os.path.join(temp_dir, "tts_voice.mp3")
    output_video_path = os.path.abspath(os.path.join(temp_dir, "video_with_audio.mp4"))
    
    # Clean up pre-existing files
    for p in [tts_audio_path, output_video_path]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    # TTS generation fallback chain
    success = False
    if generate_edge_tts(script, tts_audio_path):
        success = True
    elif generate_piper(script, tts_audio_path):
        # Note: Piper wav output can also be processed normally by ffmpeg
        success = True
    elif generate_gtts(script, tts_audio_path):
        success = True
        
    if not success:
        print("WARNING: voiceover-unavailable. Proceeding without narration.")
        return video_path
        
    # Mix TTS audio with video using ffmpeg
    has_audio = has_audio_stream(video_path)
    
    if has_audio:
        # Duck original audio (0.15 volume) and mix with TTS audio (1.2 volume)
        # Use a filter complex to blend the streams
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", tts_audio_path,
            "-filter_complex", "[0:a]volume=0.15[a1];[1:a]volume=1.2[a2];[a1][a2]amix=inputs=2:duration=first[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_video_path
        ]
    else:
        # Simply map the TTS audio stream as the primary audio track
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", tts_audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_video_path
        ]
        
    print(f"Mixing audio using ffmpeg: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if res.returncode != 0:
        print(f"WARNING: Failed to mix TTS audio. ffmpeg stderr: {res.stderr}")
        # Proceed with original un-narrated video
        return video_path
        
    if not os.path.exists(output_video_path):
        print("WARNING: mixed output file not written. Proceeding without narration.")
        return video_path
        
    # Remove local temp audio file
    try:
        os.remove(tts_audio_path)
    except Exception:
        pass
        
    print(f"TTS voiceover successfully mixed: {output_video_path}")
    return output_video_path
