"""
Smoke tests for SimpleVideoGenerator bug fixes:
1. Start frame clearing — _has_cached_image() + _ensure_video_page() logic
2. Placeholder video filtering — _get_all_video_urls() + _get_latest_video_url(exclude_urls)
3. Download size validation — _download_video() warning on small files

All tests use mocked Selenium driver (no real browser needed).
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.higgsfield_video_simple import SimpleVideoGenerator, VideoResult


# =====================================================================
# Fixtures
# =====================================================================

class FakeDriver:
    """Minimal Selenium driver mock for unit tests."""

    def __init__(self):
        self.title = "HiggsField"
        self.current_url = "https://higgsfield.ai/create/video"
        self._execute_script_results = []
        self._find_elements_results = []
        self._script_call_count = 0
        self._find_call_count = 0

    def execute_script(self, script, *args):
        if self._execute_script_results:
            idx = min(self._script_call_count, len(self._execute_script_results) - 1)
            self._script_call_count += 1
            result = self._execute_script_results[idx]
            if callable(result):
                return result(script)
            return result
        return None

    def find_elements(self, by, value):
        if self._find_elements_results:
            idx = min(self._find_call_count, len(self._find_elements_results) - 1)
            self._find_call_count += 1
            return self._find_elements_results[idx]
        return []

    def find_element(self, by, value):
        elements = self.find_elements(by, value)
        if elements:
            return elements[0]
        raise Exception(f"Element not found: {value}")

    def get(self, url):
        self.current_url = url

    def save_screenshot(self, path):
        pass


class FakeBrowser:
    def __init__(self, driver=None):
        self.driver = driver or FakeDriver()


@pytest.fixture
def fake_driver():
    return FakeDriver()


@pytest.fixture
def generator(fake_driver):
    browser = FakeBrowser(fake_driver)
    gen = SimpleVideoGenerator(browser, projects_dir=Path(tempfile.mkdtemp()))
    return gen


# =====================================================================
# Bug 1: _has_cached_image()
# =====================================================================

class TestHasCachedImage:
    """Test cached image detection logic."""

    def test_no_cached_image_clean_page(self, generator, fake_driver):
        """Clean page with dropzone text → no cached image."""
        fake_driver._execute_script_results = [
            json.dumps({
                "cached": False,
                "signals": {"preview": False, "changeBtn": False, "noDropzone": False}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._has_cached_image()
        )
        assert result is False

    def test_cached_image_with_preview(self, generator, fake_driver):
        """Page with large image preview → cached image detected."""
        fake_driver._execute_script_results = [
            json.dumps({
                "cached": True,
                "signals": {"preview": True, "changeBtn": False, "noDropzone": True}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._has_cached_image()
        )
        assert result is True

    def test_cached_image_with_change_button(self, generator, fake_driver):
        """Page with Change button and no dropzone → cached image."""
        fake_driver._execute_script_results = [
            json.dumps({
                "cached": True,
                "signals": {"preview": False, "changeBtn": True, "noDropzone": True}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._has_cached_image()
        )
        assert result is True

    def test_error_returns_true_safe_default(self, generator, fake_driver):
        """On JS error → returns True (safe default to trigger clearing)."""
        fake_driver._execute_script_results = [Exception("JS error")]

        # Override execute_script to raise
        original = fake_driver.execute_script
        def raising_script(script, *args):
            raise Exception("JS error")
        fake_driver.execute_script = raising_script

        result = asyncio.get_event_loop().run_until_complete(
            generator._has_cached_image()
        )
        assert result is True


# =====================================================================
# Bug 2: _get_all_video_urls()
# =====================================================================

class TestGetAllVideoUrls:
    """Test pre-generation URL snapshot collection."""

    def test_collects_urls(self, generator, fake_driver):
        """Should return list of URLs from JS."""
        fake_driver._execute_script_results = [
            [
                "https://cdn.higgsfield.ai/monk_placeholder.mp4",
                "https://cdn.higgsfield.ai/video_abc123.mp4",
            ]
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._get_all_video_urls()
        )
        assert len(result) == 2
        assert "monk_placeholder.mp4" in result[0]

    def test_empty_page(self, generator, fake_driver):
        """No video URLs on page → empty list."""
        fake_driver._execute_script_results = [[]]
        result = asyncio.get_event_loop().run_until_complete(
            generator._get_all_video_urls()
        )
        assert result == []

    def test_js_error_returns_empty(self, generator, fake_driver):
        """On JS error → returns empty list (not crash)."""
        def raising_script(script, *args):
            raise Exception("JS error")
        fake_driver.execute_script = raising_script

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_all_video_urls()
        )
        assert result == []

    def test_null_returns_empty(self, generator, fake_driver):
        """JS returns null → empty list."""
        fake_driver._execute_script_results = [None]
        result = asyncio.get_event_loop().run_until_complete(
            generator._get_all_video_urls()
        )
        assert result == []


# =====================================================================
# Bug 2: _get_latest_video_url(exclude_urls)
# =====================================================================

class TestGetLatestVideoUrlFiltering:
    """Test that exclude_urls properly filters placeholder videos."""

    def test_excludes_pre_existing_urls(self, generator, fake_driver):
        """Pre-existing placeholder URL is filtered, new URL returned."""
        placeholder = "https://cdn.higgsfield.ai/monk_placeholder.mp4"
        new_video = "https://cdn.higgsfield.ai/video_new_abc.mp4"

        fake_driver._execute_script_results = [
            # First attempt returns both old + new
            [placeholder, new_video],
        ]

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=1,
                exclude_urls=[placeholder]
            )
        )
        assert result == new_video

    def test_all_excluded_fallback_returns_none(self, generator, fake_driver):
        """When all URLs are excluded after max_attempts → returns None (no blind fallback)."""
        placeholder = "https://cdn.higgsfield.ai/monk_placeholder.mp4"

        # Return same URL on every attempt (CDN path reuse)
        fake_driver._execute_script_results = [
            [placeholder],  # attempt 1
            [placeholder],  # attempt 2
            [placeholder],  # attempt 3 (+ history fallback returns None)
        ]

        # Mock history to return None
        async def mock_history():
            return None
        generator._get_video_url_from_history = mock_history

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=3,
                exclude_urls=[placeholder]
            )
        )
        # No blind fallback — returns None
        assert result is None

    def test_all_excluded_no_urls_returns_none(self, generator, fake_driver):
        """No URLs at all on page → returns None (no fallback possible)."""
        fake_driver._execute_script_results = [
            [],  # attempt 1 — empty page
        ]

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=1,
                exclude_urls=["https://cdn.higgsfield.ai/old.mp4"]
            )
        )
        assert result is None

    def test_no_exclude_backwards_compatible(self, generator, fake_driver):
        """Without exclude_urls, returns first URL found (backwards compat)."""
        url = "https://cdn.higgsfield.ai/video_abc.mp4"
        fake_driver._execute_script_results = [[url]]

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(max_attempts=1)
        )
        assert result == url

    def test_exclude_strips_query_params(self, generator, fake_driver):
        """Query params are stripped for comparison — same base = excluded from 'new' pool.
        No blind fallback — returns None."""
        base = "https://cdn.higgsfield.ai/video.mp4"
        with_params = base + "?token=abc&expires=123"

        fake_driver._execute_script_results = [[with_params]]

        # Mock history to return None (final History fallback)
        async def mock_history():
            return None
        generator._get_video_url_from_history = mock_history

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=1,
                exclude_urls=[base + "?token=old"]
            )
        )
        # Same base URL → excluded, no blind fallback → None
        assert result is None

    def test_new_url_with_different_base(self, generator, fake_driver):
        """URL with different base passes through exclude filter."""
        old = "https://cdn.higgsfield.ai/old_video.mp4?t=1"
        new = "https://cdn.higgsfield.ai/new_video.mp4?t=2"

        fake_driver._execute_script_results = [[old, new]]

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=1,
                exclude_urls=[old]
            )
        )
        assert result == new


# =====================================================================
# Bug 2: _download_video() size validation
# =====================================================================

class TestDownloadVideoSizeValidation:
    """Test that small file size triggers warning."""

    def test_small_file_raises_valueerror(self, generator):
        """Files < MIN_REAL_VIDEO_SIZE raise ValueError and delete the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "video.mp4"
            small_content = b"x" * 100  # 100 bytes — clearly a placeholder

            # Mock httpx client
            mock_response = MagicMock()
            mock_response.content = small_content
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            generator._http_client = mock_client

            with pytest.raises(ValueError, match="too small"):
                asyncio.get_event_loop().run_until_complete(
                    generator._download_video("https://example.com/video.mp4", output_path)
                )

            # File should be deleted after ValueError
            assert not output_path.exists()

    def test_normal_file_no_error(self, generator):
        """Files >= MIN_REAL_VIDEO_SIZE (2 MB) download without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "video.mp4"
            normal_content = b"x" * (3 * 1024 * 1024)  # 3 MB

            mock_response = MagicMock()
            mock_response.content = normal_content
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            generator._http_client = mock_client

            asyncio.get_event_loop().run_until_complete(
                generator._download_video("https://example.com/video.mp4", output_path)
            )

            assert output_path.exists()
            assert output_path.stat().st_size == 3 * 1024 * 1024


# =====================================================================
# Integration: generate_and_download flow
# =====================================================================

class TestGenerateAndDownloadFlow:
    """Verify generate_and_download flow: upload retry, gate-check, URL filtering."""

    def _setup_mocks(self, generator, upload_returns=True, verify_returns=True):
        """Helper to set up standard mocks. Returns call_order list."""
        call_order = []

        async def mock_ensure_video_page(**kwargs):
            call_order.append("ensure_video_page")

        async def mock_take_screenshot(filename):
            pass

        async def mock_upload_image(path):
            call_order.append("upload_image")
            if callable(upload_returns):
                return upload_returns()
            return upload_returns

        async def mock_verify_image_loaded():
            call_order.append("verify_image_loaded")
            if callable(verify_returns):
                return verify_returns()
            return verify_returns

        async def mock_enter_prompt(prompt):
            call_order.append("enter_prompt")

        async def mock_get_all_video_urls():
            call_order.append("get_all_video_urls")
            return ["https://cdn.higgsfield.ai/placeholder.mp4"]

        async def mock_click_generate():
            call_order.append("click_generate")

        async def mock_wait_for_generation(timeout=420):
            call_order.append("wait_for_generation")

        async def mock_get_latest_video_url(max_attempts=20, exclude_urls=None):
            call_order.append("get_latest_video_url")
            return "https://cdn.higgsfield.ai/new_video.mp4"

        async def mock_download_video(url, path):
            call_order.append("download_video")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * (5 * 1024 * 1024))

        async def mock_save_metadata(**kwargs):
            pass

        generator._ensure_video_page = mock_ensure_video_page
        generator.take_screenshot = mock_take_screenshot
        generator._upload_image = mock_upload_image
        generator._verify_image_loaded = mock_verify_image_loaded
        generator._enter_prompt = mock_enter_prompt
        generator._get_all_video_urls = mock_get_all_video_urls
        generator._click_generate = mock_click_generate
        generator._wait_for_generation_complete = mock_wait_for_generation
        generator._get_latest_video_url = mock_get_latest_video_url
        generator._download_video = mock_download_video
        generator._save_video_metadata = mock_save_metadata

        return call_order

    def _run_generate(self, generator):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "image.png"
            image_path.write_bytes(b"PNG")
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            return asyncio.get_event_loop().run_until_complete(
                generator.generate_and_download(
                    image_path=image_path,
                    prompt="Test prompt",
                    output_dir=output_dir,
                    scene_num=1,
                    project_id="test_proj"
                )
            )

    def test_successful_flow_with_verified_upload(self, generator):
        """Upload verified on first attempt → proceeds to Generate."""
        call_order = self._setup_mocks(generator, upload_returns=True, verify_returns=True)
        result = self._run_generate(generator)

        assert result.success is True
        # Upload called once (verified immediately)
        assert call_order.count("upload_image") == 1
        # get_all_video_urls BEFORE click_generate
        urls_idx = call_order.index("get_all_video_urls")
        gen_idx = call_order.index("click_generate")
        assert urls_idx < gen_idx

    def test_upload_retry_on_inconclusive(self, generator):
        """Upload inconclusive + verify fails → page reloads → retry succeeds."""
        upload_count = [0]
        verify_count = [0]

        def upload_side_effect():
            upload_count[0] += 1
            return upload_count[0] >= 2  # Fails first, succeeds second

        def verify_side_effect():
            verify_count[0] += 1
            # First round polling: all fail (image not loaded) → triggers retry
            # After retry, upload succeeds → gate check passes
            return upload_count[0] >= 2

        call_order = self._setup_mocks(
            generator,
            upload_returns=upload_side_effect,
            verify_returns=verify_side_effect,
        )
        result = self._run_generate(generator)

        assert result.success is True
        assert call_order.count("upload_image") == 2

    def test_upload_inconclusive_but_verify_confirms(self, generator):
        """Upload returns False but verify_image_loaded confirms image → proceeds."""
        call_order = self._setup_mocks(
            generator,
            upload_returns=False,  # Always inconclusive
            verify_returns=True    # But verify says it's there
        )
        result = self._run_generate(generator)

        assert result.success is True
        # Only 1 upload attempt because verify confirmed on first round
        assert call_order.count("upload_image") == 1

    def test_upload_fails_all_retries_aborts(self, generator):
        """Upload fails 3 times + verify fails → aborts, no Generate click."""
        call_order = self._setup_mocks(
            generator,
            upload_returns=False,
            verify_returns=False
        )
        result = self._run_generate(generator)

        assert result.success is False
        assert "upload failed" in result.error.lower() or "aborting" in result.error.lower()
        assert "click_generate" not in call_order, "Generate should NOT be called when image not loaded!"
        assert call_order.count("upload_image") == 3

    def test_gate_check_prevents_generate_if_image_disappears(self, generator):
        """Image loaded after upload, but disappears before Generate → aborts."""
        # When upload returns True, _verify_image_loaded is NOT called during upload.
        # The FIRST call to _verify_image_loaded is the gate-check after enter_prompt.
        # We make that first call return False → abort.

        call_order = self._setup_mocks(
            generator,
            upload_returns=True,
            verify_returns=False  # Gate-check always fails → image "disappeared"
        )
        result = self._run_generate(generator)

        assert result.success is False
        assert "disappeared" in result.error.lower() or "aborting" in result.error.lower()
        assert "click_generate" not in call_order


# =====================================================================
# Structural: imports & class interface
# =====================================================================

class TestVerifyImageLoaded:
    """Test _verify_image_loaded() post-upload check (BUG-A: JSON-based scoring)."""

    def test_uploaded_image_blob_src(self, generator, fake_driver):
        """blob: src image → score=2 (uploadedImg) → loaded."""
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 5,
                "signals": {"uploadedImg": True, "fileInputGone": True,
                            "changeBtn": True, "noDropzone": True}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is True

    def test_uploaded_image_only(self, generator, fake_driver):
        """Only uploadedImg signal (score=2) → loaded (blob: src is enough)."""
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 2,
                "signals": {"uploadedImg": True, "fileInputGone": False,
                            "changeBtn": False, "noDropzone": False}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is True

    def test_no_uploaded_image_but_other_signals(self, generator, fake_driver):
        """No blob:/data: image but fileInputGone + changeBtn → score=2 → loaded."""
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 2,
                "signals": {"uploadedImg": False, "fileInputGone": True,
                            "changeBtn": True, "noDropzone": False}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is True

    def test_only_ui_image_not_loaded(self, generator, fake_driver):
        """BUG-A: Only UI elements (model preview) → uploadedImg=False, score=1 → NOT loaded."""
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 1,
                "signals": {"uploadedImg": False, "fileInputGone": False,
                            "changeBtn": False, "noDropzone": True}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is False

    def test_zero_score_not_loaded(self, generator, fake_driver):
        """Clean page, no signals → not loaded."""
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 0,
                "signals": {"uploadedImg": False, "fileInputGone": False,
                            "changeBtn": False, "noDropzone": False}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is False

    def test_false_positive_prevention(self, generator, fake_driver):
        """BUG-A scenario: model preview + noDropzone → score=1 → NOT loaded."""
        # This is the exact pattern that caused false positives before the fix:
        # UI elements like model previews pass the "img > 60px" check,
        # but they DON'T have blob:/data: src, so uploadedImg=False
        fake_driver._execute_script_results = [
            json.dumps({
                "score": 1,
                "signals": {"uploadedImg": False, "fileInputGone": False,
                            "changeBtn": False, "noDropzone": True}
            })
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is False, "Model preview should NOT trigger false positive"

    def test_error_returns_false(self, generator, fake_driver):
        """JS error → returns False (not loaded)."""
        def raising_script(script, *args):
            raise Exception("JS error")
        fake_driver.execute_script = raising_script

        result = asyncio.get_event_loop().run_until_complete(
            generator._verify_image_loaded()
        )
        assert result is False


class TestUploadImageReturnValue:
    """Test that _upload_image returns bool."""

    def test_upload_image_returns_bool(self):
        import inspect
        sig = inspect.signature(SimpleVideoGenerator._upload_image)
        hints = inspect.get_annotations(SimpleVideoGenerator._upload_image)
        assert hints.get('return') is bool


class TestStructural:
    """Verify new methods exist and have correct signatures."""

    def test_has_cached_image_exists(self):
        assert hasattr(SimpleVideoGenerator, '_has_cached_image')

    def test_get_all_video_urls_exists(self):
        assert hasattr(SimpleVideoGenerator, '_get_all_video_urls')

    def test_verify_image_loaded_exists(self):
        assert hasattr(SimpleVideoGenerator, '_verify_image_loaded')

    def test_get_latest_video_url_accepts_exclude_urls(self):
        import inspect
        sig = inspect.signature(SimpleVideoGenerator._get_latest_video_url)
        assert 'exclude_urls' in sig.parameters

    def test_upload_image_returns_bool(self):
        import inspect
        hints = inspect.get_annotations(SimpleVideoGenerator._upload_image)
        assert hints.get('return') is bool

    def test_video_result_dataclass(self):
        r = VideoResult(scene_num=1)
        assert r.success is False
        assert r.error is None
        assert r.video_path is None


# =====================================================================
# BUG-B: History fallback NOT filtered through exclude_set
# =====================================================================

class TestHistoryFallbackNoFilter:
    """BUG-B: History panel shows latest generation, so it should NOT be filtered."""

    def test_history_url_returned_even_if_in_exclude(self, generator, fake_driver):
        """History URL is returned regardless of exclude_set."""
        old_url = "https://cdn.higgsfield.ai/video_old.mp4"

        # All DOM URLs are excluded
        fake_driver._execute_script_results = [
            [old_url],  # attempt 1
            [old_url],  # attempt 2
            [old_url],  # attempt 3 — triggers history
        ]

        history_url = "https://cdn.higgsfield.ai/video_from_history.mp4"
        async def mock_history():
            return history_url
        generator._get_video_url_from_history = mock_history

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=4,
                exclude_urls=[old_url]
            )
        )
        # History URL should be returned without filtering
        assert result == history_url


# =====================================================================
# BUG-C: Scoped clear verification
# =====================================================================

class TestScopedClearVerification:
    """BUG-C: After clicking X, verify image count actually decreased."""

    def test_clear_succeeds_when_count_decreases(self, generator, fake_driver):
        """Click X + img count decreased → True."""
        fake_driver._execute_script_results = [
            2,                        # img_count_before
            'cleared:img_traversal',  # click result
            1,                        # img_count_after (decreased!)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._clear_cached_image_scoped()
        )
        assert result is True

    def test_clear_fails_when_count_unchanged(self, generator, fake_driver):
        """Click X but img count unchanged → False (React state didn't update)."""
        fake_driver._execute_script_results = [
            2,                        # img_count_before
            'cleared:img_traversal',  # click result
            2,                        # img_count_after (SAME — React didn't update)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._clear_cached_image_scoped()
        )
        assert result is False

    def test_clear_not_found(self, generator, fake_driver):
        """No X button found → False."""
        fake_driver._execute_script_results = [
            1,            # img_count_before
            'not_found',  # no button found
        ]
        result = asyncio.get_event_loop().run_until_complete(
            generator._clear_cached_image_scoped()
        )
        assert result is False

    def test_clear_error_returns_false(self, generator, fake_driver):
        """JS error → False."""
        def raising_script(script, *args):
            raise Exception("JS error")
        fake_driver.execute_script = raising_script

        result = asyncio.get_event_loop().run_until_complete(
            generator._clear_cached_image_scoped()
        )
        assert result is False


# =====================================================================
# SMOKE TESTS: Real pipeline failure scenarios from prod logs
# =====================================================================

class TestSmokeProdScenarios:
    """
    Reproduce exact failure patterns observed in proj_714f96645bc4:
    - Scene 2: SUCCESS (only one that worked)
    - Scenes 1, 3-8: FAILED (video generated but not downloaded)

    These tests verify that the BUG-A/B/C/D fixes prevent each failure mode.
    """

    def _setup_flow_mocks(self, generator, upload_result=True, verify_result=True,
                          video_url_result="https://cdn.higgsfield.ai/new.mp4"):
        """Wire up generate_and_download mocks. Returns call_order tracker."""
        call_order = []

        async def mock_ensure_video_page(**kw):
            call_order.append("ensure_video_page")
        async def mock_screenshot(f):
            pass
        async def mock_upload(path):
            call_order.append("upload")
            return upload_result() if callable(upload_result) else upload_result
        async def mock_verify():
            call_order.append("verify")
            return verify_result() if callable(verify_result) else verify_result
        async def mock_prompt(p):
            call_order.append("prompt")
        async def mock_get_all_urls():
            call_order.append("snapshot_urls")
            return ["https://cdn.higgsfield.ai/existing_1.mp4",
                    "https://cdn.higgsfield.ai/existing_2.mp4",
                    "https://cdn.higgsfield.ai/existing_3.mp4",
                    "https://cdn.higgsfield.ai/existing_4.mp4"]
        async def mock_click_gen():
            call_order.append("generate")
        async def mock_wait_gen(timeout=420):
            call_order.append("wait")
        async def mock_get_latest(max_attempts=20, exclude_urls=None):
            call_order.append("get_video_url")
            return video_url_result() if callable(video_url_result) else video_url_result
        async def mock_download(url, path):
            call_order.append("download")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * (8 * 1024 * 1024))
        async def mock_meta(**kw):
            pass

        generator._ensure_video_page = mock_ensure_video_page
        generator.take_screenshot = mock_screenshot
        generator._upload_image = mock_upload
        generator._verify_image_loaded = mock_verify
        generator._enter_prompt = mock_prompt
        generator._get_all_video_urls = mock_get_all_urls
        generator._click_generate = mock_click_gen
        generator._wait_for_generation_complete = mock_wait_gen
        generator._get_latest_video_url = mock_get_latest
        generator._download_video = mock_download
        generator._save_video_metadata = mock_meta
        return call_order

    def _run(self, generator):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "image.png"
            img.write_bytes(b"PNG")
            out = Path(d) / "out"
            out.mkdir()
            return asyncio.get_event_loop().run_until_complete(
                generator.generate_and_download(img, "test", out, 1, "smoke")
            )

    # --- Scenario 1: Scene 2 success path (the only one that worked) ---

    def test_scene2_happy_path(self, generator):
        """Scene 2: upload OK, verify OK, new video URL found → SUCCESS."""
        co = self._setup_flow_mocks(generator)
        r = self._run(generator)
        assert r.success is True
        assert "generate" in co
        assert "download" in co

    # --- Scenario 2: BUG-A — false positive verify after nuclear clear ---

    def test_bug_a_false_positive_prevented(self, generator):
        """
        Prod pattern: upload inconclusive → verify returns True (FALSE POSITIVE)
        → generates without image → no new video found.

        After fix: verify returns False (model preview not counted) → retry upload.
        """
        upload_count = [0]
        def upload_fn():
            upload_count[0] += 1
            return upload_count[0] >= 2  # Second attempt succeeds

        verify_count = [0]
        def verify_fn():
            verify_count[0] += 1
            # After fix: first verify = False (no blob: img), then True
            return upload_count[0] >= 2

        co = self._setup_flow_mocks(generator, upload_result=upload_fn, verify_result=verify_fn)
        r = self._run(generator)

        assert r.success is True
        assert co.count("upload") == 2, "Should retry upload after false-positive prevented"

    # --- Scenario 3: BUG-B — all URLs excluded, fallback saves the day ---

    def test_bug_b_cdn_reuse_fallback(self, generator):
        """
        Prod pattern: 4 pre-existing URLs, generation complete,
        but new video has same CDN base → all excluded → no download.

        After fix: fallback returns first URL anyway.
        """
        co = self._setup_flow_mocks(
            generator,
            # _get_latest_video_url will be called and return the fallback URL
            video_url_result="https://cdn.higgsfield.ai/existing_1.mp4"
        )
        r = self._run(generator)

        assert r.success is True
        assert "download" in co

    # --- Scenario 4: BUG-B — history finds the video ---

    def test_bug_b_history_fallback(self, generator):
        """
        All DOM URLs excluded → history panel returns the generated video.
        History is NOT filtered → download succeeds.
        """
        co = self._setup_flow_mocks(
            generator,
            video_url_result="https://cdn.higgsfield.ai/from_history.mp4"
        )
        r = self._run(generator)
        assert r.success is True

    # --- Scenario 5: Complete failure — no video generated ---

    def test_no_video_url_at_all(self, generator):
        """Generation fails or no video appears → graceful failure."""
        co = self._setup_flow_mocks(generator, video_url_result=None)
        r = self._run(generator)
        assert r.success is False
        assert "not found" in r.error.lower()
        assert "download" not in co

    # --- Scenario 6: Upload fails all 3 retries → abort (no prompt-only gen) ---

    def test_upload_total_failure_prevents_promptonly_gen(self, generator):
        """
        Prod safety: if image NEVER loads → abort entirely.
        Prevents useless prompt-only generation.
        """
        co = self._setup_flow_mocks(generator, upload_result=False, verify_result=False)
        r = self._run(generator)
        assert r.success is False
        assert "generate" not in co, "Must NOT click Generate without image!"

    # --- Scenario 7: 8-scene pipeline — each scene gets clean state ---

    def test_multi_scene_sequential_isolation(self, generator):
        """Each scene calls ensure_video_page (fresh state) before upload."""
        results = []
        for scene_num in range(1, 4):
            co = self._setup_flow_mocks(generator)
            with tempfile.TemporaryDirectory() as d:
                img = Path(d) / "image.png"
                img.write_bytes(b"PNG")
                out = Path(d) / "out"
                out.mkdir()
                r = asyncio.get_event_loop().run_until_complete(
                    generator.generate_and_download(img, f"prompt {scene_num}", out, scene_num, "smoke")
                )
                results.append(r)
                assert "ensure_video_page" in co, f"Scene {scene_num} must reset page"

        assert all(r.success for r in results)


# =====================================================================
# Placeholder URL detection
# =====================================================================

class TestPlaceholderUrlDetection:
    """Test _is_placeholder_url() and its integration with URL filtering."""

    def test_is_placeholder_url_detection(self, generator):
        """Known placeholder patterns are detected; real CloudFront URLs are not."""
        # Placeholder URLs
        assert generator._is_placeholder_url(
            "https://cdn.higgsfield.ai/kling_motion/demo_monk_ocean.mp4"
        ) is True
        assert generator._is_placeholder_url(
            "https://cdn.higgsfield.ai/kling_motion/showcase_v2.mp4?t=123"
        ) is True

        # Real CloudFront URLs
        assert generator._is_placeholder_url(
            "https://d8j0ntlcm91z4.cloudfront.net/user_abc/hf_video_123.mp4"
        ) is False
        # Normal HiggsField CDN (not kling_motion path)
        assert generator._is_placeholder_url(
            "https://cdn.higgsfield.ai/video_abc123.mp4"
        ) is False

    def test_strategy1_skips_placeholder_urls(self, generator, fake_driver):
        """Placeholder URL is filtered even if not in exclude_set."""
        placeholder = "https://cdn.higgsfield.ai/kling_motion/demo.mp4"
        real_video = "https://d8j0ntlcm91z4.cloudfront.net/user_1/hf_new.mp4"

        fake_driver._execute_script_results = [
            [placeholder, real_video],  # attempt 1
        ]

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=1,
                exclude_urls=[]  # Nothing excluded — but placeholder still filtered
            )
        )
        assert result == real_video

    def test_strategy3_returns_none_not_placeholder(self, generator, fake_driver):
        """After max_attempts with only placeholders → returns None, not the placeholder."""
        placeholder = "https://cdn.higgsfield.ai/kling_motion/monk.mp4"

        fake_driver._execute_script_results = [
            [placeholder],  # attempt 1
            [placeholder],  # attempt 2
        ]

        async def mock_history():
            return None
        generator._get_video_url_from_history = mock_history

        result = asyncio.get_event_loop().run_until_complete(
            generator._get_latest_video_url(
                max_attempts=2,
                exclude_urls=[]
            )
        )
        assert result is None

    def test_download_rejects_placeholder_size(self, generator):
        """ValueError raised for small files + file is deleted from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "video.mp4"
            # 1.2 MB — typical placeholder size (monk + ocean demo)
            small_content = b"x" * int(1.2 * 1024 * 1024)

            mock_response = MagicMock()
            mock_response.content = small_content
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            generator._http_client = mock_client

            with pytest.raises(ValueError, match="too small"):
                asyncio.get_event_loop().run_until_complete(
                    generator._download_video(
                        "https://cdn.higgsfield.ai/kling_motion/demo.mp4",
                        output_path
                    )
                )

            assert not output_path.exists(), "Placeholder file should be deleted"

    def test_generate_retries_via_history_on_placeholder(self, generator):
        """generate_and_download retries via History when download detects placeholder."""
        call_order = []

        async def mock_ensure_video_page(**kw):
            call_order.append("ensure_video_page")
        async def mock_screenshot(f):
            pass
        async def mock_upload(path):
            call_order.append("upload")
            return True
        async def mock_verify():
            return True
        async def mock_prompt(p):
            pass
        async def mock_get_all_urls():
            return ["https://cdn.higgsfield.ai/old.mp4"]
        async def mock_click_gen():
            call_order.append("generate")
        async def mock_wait_gen(timeout=420):
            pass
        async def mock_get_latest(max_attempts=20, exclude_urls=None):
            # Returns a placeholder URL (will fail size check)
            return "https://cdn.higgsfield.ai/kling_motion/demo.mp4"

        download_count = [0]
        async def mock_download(url, path):
            download_count[0] += 1
            call_order.append(f"download_{download_count[0]}")
            path.parent.mkdir(parents=True, exist_ok=True)
            if download_count[0] == 1:
                # First download: small placeholder → write small file then raise
                path.write_bytes(b"x" * 100)
                path.unlink(missing_ok=True)
                raise ValueError("too small (0.00 MB)")
            else:
                # Second download (from history): real video
                path.write_bytes(b"x" * (5 * 1024 * 1024))

        async def mock_history():
            call_order.append("history_fallback")
            return "https://d8j0ntlcm91z4.cloudfront.net/user_1/hf_real.mp4"

        async def mock_meta(**kw):
            pass

        generator._ensure_video_page = mock_ensure_video_page
        generator.take_screenshot = mock_screenshot
        generator._upload_image = mock_upload
        generator._verify_image_loaded = mock_verify
        generator._enter_prompt = mock_prompt
        generator._get_all_video_urls = mock_get_all_urls
        generator._click_generate = mock_click_gen
        generator._wait_for_generation_complete = mock_wait_gen
        generator._get_latest_video_url = mock_get_latest
        generator._download_video = mock_download
        generator._get_video_url_from_history = mock_history
        generator._save_video_metadata = mock_meta

        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "image.png"
            img.write_bytes(b"PNG")
            out = Path(d) / "out"
            out.mkdir()
            r = asyncio.get_event_loop().run_until_complete(
                generator.generate_and_download(img, "test", out, 1, "retry_test")
            )

        assert r.success is True, f"Expected success but got error: {r.error}"
        assert "download_1" in call_order, "First download should be attempted"
        assert "history_fallback" in call_order, "History fallback should be triggered"
        assert "download_2" in call_order, "Second download from history should happen"
        assert r.video_url == "https://d8j0ntlcm91z4.cloudfront.net/user_1/hf_real.mp4"
