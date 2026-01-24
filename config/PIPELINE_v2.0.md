# GLAZE CITY PIPELINE v2.2
## GEN3a/GEN3b Architecture with AudioStage

---

## 📋 ЗМІНИ v2.1 → v2.2

| Зміна | Опис |
|-------|------|
| **AudioStage** | Новий стейдж для генерації аудіо ДО GEN3a |
| **Pipeline Order** | Script → Image → Validation → Video → **Audio** → GEN3a → GEN3b → PostProcess |
| **Voiceover перед аналізом** | voiceover.mp3 генерується до GEN3a для beat sync |
| **Music перед аналізом** | music.mp3 генерується до GEN3a для beat sync |
| **PostProcessStage** | Тепер тільки FFmpeg рендеринг, Topaz, thumbnail |
| **Optional audio fallback** | GEN3a працює без аудіо з fallback JSON |

## 📋 ЗМІНИ v2.0 → v2.1

| Зміна | Опис |
|-------|------|
| **Step 0: Music Generation** | Replicate API генерує музику з suno_prompt |
| **Step 1: Beat Analysis** | librosa аналізує біти (не Gemini) |
| **SFX завжди генеруються** | ElevenLabs, не з файлів, prompt обов'язковий |
| **channel_context.json** | Автоматично створюється при першому запуску |
| **Step 8: Update Context** | Записує hook style для variety tracking |

---

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ВХІДНІ ДАНІ                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 {channel_dir}/                      ← Директорія каналу                 │
│  ├── channel_context.json               ← AUTO-CREATED при першому запуску  │
│  └── projects/                                                              │
│      └── {project_id}/                  ← Директорія проекту                │
│          ├── videos/                                                        │
│          │   ├── 1.mp4, 2.mp4, 3.mp4, 4.mp4, 5.mp4, 6.mp4                  │
│          ├── gen1_brief.json                                                │
│          │   └── contains: audio.suno_prompt, voiceover.full_script        │
│          └── gen2_brief.json                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 0: MUSIC GENERATION                                      preprocessor │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: preprocessor.py → generate_music()                                   │
│  API: Replicate (facebook/musicgen-large)                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 0.1 READ SUNO PROMPT                                                │   │
│  │                                                                      │   │
│  │ gen1_brief.json:                                                    │   │
│  │ {                                                                   │   │
│  │   "audio": {                                                        │   │
│  │     "suno_prompt": "Upbeat Japanese city pop, 120 bpm, koto and    │   │
│  │                     synth, energetic transit vibes, loopable,      │   │
│  │                     instrumental, space for voiceover"              │   │
│  │   }                                                                 │   │
│  │ }                                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 0.2 GENERATE VIA REPLICATE                                          │   │
│  │                                                                      │   │
│  │ import replicate                                                    │   │
│  │                                                                      │   │
│  │ output = replicate.run(                                             │   │
│  │     "facebook/musicgen:large",                                      │   │
│  │     input={                                                         │   │
│  │         "prompt": suno_prompt,                                      │   │
│  │         "duration": 30,          # секунд (з запасом)              │   │
│  │         "temperature": 1.0,                                         │   │
│  │         "top_k": 250,                                               │   │
│  │         "top_p": 0.0,                                               │   │
│  │         "classifier_free_guidance": 3.0                             │   │
│  │     }                                                               │   │
│  │ )                                                                   │   │
│  │ # output = URL to generated audio                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 0.3 DOWNLOAD & CONVERT                                              │   │
│  │                                                                      │   │
│  │ • Download audio from Replicate URL                                 │   │
│  │ • Convert to MP3 if needed (ffmpeg -i input.wav output.mp3)         │   │
│  │ • Save to: music/background.mp3                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: music/background.mp3                                               │
│  Duration: ~60-90s                                                          │
│  Cost: ~$0.05                                                               │
│                                                                             │
│  ⚠️  SKIP якщо music/background.mp3 вже існує                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: BEAT ANALYSIS                                         preprocessor │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: preprocessor.py → analyze_beats()                                    │
│  Library: librosa (local, no API)                                           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ALGORITHM:                                                          │   │
│  │                                                                      │   │
│  │ import librosa                                                      │   │
│  │                                                                      │   │
│  │ y, sr = librosa.load("music/background.mp3")                        │   │
│  │ tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)            │   │
│  │ beat_times = librosa.frames_to_time(beat_frames, sr=sr)             │   │
│  │                                                                      │   │
│  │ # Strong beats = every 4th (downbeat in 4/4)                        │   │
│  │ strong_beats = beat_times[::4].tolist()                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: music/beat_analysis.json                                           │
│  Duration: ~3-5s                                                            │
│                                                                             │
│  {                                                                          │
│    "source": "librosa_v0.10",                                               │
│    "file": "background.mp3",                                                │
│    "duration": 30.0,                                                        │
│    "bpm": 120,                                                              │
│    "time_signature": "4/4",                                                 │
│    "beats": [                                                               │
│      {"timestamp": 0.0, "strength": "STRONG", "beat_in_measure": 1},       │
│      {"timestamp": 0.5, "strength": "WEAK", "beat_in_measure": 2},         │
│      {"timestamp": 1.0, "strength": "MEDIUM", "beat_in_measure": 3},       │
│      {"timestamp": 1.5, "strength": "WEAK", "beat_in_measure": 4},         │
│      {"timestamp": 2.0, "strength": "STRONG", "beat_in_measure": 1},       │
│      ...                                                                    │
│    ],                                                                       │
│    "strong_beats_only": [0.0, 2.0, 4.0, 6.0, 8.0, ...],                    │
│    "sections": [                                                            │
│      {"name": "INTRO", "start": 0.0, "end": 4.0, "energy": "LOW"},         │
│      {"name": "MAIN", "start": 4.0, "end": 24.0, "energy": "HIGH"},        │
│      {"name": "OUTRO", "start": 24.0, "end": 30.0, "energy": "FALLING"}    │
│    ]                                                                        │
│  }                                                                          │
│                                                                             │
│  ⚠️  SKIP якщо music/beat_analysis.json вже існує                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 2: GENERATE VOICEOVER                                    orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → generate_voiceover()                               │
│  API: ElevenLabs TTS                                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ INPUT: gen1_brief.json                                              │   │
│  │                                                                      │   │
│  │ {                                                                   │   │
│  │   "voiceover": {                                                    │   │
│  │     "full_script": "[whispers] The commute is raw. [0.3s] ...",    │   │
│  │     "voice_id": "pNInz6obpgDQGcFmaJgB",                            │   │
│  │     "model": "eleven_multilingual_v2",                              │   │
│  │     "stability": 0.5,                                               │   │
│  │     "similarity_boost": 0.75                                        │   │
│  │   }                                                                 │   │
│  │ }                                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PROCESS:                                                            │   │
│  │                                                                      │   │
│  │ 1. Parse script, extract emotion tags: [whispers], [excited], etc. │   │
│  │ 2. Convert pause markers: [0.3s] → SSML <break time="0.3s"/>        │   │
│  │ 3. Call ElevenLabs API                                              │   │
│  │ 4. Save audio to vo/voiceover.mp3                                   │   │
│  │ 5. Save parsed tags to vo/emotion_tags.json (for GEN3a)             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: vo/voiceover.mp3, vo/emotion_tags.json                             │
│  Duration: ~10s                                                             │
│                                                                             │
│  ⚠️  SKIP якщо vo/voiceover.mp3 вже існує                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 3: UPLOAD FILES TO GEMINI                                orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → upload_files_to_gemini()                           │
│  API: Google Gemini Files API                                               │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ FILES TO UPLOAD:                                                    │   │
│  │                                                                      │   │
│  │ ├── videos/1.mp4    ──┐                                             │   │
│  │ ├── videos/2.mp4      │                                             │   │
│  │ ├── videos/3.mp4      ├── 6 video files                             │   │
│  │ ├── videos/4.mp4      │                                             │   │
│  │ ├── videos/5.mp4      │                                             │   │
│  │ ├── videos/6.mp4    ──┘                                             │   │
│  │ └── vo/voiceover.mp3  ── 1 audio file                               │   │
│  │                                                                      │   │
│  │ ⚠️  music/background.mp3 НЕ upload-ється                           │   │
│  │     (GEN3a отримує beat_analysis.json як текст)                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PROCESS:                                                            │   │
│  │                                                                      │   │
│  │ for file in files_to_upload:                                        │   │
│  │     uploaded = client.files.upload(file)                            │   │
│  │     wait_for_active(uploaded)  # polling until ACTIVE               │   │
│  │     file_refs[file.name] = uploaded                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: Dict[filename, GeminiFileRef]                                      │
│  Duration: ~30s (5s per file)                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4: GEN3a ANALYSIS                                        orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → run_gen3a_analysis()                               │
│  Prompt: config/GEN3a_v1.3.md                                               │
│  Model: Gemini 2.5 Pro                                                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ INPUTS TO GEN3a:                                                    │   │
│  │                                                                      │   │
│  │ Files (Gemini refs):                                                │   │
│  │ • uploaded_videos[1-6]                                              │   │
│  │ • uploaded_voiceover                                                │   │
│  │                                                                      │   │
│  │ Text (inline JSON):                                                 │   │
│  │ • gen1_brief.json                                                   │   │
│  │ • gen2_brief.json                                                   │   │
│  │ • beat_analysis.json      ← від librosa, НЕ генерувати!            │   │
│  │ • channel_context.json    ← якщо існує (hook history)              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ GEN3a RESPONSIBILITIES:                                             │   │
│  │                                                                      │   │
│  │ ✓ Frame-by-frame video analysis (Gemini Vision)                    │   │
│  │ ✓ Glitch detection: MORPH, FLICKER, FROZEN, POP, HAND_DEFORM       │   │
│  │ ✓ Action peaks: timestamp, intensity (0.0-1.0), type                │   │
│  │ ✓ Dead spots: timestamp, duration, VO status                       │   │
│  │ ✓ Visual type classification: MACRO_DETAIL, EPIC_WIDE, AERIAL,     │   │
│  │   INTERIOR, ACTION, REVEAL, PORTRAIT, TRANSITION                    │   │
│  │ ✓ Easter egg verification + zone protection                        │   │
│  │ ✓ Speed map: full 0.0-10.0 coverage, no gaps, VO max 1.5x          │   │
│  │ ✓ VO timing analysis (from uploaded audio)                         │   │
│  │ ✓ Subtitle style detection: [whispers]→WHISPER, [excited]→EXCITED  │   │
│  │ ✓ Hook style recommendation (respecting channel_context.avoid_next)│   │
│  │ ✓ Scene 1 = Scene 6 duration matching for loop                     │   │
│  │ ✓ COPY beat data from beat_analysis.json (NOT generate!)           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ GEN3a DOES NOT:                                                     │   │
│  │                                                                      │   │
│  │ ✗ Generate beat timestamps (uses precomputed from librosa)         │   │
│  │ ✗ Make creative effect decisions (GEN3b's job)                     │   │
│  │ ✗ Calculate final output timestamps (GEN3b's job)                  │   │
│  │ ✗ Generate FFmpeg commands (GEN3b's job)                           │   │
│  │ ✗ Recommend hook style in avoid_next list                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: gen3a_analysis.json                                                │
│  Duration: ~60-90s                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  📄 GEN3a_ANALYSIS.JSON STRUCTURE                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  {                                                                          │
│    "metadata": {                                                            │
│      "version": "1.3",                                                      │
│      "analyzer": "GEN3a",                                                   │
│      "generated_at": "2025-01-12T...",                                      │
│      "music_beat_source": "precomputed_librosa",                            │
│      "channel_context_received": true                                       │
│    },                                                                       │
│                                                                             │
│    "music_analysis": {                                                      │
│      "source": "precomputed_librosa",   ← COPIED, not generated            │
│      "bpm": 120,                                                            │
│      "strong_beats_only": [0.0, 2.0, 4.0, ...]                             │
│    },                                                                       │
│                                                                             │
│    "voiceover_analysis": {                                                  │
│      "total_duration": 14.2,                                                │
│      "segments": [                                                          │
│        {"id": "VO1", "text": "The commute is raw.", "start": 0.0, ...}     │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "subtitle_style_analysis": {                                             │
│      "segments": [                                                          │
│        {"vo_id": "VO1", "detected_tag": "[whispers]", "style": "WHISPER"}  │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "hook_variety_analysis": {                                               │
│      "scene_1_visual_type": "EPIC_WIDE",                                    │
│      "recommended_hook_style": "DRAMATIC",                                  │
│      "alternatives": ["CLASSIC", "IMPACT"],                                 │
│      "channel_context_received": true,                                      │
│      "avoided_styles": ["ELEGANT"],          ← from channel_context        │
│      "variety_reasoning": "ELEGANT used last 2 videos, avoiding"           │
│    },                                                                       │
│                                                                             │
│    "easter_egg_analysis": {                                                 │
│      "scene_number": 4,                                                     │
│      "object": "Tiny shrimp tempura luggage",                               │
│      "verified": true,                                                      │
│      "actual_zone": "bottom-center",                                        │
│      "zoom_forbidden": true,                                                │
│      "subtitle_safe_zones": ["top-left", "top-center", "top-right"]        │
│    },                                                                       │
│                                                                             │
│    "scene_analysis": [                                                      │
│      {                                                                      │
│        "scene_number": 1,                                                   │
│        "source_file": "1.mp4",                                              │
│        "source_duration": 10.0,                                             │
│        "visual_classification": {                                           │
│          "primary_type": "EPIC_WIDE",                                       │
│          "secondary_type": "REVEAL",                                        │
│          "effect_palette_recommendation": "DRAMATIC"                        │
│        },                                                                   │
│        "glitches": [...],                                                   │
│        "action_peaks": [...],                                               │
│        "dead_spots": [...],                                                 │
│        "speed_map": [                                                       │
│          {"start": 0.0, "end": 0.5, "speed": 1.0, "reason": "establish"},  │
│          {"start": 0.5, "end": 3.0, "speed": 1.2, "reason": "vo_active"},  │
│          {"start": 3.0, "end": 9.5, "speed": 4.0, "reason": "compress"},   │
│          {"start": 9.5, "end": 10.0, "speed": 1.0, "reason": "end"}        │
│        ],                                                                   │
│        "output_duration": 3.47                                              │
│      },                                                                     │
│      ... (scenes 2-6)                                                       │
│    ],                                                                       │
│                                                                             │
│    "global_analysis": {                                                     │
│      "total_output_duration": 21.35,                                        │
│      "scene_1_duration": 3.47,                                              │
│      "scene_6_duration": 3.47,                                              │
│      "loop_ready": true                                                     │
│    },                                                                       │
│                                                                             │
│    "gen3b_handoff": {                                                       │
│      "ready": true,                                                         │
│      "cumulative_scene_starts": {                                           │
│        "scene_1": 0.0,                                                      │
│        "scene_2": 3.47,                                                     │
│        "scene_3": 6.47,                                                     │
│        "scene_4": 9.97,                                                     │
│        "scene_5": 12.97,                                                    │
│        "scene_6": 17.88                                                     │
│      },                                                                     │
│      "effect_palettes_by_scene": {                                          │
│        "scene_1": "DRAMATIC",                                               │
│        "scene_2": "WARM",                                                   │
│        ...                                                                  │
│      },                                                                     │
│      "subtitle_styles_by_segment": {                                        │
│        "VO1": "WHISPER",                                                    │
│        "VO2": "NORMAL",                                                     │
│        ...                                                                  │
│      },                                                                     │
│      "strong_beats_for_cuts": [0.0, 2.0, 4.0, 6.0, ...],                   │
│      "recommended_hook_style": "DRAMATIC"                                   │
│    }                                                                        │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 4.1: VALIDATE GEN3a                                      orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: validators/val_gen3a.py                                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ LAYER 1: PYTHON VALIDATION (instant, no API)                        │   │
│  │                                                                      │   │
│  │ Structure checks:                                                   │   │
│  │ ☐ JSON is valid (parseable)                                        │   │
│  │ ☐ metadata.version = "1.3"                                          │   │
│  │ ☐ All 6 scenes in scene_analysis[]                                  │   │
│  │ ☐ music_analysis.source = "precomputed_librosa"                    │   │
│  │                                                                      │   │
│  │ Speed map checks:                                                   │   │
│  │ ☐ Each speed_map starts at 0.0                                      │   │
│  │ ☐ Each speed_map ends at 10.0 (or source_duration)                  │   │
│  │ ☐ No gaps between segments                                          │   │
│  │ ☐ VO segments have speed ≤ 1.5                                      │   │
│  │                                                                      │   │
│  │ Loop checks:                                                        │   │
│  │ ☐ scene_1.output_duration ≈ scene_6.output_duration (±0.1s)        │   │
│  │                                                                      │   │
│  │ Easter egg checks:                                                  │   │
│  │ ☐ easter_egg_analysis present                                       │   │
│  │ ☐ zoom_forbidden = true                                             │   │
│  │ ☐ subtitle_safe_zones defined                                       │   │
│  │                                                                      │   │
│  │ Handoff checks:                                                     │   │
│  │ ☐ gen3b_handoff.ready = true                                        │   │
│  │ ☐ cumulative_scene_starts has all 6 scenes                          │   │
│  │ ☐ effect_palettes_by_scene has all 6 scenes                         │   │
│  │ ☐ strong_beats_for_cuts is array                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (only if Layer 1 passed)                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ LAYER 2: LLM VALIDATION (Gemini Flash, ~5s)                         │   │
│  │                                                                      │   │
│  │ Logical checks:                                                     │   │
│  │ ☐ Visual types make sense for scene descriptions                   │   │
│  │ ☐ Glitch severities match recommended actions                      │   │
│  │ ☐ Hook recommendation fits scene_1 visual_type                     │   │
│  │ ☐ Avoided styles actually in channel_context.avoid_next            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: { "status": "PASS/FAIL", "errors": [], "warnings": [] }           │
│                                                                             │
│  ⟳ RETRY: якщо FAIL → re-run GEN3a з errors як feedback (max 3)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 5: GEN3b CREATIVE EDITING                                orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → run_gen3b_editing()                                │
│  Prompt: config/GEN3b_v1.3.md                                               │
│  Model: Gemini 2.5 Pro                                                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ INPUTS TO GEN3b:                                                    │   │
│  │                                                                      │   │
│  │ Text (inline JSON):                                                 │   │
│  │ • gen1_brief.json        ← story context                            │   │
│  │ • gen2_brief.json        ← visual intentions                        │   │
│  │ • gen3a_analysis.json    ← validated analysis                       │   │
│  │                                                                      │   │
│  │ ⚠️  NO video files — GEN3b trusts GEN3a completely                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ GEN3b RESPONSIBILITIES:                                             │   │
│  │                                                                      │   │
│  │ ✓ Select hook style (from gen3a recommendation or alternatives)    │   │
│  │ ✓ Choose effects from content-aware palettes                       │   │
│  │ ✓ Transform SOURCE → OUTPUT timestamps                              │   │
│  │ ✓ Apply subtitle styles per segment                                │   │
│  │ ✓ Align cuts to strong beats where possible                        │   │
│  │ ✓ Calculate beat_sync_score                                        │   │
│  │ ✓ Configure Scene 6 reverse = true                                 │   │
│  │ ✓ Generate FFmpeg filter strings                                   │   │
│  │ ✓ Define SFX with prompts (see below)                              │   │
│  │ ✓ Build complete manifest.json                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ⚠️  SFX DEFINITION — CRITICAL                                       │   │
│  │                                                                      │   │
│  │ ALL SFX are generated by ElevenLabs. GEN3b MUST provide:           │   │
│  │                                                                      │   │
│  │ "audio": {                                                          │   │
│  │   "sfx": [                                                          │   │
│  │     {                                                               │   │
│  │       "id": "SFX_HOOK",                        ← REQUIRED           │   │
│  │       "prompt": "Epic cinematic impact hit,    ← REQUIRED           │   │
│  │                  deep bass, reverb tail",                           │   │
│  │       "timestamp": 0.0,                        ← REQUIRED           │   │
│  │       "duration_seconds": 2.0,                 ← REQUIRED           │   │
│  │       "volume_db": -6                          ← REQUIRED           │   │
│  │     },                                                              │   │
│  │     {                                                               │   │
│  │       "id": "SFX_TRAIN",                                            │   │
│  │       "prompt": "High speed train whoosh, doppler, wind rush",     │   │
│  │       "timestamp": 7.12,                                            │   │
│  │       "duration_seconds": 1.5,                                      │   │
│  │       "volume_db": -9                                               │   │
│  │     },                                                              │   │
│  │     {                                                               │   │
│  │       "id": "SFX_RICE",                                             │   │
│  │       "prompt": "Sticky rice texture, wet organic peeling sound",  │   │
│  │       "timestamp": 10.5,                                            │   │
│  │       "duration_seconds": 1.0,                                      │   │
│  │       "volume_db": -12                                              │   │
│  │     }                                                               │   │
│  │   ]                                                                 │   │
│  │ }                                                                   │   │
│  │                                                                      │   │
│  │ Naming convention:                                                  │   │
│  │ • SFX_HOOK — hook impact sound                                     │   │
│  │ • SFX_TRANS_{N} — transition whoosh                                │   │
│  │ • SFX_ACTION_{N} — action emphasis                                 │   │
│  │ • SFX_TEXTURE_{N} — texture/ambient                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: manifest.json                                                      │
│  Duration: ~30-45s                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 5.1: VALIDATE GEN3b                                      orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: validators/val_gen3b.py                                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ LAYER 1: PYTHON VALIDATION (instant)                                │   │
│  │                                                                      │   │
│  │ Structure:                                                          │   │
│  │ ☐ JSON is valid                                                     │   │
│  │ ☐ metadata.version = "1.3"                                          │   │
│  │ ☐ All 6 scenes in timeline[]                                        │   │
│  │                                                                      │   │
│  │ Timeline:                                                           │   │
│  │ ☐ No gaps between scenes (continuous timeline)                     │   │
│  │ ☐ Scene 6 has reverse = true                                       │   │
│  │ ☐ Scene 6 duration ≈ Scene 1 duration                              │   │
│  │                                                                      │   │
│  │ Hook:                                                               │   │
│  │ ☐ hook_sequence.style_selected is valid style                      │   │
│  │ ☐ style is one of: CLASSIC, IMPACT, GLITCH, ELEGANT, DRAMATIC      │   │
│  │                                                                      │   │
│  │ SFX (CRITICAL):                                                     │   │
│  │ ☐ audio.sfx is array                                                │   │
│  │ ☐ Each SFX has: id, prompt, timestamp, duration_seconds, volume_db │   │
│  │ ☐ All prompts are non-empty strings                                │   │
│  │                                                                      │   │
│  │ Easter egg:                                                         │   │
│  │ ☐ Easter egg scene has no ZOOM effects                             │   │
│  │ ☐ Easter egg scene subtitles use safe zone                         │   │
│  │                                                                      │   │
│  │ FFmpeg:                                                             │   │
│  │ ☐ filter_chain.order is valid array                                │   │
│  │ ☐ Basic syntax check on ffmpeg_filter strings                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼ (only if Layer 1 passed)                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ LAYER 2: LLM VALIDATION (Gemini Flash)                              │   │
│  │                                                                      │   │
│  │ ☐ Effects match scene palettes (no forbidden effects)              │   │
│  │ ☐ Timestamp transformations look mathematically correct            │   │
│  │ ☐ Beat sync attempted reasonably                                   │   │
│  │ ☐ SFX prompts are descriptive and appropriate                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: { "status": "PASS/FAIL", "errors": [], "warnings": [] }           │
│                                                                             │
│  ⟳ RETRY: якщо FAIL → re-run GEN3b з errors як feedback (max 3)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  📄 MANIFEST.JSON STRUCTURE                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  {                                                                          │
│    "metadata": {                                                            │
│      "version": "1.3",                                                      │
│      "generator": "GEN3b",                                                  │
│      "gen3a_version": "1.3",                                                │
│      "generated_at": "2025-01-12T...",                                      │
│      "calculated_duration": 21.35                                           │
│    },                                                                       │
│                                                                             │
│    "canvas": {                                                              │
│      "source_resolution": {"width": 1080, "height": 1920},                  │
│      "working_resolution": {"width": 1404, "height": 2496},                 │
│      "final_resolution": {"width": 1080, "height": 1920}                    │
│    },                                                                       │
│                                                                             │
│    "hook_sequence": {                                                       │
│      "style_selected": "DRAMATIC",                                          │
│      "selection_reasoning": "Epic wide shot matches DRAMATIC style",        │
│      "duration": 0.5,                                                       │
│      "effects": [                                                           │
│        {"type": "SLOW_ZOOM", "params": {...}},                              │
│        {"type": "VIGNETTE", "params": {...}}                                │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "timeline": [                                                            │
│      {                                                                      │
│        "sequence_index": 1,                                                 │
│        "source_file": "1.mp4",                                              │
│        "reverse": false,                                                    │
│        "visual_type": {"primary": "EPIC_WIDE", "palette": "DRAMATIC"},     │
│        "cuts": [...],                                                       │
│        "speed_processing": {"speed_map": [...]},                            │
│        "visual_effects": [...],                                             │
│        "output_timing": {                                                   │
│          "cumulative_start": 0.0,                                           │
│          "duration": 3.47,                                                  │
│          "cumulative_end": 3.47                                             │
│        }                                                                    │
│      },                                                                     │
│      ... (scenes 2-5),                                                      │
│      {                                                                      │
│        "sequence_index": 6,                                                 │
│        "source_file": "6.mp4",                                              │
│        "reverse": true,                  ← ALWAYS TRUE                      │
│        ...                                                                  │
│      }                                                                      │
│    ],                                                                       │
│                                                                             │
│    "audio": {                                                               │
│      "music": {                                                             │
│        "file": "music/background.mp3",                                      │
│        "base_volume_db": -18,                                               │
│        "ducked_volume_db": -30,                                             │
│        "ducking_regions": [...]                                             │
│      },                                                                     │
│      "voiceover": {                                                         │
│        "file": "vo/voiceover.mp3",                                          │
│        "volume_db": -14                                                     │
│      },                                                                     │
│      "sfx": [                                ← ALL GENERATED BY ELEVENLABS │
│        {                                                                    │
│          "id": "SFX_HOOK",                                                  │
│          "prompt": "Epic cinematic impact hit, deep bass, reverb tail",   │
│          "timestamp": 0.0,                                                  │
│          "duration_seconds": 2.0,                                           │
│          "volume_db": -6                                                    │
│        },                                                                   │
│        ...                                                                  │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "subtitles": {                                                           │
│      "font": "Montserrat-Bold",                                             │
│      "items": [                                                             │
│        {                                                                    │
│          "id": "SUB1",                                                      │
│          "text": "The commute is raw.",                                     │
│          "style": "WHISPER",                                                │
│          "timing": {"start": 0.0, "end": 1.68},                            │
│          "position": {"zone": "bottom-center", "y_percent": 75},           │
│          "ffmpeg_drawtext": "drawtext=..."                                 │
│        },                                                                   │
│        ...                                                                  │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "beat_sync_report": {                                                    │
│      "transitions_on_beat": 4,                                              │
│      "transitions_off_beat": 2,                                             │
│      "sync_score": 0.67,                                                    │
│      "quality": "GOOD"                                                      │
│    },                                                                       │
│                                                                             │
│    "filter_chain": {                                                        │
│      "order": [                                                             │
│        "fps_normalize",                                                     │
│        "scale_up",                                                          │
│        "reverse",                                                           │
│        "trim",                                                              │
│        "setpts",                                                            │
│        "tmix",                                                              │
│        "effects",                                                           │
│        "color_grade",                                                       │
│        "crop_final",                                                        │
│        "subtitles"                                                          │
│      ]                                                                      │
│    },                                                                       │
│                                                                             │
│    "output_config": {                                                       │
│      "filename": "final.mp4",                                               │
│      "video_codec": "libx264",                                              │
│      "video_preset": "slow",                                                │
│      "video_crf": 18,                                                       │
│      "audio_codec": "aac",                                                  │
│      "audio_bitrate": "192k"                                                │
│    }                                                                        │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 6: GENERATE SFX                                          orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → generate_sfx()                                     │
│  API: ElevenLabs Sound Effects                                              │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PROCESS:                                                            │   │
│  │                                                                      │   │
│  │ for sfx in manifest.audio.sfx:                                      │   │
│  │                                                                      │   │
│  │     # ЗАВЖДИ генеруємо — без перевірки existing files              │   │
│  │     audio = await elevenlabs.text_to_sound_effects.convert(         │   │
│  │         text=sfx["prompt"],                                         │   │
│  │         duration_seconds=sfx["duration_seconds"],                   │   │
│  │         prompt_influence=0.5                                        │   │
│  │     )                                                               │   │
│  │                                                                      │   │
│  │     output_path = f"sfx/{sfx['id']}.mp3"                            │   │
│  │     save_audio(audio, output_path)                                  │   │
│  │                                                                      │   │
│  │     logger.info(f"Generated SFX: {sfx['id']}")                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Output: sfx/*.mp3                                                          │
│  Duration: ~2-3s per SFX                                                    │
│  Cost: ~$0.01 per SFX                                                       │
│                                                                             │
│  Example output files:                                                      │
│  ├── sfx/SFX_HOOK.mp3                                                      │
│  ├── sfx/SFX_TRAIN.mp3                                                     │
│  └── sfx/SFX_RICE.mp3                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 7: RENDER VIDEO                                          render_engine│
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: render_engine.py → render_from_manifest()                            │
│  Tool: FFmpeg                                                               │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ 7.1 VIDEO PROCESSING (per scene)                                    │  │
│  │                                                                       │  │
│  │ Following filter_chain.order:                                        │  │
│  │                                                                       │  │
│  │ 1. fps=30                          ← Normalize framerate            │  │
│  │ 2. scale=1404:2496                 ← Working resolution (30% larger)│  │
│  │ 3. reverse                         ← Scene 6 only                   │  │
│  │ 4. trim                            ← Apply CUTs (remove glitches)   │  │
│  │ 5. setpts=PTS/speed               ← Speed processing                │  │
│  │ 6. tmix=frames=5                   ← Motion blur for speed>2x       │  │
│  │ 7. [effects]                       ← Hook effects, content effects  │  │
│  │ 8. eq=saturation=1.1:contrast=1.05 ← Color grading                  │  │
│  │ 9. crop=1080:1920                  ← Final resolution               │  │
│  │ 10. concat                         ← Join all scenes                │  │
│  │ 11. drawtext                       ← Burn subtitles                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ 7.2 AUDIO MIXING                                                     │  │
│  │                                                                       │  │
│  │ 3 layers with amix:                                                  │  │
│  │                                                                       │  │
│  │ Layer 1 - MUSIC:                                                    │  │
│  │ • Base: -18dB                                                       │  │
│  │ • Ducked: -30dB (during voiceover)                                  │  │
│  │ • Apply ducking_regions from manifest                               │  │
│  │                                                                       │  │
│  │ Layer 2 - VOICEOVER:                                                │  │
│  │ • Normalized to -14dB LUFS                                          │  │
│  │                                                                       │  │
│  │ Layer 3 - SFX:                                                      │  │
│  │ • Load each sfx/{id}.mp3                                            │  │
│  │ • Apply at manifest timestamp                                       │  │
│  │ • Apply volume_db from manifest                                     │  │
│  │                                                                       │  │
│  │ Final: alimiter + loudnorm                                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ 7.3 ENCODE                                                           │  │
│  │                                                                       │  │
│  │ ffmpeg -i ... -filter_complex "..." \                               │  │
│  │   -c:v libx264 -preset slow -crf 18 \                               │  │
│  │   -c:a aac -b:a 192k \                                              │  │
│  │   -pix_fmt yuv420p \                                                │  │
│  │   -movflags +faststart \                                            │  │
│  │   output/final.mp4                                                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Output: output/final.mp4                                                   │
│  Duration: ~60-120s                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STEP 8: UPDATE CHANNEL CONTEXT                                orchestrator │
├─────────────────────────────────────────────────────────────────────────────┤
│  Файл: orchestrator.py → update_channel_context()                           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ АВТОМАТИЧНЕ СТВОРЕННЯ / ОНОВЛЕННЯ                                   │   │
│  │                                                                      │   │
│  │ Перший запуск (файл не існує):                                      │   │
│  │ → Створюється порожній channel_context.json                         │   │
│  │                                                                      │   │
│  │ Кожен наступний запуск:                                             │   │
│  │ → Читає існуючий файл                                               │   │
│  │ → Додає новий запис в hook_history                                  │   │
│  │ → Оновлює recent_hook_styles (останні 5)                            │   │
│  │ → Визначає avoid_next (якщо 2+ однакових підряд)                    │   │
│  │ → Зберігає назад                                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  channel_context.json structure:                                            │
│  {                                                                          │
│    "channel_id": "glaze_city",                                              │
│    "created_at": "2025-01-01T...",                                          │
│    "last_updated": "2025-01-12T...",                                        │
│                                                                             │
│    "hook_history": [                                                        │
│      {"project": "sashimi_station", "style": "DRAMATIC", "date": "..."},   │
│      {"project": "chocolate_villa", "style": "ELEGANT", "date": "..."},    │
│      {"project": "pizza_tower", "style": "IMPACT", "date": "..."}          │
│    ],                                                                       │
│                                                                             │
│    "recent_hook_styles": ["DRAMATIC", "ELEGANT", "IMPACT"],                │
│                                                                             │
│    "style_usage_count": {                                                   │
│      "DRAMATIC": 5,                                                         │
│      "ELEGANT": 3,                                                          │
│      "IMPACT": 4,                                                           │
│      "CLASSIC": 2,                                                          │
│      "GLITCH": 1                                                            │
│    },                                                                       │
│                                                                             │
│    "avoid_next": []     ← Заповнюється якщо 2+ однакових підряд            │
│  }                                                                          │
│                                                                             │
│  ⚠️  Файл зберігається на рівні КАНАЛУ, не проекту:                        │
│      {channel_dir}/channel_context.json                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ВИХІДНІ ДАНІ                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 {channel_dir}/                                                          │
│  ├── channel_context.json          ← AUTO-CREATED/UPDATED                  │
│  └── projects/                                                              │
│      └── {project_id}/                                                      │
│          ├── music/                                                         │
│          │   ├── background.mp3    ← Generated (Replicate)                 │
│          │   └── beat_analysis.json← Generated (librosa)                   │
│          ├── vo/                                                            │
│          │   ├── voiceover.mp3     ← Generated (ElevenLabs TTS)            │
│          │   └── emotion_tags.json ← Parsed from script                    │
│          ├── sfx/                                                           │
│          │   ├── SFX_HOOK.mp3      ← Generated (ElevenLabs SFX)            │
│          │   ├── SFX_TRAIN.mp3     ← Generated (ElevenLabs SFX)            │
│          │   └── ...                                                        │
│          ├── gen3a_analysis.json   ← Validated                             │
│          ├── manifest.json         ← Validated                             │
│          └── output/                                                        │
│              └── final.mp4         ← Loopable video                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 PIPELINE SUMMARY

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  MUSIC   │────▶│  BEATS   │────▶│    VO    │────▶│  UPLOAD  │
│(Replicate)     │ (librosa)│     │(ElevenLabs)    │ (Gemini) │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
   ~90s             ~3s              ~10s             ~30s
                                                        │
                      ┌─────────────────────────────────┘
                      ▼
               ┌─────────────┐      ┌─────────────┐
               │    GEN3a    │─────▶│  VAL_GEN3a  │──┐
               │  (Analyst)  │      │  (Py+Flash) │  │
               │   ~60-90s   │◀─────│    ~5s      │◀─┘ retry
               └─────────────┘      └─────────────┘
                      │
                      ▼ gen3a_analysis.json
               ┌─────────────┐      ┌─────────────┐
               │    GEN3b    │─────▶│  VAL_GEN3b  │──┐
               │  (Artist)   │      │  (Py+Flash) │  │
               │   ~30-45s   │◀─────│    ~5s      │◀─┘ retry
               └─────────────┘      └─────────────┘
                      │
                      ▼ manifest.json
               ┌─────────────┐
               │  SFX GEN    │  ← ALL from ElevenLabs
               │   ~10s      │
               └─────────────┘
                      │
                      ▼
               ┌─────────────┐
               │   RENDER    │
               │  (FFmpeg)   │
               │  ~60-120s   │
               └─────────────┘
                      │
                      ▼
               ┌─────────────┐
               │  UPDATE     │  ← channel_context.json
               │  CONTEXT    │
               └─────────────┘
                      │
                      ▼
               ┌─────────────┐
               │   OUTPUT    │
               │  final.mp4  │
               └─────────────┘
```

---

## ⏱️ TIMING ESTIMATE

| Step | Duration | Notes |
|------|----------|-------|
| 0. Music Generation | ~60-90s | Replicate MusicGen |
| 1. Beat Analysis | ~3-5s | Local librosa |
| 2. Voiceover | ~10s | ElevenLabs TTS |
| 3. Upload | ~30s | 7 files to Gemini |
| 4. GEN3a | ~60-90s | Video analysis |
| 4.1. VAL_GEN3a | ~5s | Python + Flash |
| 5. GEN3b | ~30-45s | Manifest creation |
| 5.1. VAL_GEN3b | ~5s | Python + Flash |
| 6. SFX Generation | ~10s | 3-5 SFX × 2-3s |
| 7. Render | ~60-120s | FFmpeg |
| 8. Update Context | ~1s | JSON write |
| **TOTAL** | **~5-7 min** | Without retries |

---

## 🔧 API DEPENDENCIES

| Service | Purpose | Model/Endpoint |
|---------|---------|----------------|
| Replicate | Music generation | facebook/musicgen-large |
| Gemini | GEN3a analysis | gemini-2.5-pro |
| Gemini | GEN3b editing | gemini-2.5-pro |
| Gemini | Validators | gemini-2.5-flash |
| ElevenLabs | Voiceover | text-to-speech |
| ElevenLabs | SFX | text-to-sound-effects |
| librosa | Beat detection | (local) |
| FFmpeg | Video render | (local) |

---

## 🔄 ERROR HANDLING

```python
MAX_RETRIES = 3

async def run_pipeline(channel_dir: str, project_id: str):
    project_dir = f"{channel_dir}/projects/{project_id}"
    
    # Step 0-2: Preprocessing (skip if exists)
    await ensure_music(project_dir)
    await ensure_beats(project_dir)
    await ensure_voiceover(project_dir)
    
    # Step 3: Upload
    file_refs = await upload_files(project_dir)
    
    # Step 4: GEN3a with retry
    channel_context = load_channel_context(channel_dir)
    gen3a = await run_with_retry(
        generator=lambda fb: run_gen3a(project_dir, file_refs, channel_context, fb),
        validator=validate_gen3a,
        max_retries=MAX_RETRIES
    )
    
    # Step 5: GEN3b with retry
    manifest = await run_with_retry(
        generator=lambda fb: run_gen3b(project_dir, gen3a, fb),
        validator=validate_gen3b,
        max_retries=MAX_RETRIES
    )
    
    # Step 6: SFX
    await generate_all_sfx(project_dir, manifest)
    
    # Step 7: Render
    await render_video(project_dir, manifest)
    
    # Step 8: Update context
    update_channel_context(channel_dir, project_id, manifest)
    
    return f"{project_dir}/output/final.mp4"
```

---

## 📝 FILES TO CREATE

| File | Status | Priority |
|------|--------|----------|
| config/GEN3a_v1.3.md | ✅ Є, minor updates | LOW |
| config/GEN3b_v1.3.md | ✅ Є, minor updates | LOW |
| preprocessor.py | ❌ Потрібно | HIGH |
| orchestrator.py | ❌ Потрібно | HIGH |
| validators/val_gen3a.py | ❌ Потрібно | HIGH |
| validators/val_gen3b.py | ❌ Потрібно | HIGH |
| render_engine.py | ❓ Перевірити | MEDIUM |

---

## 📋 PROMPTS TO UPDATE

### GEN3a — додати:

```markdown
## CHANNEL CONTEXT INTEGRATION

If channel_context.json is provided:

1. READ avoid_next array
2. DO NOT recommend styles in avoid_next
3. PREFER styles not recently used (variety)
4. DOCUMENT in hook_variety_analysis:
   - channel_context_received: true
   - avoided_styles: [...]
   - variety_reasoning: "..."
```

### GEN3b — додати:

```markdown
## SFX DEFINITION

ALL SFX are generated by ElevenLabs. Each SFX MUST have:

- id: Unique identifier (SFX_HOOK, SFX_TRAIN, etc.)
- prompt: Descriptive text for generation (REQUIRED!)
- timestamp: When to play (output time)
- duration_seconds: How long the sound should be
- volume_db: Volume level
```

---

*Pipeline v2.1 — Complete with Music Generation, Beat Analysis, SFX Generation*
*Last updated: 2025-01-12*