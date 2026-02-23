"""
Tests for gen1_autocorrect.py — Fixes 1-7 (v3.10)

26 unit tests covering:
- Fix 1: Humor appended to existing VO (5 tests)
- Fix 2: Post-truncation humor rescue (3 tests)
- Fix 3: Break 3+ consecutive same energy (4 tests)
- Fix 5a: "Still warm" deduplication (1 test)
- Fix 5b: Thermal blacklist rotation (2 tests)
- Fix 6: Consecutive warm background audit (5 tests)
- Fix 7: Turn-word aware humor matching (6 tests)
"""

import copy
import pytest

from app.services.gen1_autocorrect import (
    autocorrect_gen1,
    AutoFixWarning,
    _surface_humor_to_vo,
    _verify_humor_survived,
    _extract_turn_words,
    _fix_energy_floor,
    _fix_thermal_first_word,
    _fix_consecutive_warm_backgrounds,
    _TEXTURE_TO_TEMPS,
    _max_words_for_duration,
    _strip_tags,
)


# ---------------------------------------------------------------------------
# HELPERS — minimal scene/brief builders
# ---------------------------------------------------------------------------

def _make_scene(sn: int, narrator: str = "", vo: str = "", osd: str = "",
                duration: float = 3.0, energy: str = "MEDIUM",
                bg_temp: str = "WARM", sp: int = 5,
                purpose: str = "FEATURE", **kw) -> dict:
    """Build a minimal scene dict."""
    scene = {
        "scene_number": sn,
        "scene_name": f"Scene {sn}",
        "narrator_script": narrator,
        "voiceover_segment": vo,
        "on_screen_text": osd,
        "duration_seconds": duration,
        "energy_level": energy,
        "background_temp": bg_temp,
        "sensory_pressure": sp,
        "narrative_purpose": purpose,
    }
    scene.update(kw)
    return scene


def _make_brief(scenes: list, humor: list = None, **kw) -> dict:
    """Build a minimal GEN1 brief."""
    brief = {
        "metadata": {
            "title": "Test Brief",
            "concept": {"subject": "cathedral", "food_material": "croissant", "category": "IMPOSSIBLE_FOOD"},
            "scene_count": len(scenes),
            "target_duration_seconds": 30,
        },
        "scenes": scenes,
        "food_identity": {
            "primary_food": "Croissant",
            "texture_keywords": ["crispy", "flaky"],
            "color_keywords": ["golden"],
            "food_dna": {"walls_become": "layers of pastry"},
        },
        "architectural_identity": {"style_code": "GOTHIC", "distinctive_features": ["flying buttresses"]},
        "hook": {"type": "THE_IMPOSSIBLE", "first_words": "Still warm.", "complete_hook_vo": "[whispers] Still warm."},
        "engagement": {"share_trigger": "test"},
        "lighting_master": {"preset": "GOLDEN_HOUR"},
    }
    if humor is not None:
        brief["humor"] = humor
    brief.update(kw)
    return brief


# =====================================================================
# FIX 1: Humor appended to existing VO (5 tests)
# =====================================================================

class TestFix1HumorAppendToVO:

    def test_humor_appended_to_existing_vo(self):
        """PATH 1: humor first sentence fits within word budget → append."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=3.0),
            _make_scene(2, narrator="Inside.", vo="[calm] Inside.", duration=3.0),
            _make_scene(3, narrator="The walls.", vo="[warm] The walls.", duration=3.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 3,
                   "line": "Fire department said no caramel.", "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        vo = d["scenes"][2]["voiceover_segment"]
        assert "caramel" in vo.lower()
        assert "[pause]" in vo
        assert any("PATH 1" in str(x) for x in w)

    def test_humor_shortened_clause_appended(self):
        """PATH 2: full humor too long, but first clause fits."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2, narrator="One two three four five.", vo="[calm] One two three four five.", duration=2.0),
        ]
        # Full humor = 8 words (too long for 2s=6w budget with existing 5w)
        # First clause "Added more" = 2 words → fits
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Added more, because the architect insisted on it.", "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        # Should use PATH 2 (shortened clause) or PATH 1 if clause fits
        vo = d["scenes"][1]["voiceover_segment"]
        narrator = d["scenes"][1]["narrator_script"]
        assert "added" in narrator.lower() or "added" in vo.lower() or any("PATH" in str(x) for x in w)

    def test_humor_placed_in_osd_when_vo_full(self):
        """PATH 3: VO is full, humor goes to on_screen_text."""
        # 2s scene → max 6 words. Narrator already has 6 words → no room to append.
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2,
                        narrator="One two three four five six.",
                        vo="[calm] One two three four five six.",
                        osd="",
                        duration=2.0),
        ]
        # Humor first sentence = long, first clause also long → force PATH 3
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Absolutely completely totally wildly insanely remarkably unbelievably broken.",
                   "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        osd = d["scenes"][1].get("on_screen_text", "")
        # Should have OSD text OR a warning (PATH 3 or all-exhausted)
        assert osd.strip() or any("orphaned" in str(x).lower() or "PATH 3" in str(x) for x in w)

    def test_humor_all_paths_exhausted_warns(self):
        """All 3 paths fail → warning emitted."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2,
                        narrator="One two three four five six.",
                        vo="[calm] One two three four five six.",
                        osd="Existing OSD text",
                        duration=2.0),
        ]
        # Humor = very long, no commas/dashes for clause split, OSD already occupied
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Absolutely completely totally wildly insanely remarkably unbelievably broken.",
                   "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        assert any("orphaned" in str(x).lower() or "exhausted" in str(x).lower() for x in w)

    def test_humor_silence_injection_unchanged(self):
        """[silence] scenes still get whispered humor injection (existing behavior)."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2, narrator="", vo="[silence]", duration=3.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Fire department said no caramel.", "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        vo = d["scenes"][1]["voiceover_segment"]
        assert "[whispers]" in vo
        assert "caramel" in vo.lower()


# =====================================================================
# FIX 2: Post-truncation humor rescue (3 tests)
# =====================================================================

class TestFix2HumorRescue:

    def test_humor_survives_full_autocorrect(self):
        """Humor present in VO survives the full autocorrect pipeline."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2, narrator="Inside the walls.", vo="[calm] Inside the walls.", duration=3.0),
            _make_scene(3,
                        narrator="The fire department said no caramel.",
                        vo="[warm] The fire department said no caramel.",
                        duration=3.0),
            _make_scene(4, narrator="Layers hold.", vo="[calm] Layers hold.", duration=2.0),
            _make_scene(5, narrator="Loop.", vo="[silence]", duration=2.0,
                        purpose="LOOP_CLOSE"),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 3,
                   "line": "The fire department said no caramel. We added more.",
                   "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        result, warnings = autocorrect_gen1(d)
        # Humor keywords should survive in scene 3
        s3_vo = result["scenes"][2].get("voiceover_segment", "")
        s3_narrator = result["scenes"][2].get("narrator_script", "")
        text = (s3_vo + " " + s3_narrator).lower()
        assert "fire" in text or "caramel" in text or "department" in text

    def test_humor_restored_after_truncation(self):
        """Humor lost to truncation is rescued by _verify_humor_survived."""
        # Simulate post-truncation state: scene VO was truncated, humor words are gone
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2, narrator="The walls hold.", vo="[calm] The walls hold.", duration=2.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Fire department said no caramel. We added more caramel.",
                   "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _verify_humor_survived(d, d["scenes"], w)
        # Should have restored humor into scene 2
        s2 = d["scenes"][1]
        text = (s2.get("narrator_script", "") + " " + s2.get("voiceover_segment", "")).lower()
        assert "fire" in text or "caramel" in text or "department" in text
        assert any("RESCUE" in str(x) for x in w)

    def test_humor_truncation_impossible_warns(self):
        """If humor can't be restored (too long for budget), HIGH warning emitted."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm."),
            _make_scene(2, narrator="X.", vo="[calm] X.", duration=1.0),  # 1s = 3 word limit
        ]
        # Humor first sentence = way too long for 1s budget
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "The fire department absolutely categorically definitively refused all caramel applications.",
                   "setup": "s", "turn": "t"}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _verify_humor_survived(d, d["scenes"], w)
        assert any("[HIGH]" in str(x) for x in w)


# =====================================================================
# FIX 3: Break 3+ consecutive same energy (4 tests)
# =====================================================================

class TestFix3ConsecutiveEnergy:

    def test_three_consecutive_medium_broken(self):
        """3x MEDIUM → middle pumped to HIGH."""
        scenes = [
            _make_scene(1, energy="MEDIUM"),
            _make_scene(2, energy="MEDIUM"),
            _make_scene(3, energy="MEDIUM"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_energy_floor(d, scenes, w)
        assert scenes[1]["energy_level"] == "HIGH"
        assert any("pumped" in str(x).lower() or "3x consecutive MEDIUM" in str(x) for x in w)

    def test_three_consecutive_high_broken(self):
        """3x HIGH → middle dropped to MEDIUM."""
        scenes = [
            _make_scene(1, energy="HIGH"),
            _make_scene(2, energy="HIGH"),
            _make_scene(3, energy="HIGH"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_energy_floor(d, scenes, w)
        assert scenes[1]["energy_level"] == "MEDIUM"
        assert any("valley" in str(x).lower() or "3x consecutive HIGH" in str(x) for x in w)

    def test_two_consecutive_same_untouched(self):
        """2x same energy is fine — no change."""
        scenes = [
            _make_scene(1, energy="MEDIUM"),
            _make_scene(2, energy="MEDIUM"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_energy_floor(d, scenes, w)
        # Pass 4 needs 3 scenes, so 2 consecutive should NOT trigger it
        assert scenes[0]["energy_level"] == "MEDIUM"
        assert scenes[1]["energy_level"] == "MEDIUM"
        assert not any("3x consecutive" in str(x) for x in w)

    def test_mixed_energy_untouched(self):
        """MEDIUM-HIGH-MEDIUM is fine — no change."""
        scenes = [
            _make_scene(1, energy="MEDIUM"),
            _make_scene(2, energy="HIGH"),
            _make_scene(3, energy="MEDIUM"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_energy_floor(d, scenes, w)
        assert scenes[0]["energy_level"] == "MEDIUM"
        assert scenes[1]["energy_level"] == "HIGH"
        assert scenes[2]["energy_level"] == "MEDIUM"
        assert not any("3x consecutive" in str(x) for x in w)


# =====================================================================
# FIX 5a: "Still warm" deduplication (1 test)
# =====================================================================

class TestFix5aDeduplication:

    def test_still_warm_deduplicated(self):
        """'Still warm.' appears only in chewy[3], not in crispy or crunchy."""
        crispy_temps = _TEXTURE_TO_TEMPS["crispy"]
        crunchy_temps = _TEXTURE_TO_TEMPS["crunchy"]
        chewy_temps = _TEXTURE_TO_TEMPS["chewy"]

        assert "Still warm." not in crispy_temps
        assert "Still warm." not in crunchy_temps
        assert "Still warm." in chewy_temps  # remains only here


# =====================================================================
# FIX 5b: Thermal blacklist rotation (2 tests)
# =====================================================================

class TestFix5bThermalBlacklist:

    def test_thermal_blacklist_rotates(self):
        """If selected thermal is in blacklist, rotates to next candidate."""
        scenes = [
            _make_scene(1, narrator="The walls hold everything.", vo="[calm] The walls hold everything.", duration=3.0),
        ]
        d = _make_brief(scenes)
        # Force hash to select index 0 of crispy: "Barely cooled."
        # Then blacklist it
        w = []
        blacklist = {"barely cooled"}
        _fix_thermal_first_word(d, d["scenes"], w, thermal_blacklist=blacklist)
        narrator = d["scenes"][0]["narrator_script"]
        # Should NOT start with "Barely cooled." since it's blacklisted
        assert not narrator.lower().startswith("barely cooled")
        # Should still have SOME thermal prepend
        assert any("Auto-prepended THERMAL" in str(x) for x in w)

    def test_thermal_blacklist_all_blocked_keeps(self):
        """If ALL candidates are blacklisted, keeps original selection."""
        scenes = [
            _make_scene(1, narrator="The walls hold.", vo="[calm] The walls hold.", duration=3.0),
        ]
        d = _make_brief(scenes)
        w = []
        # Block everything for crispy
        blacklist = {"barely cooled", "the heat", "scorched", "warm. flaky"}
        _fix_thermal_first_word(d, d["scenes"], w, thermal_blacklist=blacklist)
        narrator = d["scenes"][0]["narrator_script"]
        # Should still have a thermal prepend (kept original even though blacklisted)
        assert any("Auto-prepended THERMAL" in str(x) for x in w)


# =====================================================================
# FIX 6: Consecutive warm background audit (5 tests)
# =====================================================================

class TestFix6ConsecutiveWarmBackground:

    def test_consecutive_warm_neutral_fixed(self):
        """WARM + NEUTRAL → second scene set to COLD."""
        scenes = [
            _make_scene(1, bg_temp="WARM"),
            _make_scene(2, bg_temp="NEUTRAL"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_consecutive_warm_backgrounds(d, scenes, w)
        assert scenes[1]["background_temp"] == "COLD"

    def test_consecutive_warm_warm_fixed(self):
        """WARM + WARM → second scene set to COLD."""
        scenes = [
            _make_scene(1, bg_temp="WARM"),
            _make_scene(2, bg_temp="WARM"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_consecutive_warm_backgrounds(d, scenes, w)
        assert scenes[1]["background_temp"] == "COLD"

    def test_high_sp_food_dominant_exempted(self):
        """SP≥8 + FOOD_DOMINANT purpose → exempted from fix."""
        scenes = [
            _make_scene(1, bg_temp="WARM", sp=9, purpose="DETAIL"),
            _make_scene(2, bg_temp="WARM", sp=8, purpose="FEATURE"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_consecutive_warm_backgrounds(d, scenes, w)
        assert scenes[1]["background_temp"] == "WARM"  # unchanged

    def test_cold_cold_untouched(self):
        """COLD + COLD → no change."""
        scenes = [
            _make_scene(1, bg_temp="COLD"),
            _make_scene(2, bg_temp="COLD"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_consecutive_warm_backgrounds(d, scenes, w)
        assert scenes[1]["background_temp"] == "COLD"
        assert len(w) == 0

    def test_cold_injected_into_image_prompt(self):
        """When background_temp fixed to COLD, cold term injected into image_prompt."""
        scenes = [
            _make_scene(1, bg_temp="WARM", image_prompt="Golden light on pastry layers"),
            _make_scene(2, bg_temp="WARM", image_prompt="Warm glow on honey dripping"),
        ]
        d = _make_brief(scenes)
        w = []
        _fix_consecutive_warm_backgrounds(d, scenes, w)
        img = scenes[1]["image_prompt"]
        assert "steel" in img.lower() or "cool" in img.lower()


# =====================================================================
# FIX 7: Turn-word aware humor matching (6 tests)
# =====================================================================

class TestFix7TurnWordAwareHumor:

    def test_turn_substitution_detected(self):
        """Setup in VO + turn missing → surfaced=False, VO replaced with humor line."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2,
                        narrator="The bars aren't gold. Smooth.",
                        vo="[calm] The bars aren't gold. Smooth.",
                        duration=3.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "The bars aren't gold. Hazelnut.",
                   "setup": "The bars aren't gold.", "turn": "Hazelnut."}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        vo = d["scenes"][1]["voiceover_segment"]
        narrator = d["scenes"][1]["narrator_script"]
        # Turn word "Hazelnut" must be present
        assert "hazelnut" in vo.lower()
        assert "hazelnut" in narrator.lower()
        # "Smooth" should be gone
        assert "smooth" not in vo.lower()
        assert any("TURN FIX" in str(x) for x in w)

    def test_turn_present_not_flagged(self):
        """Setup + turn both in VO → surfaced=True, no changes."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2,
                        narrator="The bars aren't gold. Hazelnut.",
                        vo="[calm] The bars aren't gold. Hazelnut.",
                        duration=3.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "The bars aren't gold. Hazelnut.",
                   "setup": "The bars aren't gold.", "turn": "Hazelnut."}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        # No warnings — humor is already properly surfaced
        assert not any("TURN FIX" in str(x) for x in w)
        assert not any("PATH" in str(x) for x in w)

    def test_single_sentence_humor_no_turn_check(self):
        """Single-sentence humor → general matcher only, no turn logic."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2, narrator="Inside.", vo="[calm] Inside.", duration=3.0),
        ]
        # Single-sentence humor — no turn to check
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "Fire department said no caramel.",
                   "setup": "Fire department said no caramel.", "turn": ""}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        vo = d["scenes"][1]["voiceover_segment"]
        # Should use normal injection (PATH 1/silence) since humor not surfaced
        assert "caramel" in vo.lower() or any("PATH" in str(x) or "TURN" in str(x) for x in w)

    def test_turn_rescue_after_truncation(self):
        """_verify_humor_survived detects missing turn and rescues."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2,
                        narrator="The bars aren't gold. Smooth.",
                        vo="[calm] The bars aren't gold. Smooth.",
                        duration=3.0),
        ]
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "The bars aren't gold. Hazelnut.",
                   "setup": "The bars aren't gold.", "turn": "Hazelnut."}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _verify_humor_survived(d, d["scenes"], w)
        # Should have rescued: turn word present in VO
        s2 = d["scenes"][1]
        text = (s2.get("narrator_script", "") + " " + s2.get("voiceover_segment", "")).lower()
        assert "hazelnut" in text or any("RESCUE" in str(x) for x in w)

    def test_short_turn_word_detected(self):
        """Turn word with 3 chars (e.g., 'Jam') is caught by >=3 threshold."""
        scenes = [
            _make_scene(1, narrator="Still warm.", vo="[whispers] Still warm.", duration=2.0),
            _make_scene(2,
                        narrator="The golden butter melts. Smooth.",
                        vo="[calm] The golden butter melts. Smooth.",
                        duration=4.0),
        ]
        # Setup has enough >3-char words for vo_hits>=2, turn is short "Jam"
        humor = [{"humor_type": "DEADPAN_CONSEQUENCE", "scene_number": 2,
                   "line": "The golden butter melts. Jam.",
                   "setup": "The golden butter melts.", "turn": "Jam."}]
        d = _make_brief(scenes, humor=humor)
        w = []
        _surface_humor_to_vo(d, d["scenes"], w)
        vo = d["scenes"][1]["voiceover_segment"]
        narrator = d["scenes"][1]["narrator_script"]
        text = (vo + " " + narrator).lower()
        # "jam" is 3 chars — should be detected by >=3 threshold in turn words
        assert "jam" in text
        assert any("TURN FIX" in str(x) for x in w)

    def test_extract_turn_words_helper(self):
        """Direct unit test for _extract_turn_words() with various inputs."""
        # Multi-sentence: last sentence is the turn
        result = _extract_turn_words("The bars aren't gold. Hazelnut.")
        assert result is not None
        assert "hazelnut" in result

        # Single sentence: returns None
        result = _extract_turn_words("Fire department said no caramel.")
        assert result is None

        # Short turn word (3 chars)
        result = _extract_turn_words("Not butter. Jam.")
        assert result is not None
        assert "jam" in result

        # Very short words (<3 chars) filtered out
        result = _extract_turn_words("Something setup. It is.")
        # "it" and "is" are <3 chars, should be filtered
        assert result is None or len(result) == 0 or result is None

        # Empty string
        result = _extract_turn_words("")
        assert result is None

        # Three sentences: last is turn
        result = _extract_turn_words("Setup one. Setup two. Punchline here.")
        assert result is not None
        assert "punchline" in result
        assert "here" in result
