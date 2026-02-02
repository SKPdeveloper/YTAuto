"""
Higgsfield Selectors - Централізовані CSS/XPath селектори.
Всі селектори в одному місці для легкого оновлення при зміні UI.
"""

from dataclasses import dataclass
from typing import Optional


# ============================================================================
# URLs
# ============================================================================

HIGGSFIELD_IMAGE_URL = "https://higgsfield.ai/image/nano_banana_2"
HIGGSFIELD_VIDEO_URL = "https://higgsfield.ai/create/video"
HIGGSFIELD_LOGIN_URL = "https://higgsfield.ai/login"


# ============================================================================
# TIMEOUTS (seconds)
# ============================================================================

@dataclass(frozen=True)
class Timeouts:
    """Централізовані таймаути"""
    DEFAULT_WAIT: int = 10
    PAGE_LOAD: int = 30
    GENERATION: int = 300  # 5 хв для зображень
    VIDEO_GENERATION: int = 600  # 10 хв для відео
    IMAGE_UPLOAD: int = 300  # 5 min for reference upload to server
    IMAGE_UPLOAD_EXTRA: int = 15
    VIDEO_UPLOAD: int = 90  # Longer wait for server upload
    ADSPOWER_RATE_LIMIT: float = 1.1
    POLL_INTERVAL: int = 15
    MIN_VIDEO_WAIT: int = 30


TIMEOUTS = Timeouts()


# ============================================================================
# CSS SELECTORS
# ============================================================================

@dataclass(frozen=True)
class ImageSelectors:
    """Селектори для сторінки генерації зображень"""
    # Prompt
    PROMPT_TEXTAREA: str = 'textarea[name="prompt"]'
    PROMPT_TEXTAREA_ALT1: str = 'textarea.reference-prompt'
    PROMPT_TEXTAREA_ALT2: str = 'textarea[placeholder*="Describe"]'
    PROMPT_TEXTAREA_ALT3: str = 'textarea[placeholder*="scene"]'
    PROMPT_TEXTAREA_FALLBACK: str = 'textarea'

    # Reference image
    REFERENCE_INPUT: str = '#image-form-reference'
    REFERENCE_PREVIEW: str = 'img[data-asset-preview], .reference-preview img, [class*="reference"] img'

    # Settings
    UNLIMITED_SWITCH: str = 'button[role="switch"][data-state]'

    # Buttons - Primary Generate button has bg-primary class
    GENERATE_BUTTON: str = 'button.bg-primary'

    # Results
    GENERATED_IMAGE: str = 'img[src*="higgsfield"], img[src*="blob:"], img[data-asset-preview]'
    IMAGE_CONTAINER: str = '[class*="generated"], [class*="result"], [class*="gallery"]'

    # File inputs
    FILE_INPUT: str = 'input[type="file"][accept*="image"]'


IMAGE_SELECTORS = ImageSelectors()


@dataclass(frozen=True)
class VideoSelectors:
    """Селектори для сторінки генерації відео (Kling)"""
    # Prompt
    PROMPT_TEXTAREA: str = 'textarea#prompt'
    PROMPT_TEXTAREA_FALLBACK: str = 'textarea'

    # Start frame
    START_FRAME_INPUT: str = 'input[type="file"][accept*="image"]'
    START_FRAME_PREVIEW: str = 'img[data-asset-preview], .start-frame-preview img, [class*="frame"] img, [class*="upload"] img'

    # ========== MODEL SELECTION (Kling workflow) ==========
    # Step 1: Click "Change" button (pencil icon with SVG path M13.5479)
    CHANGE_MODEL_BUTTON_SVG_PATH: str = "M13.5479"

    # Step 2: Click "Kling" tab
    KLING_TAB_TEXT: str = "Kling"

    # Step 3: Click "General" preset
    GENERAL_PRESET_TEXT: str = "General"

    # ========== CLEAR START FRAME ==========
    # X button SVG path starts with M3.81344
    CLEAR_FRAME_SVG_PATH: str = "M3.81344"

    # ========== SETTINGS ==========
    # Aspect Ratio button (9:16 for vertical video)
    ASPECT_RATIO_BUTTON: str = 'button[aria-label="Aspect Ratio"]'
    ASPECT_RATIO_OPTION_9_16: str = '[role="option"][data-key="9:16"]'
    ASPECT_RATIO_OPTION_16_9: str = '[role="option"][data-key="16:9"]'
    ASPECT_RATIO_OPTION_1_1: str = '[role="option"][data-key="1:1"]'

    # Duration button
    DURATION_BUTTON: str = 'button[aria-label="Duration"]'
    DURATION_OPTION_10S: str = '[role="option"][data-key="10"]'
    DURATION_OPTION_5S: str = '[role="option"][data-key="5"]'

    # Audio toggle (should be OFF)
    AUDIO_TOGGLE: str = 'button[role="switch"][aria-label="Sound"]'

    # Dropdown options
    DROPDOWN_OPTION: str = '[role="option"], [role="menuitem"]'

    # ========== ACTIONS ==========
    # Primary Generate button - has bg-primary class with spark SVG icon
    GENERATE_BUTTON: str = 'button.bg-primary'
    DOWNLOAD_BUTTON: str = "//button[contains(text(), 'Download')] | //a[contains(text(), 'Download')]"

    # Results
    VIDEO_ELEMENT: str = 'video'
    VIDEO_SOURCE: str = 'video source[src]'


VIDEO_SELECTORS = VideoSelectors()


@dataclass(frozen=True)
class SeedanceSelectors:
    """Селектори для Seedance моделі відео"""
    # Change model button (кнопка з SVG іконкою редагування)
    CHANGE_MODEL_BUTTON: str = 'button'  # Шукаємо по тексту "Change"

    # Seedance model tab
    SEEDANCE_TAB: str = 'button'  # Шукаємо по тексту "Seedance 1.5 Pro"

    # Preset General button
    PRESET_GENERAL: str = 'button'  # Шукаємо по тексту "General"

    # Clear start frame X button (специфічний path для X іконки)
    CLEAR_FRAME_BUTTON_XPATH: str = (
        "//button[contains(@class, 'button-xxs') or contains(@class, 'rounded-full')]"
        "[.//svg/path[contains(@d, '4.11612')]]"
    )

    # Aspect Ratio button (9:16 for vertical video - YouTube Shorts/TikTok)
    ASPECT_RATIO_BUTTON: str = 'button[aria-label="Aspect Ratio"]'
    ASPECT_RATIO_OPTION_9_16: str = '[role="option"][data-key="9:16"]'
    ASPECT_RATIO_OPTION_16_9: str = '[role="option"][data-key="16:9"]'
    ASPECT_RATIO_OPTION_1_1: str = '[role="option"][data-key="1:1"]'

    # Duration selector
    DURATION_BUTTON: str = 'button[aria-label="Duration"]'
    DURATION_OPTION_12S: str = '[role="option"][data-key="12"]'

    # Audio toggle (має бути OFF)
    AUDIO_TOGGLE: str = 'button[role="switch"][aria-label="Audio"]'

    # Prompt
    PROMPT_TEXTAREA: str = 'textarea#prompt'

    # Start frame input
    START_FRAME_INPUT: str = 'input[type="file"][accept*="image"]'

    # Generate button - Primary button has bg-primary class
    GENERATE_BUTTON: str = 'button.bg-primary'


SEEDANCE_SELECTORS = SeedanceSelectors()


@dataclass(frozen=True)
class LoginSelectors:
    """Селектори для сторінки логіну"""
    # Login detection
    LOGIN_BUTTON_XPATH: str = (
        "//button[contains(text(), 'Log in') or contains(text(), 'Sign in')] | "
        "//a[contains(text(), 'Log in') or contains(text(), 'Sign in')]"
    )

    # Continue with Email
    CONTINUE_EMAIL_XPATH: str = (
        "//*[contains(text(), 'Continue with Email') or contains(text(), 'continue with email') or "
        "contains(text(), 'Email') and contains(@class, 'button')]"
    )

    # Email input
    EMAIL_INPUT: str = (
        'input[type="email"], input[name="email"], input[placeholder*="email" i], '
        'input[autocomplete="email"], input[id*="email"]'
    )
    EMAIL_INPUT_FALLBACK: str = 'input[type="email"], input[type="text"]'

    # Password input
    PASSWORD_INPUT: str = 'input[type="password"]'

    # Submit button
    SUBMIT_BUTTON_XPATH: str = (
        "//button[@type='submit'] | "
        "//button[contains(text(), 'Log in')] | "
        "//button[contains(text(), 'Login')] | "
        "//button[contains(text(), 'Sign in')] | "
        "//button[contains(text(), 'Continue')]"
    )


LOGIN_SELECTORS = LoginSelectors()


@dataclass(frozen=True)
class CommonSelectors:
    """Загальні селектори"""
    # Buttons with SVG icons
    BUTTON_WITH_SVG: str = 'button svg'

    # Generic elements
    ALL_BUTTONS: str = 'button'
    ALL_IMAGES: str = 'img'
    ALL_VIDEOS: str = 'video'

    # Dropdowns
    ROLE_OPTION: str = '[role="option"]'
    ROLE_MENUITEM: str = '[role="menuitem"]'
    ROLE_COMBOBOX: str = '[role="combobox"]'


COMMON_SELECTORS = CommonSelectors()


# ============================================================================
# JAVASCRIPT HELPERS
# ============================================================================

class JSScripts:
    """JavaScript скрипти для складних операцій"""

    @staticmethod
    def find_plus_minus_buttons() -> str:
        """JS для пошуку кнопок +/- (image count)"""
        return """
            var result = {plus: null, minus: null};

            // Спосіб 1: Шукаємо по SVG path (старий UI)
            document.querySelectorAll('button').forEach(function(btn) {
                var svg = btn.querySelector('svg');
                if (svg) {
                    var path = svg.querySelector('path');
                    if (path) {
                        var d = path.getAttribute('d') || '';
                        // Кнопка + має вертикальну лінію V4.16602
                        if (d.includes('V4.16602')) {
                            result.plus = btn;
                        }
                        // Кнопка - має тільки горизонтальну лінію H15.8327 (без V)
                        if (d.includes('H15.8327') && !d.includes('V')) {
                            result.minus = btn;
                        }
                    }
                }
            });

            // Спосіб 2: Якщо не знайшли, шукаємо по тексту + та -
            if (!result.plus || !result.minus) {
                document.querySelectorAll('button').forEach(function(btn) {
                    var text = btn.textContent.trim();
                    if (text === '+' && !result.plus) {
                        result.plus = btn;
                    }
                    if (text === '-' && !result.minus) {
                        result.minus = btn;
                    }
                });
            }

            // Спосіб 3: Шукаємо поруч з числом 1-4 (лічильник зображень)
            if (!result.plus || !result.minus) {
                var allButtons = Array.from(document.querySelectorAll('button'));
                for (var i = 0; i < allButtons.length; i++) {
                    var btn = allButtons[i];
                    var parent = btn.parentElement;
                    if (parent) {
                        var siblings = parent.querySelectorAll('button');
                        // Якщо є 2 кнопки поруч і між ними є число
                        if (siblings.length === 2) {
                            var parentText = parent.textContent;
                            if (/[1-4]/.test(parentText)) {
                                var btns = Array.from(siblings);
                                // Перша кнопка зазвичай мінус, друга плюс
                                if (!result.minus) result.minus = btns[0];
                                if (!result.plus) result.plus = btns[1];
                                break;
                            }
                        }
                    }
                }
            }

            return result;
        """

    @staticmethod
    def set_react_textarea_value() -> str:
        """JS для встановлення значення в React textarea"""
        return """
            var textarea = arguments[0];
            var prompt = arguments[1];

            textarea.scrollIntoView({block: 'center'});
            textarea.focus();

            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(textarea, prompt);

            var inputEvent = new Event('input', { bubbles: true });
            textarea.dispatchEvent(inputEvent);

            var changeEvent = new Event('change', { bubbles: true });
            textarea.dispatchEvent(changeEvent);

            return textarea.value.length;
        """

    @staticmethod
    def clear_react_textarea() -> str:
        """JS для очищення React textarea"""
        return """
            var textarea = arguments[0];
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(textarea, '');
            var inputEvent = new Event('input', { bubbles: true });
            textarea.dispatchEvent(inputEvent);
        """

    @staticmethod
    def check_reference_exists() -> str:
        """JS для перевірки наявності reference image - СТРОГА версія (тільки візуальна перевірка)"""
        return """
            // СТРОГО: Перевіряємо ТІЛЬКИ візуальні ознаки завантаженого референса
            // НЕ перевіряємо input.files - це не надійно!

            // Метод 1: Шукаємо МАЛЕНЬКЕ превью зображення (референс показується як thumbnail)
            // Референс зазвичай маленький (< 200px) і знаходиться біля textarea/prompt area
            var allImages = document.querySelectorAll('img');
            var foundRefPreview = false;

            for (var i = 0; i < allImages.length; i++) {
                var img = allImages[i];
                var src = img.src || '';
                var rect = img.getBoundingClientRect();

                // Пропускаємо невалідні
                if (!src || src.length < 30) continue;
                if (src.includes('placeholder')) continue;
                if (src.includes('avatar')) continue;
                if (src.includes('logo')) continue;
                if (src.includes('data:image/svg')) continue;

                // Референс preview зазвичай:
                // - blob: URL (щойно завантажений файл)
                // - Маленький розмір на екрані (thumbnail)
                // - Видимий (не hidden)
                if (src.startsWith('blob:') && rect.width > 20 && rect.width < 250 && rect.height > 20 && rect.height < 250) {
                    // Перевіряємо що картинка в viewport і видима
                    if (rect.top > 0 && rect.top < window.innerHeight && rect.left > 0) {
                        console.log('[CHECK_REF] ✓ Found blob thumbnail:', rect.width + 'x' + rect.height);
                        foundRefPreview = true;
                        break;
                    }
                }
            }

            if (foundRefPreview) return true;

            // Метод 2: Шукаємо X кнопку для видалення референса
            // Ця кнопка з'являється ТІЛЬКИ коли референс завантажено
            // Вона маленька (< 40px) і має SVG з path для X
            var buttons = document.querySelectorAll('button');
            for (var j = 0; j < buttons.length; j++) {
                var btn = buttons[j];
                var btnRect = btn.getBoundingClientRect();

                // X кнопка маленька і видима
                if (btnRect.width > 10 && btnRect.width < 45 && btnRect.height > 10 && btnRect.height < 45) {
                    // Перевіряємо що має SVG
                    var svg = btn.querySelector('svg');
                    if (svg) {
                        var paths = svg.querySelectorAll('path');
                        for (var p = 0; p < paths.length; p++) {
                            var d = paths[p].getAttribute('d') || '';
                            // Типові path для X іконки
                            if (d.includes('M6 18') || d.includes('M6 6') || d.includes('M18 6') ||
                                d.includes('l12 12') || d.includes('M3.81') || d.includes('M4.11') ||
                                d.includes('m6 6') || d.includes('M19 6.41')) {

                                // Додаткова перевірка: кнопка має бути біля якогось зображення
                                var parent = btn.parentElement;
                                for (var lvl = 0; lvl < 4; lvl++) {
                                    if (!parent) break;
                                    var nearbyImg = parent.querySelector('img');
                                    if (nearbyImg && nearbyImg.src && nearbyImg.src.startsWith('blob:')) {
                                        console.log('[CHECK_REF] ✓ Found X button near blob image');
                                        return true;
                                    }
                                    parent = parent.parentElement;
                                }
                            }
                        }
                    }
                }
            }

            console.log('[CHECK_REF] ✗ No reference preview found (no blob thumbnail, no X button)');
            return false;
        """

    @staticmethod
    def verify_start_frame_uploaded() -> str:
        """JS для перевірки що start frame РЕАЛЬНО завантажено (не просто елемент, а картинка)"""
        return """
            // Шукаємо картинки в області upload
            var previewImages = document.querySelectorAll('img[data-asset-preview], .start-frame-preview img, [class*="frame"] img, [class*="upload"] img');

            for (var i = 0; i < previewImages.length; i++) {
                var img = previewImages[i];
                // Перевіряємо що src валідний
                if (img.src && img.src.length > 50 && !img.src.includes('placeholder') && !img.src.includes('data:image/svg')) {
                    // КРИТИЧНО: Перевіряємо що картинка РЕАЛЬНО завантажилась
                    // naturalWidth/naturalHeight > 0 означає що зображення декодовано
                    if (img.complete && img.naturalWidth > 100 && img.naturalHeight > 100) {
                        console.log('Found loaded image:', img.src.substring(0, 80), 'size:', img.naturalWidth, 'x', img.naturalHeight);
                        return true;
                    }
                }
            }

            // Перевіряємо контейнери з uploaded класом
            var uploadedContainers = document.querySelectorAll('[class*="uploaded"], [class*="preview"]');
            for (var i = 0; i < uploadedContainers.length; i++) {
                var container = uploadedContainers[i];
                var img = container.querySelector('img');
                if (img && img.src && img.src.length > 50) {
                    // Також перевіряємо реальне завантаження
                    if (img.complete && img.naturalWidth > 100 && img.naturalHeight > 100) {
                        console.log('Found loaded image in container:', img.src.substring(0, 80));
                        return true;
                    }
                }
            }

            return false;
        """

    @staticmethod
    def get_all_image_urls() -> str:
        """JS для отримання всіх URL зображень на сторінці"""
        return """
            var urls = [];
            var images = document.querySelectorAll('img');

            for (var i = 0; i < images.length; i++) {
                var src = images[i].src;
                if (src && src.length > 50 &&
                    !src.includes('placeholder') &&
                    !src.includes('data:image/svg') &&
                    !src.includes('avatar') &&
                    !src.includes('logo')) {
                    urls.push(src);
                }
            }

            return urls;
        """

    @staticmethod
    def find_clear_button_in_container() -> str:
        """JS для пошуку кнопки очищення в контейнері"""
        return """
            var containers = document.querySelectorAll('[class*="upload"], [class*="frame"], [class*="image"]');

            for (var i = 0; i < containers.length; i++) {
                var container = containers[i];
                var img = container.querySelector('img');
                if (img && img.src && img.src.length > 50) {
                    var buttons = container.querySelectorAll('button');
                    for (var j = 0; j < buttons.length; j++) {
                        var btn = buttons[j];
                        var svg = btn.querySelector('svg');
                        if (svg) {
                            return btn;
                        }
                    }
                }
            }

            return null;
        """


JS_SCRIPTS = JSScripts()
