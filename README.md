# YouTube Shorts Automation Bot 🤖🎬

A fully autonomous YouTube Shorts creation and upload bot powered by AI. It runs entirely on **GitHub Actions** workflows daily, scheduling, editing, transcribing, and uploading gaming clips without requiring any dedicated hosting server.

## Features

- **Automated Discovery:** Queries YouTube search for creative commons or allowed channel clips, filtering previously uploaded content.
- **Dynamic Portraiting:** Center-crops 16:9 landscape game clips into 9:16 vertical Shorts using custom `ffmpeg` overlays.
- **AI-Generated Voiceovers:** Transcribes audio using **Whisper** and writes custom narration scripts using local **LLaVA / Llama3** LLMs, then vocalizes using **Edge-TTS / Piper**.
- **Dynamic Subtitles:** Generates and burns SRT subtitles directly onto the center of the video clip with ducked background game audio.
- **Pillow Thumbnails:** Renders custom text overlay JPEGs for video thumbnail presentation.
- **Resumable Chunked Upload:** Handles large media uploads with AI disclosure metadata compliance flags automatically.
- **Git State Database:** Saves posted video history and daily api quota usages directly into your repository commits via a robust retry-rebase git loop.

---

## Workspace Structure

- `bot/` - Core Python pipeline modules.
- `games/` - Game configuration templates (e.g. `minecraft.yml`, `gta.yml`).
- `blocklists/` - Shared keyword blocklists.
- `tests/` - Unit tests for code verification.
- `.github/workflows/pipeline.yml` - Hourly matrix GHA pipeline runner.

---

## Setup & Configuration

### 1. GitHub Secrets
Add the following secrets to your GitHub repository:
- `YOUTUBE_OAUTH_JSON`: The OAuth JSON credentials block generated during authentication.
- `GROQ_API_KEY`: Groq Cloud API Key for script-writing LLM fallback.
- `ALERT_WEBHOOK_URL` (Optional): Discord/Slack Webhook URL to send pipeline alerts.

### 2. Run Locally
To run tests or test the pipeline locally:
```bash
# Create and activate virtual environment
python3 -m venv test_venv
source test_venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run unit tests
python3 -m unittest tests/test_bot.py

# Check authorized channel
python3 check_channel.py

# Run pipeline for a specific game config manually
python3 run.py games/minecraft.yml
```
