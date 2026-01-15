# Полный анализ кодовой базы YTAuto

## Обзор структуры

### Статистика файлов
- **Всего Python файлов (app/):** ~45
- **Pydantic моделей (BaseModel):** 77 классов
- **Сервисы:** 11 файлов (6,683 строк)
- **Pipeline stages:** 9 файлов
- **Config файлы:** 10 txt + 1 py

---

## 1. ДУБЛИКАТЫ МОДЕЛЕЙ

### 1.1 Критические дубликаты (одинаковая функциональность)

| Концепт | Файл 1 | Файл 2 | Файл 3 (legacy) |
|---------|--------|--------|-----------------|
| **Scene** | `Gen1SceneConcept` (gen_models:403) | `GlazeScene` (glaze_models:97) | `Scene` (models:69) |
| **Easter Egg** | `Gen1EasterEgg` (gen_models:367) | `EasterEgg` (glaze_models:74) | - |
| **Hook** | `Gen1Hook` (gen_models:294) | `HookStrategy` (glaze_models:52) | - |
| **Voiceover** | `Gen1VoiceoverConfig` (gen_models:476) | `VoiceoverConfig` (glaze_models:150) | - |
| **Audio** | `Gen1AudioConfig` (gen_models:522) | `AudioConfig` (glaze_models:196) | - |
| **Lighting** | `Gen1LightingMaster` (gen_models:354) | - | - |
| **Property** | `Gen1Property` (gen_models:286) | `PropertyBrief` (glaze_models:35) | - |
| **Validation** | - | `ValidationResponse` (validation_models:112) | `ValidationResult` (models:212) |

### 1.2 Детальное сравнение дублей

#### Scene Models (3 версии!)

**Gen1SceneConcept** (gen_models.py:403):
```python
- scene_number, scene_name, duration_seconds
- narrative_purpose, reference_hint, energy_level
- visual_concept: Gen1VisualConcept  # Вложенный объект
- camera_intent: Gen1CameraIntent    # Вложенный объект
- voiceover_segment, audio_moment
```

**GlazeScene** (glaze_models.py:97):
```python
- scene_number, scene_name, duration_seconds
- voiceover, on_screen_text, visual_description
- camera_movement, audio_sfx
- image_prompt, video_prompt, reference_type, video_tool
```

**Scene** (models.py:69) - LEGACY:
```python
- scene_number, description, key_elements, mood
- prompts: ScenePrompts  # Вложенный объект
- image_path, video_path, status
```

**ВЫВОД:** 3 разные модели для одного и того же! Нужна консолидация.

#### Easter Egg (2 версии)

**Gen1EasterEgg** (gen_models.py:367):
```python
- object: str
- scene_number: int
- safe_zone_position: str
- comment_bait: str
```

**EasterEgg** (glaze_models.py:74):
```python
- object: str
- scene_number: int
- location: str = ""  # Устарело?
- comment_bait: str = ""
```

**ВЫВОД:** Почти идентичны. `Gen1EasterEgg` более полная. `location` vs `safe_zone_position`.

#### Validation Results (2 версии)

**ValidationResult** (models.py:212) - LEGACY:
```python
- approved: bool
- confidence: float (0-1)
- feedback: str
- issues: List[str]
- strengths: List[str]
- suggestions: List[str]
- matches_prompt: bool
- quality_score: float (0-10)
```

**ValidationResponse** (validation_models.py:112) - CURRENT:
```python
- validation: ValidationMetadata
- phase1_glitch_detection: Phase1GlitchDetection
- phase2_quality_scoring: Phase2QualityScoring
- phase3_decision: Phase3Decision
- issues: Issues
- retry_prompts: RetryPrompts
```

**ВЫВОД:** `ValidationResponse` - правильная структура под VAL_IMG v2.0. `ValidationResult` - устаревшая.

---

## 2. ДУБЛИКАТЫ ORCHESTRATOR

### 2.1 Два Orchestrator класса

| Класс | Файл | Строк | Статус |
|-------|------|-------|--------|
| `ProjectOrchestrator` | app/core/orchestrator.py | 600+ | Legacy, с TODO |
| `PipelineOrchestrator` | app/pipeline/orchestrator.py | 200+ | Modern, stage-based |

**ProjectOrchestrator** (core/orchestrator.py):
- Manual PRIMARY selection workflow
- SQLite state persistence через state_manager
- Callbacks: `on_primary_image_selected()`, `on_scene_approved()`
- 20+ TODO комментариев (неполные фичи)
- Импортирует legacy `models.py` (Script, Scene, ScenePrompts)

**PipelineOrchestrator** (pipeline/orchestrator.py):
- Modern stage-based архитектура
- Использует `BasePipelineStage` паттерн
- 5 стадий: Script → Image → Validation → Video → PostProcess
- Не использует legacy models

### 2.2 ControlPipeline - wrapper над ProjectOrchestrator

**ControlPipeline** (pipeline/control_pipeline.py):
- Wrapper над `ProjectOrchestrator`
- Используется для Control Panel UI
- Дублирует логику из PipelineOrchestrator

**ВЫВОД:** 3 места с pipeline логикой! Нужна консолидация в один Orchestrator.

---

## 3. МЕРТВЫЙ КОД (Dead Code)

### 3.1 Файлы-кандидаты на удаление

| Файл | Причина | Импортируется в |
|------|---------|-----------------|
| `app/services/models.py` | Legacy модели, заменены gen_models | Только content_brain.py |
| `app/pipeline/control_pipeline.py` | Wrapper с дублированием | control_routes.py |
| `app/core/orchestrator.py` | Legacy orchestrator | control_pipeline.py |

### 3.2 Неиспользуемые импорты

```python
# app/core/orchestrator.py:28
from app.services.models import Script, Scene, ScenePrompts
# ↑ Импортируются но НЕ используются (используется ProjectData из schemas)
```

### 3.3 Устаревшие методы

**content_brain.py:**
- `generate_script()` (строки 221-348) - Legacy метод с комментарием "backwards compatibility"
- Основной API теперь `generate_glaze_project()`

**gen_models.py:**
- `Gen2BatchInput` (строка 935) - Только для backwards compat

### 3.4 Неиспользуемые конфиг файлы

| Файл | Статус |
|------|--------|
| `config/GLAZE_CITY_GEN_v7.4.txt` | Устаревшая версия (v7.4 когда есть GEN1.txt v3.0) |

---

## 4. АРХИТЕКТУРНЫЕ ПРОБЛЕМЫ

### 4.1 Модели разбросаны по 4 файлам

```
app/services/
├── models.py           # 4 класса (LEGACY)
├── gen_models.py       # 32 класса (GEN1/GEN2 contract)
├── glaze_models.py     # 19 классов (JSON output)
└── validation_models.py # 22 класса (validation)
```

**Проблема:** Одни и те же концепты определены в разных файлах с разной структурой.

### 4.2 Сложная цепочка трансформаций

```
GEN1 Output (Gen1Output из gen_models.py)
    ↓ transform
DeliveryPayload (gen_models.py)
    ↓ GEN2
Gen2BatchOutput (gen_models.py)
    ↓ merge_outputs
GlazeCityProject (glaze_models.py)
    ↓ to SceneData
ProjectData (api/schemas.py)
```

**Проблема:** Данные копируются между 4+ форматами моделей.

### 4.3 Валидация фрагментирована

```
ValidationResult (models.py)           # Legacy - простая структура
ValidationResponse (validation_models.py)  # VAL_IMG - 3-фазная
Gen1ValidationResponse (validation_models.py)  # VAL_GEN1
Gen2ValidationResponse (validation_models.py)  # VAL_GEN2
```

---

## 5. РЕКОМЕНДАЦИИ ПО ОЧИСТКЕ

### 5.1 Фаза 1: Удаление мертвого кода (SAFE)

1. **Удалить:** `app/services/models.py`
   - Перенести `ValidationResult` → `validation_models.py` (если нужен)
   - Обновить `content_brain.py` импорты

2. **Удалить:** `app/pipeline/control_pipeline.py`
   - Использовать `PipelineOrchestrator` напрямую

3. **Удалить:** `app/core/orchestrator.py`
   - Мигрировать нужную логику в `PipelineOrchestrator`

4. **Удалить:** `config/GLAZE_CITY_GEN_v7.4.txt`
   - Устаревшая версия промпта

### 5.2 Фаза 2: Консолидация моделей (MEDIUM RISK)

1. **Унифицировать Scene:**
   - Оставить `GlazeScene` как основную
   - Добавить недостающие поля из `Gen1SceneConcept`
   - Создать `@classmethod from_gen1()` для конвертации

2. **Унифицировать Easter Egg:**
   - Оставить `EasterEgg` в glaze_models.py
   - Добавить `safe_zone_position` вместо `location`

3. **Унифицировать Validation:**
   - Удалить `ValidationResult` из models.py
   - Использовать `ValidationResponse` везде

### 5.3 Фаза 3: Архитектурные улучшения (HIGH RISK)

1. **Единый Orchestrator:**
   - Мигрировать всю логику в `PipelineOrchestrator`
   - Добавить callbacks для UI integration
   - Удалить `ProjectOrchestrator` и `ControlPipeline`

2. **Единый models layer:**
   - Создать `app/models/` директорию
   - `app/models/project.py` - основные модели
   - `app/models/generation.py` - GEN1/GEN2 контракты
   - `app/models/validation.py` - валидация

---

## 6. КАРТА ЗАВИСИМОСТЕЙ

### Что от чего зависит:

```
api/schemas.py (ProjectData, SceneData)
    ↑ используется
pipeline/*.py (все stages)
    ↑ используется
services/prompt_router.py
    ↓ импортирует
services/gen_models.py + services/glaze_models.py
    ↓ импортирует
services/validation_models.py

services/content_brain.py
    ↓ импортирует
services/models.py (LEGACY) ← УДАЛИТЬ ЭТУ ЗАВИСИМОСТЬ
```

### Безопасный порядок удаления:

1. `models.py` → сначала убрать импорт из `content_brain.py`
2. `control_pipeline.py` → убрать использование в `control_routes.py`
3. `core/orchestrator.py` → убрать использование в `control_pipeline.py`

---

## 7. ИТОГОВАЯ СТАТИСТИКА ДУБЛЕЙ

| Тип | Количество | Файлы |
|-----|------------|-------|
| Дублирующиеся модели | 15+ пар | gen_models, glaze_models, models |
| Дублирующиеся orchestrators | 3 | core/orchestrator, pipeline/orchestrator, control_pipeline |
| Мертвый код (файлы) | 3-4 | models.py, control_pipeline.py, core/orchestrator.py |
| Неиспользуемые импорты | 2-3 | core/orchestrator.py |
| Устаревшие конфиги | 1 | GLAZE_CITY_GEN_v7.4.txt |

---

## 8. ПЛАН ДЕЙСТВИЙ

### Перед началом реализации нового pipeline:

```
[ ] Шаг 1: Удалить GLAZE_CITY_GEN_v7.4.txt (безопасно)
[ ] Шаг 2: Убрать импорт models.py из content_brain.py
[ ] Шаг 3: Проверить что models.py больше нигде не используется
[ ] Шаг 4: Удалить models.py
[ ] Шаг 5: Мигрировать control_pipeline → PipelineOrchestrator
[ ] Шаг 6: Удалить control_pipeline.py
[ ] Шаг 7: Мигрировать нужную логику из core/orchestrator.py
[ ] Шаг 8: Удалить core/orchestrator.py
```

### После очистки:

```
app/services/
├── gen_models.py         # GEN1/GEN2/GEN3a/GEN3b контракты
├── glaze_models.py       # Финальный JSON output
├── validation_models.py  # Все валидации
├── prompt_router.py      # Routing между стадиями
├── content_brain.py      # Gemini client (без legacy imports)
├── audio_engine.py       # ElevenLabs TTS + SFX
├── video_assembler.py    # FFmpeg rendering
├── image_validator.py    # VAL_IMG v3.0
├── gen3a_service.py      # [NEW] Video Analyst
├── gen3b_service.py      # [NEW] Manifest Generator
├── beat_analyzer.py      # [NEW] Librosa beats
└── topic_memory.py       # Blacklist

app/pipeline/
├── orchestrator.py       # ЕДИНСТВЕННЫЙ orchestrator
├── base.py               # BasePipelineStage
├── script_stage.py
├── image_stage.py
├── validation_stage.py
├── video_stage.py
├── analysis_stage.py     # [NEW] GEN3a
├── manifest_stage.py     # [NEW] GEN3b
└── postprocess_stage.py
```

---

*Анализ выполнен: 2026-01-13*
