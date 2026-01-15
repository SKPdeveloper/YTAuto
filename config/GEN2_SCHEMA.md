# GEN2 Output Schema

GEN2 receives concept from GEN1 and generates **visual prompts** for image and video generation.

## Input: Delivery Payload from GEN1

```json
{
  "project_id": "proj_123",
  "project_style": "cinematic food fantasy",
  "property_name": "Crystal Honey Falls Estate",
  "hook_line": "What if honey could freeze into glass?",
  "color_palette": "Amber, gold, warm browns",
  "key_visual_elements": ["flowing honey", "crystal formations", "light beams"],

  "scenes": [
    {
      "scene_number": 1,
      "is_primary": true,
      "narrative_purpose": "Opening hook - establish mystery",
      "visual_concept": {
        "subject": "Massive crystallized honey waterfall",
        "environment": "Enchanted forest clearing at golden hour",
        "lighting": "Warm amber glow with light refraction",
        "mood": "Magical, awe-inspiring",
        "key_elements": ["flowing honey", "crystal formations", "light beams"]
      },
      "camera_intent": {
        "movement": "Slow upward tilt",
        "framing": "Wide establishing shot"
      }
    }
  ]
}
```

## Expected JSON Output Format

```json
{
  "scenes": [
    {
      "scene_number": 1,

      "image_prompt": "Massive crystallized honey waterfall in enchanted forest clearing, golden hour lighting with warm amber glow, intricate crystal formations with flowing honey textures, light beams refracting through translucent honey crystals, photorealistic, 8k, cinematic food fantasy style, hyper-detailed macro textures, volumetric lighting, magical atmosphere",

      "video_prompt": "Slow upward camera tilt revealing full waterfall height, honey droplets slowly falling and catching light, subtle crystal shimmer effect, gentle steam rising, ambient forest movement in background, smooth cinematic motion",

      "reference_type": "PRIMARY",
      "video_tool": "KLING",

      "prompt_notes": "Established as PRIMARY reference for visual consistency"
    },
    {
      "scene_number": 2,

      "image_prompt": "Close-up of crystallized honey texture...",

      "video_prompt": "Camera slowly pushing in on crystal details...",

      "reference_type": "REQUIRES_REF",
      "video_tool": "KLING",

      "prompt_notes": "Uses Scene 1 reference for color/style consistency"
    }
  ],

  "generation_notes": "All prompts maintain amber/gold color palette and cinematic food fantasy style for consistency"
}
```

## Image Prompt Structure

Include in order:
1. **Subject** - Main focus of the scene
2. **Environment** - Setting and surroundings
3. **Lighting** - Light quality and direction
4. **Key elements** - Important visual details
5. **Technical** - "photorealistic, 8k, cinematic food fantasy style"
6. **Textures** - "hyper-detailed macro textures"
7. **Atmosphere** - "volumetric lighting, magical atmosphere"

## Video Prompt Structure

Include:
1. **Camera movement** - From camera_intent
2. **Subject animation** - What moves in the scene
3. **Effects** - Shimmer, particles, steam, etc.
4. **Background motion** - Ambient movement
5. **Quality** - "smooth cinematic motion"

## Reference Type Rules

| Condition | Reference Type |
|-----------|----------------|
| Scene 1 | `PRIMARY` |
| narrative_purpose contains "exterior/establishing/wide/aerial" | `REQUIRES_REF` |
| narrative_purpose contains "detail/interior/close-up/macro" | `INDEPENDENT` |
| Default | `REQUIRES_REF` |

## Video Tool Selection

| Condition | Tool |
|-----------|------|
| Default | `KLING` |
| Complex camera movements | `VEO` |
| Artistic/stylized | `WAN` |
