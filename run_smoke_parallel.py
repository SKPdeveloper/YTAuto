"""
Parallel Smoke Test: 3 GEN1 tests via Gemini API + Validator v2.1
Staggered API calls (10s delay), parallel validation.

Usage:
    python -X utf8 run_smoke_parallel.py
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


async def run_single_test(client, model, system_prompt, topic, test_name, delay_seconds):
    """Run a single smoke test with initial delay for API staggering."""
    if delay_seconds > 0:
        print(f"  [{test_name}] Waiting {delay_seconds}s before API call...")
        await asyncio.sleep(delay_seconds)

    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  SMOKE TEST: {test_name}")
    print(f"  Topic: {topic or 'AUTO'}")
    print(sep)

    user_prompt = build_user_prompt(topic)
    print(f"  [{test_name}] Calling Gemini... ({len(system_prompt):,} chars system)")

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
        print(f"  [{test_name}] API ERROR: {e}")
        return None
    api_time = time.time() - t0

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
        data = extract_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [{test_name}] JSON PARSE FAILED: {e}")
        fail_path = OUTPUT_DIR / f"{test_name}_raw_fail.txt"
        fail_path.write_text(raw_text, encoding="utf-8")
        print(f"  Saved raw text: {fail_path}")
        return None

    # Save raw JSON
    json_path = OUTPUT_DIR / f"{test_name}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [{test_name}] Saved: {json_path}")

    # Quick summary
    meta = data.get("metadata", {})
    concept = meta.get("concept", {})
    scenes = data.get("scenes", [])
    hook = data.get("hook", {})
    food = data.get("food_identity", {})
    arch = data.get("architectural_identity", {})
    print(f"  [{test_name}] Subject: {concept.get('subject', 'N/A')}")
    print(f"  [{test_name}] Scenes: {len(scenes)} | Hook: {hook.get('type', 'N/A')}")
    print(f"  [{test_name}] Food: {food.get('primary_food', 'N/A')} | Arch: {arch.get('style_code', 'N/A')}")

    # Scene listing
    for s in scenes:
        sn = s.get("scene_number", "?")
        name = s.get("scene_name", "N/A")
        purpose = s.get("narrative_purpose", "N/A")
        energy = s.get("energy_level", "N/A")
        sp = s.get("sensory_pressure", "?")
        vo = s.get("voiceover_segment", "")
        vo_short = vo[:60] + "..." if len(vo) > 60 else vo
        print(f"    [{sn}] {name} ({purpose}/{energy}/SP{sp}) VO: \"{vo_short}\"")

    # ====== VALIDATOR ======
    print(f"\n  [{test_name}] --- VALIDATOR v2.1 ---")
    result = validate_gen1(data, strict_mode=False)
    status = "PASSED" if result.passed else "FAILED"
    print(f"  [{test_name}] Result: {status} | {len(result.errors)} errors, {len(result.warnings)} warnings | {result.validation_time_ms:.1f}ms")

    if result.errors:
        print(f"  [{test_name}] ERRORS:")
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

    print(f"  [{test_name}] Auto-fixes applied: {len(autofix_warnings)}")
    for w in autofix_warnings:
        print(f"    {w}")

    if validation_warnings:
        print(f"  [{test_name}] Validation warnings: {len(validation_warnings)}")
        for w in validation_warnings:
            print(f"    {w}")

    # --- v9.2.0 BUG CHECKS ---
    print(f"\n  [{test_name}] --- v9.2.0 BUG CHECKS ---")
    bugs_found = []

    # BUG 1: energy arc — check if all VALLEY
    energies = [s.get("energy_level", "") for s in scenes if isinstance(s, dict)]
    mid_energies = energies[1:-1] if len(energies) > 2 else energies
    if mid_energies == ["MEDIUM", "LOW", "MEDIUM", "HIGH", "HIGH"] or mid_energies.count("LOW") == 0:
        pass  # not necessarily VALLEY
    arc_shape = "VALLEY" if "LOW" in mid_energies else "PLATEAU/ZIGZAG/OTHER"
    print(f"    BUG1 energy arc: {' → '.join(energies)} ({arc_shape})")

    # BUG 2: money shot position
    ms_scenes = [s.get("scene_number") for s in scenes if isinstance(s, dict) and isinstance(s.get("money_shot"), dict) and s["money_shot"].get("is_money_shot")]
    print(f"    BUG2 money_shot: scene(s) {ms_scenes} (N={len(scenes)})")

    # BUG 3: completion bait formula
    cb = data.get("completion_bait", {})
    vo_trigger = cb.get("vo_trigger", "") if isinstance(cb, dict) else ""
    formula = "A" if vo_trigger.lower().startswith("one more") else "B-E"
    print(f"    BUG3 completion_bait: \"{vo_trigger[:50]}\" (formula {formula})")

    # BUG 4: warning_line format
    wl = data.get("warning_line", "")
    if isinstance(wl, str) and wl.lower().startswith("don't"):
        wl_fmt = "A"
    elif isinstance(wl, str) and "i dare you" in wl.lower():
        wl_fmt = "B"
    elif isinstance(wl, str) and "architect" in wl.lower():
        wl_fmt = "C"
    elif isinstance(wl, str) and ("remembers" in wl.lower() or "knows" in wl.lower() or "watches" in wl.lower()):
        wl_fmt = "D"
    elif isinstance(wl, str) and "never meant" in wl.lower():
        wl_fmt = "E"
    elif isinstance(wl, str) and "nobody warns" in wl.lower():
        wl_fmt = "F"
    else:
        wl_fmt = "?"
    print(f"    BUG4 warning_line: \"{wl}\" (format {wl_fmt})")

    # BUG 6: title formula
    title = data.get("youtube", {}).get("title", "") if isinstance(data.get("youtube"), dict) else ""
    title_fmt = "FOOD_BUILD" if title.lower().startswith("i ") else "OTHER"
    print(f"    BUG6 title: \"{title[:50]}\" ({title_fmt})")

    # BUG 7: humor
    humor = data.get("humor", [])
    humor_types = [h.get("humor_type", "") for h in humor if isinstance(h, dict)]
    print(f"    BUG7 humor: {len(humor)} beats, types={humor_types}")

    # BUG 9: controversy
    cs = data.get("controversy_seed", {})
    ct = cs.get("technique", "") if isinstance(cs, dict) else ""
    print(f"    BUG9 controversy: {ct}")

    # BUG 10: series_hook
    si = data.get("series_identity", {})
    sh = si.get("series_hook", {}) if isinstance(si, dict) else {}
    sh_tech = sh.get("technique", "") if isinstance(sh, dict) else ""
    print(f"    BUG10 series_hook: {sh_tech}")

    # BUG 12: narrative_purpose — any invalid phase labels?
    invalid_purposes = {"ESCALATION", "CLIMAX", "TENSION", "SENSORY_BUILD", "AFTERMATH"}
    found_invalid = [(s.get("scene_number"), s.get("narrative_purpose")) for s in scenes
                     if isinstance(s, dict) and s.get("narrative_purpose") in invalid_purposes]
    print(f"    BUG12 narrative_purpose: {'CLEAN' if not found_invalid else f'INVALID: {found_invalid}'}")

    # BUG 14: on_screen_text Scene 1
    ost1 = scenes[0].get("on_screen_text", "") if scenes else ""
    print(f"    BUG14 on_screen_text S1: \"{ost1}\"")

    # Save validated version
    if result.corrected_data:
        val_path = OUTPUT_DIR / f"{test_name}_validated.json"
        val_path.write_text(
            json.dumps(result.corrected_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  [{test_name}] Saved validated: {val_path}")

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
        "food": food.get("primary_food", "N/A"),
        "bug_checks": {
            "energy_arc": arc_shape,
            "money_shot": ms_scenes,
            "completion_formula": formula,
            "warning_format": wl_fmt,
            "title_formula": title_fmt,
            "humor_count": len(humor),
            "humor_types": humor_types,
            "controversy": ct,
            "series_hook": sh_tech,
            "invalid_purposes": found_invalid,
        }
    }


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("#" * 70)
    print(f"  GEN1 v9.3.0 PARALLEL SMOKE TEST — {timestamp}")
    print(f"  Model: {settings.CONTENTBRAIN_MODEL}")
    print(f"  Strategy: 3 tests, 10s stagger between API calls")
    print("#" * 70)

    client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)
    model = settings.CONTENTBRAIN_MODEL

    gen1_prompt = load_prompt_with_banlist(GEN1_PROMPT_PATH, BANLIST_PATH)
    print(f"GEN1 prompt: {len(gen1_prompt):,} chars")

    tests = [
        ("smoke35_donut", "Donut cathedral with glaze stained glass windows and sprinkle gargoyles", 0),
        ("smoke36_sushi", "Sushi skyscraper with soy sauce river and wasabi smoke stacks", 10),
        ("smoke37_auto", None, 20),
    ]

    t_start = time.time()

    # Launch all 3 concurrently (each with its own delay)
    tasks = [
        run_single_test(client, model, gen1_prompt, topic, name, delay)
        for name, topic, delay in tests
    ]
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
    print(f"  SUMMARY — {len(results)}/{len(tests)} tests completed ({total_time:.1f}s total)")
    print("#" * 70)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        bc = r["bug_checks"]
        print(
            f"\n  [{status}] {r['name']}: {r['errors']}E {r['warnings']}W "
            f"({r['autofixes']} fixes, {r['val_warnings']} checks) | "
            f"API {r['api_time']:.1f}s | {r['subject']} / {r['food']}"
        )
        print(f"    energy={bc['energy_arc']} money={bc['money_shot']} "
              f"cb={bc['completion_formula']} wl={bc['warning_format']} "
              f"title={bc['title_formula']} humor={bc['humor_count']}×{bc['humor_types']} "
              f"contr={bc['controversy']} hook={bc['series_hook']} "
              f"invalid_np={bc['invalid_purposes'] or 'CLEAN'}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\n  Total: {passed}/{len(results)} PASSED")

    # Variety check across all 3
    if len(results) >= 2:
        print(f"\n  --- VARIETY CHECK (v9.2.0 anti-lock) ---")
        wl_fmts = [r["bug_checks"]["warning_format"] for r in results]
        contrs = [r["bug_checks"]["controversy"] for r in results]
        hooks = [r["bug_checks"]["series_hook"] for r in results]
        title_fmts = [r["bug_checks"]["title_formula"] for r in results]
        ms_pos = [r["bug_checks"]["money_shot"] for r in results]
        cb_fmts = [r["bug_checks"]["completion_formula"] for r in results]
        all_humor = []
        for r in results:
            all_humor.extend(r["bug_checks"]["humor_types"])

        print(f"    warning_formats: {wl_fmts} — {'LOCKED' if len(set(wl_fmts)) == 1 else 'VARIED ✓'}")
        print(f"    controversies: {contrs} — {'LOCKED' if len(set(contrs)) == 1 else 'VARIED ✓'}")
        print(f"    series_hooks: {hooks} — {'LOCKED' if len(set(hooks)) == 1 else 'VARIED ✓'}")
        print(f"    title_formulas: {title_fmts} — {'LOCKED' if len(set(title_fmts)) == 1 else 'VARIED ✓'}")
        print(f"    money_shots: {ms_pos} — {'LOCKED' if len(set(str(m) for m in ms_pos)) == 1 else 'VARIED ✓'}")
        print(f"    completion_bait: {cb_fmts} — {'LOCKED' if len(set(cb_fmts)) == 1 else 'VARIED ✓'}")
        print(f"    all humor types: {all_humor} — unique: {len(set(all_humor))}/{len(all_humor)}")

    print("#" * 70)


if __name__ == "__main__":
    asyncio.run(main())
