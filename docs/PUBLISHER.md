# YouTube Publisher

Модуль автоматичної публікації відео на YouTube.

## Архітектура

```
src/publisher/
├── youtube_api.py      # YouTube Data API v3 з підтримкою проксі
├── publisher.py        # Головна логіка публікації
├── config_manager.py   # Управління каналами та проєктами
├── main.py             # CLI інтерфейс (typer)
├── models.py           # Pydantic моделі
├── scheduler.py        # Планування публікацій
└── metadata_cleaner.py # FFmpeg очистка метаданих
```

## Швидкий старт

### 1. Налаштування каналу

```bash
# Ініціалізація (створює директорії)
python -m src.publisher.main init

# Додати новий канал
python -m src.publisher.main channel add my_channel
```

### 2. OAuth авторизація

1. Завантажте `client_secrets.json` з [Google Cloud Console](https://console.cloud.google.com/)
2. Покладіть файл у `config/channels/{channel_id}/client_secrets.json`
3. Запустіть авторизацію:

```bash
python -m src.publisher.main channel auth my_channel
```

Браузер відкриється для OAuth flow. Після авторизації токен збережеться у `token.json`.

### 3. Публікація відео

```bash
# Перевірка підключення
python -m src.publisher.main channel test my_channel

# Одиночна публікація
python -m src.publisher.main publish proj_xxx

# Dry-run (без реальної загрузки)
python -m src.publisher.main publish proj_xxx --dry-run

# Публікація всіх pending проєктів
python -m src.publisher.main publish-all
```

## Конфігурація каналу

`config/channels/{channel_id}/config.json`:

```json
{
  "channel_id": "my_channel",
  "channel_name": "My Channel Name",
  "youtube_channel_id": "UCxxxxxx",
  "region": "US",
  "timezone": "America/New_York",
  "proxy": {
    "enabled": true,
    "host": "proxy.example.com",
    "port": 8080,
    "username": "user",
    "password": "pass"
  },
  "adspower_profile_id": "abc123",
  "settings": {
    "active": true,
    "default_privacy": "public",
    "default_category_id": "24",
    "made_for_kids": false
  }
}
```

## Project Brief

Для публікації проєкт повинен мати `project_brief.json` з секціями:

```json
{
  "publish_config": {
    "target_channel": "my_channel",
    "auto_schedule": false,
    "privacy_status": "public"
  },
  "youtube": {
    "title": "Video Title",
    "description": "Video description...",
    "tags": ["tag1", "tag2"],
    "pinned_comment": "First comment!"
  }
}
```

## Інтеграція з Pipeline

PublishStage - 11-й етап пайплайну:

```
1. ScriptStage       → Генерація сценарію
2. ImageStage        → Генерація зображень
3. ValidationStage   → Валідація
4. VideoStage        → Генерація відео
5. AudioStage        → Генерація аудіо
6. Gen3aStage        → Аналіз відео
7. Gen3bStage        → Генерація manifest
8. PostProcessStage  → FFmpeg рендеринг
9. VideoApprovalStage → Одобрення
10. CleanupStage      → Topaz upscale
11. PublishStage      → Публікація на YouTube
```

### Автоматична публікація

PublishStage автоматично:
- Пропускається якщо `target_channel` не вказано
- Завантажує `final_4k.mp4` або `final_video.mp4`
- Додає pinned comment (якщо AdsPower запущено)

## CLI Команди

### Управління каналами

```bash
# Список каналів
python -m src.publisher.main channel list

# Тест підключення
python -m src.publisher.main channel test {channel_id}

# Авторизація
python -m src.publisher.main channel auth {channel_id}

# Авторизація через AdsPower
python -m src.publisher.main channel auth {channel_id} --adspower {profile_id}
```

### Публікація

```bash
# Статус проєкту
python -m src.publisher.main status {project_id}

# Публікація
python -m src.publisher.main publish {project_id}

# Публікація без архівування
python -m src.publisher.main publish {project_id} --skip-archive

# Публікація всіх
python -m src.publisher.main publish-all --limit 5

# Список pending проєктів
python -m src.publisher.main pending

# Історія публікацій
python -m src.publisher.main history --days 7
```

### Resumable Uploads

```bash
# Список незавершених завантажень
python -m src.publisher.main uploads {channel_id}

# Відновити завантаження
python -m src.publisher.main resume {project_id} {channel_id}
```

### Pinned Comments

```bash
# Тест додавання коментаря
python -m src.publisher.main test-pin {video_id} {channel_id}

# Закріпити існуючий коментар
python -m src.publisher.main pin {video_id} {channel_id}
```

## Proxy Support

Publisher підтримує HTTP проксі для кожного каналу окремо:

```json
{
  "proxy": {
    "enabled": true,
    "host": "154.6.57.60",
    "port": 7528,
    "username": "user",
    "password": "pass"
  }
}
```

Проксі використовується для:
- YouTube API запитів
- OAuth token refresh
- Resumable uploads

## AdsPower Integration

Для pinned comments потрібен AdsPower:

1. Встановіть AdsPower
2. Створіть профіль браузера
3. Вкажіть `adspower_profile_id` у config.json
4. Запустіть AdsPower перед публікацією

```bash
# Тест pinned comment
python -m src.publisher.main test-pin VIDEO_ID CHANNEL_ID
```

## Troubleshooting

### "Invalid Credentials" при тесті

```bash
# Примусове оновлення токена
python -c "
from src.publisher.config_manager import get_config_manager
from src.publisher.youtube_api import YouTubeAPI
config = get_config_manager()
channel = config.load_channel_config('my_channel')
api = YouTubeAPI(channel, config.get_client_secrets_path('my_channel'), config.get_token_path('my_channel'))
api.authenticate(force_refresh=True)
"
```

### "AdsPower connection refused"

AdsPower не запущено. Запустіть AdsPower або використовуйте API-only публікацію (без pinned comment).

### "Quota exceeded"

YouTube API має денний ліміт (10,000 units). Завантаження відео = 1,600 units.
Максимум ~6 відео на день на один API project.

## Залежності

```bash
pip install typer rich loguru pydantic google-api-python-client google-auth-httplib2 google-auth-oauthlib selenium
```
