# Changelog 2026-02-02: FFmpeg Configuration & ManifestRenderer Fixes

## Summary
Fixed ManifestRenderer to use full FFmpeg with subtitle support instead of Topaz FFmpeg which lacks critical filters. This enables proper ASS subtitle rendering and video concatenation with different resolutions.

---

## Problem

Topaz Video AI's custom FFmpeg build lacks several standard filters and codecs:
- **Missing filters:** `ass`, `subtitles`, `eq`
- **Missing codecs:** `libx264`
- **Available:** `h264_nvenc`, `h264_amf`, `h264_qsv`, `h264_mf`, `tvai_up` (AI upscaling)

This caused rendering failures when:
1. Burning in ASS subtitles
2. Applying contrast/brightness effects
3. Concatenating videos with different resolutions

---

## Solution

### 1. Dual FFmpeg Configuration

Now using **two FFmpeg installations**:

| FFmpeg | Purpose | Filters |
|--------|---------|---------|
| **Full FFmpeg** (winget) | Rendering, subtitles, effects | ass, subtitles, eq, libx264 |
| **Topaz FFmpeg** | AI upscaling | tvai_up, tvai_fi |

### 2. New Environment Variable

Added `FFMPEG_PATH` in `.env`:
```env
# Full FFmpeg for rendering (has ass, subtitles, eq, libx264)
FFMPEG_PATH=C:\Users\...\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe

# Topaz FFmpeg for AI upscaling (has tvai_up filter)
TOPAZ_FFMPEG_PATH=C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe
```

### 3. ManifestRenderer Changes

- Uses `FFMPEG_PATH` (full FFmpeg) for rendering
- Falls back to `TOPAZ_FFMPEG_PATH` if not configured
- Fixed filter syntax: `colorcontrast=cc=X` → `eq=contrast=X`
- Uses `filter_complex` for concatenation (handles resolution differences)
- Fixed `ffprobe` path resolution

---

## Files Modified

### 1. `app/core/config.py`

Added `FFMPEG_PATH` field:
```python
FFMPEG_PATH: Path = Field(
    default=Path(r"C:\Users\...\ffmpeg.exe"),
    description="Full FFmpeg for rendering with subtitles"
)
```

### 2. `app/services/manifest_renderer.py`

**FFmpeg Selection (line 83-90):**
```python
# Prioritize full FFmpeg (has ass/subtitles filters)
if hasattr(settings, 'FFMPEG_PATH') and settings.FFMPEG_PATH.exists():
    self.ffmpeg_path = str(settings.FFMPEG_PATH)
elif settings.TOPAZ_FFMPEG_PATH.exists():
    self.ffmpeg_path = str(settings.TOPAZ_FFMPEG_PATH)
else:
    self.ffmpeg_path = "ffmpeg"
```

**Fixed Effect Filters (line 419-439):**
```python
# Before (invalid):
"ZOOM_PUNCH": f"exposure=exposure=0.05,colorcontrast=cc=1.1"
"COLOR_BOOST": "hue=s=1.3,colorcontrast=cc=1.1"

# After (valid):
"ZOOM_PUNCH": f"eq=brightness=0.05:contrast=1.1"
"COLOR_BOOST": "eq=saturation=1.3:contrast=1.1"
```

**Fixed Hook Style Filters (line 494-520):**
```python
# Before:
"IMPACT": ["exposure=exposure=0.15", "colorcontrast=cc=1.3", ...]

# After:
"IMPACT": ["eq=brightness=0.15:contrast=1.3", ...]
```

**Fixed Concatenation (line 523-580):**

Changed from concat demuxer to filter_complex:
```python
# Before (fails with different resolutions):
cmd = [ffmpeg, "-f", "concat", "-i", concat_file, ...]

# After (normalizes all inputs):
filter_parts = []
for i in range(n):
    filter_parts.append(f"[{i}:v]scale={w}:{h}:...,setsar=1[v{i}]")
filter_parts.append(f"[v0][v1]...concat=n={n}:v=1:a=0[outv]")
cmd = [ffmpeg, "-filter_complex", filter_complex, "-map", "[outv]", ...]
```

**Fixed ffprobe Path (line 715-720):**
```python
# Before:
subprocess.run(["ffprobe", ...])

# After:
ffprobe_path = Path(self.ffmpeg_path).parent / "ffprobe.exe"
subprocess.run([str(ffprobe_path), ...])
```

### 3. `.env` (not in git)

Added:
```env
FFMPEG_PATH=C:\Users\SKP\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe
```

---

## Installation Requirements

### Full FFmpeg (for rendering)

Install via winget:
```powershell
winget install Gyan.FFmpeg
```

Default path after installation:
```
C:\Users\<USER>\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_...\ffmpeg-X.X.X-full_build\bin\ffmpeg.exe
```

### Topaz FFmpeg (for AI upscaling)

Included with Topaz Video AI installation:
```
C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe
```

---

## Testing

### Verify FFmpeg Installation
```bash
# Full FFmpeg - should show ass, subtitles, eq filters
ffmpeg -filters | grep -E "ass|subtitles|eq"

# Topaz FFmpeg - should show tvai_up filter
"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe" -filters | grep tvai
```

### Test Rendering
```python
from app.services.manifest_renderer import ManifestRenderer
renderer = ManifestRenderer()
print(f"Using: {renderer.ffmpeg_path}")
# Should show full FFmpeg path
```

---

## Rollback

If issues occur, revert:
1. `app/core/config.py` - remove FFMPEG_PATH field
2. `app/services/manifest_renderer.py` - restore original ffmpeg_path selection

---

## Related Commits

- `7bbeba1` - fix: ManifestRenderer uses full FFmpeg for subtitle support

---

## Contact

Changes made by: Claude Code (Opus 4.5)
Date: 2026-02-02
