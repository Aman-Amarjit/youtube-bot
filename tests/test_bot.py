import os
import unittest
import unittest.mock
from datetime import datetime, timezone
import yaml

from bot import config_loader
from bot import schedule_checker
from bot import quota_guard
from bot import state_writer
from bot import exceptions

class TestYouTubeBot(unittest.TestCase):

    def setUp(self):
        # Create games directory if not exists
        os.makedirs("games", exist_ok=True)
        
        # Write a dummy correct config
        self.correct_cfg_path = "games/testgame.yml"
        self.correct_cfg_data = {
            "game_name": "Test Game",
            "game_slug": "testgame",
            "enabled": True,
            "cloud_project_id": "test-project-123",
            "credential_secret": "YOUTUBE_OAUTH_TEST",
            "schedule": "* * * * *",  # fires every minute
            "tags": ["test", "gaming"],
            "upload_title_template": "{clip_title} #Shorts",
            "upload_description_template": "{voiceover_script} source:{source_video_id}",
            "blocklist": ["blockedword", "badterm"],
            "sources": [
                {"url": "https://www.youtube.com/watch?v=12345678901", "provenance": "creative_commons"}
            ]
        }
        with open(self.correct_cfg_path, "w") as f:
            yaml.dump(self.correct_cfg_data, f)

    def tearDown(self):
        # Clean up files
        for p in [self.correct_cfg_path, "games/mismatch.yml", "state/quota.json", "state/posted.json"]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_config_loader_success(self):
        cfg = config_loader.load(self.correct_cfg_path)
        self.assertEqual(cfg.game_name, "Test Game")
        self.assertEqual(cfg.game_slug, "testgame")
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.blocklist_inline, ["blockedword", "badterm"])

    def test_config_loader_slug_mismatch(self):
        mismatch_path = "games/mismatch.yml"
        with open(mismatch_path, "w") as f:
            yaml.dump(self.correct_cfg_data, f)  # slug is 'testgame', file is 'mismatch.yml'
            
        with self.assertRaises(config_loader.ConfigError) as ctx:
            config_loader.load(mismatch_path)
        self.assertIn("must equal the filename stem", str(ctx.exception))

    def test_schedule_checker_matches(self):
        cfg = config_loader.load(self.correct_cfg_path)
        # Check that it runs without raising any exception since '* * * * *' matches any time
        schedule_checker.check(cfg)

    def test_quota_guard_counters(self):
        data = {}
        date = "2026-07-09"
        
        # Test record_api_call with counts_toward_discovery=True
        data = quota_guard.record_api_call(data, date, "project_a", "game_a", 1, counts_toward_discovery=True)
        self.assertEqual(data[date]["projects"]["project_a"], 1)
        self.assertEqual(data[date]["discovery"]["game_a"], 1)
        
        # Test record_api_call with counts_toward_discovery=False
        data = quota_guard.record_api_call(data, date, "project_a", "game_a", 5, counts_toward_discovery=False)
        self.assertEqual(data[date]["projects"]["project_a"], 6)
        self.assertEqual(data[date]["discovery"]["game_a"], 1)  # unchanged

    def test_state_writer_deep_merge(self):
        base = {
            "minecraft": ["vid1", "vid2"],
            "meta": {"status": "active"}
        }
        incoming = {
            "minecraft": ["vid2", "vid3"],
            "meta": {"last_run": "today"}
        }
        
        result = state_writer.deep_merge(base, incoming)
        # Lists unioned and deduplicated
        self.assertEqual(result["minecraft"], ["vid1", "vid2", "vid3"])
        # Nested dicts merged recursively
        self.assertEqual(result["meta"], {"status": "active", "last_run": "today"})

    @unittest.mock.patch("bot.downloader.subprocess.run")
    @unittest.mock.patch("bot.downloader._upgrade_yt_dlp")
    @unittest.mock.patch("os.path.exists")
    @unittest.mock.patch("os.environ.get")
    def test_downloader_cookies_fallback(self, mock_env_get, mock_exists, mock_upgrade, mock_run):
        # YOUTUBE_COOKIES_B64 is set
        mock_env_get.side_effect = lambda key, default="": "dGVzdF9jb29raWVz" if key == "YOUTUBE_COOKIES_B64" else default
        
        # We mock subprocess.run calls
        # 1st call: check_cmd (pre-flight check) with cookies -> returns failure (returncode=1)
        # 2nd call: check_cmd (pre-flight check) without cookies -> returns success (returncode=0)
        # 3rd call: download cmd (Attempt 1) with cookies -> returns failure (returncode=1)
        # 4th call: download cmd (Attempt 2) without cookies -> returns success (returncode=0)
        mock_run_res_fail = unittest.mock.Mock()
        mock_run_res_fail.returncode = 1
        mock_run_res_fail.stderr = "Sign in to confirm you're not a bot"
        
        mock_run_res_success_check = unittest.mock.Mock()
        mock_run_res_success_check.returncode = 0
        mock_run_res_success_check.stdout = '{"formats": [{"vcodec": "h264", "ext": "mp4"}]}'
        
        mock_run_res_success_dl = unittest.mock.Mock()
        mock_run_res_success_dl.returncode = 0
        
        mock_run.side_effect = [
            mock_run_res_fail,       # pre-flight with cookies fails
            mock_run_res_success_check, # pre-flight without cookies succeeds
            mock_run_res_fail,       # download with cookies fails
            mock_run_res_success_dl, # download without cookies succeeds
        ]
        
        # mock path checks: final_path exists
        mock_exists.return_value = True
        
        # Load mock config
        from bot import config_loader
        from bot import downloader
        cfg = config_loader.load(self.correct_cfg_path)
        
        candidate = {"video_id": "test_video_id"}
        
        # Run downloader
        res_path = downloader.download(candidate, cfg)
        
        # We expect a success return value (resolved absolute path)
        self.assertTrue(res_path.endswith("test_video_id.mp4"))
        
        # subprocess.run should have been called 4 times
        self.assertEqual(mock_run.call_count, 4)
        
        # Verify call arguments
        calls = mock_run.call_args_list
        # Call 0: check_cmd with cookies
        self.assertIn("--cookies", calls[0][0][0])
        # Call 1: check_cmd without cookies
        self.assertNotIn("--cookies", calls[1][0][0])
        # Call 2: download cmd with cookies
        self.assertIn("--cookies", calls[2][0][0])
        # Call 3: download cmd without cookies
        self.assertNotIn("--cookies", calls[3][0][0])

if __name__ == "__main__":
    unittest.main()
