# Технічне завдання: YTAutoPublisher v1.2

## Модуль автоматичної публікації відео на YouTube

**Версія:** 1.2
**Дата:** 2025-01-25

---

## 1. Загальний опис

### 1.1 Призначення
Модуль автоматичної публікації готових відео на YouTube канали. Фінальний етап Glaze City pipeline.

### 1.2 Що робить модуль
- Читає `project_brief.json` (вже містить title, description, pinned_comment)
- Очищує метадані відео через FFmpeg
- Завантажує відео на YouTube через API
- Додає pinned comment
- Переміщує проект в archive
- Логує всі операції

### 1.3 Архітектура
```
[Готовий проект] → [YTAutoPublisher] → [YouTube] → [Archive]
```

Один софт обробляє канали послідовно: завершив канал А → перейшов до каналу Б.

---

## 2. Як працює OAuth (ВАЖЛИВО ЗРОЗУМІТИ)

### 2.1 Що таке OAuth простими словами

```
OAuth — це спосіб дати програмі доступ до твого YouTube без пароля.

Замість пароля ти отримуєш "ключі":
- client_id + client_secret — ідентифікатор твоєї програми (отримуєш в Google Console)
- refresh_token — довгостроковий ключ доступу до каналу (отримуєш ОДИН РАЗ)
- access_token — короткостроковий ключ (програма отримує автоматично)
```

### 2.2 Що робиш ОДИН РАЗ (вручну, через ADS Power)

```
Крок 1: Google Cloud Console (через ADS Power браузер!)
        ↓
        Створюєш проект → Вмикаєш YouTube API → Створюєш credentials
        ↓
        Завантажуєш client_secrets.json

Крок 2: Запускаєш скрипт авторизації
        ↓
        Відкривається браузер (в ADS Power) → Логінишся в YouTube
        ↓
        Натискаєш "Дозволити"
        ↓
        Скрипт отримує refresh_token → Зберігає в config

Всього 10-15 хвилин на канал. Робиш один раз.
```

### 2.3 Що відбувається АВТОМАТИЧНО (кожна публікація)

```
Скрипт читає збережений refresh_token
        ↓
Запитує у Google новий access_token (через proxy!)
        ↓
Завантажує відео
        ↓
Додає коментар

Браузер НЕ ПОТРІБЕН. ADS Power НЕ ПОТРІБЕН. Все через API.
```

### 2.4 Чому це безпечно

- Google бачить USA IP (через proxy) при кожному API запиті
- refresh_token живе місяці/роки (поки не відкличеш доступ)
- Якщо token протух — скрипт автоматично оновить через refresh_token

---

## 3. Файлова структура

```
YTAuto-main/
├── config/
│   ├── global_settings.json          # Глобальні налаштування
│   ├── channels/
│   │   ├── channel_001/
│   │   │   ├── config.json           # Налаштування каналу (proxy, etc.)
│   │   │   ├── client_secrets.json   # Від Google (НЕ КОМІТИТИ)
│   │   │   └── token.json            # refresh_token (НЕ КОМІТИТИ)
│   │   └── channel_002/
│   │       └── ...
│   └── .encryption_key               # Master key (НЕ КОМІТИТИ)
│
├── projects/
│   └── {project_name}/
│       ├── project_brief.json        # Бриф з GEN3 (твій формат)
│       ├── upscaled/
│       │   └── final_video.mp4       # Готове відео
│       └── publish_status.json       # Статус публікації
│
├── archive/                          # Опубліковані проекти
│   └── {project_name}/
│
├── logs/
│   ├── publish_history.jsonl         # Історія публікацій
│   └── errors.log
│
├── src/
│   ├── main.py                       # Entry point (CLI)
│   ├── publisher.py                  # Основна логіка
│   ├── youtube_api.py                # YouTube API wrapper
│   ├── metadata_cleaner.py           # FFmpeg очищення
│   ├── config_manager.py             # Робота з конфігами
│   ├── auth_setup.py                 # Перша авторизація (вручну)
│   ├── scheduler.py                  # Заглушка для розкладу
│   ├── logger.py                     # Логування
│   └── models.py                     # Pydantic моделі
│
├── requirements.txt
└── README.md
```

---

## 4. Вхідні дані

### 4.1 project_brief.json (твій існуючий формат + publish_config)

Модуль читає секції `youtube` та `publish_config`:

```json
{
  "youtube": {
    "title": "This fire station is made of chili peppers 🌶️🔥",
    "description": "Station No. 5: The only fire station that starts fires...\n\n#foodart #spicy #shorts",
    "pinned_comment": "🥛 Only one thing can put out this fire... spot the cure? 👇",
    "tags": ["glaze city", "chili peppers", "fire station", "ai art"],
    "hashtags": ["#spicy", "#glazecity", "#chili"]
  },
  
  "publish_config": {
    "target_channel": "channel_001",
    "scheduled_datetime": null,
    "privacy_status": "public"
  },
  
  "project_id": "proj_b99d6de73b2b",
  "_meta": {
    "created_at": "2026-01-24T07:09:09.013474"
  }
}
```

**Поля publish_config:**

| Поле | Тип | Опис |
|------|-----|------|
| `target_channel` | string | ID каналу з config/channels/ (обов'язкове) |
| `scheduled_datetime` | string \| null | ISO datetime для scheduled publish, `null` = одразу |
| `privacy_status` | string | `"public"`, `"private"`, або `"unlisted"` |

### 4.2 publish_status.json (створюється автоматично)

```json
{
  "status": "published",
  "video_id": "dQw4w9WgXcQ",
  "video_url": "https://youtube.com/shorts/dQw4w9WgXcQ",
  "comment_id": "UgzXYZ123",
  "published_at": "2025-01-25T15:30:00Z",
  "channel_id": "channel_001",
  "attempts": 1,
  "error": null
}
```

Можливі статуси:
- `pending` — готовий до публікації
- `uploading` — завантажується
- `published` — опубліковано
- `scheduled` — заплановано на дату
- `failed` — помилка (див. `error`)

---

## 5. Конфігурація каналу

### 5.1 config/channels/channel_001/config.json

```json
{
  "channel_id": "channel_001",
  "channel_name": "Glaze City USA",
  "youtube_channel_id": "UCxxxxxxxxxx",
  "region": "US",
  "timezone": "America/New_York",
  
  "proxy": {
    "enabled": true,
    "host": "us.residential-proxy.com",
    "port": 10001,
    "username": "user123",
    "password": "pass456"
  },
  
  "settings": {
    "active": true,
    "default_privacy": "public",
    "default_category_id": "22",
    "made_for_kids": false
  }
}
```

### 5.2 client_secrets.json (від Google)

```json
{
  "installed": {
    "client_id": "123456789.apps.googleusercontent.com",
    "client_secret": "GOCSPX-xxxxx",
    "redirect_uris": ["http://localhost"]
  }
}
```

### 5.3 token.json (генерується при авторизації)

```json
{
  "token": "ya29.xxxxx",
  "refresh_token": "1//xxxxx",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxxxx",
  "scopes": ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"],
  "expiry": "2025-01-25T16:30:00Z"
}
```

---

## 6. Глобальні налаштування

### config/global_settings.json

```json
{
  "version": "1.0",
  
  "paths": {
    "projects_dir": "projects",
    "archive_dir": "archive",
    "logs_dir": "logs"
  },
  
  "ffmpeg": {
    "path": "ffmpeg",
    "clean_metadata": true
  },
  
  "upload": {
    "default_category_id": "22",
    "default_privacy": "public",
    "made_for_kids": false,
    "retry_attempts": 3,
    "retry_delay_seconds": 30
  },
  
  "scheduler": {
    "enabled": false
  },
  
  "post_publish": {
    "move_to_archive": true,
    "delete_clean_video": true
  },
  
  "logging": {
    "level": "INFO"
  }
}
```

---

## 7. CLI команди

```bash
# Ініціалізація (один раз)
python -m src.main init

# Додати канал (інтерактивно, відкриє браузер для OAuth)
python -m src.main channel add channel_001

# Тест з'єднання з каналом
python -m src.main channel test channel_001

# Список каналів
python -m src.main channel list

# Публікація проекту
python -m src.main publish proj_b99d6de73b2b

# Публікація проекту (dry run — без реального завантаження)
python -m src.main publish proj_b99d6de73b2b --dry-run

# Публікація всіх готових проектів
python -m src.main publish-all

# Історія публікацій
python -m src.main history --days 7

# Статус проекту
python -m src.main status proj_b99d6de73b2b
```

---

## 8. Алгоритм публікації

```
1. Знайти проект в projects/{project_name}/
2. Прочитати project_brief.json
3. Перевірити publish_status.json (якщо вже published — пропустити)
4. Валідувати publish_config:
   - target_channel існує в config/channels/
   - scheduled_datetime валідний або null
5. Знайти відео в upscaled/ (*.mp4)
6. Очистити метадані (ffmpeg -map_metadata -1)
7. Завантажити конфіг каналу (publish_config.target_channel)
8. Підключитися до YouTube API через proxy каналу
9. Завантажити відео з metadata:
   - title: youtube.title
   - description: youtube.description
   - tags: youtube.tags
   - category: 22 (People & Blogs)
   - privacy: publish_config.privacy_status
   - scheduled: publish_config.scheduled_datetime (якщо не null)
10. Додати pinned comment: youtube.pinned_comment
11. Оновити publish_status.json
12. Записати в publish_history.jsonl
13. Перемістити проект в archive/
```

---

## 9. Обробка помилок

| Помилка | Дія |
|---------|-----|
| Відео не знайдено | Лог помилки, статус = failed |
| Brief невалідний | Лог помилки, статус = failed |
| Network timeout | Retry 3 рази з паузою 30 сек |
| OAuth token expired | Автоматичний refresh |
| Quota exceeded | Лог, пропустити до завтра |
| YouTube API 500 | Retry 3 рази |
| Proxy failed | Лог, позначити канал inactive |

---

## 10. Логування

### logs/publish_history.jsonl

```json
{"timestamp": "2025-01-25T15:30:00Z", "event": "upload_started", "project_id": "proj_b99d6de73b2b", "channel_id": "channel_001"}
{"timestamp": "2025-01-25T15:32:00Z", "event": "upload_completed", "project_id": "proj_b99d6de73b2b", "video_id": "dQw4w9WgXcQ"}
{"timestamp": "2025-01-25T15:32:05Z", "event": "comment_pinned", "video_id": "dQw4w9WgXcQ", "comment_id": "UgzXYZ"}
{"timestamp": "2025-01-25T15:32:10Z", "event": "archived", "project_id": "proj_b99d6de73b2b"}
```

---

## 11. ЧЕКЛИСТ: Що робити вручну

### 11.1 Один раз для всієї системи

| # | Дія | Деталі |
|---|-----|--------|
| 1 | Встановити Python 3.11+ | python.org |
| 2 | Встановити FFmpeg | `apt install ffmpeg` або ffmpeg.org |
| 3 | Клонувати репозиторій | `git clone ...` |
| 4 | Встановити залежності | `pip install -r requirements.txt` |
| 5 | Запустити ініціалізацію | `python -m src.main init` |
| 6 | Купити residential proxy | Smartproxy, IPRoyal, etc. |

### 11.2 Для кожного нового каналу (10-15 хв)

| # | Дія | Деталі |
|---|-----|--------|
| 1 | Відкрити ADS Power профіль | Профіль каналу з USA proxy |
| 2 | Зайти на console.cloud.google.com | Через ADS Power браузер! |
| 3 | Створити новий проект | Назва: "YT-Channel-001" |
| 4 | Увімкнути YouTube Data API v3 | APIs & Services → Enable |
| 5 | Створити OAuth credentials | Credentials → Create → OAuth client ID → Desktop app |
| 6 | Завантажити client_secrets.json | Зберегти в config/channels/channel_001/ |
| 7 | Запустити авторизацію | `python -m src.main channel add channel_001` |
| 8 | Пройти OAuth в браузері | Відкриється ADS Power, натиснути "Allow" |
| 9 | Ввести дані proxy | Інтерактивно в терміналі |
| 10 | Тест з'єднання | `python -m src.main channel test channel_001` |

### 11.3 Для кожного відео

| # | Дія |
|---|-----|
| - | АВТОМАТИЧНО |

---

## 12. Безпека — .gitignore

```gitignore
# Credentials (НІКОЛИ не комітити!)
config/channels/*/client_secrets.json
config/channels/*/token.json
config/.encryption_key

# Logs
logs/

# Projects (занадто великі)
projects/
archive/

# Python
__pycache__/
*.pyc
.env
venv/
```

---

## 13. Dependencies

### requirements.txt

```
# YouTube API
google-api-python-client>=2.100.0
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
google-auth-httplib2>=0.1.1

# Proxy support
httplib2>=0.22.0
PySocks>=1.7.1

# CLI
typer>=0.9.0
rich>=13.0.0

# Validation
pydantic>=2.5.0

# Utils
python-dateutil>=2.8.2

# Testing
pytest>=7.4.0
```

---

## 14. Фази розробки

### Phase 1: MVP (1 тиждень)
- [ ] Структура проекту
- [ ] config_manager.py
- [ ] metadata_cleaner.py (FFmpeg)
- [ ] youtube_api.py (upload + comment)
- [ ] auth_setup.py (OAuth flow)
- [ ] publisher.py
- [ ] CLI: init, channel add/test, publish
- [ ] Базове логування

### Phase 2: Стабілізація (3-5 днів)
- [ ] Повна обробка помилок
- [ ] Retry logic
- [ ] publish-all команда
- [ ] Архівування проектів
- [ ] Історія публікацій

### Phase 3: Multi-channel (майбутнє)
- [ ] Черга каналів
- [ ] Автовибір каналу

### Phase 4: Scheduler UI (майбутнє)
- [ ] Веб-інтерфейс для розкладу
- [ ] Інтеграція з існуючим browser control center

---

## 15. Приклад повного флоу

```bash
# === ПЕРШИЙ РАЗ (налаштування) ===

# 1. Ініціалізація
python -m src.main init
# Output: ✓ Created config directory
#         ✓ Created logs directory
#         ✓ System ready

# 2. Додаємо канал (відкриваємо ADS Power заздалегідь!)
python -m src.main channel add channel_usa_01

# > Enter YouTube channel ID: UCxxxxxxxxxx
# > Enter proxy host: us.smartproxy.com
# > Enter proxy port: 10001
# > Enter proxy username: user123
# > Enter proxy password: ****
# > 
# > Opening browser for OAuth...
# > [Браузер відкривається в ADS Power]
# > [Логінишся, натискаєш Allow]
# > 
# > ✓ Channel authorized successfully
# > ✓ Config saved to config/channels/channel_usa_01/

# 3. Тест
python -m src.main channel test channel_usa_01
# > Testing proxy connection... ✓
# > Testing OAuth token... ✓
# > Channel: Glaze City USA
# > Subscribers: 0
# > ✓ All tests passed


# === ЩОДЕННА РОБОТА (автоматично) ===

# Публікація конкретного проекту
python -m src.main publish proj_b99d6de73b2b

# > Loading project brief...
# > Title: This fire station is made of chili peppers 🌶️🔥
# > 
# > Cleaning video metadata...
# > ✓ Metadata removed
# > 
# > Uploading to YouTube...
# > Progress: 10%... 50%... 100%
# > ✓ Video uploaded: dQw4w9WgXcQ
# > 
# > Adding pinned comment...
# > ✓ Comment pinned
# > 
# > Moving to archive...
# > ✓ Done
# > 
# > 🎉 Published: https://youtube.com/shorts/dQw4w9WgXcQ
```

---

## 16. Відкриті питання (вирішити пізніше)

1. **Scheduler UI** — веб-інтерфейс для масового планування (поки публікуємо одразу або через scheduled_datetime в brief)
2. **Thumbnail** — YouTube Shorts auto-generate, поки не потрібно
3. **Multi-channel queue** — як автоматично розподіляти відео між каналами?

---

## 17. Контакт

При питаннях під час розробки — звертатись до цього ТЗ. Зміни в архітектурі — спочатку оновити ТЗ.
