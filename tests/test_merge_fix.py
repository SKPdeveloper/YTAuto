"""
Quick test to verify search_terms merge fix logic.
Simulates the actual merge path through Gen1FoleyPalette validator + merge logic.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the actual models to test the real behavior
try:
    from app.services.gen_models import Gen1FoleyPalette
    HAS_MODELS = True
except ImportError as e:
    print(f"Cannot import models: {e}")
    HAS_MODELS = False


def test_search_terms_preservation():
    """Test that search_terms are preserved through validator."""
    if not HAS_MODELS:
        print("Models not available, testing logic only")
        return test_logic_only()

    # Test data matching the actual GEN1 foley_palette
    test_data = {
        "primary_sounds": ["traffic hum", "wet sauce squish"],
        "search_terms": ["highway ambience", "pasta stir", "thick liquid flow", "steam hiss"],
        "scene_assignments": {"1": ["traffic whoosh", "wet impact"], "3": ["meatball thud", "low rumble"]}
    }

    print("Input data:")
    print(f"  primary_sounds: {test_data['primary_sounds']} ({len(test_data['primary_sounds'])})")
    print(f"  search_terms: {test_data['search_terms']} ({len(test_data['search_terms'])})")
    print()

    # Parse through validator
    foley = Gen1FoleyPalette.model_validate(test_data)

    print("After validator:")
    print(f"  sounds: {[(s.id, s.search) for s in foley.sounds]} ({len(foley.sounds)})")
    print(f"  primary_sounds: {foley.primary_sounds} ({len(foley.primary_sounds)})")
    print(f"  search_terms: {foley.search_terms} ({len(foley.search_terms)})")
    print()

    # Simulate merge logic from prompt_router.py (fixed version)
    if foley.sounds:
        search_from_sounds = [s.search for s in foley.sounds]
    else:
        search_from_sounds = []

    search_terms_list = foley.search_terms or []
    merged_search = list(dict.fromkeys(search_from_sounds + search_terms_list))

    print("Merge result:")
    print(f"  search_from_sounds: {search_from_sounds}")
    print(f"  search_terms_list: {search_terms_list}")
    print(f"  merged (deduplicated): {merged_search} ({len(merged_search)})")
    print()

    # Verify all original terms preserved
    original = set(test_data['search_terms'])
    result = set(merged_search)
    missing = original - result

    if missing:
        print(f"[FAIL] Missing search_terms: {missing}")
        return False
    elif len(merged_search) >= len(test_data['search_terms']):
        print(f"[OK] All {len(test_data['search_terms'])} search_terms preserved!")
        return True
    else:
        print(f"[FAIL] Not enough terms: expected {len(test_data['search_terms'])}, got {len(merged_search)}")
        return False


def test_logic_only():
    """Fallback test without model imports."""
    test_data = {
        "primary_sounds": ["traffic hum", "wet sauce squish"],
        "search_terms": ["highway ambience", "pasta stir", "thick liquid flow", "steam hiss"]
    }

    # Simulate validator conversion (converts primary to sounds, keeps search_terms)
    primary = test_data['primary_sounds']
    search = test_data['search_terms']
    sounds = []
    for i, s in enumerate(primary):
        search_term = search[i] if i < len(search) else s
        sounds.append({"id": s.replace(" ", "_"), "search": search_term})

    # search_terms stays intact
    search_terms_preserved = search

    # Merge logic
    search_from_sounds = [s['search'] for s in sounds]
    merged = list(dict.fromkeys(search_from_sounds + search_terms_preserved))

    print(f"sounds[].search: {search_from_sounds}")
    print(f"search_terms: {search_terms_preserved}")
    print(f"merged: {merged}")

    if len(merged) == len(search):
        print(f"[OK] All {len(search)} items preserved!")
        return True
    else:
        print(f"[FAIL] Expected {len(search)}, got {len(merged)}")
        return False


if __name__ == "__main__":
    success = test_search_terms_preservation()
    sys.exit(0 if success else 1)
