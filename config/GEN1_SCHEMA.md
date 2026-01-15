# GEN1 Output Schema v3.1

GEN1 generates **script, concept, voiceover, audio, architectural identity, food identity** - NOT visual prompts.

## CRITICAL: ALL FIELDS ARE REQUIRED

Per OUTPUT CONTRACT, every field must have a value. `null` and empty strings are NOT acceptable.

## Expected JSON Output Format

```json
{
  "metadata": {
    "version": "3.1",
    "status": "PRODUCTION_READY",
    "title": "Short descriptive title - REQUIRED",
    "concept": {
      "category": "LUXURY_LISTINGS | VEHICLES | TRANSIT | LANDMARKS | COMMERCIAL | INFRASTRUCTURE | ENTERTAINMENT | NEIGHBORHOODS | NATURE | FREESTYLE - REQUIRED",
      "subject": "What is the main subject - REQUIRED",
      "food_material": "Primary food - REQUIRED",
      "architectural_style": "Style code - REQUIRED",
      "originality_note": "What makes this unique - REQUIRED"
    },
    "target_duration_seconds": 10,
    "scene_count": 6
  },

  "property": {
    "name": "Creative name for the subject - REQUIRED",
    "location": "Location in Glaze City - REQUIRED",
    "price": "$X,XXX,XXX - REQUIRED",
    "tagline": "Catchy one-liner - REQUIRED"
  },

  "hook": {
    "type": "THE_IMPOSSIBLE | THE_ABSURD_LOGIC | THE_SCALE_SHOCK | THE_SENSORY_ATTACK - REQUIRED",
    "psychological_trigger": "DISBELIEF | PATTERN_BREAK | AWE | SENSORY - REQUIRED",
    "first_frame_visual": "What viewer sees in first frame - REQUIRED",
    "first_words": "Opening VO with [emotion] tag - REQUIRED",
    "complete_hook_vo": "Full hook voiceover segment - REQUIRED",
    "scroll_stop_element": "The impossible thing that stops scroll - REQUIRED"
  },

  "architectural_identity": {
    "style_code": "MODERN_MIN | MID_CENTURY | BRUTALIST | TRAD_JAPANESE | MEDITERRANEAN | CONTEMPORARY | COASTAL | ORGANIC | ART_DECO | VICTORIAN - REQUIRED",
    "style_description": "2-3 sentence description - REQUIRED",
    "stories": 2,
    "distinctive_features": ["feature1", "feature2", "feature3"],
    "silhouette_description": "One sentence describing overall shape - REQUIRED",
    "interior_style": "How interiors should feel - REQUIRED"
  },

  "food_identity": {
    "primary_food": "food name - REQUIRED",
    "food_dna": {
      "walls_become": "Description - REQUIRED",
      "roof_becomes": "Description - REQUIRED",
      "windows_become": "Description - REQUIRED",
      "floors_become": "Description - REQUIRED",
      "doors_become": "Description - REQUIRED",
      "columns_become": "Description - REQUIRED",
      "furniture_becomes": "Description - REQUIRED"
    },
    "texture_keywords": ["keyword1", "keyword2"],
    "color_keywords": ["color1", "color2"],
    "atmosphere": "Mood description - REQUIRED"
  },

  "lighting_master": {
    "preset": "MORNING_GOLDEN | SUNSET_DRAMATIC | AFTERNOON_WARM | OVERCAST_SOFT | MIDDAY_BRIGHT | BLUE_HOUR | NIGHT_NEON | HARSH_INDUSTRIAL | FOGGY_DIFFUSED | STORMY_DRAMATIC | TWILIGHT_PURPLE | FLUORESCENT_COLD | CANDLELIT_WARM | MOONLIT_SILVER - REQUIRED",
    "mood_reason": "Why this lighting fits - REQUIRED",
    "prompt_snippet": "Full lighting description for prompts (min 10 chars) - REQUIRED"
  },

  "atmosphere_mode": "CINEMATIC | VIBRANT | PLAYFUL - REQUIRED",

  "foreground_element": {
    "type": "Element description - REQUIRED",
    "prompt_snippet": "Full foreground description for prompts (min 10 chars) - REQUIRED"
  },

  "voiceover": {
    "full_script": "Complete script with [tags] - REQUIRED",
    "character": "broker | announcer | guide | narrator - REQUIRED",
    "voice_id": "Adam - REQUIRED",
    "model": "eleven_v3 - REQUIRED",
    "stability": 0.60,
    "similarity_boost": 0.75,
    "style": 0.30
  },

  "audio": {
    "sonic_hook": {
      "type": "THE_BOOM | THE_SIZZLE | THE_WHOOSH | THE_CHIME | THE_DROP - REQUIRED",
      "timing": "0.0s - REQUIRED",
      "description": "Deep bass impact on first frame - REQUIRED",
      "volume": "LOUD | MEDIUM | CRISP | SUBTLE - REQUIRED"
    },
    "suno_prompt": "Mood genre instrumental, XX bpm, instrument, atmosphere, loopable, space for voiceover - REQUIRED",
    "foley_palette": {
      "sounds": [{"id": "sound1", "search": "search terms"}],
      "scene_assignments": {"scene_1": ["sound_id"]}
    },
    "sfx_per_scene": [
      {
        "scene": 1,
        "sfx": [
          {
            "type": "IMPACT - REQUIRED",
            "timing": "0.0s - REQUIRED",
            "description": "Signature open impact - REQUIRED"
          }
        ]
      }
    ]
  },

  "engagement": {
    "easter_egg": {
      "object": "String - REQUIRED",
      "scene_number": "3 (must be 2-5) - REQUIRED",
      "placement": "[POSITION], [SIZE]% of frame, [SPATIAL RELATION] - REQUIRED",
      "visibility": "FINDABLE | HIDDEN | OBVIOUS - REQUIRED",
      "comment_bait": "String - REQUIRED",
      "validation_check": "String for QA - REQUIRED"
    },
    "share_trigger": {
      "text": "String - REQUIRED",
      "placement": "description_end - REQUIRED"
    },
    "hashtags": ["#tag1", "#tag2", "#tag3"]
  },

  "youtube": {
    "title": "Max 60 chars with emoji - NEVER NULL - REQUIRED",
    "description": "Min 100 chars with keywords - NEVER NULL - REQUIRED",
    "pinned_comment": "Easter egg mystery only - NEVER NULL - REQUIRED",
    "tags": ["tag1", "tag2", "tag3", "tag4"]
  },

  "youtube_title": "SAME AS youtube.title - NEVER NULL - REQUIRED",
  "youtube_description": "SAME AS youtube.description - NEVER NULL - REQUIRED",
  "youtube_pinned_comment": "SAME AS youtube.pinned_comment - NEVER NULL - REQUIRED",
  "youtube_hashtags": ["#tag1", "#tag2", "#tag3"],
  "youtube_tags": ["tag1", "tag2", "tag3", "tag4"],

  "viral_assessment": {
    "hook_strength": "0.0-1.0 - REQUIRED",
    "humor_quotient": "0.0-1.0 - REQUIRED",
    "shareability": "0.0-1.0 - REQUIRED",
    "comment_potential": "0.0-1.0 - REQUIRED",
    "visual_uniqueness": "0.0-1.0 - REQUIRED",
    "overall_score": "0.0-1.0 - REQUIRED",
    "weak_points": ["potential weak point"],
    "strength_points": ["strength 1", "strength 2"]
  },

  "scenes": [
    {
      "scene_number": 1,
      "scene_name": "Exterior Establishing - REQUIRED",
      "duration_seconds": 2.0,
      "narrative_purpose": "ESTABLISHING | EXTERIOR_ANGLE | AERIAL | INTERIOR | DETAIL | FEATURE | LOOP_CLOSE - REQUIRED",
      "reference_hint": "PRIMARY | REQUIRES_REF | INDEPENDENT - REQUIRED",
      "energy_level": "EXPLOSIVE | HIGH | MEDIUM | LOW - REQUIRED",

      "visual_concept": {
        "subject": "What is shown - REQUIRED",
        "environment": "Where it is - REQUIRED",
        "mood": "Emotional quality - REQUIRED",
        "key_elements": ["element1", "element2"],
        "lighting_note": "Scene-specific lighting - REQUIRED",
        "motion_elements": ["motion1", "motion2", "motion3"]
      },

      "camera_intent": {
        "movement": "APPROACH | ORBIT | RISE | RETREAT | DESCEND | RUSH | REVEAL | TRACK | PUNCH - REQUIRED",
        "combo": "APPROACH + RISE (optional)",
        "framing": "Wide | Medium | Close - REQUIRED",
        "special": "Through foreground, etc."
      },

      "broker_script": "Punchy one-liner for this scene - REQUIRED",
      "voiceover_segment": "VO text with [tags] for this scene - REQUIRED",
      "audio_moment": "Key audio event - REQUIRED"
    }
  ]
}
```

## Key Fields for GEN2 Handoff (DeliveryPayload)

GEN2 REQUIRES these fields from GEN1:

| Field | Description | Required |
|-------|-------------|----------|
| `architectural_identity` | Full object with style_code, distinctive_features | YES |
| `food_identity` | Full object with primary_food, food_dna | YES |
| `lighting_master` | Full object with preset, prompt_snippet | YES |
| `foreground_element` | Full object with type, prompt_snippet | YES |
| `easter_egg` | From engagement.easter_egg | YES |
| `scenes` | Array of 6 Gen2SceneInput objects | YES |

## Scene Requirements

| Scene | narrative_purpose | reference_hint | energy_level |
|-------|------------------|----------------|--------------|
| 1 | ESTABLISHING | PRIMARY (always) | HIGH or EXPLOSIVE |
| 2 | INTERIOR/DETAIL | INDEPENDENT | MEDIUM or HIGH |
| 3 | FEATURE | INDEPENDENT/REQUIRES_REF | HIGH |
| 4 | INTERIOR/DETAIL | INDEPENDENT | LOW or MEDIUM |
| 5 | AERIAL | REQUIRES_REF | EXPLOSIVE |
| 6 | LOOP_CLOSE | REQUIRES_REF | HIGH |

## Reference Type Logic

- Scene 1 -> `PRIMARY` (always - establishes visual style)
- Contains "exterior/aerial/wide" -> `REQUIRES_REF` (needs Scene 1 reference)
- Contains "detail/interior/close-up" -> `INDEPENDENT` (can generate standalone)
- Scene 6 -> `REQUIRES_REF` (must match Scene 1 for loop)

## Hook Types

| Type | Psychology | Use Case |
|------|-----------|----------|
| THE_IMPOSSIBLE | DISBELIEF | Show impossible thing as fact |
| THE_ABSURD_LOGIC | PATTERN_BREAK | Apply real logic to impossible |
| THE_SCALE_SHOCK | AWE | Tiny human vs massive structure |
| THE_SENSORY_ATTACK | SENSORY | Trigger taste/texture memory |

## Camera Movements

| Movement | Energy | Description |
|----------|--------|-------------|
| APPROACH | HIGH | Moving toward subject |
| RETREAT | HIGH | Moving away from subject |
| ORBIT | MEDIUM-HIGH | Circling around subject |
| RISE | HIGH | Ascending, drone-like |
| DESCEND | HIGH | Coming down toward subject |
| RUSH | EXPLOSIVE | Fast aggressive movement |
| REVEAL | HIGH | Movement that reveals hidden element |
| TRACK | MEDIUM-HIGH | Following alongside subject |
| PUNCH | EXPLOSIVE | Sudden emphasis movement |

**BANNED:** DRIFT, FLOAT, GLIDE - too slow for Shorts.

## Validation Checklist

Before output, verify ALL fields are filled:

- [ ] metadata.concept.category - NOT NULL
- [ ] property.name - NOT NULL
- [ ] hook.type - NOT NULL
- [ ] architectural_identity.style_code - NOT NULL
- [ ] food_identity.primary_food - NOT NULL
- [ ] food_identity.food_dna.walls_become - NOT NULL
- [ ] food_identity.food_dna.roof_becomes - NOT NULL
- [ ] lighting_master.preset - NOT NULL
- [ ] lighting_master.prompt_snippet - NOT NULL
- [ ] foreground_element.prompt_snippet - NOT NULL
- [ ] audio.suno_prompt - NOT NULL
- [ ] engagement.easter_egg.object - NOT NULL
- [ ] engagement.easter_egg.scene_number - 2-5
- [ ] youtube.title - NEVER NULL
- [ ] youtube.description - NEVER NULL
- [ ] youtube_title - NEVER NULL (same as youtube.title)
- [ ] youtube_description - NEVER NULL (same as youtube.description)
- [ ] viral_assessment - all scores filled
- [ ] scenes - exactly 6 scenes
- [ ] Each scene has visual_concept.subject - NOT NULL
- [ ] Each scene has visual_concept.motion_elements - NOT EMPTY
- [ ] Each scene has voiceover_segment - NOT NULL
