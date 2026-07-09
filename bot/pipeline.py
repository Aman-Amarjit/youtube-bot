import signal
import sys
from bot.exceptions import PipelineExit
from bot import config_loader
from bot import deadman
from bot import schedule_checker
from bot import discovery
from bot import validator
from bot import downloader
from bot import editor
from bot import transcriber
from bot import visual_analyzer
from bot import script_writer
from bot import content_filter
from bot import tts
from bot import caption_burner
from bot import thumbnail_generator
from bot import quota_guard
from bot import duplicate_guard
from bot import uploader
from bot import state_writer
from bot import alerter

def _sigalrm_handler(signum, frame):
    """Callback for SIGALRM timeout."""
    raise TimeoutError("SIGALRM: 45-minute in-process budget exceeded")

def run_pipeline(game_config_path: str) -> None:
    """
    Top-level pipeline orchestrator.
    Executes stages sequentially and manages graceful exit conditions and alarms.
    """
    current_stage = "config_load"
    config = None
    
    # Register 45-minute hard timeout alarm if supported on OS
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _sigalrm_handler)
        signal.alarm(45 * 60)
        
    try:
        # Stage 0: Load config
        config = config_loader.load(game_config_path)
        
        # Check enabled flag immediately
        if not config.enabled:
            print(f"Game '{config.game_name}' is disabled. Exiting gracefully.")
            return
            
        # Stage 1: Deadman Switch Check
        current_stage = "deadman"
        deadman.check(config)
        
        # Stage 2: Schedule Check
        current_stage = "schedule"
        schedule_checker.check(config)
        
        # Stage 3: Auth & Uploads Playlist Resolution
        current_stage = "auth"
        service = uploader.get_youtube_service(config)
        
        # Resolve uploads playlist ID (costs 1 unit project-level)
        try:
            request = service.channels().list(part="contentDetails", mine=True)
            resp = quota_guard.make_api_call(
                service, request, cost=1, config=config,
                counts_toward_discovery=False
            )
            items = resp.get("items", [])
            if items:
                config.uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
                print(f"Resolved channel uploads playlist ID: {config.uploads_playlist_id}")
            else:
                config.uploads_playlist_id = None
        except Exception as e:
            print(f"WARNING: Could not retrieve channel uploads playlist: {e}")
            config.uploads_playlist_id = None
            
        # Stage 3: Discovery
        current_stage = "discovery"
        candidates = discovery.run(config, service)
        
        if not candidates:
            raise PipelineExit("no-new-content", should_alert=False, message="No candidates discovered.")
            
        # Stage 4: Merge pending_posted records
        current_stage = "pending_merge"
        duplicate_guard.merge_pending_posted_if_exists()
        
        # Sequential validation and download loops
        current_stage = "validation_and_download"
        candidate = None
        raw_video = None
        remaining_candidates = list(candidates)
        
        while remaining_candidates:
            try:
                candidate = validator.validate(remaining_candidates, config, service)
                current_stage = "download"
                raw_video = downloader.download(candidate, config)
                break
            except Exception as e:
                # If validator raises validation gate exit directly, let it propagate
                if isinstance(e, PipelineExit) and e.outcome == "no-valid-candidate":
                    raise e
                    
                print(f"WARNING: Candidate validation or download failed: {e}")
                # Exclude failed candidate and repeat loop
                if candidate:
                    remaining_candidates = [c for c in remaining_candidates if c["video_id"] != candidate["video_id"]]
                else:
                    break
                candidate = None
                raw_video = None
                
        if not raw_video:
            raise PipelineExit("no-valid-candidate", should_alert=False, message="No candidate passed validation and downloaded successfully.")
            
        # Stage 6: Editing
        current_stage = "editing"
        clip = editor.edit(raw_video, config)
        
        # Stage 7: Transcription
        current_stage = "transcription"
        transcript, srt = transcriber.transcribe(clip, config.game_slug)
        
        # Stage 8: Visual Analysis
        current_stage = "visual_analysis"
        visuals = visual_analyzer.analyze(clip, candidate, config)
        
        # Stage 9: Script Writing
        current_stage = "script_writing"
        script = script_writer.generate(config, candidate, transcript, visuals)
        
        # Stage 10: Content Filtering
        current_stage = "content_filter"
        script = content_filter.check(script, config, candidate, transcript, visuals)
        
        # Stage 11: TTS Synthesis
        current_stage = "tts"
        clip_with_audio = tts.apply(script, clip, config)
        
        # Stage 12: Caption Burn-in
        current_stage = "caption_burn"
        clip_with_captions = caption_burner.burn(clip_with_audio, srt, config)
        
        # Stage 13: Thumbnail Generation
        current_stage = "thumbnail"
        thumbnail = thumbnail_generator.generate(clip_with_captions, script, config)
        
        # Stage 14: Quota Pre-check
        current_stage = "quota_check"
        quota_guard.check_pre_upload(config)
        
        # Stage 15: API Duplicate Check
        current_stage = "duplicate_check"
        duplicate_guard.api_check(service, candidate["video_id"], config)
        
        # Stage 16: Upload
        current_stage = "upload"
        video_id = uploader.upload(clip_with_captions, thumbnail, script, candidate, config, service)
        
        # Stage 17: State Write
        current_stage = "state_write"
        # Commit posted.json
        posted_update = {config.game_slug: [candidate["video_id"]]}
        state_writer.commit_state("state/posted.json", posted_update, max_retries=10, backoff_type="exponential")
        
        # Commit deadman success
        deadman.record_success(config)
        
        print(f"Outcome: success. Game slug: {config.game_slug}. Video ID: {video_id}")
        
    except PipelineExit as e:
        print(f"Pipeline exit raised. Stage: {current_stage}. Outcome: {e.outcome}. Message: {e}")
        if e.should_alert and config:
            alerter.send(config, e, stage=current_stage)
    except TimeoutError as e:
        print(f"Pipeline hard timeout exceeded. Stage: {current_stage}. Message: {e}")
        if config:
            timeout_exit = PipelineExit("error", should_alert=True, message=str(e))
            alerter.send(config, timeout_exit, stage=current_stage)
    except Exception as e:
        print(f"Pipeline crashed due to unhandled exception. Stage: {current_stage}. Message: {e}")
        import traceback
        traceback.print_exc()
        if config:
            err_exit = PipelineExit("error", should_alert=True, message=f"Unhandled crash: {e}")
            alerter.send(config, err_exit, stage=current_stage)
    finally:
        # Cancel GHA SIGALRM
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        # Cleanup down files
        if config:
            downloader.cleanup(config)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m bot.pipeline <path_to_game_config_yaml>")
        sys.exit(1)
    run_pipeline(sys.argv[1])

