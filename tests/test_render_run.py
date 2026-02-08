"""
Test script: Run the manifest renderer on existing project data.

This tests the FULL post-processing render pipeline:
1. Load gen3b_manifest.json (or manifest.json)
2. Render video with ManifestRenderer (effects, speed maps, hook, subtitles, audio)
3. Verify output

Usage: python tests/test_render_run.py
"""

import asyncio
import json
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ID = "script_20260207_211506"


async def main():
    from app.core.config import settings
    from app.services.manifest_renderer import ManifestRenderer
    from app.services.gen_models import Gen3bManifest

    project_dir = settings.PROJECTS_DIR / PROJECT_ID

    print("=" * 60)
    print("POST-PROCESSING RENDER TEST")
    print("=" * 60)

    # Step 1: Find manifest
    manifest_path = project_dir / "gen3b_manifest.json"
    if not manifest_path.exists():
        old_manifest = project_dir / "manifest.json"
        if old_manifest.exists():
            print(f"Renaming manifest.json -> gen3b_manifest.json")
            shutil.copy2(old_manifest, manifest_path)
        else:
            print("ERROR: No manifest found!")
            return

    print(f"Manifest: {manifest_path}")

    # Step 2: Load manifest
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    manifest = Gen3bManifest.model_validate(manifest_data)
    print(f"Loaded manifest: {manifest.total_duration}s, {len(manifest.scenes)} scenes")
    print(f"  Hook style: {manifest.hook.style}, duration: {manifest.hook.duration}s")
    print(f"  Subtitles: {len(manifest.subtitles)}")
    print(f"  Audio layers: music={manifest.audio_layers.music.file if manifest.audio_layers.music else 'N/A'}")
    print(f"  SFX events: {len(manifest.audio_layers.sfx_events)}")

    for scene in manifest.scenes:
        print(f"  Scene {scene.scene_number}: {scene.source_file} | "
              f"{scene.timeline_start:.2f}-{scene.timeline_end:.2f}s | "
              f"speed_segs={len(scene.speed_segments)} | "
              f"effects={len(scene.effects)}")

    # Step 3: Remove old output
    old_output = project_dir / "final_video.mp4"
    if old_output.exists():
        backup = project_dir / "final_video_old_rawconcat.mp4"
        print(f"\nBacking up old output -> {backup.name}")
        shutil.move(str(old_output), str(backup))

    # Step 4: Render
    print("\n" + "=" * 60)
    print("STARTING RENDER...")
    print("=" * 60)

    renderer = ManifestRenderer()

    try:
        final_path = await renderer.render(
            manifest=manifest,
            project_dir=project_dir,
            output_filename="final_video.mp4"
        )
        print("\n" + "=" * 60)
        print(f"RENDER COMPLETE!")
        print(f"  Output: {final_path}")
        print(f"  Size: {final_path.stat().st_size / (1024*1024):.1f} MB")
        print("=" * 60)

        # Step 5: Get duration
        import subprocess
        ffprobe = str(settings.TOPAZ_FFMPEG_PATH).replace("ffmpeg.exe", "ffprobe.exe") if settings.TOPAZ_FFMPEG_PATH else "ffprobe"
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(final_path)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            print(f"  Duration: {duration:.1f}s")

        # Step 6: Check streams
        result2 = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name",
             "-of", "csv=p=0", str(final_path)],
            capture_output=True, text=True
        )
        if result2.returncode == 0:
            print(f"  Streams: {result2.stdout.strip()}")

    except Exception as e:
        print(f"\nRENDER FAILED: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
