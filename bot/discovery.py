import re
from datetime import datetime
from typing import List, Dict, Any
from bot.exceptions import PipelineExit
from bot.config_loader import GameConfig, SourceConfig
from bot.quota_guard import make_api_call, DiscoveryQuotaLimitReached
from bot.duplicate_guard import check_posted_state

def extract_video_id_from_url(url: str) -> str:
    """Extracts the YouTube video ID from a URL."""
    if not url:
        return ""
    # Matches patterns like youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID, etc.
    pattern = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else ""

def get_channel_uploads_playlist(service, channel_id: str, config: GameConfig) -> str:
    """Get the uploads playlist ID for a given channel ID."""
    request = service.channels().list(
        part="contentDetails",
        id=channel_id
    )
    # counts_toward_discovery=True: counts against discovery budget (1 unit)
    response = make_api_call(service, request, cost=1, config=config, counts_toward_discovery=True)
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Channel {channel_id} not found or contentDetails missing.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

def fetch_videos_details(service, video_ids: List[str], config: GameConfig) -> List[Dict[str, Any]]:
    """Fetch statistics and snippet details for a batch of video IDs."""
    if not video_ids:
        return []
        
    # We batch up to 50 IDs per call (costs 1 unit)
    # If there are more than 50, we slice to the first 50.
    ids_slice = video_ids[:50]
    
    request = service.videos().list(
        part="snippet,statistics,contentDetails",
        id=",".join(ids_slice)
    )
    response = make_api_call(service, request, cost=1, config=config, counts_toward_discovery=True)
    return response.get("items", [])

def run(config: GameConfig, service) -> List[Dict[str, Any]]:
    """
    Stage 3: Discover candidates from config sources, rank them, and return up to 3 candidates.
    Catches DiscoveryQuotaLimitReached to gracefully degrade and return partial candidates.
    """
    candidates = []
    
    try:
        for source in config.sources:
            if source.channel_id:
                # 1. Resolve uploads playlist ID
                try:
                    uploads_playlist_id = get_channel_uploads_playlist(service, source.channel_id, config)
                except Exception as e:
                    print(f"WARNING: Failed to get uploads playlist for channel {source.channel_id}: {e}")
                    continue
                    
                # 2. Get recent playlist items (uploads)
                playlist_request = service.playlistItems().list(
                    part="snippet",
                    playlistId=uploads_playlist_id,
                    maxResults=50
                )
                playlist_response = make_api_call(service, playlist_request, cost=1, config=config, counts_toward_discovery=True)
                items = playlist_response.get("items", [])
                if not items:
                    continue
                    
                # Filter out items already posted before fetching stats to conserve quota
                unposted_items = []
                video_ids = []
                for item in items:
                    v_id = item.get("snippet", {}).get("resourceId", {}).get("videoId", "")
                    if v_id and not check_posted_state(v_id, config):
                        unposted_items.append(item)
                        video_ids.append(v_id)
                        
                if not video_ids:
                    continue
                    
                # 3. Batch fetch statistics to compute channel average
                try:
                    video_details = fetch_videos_details(service, video_ids, config)
                except Exception as e:
                    print(f"WARNING: Failed to fetch video details: {e}")
                    continue
                    
                # Calculate channel average views from these details
                views = []
                for detail in video_details:
                    v_views = int(detail.get("statistics", {}).get("viewCount", 0))
                    views.append(v_views)
                    
                channel_avg = sum(views) / len(views) if views else 1.0
                
                # Create candidates with quality ratio
                for detail in video_details:
                    v_id = detail.get("id")
                    v_views = int(detail.get("statistics", {}).get("viewCount", 0))
                    ratio = v_views / channel_avg if channel_avg > 0 else 1.0
                    
                    candidates.append({
                        "video_id": v_id,
                        "title": detail.get("snippet", {}).get("title", ""),
                        "description": detail.get("snippet", {}).get("description", ""),
                        "published_at": detail.get("snippet", {}).get("publishedAt", ""),
                        "view_count": v_views,
                        "ratio": ratio,
                        "provenance": source.provenance
                    })
                    
            elif source.url:
                v_id = extract_video_id_from_url(source.url)
                if not v_id:
                    print(f"WARNING: Invalid YouTube source URL: {source.url}")
                    continue
                    
                if check_posted_state(v_id, config):
                    continue
                    
                # Fetch statistics for this direct video
                try:
                    details = fetch_videos_details(service, [v_id], config)
                except Exception as e:
                    print(f"WARNING: Failed to fetch direct video details: {e}")
                    continue
                    
                if details:
                    detail = details[0]
                    candidates.append({
                        "video_id": v_id,
                        "title": detail.get("snippet", {}).get("title", ""),
                        "description": detail.get("snippet", {}).get("description", ""),
                        "published_at": detail.get("snippet", {}).get("publishedAt", ""),
                        "view_count": int(detail.get("statistics", {}).get("viewCount", 0)),
                        "ratio": 1.0,  # Neutral quality for direct links
                        "provenance": source.provenance
                    })
                    
    except DiscoveryQuotaLimitReached:
        # Graceful degrade: stop discovery loop, proceed to validation stage
        # with whatever candidates have already been gathered so far.
        print("INFO: Per-game discovery quota limit (50 units) hit. Degrading gracefully.")
        
    # Rank candidates:
    # 1. Published date (most recent first). We parse published_at to sort cleanly.
    # 2. Ratio relative to channel average (highest first).
    def sorting_key(cand):
        pub_date = cand["published_at"]
        # Parse ISO 8601 string, e.g. 2026-07-09T08:00:00Z -> replace Z with UTC
        try:
            dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            timestamp = dt.timestamp()
        except Exception:
            timestamp = 0.0
        return (timestamp, cand["ratio"])
        
    candidates.sort(key=sorting_key, reverse=True)
    
    # Return up to 3 ranked candidates
    return candidates[:3]
