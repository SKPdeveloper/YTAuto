"""
LOSSLESS MERGE VALIDATOR

This test ACTUALLY compares input data (GEN1 + GEN2) with output (merged brief).
Unlike test_merge_fields.py which only checks schemas, this validates VALUES.

If this test fails, it means data was LOST during merge.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    """
    Flatten nested dict to dot-notation keys.

    Example:
        {"a": {"b": 1}} -> {"a.b": 1}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        elif isinstance(v, list):
            # For lists, store length and individual items
            items.append((f"{new_key}.__len__", len(v)))
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    items.extend(flatten_dict(item, f"{new_key}[{i}]", sep).items())
                else:
                    items.append((f"{new_key}[{i}]", item))
        else:
            items.append((new_key, v))
    return dict(items)


def compare_merge(
    gen1_path: Path,
    gen2_path: Path,
    merged_path: Path,
    verbose: bool = False
) -> Tuple[bool, List[str], List[str]]:
    """
    Compare GEN1 + GEN2 input with merged output.

    Returns:
        (is_valid, lost_fields, truncated_arrays)
    """
    # Load files
    with open(gen1_path, 'r', encoding='utf-8') as f:
        gen1 = json.load(f)
    with open(gen2_path, 'r', encoding='utf-8') as f:
        gen2 = json.load(f)
    with open(merged_path, 'r', encoding='utf-8') as f:
        merged = json.load(f)

    lost_fields = []
    truncated_arrays = []
    warnings = []

    # Check gen1_raw preservation
    if 'gen1_raw' not in merged:
        lost_fields.append("CRITICAL: gen1_raw not preserved in merged!")
    else:
        # Compare gen1 with gen1_raw
        gen1_flat = flatten_dict(gen1)
        gen1_raw_flat = flatten_dict(merged['gen1_raw'])

        for key, value in gen1_flat.items():
            if key not in gen1_raw_flat:
                lost_fields.append(f"gen1_raw missing: {key}")
            elif gen1_raw_flat[key] != value:
                if '__len__' in key:
                    truncated_arrays.append(f"gen1_raw array length mismatch: {key} (original={value}, stored={gen1_raw_flat[key]})")

    # Check gen2_raw preservation
    if 'gen2_raw' not in merged:
        lost_fields.append("CRITICAL: gen2_raw not preserved in merged!")
    else:
        gen2_flat = flatten_dict(gen2)
        gen2_raw_flat = flatten_dict(merged['gen2_raw'])

        for key, value in gen2_flat.items():
            if key not in gen2_raw_flat:
                lost_fields.append(f"gen2_raw missing: {key}")
            elif gen2_raw_flat[key] != value:
                if '__len__' in key:
                    truncated_arrays.append(f"gen2_raw array length mismatch: {key} (original={value}, stored={gen2_raw_flat[key]})")

    # ================================================================
    # CRITICAL FIELD CHECKS - fields that have been lost before
    # ================================================================

    # 1. Check viral_assessment preservation
    if 'viral_assessment' in gen1:
        va = gen1['viral_assessment']
        if 'gen1_raw' in merged and 'viral_assessment' in merged['gen1_raw']:
            stored_va = merged['gen1_raw']['viral_assessment']
            for key in ['hook_strength', 'humor_quotient', 'shareability',
                       'comment_potential', 'visual_uniqueness', 'overall_score']:
                if key in va and (key not in stored_va or stored_va[key] != va[key]):
                    lost_fields.append(f"viral_assessment.{key} not preserved (original={va.get(key)})")

    # 2. Check foley_palette.search_terms preservation
    if 'audio' in gen1 and 'foley_palette' in gen1['audio']:
        fp = gen1['audio']['foley_palette']
        if 'search_terms' in fp:
            original_len = len(fp['search_terms'])

            # Check in gen1_raw
            if 'gen1_raw' in merged:
                stored_fp = merged['gen1_raw'].get('audio', {}).get('foley_palette', {})
                stored_len = len(stored_fp.get('search_terms', []))
                if stored_len != original_len:
                    truncated_arrays.append(
                        f"foley_palette.search_terms truncated: original={original_len}, stored={stored_len}"
                    )

            # Check in top-level merged
            merged_fp = merged.get('audio', {}).get('foley_palette', {})
            merged_len = len(merged_fp.get('search_terms', []))
            if merged_len != original_len:
                warnings.append(
                    f"foley_palette.search_terms in merged: original={original_len}, merged={merged_len}"
                )

    # 3. Check youtube_hashtags preservation
    if 'youtube_hashtags' in gen1:
        original_hashtags = set(gen1['youtube_hashtags'])
        if 'gen1_raw' in merged and 'youtube_hashtags' in merged['gen1_raw']:
            stored_hashtags = set(merged['gen1_raw']['youtube_hashtags'])
            missing = original_hashtags - stored_hashtags
            if missing:
                lost_fields.append(f"youtube_hashtags lost: {missing}")

    # 4. Check scene reference_hint preservation (alongside reference_type)
    if 'scenes' in gen1:
        for i, scene in enumerate(gen1['scenes']):
            if 'reference_hint' in scene:
                original_hint = scene['reference_hint']
                # Check if preserved in gen1_raw
                if 'gen1_raw' in merged and 'scenes' in merged['gen1_raw']:
                    stored_scenes = merged['gen1_raw']['scenes']
                    if i < len(stored_scenes):
                        stored_hint = stored_scenes[i].get('reference_hint')
                        if stored_hint != original_hint:
                            lost_fields.append(
                                f"scene[{i}].reference_hint not preserved (original={original_hint})"
                            )

    # Print results
    is_valid = len(lost_fields) == 0 and len(truncated_arrays) == 0

    print("\n" + "=" * 70)
    print("LOSSLESS MERGE VALIDATION RESULTS")
    print("=" * 70)

    if is_valid:
        print("\n[OK] ALL FIELDS PRESERVED!")
    else:
        if lost_fields:
            print(f"\n[FAIL] LOST FIELDS ({len(lost_fields)}):")
            for field in lost_fields[:20]:
                print(f"  - {field}")
            if len(lost_fields) > 20:
                print(f"  ... and {len(lost_fields) - 20} more")

        if truncated_arrays:
            print(f"\n[FAIL] TRUNCATED ARRAYS ({len(truncated_arrays)}):")
            for arr in truncated_arrays:
                print(f"  - {arr}")

    if warnings and verbose:
        print(f"\n[WARN] WARNINGS ({len(warnings)}):")
        for warn in warnings:
            print(f"  - {warn}")

    print("\n" + "=" * 70)

    return is_valid, lost_fields, truncated_arrays


def main():
    """Run validation on latest test project."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate merge is lossless")
    parser.add_argument("--project", "-p", help="Project ID to test")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show warnings")
    args = parser.parse_args()

    base_dir = Path(__file__).parent.parent

    # Find project
    if args.project:
        project_id = args.project
    else:
        # Find latest script_ project
        projects_dir = base_dir / "projects"
        script_projects = sorted(projects_dir.glob("script_*"), reverse=True)
        if not script_projects:
            print("No script_ projects found. Run run_script_only.py first.")
            sys.exit(1)
        project_id = script_projects[0].name

    print(f"Testing project: {project_id}")

    # Find files
    project_dir = base_dir / "projects" / project_id
    merged_path = project_dir / "project_brief.json"

    debug_dir = base_dir / "debug" / "gen_responses"
    gen1_files = sorted(debug_dir.glob(f"GEN1_{project_id}*.txt"), reverse=True)
    gen2_files = sorted(debug_dir.glob(f"GEN2_{project_id}*.txt"), reverse=True)

    if not merged_path.exists():
        print(f"Merged brief not found: {merged_path}")
        sys.exit(1)

    if not gen1_files:
        print(f"GEN1 raw file not found for {project_id}")
        sys.exit(1)

    if not gen2_files:
        print(f"GEN2 raw file not found for {project_id}")
        sys.exit(1)

    gen1_path = gen1_files[0]
    gen2_path = gen2_files[0]

    print(f"  GEN1: {gen1_path.name}")
    print(f"  GEN2: {gen2_path.name}")
    print(f"  Merged: {merged_path.name}")

    is_valid, lost, truncated = compare_merge(
        gen1_path, gen2_path, merged_path,
        verbose=args.verbose
    )

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
