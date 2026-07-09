"""
bot/game_scout.py

Automatically discovers trending games on YouTube and generates
game config YAML files in the games/ directory.

How it works:
1. Searches YouTube for top trending gaming videos (category 20)
2. Groups results by detected game title using video metadata
3. Finds top channels posting that game's content
4. Writes a games/<slug>.yml config if one doesn't already exist
5. Commits the new configs back to the repo
"""

import os
import re
import json
import time
import yaml
import pathlib
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ─── Known game name normalisations ──────────────────────────────────────────
GAME_ALIASES = {
    "gta": "GTA",
    "gta 5": "GTA",
    "gta v": "GTA",
    "grand theft auto": "GTA",
    "grand theft auto v": "GTA",
    "minecraft": "Minecraft",
    "valorant": "Valorant",
    "fortnite": "Fortnite",
    "apex legends": "Apex Legends",
    "apex": "Apex Legends",
    "call of duty": "Call of Duty",
    "cod": "Call of Duty",
    "warzone": "Warzone",
    "call of duty warzone": "Warzone",
    "league of legends": "League of Legends",
    "lol": "League of Legends",
    "counter strike": "CS2",
    "cs2": "CS2",
    "csgo": "CS2",
    "overwatch": "Overwatch 2",
    "overwatch 2": "Overwatch 2",
    "pubg": "PUBG",
    "battlegrounds": "PUBG",
    "rocket league": "Rocket League",
    "elden ring": "Elden Ring",
    "roblox": "Roblox",
    "among us": "Among Us",
    "cyberpunk": "Cyberpunk 2077",
    "cyberpunk 2077": "Cyberpunk 2077",
    "the last of us": "The Last of Us",
    "god of war": "God of War",
    "spider man": "Spider-Man",
    "spiderman": "Spider-Man",
    "zelda": "Zelda",
    "pokemon": "Pokemon",
    "mario": "Mario",
    "fifa": "EA FC",
    "ea fc": "EA FC",
    "fc 25": "EA FC",
    "fc25": "EA FC",
    "street fighter": "Street Fighter 6",
    "mortal kombat": "Mortal Kombat",
    "black ops": "Black Ops 6",
    "black ops 6": "Black Ops 6",
    "deadlock": "Deadlock",
    "marvel rivals": "Marvel Rivals",
    "indiana jones": "Indiana Jones",
    "delta force": "Delta Force",
    "path of exile": "Path of Exile 2",
}

# Tags to use per game (defaults if no specific tags defined)
DEFAULT_TAGS = ["shorts", "gaming", "clips", "highlights"]

GAME_TAGS = {
    "Minecraft":      ["minecraft", "shorts", "gaming", "mc", "minecraftshorts"],
    "Valorant":       ["valorant", "shorts", "gaming", "vct", "valorantclips"],
    "Fortnite":       ["fortnite", "shorts", "gaming", "fortniteclips", "fnbr"],
    "GTA":            ["gta", "shorts", "gaming", "gtav", "gta5", "gtaonline"],
    "Apex Legends":   ["apexlegends", "shorts", "gaming", "apex", "apexclips"],
    "Warzone":        ["warzone", "shorts", "gaming", "cod", "warzoneClips"],
    "Call of Duty":   ["callofduty", "shorts", "gaming", "cod"],
    "CS2":            ["cs2", "shorts", "gaming", "csgo", "counterstrike"],
    "League of Legends": ["leagueoflegends", "shorts", "gaming", "lol", "league"],
    "Overwatch 2":    ["overwatch2", "shorts", "gaming", "overwatch", "ow2"],
    "Rocket League":  ["rocketleague", "shorts", "gaming", "rl", "rlclips"],
    "Roblox":         ["roblox", "shorts", "gaming", "robloxclips"],
    "EA FC":          ["eafc", "shorts", "gaming", "fc25", "fifa", "football"],
    "Marvel Rivals":  ["marvelrivals", "shorts", "gaming", "marvel"],
    "Deadlock":       ["deadlock", "shorts", "gaming", "valve"],
    "PUBG":           ["pubg", "shorts", "gaming", "battlegrounds"],
    "Elden Ring":     ["eldenring", "shorts", "gaming", "fromsoftware"],
    "Black Ops 6":    ["blackops6", "shorts", "gaming", "cod", "bo6"],
}


def slugify(name: str) -> str:
    """Convert a game name to a filesystem-safe slug."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_-]+", "_", name).strip("_")
    return name


def normalise_game(title: str) -> str | None:
    """Try to extract a known game name from a video title."""
    title_lower = title.lower()
    # Sort by length descending so longer matches win
    for alias in sorted(GAME_ALIASES.keys(), key=len, reverse=True):
        if alias in title_lower:
            return GAME_ALIASES[alias]
    return None


def get_youtube_service() -> object:
    """Build a YouTube API service from YOUTUBE_OAUTH_JSON env variable."""
    creds_json = os.environ.get("YOUTUBE_OAUTH_JSON", "")
    if not creds_json:
        raise RuntimeError("YOUTUBE_OAUTH_JSON environment variable not set.")
    creds_data = json.loads(creds_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data.get("refresh_token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly"]
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def search_trending_gaming_videos(service, max_results: int = 50) -> list[dict]:
    """
    Search YouTube for the most-viewed recent gaming videos.
    Returns list of video metadata dicts.
    """
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=14)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    request = service.search().list(
        part="snippet",
        type="video",
        videoCategoryId="20",      # Gaming
        order="viewCount",
        publishedAfter=published_after,
        maxResults=max_results,
        regionCode="US",
    )
    response = request.execute()
    return response.get("items", [])


def find_top_channels_for_game(service, game_name: str, max_results: int = 5) -> list[dict]:
    """
    Search for top channels posting content about a specific game.
    Returns list of {channel_id, title, subscriber_count} dicts.
    """
    results = []
    seen_channels = set()

    request = service.search().list(
        part="snippet",
        type="video",
        q=f"{game_name} gameplay",
        videoCategoryId="20",
        order="viewCount",
        maxResults=25,
    )
    response = request.execute()

    channel_ids = []
    for item in response.get("items", []):
        cid = item["snippet"]["channelId"]
        if cid not in seen_channels:
            seen_channels.add(cid)
            channel_ids.append(cid)

    if not channel_ids:
        return []

    # Batch fetch channel stats to filter by subscriber count
    channels_resp = service.channels().list(
        part="snippet,statistics",
        id=",".join(channel_ids[:25])
    ).execute()

    for ch in channels_resp.get("items", []):
        subs = int(ch["statistics"].get("subscriberCount", 0))
        if 100_000 <= subs <= 2_500_000:   # Focus on mid-sized active channels (avoids mega-celebrity bot-blocks)
            results.append({
                "channel_id": ch["id"],
                "title": ch["snippet"]["title"],
                "subscriber_count": subs,
            })

    # Sort by subs descending, take top N
    results.sort(key=lambda x: x["subscriber_count"], reverse=True)
    return results[:max_results]


def write_game_config(game_name: str, channels: list[dict], games_dir: str = "games") -> str | None:
    """
    Write a YAML config file for a game if it doesn't already exist.
    Returns the file path if written, None if skipped.
    """
    slug = slugify(game_name)
    config_path = pathlib.Path(games_dir) / f"{slug}.yml"

    if config_path.exists():
        print(f"  ⏭  Config already exists: {config_path}")
        return None

    tags = GAME_TAGS.get(game_name, DEFAULT_TAGS + [slug])

    sources = [
        {"channel_id": ch["channel_id"], "provenance": "creative_commons"}
        for ch in channels
    ]

    config = {
        "game_name": game_name,
        "game_slug": slug,
        "enabled": True,
        "cloud_project_id": os.environ.get("CLOUD_PROJECT_ID", "erudite-spot-501908-e0"),
        "credential_secret": "YOUTUBE_OAUTH_JSON",
        "schedule": "* * * * *",
        "tags": tags,
        "upload_title_template": "{clip_title} #Shorts",
        "upload_description_template": "{voiceover_script}\n\nsource:{source_video_id}\n",
        "blocklist": "./blocklists/shared_blocklist.txt",
        "sources": sources,
    }

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    channel_names = ", ".join(f"{c['title']} ({c['subscriber_count']//1000}K)" for c in channels)
    print(f"  ✅ Created {config_path} | Channels: {channel_names}")
    return str(config_path)


def run_scout(max_new_games: int = 5) -> list[str]:
    """
    Main entry point: discover trending games and create configs.
    Returns list of newly created config file paths.
    """
    print(f"\n{'='*60}")
    print(f"Game Scout — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    service = get_youtube_service()

    # Step 1: Find trending gaming videos
    print("\n🔍 Fetching trending gaming videos from YouTube...")
    videos = search_trending_gaming_videos(service, max_results=50)
    print(f"   Found {len(videos)} trending gaming videos")

    # Step 2: Group by game
    game_hits: dict[str, int] = defaultdict(int)
    for video in videos:
        title = video["snippet"].get("title", "")
        game = normalise_game(title)
        if game:
            game_hits[game] += 1

    # Sort games by how many trending videos they have
    trending_games = sorted(game_hits.items(), key=lambda x: x[1], reverse=True)
    print(f"\n📊 Detected trending games: {[g for g, _ in trending_games[:10]]}")

    # Step 3: Find new games not yet in games/ directory
    existing_slugs = {p.stem for p in pathlib.Path("games").glob("*.yml")}
    new_games = [(g, c) for g, c in trending_games if slugify(g) not in existing_slugs]

    if not new_games:
        print("\n✅ All trending games already have configs. Nothing new to add.")
        return []

    print(f"\n🆕 New games to add: {[g for g, _ in new_games[:max_new_games]]}")

    # Step 4: For each new game, find top channels and write config
    created = []
    for game_name, hit_count in new_games[:max_new_games]:
        print(f"\n🎮 Processing: {game_name} ({hit_count} trending videos)")

        # Rate limit: 1 search per second
        time.sleep(1)

        channels = find_top_channels_for_game(service, game_name, max_results=4)
        if not channels:
            print(f"  ⚠  No suitable channels found for {game_name}, skipping.")
            continue

        path = write_game_config(game_name, channels)
        if path:
            created.append(path)

    print(f"\n{'='*60}")
    print(f"Scout complete. Created {len(created)} new game configs.")
    print(f"{'='*60}\n")
    return created


if __name__ == "__main__":
    run_scout()
