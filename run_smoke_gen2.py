"""
Smoke Test: GEN2 via Gemini API + autocorrect + validator

Takes existing GEN1 validated outputs as input, runs GEN2, validates.

Usage:
    python -X utf8 run_smoke_gen2.py
    python -X utf8 run_smoke_gen2.py --inputs 44 45 46
"""

import asyncio
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.gen_models import Gen1Output, DeliveryPayload
from app.services.gen2_autocorrect import autocorrect_gen2
from app.services.gen2_validator import validate_gen2

CONFIG_DIR = PROJECT_ROOT / "config"
GEN2_PROMPT_PATH = CONFIG_DIR / "GEN2.txt"
OUTPUT_DIR = PROJECT_ROOT / "debug" / "test_outputs"


def extract_json(text: str) -> dict:
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
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    return json.loads(json_str)


def find_gen1_inputs(input_nums: List[int]) -> List[Path]:
    """Find validated GEN1 JSON files by smoke number."""
    found = []
    for num in input_nums:
        pattern = f"smoke{num}_*_validated.json"
        matches = sorted(OUTPUT_DIR.glob(pattern))
        if matches:
            found.append(matches[0])
        else:
            # Try without _validated
            pattern2 = f"smoke{num}_*.json"
            matches2 = [m for m in sorted(OUTPUT_DIR.glob(pattern2)) if "_validated" not in m.name]
            if matches2:
                found.append(matches2[0])
            else:
                print(f"  WARNING: No file found for smoke{num}")
    return found


def build_gen2_user_prompt(payload: DeliveryPayload) -> str:
    """Build GEN2 user prompt from delivery payload (mirrors prompt_router logic)."""
    payload_json = payload.model_dump_json(indent=2)
    scene_count = len(payload.scenes)

    return f"""Generate visual prompts for the following creative brief:

{payload_json}

⚠️ TOKEN LIMIT: Keep CONCISE to avoid truncation.
- image_prompt: per WORD COUNT HIERARCHY in system prompt (money shot 130-150w, others less)
- video_prompt: per ENERGY LEVELS table (15-40 words depending on energy)
- motion_elements: MAX 4 items per scene

REQUIREMENTS:

1. SCENE COUNT: Return EXACTLY {scene_count} scenes, scene_number 1 through {scene_count}, no gaps.

2. TIER SYSTEM: Assign visual_tier MECHANICALLY from sensory_pressure + money_shot per system prompt rules. Write money shot scene FIRST (≥130 words, longest in output).

3. IMAGE PROMPTS: Use FORMULAS from system prompt per tier. Negative prompt required. Safe zone required. NO --ar, NO --duration, NO quality specs.

4. VIDEO PROMPTS: Use SP-driven motion vocabulary. NO banned words (slow, gentle, subtle, drifting, floating, gliding, accelerating, rack focus, speed ramp). NO "10s". Gerunds required.

5. LOOP_CLOSE: Last scene reference_type="LOOP_CLOSE" with inheritance. Different camera movement from Scene 1. Reversal-safe motion only. Standalone description (no "Scene 1", "identical", "matching").

6. COLOR ACCURACY: Warm/golden tones on FOOD SURFACES only. Environment keeps true natural colors. Anti-yellow in negative prompts.

7. Scene 1: first_frame_composition REQUIRED. body_trigger visual emphasis (≥2 keywords).

Output ONLY valid JSON."""


async def run_gen2_smoke(
    client,
    model: str,
    gen2_prompt: str,
    gen1_path: Path,
    test_name: str,
    delay_seconds: int = 0,
) -> Optional[Dict[str, Any]]:
    """Run a single GEN2 smoke test from a GEN1 validated output."""
    if delay_seconds > 0:
        print(f"  [{test_name}] Waiting {delay_seconds}s before API call...")
        await asyncio.sleep(delay_seconds)

    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  GEN2 SMOKE: {test_name}")
    print(f"  Input: {gen1_path.name}")
    print(sep)

    # Load GEN1 validated output
    gen1_data = json.loads(gen1_path.read_text(encoding="utf-8"))

    # Pre-process: fix target_duration_seconds if it's non-int
    meta = gen1_data.get("metadata", {})
    tds = meta.get("target_duration_seconds")
    if tds is not None and not isinstance(tds, int):
        if isinstance(tds, float):
            meta["target_duration_seconds"] = int(tds)
        elif isinstance(tds, str):
            # Extract first number from strings like "11-12" or "13 (minimum viable...)"
            m = re.search(r'(\d+)', str(tds))
            meta["target_duration_seconds"] = int(m.group(1)) if m else 10
        else:
            meta["target_duration_seconds"] = 10

    # Parse into Gen1Output
    try:
        gen1_output = Gen1Output.model_validate(gen1_data)
    except Exception as e:
        print(f"  [{test_name}] Gen1Output parse FAILED: {e}")
        return None

    # Create delivery payload
    try:
        payload = DeliveryPayload.from_gen1_output(gen1_output)
    except Exception as e:
        print(f"  [{test_name}] DeliveryPayload FAILED: {e}")
        return None

    food = gen1_data.get("food_identity", {}).get("primary_food", "N/A")
    arch = gen1_data.get("architectural_identity", {}).get("style_code", "N/A")
    scene_count = len(payload.scenes)
    print(f"  [{test_name}] Food: {food} | Arch: {arch} | Scenes: {scene_count}")

    # Build user prompt
    user_prompt = build_gen2_user_prompt(payload)

    # Call Gemini
    print(f"  [{test_name}] Calling Gemini GEN2... ({len(gen2_prompt):,} chars system, {len(user_prompt):,} chars user)")
    t0 = time.time()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=gen2_prompt,
                    temperature=1.0,
                    max_output_tokens=16384,
                    response_mime_type="application/json",
                ),
            ),
            timeout=300,
        )
    except Exception as e:
        print(f"  [{test_name}] API ERROR: {e}")
        return None
    api_time = time.time() - t0

    # Token usage
    prompt_tokens = output_tokens = "N/A"
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        u = response.usage_metadata
        prompt_tokens = getattr(u, 'prompt_token_count', 'N/A')
        output_tokens = getattr(u, 'candidates_token_count', 'N/A')

    try:
        raw_text = response.text
    except ValueError as e:
        print(f"  [{test_name}] BLOCKED: {e}")
        return None

    if not raw_text:
        print(f"  [{test_name}] EMPTY response!")
        return None

    print(f"  [{test_name}] API: {api_time:.1f}s | tokens: {prompt_tokens} in / {output_tokens} out | {len(raw_text):,} chars")

    # Parse JSON
    try:
        gen2_data = extract_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [{test_name}] JSON PARSE FAILED: {e}")
        fail_path = OUTPUT_DIR / f"{test_name}_gen2_raw_fail.txt"
        fail_path.write_text(raw_text, encoding="utf-8")
        print(f"  Saved raw text: {fail_path}")
        return None

    # Save raw GEN2 output
    raw_path = OUTPUT_DIR / f"{test_name}_gen2_raw.json"
    raw_path.write_text(json.dumps(gen2_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [{test_name}] Saved raw: {raw_path}")

    # Quick scene summary
    gen2_scenes = gen2_data.get("scenes", [])
    print(f"  [{test_name}] GEN2 scenes: {len(gen2_scenes)}")
    for s in gen2_scenes:
        sn = s.get("scene_number", "?")
        tier = s.get("visual_tier", "N/A")
        ref = s.get("reference_type", "N/A")
        ip = s.get("image_prompt", "")
        wc = len(ip.split()) if ip else 0
        print(f"    [S{sn}] {tier} | {ref} | {wc}w")

    # ====== AUTOCORRECT ======
    print(f"\n  [{test_name}] --- AUTOCORRECT v2.2 ---")
    t1 = time.time()
    corrected, ac_warnings = autocorrect_gen2(gen2_data, gen1_data)
    ac_time = (time.time() - t1) * 1000

    print(f"  [{test_name}] Auto-fixes: {len(ac_warnings)} ({ac_time:.1f}ms)")
    for w in ac_warnings:
        print(f"    {w}")

    # ====== VALIDATOR ======
    print(f"\n  [{test_name}] --- VALIDATOR ---")
    result = validate_gen2(corrected, gen1_data, auto_fix=True)
    status = "PASSED" if result.passed else "FAILED"
    print(f"  [{test_name}] Result: {status} | {len(result.errors)} errors, {len(result.warnings)} warnings | {result.validation_time_ms:.1f}ms")

    if result.errors:
        print(f"  [{test_name}] ERRORS:")
        for e in result.errors:
            print(f"    {e}")

    if result.warnings:
        print(f"  [{test_name}] WARNINGS:")
        for w in result.warnings:
            print(f"    {w}")

    if result.auto_fixes:
        print(f"  [{test_name}] VALIDATOR AUTO-FIXES: {len(result.auto_fixes)}")
        for f in result.auto_fixes:
            print(f"    {f}")

    # Post-correction scene summary
    print(f"\n  [{test_name}] --- POST-CORRECTION SUMMARY ---")
    cor_scenes = corrected.get("scenes", [])
    for s in cor_scenes:
        sn = s.get("scene_number", "?")
        tier = s.get("visual_tier", "N/A")
        ref = s.get("reference_type", "N/A")
        ip = s.get("image_prompt", "")
        wc = len(ip.split()) if ip else 0
        mi = s.get("motion_intensity", "?")
        print(f"    [S{sn}] {tier} | {ref} | {wc}w | MI={mi}")

    # Visual summary check
    vs = corrected.get("visual_summary", {})
    if vs:
        print(f"    tier_breakdown: {vs.get('tier_breakdown', 'MISSING')}")
        print(f"    scale_protocol: {vs.get('scale_protocol', 'MISSING')}")
        print(f"    tricks_applied: {vs.get('tricks_applied', 'MISSING')}")
        print(f"    loop_verified: {vs.get('loop_verified', 'MISSING')}")
        print(f"    sp_curve: {vs.get('sp_curve', 'MISSING')}")

    # FFC check (Scene 1)
    ffc = cor_scenes[0].get("first_frame_composition") if cor_scenes else None
    if ffc:
        ffc_fields = list(ffc.keys())
        expected = {"hook_element", "entry_type", "focal_point", "foreground", "background",
                    "color_anchor", "temperature_mood", "body_trigger_visual",
                    "safe_zone", "motion_visible", "scroll_stop"}
        missing = expected - set(ffc_fields)
        print(f"    FFC fields: {len(ffc_fields)}/11 | missing: {missing or 'none'}")
    else:
        print(f"    FFC: MISSING!")

    # Save corrected output
    cor_path = OUTPUT_DIR / f"{test_name}_gen2_corrected.json"
    cor_path.write_text(json.dumps(corrected, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [{test_name}] Saved corrected: {cor_path}")

    return {
        "name": test_name,
        "input": gen1_path.name,
        "food": food,
        "passed": result.passed,
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "autofixes_ac": len(ac_warnings),
        "autofixes_val": len(result.auto_fixes),
        "api_time": api_time,
        "ac_time_ms": ac_time,
        "val_time_ms": result.validation_time_ms,
        "tokens_in": prompt_tokens,
        "tokens_out": output_tokens,
        "scene_count": len(gen2_scenes),
        "error_messages": [str(e) for e in result.errors],
    }


async def main():
    parser = argparse.ArgumentParser(description="GEN2 Smoke Test")
    parser.add_argument("--inputs", nargs="+", type=int, default=[44, 45, 46],
                        help="Smoke test numbers to use as GEN1 input (default: 44 45 46)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("#" * 70)
    print(f"  GEN2 v6.5.0 SMOKE TEST — {timestamp}")
    print(f"  Model: {settings.CONTENTBRAIN_MODEL}")
    print(f"  Inputs: smoke{args.inputs}")
    print(f"  Strategy: {len(args.inputs)} tests, 10s stagger")
    print("#" * 70)

    # Load GEN2 system prompt
    gen2_prompt = GEN2_PROMPT_PATH.read_text(encoding="utf-8").strip()
    print(f"GEN2 prompt: {len(gen2_prompt):,} chars")

    # Find GEN1 input files
    gen1_files = find_gen1_inputs(args.inputs)
    if not gen1_files:
        print("ERROR: No GEN1 input files found!")
        return

    print(f"Found {len(gen1_files)} GEN1 inputs:")
    for f in gen1_files:
        print(f"  {f.name}")

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    model = settings.CONTENTBRAIN_MODEL

    t_start = time.time()

    # Launch all tests concurrently with stagger
    tasks = []
    for i, gen1_path in enumerate(gen1_files):
        stem = gen1_path.stem.replace("_validated", "")
        test_name = stem
        delay = i * 10  # 10s stagger
        tasks.append(run_gen2_smoke(client, model, gen2_prompt, gen1_path, test_name, delay))

    results_raw = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = time.time() - t_start

    # Filter results
    results = []
    for r in results_raw:
        if isinstance(r, Exception):
            print(f"  EXCEPTION: {r}")
        elif r is not None:
            results.append(r)

    # Summary
    print(f"\n{'#' * 70}")
    print(f"  SUMMARY — {len(results)}/{len(gen1_files)} tests ({total_time:.1f}s total)")
    print("#" * 70)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"\n  [{status}] {r['name']}: {r['errors']}E {r['warnings']}W "
            f"({r['autofixes_ac']} ac + {r['autofixes_val']} val fixes) | "
            f"API {r['api_time']:.1f}s | {r['food']} | {r['scene_count']} scenes"
        )
        if r["error_messages"]:
            for em in r["error_messages"]:
                print(f"    ERROR: {em}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\n  Total: {passed}/{len(results)} PASSED")
    print("#" * 70)


if __name__ == "__main__":
    asyncio.run(main())
