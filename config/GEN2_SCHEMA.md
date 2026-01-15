# GEN2 Output Schema v3.0

GEN2 receives concept from GEN1 and generates **visual prompts** (image_prompt, video_prompt) - NOT creative concept.

## CRITICAL: ALL FIELDS ARE REQUIRED

Per OUTPUT CONTRACT, every field must have a value. `null` and empty strings are NOT acceptable.

## Input: DeliveryPayload from GEN1

GEN2 receives these REQUIRED fields from GEN1:

| Field | Required | Description |
|-------|----------|-------------|
| `architectural_identity` | YES | style_code, style_description, distinctive_features |
| `food_identity` | YES | primary_food, food_dna, texture_keywords |
| `lighting_master` | YES | preset, prompt_snippet |
| `foreground_element` | YES | type, prompt_snippet |
| `easter_egg` | YES | object, scene_number, placement |
| `scenes` | YES | Array of 6 Gen2SceneInput objects |

## Expected JSON Output Format

```json
{
  "global_settings": {
    "negative_prompt": "tilt-shift, miniature, diorama, toy, small scale, plastic, fake, 3d render, isometric, text, watermark, cute, tiny, dollhouse, dull, desaturated, muted colors - REQUIRED",
    "gigantism_applied": true
  },

  "scenes": [
    {
      "scene_number": 1,
      "scene_name": "Exterior Establishing - REQUIRED",
      "duration_seconds": 2.0,
      "narrative_purpose": "ESTABLISHING - REQUIRED",
      "reference_hint": "PRIMARY - REQUIRED",
      "energy_level": "HIGH - REQUIRED",

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

      "reference_type": "PRIMARY - REQUIRED",

      "inheritance": null,

      "image_prompt": "Full PROSE prompt with GIGANTISM keywords, NO --ar, NO 8k, NO duration - REQUIRED",

      "video_prompt": "Motion-enforced prompt, 3+ motion elements, NO duration spec, NO 10s - REQUIRED",

      "motion_elements": ["clouds drifting", "light shifting", "surface glistening"],

      "scale_techniques": {
        "camera_angle": "low angle looking up - REQUIRED",
        "atmospheric_depth": "haze and fog applied - REQUIRED",
        "scale_indicators": "tiny railings, human-scale steps - REQUIRED"
      },

      "visual_punctuation": "lens flare bloom - REQUIRED",

      "first_frame_composition": {
        "hook_element": "THE_IMPOSSIBLE | SCALE_SHOCK | etc. - REQUIRED for Scene 1",
        "focal_point": "Main attention grabber - REQUIRED",
        "foreground": "What's blurred in front - REQUIRED",
        "background": "Supporting environment - REQUIRED",
        "color_anchor": "Dominant color 40%+ of frame - REQUIRED",
        "safe_zone": "Subject in upper 60% - REQUIRED",
        "motion_visible": "What's moving in first frame - REQUIRED",
        "scroll_stop": "Why viewer stops scrolling - REQUIRED",
        "scale_proof": "Scale proof elements - REQUIRED"
      },

      "easter_egg_integration": null,

      "post_production_notes": {
        "speed_ramp": "None - OPTIONAL",
        "color_grade": "Match Scene 1 - OPTIONAL",
        "loop_match": "N/A - OPTIONAL"
      }
    }
  ],

  "visual_summary": {
    "total_scenes": 6,
    "gigantism_protocol": "APPLIED - REQUIRED",
    "reference_breakdown": {
      "PRIMARY": 1,
      "REQUIRES_REF": 3,
      "INDEPENDENT": 2
    },
    "scale_techniques_used": ["low_angle", "atmospheric_depth", "scale_indicators"],
    "lighting_continuity": "All scenes match lighting_master - REQUIRED",
    "foreground_scenes": [1, 6],
    "motion_summary": "All scenes have camera movement + 3+ motion elements - REQUIRED",
    "energy_pattern": "HIGH -> MEDIUM -> HIGH -> LOW -> EXPLOSIVE -> HIGH - REQUIRED",
    "motion_enforcement": "All scenes have 3+ motion elements - REQUIRED",
    "loop_verified": true,
    "banned_words_checked": true,
    "consistency_target": "80% - REQUIRED",
    "loop_verification": {
      "scene1_camera_movement": "push forward + rise - REQUIRED",
      "scene6_camera_movement": "rise to aerial - REQUIRED",
      "movements_are_different": true,
      "scene6_after_reverse": "descend from aerial - REQUIRED",
      "scene1_foreground": "blurred element - REQUIRED",
      "scene6_foreground": "blurred element - REQUIRED",
      "foreground_match": true,
      "scene1_lighting": "MORNING_GOLDEN - REQUIRED",
      "scene6_lighting": "MORNING_GOLDEN - REQUIRED",
      "lighting_match": true,
      "same_reference_image": true,
      "loop_ready": true
    }
  }
}
```

## Image Prompt Rules (PROSE FORMAT)

### Order (Always follow):
1. **CAMERA ANGLE + SCALE** - "A low-angle cinematic shot looking up at..."
2. **SCALE KEYWORDS** - "...a TOWERING, imposing..."
3. **FOREGROUND** - "Camera pushes past blurred [element]..."
4. **MAIN SUBJECT** - "...revealing the massive [style] [subject] made of [food]..."
5. **KEY DETAILS** - "...featuring [distinctive_features], [food_dna]..."
6. **SCALE INDICATORS** - "...with tiny railings, human-scale steps..."
7. **ATMOSPHERIC DEPTH** - "...atmospheric haze separating foreground..."
8. **LIGHTING** - "...[lighting_master.prompt_snippet]..."
9. **SAFE ZONE** - "...subject positioned in upper portion of frame..."
10. **STYLE** - "...editorial food photography, hyperrealistic, cinematic"
11. **NEGATIVE** - "--no [negative_prompt]"

### BANNED from Image Prompts:
- `--ar 9:16` (hardcoded in software)
- `8k`, `2K`, `4K` (hardcoded in software)
- `--duration 10` (hardcoded)

### Word Count Targets:
| Scene Type | Target Words |
|------------|--------------|
| PRIMARY | 100-130 words |
| REQUIRES_REF | 60-80 words |
| INDEPENDENT | 70-90 words |
| LOOP_CLOSE | 80-100 words |

## Video Prompt Rules (MOTION ENFORCED)

### Structure (Max 40 words):
```
[Camera movement] [direction/angle], [main subject with scale],
[motion element 1] + [motion element 2] + [motion element 3],
[lighting atmosphere], [visual punctuation]
```

### BANNED Words in Video Prompts:
| BANNED | Replace With |
|--------|--------------|
| "Slowly" | (remove) |
| "Slow" | "Steady", "Smooth" |
| "Gentle" | "Soft", "Fluid" |
| "Subtle" | "Visible", "Clear" |
| "Calm" | "Smooth", "Controlled" |
| "Drifting" | "Pushing", "Tracking" |
| "Floating" | "Rising", "Ascending" |
| "Gliding" | "Tracking", "Pushing" |
| "10s" | (remove - hardcoded) |
| "matching Scene 1" | (remove - AI doesn't know) |

### BANNED Camera Movements:
| BANNED | Replace With |
|--------|--------------|
| DRIFT | PUSH, TRACK, ORBIT |
| FLOAT | CRANE UP/DOWN |
| GLIDE | TRACK, PUSH |
| PAN (alone) | ORBIT + PUSH |

## Reference Type System

### The Golden Rule:
**"Is the PRIMARY SUBJECT visible in this scene?"**
- Scene 1 -> **PRIMARY** (establishes reference)
- YES (any amount visible) -> **REQUIRES_REF**
- NO (interior/detail only) -> **INDEPENDENT**

### Inheritance Object (REQUIRED for REQUIRES_REF):
```json
"inheritance": {
  "parent_scene": 1,
  "inherited_elements": ["architectural_style", "food_material", "lighting_preset", "color_palette"],
  "modified_elements": ["camera_angle", "subject_focus"]
}
```

**Validation:**
- `reference_type: "REQUIRES_REF"` AND `inheritance: null` -> **INSTANT FAIL**

## GIGANTISM Protocol (CRITICAL)

### Rule 1: Camera Angle - WORM'S EYE VIEW
For Scene 1 and Scene 6:
- **ALWAYS:** Look UP at building
- **NEVER:** Look DOWN (bird's eye only for Scene 5)

### Rule 2: Atmospheric Depth
Every exterior prompt MUST include:
- "Atmospheric haze"
- "Distance fog"
- "Depth separation"

### Rule 3: Scale Indicators
| Subject Type | Scale Indicators |
|--------------|------------------|
| BUILDINGS | tiny railings, human-scale steps, miniature balconies |
| VEHICLES | wheel size comparison, tiny door handles |
| LANDMARKS | human figures near base, birds flying past |
| BRIDGES | cars on deck, lampposts |

## Loop Engineering (Scene 6)

### The Loop Mechanism:
```
Scene 1: Frame A + Movement X -> Video 1
Scene 6: Frame A + Movement Y (DIFFERENT!) -> Video 6
         | POST-PRODUCTION: REVERSE Video 6
         Result: Reversed Y movement ends at Frame A = Scene 1 start
         | SEAMLESS LOOP
```

### Scene 6 Movement Rules:
| Element | Scene 1 | Scene 6 (LOOP_CLOSE) |
|---------|---------|----------------------|
| First Frame | Frame A | Frame A (IDENTICAL) |
| Camera Movement | Movement X | Movement Y (DIFFERENT) |
| Foreground | Element Z | Element Z (SAME) |
| Lighting | Preset L | Preset L (IDENTICAL) |

### Loop Verification Required:
```json
"loop_verification": {
  "scene1_camera_movement": "push forward + rise",
  "scene6_camera_movement": "rise to aerial",
  "movements_are_different": true,
  "foreground_match": true,
  "lighting_match": true,
  "loop_ready": true
}
```

## Easter Egg Integration

When GEN1 specifies easter egg scene:

```json
"easter_egg_integration": {
  "object": "tiny marzipan squirrel - REQUIRED",
  "placement_in_prompt": "perched on pool edge, center-right area - REQUIRED",
  "visibility_check": "Findable but not obvious - REQUIRED",
  "integrated_in_image_prompt": true
}
```

### Safe Zones for Easter Egg:
| Zone | Status |
|------|--------|
| top-left | SAFE |
| top-right | SAFE |
| center-left | SAFE (best) |
| center-right | SAFE (best) |
| bottom-center | BANNED (UI covers) |

## Validation Checklist

### GIGANTISM:
- [ ] Scene 1 has "low angle looking up" or "TOWERING"
- [ ] Scene 1 has atmospheric depth (haze, fog)
- [ ] Scene 1 has scale indicators
- [ ] Negative prompt includes anti-miniature keywords

### Image Prompts:
- [ ] Written as PROSE (not keyword soup)
- [ ] NO --ar 9:16
- [ ] NO quality specs (8k)
- [ ] Every prompt includes safe zone mention
- [ ] Word count within targets

### Video Prompts:
- [ ] NO duration spec (10s)
- [ ] NO banned words (slowly, gentle, subtle)
- [ ] Every prompt has camera MOVEMENT
- [ ] 3+ motion elements per scene

### Data Completeness:
- [ ] ALL fields have values (no null)
- [ ] motion_elements array has 3+ items
- [ ] scale_techniques filled for exteriors
- [ ] first_frame_composition filled for Scene 1
- [ ] visual_summary.motion_summary NOT empty
- [ ] visual_summary.energy_pattern NOT empty
- [ ] All inheritance objects present for REQUIRES_REF
- [ ] loop_verification all fields true
