# YTAuto — Claude Code Instructions

## Мова
**Спілкуйся з користувачем УКРАЇНСЬКОЮ.** Код, змінні, коміти — англійською.

## Про проект
YTAuto — автоматизована платформа для YouTube Shorts: AI-сценарій → зображення → відео → аудіо → монтаж → публікація.
- Windows 11, Python 3.11+, FastAPI + WebSocket, Pydantic v2
- AI: Gemini 1.5 Pro, ElevenLabs TTS, Replicate MusicGen, HiggsField (Kling v2.6)
- Постобробка: FFmpeg + Topaz Video AI

## Пайплайн (10 stages)
```
GEN1 (Creative Director) → DeliveryPayload → GEN2 (Visual Director) → Merge → GlazeCityProject
→ Image Gen → Image Validation → Video Gen → Audio Gen
→ GEN3a Preprocessing → GEN3a (Video Analyst) → GEN3b (FFmpeg Manifest)
→ ManifestRenderer → Topaz 4K → Thumbnail → YouTube Upload
```
- Сцени: 6-10 динамічно. Scene 1=PRIMARY, Scene N-1=AERIAL, Scene N=LOOP_CLOSE (реверс)
- Pipeline stages: `app/pipeline/` — async, послідовні, через `orchestrator.py`

## Ключові файли (hot path)
| Файл | Що робить |
|------|-----------|
| `app/services/gen_models.py` | Pydantic моделі: Gen1Output, Gen2BatchOutput, DeliveryPayload |
| `app/services/gen1_validator.py` | Детермінований валідатор GEN1 (MIN=6, MAX=10 сцен) |
| `app/services/gen2_validator.py` | Детермінований валідатор GEN2 |
| `app/services/prompt_router.py` | Оркестрація GEN1→GEN2→merge |
| `app/services/glaze_models.py` | GlazeCityProject — merged output model |
| `app/services/content_brain.py` | Gemini script generation |
| `app/services/audio_engine.py` | 5-layer audio + ElevenLabs TTS |
| `app/services/manifest_renderer.py` | Gen3b manifest → final video (FFmpeg) |
| `app/pipeline/orchestrator.py` | Запуск stages послідовно |
| `app/pipeline/control_pipeline.py` | Control Panel + approval workflow |
| `app/core/config.py` | Settings (Pydantic BaseSettings, .env) |
| `app/core/paths.py` | BASE_DIR, PROJECTS_DIR, get_project_path() |
| `config/GEN1.txt` | Creative Director prompt v8.2.0 |
| `config/GEN2.txt` | Visual Director prompt v5.0.0 |

## Структура (коротко)
```
app/services/     — бізнес-логіка (моделі, валідатори, AI сервіси, аудіо, відео)
app/pipeline/     — pipeline stages (script → image → video → audio → gen3 → render → publish)
app/clients/      — HiggsField + AdsPower Selenium автоматизація
app/core/         — config, paths, errors, state_manager
app/utils/        — logger, file_manager, prompt_loader, yt_metadata_parser
app/api/          — FastAPI routes (control_routes.py — основний)
app/server/       — WebSocket (notifications, broadcasts)
app/modules/      — Topaz Video AI integration
config/           — промпти (GEN1-3, VAL_*), ban_list, timeouts.py, channels/
src/publisher/    — YouTube upload daemon + A/B testing
src/human_commenter/ — YouTube commenting bot (Playwright)
projects/         — згенеровані проекти (proj_<uuid>/)
```

## Coding conventions
- **Імпорти**: абсолютні — `from app.services.gen_models import Gen1Output`
- **Async**: всі pipeline stages — `async def execute(self) -> StageResult`
- **Логер**: `from loguru import logger` (не logging, не print)
- **Моделі**: Pydantic v2. Валідатори окремо від моделей (gen1_validator.py, gen2_validator.py)
- **Промпти**: `config/*.txt`, завантажуються через `app/utils/prompt_loader.py`

## Запуск
```bash
python run_real_pipeline.py --free -y   # повний пайплайн
python run_web.py                       # Web UI (:8000)
python run_pipeline.py                  # тільки постобробка
python -m pytest tests/                 # тести
```

## Правила безпеки
- **НЕ чіпай** prompt-файли (GEN1.txt, GEN2.txt, GEN3*.txt) без явного дозволу
- **НЕ модифікуй** `.env`, `config/channels/` (OAuth tokens)
- **НЕ видаляй** `projects/` директорії — там готові відео
- Якщо правиш модель → перевір відповідний валідатор → запусти тести

## Gotchas
- Pydantic v2: `_field` заборонено → `field` + `model_validator` для маппінгу
- Windows console: cp1251 не тримає emoji → `python -X utf8`
- GEN3a.txt: read-only на Windows → `attrib -R` перед редагуванням
- `gen2_validator`: `_total_scenes` attr, fallback `getattr(self, '_total_scenes', 6)`
- DeliveryPayload — тільки GEN1→GEN2 handoff, НЕ для merged output
- GEN1 v6+: verdict=рядки, hashtags optional, pinned_comment nullable, emotion tags в complete_hook_vo
- Gen2 banned camera: "drifting/floating" OK для об'єктів (планктон, пилинки)
- `validation_models.py`: scene fields `le=10` (було `le=6` — ламало сцени 7-10)
