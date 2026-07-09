import os
import json
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from bot.config_loader import GameConfig
from bot.exceptions import PipelineExit

def get_youtube_service(config: GameConfig):
    """
    Builds and returns an authorized YouTube Data API service client.
    Handles auto-refreshing. Raises PipelineExit("invalid-grant") on authentication failures.
    """
    secret_name = config.credential_secret
    creds_json_str = os.environ.get("YOUTUBE_OAUTH_JSON") or os.environ.get(secret_name)
    if not creds_json_str:
        raise PipelineExit(
            "invalid-grant",
            should_alert=True,
            message=f"YouTube OAuth credentials environment secret '{secret_name}' (or 'YOUTUBE_OAUTH_JSON') is not set."
        )
        
    try:
        creds_data = json.loads(creds_json_str)
        # Setup credentials with refresh token
        creds = Credentials(
            token=None,  # Will be resolved and refreshed on use
            refresh_token=creds_data["refresh_token"],
            client_id=creds_data["client_id"],
            client_secret=creds_data["client_secret"],
            token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token")
        )
    except Exception as e:
        raise PipelineExit(
            "invalid-grant",
            should_alert=True,
            message=f"Failed to parse credentials JSON string from secret {secret_name}: {e}"
        )
        
    try:
        # Build client service. Standard discovery build triggers auto-refresh.
        service = build("youtube", "v3", credentials=creds)
        # Test connection by making a cheap dummy call (e.g. channels list for self)
        # to force token refresh and validate token grant early.
        service.channels().list(part="id", mine=True).execute()
        return service
    except Exception as e:
        err_msg = str(e).lower()
        if "invalid_grant" in err_msg or "unauthorized" in err_msg or "401" in err_msg or "403" in err_msg:
            raise PipelineExit(
                "invalid-grant",
                should_alert=True,
                message=f"YouTube OAuth refresh token rejected (invalid_grant/unauthorized): {e}"
            )
        # Other API or network error
        raise e

def upload(video_path: str, thumbnail_path: str, script: str, candidate: dict, config: GameConfig, service) -> str:
    """
    Stage 16: Resumable video upload + thumbnail upload.
    Returns the uploaded YouTube Video ID on success.
    """
    candidate_id = candidate["video_id"]
    candidate_title = candidate.get("title", "Awesome Clip")
    
    # 1. Format Title (truncated to 100 character limit)
    raw_title = config.upload_title_template.format(clip_title=candidate_title)
    if len(raw_title) > 100:
        # Retain trailing tags like #Shorts if possible
        # e.g., if template was "{clip_title} #Shorts"
        # We truncate clip_title segment and rebuild
        tags_index = config.upload_title_template.find("{clip_title}")
        if tags_index != -1:
            template_suffix = config.upload_title_template[tags_index + len("{clip_title}"):]
            max_clip_len = 100 - len(template_suffix)
            truncated_clip = candidate_title[:max_clip_len].strip()
            title = f"{truncated_clip}{template_suffix}"
        else:
            title = raw_title[:100]
    else:
        title = raw_title
        
    # 2. Format Description
    description = config.upload_description_template.format(
        voiceover_script=script,
        source_video_id=candidate_id
    )
    
    print(f"Uploading video to YouTube: Title='{title}'")
    
    # 3. Resumable Upload
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024  # 1MB chunk size
    )
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": config.tags,
            "categoryId": "20"  # Gaming
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True  # Compliance with AI content disclosure
        }
    }
    
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )
    
    video_id = None
    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")
        except Exception as e:
            # Handle invalid grant during upload chunks too
            if "invalid_grant" in str(e).lower():
                raise PipelineExit(
                    "invalid-grant",
                    should_alert=True,
                    message=f"YouTube OAuth refresh token expired mid-upload: {e}"
                )
            raise e
            
    if response and "id" in response:
        video_id = response["id"]
        print(f"Video uploaded successfully. Video ID: {video_id}")
    else:
        raise RuntimeError(f"Video upload completed but response was empty or missing ID: {response}")
        
    # 4. Optional Thumbnail Upload
    if thumbnail_path and os.path.exists(thumbnail_path):
        print(f"Uploading thumbnail {thumbnail_path} for video {video_id}...")
        try:
            # thumbnails.set costs 1 unit
            thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            service.thumbnails().set(
                videoId=video_id,
                media_body=thumb_media
            ).execute()
            print("Thumbnail successfully uploaded.")
        except Exception as e:
            # Stage 13 failure guideline: log warning and continue without raising
            print(f"WARNING: Thumbnail upload failed: {e}. Pipeline will continue normally.")
            
    return video_id
