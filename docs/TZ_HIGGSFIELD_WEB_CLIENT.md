# ТЗ: HiggsFieldWebClient - Інтеграція через AdsPower

> **Дата:** 2024-12-30
> **Статус:** Дослідження завершено, готово до розробки
> **Пріоритет:** Високий (економія на API credits)

---

## Мета

Замінити платний Higgsfield Cloud API (`platform.higgsfield.ai`) на автоматизацію веб-інтерфейсу (`higgsfield.ai`) через AdsPower антидетект браузер. Це дозволить використовувати **Ultimate підписку** (безлімітну) замість pay-per-use API.

---

## Досліджено та підтверджено

### AdsPower API
```
API Key: 8005e976e2e12496de5fad777e96e0cd
Base URL: http://local.adspower.net:50325
Profile ID: k18ewu4m
```

### Selenium підключення
```python
# Отримання connection details
resp = requests.get(f'{BASE_URL}/api/v1/browser/start?user_id={PROFILE_ID}')
data = resp.json()

SELENIUM_ADDR = data['data']['ws']['selenium']  # 127.0.0.1:PORT
WEBDRIVER_PATH = data['data']['webdriver']       # chromedriver.exe path

# Підключення
chrome_options = Options()
chrome_options.add_experimental_option('debuggerAddress', SELENIUM_ADDR)
service = Service(executable_path=WEBDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=chrome_options)
```

### Higgsfield URLs
- Image generation: `https://higgsfield.ai/image/nano_banana_2`
- Video generation: `https://higgsfield.ai/create/video`

---

## Налаштування (ФІНАЛЬНІ)

### IMAGE - Nano Banana Pro
| Параметр | Значення | Селектор |
|----------|----------|----------|
| Model | Nano Banana Pro | URL contains `/nano_banana` |
| Aspect Ratio | **9:16** | `button` з текстом aspect ratio → `[role="option"]` |
| Resolution | **2K** | `button` з текстом resolution → `[role="option"]` |
| Unlimited | ON/OFF (toggle) | `//div[text()='Unlimited']/..//[role="switch"]` |

### VIDEO - Kling 2.6
| Параметр | Значення | Селектор |
|----------|----------|----------|
| Model | **Kling 2.6** | `button` "Model..." → click on `p` with "Kling 2.6" |
| Duration | **10s** | `button` "Duration..." → `[role="option"]` |
| Aspect Ratio | **9:16** | `button` "Aspect..." → `[role="option"]` |
| Mode/Preset | **GENERAL** | Вбудовано в Kling 2.6 |
| Resolution | **1080p** | Вбудовано в Kling 2.6 |

---

## Workflow

### Phase 1: PRIMARY Scene (Scene 1)

```
1. Відкрити Image tab
2. Встановити: 9:16, 2K, Unlimited=OFF
3. Ввести prompt в textarea
4. Натиснути Generate (button[type="submit"])
5. Дочекатися генерації 4 candidates
6. Завантажити всі 4 зображення
7. Надіслати в Telegram для вибору
8. Користувач обирає 1 → зберегти як REFERENCE
```

### Phase 2: Secondary Scenes (Scenes 2-N)

```
1. Відкрити Image tab
2. Встановити: 9:16, 2K, Unlimited=ON
3. Завантажити REFERENCE зображення (якщо є така опція)
4. Ввести prompt
5. Generate → 1 зображення
6. Завантажити результат
```

### Phase 3: Video Generation (для кожної сцени)

```
1. Відкрити Video tab
2. Встановити: Kling 2.6, 10s, 9:16
3. Завантажити зображення сцени як start frame
4. Ввести motion prompt
5. Generate
6. Дочекатися генерації (~2-5 хв)
7. Завантажити відео
```

---

## DOM Елементи (знайдені)

### Image Page

```python
# Prompt textarea
textarea = driver.find_element(By.TAG_NAME, 'textarea')
# placeholder="Describe the scene you imagine"

# Generate button
generate_btn = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
# text: "Generate\n{credits}"

# Settings buttons (aspect, resolution)
buttons = driver.find_elements(By.TAG_NAME, 'button')
# Фільтрувати по тексту: '9:16', '2K', etc.

# Unlimited toggle
switch = driver.find_element(By.XPATH, "//div[text()='Unlimited']/..//*[@role='switch']")
# aria-checked="true" / "false"
```

### Video Page

```python
# Model selector
model_btn = # button з текстом "Model Kling..."

# Duration, Aspect selectors
# Аналогічно до Image

# Start frame upload
# TODO: Дослідити як завантажити зображення
```

---

## Архітектура клієнта

### Файл: `app/clients/higgsfield_web.py`

```python
class HiggsFieldWebClient:
    """
    Higgsfield через AdsPower браузер.
    Використовує Ultimate підписку замість API credits.
    """

    def __init__(
        self,
        adspower_api_key: str,
        adspower_profile_id: str,
        adspower_base_url: str = "http://local.adspower.net:50325"
    ):
        self.api_key = adspower_api_key
        self.profile_id = adspower_profile_id
        self.base_url = adspower_base_url
        self.driver: Optional[webdriver.Chrome] = None

    async def start_browser(self) -> None:
        """Запустити AdsPower профіль і підключити Selenium"""
        ...

    async def close_browser(self) -> None:
        """Закрити браузер"""
        ...

    async def generate_primary_candidates(
        self,
        prompt: str,
        num_candidates: int = 4
    ) -> List[Path]:
        """
        Генерація 4 candidates для PRIMARY сцени.
        Unlimited=OFF (використовує кредити).
        """
        ...

    async def generate_scene_image(
        self,
        prompt: str,
        reference_image: Optional[Path] = None
    ) -> Path:
        """
        Генерація зображення для сцени.
        Unlimited=ON (безкоштовно).
        """
        ...

    async def generate_video(
        self,
        image_path: Path,
        motion_prompt: str,
        duration: int = 10
    ) -> Path:
        """
        Генерація відео з зображення.
        Kling 2.6, GENERAL, 1080p.
        """
        ...

    # Private methods
    async def _navigate_to_image(self) -> None: ...
    async def _navigate_to_video(self) -> None: ...
    async def _set_aspect_ratio(self, ratio: str) -> None: ...
    async def _set_resolution(self, res: str) -> None: ...
    async def _set_unlimited(self, enabled: bool) -> None: ...
    async def _set_video_model(self, model: str) -> None: ...
    async def _set_video_duration(self, seconds: int) -> None: ...
    async def _upload_image(self, path: Path) -> None: ...
    async def _download_result(self, output_path: Path) -> Path: ...
    async def _wait_for_generation(self, timeout: int = 300) -> None: ...
```

---

## Конфігурація (.env)

```env
# AdsPower
ADSPOWER_API_KEY=8005e976e2e12496de5fad777e96e0cd
ADSPOWER_BASE_URL=http://local.adspower.net:50325
ADSPOWER_PROFILE_ID=k18ewu4m

# Higgsfield Web Settings
HIGGSFIELD_WEB_ASPECT_RATIO=9:16
HIGGSFIELD_WEB_IMAGE_RESOLUTION=2K
HIGGSFIELD_WEB_VIDEO_MODEL=Kling 2.6
HIGGSFIELD_WEB_VIDEO_DURATION=10
HIGGSFIELD_WEB_VIDEO_RESOLUTION=1080p
```

---

## TODO для наступної сесії

1. [ ] Створити `app/clients/higgsfield_web.py`
2. [ ] Імплементувати базові методи (start/close browser)
3. [ ] Імплементувати навігацію між табами
4. [ ] Імплементувати зміну налаштувань
5. [ ] Імплементувати `generate_primary_candidates()`
6. [ ] Дослідити як завантажити reference image
7. [ ] Імплементувати `generate_scene_image()`
8. [ ] Дослідити як завантажити start frame для video
9. [ ] Імплементувати `generate_video()`
10. [ ] Імплементувати очікування результату та download
11. [ ] Додати error handling та retry logic
12. [ ] Інтегрувати з orchestrator.py
13. [ ] Написати тести

---

## Відкриті питання

1. **Reference Image**: Як саме завантажити reference зображення для наступних сцен? Потрібно дослідити UI.

2. **Video Start Frame**: Як завантажити зображення як початковий кадр для відео? Потрібно дослідити UI.

3. **Download Results**: Як завантажити згенеровані зображення/відео? Можливо через:
   - Правий клік → Save as
   - Пошук URL в DOM/Network
   - Drag & drop з браузера

4. **Rate Limiting**: AdsPower має ліміт 1 req/sec на API. Враховувати при polling.

5. **Generation Queue**: Як відслідковувати прогрес генерації? Потрібно знайти індикатор.

---

## Залежності

```
selenium>=4.18.0
requests>=2.31.0
```

Вже встановлені в проекті.

---

## Контакти

При питаннях - читати цей документ та `config/PROJECT_STRUCTURE.md`.
