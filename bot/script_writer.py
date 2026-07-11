import os
import requests
from datetime import datetime, timezone
from bot.config_loader import GameConfig

def query_ollama_text(prompt: str, model_name: str = "llama3") -> str:
    """Attempt to generate script via local Ollama."""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "keep_alive": 0  # Unload immediately to save RAM
    }
    try:
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json().get("response", "").strip()
    except Exception as e:
        print(f"INFO: Local Ollama generation failed/unavailable: {e}")
    return ""

def query_groq_text(prompt: str) -> str:
    """Attempt to generate script via Groq API (fallback 1)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("INFO: GROQ_API_KEY not found in environment. Skipping Groq fallback.")
        return ""
        
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-8b-8192",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=20)
        if res.status_code == 200:
            choices = res.json().get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
        else:
            print(f"WARNING: Groq API returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"INFO: Groq API generation failed: {e}")
    return ""

def generate(config: GameConfig, candidate: dict, transcript: str, visuals: list) -> str:
    """
    Stage 9: Generate a 2-sentence voiceover script using a fallback chain:
    1. Local Ollama (llama3)
    2. Groq API (llama3-8b-8192)
    3. Static Template fallback
    """
    game_name = config.game_name
    player_metadata = candidate.get("channel_title", "the player")
    visual_descriptions = "; ".join(visuals) if visuals else "No visual analysis available."
    
    prompt = (
        "You are writing a punchy 2-sentence voiceover for a YouTube Shorts gaming clip.\n"
        f"Game: {game_name}\n"
        f"Player: {player_metadata}\n"
        f"Transcript: {transcript or 'No voice transcript available.'}\n"
        f"Visual context: {visual_descriptions}\n\n"
        "Write exactly 2 sentences. Be energetic and concise. Do NOT include any intro, outro, headers, or quotes. Output ONLY the 2 sentences of voiceover script."
    )
    
    # 1. Try Ollama (local llama3) if visual analysis is not disabled
    if os.environ.get("DISABLE_VISUAL_ANALYSIS", "").lower() != "true":
        ollama_model = getattr(config, "ollama_model", "llama3")
        script = query_ollama_text(prompt, model_name=ollama_model)
        if script:
            print(f"Script generated via local Ollama ({ollama_model}): {script}")
            return script
        
    # 2. Try Groq (remote fallback)
    script = query_groq_text(prompt)
    if script:
        print(f"Script generated via Groq API (llama3-8b-8192): {script}")
        return script
        
    # 3. Static Template fallback
    published_date = candidate.get("published_at", "")
    if published_date:
        try:
            dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%B %d, %Y")
        except Exception:
            date_str = "recently"
    else:
        date_str = "recently"
        
    script = f"Incredible play in {game_name}! Don't miss this amazing moment captured {date_str}."
    print(f"Script generated via static template: {script}")
    return script
