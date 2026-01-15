# 🎬 Edible House Automator

**AI Video Generation Pipeline для Windows**

Автоматизована система для створення відео через AI з асинхронною обробкою сцен, Gemini-валідацією та Telegram-контролем.

---

## 📊 Поточний стан: ЕТАП 1 ✅

**Статус:** Core Infrastructure завершено

### Що реалізовано:
- ✅ Структура проєкту
- ✅ ConfigManager (Pydantic Settings + multi-model support)
- ✅ Logger (loguru з rotation)
- ✅ FileManager (async file operations)
- ✅ StateManager (async SQLite)
- ✅ .env.example з усіма ключами
- ✅ setup.bat та run.bat для Windows
- ✅ Базовий main.py (entry point)

### Наступний етап:
📍 **ЕТАП 2:** Higgsfield API Client (див. `STEPS.txt`)

---

## 🚀 Швидкий старт

### 1. Вимоги
- **Windows 11**
- **Python 3.11+**
- **Topaz Video AI** (встановлений)
- **API ключі:**
  - Higgsfield AI
  - Google Gemini
  - Telegram Bot

### 2. Перший запуск

```batch
# 1. Запустити setup
setup.bat

# 2. Налаштувати .env
# Відкрий config\.env та додай свої API ключі

# 3. Запустити додаток
run.bat
```

### 3. Налаштування API ключів

Відкрий `config\.env` та заповни:

```env
# Higgsfield
HIGGSFIELD_API_KEY=your_key_here
HIGGSFIELD_API_SECRET=your_secret_here

# Gemini
GOOGLE_GEMINI_API_KEY=your_gemini_key_here

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

**Опціонально (для Claude):**
```env
ANTHROPIC_API_KEY=your_claude_key_here
CONTENTBRAIN_PROVIDER=claude
CONTENTBRAIN_MODEL=claude-3-5-sonnet-20241022
```

---

## 📁 Структура проєкту

```
YTAuto/
├── app/                          # Головний код
│   ├── core/
│   │   ├── config.py             # ✅ ConfigManager
│   │   └── state_manager.py     # ✅ SQLite persistence
│   ├── modules/
│   │   ├── content_brain.py      # ⏳ Етап 3
│   │   ├── visual_engine.py      # ⏳ Етап 2
│   │   ├── validator_gemini.py   # ⏳ Етап 3
│   │   ├── telegram_controller.py # ⏳ Етап 5
│   │   └── topaz_queue.py        # ⏳ Етап 6
│   ├── api/
│   │   └── routes.py             # ⏳ Етап 7
│   ├── web/
│   │   ├── static/
│   │   └── templates/            # ⏳ Етап 7
│   └── utils/
│       ├── logger.py             # ✅ Loguru
│       └── file_manager.py       # ✅ Async file ops
├── projects/                     # Генеровані відео
├── logs/                         # Логи (app.log, telegram.log, topaz.log)
├── data/                         # SQLite database
├── config/
│   ├── .env                      # API keys (створи вручну)
│   └── .env.example              # Шаблон
├── requirements.txt              # Python dependencies
├── setup.bat                     # Перший запуск
├── run.bat                       # Запуск додатку
├── main.py                       # Entry point
├── STEPS.txt                     # Поетапний план розробки
└── README.md                     # Ця документація
```

---

## ⚙️ Конфігурація

### Multi-Model Support

ContentBrain може використовувати **Gemini** (за замовчуванням) або **Claude**:

**Gemini (default):**
```env
CONTENTBRAIN_PROVIDER=gemini
CONTENTBRAIN_MODEL=gemini-1.5-pro
```

**Claude:**
```env
CONTENTBRAIN_PROVIDER=claude
CONTENTBRAIN_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_API_KEY=your_key
```

### Налаштування Topaz

Якщо Topaz встановлено в іншому місці:

```env
TOPAZ_FFMPEG_PATH=D:\Custom\Path\To\Topaz Video AI\ffmpeg.exe
```

### Додаткові параметри

Дивись `config/.env.example` для повного списку параметрів:
- Higgsfield models
- Processing limits
- Topaz upscaling settings
- Web UI port
- Logging configuration

---

## 🧪 Тестування Етапу 1

Після запуску `run.bat` ти побачиш:

```
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║   🎬  EDIBLE HOUSE AUTOMATOR  🎬                                      ║
║                                                                       ║
║   AI Video Generation Pipeline                                       ║
║   Version: 0.1.0 (ЕТАП 1: Core Infrastructure)                       ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝

[INFO] Starting system initialization...
[INFO] Checking configuration...
[SUCCESS] All directories ready
[SUCCESS] Database initialized
[SUCCESS] API keys configured
[SUCCESS] System initialization completed!

=============================================================================
ЕТАП 1: CORE INFRASTRUCTURE - ЗАВЕРШЕНО ✅
=============================================================================
```

### Перевірка компонентів:

**1. ConfigManager:**
```python
from app.core.config import settings
print(settings.BASE_DIR)
print(settings.HIGGSFIELD_API_KEY)  # Має бути заповнено
```

**2. Logger:**
Перевір файли в `logs/`:
- `app.log` - загальні логи
- Інші логи з'являться в наступних етапах

**3. StateManager:**
Перевір що створився `data/state.db`

---

## 📝 Логування

### Рівні логування

В `.env`:
```env
LOG_LEVEL=INFO  # DEBUG | INFO | WARNING | ERROR
```

### Файли логів

- `logs/app.log` - всі події додатку
- `logs/telegram.log` - Telegram bot (Етап 5)
- `logs/topaz.log` - Topaz queue (Етап 6)
- `logs/api.log` - API виклики (Етап 2-3)

Логи автоматично ротуються (10 MB per file, зберігаються 1 тиждень).

---

## 🔧 Troubleshooting

### Помилка: "Python not found"
- Встанови Python 3.11+ з [python.org](https://python.org)
- Додай Python до PATH при встановленні

### Помилка: "Virtual environment not found"
- Запусти `setup.bat` перед `run.bat`

### Помилка: "config\.env not found"
- Скопіюй `config\.env.example` → `config\.env`
- Заповни API ключі

### Warning: "Topaz FFmpeg not found"
- Встанови Topaz Video AI
- АБО оновити `TOPAZ_FFMPEG_PATH` в `.env`

### Помилка: "Missing required API keys"
- Переконайся що заповнив в `.env`:
  - `HIGGSFIELD_API_KEY` + `HIGGSFIELD_API_SECRET`
  - `GOOGLE_GEMINI_API_KEY`
  - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`

---

## 📚 Наступні кроки

### Етап 2: Higgsfield API Client

Дивись детальний план в `STEPS.txt`

Коротко:
1. Створити `app/modules/visual_engine.py`
2. Імплементувати `HiggsFieldClient`:
   - `generate_images()` - 4 зображення
   - `animate_image()` - відео з зображення
   - Async polling статусу
3. Створити тестовий скрипт

### Як продовжити розробку:

1. Прочитай `STEPS.txt` - там детальний план всіх етапів
2. Кожен етап - окремий завершений модуль
3. Тестуй кожен етап перед переходом до наступного
4. Коміть код після завершення кожного етапу

---

## 🎯 Критерії успіху Етапу 1

- ✅ `python main.py` запускається без помилок
- ✅ Створюються папки: `projects/`, `logs/`, `data/`
- ✅ `data/state.db` створюється автоматично
- ✅ `logs/app.log` містить логи ініціалізації
- ✅ ConfigManager завантажує `.env`
- ✅ Multi-model support працює (Gemini/Claude)
- ✅ `setup.bat` та `run.bat` працюють на чистій Windows машині

---

## 🛠️ Технічний стек

| Компонент | Технологія |
|-----------|------------|
| Python | 3.11+ |
| Async | asyncio (native) |
| Config | Pydantic Settings |
| Database | aiosqlite (SQLite) |
| Logging | loguru |
| HTTP Client | httpx (async) |
| File I/O | aiofiles |
| Web Framework | FastAPI (Етап 7) |
| Telegram Bot | aiogram 3.x (Етап 5) |
| AI Services | Higgsfield, Gemini, Claude |
| Video Processing | Topaz Video AI (FFmpeg) |

---

## 📞 Підтримка

Якщо виникли проблеми:

1. Перевір `logs/app.log` - там детальна інформація
2. Переконайся що всі API ключі правильні
3. Перевір що Python 3.11+ встановлено
4. Перевір що Topaz Video AI встановлено (для Етапу 6)

---

## 📜 Ліцензія

Internal project - Edible House

---

## 🚀 Roadmap

- [x] **Етап 1:** Core Infrastructure ✅
- [ ] **Етап 2:** Higgsfield API Client
- [ ] **Етап 3:** Gemini Validator + ContentBrain
- [ ] **Етап 4:** Orchestrator (Pipeline)
- [ ] **Етап 5:** Telegram Bot
- [ ] **Етап 6:** Topaz Queue
- [ ] **Етап 7:** Web UI + Integration

**Детальний план:** `STEPS.txt`

---

Made with ❤️ and AI by Claude Code
