"""
Smoke Test: GEN1 via Gemini API + Validator v2.0

Runs 3 GEN1 tests, validates each with gen1_validator v2.0,
saves raw + validated JSON, prints summary.

Usage:
    python -X utf8 run_smoke_validator.py
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai
from google.genai import types

from app.core.config import settings
from app.utils.prompt_loader import load_prompt_with_banlist
from app.services.gen1_validator import validate_gen1

# ---------------------------------------------------------------------------
CONFIG_DIR = PROJECT_ROOT / "config"
GEN1_PROMPT_PATH = CONFIG_DIR / "GEN1.txt"
BANLIST_PATH = CONFIG_DIR / "ban_list.txt"
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


def build_user_prompt(topic=None, num_scenes=8):
    if topic is None:
        return f"""NEW TOPIC
Generate a completely new, UNIQUE and VIRAL video concept.
MODE: AUTO - Create an original topic yourself!
CONSTRAINTS:
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: 10 seconds
- VISUAL STYLE: cinematic food fantasy
- TARGET AUDIENCE: YouTube Shorts viewers
CRITICAL: Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY.
Output ONLY valid JSON. Start with {{ and end with }}"""
    else:
        return f"""TOPIC: {topic}
Develop this idea into a complete video concept for "Glaze City" style channel.
CONSTRAINTS:
- SCENES: TARGET {num_scenes} scenes (Dynamic Scene Engine range: 6-10, but AIM FOR {num_scenes})
- TOTAL DURATION: 10 seconds
- VISUAL STYLE: cinematic food fantasy
- TARGET AUDIENCE: YouTube Shorts viewers
CRITICAL: Follow the OUTPUT CONTRACT FOR GEN2 EXACTLY.
Output ONLY valid JSON. Start with {{ and end with }}"""


async def run_smoke(client, model, system_prompt, topic, test_name):
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  SMOKE TEST: {test_name}")
    print(f"  Topic: {topic or 'AUTO'}")
    print(sep)

    user_prompt = build_user_prompt(topic)
    print(f"[GEN1] Calling Gemini... ({len(system_prompt):,} chars system, {len(user_prompt):,} chars user)")

    t0 = time.time()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=1.0,
                    max_output_tokens=16384,
                    response_mime_type="application/json",
                ),
            ),
            timeout=300,
        )
    except Exception as e:
        print(f"  API ERROR: {e}")
        return None
    api_time = time.time() - t0

    # Tokens
    prompt_tokens = output_tokens = "N/A"
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        u = response.usage_metadata
        prompt_tokens = getattr(u, 'prompt_token_count', 'N/A')
        output_tokens = getattr(u, 'candidates_token_count', 'N/A')

    try:
        raw_text = response.text
    except ValueError as e:
        print(f"  BLOCKED: {e}")
        return None

    if not raw_text:
        print("  EMPTY response!")
        return None

    print(f"  API: {api_time:.1f}s | tokens: {prompt_tokens} in / {output_tokens} out | {len(raw_text):,} chars")

    # Parse JSON
    try:
        data = extract_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  JSON PARSE FAILED: {e}")
        # Save raw for debug
        fail_path = OUTPUT_DIR / f"{test_name}_raw_fail.txt"
        fail_path.write_text(raw_text, encoding="utf-8")
        print(f"  Saved raw text: {fail_path}")
        return None

    # Save raw JSON
    json_path = OUTPUT_DIR / f"{test_name}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: {json_path}")

    # Quick summary
    meta = data.get("metadata", {})
    concept = meta.get("concept", {})
    scenes = data.get("scenes", [])
    hook = data.get("hook", {})
    food = data.get("food_identity", {})
    arch = data.get("architectural_identity", {})
    print(f"  Subject: {concept.get('subject', 'N/A')}")
    print(f"  Scenes: {len(scenes)} | Hook: {hook.get('type', 'N/A')}")
    print(f"  Food: {food.get('primary_food', 'N/A')} | Arch: {arch.get('style_code', 'N/A')}")

    # Scene listing
    for s in scenes:
        sn = s.get("scene_number", "?")
        name = s.get("scene_name", "N/A")
        purpose = s.get("narrative_purpose", "N/A")
        energy = s.get("energy_level", "N/A")
        vo = s.get("voiceover_segment", "")
        vo_short = vo[:60] + "..." if len(vo) > 60 else vo
        print(f"    [{sn}] {name} ({purpose}/{energy}) VO: \"{vo_short}\"")

    # ====== VALIDATOR v2.0 ======
    print(f"\n  --- VALIDATOR v2.0 ---")
    result = validate_gen1(data, strict_mode=False)
    status = "PASSED" if result.passed else "FAILED"
    print(f"  Result: {status} | {len(result.errors)} errors, {len(result.warnings)} warnings | {result.validation_time_ms:.1f}ms")

    if result.errors:
        print(f"  ERRORS:")
        for e in result.errors:
            print(f"    {e}")

    # Split warnings
    autofix_warnings = []
    validation_warnings = []
    for w in result.warnings:
        ws = str(w)
        if "Auto-" in ws or "auto-" in ws:
            autofix_warnings.append(w)
        else:
            validation_warnings.append(w)

    print(f"  Auto-fixes applied: {len(autofix_warnings)}")
    for w in autofix_warnings:
        print(f"    {w}")

    if validation_warnings:
        print(f"  Validation warnings: {len(validation_warnings)}")
        for w in validation_warnings:
            print(f"    {w}")

    # Save validated version
    if result.corrected_data:
        val_path = OUTPUT_DIR / f"{test_name}_validated.json"
        val_path.write_text(
            json.dumps(result.corrected_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  Saved validated: {val_path}")

    return {
        "name": test_name,
        "passed": result.passed,
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "autofixes": len(autofix_warnings),
        "val_warnings": len(validation_warnings),
        "api_time": api_time,
        "val_time": result.validation_time_ms,
        "tokens_in": prompt_tokens,
        "tokens_out": output_tokens,
        "subject": concept.get("subject", "N/A"),
    }


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("#" * 70)
    print(f"  GEN1 SMOKE TEST + VALIDATOR v2.0 — {timestamp}")
    print(f"  Model: {settings.CONTENTBRAIN_MODEL}")
    print("#" * 70)

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    model = settings.CONTENTBRAIN_MODEL

    gen1_prompt = load_prompt_with_banlist(GEN1_PROMPT_PATH, BANLIST_PATH)
    print(f"GEN1 prompt: {len(gen1_prompt):,} chars")

    tests = [
        ("smoke19_auto", None),
        ("smoke20_matcha", "Matcha lava cake factory inside a volcanic observatory tower"),
        ("smoke21_honey", "Honeycomb cathedral with liquid gold honey waterfalls"),
    ]

    results = []
    for name, topic in tests:
        r = await run_smoke(client, model, gen1_prompt, topic, name)
        if r:
            results.append(r)

    # Summary
    print(f"\n{'#' * 70}")
    print(f"  SUMMARY — {len(results)}/{len(tests)} tests completed")
    print("#" * 70)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(
            f"  [{status}] {r['name']}: {r['errors']}E {r['warnings']}W "
            f"({r['autofixes']} fixes, {r['val_warnings']} checks) | "
            f"API {r['api_time']:.1f}s, val {r['val_time']:.1f}ms | "
            f"{r['subject']}"
        )

    passed = sum(1 for r in results if r["passed"])
    print(f"\n  Total: {passed}/{len(results)} PASSED")
    print("#" * 70)


if __name__ == "__main__":
    asyncio.run(main())
