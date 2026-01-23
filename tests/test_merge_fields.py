"""
Test that all fields from GEN1/GEN2 models are properly mapped in merge.

This test prevents the common issue of adding fields to gen_models.py
but forgetting to add them to glaze_models.py or merge_outputs().
"""

import sys
from pathlib import Path
from typing import Set, Dict, Any, get_type_hints, get_origin, get_args
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.gen_models import (
    Gen1SceneConcept,
    Gen1VisualConcept,
    Gen1CameraIntent,
    Gen1Output,
    Gen2SceneOutput,
    Gen2BatchOutput,
)
from app.services.glaze_models import (
    GlazeScene,
    GlazeCityProject,
    VisualConcept,
    CameraIntent,
)


def get_all_fields(model: type) -> Set[str]:
    """Get all field names from a Pydantic model."""
    if hasattr(model, 'model_fields'):
        return set(model.model_fields.keys())
    return set()


def get_nested_fields(model: type, prefix: str = "") -> Dict[str, str]:
    """Get all fields including nested models, with dot notation."""
    fields = {}

    if not hasattr(model, 'model_fields'):
        return fields

    for name, field_info in model.model_fields.items():
        full_name = f"{prefix}.{name}" if prefix else name
        fields[full_name] = str(field_info.annotation)

        # Check if it's a nested Pydantic model
        annotation = field_info.annotation
        origin = get_origin(annotation)

        # Handle Optional types
        if origin is type(None) or str(origin) == "typing.Union":
            args = get_args(annotation)
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    nested = get_nested_fields(arg, full_name)
                    fields.update(nested)
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            nested = get_nested_fields(annotation, full_name)
            fields.update(nested)

    return fields


def test_gen1_scene_fields_in_glaze_scene():
    """Check that all Gen1SceneConcept fields exist in GlazeScene."""
    gen1_fields = get_all_fields(Gen1SceneConcept)
    glaze_fields = get_all_fields(GlazeScene)

    # Fields that are intentionally renamed or transformed
    field_mapping = {
        'reference_hint': None,  # Removed, using reference_type from GEN2
    }

    missing = []
    for field in gen1_fields:
        if field in field_mapping:
            continue  # Intentionally skipped/renamed
        if field not in glaze_fields:
            missing.append(field)

    if missing:
        print(f"\n[FAIL] Gen1SceneConcept fields missing in GlazeScene:")
        for f in sorted(missing):
            print(f"  - {f}")
        return False

    print(f"[OK] All {len(gen1_fields)} Gen1SceneConcept fields mapped to GlazeScene")
    return True


def test_gen1_visual_concept_fields():
    """Check that all Gen1VisualConcept fields exist in VisualConcept."""
    gen1_fields = get_all_fields(Gen1VisualConcept)
    glaze_fields = get_all_fields(VisualConcept)

    missing = []
    for field in gen1_fields:
        if field not in glaze_fields:
            missing.append(field)

    if missing:
        print(f"\n[FAIL] Gen1VisualConcept fields missing in VisualConcept:")
        for f in sorted(missing):
            print(f"  - {f}")
        return False

    print(f"[OK] All {len(gen1_fields)} Gen1VisualConcept fields mapped to VisualConcept")
    return True


def test_gen1_camera_intent_fields():
    """Check that all Gen1CameraIntent fields exist in CameraIntent."""
    gen1_fields = get_all_fields(Gen1CameraIntent)
    glaze_fields = get_all_fields(CameraIntent)

    missing = []
    for field in gen1_fields:
        if field not in glaze_fields:
            missing.append(field)

    if missing:
        print(f"\n[FAIL] Gen1CameraIntent fields missing in CameraIntent:")
        for f in sorted(missing):
            print(f"  - {f}")
        return False

    print(f"[OK] All {len(gen1_fields)} Gen1CameraIntent fields mapped to CameraIntent")
    return True


def test_gen2_scene_fields_in_glaze_scene():
    """Check that all Gen2SceneOutput fields exist in GlazeScene."""
    gen2_fields = get_all_fields(Gen2SceneOutput)
    glaze_fields = get_all_fields(GlazeScene)

    # Fields that are intentionally not copied (they come from GEN1 or are internal)
    skip_fields = {
        'reference_hint',  # GEN1 field duplicated in GEN2
        'visual_concept',  # Nested, handled separately
        'camera_intent',   # Nested, handled separately
        'broker_script',   # Comes from GEN1
        'voiceover_segment',  # Comes from GEN1
        'audio_moment',    # Comes from GEN1
        'duration_seconds',  # Comes from GEN1
        'scene_name',      # Comes from GEN1
        'narrative_purpose',  # Comes from GEN1
        'energy_level',    # Comes from GEN1
    }

    missing = []
    for field in gen2_fields:
        if field in skip_fields:
            continue
        if field not in glaze_fields:
            missing.append(field)

    if missing:
        print(f"\n[FAIL] Gen2SceneOutput fields missing in GlazeScene:")
        for f in sorted(missing):
            print(f"  - {f}")
        return False

    print(f"[OK] All relevant Gen2SceneOutput fields mapped to GlazeScene")
    return True


def print_field_comparison():
    """Print detailed field comparison for debugging."""
    print("\n" + "=" * 70)
    print("FIELD COMPARISON: gen_models.py vs glaze_models.py")
    print("=" * 70)

    print("\n--- Gen1SceneConcept ---")
    gen1_scene = get_all_fields(Gen1SceneConcept)
    for f in sorted(gen1_scene):
        print(f"  {f}")

    print("\n--- Gen1VisualConcept ---")
    gen1_vc = get_all_fields(Gen1VisualConcept)
    for f in sorted(gen1_vc):
        print(f"  {f}")

    print("\n--- Gen1CameraIntent ---")
    gen1_ci = get_all_fields(Gen1CameraIntent)
    for f in sorted(gen1_ci):
        print(f"  {f}")

    print("\n--- GlazeScene ---")
    glaze_scene = get_all_fields(GlazeScene)
    for f in sorted(glaze_scene):
        print(f"  {f}")

    print("\n--- VisualConcept (glaze) ---")
    glaze_vc = get_all_fields(VisualConcept)
    for f in sorted(glaze_vc):
        print(f"  {f}")

    print("\n--- CameraIntent (glaze) ---")
    glaze_ci = get_all_fields(CameraIntent)
    for f in sorted(glaze_ci):
        print(f"  {f}")


def main():
    """Run all merge field tests."""
    print("=" * 70)
    print("MERGE FIELD SYNCHRONIZATION TEST")
    print("Checking that all GEN1/GEN2 fields are mapped to GlazeScene")
    print("=" * 70)
    print()

    all_passed = True

    # Run tests
    if not test_gen1_scene_fields_in_glaze_scene():
        all_passed = False

    if not test_gen1_visual_concept_fields():
        all_passed = False

    if not test_gen1_camera_intent_fields():
        all_passed = False

    if not test_gen2_scene_fields_in_glaze_scene():
        all_passed = False

    print()
    print("=" * 70)

    if all_passed:
        print("[SUCCESS] All merge field tests PASSED")
        print("=" * 70)
        return 0
    else:
        print("[FAILURE] Some merge field tests FAILED")
        print("=" * 70)
        print("\nRun with --verbose to see detailed field comparison")
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test merge field synchronization")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed field comparison")
    args = parser.parse_args()

    if args.verbose:
        print_field_comparison()
        print()

    exit_code = main()
    sys.exit(exit_code)
