# План обновления YTAuto Pipeline v7.4

## Текущее состояние vs Требуемое

### Текущий пайплайн (5 стадий)
```
ScriptStage (GEN1 → VAL_GEN1 → GEN2 → VAL_GEN2)
    ↓
ImageStage (PRIMARY + REMAINING)
    ↓
ValidationStage (VAL_IMG)
    ↓
VideoStage (Kling generation)
    ↓
PostProcessStage (VO + простая сборка)
```

### Требуемый пайплайн (7 стадий)
```
ScriptStage (GEN1 v3.0 → VAL_GEN1 → GEN2 v3.0 → VAL_GEN2)
    ↓
ImageStage (PRIMARY + REMAINING с Gigantism Protocol)
    ↓
ValidationStage (VAL_IMG v3.0)
    ↓
VideoStage (Kling 10s clips)
    ↓
AnalysisStage [NEW] (GEN3a v1.3.1 → VAL_GEN3a)
    ↓
ManifestStage [NEW] (GEN3b v1.3.1 → VAL_GEN3b)
    ↓
PostProcessStage (5-layer audio + manifest.json assembly)
```

---

## Часть 1: Обновление Data Models

### 1.1 glaze_models.py — Новые поля v7.4

**Файл:** `app/services/glaze_models.py`

**Добавить модели:**

```python
# Architectural Identity (из GEN1 v3.0)
class ArchitecturalIdentity(BaseModel):
    style_code: str  # "JAPANESE_MINIMALIST", "BRUTALIST_GOTHIC", etc.
    style_description: str
    distinctive_features: List[str]
    silhouette_description: str
    interior_style: str

# Food DNA (маппинг еды на архитектурные элементы)
class FoodDNA(BaseModel):
    walls_become: str
    roof_becomes: str
    windows_become: str
    door_becomes: str
    chimney_becomes: str
    stairs_become: str
    fence_becomes: str
    landscaping_becomes: str

# Food Identity
class FoodIdentity(BaseModel):
    primary_food: str
    food_dna: FoodDNA
    texture_keywords: List[str]
    color_keywords: List[str]
    atmosphere: str

# Lighting Master
class LightingMaster(BaseModel):
    preset: str  # "GOLDEN_HOUR", "DRAMATIC_SHADOWS", etc.
    mood_reason: str
    prompt_snippet: str

# Foreground Element
class ForegroundElement(BaseModel):
    type: str  # "STEAM", "GLAZE_DRIP", "FALLING_INGREDIENT", "NONE"
    prompt_snippet: str

# First Frame Composition (из GEN2)
class FirstFrameComposition(BaseModel):
    hero_subject: str
    hero_position: str  # "upper_center", "center_left", etc.
    foreground_element: str
    background_depth: str
    lighting_direction: str
    hook_element: str
    safe_zone_compliance: bool

# Easter Egg (обновленная)
class EasterEgg(BaseModel):
    object: str
    scene_number: int
    safe_zone_position: str  # NOT "bottom_center"!
    visibility_score: float  # 0.0-1.0
```

**Обновить GlazeCityProject:**

```python
class GlazeCityProject(BaseModel):
    # Existing fields...

    # NEW v7.4 fields
    architectural_identity: ArchitecturalIdentity
    food_identity: FoodIdentity
    lighting_master: LightingMaster
    foreground_element: ForegroundElement
    atmosphere_mode: str  # "CINEMATIC", "VIBRANT", "PLAYFUL"
    hook_matrix: HookMatrix
```

### 1.2 gen_models.py — GEN1/GEN2 v3.0 Contract

**Файл:** `app/services/gen_models.py`

**Обновить Gen1Output:**

```python
class Gen1Output(BaseModel):
    metadata: Gen1Metadata
    property: Gen1Property
    hook: Gen1Hook
    architectural_identity: Gen1ArchitecturalIdentity  # REQUIRED
    food_identity: Gen1FoodIdentity  # REQUIRED
    lighting_master: Gen1LightingMaster  # REQUIRED
    foreground_element: Gen1ForegroundElement  # REQUIRED
    scenes: List[Gen1SceneConcept]  # EXACTLY 6
    voiceover: Gen1VoiceoverConfig
    audio: Gen1AudioConfig
    engagement: Gen1Engagement
```

**Добавить Gen3a/Gen3b модели:**

```python
# GEN3a Output (Video Analysis)
class Gen3aSceneAnalysis(BaseModel):
    scene_number: int
    video_quality: float
    glitches: List[GlitchDetection]
    action_peaks: List[ActionPeak]
    dead_spots: List[DeadSpot]
    speed_map: List[SpeedSegment]
    visual_classification: VisualClassification
    easter_egg_verification: Optional[EasterEggVerification]

class Gen3aOutput(BaseModel):
    analysis_metadata: AnalysisMetadata
    scenes: List[Gen3aSceneAnalysis]
    music_analysis: MusicAnalysis
    vo_analysis: VOAnalysis
    hook_variety_analysis: HookVarietyAnalysis
    gen3b_handoff: Gen3bHandoff

# GEN3b Output (FFmpeg Manifest)
class ManifestScene(BaseModel):
    scene_number: int
    source_file: str
    timeline_start: float
    timeline_end: float
    speed_segments: List[SpeedSegment]
    effects: List[Effect]
    cut_segments: List[CutSegment]

class Manifest(BaseModel):
    version: str  # "1.3.1"
    total_duration: float
    hook_style: str  # "CLASSIC", "IMPACT", etc.
    scenes: List[ManifestScene]
    audio_layers: AudioLayers
    subtitles: List[Subtitle]
    effects_global: List[GlobalEffect]
```

---

## Часть 2: Новые сервисы

### 2.1 GEN3aService — Video Analyst

**Файл:** `app/services/gen3a_service.py`

```python
class Gen3aService:
    """
    GEN3a - Video Analyst v1.3.1

    Analyzes 6 raw Kling videos and produces:
    - Glitch detection with timestamps
    - Action peaks and dead spots
    - Speed map recommendations
    - Easter egg verification
    - Visual type classification
    - VO sync analysis
    """

    def __init__(self):
        self.prompt = load_prompt("GEN3a.txt")
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    async def analyze_videos(
        self,
        video_paths: List[Path],
        gen1_brief: dict,
        gen2_brief: dict,
        music_beat_data: dict,
        voiceover_path: Path,
    ) -> Gen3aOutput:
        """
        Analyze all 6 videos using Gemini Vision.

        Input: 6 videos (1.mp4-6.mp4), gen1_brief, gen2_brief, music beats, VO
        Output: Gen3aOutput with analysis for each scene
        """
        pass
```

### 2.2 GEN3bService — FFmpeg Manifest Generator

**Файл:** `app/services/gen3b_service.py`

```python
class Gen3bService:
    """
    GEN3b - The Artist v1.3.1

    Transforms GEN3a analysis into production-ready manifest.json
    """

    def __init__(self):
        self.prompt = load_prompt("GEN3b.txt")
        self.client = genai.Client(api_key=settings.GOOGLE_GEMINI_API_KEY)

    async def generate_manifest(
        self,
        gen3a_analysis: Gen3aOutput,
        gen1_brief: dict,
        gen2_brief: dict,
    ) -> Manifest:
        """
        Generate FFmpeg manifest from GEN3a analysis.

        Output: manifest.json ready for FFmpeg rendering
        """
        pass
```

### 2.3 BeatAnalyzer — Librosa Integration

**Файл:** `app/services/beat_analyzer.py`

```python
class BeatAnalyzer:
    """
    Analyzes music for beat detection using librosa.

    Output: music_beat_data.json for GEN3a
    """

    async def analyze_music(self, music_path: Path) -> MusicBeatData:
        """
        Analyze music file for:
        - BPM detection
        - Beat timestamps
        - Strong/weak beat classification
        - Music sections (intro, build, drop, outro)
        """
        import librosa

        y, sr = librosa.load(str(music_path))
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        # Classify beat strength
        beats = []
        for i, t in enumerate(beat_times):
            strength = "STRONG" if i % 4 == 0 else ("MEDIUM" if i % 2 == 0 else "WEAK")
            beats.append({"timestamp": float(t), "strength": strength, "beat_number": (i % 4) + 1})

        return MusicBeatData(
            bpm=float(tempo),
            beats=beats,
            strong_beats_only=[b["timestamp"] for b in beats if b["strength"] == "STRONG"],
            # ... sections detection
        )
```

---

## Часть 3: Валидаторы

### 3.1 VAL_GEN3a

**Файл:** `app/services/validators/val_gen3a.py`

**Правила валидации:**
- speed_map покрывает 100% видео (без gaps)
- Сумма output_duration = target (25±0.5s)
- Scene 1 duration = Scene 6 duration (±0.1s для loop)
- Easter egg verified если scene_number указан
- visual_classification присутствует для всех сцен
- hook_variety_analysis присутствует

### 3.2 VAL_GEN3b

**Файл:** `app/services/validators/val_gen3b.py`

**Правила валидации:**
- manifest.json структурно валиден
- Все timestamps в правильном диапазоне
- 5 audio layers присутствуют
- Subtitles не в bottom 20% (Safe Zone)
- Effects matching visual_type (из GEN3a)
- Hook style из approved pool

### 3.3 Обновление VAL_IMG v3.0

**Файл:** `app/services/image_validator.py`

**Новые проверки:**
- Gigantism Protocol (no miniature/toy effect)
- Safe Zone compliance (subject in upper 60%)
- Foreground element presence (Scene 1)
- Architectural consistency (REQUIRES_REF scenes)
- Food DNA adherence

---

## Часть 4: Audio Engine 5-Layer System

### 4.1 Обновление AudioEngine

**Файл:** `app/services/audio_engine.py`

**Новая структура:**

```python
class AudioLayer(Enum):
    BED = "bed"        # Ambient bed (looped, -20dB)
    MUSIC = "music"    # Background music from SUNO
    SFX = "sfx"        # Impact sounds, transitions
    FOLEY = "foley"    # Food sounds (sizzle, crunch, etc.)
    VO = "vo"          # Voiceover (priority)

class MultiLayerAudioEngine:
    """
    5-layer audio system for Glaze City videos.

    Layers (bottom to top):
    1. BED - Ambient (always playing, ducked during VO)
    2. MUSIC - SUNO-generated music (ducked during VO)
    3. SFX - Impact sounds synced to transitions
    4. FOLEY - Food-specific sounds
    5. VO - Voiceover (highest priority)

    Features:
    - Auto-ducking (BED/MUSIC duck 40% during VO)
    - Beat-synced SFX placement
    - ElevenLabs SFX generation
    """

    async def generate_full_audio(
        self,
        manifest: Manifest,
        project_dir: Path,
    ) -> Path:
        """
        Generate all audio layers and mix them.

        1. Generate VO from voiceover.full_script
        2. Generate/load BED ambient
        3. Generate MUSIC from SUNO prompt (or use provided)
        4. Generate SFX from manifest.audio_layers.sfx
        5. Generate FOLEY from manifest.audio_layers.foley
        6. Mix with ducking and export final_audio.mp3
        """
        pass
```

### 4.2 ElevenLabs SFX Integration

**Новые методы:**

```python
async def generate_sfx(self, sfx_prompt: str) -> bytes:
    """Generate sound effect using ElevenLabs Sound Effects API"""
    pass

async def generate_foley(self, foley_type: str) -> bytes:
    """Generate food foley sound"""
    # Types: "sizzle", "crunch", "pour_thick", "drip", etc.
    pass
```

---

## Часть 5: Video Assembler с Manifest

### 5.1 ManifestRenderer

**Файл:** `app/services/manifest_renderer.py`

```python
class ManifestRenderer:
    """
    Renders final video from manifest.json using FFmpeg.

    Processes:
    - Speed segments (setpts filter)
    - Cut segments (trim filter)
    - Effects (zoompan, shake, rgb_split, etc.)
    - Subtitles (drawtext with style animations)
    - Audio layers (amix with ducking)
    """

    async def render(
        self,
        manifest: Manifest,
        project_dir: Path,
        output_path: Path,
    ) -> Path:
        """
        Execute full render pipeline.

        1. Process each scene with speed_segments and effects
        2. Apply cuts (remove glitch frames)
        3. Concatenate scenes
        4. Add subtitles with animations
        5. Mix audio layers
        6. Export final.mp4
        """
        pass

    def _build_scene_filter(self, scene: ManifestScene) -> str:
        """Build FFmpeg filter chain for single scene"""
        pass

    def _build_subtitle_filter(self, subtitles: List[Subtitle]) -> str:
        """Build drawtext filter with style animations"""
        pass

    def _build_audio_mix(self, audio_layers: AudioLayers) -> str:
        """Build amix filter with ducking"""
        pass
```

---

## Часть 6: Pipeline Stages

### 6.1 AnalysisStage (NEW)

**Файл:** `app/pipeline/analysis_stage.py`

```python
class AnalysisStage(BasePipelineStage):
    """
    Stage 5: Video Analysis (GEN3a)

    Analyzes all generated videos using GEN3a.
    Produces gen3a_analysis.json for GEN3b.
    """

    name = "video_analysis"
    description = "Analyze videos via GEN3a"

    async def execute(self) -> StageResult:
        # 1. Load gen1_brief, gen2_brief
        # 2. Analyze music for beats
        # 3. Run GEN3a analysis
        # 4. Validate with VAL_GEN3a
        # 5. Save gen3a_analysis.json
        pass
```

### 6.2 ManifestStage (NEW)

**Файл:** `app/pipeline/manifest_stage.py`

```python
class ManifestStage(BasePipelineStage):
    """
    Stage 6: Manifest Generation (GEN3b)

    Generates FFmpeg manifest from GEN3a analysis.
    """

    name = "manifest_generation"
    description = "Generate FFmpeg manifest via GEN3b"

    async def execute(self) -> StageResult:
        # 1. Load gen3a_analysis.json
        # 2. Run GEN3b generation
        # 3. Validate with VAL_GEN3b
        # 4. Save manifest.json
        pass
```

### 6.3 Обновление PostProcessStage

**Файл:** `app/pipeline/postprocess_stage.py`

```python
async def execute(self) -> StageResult:
    # NEW FLOW:
    # 1. Load manifest.json
    # 2. Generate 5-layer audio (AudioEngine)
    # 3. Render video with ManifestRenderer
    # 4. Optional Topaz enhancement
    # 5. Generate thumbnail
    pass
```

---

## Часть 7: Orchestrator Update

### 7.1 Новый Pipeline Flow

**Файл:** `app/pipeline/orchestrator.py`

```python
PIPELINE_STAGES = [
    ScriptStage,      # GEN1 + GEN2
    ImageStage,       # Image generation
    ValidationStage,  # VAL_IMG
    VideoStage,       # Kling video gen
    AnalysisStage,    # GEN3a (NEW)
    ManifestStage,    # GEN3b (NEW)
    PostProcessStage, # Final assembly
]
```

---

## Часть 8: Зависимости

### 8.1 Новые Python packages

```txt
# requirements.txt additions
librosa>=0.10.0      # Beat analysis
aubio>=0.4.9         # Alternative beat detection
soundfile>=0.12.0    # Audio file handling
pydub>=0.25.0        # Audio manipulation
```

### 8.2 External Services

- **SUNO API** (опционально) — для генерации музыки по промпту
- **ElevenLabs SFX API** — для генерации SFX
- **Librosa** — для анализа битов

---

## Порядок реализации

### Фаза 1: Data Models (Приоритет: ВЫСОКИЙ)
1. Обновить `glaze_models.py` — добавить v7.4 поля
2. Обновить `gen_models.py` — GEN3a/GEN3b модели
3. Обновить `validation_models.py` — VAL_GEN3a/VAL_GEN3b response models

### Фаза 2: Core Services (Приоритет: ВЫСОКИЙ)
4. Создать `gen3a_service.py`
5. Создать `gen3b_service.py`
6. Создать `beat_analyzer.py`
7. Создать `manifest_renderer.py`

### Фаза 3: Validators (Приоритет: СРЕДНИЙ)
8. Создать `validators/val_gen3a.py`
9. Создать `validators/val_gen3b.py`
10. Обновить `image_validator.py` для VAL_IMG v3.0

### Фаза 4: Audio System (Приоритет: СРЕДНИЙ)
11. Обновить `audio_engine.py` — 5-layer system
12. Добавить ElevenLabs SFX integration
13. Добавить audio ducking

### Фаза 5: Pipeline Integration (Приоритет: ВЫСОКИЙ)
14. Создать `analysis_stage.py`
15. Создать `manifest_stage.py`
16. Обновить `postprocess_stage.py`
17. Обновить `orchestrator.py`

### Фаза 6: Testing
18. Unit tests для каждого сервиса
19. Integration test полного пайплайна
20. E2E test с реальными данными

---

## Ожидаемые результаты

После полной реализации:

1. **GEN1 v3.0** генерирует полный creative brief с:
   - architectural_identity
   - food_identity с food_dna
   - lighting_master
   - foreground_element
   - hook matrix

2. **GEN2 v3.0** генерирует visual prompts с:
   - Gigantism Protocol
   - Safe Zone compliance
   - First frame composition
   - Loop engineering (Scene 1 ↔ Scene 6)

3. **GEN3a v1.3.1** анализирует видео:
   - Glitch detection
   - Speed map
   - Visual classification
   - Easter egg verification
   - Beat-aligned cuts

4. **GEN3b v1.3.1** генерирует manifest.json:
   - Hook variety system
   - Content-aware effects
   - Subtitle styles
   - 5-layer audio plan

5. **PostProcess** рендерит финальное видео:
   - FFmpeg с manifest.json
   - 5-layer audio mix
   - Subtitles с анимациями
   - 9:16 vertical format

---

## Важные заметки

### Loop Engineering
- Scene 1 duration MUST = Scene 6 duration (±0.1s)
- Scene 6 = Scene 1 reversed (camera movement)
- Seamless loop для повторного просмотра

### Safe Zone
- Subject в верхних 60% кадра
- Subtitles NEVER в bottom 20%
- Easter egg NEVER в bottom-center

### Gigantism Protocol
- Архитектура должна выглядеть МАССИВНОЙ
- Использовать human figures для масштаба
- Запрещены слова: miniature, toy, small, cute, tiny

### Hook Variety
- НИКОГДА не использовать один стиль подряд
- 5 стилей: CLASSIC, IMPACT, GLITCH, ELEGANT, DRAMATIC
- GEN3a рекомендует, GEN3b выбирает

---

*План создан: 2026-01-13*
*Версия пайплайна: v7.4*
*Версия GEN3a/GEN3b: v1.3.1*
