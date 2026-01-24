# YTAuto - Project Structure

> **Last Updated:** 2026-01-24
> **Stage:** Pipeline v2.2 with AudioStage

## Quick Overview

AI-конвеєр для автоматичної генерації коротких відео (9:16, 4K) для YouTube.

**Pipeline:** Script → Image → Validation → Video → **Audio** → GEN3a → GEN3b → PostProcess

---

## Directory Structure

```
YTAuto/
├── app/                           # Main application
│   ├── core/                      # Core infrastructure
│   │   ├── config.py              # Pydantic Settings, loads .env
│   │   ├── state_manager.py       # Async SQLite, project/scene CRUD
│   │   └── orchestrator.py        # Pipeline orchestration, PRIMARY flow
│   │
│   ├── services/                  # AI service integrations
│   │   ├── content_brain.py       # GEN1: Gemini/Claude script generation
│   │   ├── visual_engine.py       # Higgsfield API (images + videos)
│   │   ├── audio_engine.py        # ElevenLabs TTS
│   │   ├── video_assembler.py     # FFmpeg final assembly
│   │   ├── image_validator.py     # GLAZE-VAL image validation
│   │   ├── prompt_router.py       # Routes prompts GEN1 → GEN2
│   │   ├── topic_memory.py        # [NEW] Blacklist: last N topics FIFO
│   │   ├── models.py              # Core Pydantic models (Script, Scene)
│   │   ├── glaze_models.py        # GLAZE system data structures
│   │   ├── glaze_parser.py        # GLAZE JSON parsing
│   │   ├── gen_models.py          # Generation models
│   │   └── validation_models.py   # Validation response models
│   │
│   ├── pipeline/                  # Pipeline stages
│   │   ├── orchestrator.py        # Stage coordinator
│   │   ├── base.py                # BasePipelineStage
│   │   ├── script_stage.py        # GEN1 + GEN2
│   │   ├── image_stage.py         # Image generation
│   │   ├── validation_stage.py    # Image validation
│   │   ├── video_stage.py         # Video generation
│   │   ├── audio_stage.py         # [NEW] Audio generation (voiceover, music)
│   │   ├── gen3_stages.py         # GEN3a + GEN3b stages
│   │   └── postprocess_stage.py   # FFmpeg render, Topaz, thumbnail
│   │
│   ├── modules/                   # High-level modules
│   │   └── topaz_queue.py         # Topaz Video AI queue
│   │
│   ├── telegram/                  # Telegram bot
│   │   └── telegram_controller.py # Bot commands, approval flows
│   │
│   ├── api/                       # REST API
│   │   ├── routes.py              # FastAPI endpoints
│   │   └── schemas.py             # API request/response models
│   │
│   ├── web/                       # Web UI
│   │   ├── database.py            # Web DB models
│   │   ├── schemas.py             # Web schemas
│   │   ├── channel_service.py     # Channel management
│   │   ├── static/                # CSS, JS
│   │   └── templates/             # Jinja2 HTML
│   │
│   └── utils/                     # Utilities
│       ├── logger.py              # Loguru setup, rotating logs
│       └── file_manager.py        # Async file operations
│
├── config/                        # Configuration
│   ├── .env                       # API keys (FILLED)
│   ├── .env.example               # Template
│   ├── settings.yaml              # Non-secret config
│   ├── GEN1.txt                   # [PROTECTED] Creative Director
│   ├── GEN2.txt                   # [PROTECTED] Visual Director
│   ├── VAL_IMG.txt                # [PROTECTED] Image Validator
│   ├── VAL_GEN1.txt               # [PROTECTED] GEN1 Validator
│   ├── VAL_GEN2.txt               # [PROTECTED] GEN2 Validator
│   └── PROJECT_STRUCTURE.md       # THIS FILE
│
├── python/                        # Portable Python 3.11.9
│   └── python.exe                 # Main interpreter
│
├── projects/                      # Generated video projects
│   └── {project_id}/              # Each project folder
│       ├── scene_N/               # Scene assets
│       ├── project_brief.json     # Project metadata
│       ├── voiceover.mp3          # Generated audio
│       └── final.mp4              # Final video
│
├── data/                          # Data storage
│   ├── state.db                   # SQLite (projects, scenes, api_logs)
│   └── topic_memory.json          # [NEW] Last N topics blacklist (FIFO)
│
├── logs/                          # Rotating logs
│   ├── app.log                    # Main app
│   ├── api.log                    # API calls
│   ├── telegram.log               # Bot
│   └── topaz.log                  # Upscaling
│
├── tests/                         # Test files (40+)
├── debug/                         # Debug artifacts
│
├── main.py                        # Entry point
├── run.bat                        # Windows launcher
├── setup.bat                      # First-time setup
└── requirements.txt               # Dependencies
```

---

## Key Modules Reference

### Core (`app/core/`)

| File | Class/Function | Purpose |
|------|----------------|---------|
| `config.py` | `Settings` | Pydantic config, loads `.env`, validates API keys |
| `state_manager.py` | `StateManager` | Async SQLite CRUD for projects/scenes |
| `orchestrator.py` | `ProjectOrchestrator` | Full pipeline lifecycle, PRIMARY selection |

### Services (`app/services/`)

| File | Class | Purpose |
|------|-------|---------|
| `content_brain.py` | `ContentBrain` | GEN1: Script generation via Gemini/Claude |
| `visual_engine.py` | `HiggsFieldClient` | Image gen (Nano Banana Pro), Video gen (Kling v2.6) |
| `audio_engine.py` | `AudioEngine` | ElevenLabs TTS voiceover |
| `video_assembler.py` | `VideoAssembler` | FFmpeg scene concatenation + audio |
| `image_validator.py` | `ImageValidator` | GLAZE-VAL quality check |
| `prompt_router.py` | `PromptRouter` | Passes GEN1 output to GEN2 |
| `topic_memory.py` | `TopicMemory` | FIFO blacklist, prevents topic repetition |
| `models.py` | `Script`, `Scene`, `ScenePrompts` | Core data models |

### Integration

| File | Class | Purpose |
|------|-------|---------|
| `modules/topaz_queue.py` | `TopazQueue` | Video upscaling queue |
| `telegram/telegram_controller.py` | `TelegramController` | Bot, approvals |
| `api/routes.py` | - | REST API endpoints |
| `web/` | - | Dashboard UI |

---

## Pipeline Flow (v2.2)

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR STAGES                         │
│     Script → Image → Validation → Video → Audio → GEN3a/b       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  1. ScriptStage                                                  │
│  - GEN1: Creative Director (Gemini) → script, hooks, scenes     │
│  - GEN2: Visual Director → image_prompt, video_prompt per scene │
│  - Output: project_brief.json                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. ImageStage                                                   │
│  - Higgsfield Web: nano-banana-pro                               │
│  - Resolution: 2160x3840 (4K vertical)                           │
│  - PRIMARY scene first, then remaining in parallel               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. ValidationStage                                              │
│  - GLAZE-VAL: Image quality validation                           │
│  - Checks: artifacts, composition, consistency                   │
│  - Auto-retry failed images                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. VideoStage                                                   │
│  - Kling v2.6 Pro image-to-video                                 │
│  - 10 seconds per scene                                          │
│  - Motion from video_prompt                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. AudioStage (NEW - runs BEFORE GEN3a!)                        │
│  - Voiceover: ElevenLabs TTS from project_brief                  │
│  - Music: Replicate Stable Audio                                 │
│  - Ambient: Optional ambient bed                                 │
│  - Output: voiceover.mp3, music.mp3, ambient.mp3                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. Gen3aStage                                                   │
│  - Preprocessing: beats.json, vo_timing.json (uses audio!)      │
│  - Video analysis with Gemini Vision                             │
│  - Glitch detection, action peaks, speed maps                    │
│  - Output: gen3a_analysis.json                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. Gen3bStage                                                   │
│  - Creative editing decisions                                    │
│  - Hook style, effects, transitions                              │
│  - Beat sync alignment                                           │
│  - Output: manifest.json                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  8. PostProcessStage                                             │
│  - ManifestRenderer: FFmpeg rendering from manifest              │
│  - 5-layer audio mixing                                          │
│  - Topaz upscale (optional)                                      │
│  - Thumbnail generation                                          │
│  - Output: final.mp4                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Topic Memory (Blacklist System)

Prevents repetitive content by tracking last N topics.

**Module:** `app/services/topic_memory.py`
**Storage:** `data/topic_memory.json`
**Config:** `TOPIC_MEMORY_LIMIT` in `.env` (default: 20, range: 5-100)

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  TOPIC MEMORY (FIFO Queue)                                      │
├─────────────────────────────────────────────────────────────────┤
│  Stores last N topics:                                          │
│  - title, category, primary_food, subject, created_at           │
│                                                                 │
│  Generates blacklist for GEN1:                                  │
│  - blocked_subjects (unique subjects from last N)               │
│  - blocked_foods (unique foods from last N)                     │
│  - category_counts (to avoid overused categories)               │
└─────────────────────────────────────────────────────────────────┘
```

### Usage

```python
from app.services.topic_memory import topic_memory

# Get blacklist markdown for GEN1 prompt
blacklist_md = topic_memory.generate_blacklist_markdown()

# Inject into GEN1 prompt
prompt = GEN1_TEMPLATE.replace("{{BLACKLIST_INJECTION}}", blacklist_md)

# After successful generation, add to memory
topic_memory.add_topic(gen1_output)

# Check if combination is blocked
is_blocked, reason = topic_memory.is_blocked("peanut butter", "dam")
```

### GEN1.txt Integration

GEN1.txt contains placeholder `{{BLACKLIST_INJECTION}}` that gets replaced with dynamic blacklist before each generation.

---

## API Keys Required (in .env)

| Key | Service | Used By |
|-----|---------|---------|
| `HIGGSFIELD_API_KEY` | Higgsfield | visual_engine.py |
| `HIGGSFIELD_API_SECRET` | Higgsfield | visual_engine.py |
| `GOOGLE_GEMINI_API_KEY` | Google AI | content_brain.py |
| `ANTHROPIC_API_KEY` | Claude (optional) | content_brain.py |
| `ELEVENLABS_API_KEY` | ElevenLabs | audio_engine.py |
| `TELEGRAM_BOT_TOKEN` | Telegram | telegram_controller.py |
| `TELEGRAM_CHAT_ID` | Telegram | telegram_controller.py |

---

## Protected Files (DO NOT MODIFY)

These files contain carefully crafted prompts:

- `config/GEN1.txt` - Creative Director system prompt
- `config/GEN2.txt` - Visual Director system prompt
- `config/VAL_IMG.txt` - Image Validator prompt
- `config/VAL_GEN1.txt` - GEN1 output validator
- `config/VAL_GEN2.txt` - GEN2 output validator

---

## Entry Points

```bash
# Main application
./python/python.exe main.py

# Full pipeline test
./python/python.exe run_real_pipeline.py "Topic" --yes

# Free topic (auto-generated)
./python/python.exe run_real_pipeline.py --free --yes

# Web UI
./python/python.exe run_web.py

# Telegram bot standalone
./python/python.exe run_bot.py
```

---

## Database Schema (data/state.db)

Tables:
- `projects` - Project metadata, status
- `scenes` - Scene data, prompts, status
- `images` - Generated images
- `videos` - Generated videos
- `api_requests` - API call logs
- `state_storage` - Key-value state

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Python | 3.11.9 (portable) |
| Web | FastAPI + Uvicorn |
| Templates | Jinja2 |
| Bot | Aiogram 3.x |
| AI (text) | Google Gemini / Claude |
| AI (image) | Higgsfield Nano Banana Pro |
| AI (video) | Kling v2.6 |
| TTS | ElevenLabs |
| Video | FFmpeg |
| Upscale | Topaz Video AI |
| Database | SQLite (aiosqlite) |
| Config | Pydantic 2.x |
| Logging | Loguru |
