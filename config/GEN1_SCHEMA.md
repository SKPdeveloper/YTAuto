# GEN1 Output Schema

GEN1 generates **script, concept, voiceover, and audio** - NOT visual prompts.

## Expected JSON Output Format

```json
{
  "metadata": {
    "title": "The Crystal Honey Waterfall",
    "property_name": "Crystal Honey Falls Estate",
    "hook_type": "MYSTERY",
    "hook_line": "What if honey could freeze into glass?",
    "style": "cinematic food fantasy",
    "target_duration_seconds": 45,
    "target_audience": "YouTube Shorts viewers"
  },

  "scenes": [
    {
      "scene_number": 1,
      "scene_name": "The Discovery",
      "duration_seconds": 5.0,
      "narrative_purpose": "Opening hook - establish mystery",

      "visual_concept": {
        "subject": "Massive crystallized honey waterfall",
        "environment": "Enchanted forest clearing at golden hour",
        "lighting": "Warm amber glow with light refraction",
        "mood": "Magical, awe-inspiring",
        "key_elements": ["flowing honey", "crystal formations", "light beams"],
        "color_palette": "Amber, gold, warm browns"
      },

      "camera_intent": {
        "movement": "Slow upward tilt",
        "framing": "Wide establishing shot",
        "speed": "slow",
        "notes": "Reveal full height dramatically"
      },

      "voiceover": "In a hidden corner of the world... [0.5s] something impossible exists.",
      "on_screen_text": null,
      "audio_sfx": "Flowing liquid, crystal chimes"
    }
  ],

  "voiceover": {
    "voice_id": "Adam",
    "full_script": "In a hidden corner of the world... [0.5s] something impossible exists. [0.3s] A waterfall... made entirely of crystallized honey.",
    "voice_style": "Warm, storytelling tone with wonder",
    "pacing": "Measured, with dramatic pauses",
    "stability": 0.50,
    "similarity_boost": 0.75
  },

  "audio": {
    "background_music_genre": "Ethereal orchestral",
    "background_music_mood": "Magical wonder",
    "background_music_bpm": 80,
    "sfx_notes": ["flowing liquid", "crystal chimes", "soft wind"]
  },

  "psychology_triggers": ["CURIOSITY", "WONDER", "EXCLUSIVITY"],
  "easter_egg_description": "Small golden bee hidden in crystal",
  "easter_egg_scene": 3,
  "loop_connection": "Last shot of honey drop connects to opening shot",

  "youtube_title": "This Waterfall is Made of HONEY",
  "youtube_description": "Discover the world's only crystallized honey waterfall...",
  "youtube_hashtags": ["#honey", "#nature", "#impossible"],
  "youtube_tags": ["honey waterfall", "crystal honey", "nature wonder"]
}
```

## Key Fields for GEN2

GEN2 needs these fields from each scene:
- `visual_concept` (subject, environment, lighting, mood, key_elements)
- `camera_intent` (movement, framing, speed)
- `narrative_purpose` (determines reference_type)

## Reference Type Logic

GEN2 will determine `reference_type` based on `narrative_purpose`:
- Scene 1 → `PRIMARY` (always)
- Contains "exterior/establishing/wide" → `REQUIRES_REF`
- Contains "detail/interior/close-up" → `INDEPENDENT`
