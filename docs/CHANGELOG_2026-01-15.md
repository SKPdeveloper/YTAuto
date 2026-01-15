# Changelog 2026-01-15: Post-Processing Pipeline Fixes

## Summary
Fixed critical bugs in post-processing pipeline (GEN3a/GEN3b stages) and implemented unified work directory structure for video processing.

---

## Issues Fixed

### 1. Gen3aService.analyze_videos() Signature Error
**Error:** `TypeError: analyze_videos() got an unexpected keyword argument 'music_beat_data'`

**Root Cause:** `gen3_stages.py` was passing `music_beat_data=music_beat_data` but the method expected `music_path=`.

**Fix:** Changed call in `gen3_stages.py:160-167` to pass correct parameters:
```python
analysis = await self.gen3a_service.analyze_videos(
    video_paths=video_paths,
    gen1_brief=gen1_brief,
    gen2_brief=gen2_brief,
    music_path=music_path,
    voiceover_path=project_dir / "voiceover.mp3",
    project_dir=project_dir,
)
```

### 2. FFmpeg Concat Path Duplication
**Error:** `projects\proj_xxx\projects/proj_xxx/scene_1/video.mp4` (path doubled)

**Root Cause:** LLM could return full paths in `source_file` field instead of relative paths.

**Fix:** Added `_resolve_source_path()` method in `manifest_renderer.py:154-180`:
```python
def _resolve_source_path(self, project_dir: Path, source_file: str) -> Path:
    """Handle both relative and absolute paths, fix duplication."""
    # Checks if source_file contains project_name and extracts relative part
```

### 3. Gemini Validation Empty/Truncated Responses (from earlier session)
**Error:** `ValueError: Gemini returned empty response` and Pydantic validation errors for missing fields.

**Fix:** In `content_brain.py`:
- Return rejected `SimpleValidationResult` instead of raising exception for empty responses
- Added `_fill_missing_validation_fields()` to handle truncated JSON

---

## New Feature: Unified Work Directory (`gen3a_work/`)

### Problem
Videos were scattered across `scene_N/video.mp4` folders, causing:
- Path confusion in manifest generation
- LLM returning inconsistent path formats
- Difficult debugging

### Solution
Preprocessing now creates unified `gen3a_work/` directory with standardized file names.

### New Project Structure
```
project_dir/
├── scene_1/video.mp4        # Original generated video
├── scene_2/video.mp4
├── scene_3/video.mp4
├── scene_4/video.mp4
├── scene_5/video.mp4
├── scene_6/video.mp4
├── music/
│   └── background.mp3       # Generated music
├── voiceover.mp3            # Generated voiceover
│
├── gen3a_work/              # NEW: Unified work directory
│   ├── 1.mp4                # Copy of scene_1/video.mp4
│   ├── 2.mp4                # Copy of scene_2/video.mp4
│   ├── 3.mp4                # Copy of scene_3/video.mp4
│   ├── 4.mp4                # Copy of scene_4/video.mp4
│   ├── 5.mp4                # Copy of scene_5/video.mp4
│   ├── 6.mp4                # REVERSED scene_6/video.mp4 (for loop)
│   ├── beats.json           # Music beat analysis
│   ├── vo_timing.json       # Voiceover timing segments
│   └── audio_levels.json    # Audio levels for ducking
│
├── gen3a_analysis.json      # GEN3a output
├── manifest.json            # GEN3b output (source_file: "gen3a_work/N.mp4")
└── final_video.mp4          # Rendered output
```

---

## Files Modified

### 1. `app/services/gen3a_preprocessing.py`
**Version:** 1.6.0 → 1.7.0

**Changes:**
- Updated `PreprocessingResult` dataclass:
  ```python
  @dataclass
  class PreprocessingResult:
      work_dir: Path              # NEW: gen3a_work/ directory
      video_paths: List[Path]     # NEW: [1.mp4, 2.mp4, ..., 6.mp4]
      beats_json_path: Path
      vo_timing_json_path: Path
      audio_levels_json_path: Path
      success: bool
      errors: List[str]
      # REMOVED: reversed_scene6_path (now part of video_paths)
  ```

- Updated `preprocess()` method signature:
  ```python
  async def preprocess(
      self,
      project_dir: Path,
      video_paths: List[Path],    # NEW: all 6 video paths
      music_path: Path,
      voiceover_path: Path,
      # REMOVED: scene6_path (now in video_paths)
  ) -> PreprocessingResult
  ```

- New preprocessing flow:
  1. Create `gen3a_work/` directory
  2. Copy videos 1-5 as `1.mp4`-`5.mp4`
  3. Reverse video 6 and save as `6.mp4`
  4. Generate `beats.json` (music analysis)
  5. Generate `vo_timing.json` (voiceover timing)
  6. Generate `audio_levels.json` (ducking recommendations)

### 2. `app/services/gen3a_service.py`

**Changes:**
- Updated preprocessing call to pass all video paths:
  ```python
  preprocessing_result = await self.preprocessor.preprocess(
      project_dir=project_dir,
      video_paths=video_paths,  # All 6 videos
      music_path=music_path,
      voiceover_path=voiceover_path,
  )
  ```

- Use preprocessed video paths for Gemini upload:
  ```python
  if preprocessing_result.video_paths:
      video_paths = preprocessing_result.video_paths
  ```

- Fixed fallback project_dir detection (now uses parent.parent for scene folder structure)

### 3. `app/pipeline/gen3_stages.py`

**Changes:**
- Removed redundant `BeatAnalyzer` import and initialization
- Removed duplicate beat analysis (now handled in preprocessing)
- Simplified `Gen3aStage.execute()`:
  ```python
  # Before: ran beat analysis, then called analyze_videos with music_beat_data
  # After: just finds music path and calls analyze_videos (preprocessing handles rest)
  ```

### 4. `app/services/gen3b_service.py`

**Changes:**
- Updated `generate_simple_manifest()` to use new path format:
  ```python
  # Before:
  source_file=f"scene_{scene_analysis.scene_number}/video.mp4"

  # After:
  source_file=f"gen3a_work/{scene_analysis.scene_number}.mp4"
  ```

### 5. `app/services/manifest_renderer.py`

**Changes:**
- Added `_resolve_source_path()` method to handle path variations
- Updated `_process_scenes()` to use `_resolve_source_path()`
- Updated `render_simple()` to use `_resolve_source_path()`

---

## Testing Checklist

### Pre-requisites
- [ ] FFmpeg installed and in PATH
- [ ] Gemini API key configured
- [ ] ElevenLabs API key configured (for voiceover)
- [ ] Replicate API key configured (for music)

### Test Cases

#### 1. Full Pipeline Test
```bash
# Start server
python main.py

# Trigger new project generation via API or UI
# Verify all stages complete:
# - Script generation
# - Image generation
# - Image validation
# - Video generation (6 scenes)
# - Post-processing (GEN3a → GEN3b → Render)
```

**Expected Result:**
- `gen3a_work/` directory created with 6 videos + 3 JSON files
- `gen3a_analysis.json` generated
- `manifest.json` with `source_file: "gen3a_work/N.mp4"` format
- `final_video.mp4` rendered successfully

#### 2. Verify Work Directory Structure
```bash
# After successful pipeline run, check:
ls projects/proj_xxx/gen3a_work/
# Should contain: 1.mp4, 2.mp4, 3.mp4, 4.mp4, 5.mp4, 6.mp4, beats.json, vo_timing.json, audio_levels.json
```

#### 3. Verify Scene 6 Reversal
```bash
# Compare duration of original and reversed:
ffprobe -v error -show_entries format=duration projects/proj_xxx/scene_6/video.mp4
ffprobe -v error -show_entries format=duration projects/proj_xxx/gen3a_work/6.mp4
# Should be same duration, but 6.mp4 plays in reverse
```

#### 4. Test Resume from GEN3a Stage
```bash
# Delete gen3a_work/ and re-run pipeline
# Should recreate work directory and continue
```

---

## Rollback Plan

If issues occur, revert these files to previous versions:
1. `app/services/gen3a_preprocessing.py`
2. `app/services/gen3a_service.py`
3. `app/pipeline/gen3_stages.py`
4. `app/services/gen3b_service.py`
5. `app/services/manifest_renderer.py`

---

## Known Remaining Issues

1. **Redundant beat analysis in orchestrator** - `_run_post_processing()` still runs beat analysis to `music/beat_analysis.json` which is unused. Can be removed later.

2. **FFmpeg path inconsistency** - `gen3a_preprocessing.py` uses `"ffmpeg"` while `video_assembler.py` uses `settings.TOPAZ_FFMPEG_PATH`. May need unification.

3. **Synchronous FFmpeg in async function** - `_reverse_video()` uses `subprocess.run()` which blocks event loop. Could be improved with `asyncio.create_subprocess_exec()`.

---

## Contact

Changes made by: Claude Code (Opus 4.5)
Date: 2026-01-15
Session context: Post-processing pipeline bug fixes after full pipeline test failure
