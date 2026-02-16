"""
GEN1 & GEN2 Data Models - v2.2

Models for the two-stage prompt generation system matching GEN1/GEN2 OUTPUT CONTRACTS:
- GEN1: Script, concept, voiceover, audio, architectural/food identity (story & structure)
- GEN2: Visual prompts (image_prompt, video_prompt, reference_type, motion_elements)

The delivery module (prompt_router.py) handles the data flow between stages.

VALIDATION: All required fields are validated per GEN1/GEN2 contracts.
"""

import re
import warnings

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any, Tuple, Union
from enum import Enum


def _coerce_to_str_list(v: Any) -> List[str]:
    """Coerce Gemini output to List[str] — handles string, list, None."""
    if v is None:
        return []
    if isinstance(v, str):
        # Split comma-separated string into list
        return [s.strip() for s in v.split(',') if s.strip()]
    if isinstance(v, list):
        return [str(item) for item in v]
    return [str(v)]


# ============================================================================
# REQUIRED FIELDS CONTRACTS
# ============================================================================

# Scene count bounds (dynamic 6-10, shared with gen1_validator / gen2_validator)
MIN_SCENES: int = 6
MAX_SCENES: int = 10

# Обов'язкові поля GEN1 output
REQUIRED_GEN1_FIELDS = [
    "metadata",
    "metadata.concept.category",
    "metadata.concept.subject",
    "metadata.concept.food_material",
    "metadata.scene_count",  # має бути 6-10 (динамічно)
    "property",
    "hook",
    "hook.type",  # THE_IMPOSSIBLE | THE_ABSURD_LOGIC | THE_SCALE_SHOCK | THE_SENSORY_ATTACK
    "hook.psychological_trigger",
    "hook.first_words",
    "architectural_identity",
    "architectural_identity.style_code",
    "architectural_identity.silhouette_description",
    "architectural_identity.distinctive_features",
    "food_identity",
    "food_identity.primary_food",
    "food_identity.food_dna",
    "food_identity.food_dna.walls_become",
    "food_identity.food_dna.roof_becomes",
    "lighting_master",
    "lighting_master.preset",
    "lighting_master.prompt_snippet",
    "foreground_element",
    "foreground_element.prompt_snippet",
    "scenes",  # array of 6-10 (dynamic)
    "voiceover",
    "audio",
    "audio.suno_prompt",
    "audio.foley_palette",
    "audio.sfx_per_scene",
    "engagement.easter_egg",
    "engagement.easter_egg.object",
    "engagement.easter_egg.scene_number",
    "engagement.easter_egg.placement",
]

# Обов'язкові поля кожної scene
REQUIRED_SCENE_FIELDS = [
    "scene_number",
    "narrative_purpose",
    "reference_hint",
    "energy_level",
    "visual_concept",
    "visual_concept.subject",
    "visual_concept.environment",
    "visual_concept.motion_elements",
    "camera_intent",
    "camera_intent.movement",
    "voiceover_segment",
]

# Обов'язкові поля для передачі GEN1 → GEN2 (DeliveryPayload)
REQUIRED_HANDOFF_FIELDS = [
    "architectural_identity",  # повний об'єкт
    "food_identity",           # повний об'єкт
    "lighting_master",         # повний об'єкт
    "foreground_element",      # повний об'єкт
    "easter_egg",              # повний об'єкт
    "scenes",                  # array of Gen2SceneInput
]

# Valid hook types
VALID_HOOK_TYPES = [
    "THE_IMPOSSIBLE",
    "THE_ABSURD_LOGIC",
    "THE_SCALE_SHOCK",
    "THE_SENSORY_ATTACK",
    "THE_WHISPER",
    "THE_SOUND_FIRST",
    "THE_TEXTURE_ZOOM",
]

# Valid psychological triggers (accept any string — GEN1 prompt encourages creative values)
VALID_PSYCHOLOGICAL_TRIGGERS = [
    "DISBELIEF",
    "PATTERN_BREAK",
    "AWE",
    "SENSORY",
    "CONTRAST_HOOK",
    "AUDIO_PRIME",
    "CURIOSITY_GAP",
    "OLFACTORY_RECALL",
    "SYNAESTHESIA",
    "OLFACTORY_MEMORY",
]

# Valid narrative purposes
VALID_NARRATIVE_PURPOSES = [
    "ESTABLISHING",
    "EXTERIOR_ANGLE",
    "AERIAL",
    "INTERIOR",
    "DETAIL",
    "FEATURE",
    "LOOP_CLOSE",
    "STRUCTURAL_DETAIL",
    "THEMATIC_INTERIOR",
    "CONTEXTUAL_ENVIRONMENT",
    "DYNAMIC_ACTION",
    "FEATURE_HIGHLIGHT",
    "AERIAL_WOW",
    "AERIAL_REVEAL",
]

# Valid reference hints
VALID_REFERENCE_HINTS = [
    "PRIMARY",
    "REQUIRES_REF",
    "INDEPENDENT",
    "LOOP_CLOSE",
]

# Valid energy levels
VALID_ENERGY_LEVELS = [
    "EXPLOSIVE",
    "HIGH",
    "MEDIUM",
    "LOW",
]

# Valid camera movements
VALID_CAMERA_MOVEMENTS = [
    "APPROACH",
    "RETREAT",
    "ORBIT",
    "RISE",
    "DESCEND",
    "RUSH",
    "REVEAL",
    "TRACK",
    "PUNCH",
    "PUSH",
    "STATIC",
]


# ============================================================================
# ENUMS
# ============================================================================

class ReferenceType(str, Enum):
    """Reference type for scene generation."""
    PRIMARY = "PRIMARY"           # Scene 1, establishes visual style
    REQUIRES_REF = "REQUIRES_REF" # Needs reference from PRIMARY
    INDEPENDENT = "INDEPENDENT"   # Can be generated independently
    LOOP_CLOSE = "LOOP_CLOSE"     # Last scene, must match Scene 1 for seamless loop


class VideoTool(str, Enum):
    """Video generation tool."""
    KLING = "KLING"
    VEO = "VEO"
    WAN = "WAN"


class ContentCategory(str, Enum):
    """Content pillar categories."""
    LUXURY_LISTINGS = "LUXURY_LISTINGS"
    VEHICLES = "VEHICLES"
    TRANSIT = "TRANSIT"
    LANDMARKS = "LANDMARKS"
    COMMERCIAL = "COMMERCIAL"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    ENTERTAINMENT = "ENTERTAINMENT"


class HookType(str, Enum):
    """Hook types for scroll-stopping (synced with GEN1.txt v8.0.0 HOOK MATRIX)."""
    THE_IMPOSSIBLE = "THE_IMPOSSIBLE"
    THE_ABSURD_LOGIC = "THE_ABSURD_LOGIC"
    THE_SCALE_SHOCK = "THE_SCALE_SHOCK"
    THE_SENSORY_ATTACK = "THE_SENSORY_ATTACK"
    THE_WHISPER = "THE_WHISPER"
    THE_SOUND_FIRST = "THE_SOUND_FIRST"
    THE_TEXTURE_ZOOM = "THE_TEXTURE_ZOOM"


class PsychologicalTrigger(str, Enum):
    """Psychological triggers for hooks (synced with GEN1.txt v8.0.0)."""
    DISBELIEF = "DISBELIEF"
    PATTERN_BREAK = "PATTERN_BREAK"
    AWE = "AWE"
    SENSORY = "SENSORY"
    CONTRAST_HOOK = "CONTRAST_HOOK"
    AUDIO_PRIME = "AUDIO_PRIME"
    CURIOSITY_GAP = "CURIOSITY_GAP"


class ArchitecturalStyle(str, Enum):
    """Architectural style codes."""
    MODERN_MIN = "MODERN_MIN"
    MID_CENTURY = "MID_CENTURY"
    BRUTALIST = "BRUTALIST"
    ORGANIC = "ORGANIC"
    ART_DECO = "ART_DECO"
    MEDITERRANEAN = "MEDITERRANEAN"
    VICTORIAN = "VICTORIAN"
    GOTHIC = "GOTHIC"
    SPANISH_COLONIAL = "SPANISH_COLONIAL"
    CAPE_COD = "CAPE_COD"
    TRAD_JAPANESE = "TRAD_JAPANESE"
    CONTEMPORARY = "CONTEMPORARY"
    COASTAL = "COASTAL"


class LightingPreset(str, Enum):
    """Lighting presets."""
    MORNING_GOLDEN = "MORNING_GOLDEN"
    SUNSET_DRAMATIC = "SUNSET_DRAMATIC"
    BLUE_HOUR = "BLUE_HOUR"
    NIGHT_NEON = "NIGHT_NEON"
    TWILIGHT_PURPLE = "TWILIGHT_PURPLE"
    OVERCAST_SOFT = "OVERCAST_SOFT"
    CANDLELIT_WARM = "CANDLELIT_WARM"
    MOONLIT_SILVER = "MOONLIT_SILVER"
    # Legacy presets kept for backwards compat
    AFTERNOON_WARM = "AFTERNOON_WARM"
    MIDDAY_BRIGHT = "MIDDAY_BRIGHT"


class CameraMovement(str, Enum):
    """Camera movement types."""
    APPROACH = "APPROACH"
    RETREAT = "RETREAT"
    ORBIT = "ORBIT"
    RISE = "RISE"
    DESCEND = "DESCEND"
    RUSH = "RUSH"
    REVEAL = "REVEAL"
    TRACK = "TRACK"
    PUNCH = "PUNCH"
    PUSH = "PUSH"
    STATIC = "STATIC"


class NarrativePurpose(str, Enum):
    """Scene narrative purposes."""
    ESTABLISHING = "ESTABLISHING"
    EXTERIOR_ANGLE = "EXTERIOR_ANGLE"
    AERIAL = "AERIAL"
    INTERIOR = "INTERIOR"
    DETAIL = "DETAIL"
    FEATURE = "FEATURE"
    LOOP_CLOSE = "LOOP_CLOSE"
    STRUCTURAL_DETAIL = "STRUCTURAL_DETAIL"
    THEMATIC_INTERIOR = "THEMATIC_INTERIOR"
    CONTEXTUAL_ENVIRONMENT = "CONTEXTUAL_ENVIRONMENT"
    DYNAMIC_ACTION = "DYNAMIC_ACTION"
    FEATURE_HIGHLIGHT = "FEATURE_HIGHLIGHT"
    AERIAL_WOW = "AERIAL_WOW"
    AERIAL_REVEAL = "AERIAL_REVEAL"


class EnergyLevel(str, Enum):
    """Scene energy levels."""
    EXPLOSIVE = "EXPLOSIVE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SonicHookType(str, Enum):
    """Sonic hook types (synced with GEN1.txt v8.0.0 AUDIO SYSTEM)."""
    THE_BOOM = "THE_BOOM"
    THE_SIZZLE = "THE_SIZZLE"
    THE_WHOOSH = "THE_WHOOSH"
    THE_CHIME = "THE_CHIME"
    THE_DROP = "THE_DROP"
    THE_CRUNCH = "THE_CRUNCH"
    THE_GLITCH = "THE_GLITCH"
    THE_SILENCE = "THE_SILENCE"


# ============================================================================
# GEN1 OUTPUT MODELS - Matching OUTPUT CONTRACT FOR GEN2
# ============================================================================

class Gen1Concept(BaseModel):
    """Concept metadata for the video."""
    model_config = ConfigDict(extra='allow')

    category: str = Field(..., description="LUXURY_LISTINGS | VEHICLES | TRANSIT | etc.")
    subject: str = Field(..., description="Main subject of the video")
    food_material: str = Field(..., description="Primary food material")
    architectural_style: str = Field(..., description="Architectural style code")
    originality_note: str = Field(..., description="What makes this unique")


class Gen1PublishConfig(BaseModel):
    """Publish configuration for multi-channel support."""
    model_config = ConfigDict(extra='allow')

    target_channel: str = Field(default="glaze_city", description="Target YouTube channel ID")


class Gen1Metadata(BaseModel):
    """Project metadata from GEN1."""
    model_config = ConfigDict(extra='allow')

    version: str = Field(default="3.0", description="Schema version")
    status: str = Field(default="PRODUCTION_READY", description="Output status")
    title: str = Field(..., description="Short descriptive title")
    concept: Gen1Concept = Field(..., description="Concept details")
    target_duration_seconds: int = Field(default=10, description="Target duration")
    scene_count: int = Field(..., description="Number of scenes (6-10)")

    @field_validator('scene_count')
    @classmethod
    def validate_scene_count(cls, v: int) -> int:
        """Enforce MIN_SCENES-MAX_SCENES per GEN1/GEN2 contract."""
        if v < MIN_SCENES:
            logger.warning(f"scene_count {v} below minimum, clamping to {MIN_SCENES}")
            return MIN_SCENES
        if v > MAX_SCENES:
            logger.warning(f"scene_count {v} above maximum, clamping to {MAX_SCENES}")
            return MAX_SCENES
        return v


class Gen1Property(BaseModel):
    """Property/subject information."""
    model_config = ConfigDict(extra='allow')

    name: str = Field(..., description="Creative name for the subject")
    location: str = Field(..., description="Location in Glaze City")
    price: Optional[str] = Field(default=None, description="Price for listings or null")
    tagline: str = Field(..., description="Catchy one-liner")


class Gen1Hook(BaseModel):
    """Hook strategy for scroll-stopping."""
    model_config = ConfigDict(extra='allow')

    type: str = Field(..., description="THE_IMPOSSIBLE | THE_ABSURD_LOGIC | etc.")
    psychological_trigger: str = Field(..., description="DISBELIEF | PATTERN_BREAK | etc.")
    first_frame_visual: str = Field(..., description="What viewer sees in first frame")
    first_words: str = Field(..., description="Opening VO with emotion tag")
    complete_hook_vo: str = Field(..., description="Full hook voiceover segment")
    scroll_stop_element: str = Field(..., description="The impossible thing that stops scroll")
    scene_1_entry_type: str = Field(default="MACRO_ENTRY", description="MACRO_ENTRY | SCALE_SHOCK")
    body_trigger: Optional[str] = Field(default=None, description="SKIN | MOUTH | NOSE | EARS | STOMACH")

    @field_validator('type')
    @classmethod
    def validate_hook_type(cls, v: str) -> str:
        """Normalize hook type — deterministic validator catches invalid values."""
        return v.upper().strip()

    @field_validator('psychological_trigger')
    @classmethod
    def validate_psychological_trigger(cls, v: str) -> str:
        """Normalize psychological trigger — accept any value (GEN1 prompt encourages creative values)."""
        return v.upper().strip()


_DEFAULT_STORIES: int = 10


class Gen1ArchitecturalIdentity(BaseModel):
    """Architectural identity for visual consistency - ALL FIELDS REQUIRED."""
    style_code: str = Field(..., description="MODERN_MIN | MID_CENTURY | BRUTALIST | etc. - REQUIRED")
    style_description: str = Field(..., description="2-3 sentence description - REQUIRED")
    stories: int = Field(default=_DEFAULT_STORIES, description="Number of stories - REQUIRED")
    distinctive_features: List[str] = Field(default_factory=list, description="Key features")
    silhouette_description: str = Field(default="", description="One sentence describing shape")
    interior_style: str = Field(default="", description="How interiors should feel")

    @field_validator('distinctive_features', mode='before')
    @classmethod
    def coerce_distinctive_features(cls, v: Any) -> List[str]:
        return _coerce_to_str_list(v)

    @field_validator('stories', mode='before')
    @classmethod
    def coerce_stories(cls, v: Any) -> int:
        """Gemini sometimes returns a string like 'Suspended' or 'Vertical cliff' instead of int."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            digits = re.findall(r'\d+', v)
            if digits:
                return int(digits[0])
        return _DEFAULT_STORIES


class Gen1FoodDNA(BaseModel):
    """Food material mapping to architectural elements."""
    walls_become: str = Field(..., description="What walls are made of")
    roof_becomes: str = Field(..., description="What roof is made of")
    windows_become: str = Field(..., description="What windows are made of")
    floors_become: str = Field(..., description="What floors are made of")
    doors_become: str = Field(..., description="What doors are made of")
    columns_become: str = Field(..., description="What columns are made of")
    furniture_becomes: str = Field(default="", description="What furniture is made of")


class Gen1FoodIdentity(BaseModel):
    """Food identity for the project."""
    primary_food: str = Field(..., description="Primary food material - REQUIRED")
    food_dna: Gen1FoodDNA = Field(..., description="Food-to-architecture mapping - REQUIRED")
    texture_keywords: List[str] = Field(default_factory=list, description="Texture words")
    color_keywords: List[str] = Field(default_factory=list, description="Color words")
    atmosphere: str = Field(default="", description="Overall atmosphere")

    @field_validator('texture_keywords', 'color_keywords', mode='before')
    @classmethod
    def coerce_keywords(cls, v: Any) -> List[str]:
        return _coerce_to_str_list(v)


class Gen1LightingMaster(BaseModel):
    """Lighting configuration for consistency."""
    model_config = ConfigDict(extra='allow')

    preset: str = Field(..., description="MORNING_GOLDEN | SUNSET_DRAMATIC | etc.")
    mood_reason: str = Field(..., description="Why this lighting fits")
    prompt_snippet: str = Field(..., description="Full lighting description for prompts")


class Gen1ForegroundElement(BaseModel):
    """Foreground element for depth."""
    model_config = ConfigDict(extra='allow')

    type: str = Field(..., description="Type of foreground element")
    prompt_snippet: str = Field(..., description="Prompt snippet for foreground")


class Gen1EasterEgg(BaseModel):
    """Easter egg for engagement."""
    format: Optional[str] = Field(default=None, description="VISUAL | AUDIO_ONLY")
    object: Optional[str] = Field(default=None, description="What the easter egg is")
    scene_number: Optional[int] = Field(default=None, description="Which scene contains it")
    placement: Optional[str] = Field(default=None, description="[POSITION], [SIZE]% of frame, [SPATIAL RELATION]")
    comment_bait: str = Field(default="", description="Text to bait comments")
    visibility: str = Field(default="FINDABLE", description="FINDABLE | HIDDEN | OBVIOUS")
    validation_check: str = Field(default="CONFIRMED_VISIBLE", description="Validation status")
    audio_hint: Optional[str] = Field(default=None, description="Audio hint for AUDIO_ONLY format")

    @model_validator(mode='before')
    @classmethod
    def normalize_easter_egg(cls, data: Any) -> Any:
        """Normalize easter egg - AUDIO_ONLY format doesn't require object/scene_number/placement."""
        if isinstance(data, dict):
            fmt = data.get('format', '').upper() if data.get('format') else None
            if fmt == 'AUDIO_ONLY':
                data.setdefault('object', 'audio_easter_egg')
                data.setdefault('scene_number', 1)
                data.setdefault('placement', 'AUDIO_ONLY')
            else:
                # Ensure required fields have defaults for VISUAL format
                data.setdefault('object', '')
                data.setdefault('scene_number', 0)
                data.setdefault('placement', '')
        return data


class Gen1VisualConcept(BaseModel):
    """Visual concept for a scene (from GEN1)."""
    subject: str = Field(..., description="Main subject of the scene - REQUIRED")
    environment: str = Field(default="", description="Environment/setting")
    mood: str = Field(default="", description="Emotional quality")
    key_elements: List[str] = Field(default_factory=list, description="Key visual elements")
    lighting_note: str = Field(default="", description="Specific lighting for this scene")
    motion_elements: List[str] = Field(default_factory=list, description="What should move")

    @field_validator('key_elements', 'motion_elements', mode='before')
    @classmethod
    def coerce_lists(cls, v: Any) -> List[str]:
        return _coerce_to_str_list(v)


class Gen1CameraIntent(BaseModel):
    """Camera intent for a scene."""
    movement: str = Field(..., description="APPROACH | RETREAT | ORBIT | etc.")
    combo: Optional[str] = Field(default=None, description="Movement combination")
    framing: str = Field(default="Wide", description="Wide | Medium | Close | Extreme Close")
    special: Optional[str] = Field(default=None, description="Special technique")

    @field_validator('movement')
    @classmethod
    def validate_movement(cls, v: str) -> str:
        """Normalize camera movement — deterministic validator catches invalid values."""
        return v.upper().strip()


class Gen2VisualParams(BaseModel):
    """Visual parameters from GEN1 v6 for GEN2 scene rendering."""
    subject_scale: Optional[str] = Field(default=None, description="Scale of subject in frame")
    depth_layers: Optional[Any] = Field(default=None, description="Depth layer description (str or list)")
    dominant_color: Optional[str] = Field(default=None, description="Dominant color")
    contrast_color: Optional[str] = Field(default=None, description="Contrast color")
    texture_focus: Optional[str] = Field(default=None, description="Texture focus area")
    light_direction: Optional[str] = Field(default=None, description="Light direction")
    atmosphere_density: Optional[str] = Field(default=None, description="Atmosphere density")


class SceneTrick(BaseModel):
    """Scene trick from GEN1 v6 dynamic scene engine."""
    trick_id: str = Field(..., description="Trick identifier")
    trick_name: str = Field(..., description="Trick name")
    application: str = Field(..., description="How the trick is applied")


class Gen1SceneConcept(BaseModel):
    """Scene concept from GEN1 (story & structure, not visual prompts) - ALL FIELDS REQUIRED."""
    model_config = ConfigDict(extra='allow')

    scene_number: int = Field(..., description="Scene number (1-based) - REQUIRED")
    scene_name: str = Field(..., description="Scene name - REQUIRED")
    duration_seconds: float = Field(..., description="Scene duration - REQUIRED")
    narrative_purpose: str = Field(..., description="ESTABLISHING | EXTERIOR_ANGLE | etc. - REQUIRED")
    reference_hint: str = Field(..., description="PRIMARY | REQUIRES_REF | INDEPENDENT - REQUIRED")
    energy_level: str = Field(..., description="EXPLOSIVE | HIGH | MEDIUM | LOW - REQUIRED")
    visual_concept: Gen1VisualConcept = Field(..., description="Visual concept for GEN2 - REQUIRED")
    camera_intent: Gen1CameraIntent = Field(..., description="Camera movement intent - REQUIRED")
    voiceover_segment: str = Field(default="", description="VO text with [tags] - can be empty for later scenes")
    broker_script: str = Field(default="", description="Broker script - can be empty for later scenes")
    audio_moment: str = Field(default="", description="Key audio event - can be empty")
    gen2_visual_params: Optional[Gen2VisualParams] = Field(default=None, description="Visual params for GEN2")
    scene_tricks: Optional[List[SceneTrick]] = Field(default=None, description="Scene tricks from dynamic engine")
    on_screen_text: str = Field(default="", description="Mute-friendly headline text (3-6 words)")
    # v8.4.0 sensory fields (declared for validation + explicit merge passthrough)
    sensory_pressure: Optional[int] = Field(default=None, ge=1, le=10, description="Sensory pressure 1-10 — drives GEN2 visual tier")
    money_shot: Optional[Dict[str, Any]] = Field(default=None, description="Money shot info {is_money_shot, still_image_description}")
    snap_moment: Optional[Dict[str, Any]] = Field(default=None, description="Snap moment timing envelope for money_shot scenes (v8.4.0)")
    temperature_contrast: Optional[Dict[str, str]] = Field(default=None, description="Color/mood {subject_temp, background_temp, contrast_method}")

    @model_validator(mode='before')
    @classmethod
    def fill_voiceover_from_alternatives(cls, data: Any) -> Any:
        """Fill voiceover_segment from narrator_script or broker_script if missing."""
        if isinstance(data, dict):
            if not data.get('voiceover_segment'):
                # GEN1.txt uses narrator_script (clean text) as primary VO field
                if data.get('narrator_script'):
                    data['voiceover_segment'] = data['narrator_script']
                elif data.get('broker_script'):
                    data['voiceover_segment'] = data['broker_script']
        return data

    @field_validator('narrative_purpose')
    @classmethod
    def validate_narrative_purpose(cls, v: str) -> str:
        """Normalize narrative purpose — deterministic validator catches invalid values."""
        return v.upper().strip()

    @field_validator('reference_hint')
    @classmethod
    def validate_reference_hint(cls, v: str) -> str:
        """Normalize reference hint — deterministic validator catches invalid values."""
        return v.upper().strip()

    @field_validator('energy_level')
    @classmethod
    def validate_energy_level(cls, v: str) -> str:
        """Normalize energy level — deterministic validator catches invalid values."""
        return v.upper().strip()

    @model_validator(mode='after')
    def validate_scene_fields(self) -> 'Gen1SceneConcept':
        """Validate all required scene fields are present and valid."""
        errors = []

        # Check visual_concept.subject - REQUIRED
        if not self.visual_concept.subject:
            errors.append(f"Scene {self.scene_number}: missing visual_concept.subject")

        # Check visual_concept.environment - REQUIRED
        if not self.visual_concept.environment:
            errors.append(f"Scene {self.scene_number}: missing visual_concept.environment")

        # Check visual_concept.motion_elements - REQUIRED
        if not self.visual_concept.motion_elements:
            errors.append(f"Scene {self.scene_number}: missing visual_concept.motion_elements")

        # Check camera_intent.movement - REQUIRED
        if not self.camera_intent.movement:
            errors.append(f"Scene {self.scene_number}: missing camera_intent.movement")

        # Check voiceover_segment - REQUIRED for all scenes except last 2 (AERIAL + LOOP_CLOSE)
        if self.narrative_purpose not in ("AERIAL", "LOOP_CLOSE", "AERIAL_WOW", "AERIAL_REVEAL") and not self.voiceover_segment:
            errors.append(f"Scene {self.scene_number}: missing voiceover_segment")

        # Scene 1 must be PRIMARY
        if self.scene_number == 1 and self.reference_hint != "PRIMARY":
            self.reference_hint = "PRIMARY"

        if errors:
            raise ValueError("; ".join(errors))

        return self


class Gen1VoiceoverConfig(BaseModel):
    """Voiceover configuration from GEN1."""
    full_script: str = Field(..., description="Full voiceover script with markers")
    character: str = Field(default="sensory_witness", description="Voice character")
    voice_id: str = Field(default="fdph4PvCSJPBv95E9UZF", description="ElevenLabs voice ID")
    model: str = Field(default="eleven_v3", description="ElevenLabs model")
    stability: float = Field(default=0.60, ge=0.0, le=1.0)
    similarity_boost: float = Field(default=0.75, ge=0.0, le=1.0)
    style: float = Field(default=0.30, ge=0.0, le=1.0)
    speaker_boost: bool = Field(default=True, description="ElevenLabs speaker boost for voice clarity")


class Gen1SonicHook(BaseModel):
    """Sonic hook configuration."""
    type: str = Field(..., description="THE_BOOM | THE_SIZZLE | etc.")
    timing: str = Field(..., description="When it plays")
    description: str = Field(..., description="Description of the sound")
    volume: str = Field(default="LOUD", description="Volume level: LOUD | MEDIUM | SUBTLE")


class Gen1FoleySound(BaseModel):
    """Single foley sound definition per GEN1_SCHEMA."""
    id: str = Field(..., description="Sound identifier")
    search: str = Field(..., description="Search terms for stock audio")


class Gen1FoleyPalette(BaseModel):
    """Foley sounds configuration - supports both old and new formats per GEN1_SCHEMA."""
    # New format per GEN1_SCHEMA.md
    sounds: List[Gen1FoleySound] = Field(default_factory=list, description="Sound definitions [{id, search}]")
    scene_assignments: Dict[str, List[str]] = Field(default_factory=dict, description="Mapping of scene_N to sound IDs")
    # Legacy format for backwards compatibility
    primary_sounds: List[str] = Field(default_factory=list, description="Legacy: List of sound identifiers")
    search_terms: List[str] = Field(default_factory=list, description="Legacy: Search terms for stock audio")

    @model_validator(mode='before')
    @classmethod
    def normalize_foley_format(cls, data: Any) -> Any:
        """Convert between legacy and new formats."""
        if isinstance(data, dict):
            # Extract scene assignments from numbered keys (legacy Gemini format)
            scene_assignments = data.get('scene_assignments', {})
            for key in list(data.keys()):
                if key.isdigit():
                    scene_assignments[f"scene_{key}"] = data.pop(key)
            if scene_assignments:
                data['scene_assignments'] = scene_assignments

            # Convert primary_sounds + search_terms to sounds format
            # IMPORTANT: Preserve search_terms separately since they may have MORE items than primary_sounds
            if 'primary_sounds' in data and 'sounds' not in data:
                primary = data.get('primary_sounds', [])
                search = data.get('search_terms', primary)  # fallback to primary if no search
                sounds = []
                # Create sound objects for each primary sound
                for i, s in enumerate(primary):
                    search_term = search[i] if i < len(search) else s
                    sounds.append({"id": s.replace(" ", "_"), "search": search_term})
                data['sounds'] = sounds
                # Keep search_terms intact - it may have MORE items than primary_sounds
                # The merge code in prompt_router.py will combine both sources

            # Convert sounds to primary_sounds for legacy code
            if 'sounds' in data and 'primary_sounds' not in data:
                sounds = data.get('sounds', [])
                if sounds and isinstance(sounds[0], dict):
                    data['primary_sounds'] = [s.get('id', '') for s in sounds]
                    data['search_terms'] = [s.get('search', '') for s in sounds]
        return data


class Gen1SfxItem(BaseModel):
    """Single SFX item."""
    type: str = Field(..., description="IMPACT | WHOOSH | STING | etc.")
    timing: str = Field(..., description="When it plays (seconds or 'cut'/'end')")
    description: str = Field(..., description="Description")
    volume: str = Field(default="MEDIUM", description="Volume: LOUD | MEDIUM | SOFT")


class Gen1SfxScene(BaseModel):
    """SFX configuration for a scene - ALL FIELDS REQUIRED."""
    scene: int = Field(..., description="Scene number - REQUIRED")
    sfx: List[Gen1SfxItem] = Field(..., description="SFX items - REQUIRED")


class Gen1AudioConfig(BaseModel):
    """Audio configuration from GEN1 - ALL FIELDS REQUIRED."""
    sonic_hook: Gen1SonicHook = Field(..., description="Sonic hook - REQUIRED")
    suno_prompt: str = Field(..., description="SUNO music generation prompt - REQUIRED")
    foley_palette: Gen1FoleyPalette = Field(..., description="Foley sounds - REQUIRED")
    sfx_per_scene: List[Gen1SfxScene] = Field(..., description="SFX per scene - REQUIRED")


class Gen1ShareTrigger(BaseModel):
    """Share trigger for engagement - ALL FIELDS REQUIRED."""
    text: str = Field(..., description="Share trigger text - REQUIRED")
    placement: str = Field(..., description="Where to place - REQUIRED")


class Gen1YouTube(BaseModel):
    """YouTube metadata nested object (REQUIRED - NEVER NULL) - ALL FIELDS REQUIRED."""
    title: str = Field(..., description="YouTube title (max 60 chars with emoji) - REQUIRED")
    description: str = Field(..., description="YouTube description (min 100 chars) - REQUIRED")
    pinned_comment: Optional[str] = Field(default=None, description="Pinned comment (easter egg mystery)")
    tags: List[str] = Field(default_factory=list, description="YouTube tags")
    title_variants: Optional[List[str]] = Field(default=None, description="Title variants from GEN1 v6")
    description_variants: Optional[List[str]] = Field(default=None, description="Description variants from GEN1 v6")


VALID_METADATA_TRIGGERS = {"SATISFYING", "FORBIDDEN", "TACTILE", "IDENTITY"}


class MetadataVariant(BaseModel):
    """Single metadata variant for A/B rotation (generated by GEN1 v8.2.0)."""
    model_config = ConfigDict(extra='allow')
    trigger: str = Field(..., description="Psychological trigger (SATISFYING, FORBIDDEN, TACTILE, IDENTITY)")
    title: str = Field(..., description="YouTube title for this variant")
    description: str = Field(..., description="YouTube description for this variant")
    pinned_comment: Optional[str] = Field(default=None, description="Pinned comment for this variant")

    @field_validator('trigger')
    @classmethod
    def validate_trigger(cls, v: str) -> str:
        upper = v.upper().strip()
        if upper not in VALID_METADATA_TRIGGERS:
            warnings.warn(
                f"MetadataVariant trigger '{v}' not in {VALID_METADATA_TRIGGERS}, "
                f"accepting as-is but may indicate LLM hallucination"
            )
        return v


class MetadataVariants(BaseModel):
    """Container for all 4 A/B metadata variants."""
    model_config = ConfigDict(extra='allow')
    variant_a: MetadataVariant = Field(..., description="Primary variant (SATISFYING)")
    variant_b: MetadataVariant = Field(..., description="Variant B (FORBIDDEN)")
    variant_c: MetadataVariant = Field(..., description="Variant C (TACTILE)")
    variant_d: MetadataVariant = Field(..., description="Variant D (IDENTITY)")


class Gen1ViralAssessment(BaseModel):
    """Viral assessment scores - supports both v5 (numeric) and v6 (verdict) formats."""
    # v5 numeric scores (optional in v6)
    hook_strength: float = Field(default=0.8, ge=0.0, le=1.0, description="Hook strength score")
    humor_quotient: float = Field(default=0.7, ge=0.0, le=1.0, description="Humor quotient")
    shareability: float = Field(default=0.8, ge=0.0, le=1.0, description="Shareability score")
    comment_potential: float = Field(default=0.8, ge=0.0, le=1.0, description="Comment potential")
    visual_uniqueness: float = Field(default=0.8, ge=0.0, le=1.0, description="Visual uniqueness")
    overall_score: float = Field(default=0.8, ge=0.0, le=1.0, description="Overall viral score")
    weak_points: List[str] = Field(default_factory=list, description="Weak points")
    strength_points: List[str] = Field(default_factory=list, description="Strength points")
    # v6 verdict fields
    hook_verdict: Optional[str] = Field(default=None, description="GEN1 v6 hook verdict")
    retention_verdict: Optional[str] = Field(default=None, description="GEN1 v6 retention verdict")
    share_verdict: Optional[str] = Field(default=None, description="GEN1 v6 share verdict")
    improvement_if_regenerated: Optional[str] = Field(default=None, description="GEN1 v6 improvement note")
    # v8.3.0 verdicts
    mute_test_verdict: Optional[str] = Field(default=None, description="Can the video be understood without sound?")
    categorization_verdict: Optional[str] = Field(default=None, description="Can YouTube NLP classify this into a niche?")
    niche_alignment_verdict: Optional[str] = Field(default=None, description="Does this fit existing large niches?")


class Gen1ReplayHook(BaseModel):
    """Replay hook for engagement (v8.0.0)."""
    model_config = ConfigDict(extra='allow')
    tier: str = Field(default="FEEL_AGAIN", description="FEEL_AGAIN | MISSED_DETAIL | SHARE_MOMENT")
    format: str = Field(default="SENSORY_PEAK", description="SENSORY_PEAK | DENSITY_OVERLOAD | BACKGROUND_ACTION | AUDIO_LAYER | MONEY_SHOT")
    description: str = Field(default="", description="What the replay hook is")
    scene_number: Optional[int] = Field(default=None, description="Which scene contains it")
    rewatch_trigger: Optional[str] = Field(default=None, description="Why viewer replays")
    comment_bait: Optional[str] = Field(default=None, description="Comment bait text")
    validation_check: Optional[str] = Field(default=None, description="QA check")


class Gen1Engagement(BaseModel):
    """Engagement elements — v8.0.0 uses replay_hooks instead of easter_egg."""
    model_config = ConfigDict(extra='allow')
    easter_egg: Optional[Gen1EasterEgg] = Field(default=None, description="Easter egg — OPTIONAL in v8.0.0")
    replay_hooks: List[Gen1ReplayHook] = Field(default_factory=list, description="Replay hooks (v8.0.0)")
    share_trigger: Gen1ShareTrigger = Field(..., description="Share trigger - REQUIRED")
    hashtags: List[str] = Field(default_factory=list, description="3 hashtags")

    @model_validator(mode='before')
    @classmethod
    def normalize_share_trigger(cls, data: Any) -> Any:
        """Normalize share_trigger - support both string and object form."""
        if isinstance(data, dict):
            st = data.get('share_trigger')
            if isinstance(st, str):
                data['share_trigger'] = {'text': st, 'placement': 'end_screen'}
        return data


class Gen1Output(BaseModel):
    """
    Complete GEN1 output matching OUTPUT CONTRACT FOR GEN2.
    Contains story, structure, identities - NOT visual prompts.

    Validates all REQUIRED_GEN1_FIELDS per contract.
    """
    model_config = ConfigDict(extra='allow')

    concept_reasoning: Optional[str] = Field(default=None, description="GEN1 v6 concept reasoning")
    metadata: Gen1Metadata = Field(..., description="Project metadata")
    publish_config: Optional[Gen1PublishConfig] = Field(default=None, description="Publish configuration for multi-channel support")
    property: Gen1Property = Field(..., description="Property/subject info")
    hook: Gen1Hook = Field(..., description="Hook strategy")
    architectural_identity: Gen1ArchitecturalIdentity = Field(..., description="Architectural style")
    food_identity: Gen1FoodIdentity = Field(..., description="Food material identity")
    lighting_master: Gen1LightingMaster = Field(..., description="Lighting configuration")
    atmosphere_mode: str = Field(default="CINEMATIC", description="CINEMATIC | VIBRANT | PLAYFUL")
    foreground_element: Gen1ForegroundElement = Field(..., description="Foreground element")
    scenes: List[Gen1SceneConcept] = Field(default_factory=list, description="Scene concepts")
    voiceover: Gen1VoiceoverConfig = Field(..., description="Voiceover config")
    warning_line: str = Field(default="", description="Memorable warning for AERIAL (N-1) scene, 3-8 words")
    audio: Gen1AudioConfig = Field(..., description="Audio config")
    engagement: Gen1Engagement = Field(..., description="Engagement elements")

    # A/B metadata variants (optional — generated by GEN1 v8.2.0+)
    metadata_variants: Optional[MetadataVariants] = Field(default=None, description="A/B rotation metadata variants")

    # YouTube nested object (REQUIRED - NEVER NULL)
    youtube: Gen1YouTube = Field(..., description="YouTube metadata nested object - REQUIRED")

    # Flat YouTube fields for backwards compatibility (OPTIONAL - synced from nested)
    youtube_title: Optional[str] = Field(default=None, description="YouTube title - synced from youtube.title")
    youtube_description: Optional[str] = Field(default=None, description="YouTube description - synced from youtube.description")
    youtube_pinned_comment: Optional[str] = Field(default=None, description="YouTube pinned comment - synced from youtube.pinned_comment")
    youtube_hashtags: List[str] = Field(default_factory=list, description="YouTube hashtags")
    youtube_tags: List[str] = Field(default_factory=list, description="YouTube tags")

    # Viral assessment (REQUIRED - NEVER NULL)
    viral_assessment: Gen1ViralAssessment = Field(..., description="Viral assessment scores - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def fix_scene_numbers_and_voiceover(cls, data: Any) -> Any:
        """
        Fix scene_number values based on array position and fill missing voiceover.
        This handles LLM errors where scene_number doesn't match array index.
        Also renames GEN1 prompt field names to match Pydantic model field names.
        """
        if isinstance(data, dict):
            # GEN1 prompt outputs "structure" but model expects "property"
            if 'structure' in data and 'property' not in data:
                data['property'] = data.pop('structure')

            # Handle _concept_reasoning field from GEN1 v6 (rename to concept_reasoning)
            if '_concept_reasoning' in data and 'concept_reasoning' not in data:
                data['concept_reasoning'] = data.pop('_concept_reasoning')

            if 'scenes' in data and isinstance(data['scenes'], list):
                for i, scene in enumerate(data['scenes']):
                    if isinstance(scene, dict):
                        expected_number = i + 1
                        actual_number = scene.get('scene_number')

                        # Fix wrong scene_number
                        if actual_number != expected_number:
                            scene['scene_number'] = expected_number

                        # Ensure voiceover_segment exists for non-aerial/non-loop scenes
                        purpose = scene.get('narrative_purpose', '').upper()
                        if purpose not in ('AERIAL', 'LOOP_CLOSE', 'AERIAL_WOW', 'AERIAL_REVEAL'):
                            if not scene.get('voiceover_segment'):
                                if scene.get('narrator_script'):
                                    scene['voiceover_segment'] = scene['narrator_script']
                                elif scene.get('broker_script'):
                                    scene['voiceover_segment'] = scene['broker_script']
                                else:
                                    scene_name = scene.get('scene_name', f'Scene {expected_number}')
                                    scene['voiceover_segment'] = f"[dramatic] {scene_name}."
        return data

    @model_validator(mode='after')
    def validate_gen1_contract(self) -> 'Gen1Output':
        """
        Validate all required GEN1 fields per OUTPUT CONTRACT FOR GEN2.
        """
        errors = []

        # ===== METADATA VALIDATION =====
        if not self.metadata.concept.category:
            errors.append("Missing metadata.concept.category")
        if not self.metadata.concept.subject:
            errors.append("Missing metadata.concept.subject")
        if not self.metadata.concept.food_material:
            errors.append("Missing metadata.concept.food_material")

        # ===== HOOK VALIDATION =====
        if not self.hook.type:
            errors.append("Missing hook.type")
        if not self.hook.psychological_trigger:
            errors.append("Missing hook.psychological_trigger")
        if not self.hook.first_words:
            errors.append("Missing hook.first_words")
        if self.hook.scene_1_entry_type not in ("MACRO_ENTRY", "SCALE_SHOCK"):
            errors.append(f"Invalid hook.scene_1_entry_type: '{self.hook.scene_1_entry_type}' — expected MACRO_ENTRY or SCALE_SHOCK")

        # ===== ARCHITECTURAL IDENTITY VALIDATION =====
        if not self.architectural_identity.style_code:
            errors.append("Missing architectural_identity.style_code")
        if not self.architectural_identity.style_description:
            errors.append("Missing architectural_identity.style_description")
        if not self.architectural_identity.silhouette_description:
            errors.append("Missing architectural_identity.silhouette_description")
        if not self.architectural_identity.distinctive_features:
            errors.append("Missing architectural_identity.distinctive_features")

        # ===== FOOD IDENTITY VALIDATION =====
        if not self.food_identity.primary_food:
            errors.append("Missing food_identity.primary_food")
        if not self.food_identity.food_dna.walls_become:
            errors.append("Missing food_identity.food_dna.walls_become")
        if not self.food_identity.food_dna.roof_becomes:
            errors.append("Missing food_identity.food_dna.roof_becomes")

        # ===== LIGHTING MASTER VALIDATION =====
        if not self.lighting_master.preset:
            errors.append("Missing lighting_master.preset")
        if not self.lighting_master.prompt_snippet:
            errors.append("Missing lighting_master.prompt_snippet")

        # ===== FOREGROUND ELEMENT VALIDATION =====
        if not self.foreground_element.prompt_snippet:
            errors.append("Missing foreground_element.prompt_snippet")

        # ===== SCENES VALIDATION =====
        if len(self.scenes) < 6 or len(self.scenes) > 10:
            errors.append(f"Expected 6-10 scenes, got {len(self.scenes)}")

        # ===== AUDIO VALIDATION =====
        if not self.audio.suno_prompt:
            errors.append("Missing audio.suno_prompt")

        # ===== YOUTUBE VALIDATION (sync flat fields from nested object) =====
        # Sync flat fields from nested object for backwards compatibility
        if self.youtube.title and not self.youtube_title:
            self.youtube_title = self.youtube.title
        if self.youtube.description and not self.youtube_description:
            self.youtube_description = self.youtube.description
        if self.youtube.pinned_comment and not self.youtube_pinned_comment:
            self.youtube_pinned_comment = self.youtube.pinned_comment
        if self.youtube.tags and not self.youtube_tags:
            self.youtube_tags = self.youtube.tags

        # ===== VIRAL ASSESSMENT VALIDATION =====
        # viral_assessment is now REQUIRED - no defaults needed

        # ===== ENGAGEMENT VALIDATION =====
        # easter_egg is optional in v8.0.0 (replaced by replay_hooks)
        egg = self.engagement.easter_egg
        if egg is not None:
            is_audio_only = getattr(egg, 'format', None) == 'AUDIO_ONLY'
            if not is_audio_only:
                if not egg.object:
                    errors.append("Missing engagement.easter_egg.object")
                if egg.scene_number is None or egg.scene_number == 0:
                    errors.append("Missing engagement.easter_egg.scene_number")
                elif egg.scene_number < 2 or egg.scene_number > len(self.scenes) - 1:
                    errors.append(f"easter_egg.scene_number must be 2-{len(self.scenes)-1}, got {egg.scene_number}")
                if not egg.placement:
                    errors.append("Missing engagement.easter_egg.placement")

        # If critical errors, raise
        if errors:
            raise ValueError(f"GEN1 Contract Validation Failed: {'; '.join(errors)}")

        return self

    def get_validation_report(self) -> Tuple[bool, List[str]]:
        """
        Get a detailed validation report without raising exceptions.

        Returns:
            Tuple of (is_valid, list of issues)
        """
        issues = []

        # Check all required fields
        checks = [
            (self.metadata.concept.category, "metadata.concept.category"),
            (self.metadata.concept.subject, "metadata.concept.subject"),
            (self.metadata.concept.food_material, "metadata.concept.food_material"),
            (self.hook.type, "hook.type"),
            (self.hook.psychological_trigger, "hook.psychological_trigger"),
            (self.hook.first_words, "hook.first_words"),
            (self.architectural_identity.style_code, "architectural_identity.style_code"),
            (self.architectural_identity.silhouette_description, "architectural_identity.silhouette_description"),
            (self.architectural_identity.distinctive_features, "architectural_identity.distinctive_features"),
            (self.food_identity.primary_food, "food_identity.primary_food"),
            (self.food_identity.food_dna.walls_become, "food_identity.food_dna.walls_become"),
            (self.food_identity.food_dna.roof_becomes, "food_identity.food_dna.roof_becomes"),
            (self.lighting_master.preset, "lighting_master.preset"),
            (self.lighting_master.prompt_snippet, "lighting_master.prompt_snippet"),
            (self.foreground_element.prompt_snippet, "foreground_element.prompt_snippet"),
            (self.audio.suno_prompt, "audio.suno_prompt"),
        ]

        # Easter egg checks - only for VISUAL format (optional in v8.0.0)
        if self.engagement.easter_egg is not None:
            if getattr(self.engagement.easter_egg, 'format', None) != 'AUDIO_ONLY':
                checks.extend([
                    (self.engagement.easter_egg.object, "engagement.easter_egg.object"),
                    (self.engagement.easter_egg.placement, "engagement.easter_egg.placement"),
                ])

        for value, field_name in checks:
            if not value:
                issues.append(f"Missing: {field_name}")

        # Check scenes
        if len(self.scenes) < 6 or len(self.scenes) > 10:
            issues.append(f"Wrong scene count: {len(self.scenes)} (expected 6-10)")

        # Check each scene
        for scene in self.scenes:
            if not scene.visual_concept.subject:
                issues.append(f"Scene {scene.scene_number}: missing visual_concept.subject")
            if not scene.visual_concept.motion_elements:
                issues.append(f"Scene {scene.scene_number}: missing visual_concept.motion_elements")

        return (len(issues) == 0, issues)


# ============================================================================
# SNAP MOMENT MODEL (v8.4.0 — Brand Signature)
# ============================================================================

class SnapMoment(BaseModel):
    """Snap moment for money_shot scenes — the ASMR SFX timing envelope."""
    enabled: bool = Field(default=True, description="Whether snap moment is active")
    pre_silence_seconds: float = Field(default=0.5, ge=0.0, le=2.0, description="Silence before snap SFX")
    snap_sfx: str = Field(default="", description="Descriptive text of the ASMR sound for GEN3")
    snap_duration_seconds: float = Field(default=0.8, ge=0.1, le=3.0, description="Duration of snap SFX")
    post_silence_seconds: float = Field(default=0.3, ge=0.0, le=2.0, description="Silence after snap SFX")


# ============================================================================
# GEN2 INPUT MODELS
# ============================================================================

class Gen2SceneInput(BaseModel):
    """Input for GEN2 - one scene to generate prompts for."""
    scene_number: int = Field(..., description="Scene number")
    narrative_purpose: str = Field(..., description="ESTABLISHING | EXTERIOR_ANGLE | etc.")
    visual_concept: Gen1VisualConcept = Field(..., description="Visual concept from GEN1")
    camera_intent: Gen1CameraIntent = Field(..., description="Camera intent from GEN1")
    energy_level: str = Field(default="HIGH", description="Energy level")
    voiceover_segment: str = Field(default="", description="VO segment")

    # GEN1 → GEN2 handoff fields (required by GEN2 prompt)
    reference_hint: str = Field(default="INDEPENDENT", description="PRIMARY | REQUIRES_REF | INDEPENDENT | LOOP_CLOSE")
    gen2_visual_params: Optional[Gen2VisualParams] = Field(default=None, description="Visual params for GEN2 (subject_scale, texture_focus, colors, etc.)")
    scene_tricks: Optional[List[SceneTrick]] = Field(default=None, description="Scene tricks from dynamic engine")

    # Sensory/tier fields (GEN2 TIER SYSTEM depends on these)
    sensory_pressure: Optional[int] = Field(default=None, ge=1, le=10, description="Sensory pressure 1-10 — drives GEN2 visual tier assignment")
    money_shot: Optional[Dict[str, Any]] = Field(default=None, description="Money shot info {is_money_shot, still_image_description}")
    snap_moment: Optional[Dict[str, Any]] = Field(default=None, description="Snap moment timing envelope for money_shot scenes (v8.4.0)")
    temperature_contrast: Optional[Dict[str, str]] = Field(default=None, description="Color/mood direction {subject_temp, background_temp, contrast_method}")

    # Easter egg info
    has_easter_egg: bool = Field(default=False, description="Whether this scene has easter egg")
    easter_egg_info: Optional[Gen1EasterEgg] = Field(
        default=None,
        description="Easter egg details if has_easter_egg"
    )


# ============================================================================
# GEN2 OUTPUT MODELS - Matching OUTPUT STRUCTURE
# ============================================================================

class Gen2FirstFrameComposition(BaseModel):
    """First frame composition for Scene 1 - ALL FIELDS REQUIRED."""
    hook_element: str = Field(..., description="THE_IMPOSSIBLE | SCALE_SHOCK | etc. - REQUIRED")
    focal_point: str = Field(..., description="Main attention grabber - REQUIRED")
    foreground: str = Field(..., description="What's blurred/atmospheric in front - REQUIRED")
    background: str = Field(..., description="Supporting environment - REQUIRED")
    color_anchor: str = Field(..., description="Dominant color 40%+ of frame - REQUIRED")
    safe_zone: str = Field(..., description="Subject in upper 60% - REQUIRED")
    motion_visible: str = Field(..., description="What's moving in first frame - REQUIRED")
    scroll_stop: str = Field(..., description="Why viewer stops scrolling - REQUIRED")
    scale_proof: str = Field(default="", description="Scale proof elements — optional")


class Gen2PostProductionNotes(BaseModel):
    """Post-production notes for effects Kling can't do."""
    color_grade: Optional[str] = Field(default=None, description="Color grading notes")
    speed_ramp: Optional[str] = Field(default=None, description="Speed ramp timing")
    focus_effect: Optional[str] = Field(default=None, description="Rack focus notes")
    loop_reference: Optional[str] = Field(default=None, description="Loop matching notes (alias: loop_match)")
    loop_match: Optional[str] = Field(default=None, description="Loop matching notes (preferred)")

    @model_validator(mode='before')
    @classmethod
    def normalize_loop_field(cls, data: Any) -> Any:
        """Normalize loop_match to loop_reference for backwards compatibility."""
        if isinstance(data, dict):
            # If loop_match exists but loop_reference doesn't, copy it
            if data.get('loop_match') and not data.get('loop_reference'):
                data['loop_reference'] = data['loop_match']
            # If loop_reference exists but loop_match doesn't, copy it
            elif data.get('loop_reference') and not data.get('loop_match'):
                data['loop_match'] = data['loop_reference']
        return data


class Gen2Inheritance(BaseModel):
    """Inheritance data for REQUIRES_REF and LOOP_CLOSE scenes."""
    parent_scene: int = Field(default=1, description="Parent scene number")
    inherited_elements: List[str] = Field(default_factory=list, description="Elements inherited from parent")
    modified_elements: List[str] = Field(default_factory=list, description="Elements modified from parent")


class Gen2ScaleTechniques(BaseModel):
    """Scale techniques for exterior scenes."""
    camera_angle: Optional[str] = Field(default=None, description="Camera angle for scale")
    atmospheric_depth: Optional[str] = Field(default=None, description="Atmospheric depth description")
    scale_indicators: Optional[str] = Field(default=None, description="Scale indicator elements")


class Gen2EasterEggIntegration(BaseModel):
    """Easter egg integration details."""
    object: str = Field(default="", description="Easter egg object")
    placement_in_prompt: str = Field(default="", description="Where egg is placed in prompt")
    visibility_check: str = Field(default="", description="Visibility verification")
    integrated_in_image_prompt: bool = Field(default=False, description="Whether integrated in image prompt")


class Gen2SceneOutput(BaseModel):
    """Output from GEN2 - visual prompts for one scene - ALL FIELDS REQUIRED."""
    model_config = ConfigDict(extra='allow')

    scene_number: int = Field(..., description="Scene number - REQUIRED")
    reference_type: str = Field(..., description="PRIMARY | REQUIRES_REF | INDEPENDENT | LOOP_CLOSE - REQUIRED")

    # Tier system fields (GEN2 v6.1.0)
    visual_tier: Optional[str] = Field(default=None, description="TIER_1_MONEY_SHOT | TIER_2_HIGH_APPETITE | TIER_3_BALANCED | TIER_4_ARCHITECTURE")
    motion_intensity: Optional[int] = Field(default=None, ge=1, le=10, description="Motion intensity 1-10")

    # Generated prompts - REQUIRED
    image_prompt: str = Field(..., description="Full prompt for Nano Banana Pro - REQUIRED")
    video_prompt: str = Field(..., description="Animation prompt for Kling i2v - NO duration spec (hardcoded) - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def coerce_none_strings(cls, data: Any) -> Any:
        """Gemini sometimes returns None for required string fields. Coerce to empty string."""
        if isinstance(data, dict):
            for key in ('visual_punctuation', 'image_prompt', 'video_prompt', 'reference_type'):
                if key in data and data[key] is None:
                    data[key] = ""
                    if key in ('image_prompt', 'video_prompt'):
                        warnings.warn(
                            f"GEN2 scene has {key}=None (Gemini generation gap) — coerced to empty string",
                            stacklevel=2,
                        )
            # Coerce motion_elements: None→[], string→list
            me = data.get('motion_elements')
            if me is None:
                data['motion_elements'] = []
            elif isinstance(me, str):
                data['motion_elements'] = [s.strip() for s in me.split(',') if s.strip()]
        return data

    # Motion and dynamics
    motion_elements: List[str] = Field(default_factory=list, description="Motion elements")
    energy_level: Optional[str] = Field(default=None, description="Energy level - from GEN1, optional in GEN2 v4.0")
    visual_punctuation: str = Field(..., description="Visual beat - REQUIRED")

    # Scene 1 only - Required for Scene 1, Optional for others
    first_frame_composition: Optional[Gen2FirstFrameComposition] = Field(
        default=None,
        description="First frame composition (Scene 1 only) - REQUIRED for Scene 1"
    )

    # Post-production - Optional
    post_production_notes: Optional[Gen2PostProductionNotes] = Field(
        default=None,
        description="Post-production notes - OPTIONAL"
    )

    # Inheritance - Optional (for REQUIRES_REF and LOOP_CLOSE scenes)
    inheritance: Optional[Gen2Inheritance] = Field(
        default=None,
        description="Inheritance data for dependent scenes"
    )

    # Scale techniques - Optional (for exterior scenes)
    scale_techniques: Optional[Gen2ScaleTechniques] = Field(
        default=None,
        description="Scale techniques for gigantism"
    )

    # Easter egg integration - Optional (for easter egg scene)
    easter_egg_integration: Optional[Gen2EasterEggIntegration] = Field(
        default=None,
        description="Easter egg integration details"
    )

    @field_validator('video_prompt')
    @classmethod
    def validate_video_prompt_no_duration(cls, v: str) -> str:
        """Remove duration spec from video_prompt - 10s is hardcoded in software."""
        v = v.strip()
        # Remove any duration spec - it's hardcoded in video generation software
        import re
        v = re.sub(r',?\s*\d+s\s*$', '', v)
        v = re.sub(r',?\s*--duration\s*\d+\s*', '', v)
        return v.strip().rstrip(',')

    @model_validator(mode='after')
    def validate_inheritance_for_requires_ref(self) -> 'Gen2SceneOutput':
        """
        Per GEN2_SCHEMA: reference_type REQUIRES_REF with inheritance=null is invalid.
        Auto-create default inheritance if missing.
        """
        if self.reference_type in ("REQUIRES_REF", "LOOP_CLOSE") and self.inheritance is None:
            # Auto-fix: create default inheritance from Scene 1
            self.inheritance = Gen2Inheritance(
                parent_scene=1,
                inherited_elements=["architectural_style", "food_material", "lighting_preset", "color_palette"],
                modified_elements=["camera_angle", "subject_focus"]
            )
        return self


class Gen2LoopVerification(BaseModel):
    """Loop verification data from GEN2 for seamless video looping."""
    scene1_camera_movement: str = Field(default="", description="Camera movement in Scene 1")
    sceneN_camera_movement: str = Field(default="", description="Camera movement in last scene")
    movements_are_different: bool = Field(default=True, description="Whether movements are different")
    sceneN_after_reverse: str = Field(default="", description="Last scene description after reverse")
    scene1_foreground: str = Field(default="", description="Foreground element in Scene 1")
    sceneN_foreground: str = Field(default="", description="Foreground element in last scene")
    foreground_match: bool = Field(default=True, description="Whether foreground elements match")
    scene1_lighting: str = Field(default="", description="Lighting in Scene 1")
    sceneN_lighting: str = Field(default="", description="Lighting in last scene")
    lighting_match: bool = Field(default=True, description="Whether lighting matches")
    same_reference_image: bool = Field(default=True, description="Whether same reference image is used")
    loop_ready: bool = Field(default=True, description="Whether loop is ready")

    @model_validator(mode='before')
    @classmethod
    def migrate_scene6_to_sceneN(cls, data: Any) -> Any:
        """Map old scene6_* field names to sceneN_* for backwards compat."""
        if isinstance(data, dict):
            mapping = {
                'scene6_camera_movement': 'sceneN_camera_movement',
                'scene6_after_reverse': 'sceneN_after_reverse',
                'scene6_foreground': 'sceneN_foreground',
                'scene6_lighting': 'sceneN_lighting',
            }
            for old_key, new_key in mapping.items():
                if old_key in data and new_key not in data:
                    data[new_key] = data.pop(old_key)
        return data


class Gen2VisualSummary(BaseModel):
    """Summary of GEN2 visual generation."""
    total_scenes: int = Field(..., ge=6, le=10, description="Total scenes (6-10) - REQUIRED")
    reference_breakdown: Dict[str, int] = Field(default_factory=dict, description="Count by reference type")
    lighting_continuity: str = Field(default="consistent", description="Lighting consistency note")
    foreground_scenes: List[int] = Field(default_factory=list, description="Scenes with foreground")
    motion_summary: str = Field(default="", description="Motion elements summary")
    energy_pattern: str = Field(default="", description="Energy pattern across scenes")
    loop_verified: bool = Field(default=True, description="Whether loop is verified")
    loop_ready: Optional[bool] = Field(default=None, description="Alias for loop_verified")
    consistency_target: str = Field(default="high", description="Target consistency")
    giga_prompt_ready: Optional[bool] = Field(default=None, description="Whether giga prompt is ready")
    # Additional fields required by merge
    gigantism_protocol: str = Field(default="APPLIED", description="Gigantism protocol status")
    scale_techniques_used: List[str] = Field(default_factory=list, description="Scale techniques used")
    motion_enforcement: str = Field(default="", description="Motion enforcement notes")
    banned_words_checked: bool = Field(default=True, description="Whether banned words were checked")
    loop_verification: Optional[Gen2LoopVerification] = Field(default=None, description="Detailed loop verification")

    @model_validator(mode='before')
    @classmethod
    def normalize_summary(cls, data: Any) -> Any:
        """Normalize visual summary fields from Gemini output."""
        if isinstance(data, dict):
            # motion_summary: Gemini sometimes returns dict instead of string
            ms = data.get('motion_summary')
            if isinstance(ms, dict):
                data['motion_summary'] = str(ms)
            # energy_pattern: same issue
            ep = data.get('energy_pattern')
            if isinstance(ep, dict):
                data['energy_pattern'] = str(ep)
            # Handle loop_ready as alias for loop_verified
            if 'loop_ready' in data and 'loop_verified' not in data:
                data['loop_verified'] = data['loop_ready']
            # Default consistency_target if missing
            if 'consistency_target' not in data:
                data['consistency_target'] = 'high'
            # Default gigantism_protocol if missing
            if 'gigantism_protocol' not in data:
                data['gigantism_protocol'] = 'APPLIED'
            # Default loop_verification if missing - provide full default object
            if 'loop_verification' not in data or data['loop_verification'] is None:
                data['loop_verification'] = {
                    'scene1_camera_movement': '',
                    'sceneN_camera_movement': '',
                    'movements_are_different': False,
                    'sceneN_after_reverse': '',
                    'scene1_foreground': '',
                    'sceneN_foreground': '',
                    'foreground_match': False,
                    'scene1_lighting': '',
                    'sceneN_lighting': '',
                    'lighting_match': False,
                    'same_reference_image': False,
                    'loop_ready': False
                }
        return data


class Gen2GlobalSettings(BaseModel):
    """Global settings from GEN2 for consistent visual generation."""
    gigantism_applied: bool = Field(default=True, description="Whether gigantism protocol is applied")
    negative_prompt: str = Field(
        default="tilt-shift, miniature, diorama, toy, cartoon, anime, illustration, drawing, painting, sketch, yellow color cast, sepia tone",
        description="Global negative prompt with anti-toy and anti-yellow keywords"
    )
    style_reference: str = Field(default="", description="Global style reference")
    quality_preset: str = Field(default="ultra", description="Quality preset")


class Gen2BatchOutput(BaseModel):
    """Batch output from GEN2 - ALL FIELDS REQUIRED."""
    model_config = ConfigDict(extra='allow')

    scenes: List[Gen2SceneOutput] = Field(..., description="Scene outputs - REQUIRED")
    visual_summary: Gen2VisualSummary = Field(..., description="Visual summary - REQUIRED")
    global_settings: Gen2GlobalSettings = Field(default_factory=Gen2GlobalSettings, description="Global settings for visual generation")

    @model_validator(mode='before')
    @classmethod
    def ensure_global_settings(cls, data: Any) -> Any:
        """Ensure global_settings exists with defaults if not provided by Gemini."""
        if isinstance(data, dict):
            if 'global_settings' not in data or data['global_settings'] is None:
                data['global_settings'] = {
                    'gigantism_applied': True,
                    'negative_prompt': 'tilt-shift, miniature, diorama, toy, cartoon, anime, illustration, drawing, painting, sketch, yellow color cast, sepia tone',
                    'style_reference': '',
                    'quality_preset': 'ultra'
                }
        return data

    @model_validator(mode='after')
    def validate_scenes(self) -> 'Gen2BatchOutput':
        """Validate scenes with unique scene_numbers 1-N (6-10 scenes)."""
        num_scenes = len(self.scenes)
        if num_scenes < 6 or num_scenes > 10:
            raise ValueError(f"GEN2 must return 6-10 scenes, got {num_scenes}")

        scene_numbers = [s.scene_number for s in self.scenes]
        if len(scene_numbers) != len(set(scene_numbers)):
            duplicates = [n for n in scene_numbers if scene_numbers.count(n) > 1]
            raise ValueError(f"GEN2 has duplicate scene_numbers: {duplicates}")

        expected = list(range(1, num_scenes + 1))
        if scene_numbers != expected:
            raise ValueError(f"GEN2 scene_numbers must be ordered 1-{num_scenes}, got {scene_numbers}")

        return self


# ============================================================================
# DELIVERY PAYLOAD (GEN1 -> GEN2)
# ============================================================================

class DeliveryPayload(BaseModel):
    """
    Payload delivered from GEN1 to GEN2.
    This is the contract between the two stages.

    Validates all REQUIRED_HANDOFF_FIELDS per contract.
    """
    # Project info
    project_id: str = Field(default="", description="Project ID")
    project_style: str = Field(..., description="Project visual style")
    property_name: str = Field(..., description="Property/subject name")

    # Scenes to process
    scenes: List[Gen2SceneInput] = Field(default_factory=list, description="Scenes for GEN2")

    # Context for consistency
    hook_line: str = Field(default="", description="Opening hook line (legacy — use hook object)")
    hook: Optional[Gen1Hook] = Field(default=None, description="Full hook object for GEN2 (scene_1_entry_type, body_trigger, etc.)")
    atmosphere_mode: str = Field(default="CINEMATIC", description="CINEMATIC | VIBRANT | PLAYFUL — mood context for GEN2")

    # REQUIRED HANDOFF FIELDS - from GEN1 contract
    lighting_master: Gen1LightingMaster = Field(..., description="Lighting config")
    foreground_element: Gen1ForegroundElement = Field(..., description="Foreground element")
    easter_egg: Optional[Gen1EasterEgg] = Field(default=None, description="Easter egg info — optional in v8.0.0")
    architectural_identity: Gen1ArchitecturalIdentity = Field(..., description="Architectural style")
    food_identity: Gen1FoodIdentity = Field(..., description="Food identity")

    @model_validator(mode='after')
    def validate_handoff_contract(self) -> 'DeliveryPayload':
        """
        Validate all required handoff fields for GEN1 -> GEN2 delivery.
        """
        errors = []

        # ===== SCENES VALIDATION =====
        if len(self.scenes) < 6 or len(self.scenes) > 10:
            errors.append(f"Expected 6-10 scenes, got {len(self.scenes)}")

        # ===== ARCHITECTURAL IDENTITY VALIDATION =====
        if not self.architectural_identity.style_code:
            errors.append("Missing architectural_identity.style_code")
        if not self.architectural_identity.style_description:
            errors.append("Missing architectural_identity.style_description")
        if not self.architectural_identity.distinctive_features:
            errors.append("Missing architectural_identity.distinctive_features")

        # ===== FOOD IDENTITY VALIDATION =====
        if not self.food_identity.primary_food:
            errors.append("Missing food_identity.primary_food")
        if not self.food_identity.food_dna.walls_become:
            errors.append("Missing food_identity.food_dna.walls_become")
        if not self.food_identity.food_dna.roof_becomes:
            errors.append("Missing food_identity.food_dna.roof_becomes")

        # ===== LIGHTING MASTER VALIDATION =====
        if not self.lighting_master.preset:
            errors.append("Missing lighting_master.preset")
        if not self.lighting_master.prompt_snippet:
            errors.append("Missing lighting_master.prompt_snippet")

        # ===== FOREGROUND ELEMENT VALIDATION =====
        if not self.foreground_element.prompt_snippet:
            errors.append("Missing foreground_element.prompt_snippet")

        # ===== EASTER EGG VALIDATION (optional in v8.0.0) =====
        if self.easter_egg is not None:
            is_audio_only = getattr(self.easter_egg, 'format', None) == 'AUDIO_ONLY'
            if not is_audio_only:
                if not self.easter_egg.object:
                    errors.append("Missing easter_egg.object")
                if self.easter_egg.scene_number is None or self.easter_egg.scene_number == 0:
                    errors.append("Missing easter_egg.scene_number")
                elif self.easter_egg.scene_number < 2 or self.easter_egg.scene_number > len(self.scenes) - 1:
                    errors.append(f"easter_egg.scene_number must be 2-{len(self.scenes)-1}, got {self.easter_egg.scene_number}")

        # ===== SCENE CONTENT VALIDATION =====
        for scene in self.scenes:
            if not scene.visual_concept.subject:
                errors.append(f"Scene {scene.scene_number}: missing visual_concept.subject")
            if not scene.camera_intent.movement:
                errors.append(f"Scene {scene.scene_number}: missing camera_intent.movement")

        if errors:
            raise ValueError(f"Handoff Contract Validation Failed: {'; '.join(errors)}")

        return self

    def get_handoff_summary(self) -> Dict[str, Any]:
        """Get summary of handoff data for logging."""
        return {
            "project_id": self.project_id,
            "project_style": self.project_style,
            "property_name": self.property_name,
            "scene_count": len(self.scenes),
            "architecture": self.architectural_identity.style_code,
            "food": self.food_identity.primary_food,
            "lighting": self.lighting_master.preset,
            "easter_egg_scene": self.easter_egg.scene_number if self.easter_egg else None,
        }

    @classmethod
    def from_gen1_output(cls, gen1: Gen1Output, project_id: str = "") -> "DeliveryPayload":
        """Create delivery payload from GEN1 output."""
        # Create scene inputs for GEN2
        scene_inputs = []
        # easter_egg is optional in v8.0.0 (replaced by replay_hooks)
        easter_egg_scene = gen1.engagement.easter_egg.scene_number if gen1.engagement.easter_egg else None

        for scene in gen1.scenes:
            has_easter_egg = easter_egg_scene is not None and scene.scene_number == easter_egg_scene

            # Extract sensory fields from Gen1SceneConcept extra fields
            scene_extra = scene.model_extra or {}

            scene_input = Gen2SceneInput(
                scene_number=scene.scene_number,
                narrative_purpose=scene.narrative_purpose,
                visual_concept=scene.visual_concept,
                camera_intent=scene.camera_intent,
                energy_level=scene.energy_level,
                voiceover_segment=scene.voiceover_segment,
                reference_hint=scene.reference_hint,
                gen2_visual_params=scene.gen2_visual_params,
                scene_tricks=scene.scene_tricks,
                sensory_pressure=scene.sensory_pressure or scene_extra.get('sensory_pressure'),
                money_shot=scene.money_shot or scene_extra.get('money_shot'),
                snap_moment=scene.snap_moment or scene_extra.get('snap_moment'),
                temperature_contrast=scene.temperature_contrast or scene_extra.get('temperature_contrast'),
                has_easter_egg=has_easter_egg,
                easter_egg_info=gen1.engagement.easter_egg if has_easter_egg else None,
            )
            scene_inputs.append(scene_input)

        return cls(
            project_id=project_id,
            project_style=gen1.metadata.concept.category,
            property_name=gen1.property.name,
            scenes=scene_inputs,
            hook_line=gen1.hook.first_words,
            hook=gen1.hook,
            atmosphere_mode=gen1.atmosphere_mode,
            lighting_master=gen1.lighting_master,
            foreground_element=gen1.foreground_element,
            easter_egg=gen1.engagement.easter_egg,
            architectural_identity=gen1.architectural_identity,
            food_identity=gen1.food_identity,
        )


# ============================================================================
# GEN3a MODELS - Video Analyst v1.6.0
# All fields REQUIRED per GEN3a v1.6.0 contract
# ============================================================================

class GlitchDetection(BaseModel):
    """Виявлений глітч у відео - ALL FIELDS REQUIRED."""
    id: str = Field(..., description="ID глітчу (S1_G1, S2_G1, etc) - REQUIRED")
    source_start: float = Field(..., description="Початок в source video (seconds) - REQUIRED")
    source_end: float = Field(..., description="Кінець в source video (seconds) - REQUIRED")
    type: str = Field(..., description="Тип глітчу (MORPH_ARTIFACT, FLICKER, FROZEN_FRAME, etc) - REQUIRED")
    severity: str = Field(..., description="Серйозність (LOW/MEDIUM/HIGH) - REQUIRED")
    description: str = Field(..., description="Опис глітчу - REQUIRED")
    recommended_action: str = Field(..., description="CUT/SPEED_THROUGH/EFFECT_MASK - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def normalize_gemini_fields(cls, data: Any) -> Any:
        """Normalize field names from Gemini response (GEN3a.txt format)."""
        if isinstance(data, dict):
            # GEN3a prompt returns timestamp_start/timestamp_end, model expects source_start/source_end
            if 'timestamp_start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('timestamp_start')
            if 'timestamp_end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('timestamp_end')
            # Also handle start/end without prefix
            if 'start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('start')
            if 'end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('end')
            # Set defaults for required fields if missing
            if 'severity' not in data:
                data['severity'] = "MEDIUM"
            if 'description' not in data:
                data['description'] = "Detected glitch"
            if 'recommended_action' not in data:
                data['recommended_action'] = "CUT"
        return data


class ActionPeak(BaseModel):
    """Пік дії у відео - ALL FIELDS REQUIRED."""
    id: str = Field(..., description="ID (S1_AP1, etc) - REQUIRED")
    source_timestamp: float = Field(..., description="Час в source video - REQUIRED")
    type: str = Field(..., description="Тип (MOTION_PEAK, REVEAL, TRANSITION, MOTION_BURST) - REQUIRED")
    intensity: float = Field(..., ge=0.0, le=1.0, description="Інтенсивність 0.0-1.0 - REQUIRED")
    beat_aligned: bool = Field(..., description="Вирівняно з бітом - REQUIRED")
    nearest_beat: float = Field(..., description="Найближчий біт timestamp - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def normalize_gemini_fields(cls, data: Any) -> Any:
        """Normalize field names from Gemini response."""
        if isinstance(data, dict):
            # Gemini returns 'timestamp' instead of 'source_timestamp'
            if 'timestamp' in data and 'source_timestamp' not in data:
                data['source_timestamp'] = data.pop('timestamp')
            # Gemini returns 'on_beat' instead of 'beat_aligned'
            if 'on_beat' in data and 'beat_aligned' not in data:
                data['beat_aligned'] = data.pop('on_beat')
            # Handle beat_alignment nested object
            if 'beat_alignment' in data:
                ba = data['beat_alignment']
                if isinstance(ba, dict):
                    if 'on_beat' in ba and 'beat_aligned' not in data:
                        data['beat_aligned'] = ba['on_beat']
                    if 'nearest_strong_beat' in ba and 'nearest_beat' not in data:
                        data['nearest_beat'] = ba['nearest_strong_beat']
            # Set defaults for required fields if missing
            if 'type' not in data:
                data['type'] = "MOTION_PEAK"
            if 'intensity' not in data:
                data['intensity'] = 0.8
            if 'beat_aligned' not in data:
                data['beat_aligned'] = False
            if 'nearest_beat' not in data:
                data['nearest_beat'] = data.get('source_timestamp', 0.0)
        return data


class DeadSpot(BaseModel):
    """Мертва зона у відео (низька активність) - ALL FIELDS REQUIRED."""
    source_start: float = Field(..., description="Початок - REQUIRED")
    source_end: float = Field(..., description="Кінець - REQUIRED")
    reason: str = Field(..., description="Причина - REQUIRED")
    recommendation: str = Field(..., description="Рекомендація (SPEED_UP, etc) - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def normalize_gemini_fields(cls, data: Any) -> Any:
        """Normalize field names from Gemini response (GEN3a.txt format)."""
        if isinstance(data, dict):
            # GEN3a prompt returns timestamp_start/timestamp_end
            if 'timestamp_start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('timestamp_start')
            if 'timestamp_end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('timestamp_end')
            # Also handle start/end without prefix
            if 'start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('start')
            if 'end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('end')
            # Handle description -> reason
            if 'description' in data and 'reason' not in data:
                data['reason'] = data.pop('description')
            # Handle recommended_speed -> recommendation
            if 'recommended_speed' in data and 'recommendation' not in data:
                data['recommendation'] = f"SPEED_{data['recommended_speed']}x"
            # Set defaults for required fields if missing
            if 'reason' not in data:
                data['reason'] = "Low activity segment"
            if 'recommendation' not in data:
                data['recommendation'] = "SPEED_UP"
        return data


class SpeedSegment(BaseModel):
    """Сегмент швидкості відео - ALL FIELDS REQUIRED."""
    source_start: float = Field(..., description="Початок в source - REQUIRED")
    source_end: float = Field(..., description="Кінець в source - REQUIRED")
    speed: float = Field(..., description="Швидкість (>=1.5x min per contract) - REQUIRED")
    output_duration: float = Field(..., description="Тривалість на виході - REQUIRED")
    reason: str = Field(..., description="Причина - REQUIRED")
    motion_density: str = Field(..., description="Motion density (HIGH/MEDIUM/LOW/STATIC) - REQUIRED")
    technique: str = Field(..., description="Technique (NORMAL/RAMP_IN_OUT/WHIP_RAMP/etc) - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def normalize_gemini_fields(cls, data: Any) -> Any:
        """Normalize field names from Gemini response (GEN3a.txt format)."""
        if isinstance(data, dict):
            # GEN3a prompt returns start/end without prefix
            if 'start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('start')
            if 'end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('end')
            # Ensure speed is never 0 (would cause ZeroDivisionError in renderer)
            if 'speed' in data and (not data['speed'] or data['speed'] <= 0):
                data['speed'] = 1.0
            # Calculate output_duration if not provided
            if 'source_start' in data and 'source_end' in data:
                source_dur = data['source_end'] - data['source_start']
                speed = data.get('speed', 1.0) or 1.0
                if 'output_duration' not in data:
                    data['output_duration'] = source_dur / speed
            # Set defaults for required fields if missing
            if 'speed' not in data:
                data['speed'] = 2.5
            if 'reason' not in data:
                data['reason'] = "compression"
            if 'motion_density' not in data:
                data['motion_density'] = "MEDIUM"
            if 'technique' not in data:
                data['technique'] = "NORMAL"
        return data


class VisualClassification(BaseModel):
    """Класифікація візуального контенту сцени - ALL FIELDS REQUIRED."""
    primary_type: str = Field(..., description="Основний тип (EPIC_WIDE, MACRO_DETAIL, etc) - REQUIRED")
    secondary_type: str = Field(..., description="Вторинний тип - REQUIRED")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Впевненість 0.0-1.0 - REQUIRED")
    reasoning: str = Field(..., description="Обґрунтування - REQUIRED")
    dominant_elements: List[str] = Field(..., description="Домінантні елементи - REQUIRED")
    scale: str = Field(..., description="Масштаб (CLOSE/MEDIUM/WIDE) - REQUIRED")
    camera_motion: str = Field(..., description="Рух камери - REQUIRED")
    effect_palette_recommendation: str = Field(..., description="Рекомендована палітра - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'primary_type' not in data:
                data['primary_type'] = "EPIC_WIDE"
            if 'secondary_type' not in data:
                data['secondary_type'] = "NONE"
            if 'confidence' not in data:
                data['confidence'] = 0.8
            if 'reasoning' not in data:
                data['reasoning'] = "Visual classification"
            if 'dominant_elements' not in data:
                data['dominant_elements'] = ["architecture"]
            if 'scale' not in data:
                data['scale'] = "MEDIUM"
            if 'camera_motion' not in data:
                data['camera_motion'] = "STATIC"
            if 'effect_palette_recommendation' not in data:
                data['effect_palette_recommendation'] = "SUBTLE"
        return data


class EasterEggVerification(BaseModel):
    """Верифікація Easter Egg - ALL FIELDS REQUIRED."""
    found: bool = Field(..., description="Чи знайдено - REQUIRED")
    source_timestamp: float = Field(..., description="Час появи - REQUIRED")
    visibility_score: float = Field(..., ge=0.0, le=1.0, description="Видимість 0.0-1.0 - REQUIRED")
    position_in_frame: str = Field(..., description="Позиція в кадрі (zone) - REQUIRED")
    safe_zone_compliant: bool = Field(..., description="Відповідає Safe Zone - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            # Handle verified -> found
            if 'verified' in data and 'found' not in data:
                data['found'] = data['verified']
            # Handle actual_zone -> position_in_frame
            if 'actual_zone' in data and 'position_in_frame' not in data:
                data['position_in_frame'] = data['actual_zone']
            # Handle visibility_percentage -> visibility_score
            if 'visibility_percentage' in data and 'visibility_score' not in data:
                data['visibility_score'] = data['visibility_percentage'] / 100.0
            # Set defaults
            if 'found' not in data:
                data['found'] = False
            if 'source_timestamp' not in data:
                data['source_timestamp'] = 0.0
            if 'visibility_score' not in data:
                data['visibility_score'] = 0.5
            if 'position_in_frame' not in data:
                data['position_in_frame'] = "bottom-center"
            if 'safe_zone_compliant' not in data:
                data['safe_zone_compliant'] = True
        return data


class VOSegmentAnalysis(BaseModel):
    """Аналіз сегменту voiceover - ALL FIELDS REQUIRED."""
    segment_id: str = Field(..., description="ID сегменту - REQUIRED")
    text: str = Field(..., description="Текст - REQUIRED")
    source_start: float = Field(..., description="Початок - REQUIRED")
    source_end: float = Field(..., description="Кінець - REQUIRED")
    style_tag: str = Field(..., description="Тег стилю (WHISPER/NORMAL/EXCITED/etc) - REQUIRED")
    recommended_subtitle_style: str = Field(..., description="Стиль субтитрів - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            # Handle start/end without prefix
            if 'start' in data and 'source_start' not in data:
                data['source_start'] = data.pop('start')
            if 'end' in data and 'source_end' not in data:
                data['source_end'] = data.pop('end')
            # Set defaults
            if 'style_tag' not in data:
                data['style_tag'] = "NORMAL"
            if 'recommended_subtitle_style' not in data:
                data['recommended_subtitle_style'] = "NORMAL"
        return data


class MusicBeat(BaseModel):
    """Біт музики - ALL FIELDS REQUIRED."""
    timestamp: float = Field(..., description="Час біту - REQUIRED")
    strength: str = Field(..., description="Сила (STRONG/MEDIUM/WEAK) - REQUIRED")
    beat_number: int = Field(..., ge=1, le=4, description="Номер біту в такті 1-4 - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'strength' not in data:
                data['strength'] = "MEDIUM"
            if 'beat_number' not in data:
                data['beat_number'] = 1
        return data


class MusicAnalysis(BaseModel):
    """Аналіз музики - ALL FIELDS REQUIRED."""
    bpm: float = Field(..., description="BPM - REQUIRED")
    time_signature: str = Field(..., description="Time signature (4/4) - REQUIRED")
    strong_beats_for_cuts: List[float] = Field(..., description="Сильні біти для катів - REQUIRED")
    beats: List[MusicBeat] = Field(..., description="Всі біти - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'bpm' not in data:
                data['bpm'] = 120.0
            if 'time_signature' not in data:
                data['time_signature'] = "4/4"
            if 'strong_beats_for_cuts' not in data:
                data['strong_beats_for_cuts'] = []
            if 'beats' not in data:
                data['beats'] = []
        return data


class HookVarietyAnalysis(BaseModel):
    """Аналіз variety хуків - ALL FIELDS REQUIRED."""
    recommended_style: str = Field(..., description="Рекомендований стиль (CLASSIC/IMPACT/GLITCH/etc) - REQUIRED")
    reasoning: str = Field(..., description="Обґрунтування - REQUIRED")
    avoid_styles: List[str] = Field(..., description="Уникати стилів - REQUIRED")
    scene1_energy: str = Field(..., description="Енергія/тип Scene 1 - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'recommended_style' not in data:
                data['recommended_style'] = "CLASSIC"
            if 'reasoning' not in data:
                data['reasoning'] = "Default hook style"
            if 'avoid_styles' not in data:
                data['avoid_styles'] = []
            if 'scene1_energy' not in data:
                data['scene1_energy'] = "HIGH"
        return data


class Gen3aSceneAnalysis(BaseModel):
    """Повний аналіз однієї сцени від GEN3a - ALL FIELDS REQUIRED."""
    scene_number: int = Field(..., ge=1, le=MAX_SCENES, description="Номер сцени 1-N - REQUIRED")
    source_duration: float = Field(..., description="Тривалість source (10s) - REQUIRED")
    output_duration: float = Field(..., description="Тривалість на виході - REQUIRED")
    video_quality: float = Field(..., ge=0.0, le=1.0, description="Якість відео 0.0-1.0 - REQUIRED")
    glitches: List[GlitchDetection] = Field(..., description="Виявлені глітчі - REQUIRED (can be empty)")
    action_peaks: List[ActionPeak] = Field(..., description="Піки дії - REQUIRED (can be empty)")
    dead_spots: List[DeadSpot] = Field(..., description="Мертві зони - REQUIRED (can be empty)")
    speed_map: List[SpeedSegment] = Field(..., description="Карта швидкості - REQUIRED")
    visual_classification: VisualClassification = Field(..., description="Класифікація - REQUIRED")
    easter_egg_verification: EasterEggVerification = Field(..., description="Верифікація Easter Egg - REQUIRED")
    special_flags: List[str] = Field(default_factory=list, description="Special flags: HOOK_SCENE, LOOP_SCENE, EASTER_EGG_SCENE")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'source_duration' not in data:
                data['source_duration'] = 10.0
            if 'video_quality' not in data:
                data['video_quality'] = 0.8
            if 'glitches' not in data:
                data['glitches'] = []
            if 'action_peaks' not in data:
                data['action_peaks'] = []
            if 'dead_spots' not in data:
                data['dead_spots'] = []
            if 'speed_map' not in data:
                data['speed_map'] = []
            if 'visual_classification' not in data:
                data['visual_classification'] = {}
            if 'easter_egg_verification' not in data:
                data['easter_egg_verification'] = {}
        return data


class Gen3bHandoff(BaseModel):
    """Дані для передачі до GEN3b - ALL FIELDS REQUIRED."""
    total_output_duration: float = Field(..., description="Загальна тривалість 18-25s - REQUIRED")
    cumulative_scene_starts: Dict[str, float] = Field(..., description="Початки сцен - REQUIRED")
    loop_compliant: bool = Field(..., description="Scene1 ≈ SceneN (last) duration - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'total_output_duration' not in data:
                data['total_output_duration'] = 25.0
            if 'cumulative_scene_starts' not in data:
                data['cumulative_scene_starts'] = {}
            if 'loop_compliant' not in data:
                data['loop_compliant'] = True
        return data


class Gen3aOutput(BaseModel):
    """Повний вивід GEN3a - Video Analyst v1.6.0 - ALL FIELDS REQUIRED."""
    version: str = Field(..., description="Версія GEN3a - REQUIRED")
    project_id: str = Field(..., description="ID проекту - REQUIRED")
    analysis_timestamp: str = Field(..., description="Час аналізу ISO-8601 - REQUIRED")

    scenes: List[Gen3aSceneAnalysis] = Field(..., description="Аналіз сцен (6-10) - REQUIRED")
    music_analysis: MusicAnalysis = Field(..., description="Аналіз музики - REQUIRED")
    vo_segments: List[VOSegmentAnalysis] = Field(..., description="VO сегменти - REQUIRED")
    hook_variety_analysis: HookVarietyAnalysis = Field(..., description="Аналіз хуків - REQUIRED")
    gen3b_handoff: Gen3bHandoff = Field(..., description="Дані для GEN3b - REQUIRED")

    @model_validator(mode='before')
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        """Set defaults for required fields if missing."""
        if isinstance(data, dict):
            if 'version' not in data:
                data['version'] = "1.6.0"
            if 'project_id' not in data:
                data['project_id'] = ""
            if 'analysis_timestamp' not in data:
                from datetime import datetime
                data['analysis_timestamp'] = datetime.now().isoformat()
            if 'scenes' not in data:
                data['scenes'] = []
            if 'music_analysis' not in data:
                data['music_analysis'] = {}
            if 'vo_segments' not in data:
                data['vo_segments'] = []
            if 'hook_variety_analysis' not in data:
                data['hook_variety_analysis'] = {}
            if 'gen3b_handoff' not in data:
                data['gen3b_handoff'] = {}
        return data

    @model_validator(mode='after')
    def validate_output_contract(self) -> 'Gen3aOutput':
        """Validate GEN3a v1.6.0 output contract."""
        errors = []

        # Must have 6-10 scenes
        if len(self.scenes) < 6 or len(self.scenes) > 10:
            errors.append(f"Must have 6-10 scenes, got {len(self.scenes)}")

        # Total duration must be 18-25 seconds
        total = self.gen3b_handoff.total_output_duration
        if total < 18 or total > 25:
            errors.append(f"Total duration {total}s outside 18-25s target range")

        # Scene 1 and last scene duration should be similar for loop
        if len(self.scenes) >= 6:
            s1_dur = self.scenes[0].output_duration
            sN_dur = self.scenes[-1].output_duration
            if abs(s1_dur - sN_dur) > 0.5:
                errors.append(f"Scene 1 ({s1_dur}s) and Scene {len(self.scenes)} ({sN_dur}s) durations differ by more than 0.5s")

        # Each scene must have speed_map
        for scene in self.scenes:
            if not scene.speed_map:
                errors.append(f"Scene {scene.scene_number} missing speed_map")

        if errors:
            # Log warnings but don't raise - allow processing to continue
            from app.utils.logger import logger
            for error in errors:
                logger.warning(f"GEN3a contract warning: {error}")

        return self


# ============================================================================
# GEN3b MODELS - FFmpeg Manifest Generator v1.3.2
# ============================================================================

# ---------------------------------------------------------------------------
# Music Analysis (from GEN3a)
# ---------------------------------------------------------------------------

# MusicBeat defined above (line ~1473) with set_defaults() validator
# MusicAnalysis defined above (line ~1491) with set_defaults() validator


# ---------------------------------------------------------------------------
# Visual Classification (from GEN3a)
# ---------------------------------------------------------------------------

# VisualClassification defined above (line ~1375) with set_defaults() validator


# ---------------------------------------------------------------------------
# Glitch Detection (from GEN3a)
# ---------------------------------------------------------------------------

class GlitchInfo(BaseModel):
    """Інформація про glitch."""
    id: str = Field(..., description="ID glitch")
    source_start: float = Field(..., description="Початок в source")
    source_end: float = Field(..., description="Кінець в source")
    type: str = Field(default="MORPH_ARTIFACT", description="Тип glitch")
    severity: str = Field(default="LOW", description="Серйозність")
    description: str = Field(default="", description="Опис")
    recommended_action: str = Field(default="MASK", description="Рекомендована дія")


# ---------------------------------------------------------------------------
# Action Peak (from GEN3a)
# ---------------------------------------------------------------------------

# ActionPeak defined above (line ~1261) with normalize_gemini_fields() validator


# ---------------------------------------------------------------------------
# Easter Egg Verification (from GEN3a)
# ---------------------------------------------------------------------------

# EasterEggVerification defined above (line ~1410) with set_defaults() validator


# ---------------------------------------------------------------------------
# Canvas Config (from GEN3b)
# ---------------------------------------------------------------------------

class Resolution(BaseModel):
    """Роздільна здатність."""
    width: int = Field(default=1080, description="Ширина")
    height: int = Field(default=1920, description="Висота")


class CanvasConfig(BaseModel):
    """Конфігурація canvas."""
    source_resolution: Resolution = Field(default_factory=lambda: Resolution(width=1080, height=1920))
    working_resolution: Resolution = Field(default_factory=lambda: Resolution(width=1404, height=2496))
    final_resolution: Resolution = Field(default_factory=lambda: Resolution(width=1080, height=1920))


# ---------------------------------------------------------------------------
# FPS Config (from GEN3b)
# ---------------------------------------------------------------------------

class FpsConfig(BaseModel):
    """Конфігурація FPS."""
    target_fps: int = Field(default=30, description="Цільовий FPS")
    source_fps: str = Field(default="auto_detect", description="FPS джерела")
    conversion_filter: str = Field(default="fps=30", description="FFmpeg filter")


# ---------------------------------------------------------------------------
# Font Config (from GEN3b)
# ---------------------------------------------------------------------------

class FontConfig(BaseModel):
    """Конфігурація шрифту."""
    font_name: str = Field(default="Montserrat-Bold", description="Назва шрифту")
    fontfile: str = Field(default="", description="Шлях до файлу")
    fallback: str = Field(default="DejaVu-Sans-Bold", description="Fallback шрифт")


# ---------------------------------------------------------------------------
# Beat Sync Report (from GEN3b)
# ---------------------------------------------------------------------------

class BeatSyncScore(BaseModel):
    """Оцінка синхронізації з бітами."""
    transitions_on_beat: int = Field(default=0, description="Кількість переходів на біті")
    effects_on_beat: int = Field(default=0, description="Кількість ефектів на біті")
    overall_sync_quality: str = Field(default="GOOD", description="Загальна якість")
    final_score: float = Field(default=0.7, description="Фінальна оцінка 0-1")


class SceneTransitionBeat(BaseModel):
    """Інформація про перехід між сценами."""
    from_scene: int = Field(..., description="З якої сцени")
    to_scene: int = Field(..., description="В яку сцену")
    timestamp: float = Field(..., description="Час переходу")
    nearest_beat: float = Field(..., description="Найближчий біт")
    offset: float = Field(default=0.0, description="Зміщення від біту")
    aligned: bool = Field(default=True, description="Чи вирівняно")


class BeatSyncReport(BaseModel):
    """Звіт синхронізації з бітами."""
    music_bpm: float = Field(default=120.0, description="BPM")
    strong_beats_used: List[float] = Field(default_factory=list, description="Використані сильні біти")
    scene_transitions: List[SceneTransitionBeat] = Field(default_factory=list, description="Переходи")
    sync_score: BeatSyncScore = Field(default_factory=BeatSyncScore)


# ---------------------------------------------------------------------------
# Transition Info (from GEN3b timeline)
# ---------------------------------------------------------------------------

class TransitionBeatInfo(BaseModel):
    """Інформація про біт для переходу."""
    timestamp: float = Field(..., description="Час")
    nearest_beat: float = Field(..., description="Найближчий біт")
    on_beat: bool = Field(default=False, description="Чи на біті")
    offset: float = Field(default=0.0, description="Зміщення")


class TransitionToNext(BaseModel):
    """Перехід до наступної сцени."""
    type: str = Field(default="HARD_CUT", description="Тип переходу")
    beat_info: Optional[TransitionBeatInfo] = Field(default=None, description="Інформація про біт")


# ---------------------------------------------------------------------------
# Visual Type (from GEN3b timeline)
# ---------------------------------------------------------------------------

class SceneVisualType(BaseModel):
    """Візуальний тип сцени з GEN3b."""
    primary: str = Field(default="EPIC_WIDE", description="Основний тип")
    secondary: Optional[str] = Field(default=None, description="Другорядний тип")
    effect_palette: str = Field(default="DRAMATIC", description="Палітра ефектів")
    source: str = Field(default="", description="Джерело класифікації")


# ---------------------------------------------------------------------------
# Easter Egg Protection (from GEN3b)
# ---------------------------------------------------------------------------

class EasterEggProtection(BaseModel):
    """Захист easter egg в сцені."""
    object: str = Field(default="", description="Об'єкт")
    verified: bool = Field(default=False, description="Верифіковано")
    applied_restrictions: Dict[str, str] = Field(default_factory=dict, description="Застосовані обмеження")


# ---------------------------------------------------------------------------
# Loop Processing (from GEN3b)
# ---------------------------------------------------------------------------

class LoopProcessing(BaseModel):
    """Обробка loop для останньої сцени (N)."""
    reverse: bool = Field(default=True, description="Чи реверсувати")
    duration_match: Dict[str, Any] = Field(default_factory=dict, description="Відповідність тривалості")


# ---------------------------------------------------------------------------
# Output Config (from GEN3b)
# ---------------------------------------------------------------------------

class VideoOutputConfig(BaseModel):
    """Конфігурація відео виходу."""
    codec: str = Field(default="libx264", description="Кодек")
    preset: str = Field(default="slow", description="Preset")
    crf: int = Field(default=18, description="CRF якість")
    pix_fmt: str = Field(default="yuv420p", description="Pixel format")


class AudioOutputConfig(BaseModel):
    """Конфігурація аудіо виходу."""
    codec: str = Field(default="aac", description="Кодек")
    bitrate: str = Field(default="192k", description="Бітрейт")


class OutputConfig(BaseModel):
    """Повна конфігурація виходу."""
    filename: str = Field(default="output_final.mp4", description="Ім'я файлу")
    video: VideoOutputConfig = Field(default_factory=VideoOutputConfig)
    audio: AudioOutputConfig = Field(default_factory=AudioOutputConfig)


# ---------------------------------------------------------------------------
# Validation Result (from GEN3b)
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    """Результат валідації від GEN3b."""
    duration: Dict[str, Any] = Field(default_factory=dict)
    scenes: Dict[str, Any] = Field(default_factory=dict)
    loop: Dict[str, Any] = Field(default_factory=dict)
    glitches: Dict[str, Any] = Field(default_factory=dict)
    easter_egg: Dict[str, Any] = Field(default_factory=dict)
    hook: Dict[str, Any] = Field(default_factory=dict)
    content_aware_effects: Dict[str, Any] = Field(default_factory=dict)
    subtitle_styles: Dict[str, Any] = Field(default_factory=dict)
    beat_sync: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Creative Summary (from GEN3b)
# ---------------------------------------------------------------------------

class CreativeSummary(BaseModel):
    """Творчий підсумок від GEN3b."""
    hook_style: str = Field(default="", description="Стиль хуку")
    hook_reasoning: str = Field(default="", description="Причина вибору")
    effects_by_palette: Dict[str, int] = Field(default_factory=dict)
    subtitle_style: str = Field(default="", description="Стиль субтитрів")
    subtitle_word_count: int = Field(default=0, description="Кількість слів")
    beat_sync_quality: str = Field(default="", description="Якість синхронізації")
    variety_score: float = Field(default=0.0, description="Оцінка різноманітності")
    loop_ready: bool = Field(default=True, description="Готовність до loop")


# ---------------------------------------------------------------------------
# Effect Selection Log (from GEN3b)
# ---------------------------------------------------------------------------

class EffectSelectionLog(BaseModel):
    """Лог вибору ефектів для сцени."""
    palette_used: str = Field(default="", description="Використана палітра")
    visual_type: str = Field(default="", description="Візуальний тип")
    effects_applied: int = Field(default=0, description="Кількість ефектів")
    reason: Optional[str] = Field(default=None, description="Причина")
    forbidden_checked: List[str] = Field(default_factory=list, description="Перевірені заборонені")


# ---------------------------------------------------------------------------
# Core Manifest Models
# ---------------------------------------------------------------------------

class ManifestEffect(BaseModel):
    """Ефект для manifest.json."""
    type: str = Field(..., description="Тип ефекту (ZOOM_PUNCH, RGB_SPLIT, etc)")
    output_start: Optional[float] = Field(default=None, description="Початок на timeline (optional for global effects)")
    output_end: Optional[float] = Field(default=None, description="Кінець на timeline (optional for global effects)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Параметри ефекту")
    effect_id: Optional[str] = Field(default=None, description="ID ефекту")
    ffmpeg_filter: Optional[str] = Field(default=None, description="FFmpeg filter string")
    palette_source: Optional[str] = Field(default=None, description="Джерело палітри")
    trigger: Optional[str] = Field(default=None, description="Тригер ефекту")
    is_hook_effect: bool = Field(default=False, description="Чи це хук-ефект")


class ManifestCut(BaseModel):
    """Cut segment для manifest."""
    source_start: float = Field(..., description="Початок в source")
    source_end: float = Field(..., description="Кінець в source")
    reason: str = Field(default="GLITCH", description="Причина")


class ManifestScene(BaseModel):
    """Сцена в manifest.json - розширена версія з GEN3a/GEN3b даними."""
    # Core fields
    scene_number: int = Field(..., description="Номер сцени")
    source_file: str = Field(..., description="Файл джерела")
    timeline_start: float = Field(..., description="Початок на timeline")
    timeline_end: float = Field(..., description="Кінець на timeline")
    speed_segments: List[SpeedSegment] = Field(default_factory=list)
    effects: List[ManifestEffect] = Field(default_factory=list)
    cuts: List[ManifestCut] = Field(default_factory=list)

    # From GEN3a - scene analysis
    source_duration: float = Field(default=10.0, description="Тривалість source відео")
    video_quality: float = Field(default=0.8, description="Якість відео 0-1")
    glitches: List[GlitchInfo] = Field(default_factory=list, description="Знайдені glitches")
    action_peaks: List[ActionPeak] = Field(default_factory=list, description="Action peaks")
    dead_spots: List[DeadSpot] = Field(default_factory=list, description="Dead spots")
    visual_classification: Optional[VisualClassification] = Field(default=None, description="Візуальна класифікація")
    easter_egg_verification: Optional[EasterEggVerification] = Field(default=None, description="Верифікація easter egg")

    # From GEN3b - timeline item
    special_flags: List[str] = Field(default_factory=list, description="Спеціальні флаги (HOOK_SCENE, EASTER_EGG_SCENE, etc)")
    visual_type: Optional[SceneVisualType] = Field(default=None, description="Візуальний тип з GEN3b")
    transition_to_next: Optional[TransitionToNext] = Field(default=None, description="Перехід до наступної сцени")
    effect_selection_log: Optional[EffectSelectionLog] = Field(default=None, description="Лог вибору ефектів")
    easter_egg_protection: Optional[EasterEggProtection] = Field(default=None, description="Захист easter egg")
    loop_processing: Optional[LoopProcessing] = Field(default=None, description="Обробка loop (для останньої сцени N)")


class ManifestSubtitle(BaseModel):
    """Субтитр в manifest."""
    id: str = Field(..., description="ID субтитру")
    text: str = Field(..., description="Текст")
    output_start: float = Field(..., description="Початок")
    output_end: float = Field(..., description="Кінець")
    style: str = Field(default="NORMAL", description="Стиль")
    position: str = Field(default="bottom_center", description="Позиція")
    animation: str = Field(default="fade", description="Анімація")


class ManifestAudioLayer(BaseModel):
    """Аудіо шар в manifest."""
    layer: str = Field(..., description="Назва шару (BED/MUSIC/SFX/FOLEY/VO)")
    file: str = Field(default="", description="Файл")
    volume: float = Field(default=1.0, description="Гучність")
    duck_during_vo: bool = Field(default=False, description="Притишувати під час VO")
    duck_amount: float = Field(default=0.4, description="На скільки притишувати")


class ManifestSFXEvent(BaseModel):
    """SFX подія в manifest."""
    id: str = Field(..., description="ID")
    output_timestamp: float = Field(..., description="Час на timeline")
    effect: str = Field(..., description="Назва ефекту")
    file: str = Field(default="", description="Файл")
    volume: float = Field(default=1.0)


class ManifestAudioLayers(BaseModel):
    """Всі аудіо шари."""
    bed: ManifestAudioLayer = Field(default_factory=lambda: ManifestAudioLayer(layer="BED"))
    music: ManifestAudioLayer = Field(default_factory=lambda: ManifestAudioLayer(layer="MUSIC"))
    vo: ManifestAudioLayer = Field(default_factory=lambda: ManifestAudioLayer(layer="VO"))
    sfx_events: List[ManifestSFXEvent] = Field(default_factory=list)
    foley_events: List[ManifestSFXEvent] = Field(default_factory=list)


class HookSection(BaseModel):
    """Секція хуку в manifest."""
    style: str = Field(..., description="Стиль хуку")
    duration: float = Field(..., description="Тривалість")
    effects: List[ManifestEffect] = Field(default_factory=list)
    sfx: str = Field(default="", description="SFX файл")


class Gen3bManifest(BaseModel):
    """Повний manifest.json від GEN3b v1.3.2 - з 100% даних з GEN3a та GEN3b."""
    version: str = Field(default="1.3.2", description="Версія GEN3b manifest")
    project_id: str = Field(default="", description="ID проекту")
    generated_at: str = Field(default="", description="Час генерації")

    # Timing
    total_duration: float = Field(..., description="Загальна тривалість")
    target_duration: float = Field(default=25.0, description="Цільова тривалість")

    # Hook
    hook: HookSection = Field(default_factory=lambda: HookSection(style="CLASSIC", duration=0.3))

    # Scenes (з розширеними полями)
    scenes: List[ManifestScene] = Field(default_factory=list)

    # Audio
    audio_layers: ManifestAudioLayers = Field(default_factory=ManifestAudioLayers)

    # Subtitles
    subtitles: List[ManifestSubtitle] = Field(default_factory=list)

    # Global effects
    global_effects: List[ManifestEffect] = Field(default_factory=list)

    # Loop info
    loop_point: float = Field(default=0.0, description="Точка loop")
    loop_compliant: bool = Field(default=True)

    # =========================================================================
    # NEW FIELDS FROM GEN3a (v1.3.2)
    # =========================================================================
    music_analysis: Optional[MusicAnalysis] = Field(default=None, description="Музичний аналіз з GEN3a")
    hook_variety_analysis: Optional[Dict[str, Any]] = Field(default=None, description="Аналіз різноманітності хуків")

    # =========================================================================
    # NEW FIELDS FROM GEN3b (v1.3.2)
    # =========================================================================
    canvas: Optional[CanvasConfig] = Field(default=None, description="Конфігурація canvas")
    fps_config: Optional[FpsConfig] = Field(default=None, description="Конфігурація FPS")
    font_config: Optional[FontConfig] = Field(default=None, description="Конфігурація шрифту")
    beat_sync_report: Optional[BeatSyncReport] = Field(default=None, description="Звіт синхронізації з бітами")
    filter_chain: List[str] = Field(default_factory=list, description="Порядок FFmpeg фільтрів")
    output_config: Optional[OutputConfig] = Field(default=None, description="Конфігурація виходу")
    validation: Optional[ValidationResult] = Field(default=None, description="Результат валідації")
    creative_summary: Optional[CreativeSummary] = Field(default=None, description="Творчий підсумок")

    # =========================================================================
    # RAW BACKUPS (v1.3.2) - для 100% відновлення даних
    # =========================================================================
    gen3a_raw: Optional[Dict[str, Any]] = Field(default=None, description="Повний GEN3a output")
    gen3b_raw: Optional[Dict[str, Any]] = Field(default=None, description="Повний GEN3b output")


# ============================================================================
# LEGACY COMPATIBILITY (for existing code)
# ============================================================================

class Gen2BatchInput(BaseModel):
    """Batch input for GEN2 (legacy compatibility)."""
    project_style: str
    property_name: str
    total_scenes: int
    scenes: List[Gen2SceneInput]


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Scene count bounds
    "MIN_SCENES",
    "MAX_SCENES",
    # Contract Constants
    "REQUIRED_GEN1_FIELDS",
    "REQUIRED_SCENE_FIELDS",
    "REQUIRED_HANDOFF_FIELDS",
    "VALID_HOOK_TYPES",
    "VALID_PSYCHOLOGICAL_TRIGGERS",
    "VALID_NARRATIVE_PURPOSES",
    "VALID_REFERENCE_HINTS",
    "VALID_ENERGY_LEVELS",
    "VALID_CAMERA_MOVEMENTS",

    # Enums
    "ReferenceType",
    "VideoTool",
    "ContentCategory",
    "HookType",
    "PsychologicalTrigger",
    "ArchitecturalStyle",
    "LightingPreset",
    "CameraMovement",
    "NarrativePurpose",
    "EnergyLevel",
    "SonicHookType",

    # GEN1 Models
    "Gen1Concept",
    "Gen1Metadata",
    "Gen1Property",
    "Gen1Hook",
    "Gen1ArchitecturalIdentity",
    "Gen1FoodDNA",
    "Gen1FoodIdentity",
    "Gen1LightingMaster",
    "Gen1ForegroundElement",
    "Gen1EasterEgg",
    "Gen1ReplayHook",
    "Gen1VisualConcept",
    "Gen1CameraIntent",
    "Gen1SceneConcept",
    "Gen1VoiceoverConfig",
    "Gen1SonicHook",
    "Gen1FoleySound",
    "Gen1FoleyPalette",
    "Gen1SfxItem",
    "Gen1SfxScene",
    "Gen1AudioConfig",
    "Gen1ShareTrigger",
    "Gen1YouTube",
    "Gen1ViralAssessment",
    "Gen1Engagement",
    "Gen1Output",

    # Snap Moment (v8.4.0)
    "SnapMoment",

    # GEN2 Models
    "Gen2SceneInput",
    "Gen2FirstFrameComposition",
    "Gen2PostProductionNotes",
    "Gen2Inheritance",
    "Gen2ScaleTechniques",
    "Gen2EasterEggIntegration",
    "Gen2SceneOutput",
    "Gen2LoopVerification",
    "Gen2VisualSummary",
    "Gen2GlobalSettings",
    "Gen2BatchOutput",
    "Gen2BatchInput",

    # GEN3a Models - Video Analyst v1.3.1
    "GlitchDetection",
    "ActionPeak",
    "DeadSpot",
    "SpeedSegment",
    "VisualClassification",
    "EasterEggVerification",
    "VOSegmentAnalysis",
    "MusicBeat",
    "MusicAnalysis",
    "HookVarietyAnalysis",
    "Gen3aSceneAnalysis",
    "Gen3bHandoff",
    "Gen3aOutput",

    # GEN3b Models - FFmpeg Manifest v1.3.1
    "ManifestEffect",
    "ManifestCut",
    "ManifestScene",
    "ManifestSubtitle",
    "ManifestAudioLayer",
    "ManifestSFXEvent",
    "ManifestAudioLayers",
    "HookSection",
    "Gen3bManifest",

    # Delivery
    "DeliveryPayload",
]
