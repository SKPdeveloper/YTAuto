"""
GEN1 + GEN2 Smoke Test — Raw Output Review (No Validators)

Запускає GEN1 → DeliveryPayload → GEN2 і зберігає сирі JSON-аутпути
для ручної оцінки креативної якості.

Usage:
    # AUTO режим (Gemini сам вигадує тему)
    python test_gen1_gen2.py

    # З конкретною темою
    python test_gen1_gen2.py --topic "Wasabi volcano dip truck at luxury beach resort"

    # Тільки GEN1 (без GEN2)
    python test_gen1_gen2.py --gen1-only

    # Тільки GEN2 (з існуючого GEN1 файлу)
    python test_gen1_gen2.py --gen2-only --gen1-file debug/test_outputs/gen1_raw.json
"""

import asyncio
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai
from google.genai import types

from app.core.config import settings
from app.utils.prompt_loader import load_prompt_with_banlist


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_DIR = PROJECT_ROOT / "config"
GEN1_PROMPT_PATH = CONFIG_DIR / "GEN1.txt"
GEN2_PROMPT_PATH = CONFIG_DIR / "GEN2.txt"
BANLIST_PATH = CONFIG_DIR / "ban_list.txt"

OUTPUT_DIR = PROJECT_ROOT / "debug" / "test_outputs"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Extract JSON from Gemini response (handles markdown blocks)."""
    # Try markdown code block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if json_match:
        json_str = json_match.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end + 1]
        else:
            json_str = text.strip()

    # Strip trailing commas (common Gemini issue)
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    return json.loads(json_str)


def build_gen1_user_prompt(topic: str | None, num_scenes: int = 8) -> str:
    """Build user prompt for GEN1."""
    if topic is None:
        return f"""NEW TOPIC

Generate a completely new, UNIQUE and VIRAL video concept.

MODE: AUTO - Create an original topic yourself!

CONSTRAINTS:
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: 10 seconds
- VISUAL STYLE: cinematic food fantasy
- TARGET AUDIENCE: YouTube Shorts viewers

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object, scene_count matching actual scenes)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (6-10 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-N sequential)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

Output ONLY valid JSON. Start with {{ and end with }}"""
    else:
        return f"""TOPIC: {topic}

Develop this idea into a complete video concept for "Glaze City" style channel.

CONSTRAINTS:
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: 10 seconds
- VISUAL STYLE: cinematic food fantasy
- TARGET AUDIENCE: YouTube Shorts viewers

CRITICAL REQUIREMENTS:
1. Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY
2. Include ALL mandatory fields:
   - metadata (with concept object, scene_count matching actual scenes)
   - property
   - hook
   - architectural_identity (with style_code, style_description, distinctive_features, silhouette_description, interior_style)
   - food_identity (with primary_food, food_dna mapping ALL elements, texture_keywords, color_keywords, atmosphere)
   - lighting_master (with preset, mood_reason, prompt_snippet)
   - foreground_element (with type, prompt_snippet)
   - scenes (6-10 scenes with visual_concept and camera_intent)
   - voiceover (with full_script)
   - audio (with sonic_hook, suno_prompt, foley_palette, sfx_per_scene)
   - engagement (with easter_egg, share_trigger, hashtags)
3. Each scene MUST have:
   - scene_number (1-N sequential)
   - scene_name
   - duration_seconds
   - narrative_purpose
   - reference_hint (PRIMARY for scene 1, REQUIRES_REF/INDEPENDENT for others)
   - energy_level
   - visual_concept (with subject, environment, mood, key_elements, lighting_note, motion_elements)
   - camera_intent (with movement, combo, framing, special)
   - voiceover_segment
   - audio_moment

Output ONLY valid JSON. Start with {{ and end with }}"""


def build_gen2_user_prompt(payload_json: str) -> str:
    """Build user prompt for GEN2."""
    return f"""Generate visual prompts for the following creative brief:

{payload_json}

⚠️ TOKEN LIMIT WARNING: Keep your response CONCISE to avoid truncation!
- image_prompt: MAX 150 words each
- video_prompt: MAX 40 words each
- motion_elements: MAX 4 items per scene
- scale_techniques: Keep brief, 5-10 words per field

CRITICAL REQUIREMENTS:

1. SCENE COUNT (MANDATORY - DO NOT SKIP!):
   - You MUST return scenes matching the GEN1 scene count from the input
   - scene_number MUST be: 1 through N (in order, no duplicates, no gaps)
   - Process ALL scenes from the input - do not skip any!

2. IMAGE PROMPTS:
   - Use formulas from system prompt
   - Include "--no tilt-shift, miniature, diorama..." negative prompt
   - Include "subject positioned in upper portion of frame for vertical safe zone"
   - Scene 1 (PRIMARY): Full description with foreground, landscaping
   - REQUIRES_REF: Include "Maintaining exact design and material consistency..."
   - INDEPENDENT (interior): Include food floor, furniture, fixtures
   - NO --ar (hardcoded in software)

3. VIDEO PROMPTS:
   - MAX 40 words
   - 2-3+ motion elements per scene
   - NO banned words (slow, gentle, accelerating, rack focus, speed ramp)
   - Include camera movement
   - NO duration spec like "10s" (hardcoded in software)

4. SCENE 1 MUST HAVE first_frame_composition

5. LAST SCENE LOOP REQUIREMENTS (CRITICAL!):
   - reference_type MUST be "LOOP_CLOSE" (NOT "REQUIRES_REF"!)
   - Must match Scene 1 for seamless loop
   - Must have inheritance object referencing Scene 1

6. OUTPUT STRUCTURE:
   - scenes: array of Gen2SceneOutput objects with scene_number 1 through N
   - visual_summary: summary object with total_scenes matching scene count

Output ONLY valid JSON matching Gen2BatchOutput schema."""


def print_separator(char: str = "=", width: int = 70):
    print(char * width)


def print_gen1_summary(data: dict):
    """Print human-readable GEN1 summary."""
    print_separator()
    print("  GEN1 OUTPUT SUMMARY")
    print_separator()

    # Metadata
    meta = data.get("metadata", {})
    concept = meta.get("concept", {})
    print(f"\n  Title:    {meta.get('title', 'N/A')}")
    print(f"  Subject:  {concept.get('subject', 'N/A')}")
    print(f"  Category: {concept.get('category', 'N/A')}")
    print(f"  Scenes:   {meta.get('scene_count', 'N/A')}")

    # Property
    prop = data.get("property", data.get("structure", {}))
    print(f"\n  Property: {prop.get('name', 'N/A')}")
    print(f"  Location: {prop.get('location', 'N/A')}")
    print(f"  Price:    {prop.get('price', 'N/A')}")

    # Hook
    hook = data.get("hook", {})
    print(f"\n  Hook type:   {hook.get('type', 'N/A')}")
    print(f"  First words: {hook.get('first_words', 'N/A')}")

    # Architecture & Food
    arch = data.get("architectural_identity", {})
    food = data.get("food_identity", {})
    print(f"\n  Architecture: {arch.get('style_code', 'N/A')}")
    print(f"  Primary food: {food.get('primary_food', 'N/A')}")

    # Lighting
    light = data.get("lighting_master", {})
    print(f"  Lighting:     {light.get('preset', 'N/A')}")

    # Scenes
    scenes = data.get("scenes", [])
    print(f"\n  --- SCENES ({len(scenes)}) ---")
    for s in scenes:
        vc = s.get("visual_concept", {})
        cam = s.get("camera_intent", {})
        print(f"  [{s.get('scene_number', '?')}] {s.get('scene_name', 'N/A')}")
        print(f"      Purpose: {s.get('narrative_purpose', 'N/A')} | Energy: {s.get('energy_level', 'N/A')}")
        print(f"      Subject: {vc.get('subject', 'N/A')}")
        print(f"      Camera:  {cam.get('movement', 'N/A')} + {cam.get('combo', 'N/A')}")
        vo = s.get("voiceover_segment", "")
        if vo:
            print(f"      VO:      \"{vo[:80]}{'...' if len(vo) > 80 else ''}\"")

    # Voiceover full script
    vo_config = data.get("voiceover", {})
    full_script = vo_config.get("full_script", "")
    if full_script:
        print(f"\n  --- FULL SCRIPT ---")
        print(f"  \"{full_script}\"")

    # YouTube
    yt = data.get("youtube", {})
    print(f"\n  --- YOUTUBE ---")
    print(f"  Title:       {yt.get('title', 'N/A')}")
    desc = yt.get("description", "")
    if desc:
        print(f"  Description: {desc[:100]}{'...' if len(desc) > 100 else ''}")

    # Viral
    viral = data.get("viral_assessment", {})
    if viral:
        print(f"\n  --- VIRAL ASSESSMENT ---")
        print(f"  Overall: {viral.get('overall_score', 'N/A')}/10")
        print(f"  Verdict: {viral.get('verdict', 'N/A')}")

    print_separator()


def print_gen2_summary(data: dict):
    """Print human-readable GEN2 summary."""
    print_separator()
    print("  GEN2 OUTPUT SUMMARY")
    print_separator()

    scenes = data.get("scenes", [])
    print(f"\n  Total scenes: {len(scenes)}")

    for s in scenes:
        sn = s.get("scene_number", "?")
        ref = s.get("reference_type", "N/A")
        img = s.get("image_prompt", "")
        vid = s.get("video_prompt", "")
        motion = s.get("motion_elements", [])

        print(f"\n  [{sn}] ref={ref}")
        print(f"      Image prompt ({len(img.split())} words): {img[:120]}...")
        print(f"      Video prompt ({len(vid.split())} words): {vid[:100]}...")
        print(f"      Motion: {motion}")

        ffc = s.get("first_frame_composition")
        if ffc:
            print(f"      First frame: {ffc}")

    # Visual summary
    vs = data.get("visual_summary", {})
    if vs:
        print(f"\n  Visual summary: {vs}")

    print_separator()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_gen1(client, model: str, gen1_system_prompt: str, topic: str | None) -> dict | None:
    """Run GEN1 and return raw JSON dict."""
    user_prompt = build_gen1_user_prompt(topic)

    print("\n[GEN1] Calling Gemini...")
    print(f"  Model: {model}")
    print(f"  Mode: {'AUTO' if topic is None else f'IDEA ({topic})'}")
    print(f"  System prompt: {len(gen1_system_prompt):,} chars")
    print(f"  User prompt: {len(user_prompt):,} chars")

    t0 = time.time()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=gen1_system_prompt,
                temperature=0.7,
                max_output_tokens=16384,
                response_mime_type="application/json",
            ),
        ),
        timeout=300,
    )
    elapsed = time.time() - t0

    # Log metadata
    finish_reason = "UNKNOWN"
    if hasattr(response, 'candidates') and response.candidates:
        finish_reason = str(getattr(response.candidates[0], 'finish_reason', 'UNKNOWN'))
    prompt_tokens = output_tokens = "N/A"
    if hasattr(response, 'usage_metadata'):
        u = response.usage_metadata
        prompt_tokens = getattr(u, 'prompt_token_count', 'N/A')
        output_tokens = getattr(u, 'candidates_token_count', 'N/A')

    print(f"\n[GEN1] Response received in {elapsed:.1f}s")
    print(f"  Finish reason: {finish_reason}")
    print(f"  Tokens — prompt: {prompt_tokens}, output: {output_tokens}")

    try:
        raw_text = response.text
    except ValueError as e:
        print(f"\n[GEN1] BLOCKED by safety filters: {e}")
        return None

    if not raw_text:
        print("\n[GEN1] Empty response!")
        return None

    print(f"  Raw output: {len(raw_text):,} chars")

    # Save raw text
    raw_path = OUTPUT_DIR / "gen1_raw_text.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    print(f"  Saved raw text: {raw_path}")

    # Parse JSON
    try:
        data = extract_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"\n[GEN1] JSON parse FAILED: {e}")
        print(f"  Check {raw_path} for raw output")
        return None

    # Save parsed JSON
    json_path = OUTPUT_DIR / "gen1_raw.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved parsed JSON: {json_path}")

    # Quick Pydantic parse test (informational, not blocking)
    try:
        from app.services.gen_models import Gen1Output
        Gen1Output.model_validate(data)
        print("  Pydantic parse: OK")
    except Exception as e:
        print(f"  Pydantic parse: FAILED — {e}")
        print("  (This is informational — raw JSON is still saved for review)")

    return data


async def run_gen2(client, model: str, gen2_system_prompt: str, gen1_data: dict) -> dict | None:
    """Run GEN2 using GEN1 output and return raw JSON dict."""
    # Create DeliveryPayload through Pydantic
    try:
        from app.services.gen_models import Gen1Output, DeliveryPayload
        gen1_output = Gen1Output.model_validate(gen1_data)
        payload = DeliveryPayload.from_gen1_output(gen1_output, project_id="smoke_test")
        payload_json = payload.model_dump_json(indent=2)
    except Exception as e:
        print(f"\n[GEN2] Cannot create DeliveryPayload: {e}")
        print("  Falling back to manual extraction...")
        # Fallback: just dump the relevant parts of gen1_data
        payload_json = json.dumps(gen1_data, indent=2, ensure_ascii=False)

    user_prompt = build_gen2_user_prompt(payload_json)

    print("\n[GEN2] Calling Gemini...")
    print(f"  Model: {model}")
    print(f"  System prompt: {len(gen2_system_prompt):,} chars")
    print(f"  User prompt: {len(user_prompt):,} chars")

    t0 = time.time()
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=gen2_system_prompt,
                temperature=0.3,
                max_output_tokens=16384,
                response_mime_type="application/json",
            ),
        ),
        timeout=300,
    )
    elapsed = time.time() - t0

    # Log metadata
    finish_reason = "UNKNOWN"
    if hasattr(response, 'candidates') and response.candidates:
        finish_reason = str(getattr(response.candidates[0], 'finish_reason', 'UNKNOWN'))
    prompt_tokens = output_tokens = "N/A"
    if hasattr(response, 'usage_metadata'):
        u = response.usage_metadata
        prompt_tokens = getattr(u, 'prompt_token_count', 'N/A')
        output_tokens = getattr(u, 'candidates_token_count', 'N/A')

    print(f"\n[GEN2] Response received in {elapsed:.1f}s")
    print(f"  Finish reason: {finish_reason}")
    print(f"  Tokens — prompt: {prompt_tokens}, output: {output_tokens}")

    # Check for truncation
    if "MAX_TOKENS" in finish_reason or finish_reason == "2":
        print("  WARNING: Response was TRUNCATED (MAX_TOKENS)!")

    try:
        raw_text = response.text
    except ValueError as e:
        print(f"\n[GEN2] BLOCKED by safety filters: {e}")
        return None

    if not raw_text:
        print("\n[GEN2] Empty response!")
        return None

    print(f"  Raw output: {len(raw_text):,} chars")

    # Save raw text
    raw_path = OUTPUT_DIR / "gen2_raw_text.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    print(f"  Saved raw text: {raw_path}")

    # Parse JSON
    try:
        data = extract_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"\n[GEN2] JSON parse FAILED: {e}")
        print(f"  Check {raw_path} for raw output")
        return None

    # Save parsed JSON
    json_path = OUTPUT_DIR / "gen2_raw.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved parsed JSON: {json_path}")

    # Quick Pydantic parse test (informational)
    try:
        from app.services.gen_models import Gen2BatchOutput
        Gen2BatchOutput.model_validate(data)
        print("  Pydantic parse: OK")
    except Exception as e:
        print(f"  Pydantic parse: FAILED — {e}")
        print("  (This is informational — raw JSON is still saved for review)")

    return data


async def main():
    parser = argparse.ArgumentParser(description="GEN1 + GEN2 Smoke Test")
    parser.add_argument("--topic", type=str, default=None,
                        help="Topic for GEN1 (omit for AUTO mode)")
    parser.add_argument("--gen1-only", action="store_true",
                        help="Run only GEN1, skip GEN2")
    parser.add_argument("--gen2-only", action="store_true",
                        help="Run only GEN2 from existing GEN1 file")
    parser.add_argument("--gen1-file", type=str, default=None,
                        help="Path to existing GEN1 JSON (for --gen2-only)")
    parser.add_argument("--scenes", type=int, default=8,
                        help="Target number of scenes (default: 8)")
    args = parser.parse_args()

    # Ensure output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print_separator("#")
    print(f"  GEN1 + GEN2 SMOKE TEST — {timestamp}")
    print(f"  Model: {settings.CONTENTBRAIN_MODEL}")
    print_separator("#")

    # Init Gemini client
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    model = settings.CONTENTBRAIN_MODEL

    gen1_data = None

    # ========== GEN1 ==========
    if not args.gen2_only:
        # Load GEN1 system prompt (with banlist)
        gen1_system_prompt = load_prompt_with_banlist(
            prompt_path=GEN1_PROMPT_PATH,
            banlist_path=BANLIST_PATH,
        )
        print(f"\n[INIT] GEN1 prompt loaded: {len(gen1_system_prompt):,} chars")

        gen1_data = await run_gen1(client, model, gen1_system_prompt, args.topic)

        if gen1_data:
            print_gen1_summary(gen1_data)
        else:
            print("\n[GEN1] FAILED — cannot proceed to GEN2")
            return

        if args.gen1_only:
            print("\n--gen1-only flag set, skipping GEN2")
            print(f"\nOutputs saved to: {OUTPUT_DIR}")
            return
    else:
        # Load GEN1 from file
        gen1_file = Path(args.gen1_file) if args.gen1_file else OUTPUT_DIR / "gen1_raw.json"
        if not gen1_file.exists():
            print(f"\n[ERROR] GEN1 file not found: {gen1_file}")
            print("  Run with --gen1-only first, or specify --gen1-file")
            return
        gen1_data = json.loads(gen1_file.read_text(encoding="utf-8"))
        print(f"\n[INIT] Loaded GEN1 from: {gen1_file}")
        print_gen1_summary(gen1_data)

    # ========== GEN2 ==========
    gen2_system_prompt = GEN2_PROMPT_PATH.read_text(encoding="utf-8").strip()
    print(f"\n[INIT] GEN2 prompt loaded: {len(gen2_system_prompt):,} chars")

    gen2_data = await run_gen2(client, model, gen2_system_prompt, gen1_data)

    if gen2_data:
        print_gen2_summary(gen2_data)

    # ========== DONE ==========
    print_separator("#")
    print("  SMOKE TEST COMPLETE")
    print(f"\n  Output directory: {OUTPUT_DIR}")
    print(f"  Files:")
    for f in sorted(OUTPUT_DIR.glob("*.json")) + sorted(OUTPUT_DIR.glob("*.txt")):
        size = f.stat().st_size
        print(f"    {f.name} ({size:,} bytes)")
    print_separator("#")


if __name__ == "__main__":
    asyncio.run(main())
