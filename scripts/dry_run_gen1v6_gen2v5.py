"""
DRY RUN: GEN1 v6.0.0 + GEN2 v5.0.0 Integration Test
=====================================================
Tests the new prompt pair end-to-end:
  1. GEN1 v6 → creative brief (dynamic 6-10 scenes)
  2. GEN2 v5 → visual prompts
  3. Merge by scene_number
  4. Diagnostic checks on new features

Usage:
  python scripts/dry_run_gen1v6_gen2v5.py
"""

import asyncio
import json
import sys
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# Fix Windows console encoding for emoji
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai
from google.genai import types
from app.core.config import settings

# ============================================================================
# CONFIG
# ============================================================================

CONFIG_DIR = PROJECT_ROOT / "config"
GEN1_V6_PATH = CONFIG_DIR / "GEN1_v6.txt"
GEN2_V5_PATH = CONFIG_DIR / "GEN2_v5.txt"
BANLIST_PATH = CONFIG_DIR / "ban_list.txt"
OUTPUT_DIR = PROJECT_ROOT / "debug" / "dry_run_v6v5"

TOPIC = "Mango submarine deep sea station"

FAKE_BLACKLIST = """
| # | Food | Subject | Category | Hook Type |
|---|------|---------|----------|-----------|
| 1 | Honey | Mansion | LUXURY_LISTINGS | THE_IMPOSSIBLE |
| 2 | Sushi | Train Station | TRANSIT | THE_SCALE_SHOCK |
| 3 | Chocolate | Villa | LUXURY_LISTINGS | THE_SENSORY_ATTACK |
| 4 | Waffle | Fire Station | COMMERCIAL | THE_ABSURD_LOGIC |
| 5 | Ice Cream | Lighthouse | LANDMARKS | THE_IMPOSSIBLE |
""".strip()


# ============================================================================
# PROMPT LOADING
# ============================================================================

def load_gen1_prompt() -> str:
    """Load GEN1 v6 with banlist + fake blacklist injection."""
    with open(GEN1_V6_PATH, "r", encoding="utf-8") as f:
        prompt = f.read()

    with open(BANLIST_PATH, "r", encoding="utf-8") as f:
        banlist = f.read().strip()

    # Inject banlist
    prompt = prompt.replace("{{BANLIST}}", banlist)

    # Inject fake blacklist
    prompt = prompt.replace("{{BLACKLIST_INJECTION}}", FAKE_BLACKLIST)

    # External table placeholders — leave as-is for tables that don't exist yet.
    # Gemini will use contextual knowledge from the examples in the prompt.
    for placeholder in [
        "{{ARCH_STYLES_TABLE}}",
        "{{FOOD_DNA_TABLE}}",
        "{{FOREGROUND_TABLE}}",
        "{{TRICKS_CATALOG}}",
        "{{FOLEY_TABLE}}",
    ]:
        if placeholder in prompt:
            prompt = prompt.replace(
                placeholder,
                f"[Table externalized — use your knowledge of the prompt examples and categories listed above]"
            )

    return prompt


def load_gen2_prompt() -> str:
    """Load GEN2 v5 prompt."""
    with open(GEN2_V5_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================================
# API CALLS
# ============================================================================

async def call_gen1(client: genai.Client, system_prompt: str, topic: str) -> Dict[str, Any]:
    """Call Gemini with GEN1 v6 system prompt."""
    user_prompt = f"""TOPIC: {topic}

Develop this idea into a complete video concept for "Glaze City" style channel.

CONSTRAINTS:
- NUMBER OF SCENES: Choose 7-9 scenes (dynamic — NOT fixed 6!)
- TOTAL DURATION: 12-20 seconds
- VISUAL STYLE: cinematic food fantasy
- TARGET AUDIENCE: YouTube Shorts viewers (US)

CRITICAL REQUIREMENTS (v6.0.0):
1. Follow the DYNAMIC SCENE ENGINE — pick a random scene count between 7-9
2. Include ALL mandatory fields per v6.0.0 spec
3. Every scene MUST include gen2_visual_params object
4. Every MIDDLE scene MUST include scene_tricks array + trick_context
5. Include exactly ONE STRUCTURAL_DETAIL scene with LOW energy (sensory scene)
6. For easter_egg, use format: "AUDIO_ONLY" (to test audio-only routing)
7. Include share_trigger in engagement
8. Include _concept_reasoning as FIRST field
9. broker_script = clean text, voiceover_segment = same text WITH [tags]

Output ONLY valid JSON. Start with {{ and end with }}"""

    print(f"\n{'='*60}")
    print(f"  STAGE 1: GEN1 v6.0.0 — Creative Director")
    print(f"  Topic: {topic}")
    print(f"  System prompt: {len(system_prompt):,} chars")
    print(f"{'='*60}")

    t0 = time.time()
    response = await client.aio.models.generate_content(
        model=settings.CONTENTBRAIN_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            max_output_tokens=32768,
        ),
    )
    elapsed = time.time() - t0

    text = response.text or ""
    print(f"  Response: {len(text):,} chars in {elapsed:.1f}s")

    # Extract JSON
    json_str = extract_json(text)
    data = json.loads(json_str)
    return data


async def call_gen2(
    client: genai.Client, system_prompt: str, gen1_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Call Gemini with GEN2 v5 system prompt."""
    gen1_json = json.dumps(gen1_data, indent=2, ensure_ascii=False)
    scene_count = len(gen1_data.get("scenes", []))

    user_prompt = f"""Generate visual prompts for the following creative brief:

{gen1_json}

⚠️ TOKEN LIMIT WARNING: Keep your response CONCISE to avoid truncation!
- image_prompt: MAX 130 words each
- video_prompt: MAX 40 words each
- motion_elements: MAX 4 items per scene
- scale_techniques: Keep brief, 5-10 words per field

CRITICAL REQUIREMENTS (v5.0.0):

1. SCENE COUNT (MANDATORY):
   - You MUST return EXACTLY {scene_count} scenes (matching GEN1 input)
   - scene_number MUST match GEN1 scene numbers exactly
   - Process ALL scenes from the input — do not skip any!

2. USE gen2_visual_params FROM EACH SCENE:
   - subject_scale → camera angle choice
   - depth_layers → foreground/mid/background layering
   - dominant_color + contrast_color → color prose
   - texture_focus → detail keywords
   - light_direction → lighting placement
   - atmosphere_density → haze level

3. TRANSLATE scene_tricks INTO PROMPTS:
   - Read trick_context from visual_concept
   - Weave trick keywords into image_prompt AND video_prompt naturally

4. EASTER EGG FORMAT ROUTING:
   - GEN1 specifies format = "AUDIO_ONLY"
   - For AUDIO_ONLY: do NOT add easter egg to image_prompt
   - Set easter_egg_integration = null for ALL scenes

5. SCENE {scene_count} LOOP REQUIREMENTS:
   - reference_type MUST be "LOOP_CLOSE"
   - Complementary camera movement (different from Scene 1)
   - Reversal-safe motion elements ONLY
   - Include loop_verification in visual_summary with ALL boolean fields = true

6. SENSORY SCENE:
   - Detect STRUCTURAL_DETAIL + LOW energy + Close/Extreme Close
   - Use SENSORY formula (no gigantism, macro detail)
   - scale_techniques = null for sensory scenes

Output ONLY valid JSON matching Gen2BatchOutput schema."""

    print(f"\n{'='*60}")
    print(f"  STAGE 2: GEN2 v5.0.0 — Visual Director")
    print(f"  Scenes from GEN1: {scene_count}")
    print(f"  System prompt: {len(system_prompt):,} chars")
    print(f"  Payload: {len(gen1_json):,} chars")
    print(f"{'='*60}")

    t0 = time.time()
    response = await client.aio.models.generate_content(
        model=settings.CONTENTBRAIN_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
            max_output_tokens=32768,
        ),
    )
    elapsed = time.time() - t0

    text = response.text or ""
    print(f"  Response: {len(text):,} chars in {elapsed:.1f}s")

    json_str = extract_json(text)
    data = json.loads(json_str)
    return data


# ============================================================================
# MERGE
# ============================================================================

def merge_outputs(gen1: Dict, gen2: Dict) -> Dict:
    """Merge GEN1 + GEN2 by scene_number."""
    # Build GEN2 scene lookup
    gen2_scenes = {}
    for s in gen2.get("scenes", []):
        sn = s.get("scene_number")
        if sn is not None:
            gen2_scenes[sn] = s

    merged_scenes = []
    for g1_scene in gen1.get("scenes", []):
        sn = g1_scene.get("scene_number")
        g2_scene = gen2_scenes.get(sn, {})

        # Deep merge: GEN1 base + GEN2 overlay
        merged = {**g1_scene}
        for key, value in g2_scene.items():
            if key == "scene_number":
                continue  # already in base
            merged[key] = value

        merged_scenes.append(merged)

    # Build final merged output
    merged = {}
    # Copy all GEN1 top-level fields
    for key, value in gen1.items():
        if key != "scenes":
            merged[key] = value
    # Add GEN2 top-level fields
    for key, value in gen2.items():
        if key != "scenes":
            merged[key] = value
    # Add merged scenes
    merged["scenes"] = merged_scenes

    return merged


# ============================================================================
# DIAGNOSTICS
# ============================================================================

def run_diagnostics(gen1: Dict, gen2: Dict, merged: Dict) -> List[str]:
    """Run all diagnostic checks. Returns list of [PASS]/[FAIL] results."""
    results = []
    gen1_scenes = gen1.get("scenes", [])
    gen2_scenes = gen2.get("scenes", [])
    merged_scenes = merged.get("scenes", [])
    scene_count = len(gen1_scenes)

    # ── 1. DYNAMIC SCENE COUNT ──
    results.append(f"\n{'─'*50}")
    results.append("1. DYNAMIC SCENE COUNT (not fixed 6)")
    results.append(f"{'─'*50}")
    results.append(f"   GEN1 scenes: {scene_count}")
    results.append(f"   GEN2 scenes: {len(gen2_scenes)}")
    results.append(f"   Merged scenes: {len(merged_scenes)}")
    if scene_count >= 7:
        results.append(f"   [PASS] Scene count = {scene_count} (>6, dynamic engine works)")
    elif scene_count == 6:
        results.append(f"   [WARN] Scene count = 6 (minimum — dynamic engine may not have triggered)")
    else:
        results.append(f"   [FAIL] Scene count = {scene_count} (unexpected)")

    if len(gen2_scenes) == scene_count:
        results.append(f"   [PASS] GEN2 returned matching scene count")
    else:
        results.append(f"   [FAIL] GEN2 scene count mismatch: {len(gen2_scenes)} vs {scene_count}")

    # ── 2. gen2_visual_params ──
    results.append(f"\n{'─'*50}")
    results.append("2. gen2_visual_params PRESENCE (new field in v6)")
    results.append(f"{'─'*50}")
    required_vp_fields = [
        "subject_scale", "depth_layers", "dominant_color",
        "contrast_color", "texture_focus", "light_direction", "atmosphere_density"
    ]
    for s in gen1_scenes:
        sn = s.get("scene_number")
        vp = s.get("gen2_visual_params")
        if vp:
            missing = [f for f in required_vp_fields if f not in vp]
            if missing:
                results.append(f"   Scene {sn}: [WARN] gen2_visual_params missing fields: {missing}")
            else:
                results.append(f"   Scene {sn}: [PASS] gen2_visual_params complete ({len(vp)} fields)")
        else:
            results.append(f"   Scene {sn}: [FAIL] gen2_visual_params MISSING")

    # ── 3. scene_tricks (middle scenes only) ──
    results.append(f"\n{'─'*50}")
    results.append("3. scene_tricks PRESENCE (middle scenes only)")
    results.append(f"{'─'*50}")
    last_scene_num = max(s.get("scene_number", 0) for s in gen1_scenes)
    tricks_found = 0
    for s in gen1_scenes:
        sn = s.get("scene_number")
        purpose = s.get("narrative_purpose", "")
        tricks = s.get("scene_tricks")
        vc = s.get("visual_concept", {})
        trick_context = vc.get("trick_context") if isinstance(vc, dict) else None

        # Middle scenes: not scene 1, not last, not second-to-last
        is_anchor = (sn == 1 or sn == last_scene_num or sn == last_scene_num - 1)

        if is_anchor:
            if tricks:
                results.append(f"   Scene {sn} ({purpose}): [WARN] anchor scene has scene_tricks (should NOT)")
            else:
                results.append(f"   Scene {sn} ({purpose}): [PASS] anchor scene — no tricks (correct)")
        else:
            if tricks and len(tricks) > 0:
                trick_ids = [t.get("trick_id", "?") for t in tricks]
                ctx = "yes" if trick_context else "NO"
                results.append(f"   Scene {sn} ({purpose}): [PASS] tricks={trick_ids}, trick_context={ctx}")
                tricks_found += 1
            else:
                results.append(f"   Scene {sn} ({purpose}): [FAIL] MISSING scene_tricks")

    if tricks_found > 0:
        results.append(f"   Total middle scenes with tricks: {tricks_found}")
    else:
        results.append(f"   [FAIL] No tricks found in any middle scene!")

    # ── 4. MERGE BY scene_number ──
    results.append(f"\n{'─'*50}")
    results.append("4. MERGE BY scene_number (dynamic count)")
    results.append(f"{'─'*50}")
    gen1_sns = sorted([s.get("scene_number") for s in gen1_scenes])
    gen2_sns = sorted([s.get("scene_number") for s in gen2_scenes])
    merged_sns = sorted([s.get("scene_number") for s in merged_scenes])

    results.append(f"   GEN1 scene_numbers: {gen1_sns}")
    results.append(f"   GEN2 scene_numbers: {gen2_sns}")
    results.append(f"   Merged scene_numbers: {merged_sns}")

    if gen1_sns == gen2_sns == merged_sns:
        results.append(f"   [PASS] All scene_numbers align perfectly")
    else:
        missing_in_gen2 = set(gen1_sns) - set(gen2_sns)
        extra_in_gen2 = set(gen2_sns) - set(gen1_sns)
        if missing_in_gen2:
            results.append(f"   [FAIL] GEN2 missing scenes: {sorted(missing_in_gen2)}")
        if extra_in_gen2:
            results.append(f"   [FAIL] GEN2 extra scenes: {sorted(extra_in_gen2)}")

    # Check merged scenes have BOTH GEN1 + GEN2 data
    for ms in merged_scenes:
        sn = ms.get("scene_number")
        has_gen1 = "visual_concept" in ms and "broker_script" in ms
        has_gen2 = "image_prompt" in ms and "video_prompt" in ms
        if has_gen1 and has_gen2:
            results.append(f"   Scene {sn}: [PASS] has GEN1 + GEN2 data")
        elif has_gen1:
            results.append(f"   Scene {sn}: [FAIL] has GEN1 but MISSING GEN2 data")
        elif has_gen2:
            results.append(f"   Scene {sn}: [FAIL] has GEN2 but MISSING GEN1 data")

    # ── 5. EASTER EGG AUDIO_ONLY ROUTING ──
    results.append(f"\n{'─'*50}")
    results.append("5. EASTER EGG: AUDIO_ONLY → null in image_prompt")
    results.append(f"{'─'*50}")
    ee = gen1.get("engagement", {}).get("easter_egg")
    if isinstance(ee, dict):
        fmt = ee.get("format", "UNKNOWN")
        results.append(f"   GEN1 easter_egg.format: {fmt}")
        if fmt == "AUDIO_ONLY":
            results.append(f"   [PASS] GEN1 correctly used AUDIO_ONLY format")
            # Check GEN2 didn't add easter egg to image prompts
            ee_in_prompts = False
            for s in gen2_scenes:
                eei = s.get("easter_egg_integration")
                if eei is not None and eei != {} and eei:
                    results.append(f"   Scene {s.get('scene_number')}: [FAIL] easter_egg_integration should be null for AUDIO_ONLY")
                    ee_in_prompts = True
            if not ee_in_prompts:
                results.append(f"   [PASS] GEN2 correctly set all easter_egg_integration = null")
        else:
            results.append(f"   [WARN] GEN1 used format '{fmt}' instead of AUDIO_ONLY (test wanted AUDIO_ONLY)")
    elif ee is None:
        fmt_check = gen1.get("engagement", {}).get("easter_egg")
        results.append(f"   GEN1 easter_egg = null (SKIP format)")
        results.append(f"   [WARN] Expected AUDIO_ONLY, got SKIP/null")
    else:
        results.append(f"   [WARN] easter_egg format unclear: {type(ee)}")

    # ── 6. SENSORY SCENE DETECTION ──
    results.append(f"\n{'─'*50}")
    results.append("6. SENSORY SCENE DETECTION (STRUCTURAL_DETAIL + LOW + Close)")
    results.append(f"{'─'*50}")
    sensory_found = False
    sensory_keywords = [
        "glistening", "dripping", "crystallized", "melting", "sticky",
        "crispy", "steaming", "sizzling", "bubbling", "glossy",
        "crunchy", "oozing", "frosted", "caramelized", "glazed"
    ]
    for s in gen1_scenes:
        sn = s.get("scene_number")
        purpose = s.get("narrative_purpose", "")
        energy = s.get("energy_level", "")
        ci = s.get("camera_intent", {})
        framing = ci.get("framing", "") if isinstance(ci, dict) else ""

        is_sensory = (
            purpose == "STRUCTURAL_DETAIL"
            and energy == "LOW"
            and ("Close" in framing or "close" in framing.lower())
        )

        if is_sensory:
            sensory_found = True
            results.append(f"   Scene {sn}: [PASS] SENSORY scene detected")
            results.append(f"     purpose={purpose}, energy={energy}, framing={framing}")

            # Check for sensory keywords in visual_concept
            vc = s.get("visual_concept", {})
            key_elements = vc.get("key_elements", []) if isinstance(vc, dict) else []
            ke_text = " ".join(key_elements).lower() if key_elements else ""
            found_kw = [kw for kw in sensory_keywords if kw in ke_text]
            if len(found_kw) >= 2:
                results.append(f"     [PASS] Sensory keywords in key_elements: {found_kw}")
            else:
                results.append(f"     [WARN] <2 sensory keywords found: {found_kw}")

            # Check GEN2 treated this as sensory (no gigantism)
            gen2_scene = next((gs for gs in gen2_scenes if gs.get("scene_number") == sn), None)
            if gen2_scene:
                st = gen2_scene.get("scale_techniques")
                if st is None or st == {}:
                    results.append(f"     [PASS] GEN2 scale_techniques = null (sensory exempt)")
                else:
                    results.append(f"     [WARN] GEN2 has scale_techniques for sensory scene (should be null)")

    if not sensory_found:
        results.append(f"   [FAIL] No sensory scene found (STRUCTURAL_DETAIL + LOW + Close)")
        # Try to find the closest match
        for s in gen1_scenes:
            purpose = s.get("narrative_purpose", "")
            energy = s.get("energy_level", "")
            if purpose == "STRUCTURAL_DETAIL":
                ci = s.get("camera_intent", {})
                framing = ci.get("framing", "") if isinstance(ci, dict) else ""
                results.append(f"   Closest: Scene {s.get('scene_number')} purpose={purpose} energy={energy} framing={framing}")

    # ── 7. LOOP VERIFICATION ──
    results.append(f"\n{'─'*50}")
    results.append("7. LOOP VERIFICATION OBJECT (all booleans = true)")
    results.append(f"{'─'*50}")
    vs = gen2.get("visual_summary", {})
    lv = vs.get("loop_verification", {}) if isinstance(vs, dict) else {}

    if not lv:
        results.append(f"   [FAIL] loop_verification not found in visual_summary")
    else:
        bool_fields = [
            "movements_are_different",
            "foreground_match",
            "lighting_match",
            "motion_elements_reversal_safe",
            "same_reference_image",
            "loop_ready",
        ]
        all_true = True
        for field in bool_fields:
            val = lv.get(field)
            status = "[PASS]" if val is True else "[FAIL]"
            if val is not True:
                all_true = False
            results.append(f"   {field}: {val} {status}")

        # Extra info
        results.append(f"   scene1_camera: {lv.get('scene1_camera_movement', '?')}")
        results.append(f"   sceneN_camera: {lv.get('sceneN_camera_movement', '?')}")
        results.append(f"   after_reverse: {lv.get('sceneN_after_reverse', '?')}")

        if all_true:
            results.append(f"   [PASS] ALL boolean fields = true — loop is ready!")
        else:
            results.append(f"   [FAIL] Some boolean fields are not true")

    # ── 8. BROKER_SCRIPT vs VOICEOVER_SEGMENT ──
    results.append(f"\n{'─'*50}")
    results.append("8. broker_script (clean) vs voiceover_segment (tagged)")
    results.append(f"{'─'*50}")
    import re
    tag_pattern = re.compile(r'\[.*?\]')
    for s in gen1_scenes:
        sn = s.get("scene_number")
        bs = s.get("broker_script", "")
        vs_seg = s.get("voiceover_segment", "")
        if not bs and not vs_seg:
            results.append(f"   Scene {sn}: (empty VO) [PASS]")
            continue
        bs_has_tags = bool(tag_pattern.search(bs))
        vs_has_tags = bool(tag_pattern.search(vs_seg))
        bs_status = "[FAIL] tags in broker_script!" if bs_has_tags else "[PASS]"
        vs_status = "[PASS]" if vs_has_tags else "[WARN] no tags in voiceover_segment"
        results.append(f"   Scene {sn}: broker_script {bs_status} | voiceover_segment {vs_status}")

    # ── 9. WORD COUNT (Rap God Rule) ──
    results.append(f"\n{'─'*50}")
    results.append("9. WORD COUNT (broker_script vs duration)")
    results.append(f"{'─'*50}")
    word_limits = {2.0: 4, 2.5: 5, 3.0: 7, 4.0: 10}
    for s in gen1_scenes:
        sn = s.get("scene_number")
        dur = s.get("duration_seconds", 0)
        bs = s.get("broker_script", "")
        is_anchor = (sn == 1 or sn == last_scene_num or sn == last_scene_num - 1)
        if is_anchor:
            continue  # Anchors have relaxed rules
        wc = len(bs.split()) if bs else 0
        limit = word_limits.get(dur, word_limits.get(int(dur), 10))
        status = "[PASS]" if wc <= limit else "[FAIL]"
        results.append(f"   Scene {sn}: {wc} words / {dur}s (max {limit}) {status}")

    # ── 10. _concept_reasoning (first field check) ──
    results.append(f"\n{'─'*50}")
    results.append("10. _concept_reasoning as FIRST FIELD")
    results.append(f"{'─'*50}")
    cr = gen1.get("_concept_reasoning")
    if cr:
        first_key = list(gen1.keys())[0]
        if first_key == "_concept_reasoning":
            results.append(f"   [PASS] _concept_reasoning is first field")
        else:
            results.append(f"   [WARN] _concept_reasoning exists but first key is '{first_key}'")
        results.append(f"   Content: {cr[:200]}...")
    else:
        results.append(f"   [FAIL] _concept_reasoning MISSING")

    return results


# ============================================================================
# UTILITIES
# ============================================================================

def extract_json(text: str) -> str:
    """Extract JSON from potentially wrapped response text."""
    # Try to find JSON block in markdown code fences
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end + 1]

    raise ValueError("No JSON found in response")


def save_json(data: Dict, path: Path, label: str) -> None:
    """Save JSON to file with pretty printing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved {label}: {path}")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / timestamp

    print("\n" + "=" * 60)
    print("  DRY RUN: GEN1 v6.0.0 + GEN2 v5.0.0")
    print(f"  Topic: {TOPIC}")
    print(f"  Model: {settings.CONTENTBRAIN_MODEL}")
    print(f"  Output: {run_dir}")
    print("=" * 60)

    # Load prompts
    gen1_prompt = load_gen1_prompt()
    gen2_prompt = load_gen2_prompt()
    print(f"\n  GEN1 v6 prompt: {len(gen1_prompt):,} chars")
    print(f"  GEN2 v5 prompt: {len(gen2_prompt):,} chars")

    # Initialize client
    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    # ── STAGE 1: GEN1 ──
    try:
        gen1_data = await call_gen1(client, gen1_prompt, TOPIC)
        save_json(gen1_data, run_dir / "gen1_output.json", "GEN1 output")

        scene_count = len(gen1_data.get("scenes", []))
        food = gen1_data.get("food_identity", {}).get("primary_food", "?")
        title = gen1_data.get("youtube", {}).get("title", "?")
        print(f"\n  GEN1 Summary:")
        print(f"    Scenes: {scene_count}")
        print(f"    Food: {food}")
        print(f"    Title: {title}")
    except Exception as e:
        print(f"\n  [ERROR] GEN1 failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # ── STAGE 2: GEN2 ──
    try:
        gen2_data = await call_gen2(client, gen2_prompt, gen1_data)
        save_json(gen2_data, run_dir / "gen2_output.json", "GEN2 output")

        gen2_scene_count = len(gen2_data.get("scenes", []))
        print(f"\n  GEN2 Summary:")
        print(f"    Scenes: {gen2_scene_count}")
        vs = gen2_data.get("visual_summary", {})
        if vs:
            print(f"    Gigantism: {vs.get('gigantism_protocol', '?')}")
            print(f"    Loop verified: {vs.get('loop_verified', '?')}")
    except Exception as e:
        print(f"\n  [ERROR] GEN2 failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # ── STAGE 3: MERGE ──
    merged = merge_outputs(gen1_data, gen2_data)
    save_json(merged, run_dir / "merged_output.json", "Merged output")
    print(f"\n  Merged: {len(merged.get('scenes', []))} scenes")

    # ── STAGE 4: DIAGNOSTICS ──
    print("\n" + "=" * 60)
    print("  DIAGNOSTIC RESULTS")
    print("=" * 60)

    results = run_diagnostics(gen1_data, gen2_data, merged)
    for line in results:
        print(line)

    # Save diagnostic report
    report_path = run_dir / "diagnostic_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"DRY RUN DIAGNOSTIC REPORT\n")
        f.write(f"Date: {timestamp}\n")
        f.write(f"Topic: {TOPIC}\n")
        f.write(f"Model: {settings.CONTENTBRAIN_MODEL}\n")
        f.write(f"GEN1 scenes: {len(gen1_data.get('scenes', []))}\n")
        f.write(f"GEN2 scenes: {len(gen2_data.get('scenes', []))}\n\n")
        for line in results:
            f.write(line + "\n")
    print(f"\n  Diagnostic report saved: {report_path}")

    # ── SUMMARY ──
    pass_count = sum(1 for r in results if "[PASS]" in r)
    fail_count = sum(1 for r in results if "[FAIL]" in r)
    warn_count = sum(1 for r in results if "[WARN]" in r)

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {pass_count} PASS | {fail_count} FAIL | {warn_count} WARN")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
