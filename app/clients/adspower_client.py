"""
AdsPower Client - Управління браузером через AdsPower API.

ВАЖЛИВО: Браузер НЕ закривається автоматично!
Закриття тільки після явного виклику shutdown() з approve_for_shutdown().
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

from loguru import logger

from app.core.errors import (
    AdsPowerConnectionError,
    AdsPowerBrowserError,
    HiggsFieldWebNavigationError,
)
from app.clients.higgsfield_selectors import (
    HIGGSFIELD_LOGIN_URL,
    LOGIN_SELECTORS,
    TIMEOUTS,
)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class AdsPowerConfig:
    """Конфігурація AdsPower підключення"""
    api_key: str
    profile_id: str
    base_url: str = "http://local.adspower.net:50325"


# ============================================================================
# ADSPOWER CLIENT
# ============================================================================

class AdsPowerClient:
    """
    Клієнт для управління браузером через AdsPower.

    ВАЖЛИВО: Браузер НЕ закривається автоматично!
    Потрібно явно викликати shutdown() після апрува анімацій в Телеграмі.

    Usage:
        client = AdsPowerClient(config)
        await client.start_browser()

        # ... робота з браузером ...

        # Тільки після апрува:
        client.approve_for_shutdown()
        await client.shutdown()
    """

    def __init__(self, config: AdsPowerConfig):
        self.config = config
        self._driver: Optional[webdriver.Chrome] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._approved_for_shutdown = False

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def driver(self) -> Optional[webdriver.Chrome]:
        """Selenium WebDriver instance"""
        return self._driver

    @property
    def is_browser_open(self) -> bool:
        """Перевірити чи браузер відкритий"""
        return self._driver is not None

    def is_browser_alive(self) -> bool:
        """
        Перевірити чи браузер дійсно працює (вікно не закрите).

        Відрізняється від is_browser_open тим, що реально тестує з'єднання.
        """
        if not self._driver:
            return False

        try:
            # Спроба виконати просту команду - якщо вікно закрите, буде exception
            _ = self._driver.current_url
            return True
        except WebDriverException:
            return False
        except Exception:
            return False

    @property
    def is_approved_for_shutdown(self) -> bool:
        """Перевірити чи є апрув на закриття"""
        return self._approved_for_shutdown

    # ========================================================================
    # BROWSER LIFECYCLE
    # ========================================================================

    async def start_browser(self, max_retries: int = 3, update_wait_retries: int = 30) -> None:
        """
        Запустити AdsPower профіль і підключити Selenium.

        Args:
            max_retries: Кількість спроб підключення (default: 3)
            update_wait_retries: Кількість спроб очікування оновлення браузера (default: 30)
        """
        logger.info(f"Starting AdsPower browser, profile: {self.config.profile_id}")

        self._http_client = httpx.AsyncClient(timeout=60)  # Збільшено таймаут

        last_error = None
        update_attempts = 0

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[Attempt {attempt}/{max_retries}] Connecting to AdsPower...")

                # Запустити профіль через AdsPower API
                start_url = (
                    f"{self.config.base_url}/api/v1/browser/start"
                    f"?user_id={self.config.profile_id}"
                )

                response = await self._http_client.get(start_url)
                data = response.json()

                if data.get("code") != 0:
                    error_msg = data.get('msg', 'Unknown error')

                    # Перевірка на оновлення браузера - це тимчасовий стан
                    if "updating" in error_msg.lower() or "waiting for download" in error_msg.lower():
                        update_attempts += 1
                        if update_attempts <= update_wait_retries:
                            logger.warning(
                                f"[Update {update_attempts}/{update_wait_retries}] "
                                f"Browser is updating: {error_msg}"
                            )
                            logger.info("Waiting 10s for update to complete...")
                            await asyncio.sleep(10)
                            continue  # Повторити спробу без збільшення attempt
                        else:
                            raise AdsPowerConnectionError(
                                f"Browser update timeout after {update_wait_retries} attempts",
                                details={"response": data}
                            )

                    raise AdsPowerConnectionError(
                        f"AdsPower API error: {error_msg}",
                        details={"response": data}
                    )

                # Отримати connection details
                selenium_addr = data["data"]["ws"]["selenium"]
                webdriver_path = data["data"]["webdriver"]

                logger.debug(f"Selenium address: {selenium_addr}")
                logger.debug(f"WebDriver path: {webdriver_path}")

                # Підключити Selenium (sync operation)
                self._driver = await asyncio.to_thread(
                    self._connect_selenium,
                    selenium_addr,
                    webdriver_path
                )

                logger.success("Browser started successfully")
                return  # Успіх - виходимо

            except httpx.HTTPError as e:
                last_error = e
                logger.warning(f"[Attempt {attempt}] Connection failed: {e}")

                if attempt < max_retries:
                    wait_time = attempt * 5  # 5, 10, 15 секунд
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except AdsPowerConnectionError:
                raise  # API помилка - не retry

        # Всі спроби невдалі
        raise AdsPowerConnectionError(
            "Failed to connect to AdsPower API",
            cause=last_error,
            details={"base_url": self.config.base_url, "attempts": max_retries}
        )

    def _connect_selenium(
        self,
        selenium_addr: str,
        webdriver_path: str
    ) -> webdriver.Chrome:
        """Sync підключення до Selenium (запускається в thread)"""
        try:
            # Parse selenium_addr - може бути ws:// URL або host:port
            # AdsPower повертає ws://127.0.0.1:12345/... - потрібно витягти host:port
            debugger_address = selenium_addr
            if selenium_addr.startswith("ws://") or selenium_addr.startswith("wss://"):
                # Витягти host:port з WebSocket URL
                from urllib.parse import urlparse
                parsed = urlparse(selenium_addr)
                debugger_address = f"{parsed.hostname}:{parsed.port}"
                logger.debug(f"Parsed debugger address: {debugger_address} from {selenium_addr}")

            chrome_options = Options()
            chrome_options.add_experimental_option("debuggerAddress", debugger_address)

            service = Service(executable_path=webdriver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)

            return driver

        except WebDriverException as e:
            raise AdsPowerBrowserError(
                "Failed to connect Selenium to AdsPower browser",
                cause=e
            )

    # ========================================================================
    # RECONNECTION
    # ========================================================================

    async def reconnect(self, max_retries: int = 3) -> bool:
        """
        Перепідключитися до браузера якщо з'єднання втрачено.

        Args:
            max_retries: Кількість спроб підключення

        Returns:
            True якщо успішно перепідключено
        """
        logger.warning("Browser connection lost, attempting reconnect...")

        # Очистити старий driver
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

        # Спробувати перезапустити
        try:
            await self.start_browser(max_retries=max_retries)
            logger.success("Browser reconnected successfully")
            return True
        except Exception as e:
            logger.error(f"Browser reconnection failed: {e}")
            return False

    async def ensure_alive_or_reconnect(self, max_retries: int = 3) -> bool:
        """
        Перевірити що браузер живий, якщо ні - перепідключитися.

        Args:
            max_retries: Кількість спроб перепідключення

        Returns:
            True якщо браузер живий або успішно перепідключено
        """
        if self.is_browser_alive():
            return True

        logger.warning("Browser window closed unexpectedly, reconnecting...")
        return await self.reconnect(max_retries=max_retries)

    # ========================================================================
    # APPROVAL & SHUTDOWN
    # ========================================================================

    def approve_for_shutdown(self) -> None:
        """
        Позначити що анімації апрувнуті і браузер можна закривати.
        Викликати з Telegram handler після апрува користувачем.
        """
        logger.info("Browser approved for shutdown")
        self._approved_for_shutdown = True

    async def shutdown(self) -> None:
        """
        Закрити браузер. Викликати ТІЛЬКИ після апрува анімацій!
        """
        if not self._approved_for_shutdown:
            logger.warning(
                "shutdown() called without approval! "
                "Call approve_for_shutdown() first after Telegram approval."
            )
            # Все одно закриваємо, але з попередженням

        await self._close_browser()

    async def force_shutdown(self) -> None:
        """
        Примусово закрити браузер (для error handling).
        Використовувати тільки при критичних помилках!
        """
        logger.warning("Force shutdown initiated!")
        self._approved_for_shutdown = True
        await self._close_browser()

    async def _close_browser(self) -> None:
        """Внутрішній метод закриття браузера"""
        logger.info("Closing browser...")

        # Закрити Selenium
        if self._driver:
            try:
                await asyncio.to_thread(self._driver.quit)
            except Exception as e:
                logger.warning(f"Error closing Selenium: {e}")
            self._driver = None

        # Зупинити AdsPower профіль
        if self._http_client:
            try:
                stop_url = (
                    f"{self.config.base_url}/api/v1/browser/stop"
                    f"?user_id={self.config.profile_id}"
                )
                await self._http_client.get(stop_url)
            except Exception as e:
                logger.warning(f"Error stopping AdsPower profile: {e}")

            await self._http_client.aclose()
            self._http_client = None

        logger.info("Browser closed")

    # ========================================================================
    # CONTEXT MANAGER (НЕ закриває браузер автоматично!)
    # ========================================================================

    async def __aenter__(self) -> "AdsPowerClient":
        await self.start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # НЕ закриваємо браузер автоматично!
        if exc_type is not None:
            logger.warning(f"Context exit with error: {exc_type.__name__}: {exc_val}")
            logger.warning("Browser NOT closed - call shutdown() manually after approval")

    # ========================================================================
    # NAVIGATION HELPERS
    # ========================================================================

    async def navigate(self, url: str) -> None:
        """Перейти на URL"""
        if not self._driver:
            raise AdsPowerBrowserError("Browser not started")

        logger.debug(f"Navigating to: {url}")
        await asyncio.to_thread(self._driver.get, url)

    async def refresh(self) -> None:
        """Оновити сторінку"""
        if self._driver:
            await asyncio.to_thread(self._driver.refresh)

    async def wait_for_element(
        self,
        by: By,
        value: str,
        timeout: int = TIMEOUTS.DEFAULT_WAIT
    ):
        """Async очікування елемента"""
        return await asyncio.to_thread(
            self._sync_wait_for_element,
            by,
            value,
            timeout
        )

    def _sync_wait_for_element(
        self,
        by: By,
        value: str,
        timeout: int
    ):
        """Sync очікування елемента"""
        wait = WebDriverWait(self._driver, timeout)
        return wait.until(EC.presence_of_element_located((by, value)))

    async def wait_for_page_ready(self, timeout: int = 10) -> None:
        """Дочекатися повного завантаження сторінки"""
        await asyncio.to_thread(self._sync_wait_for_page_ready, timeout)

    def _sync_wait_for_page_ready(self, timeout: int) -> None:
        """Sync очікування завантаження сторінки"""
        try:
            WebDriverWait(self._driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            logger.warning("Page load timeout, continuing anyway...")

    # ========================================================================
    # LOGIN HANDLING
    # ========================================================================

    async def check_and_handle_logout(self) -> None:
        """
        Перевірити чи користувач розлогінений і залогінитись якщо потрібно.
        """
        if not self._driver:
            return

        current_url = self._driver.current_url

        # Перевірка чи redirected на login сторінку
        if "login" in current_url.lower() or "signin" in current_url.lower():
            logger.warning("Session expired! Attempting auto-login...")
            await self._perform_login()
            return

        # Перевірка чи є кнопка Login на сторінці
        is_logged_out = await asyncio.to_thread(self._check_logged_out_state)
        if is_logged_out:
            logger.warning("Detected logged out state! Attempting auto-login...")
            await self._perform_login()

    def _check_logged_out_state(self) -> bool:
        """Sync перевірка чи користувач розлогінений"""
        try:
            login_buttons = self._driver.find_elements(
                By.XPATH,
                LOGIN_SELECTORS.LOGIN_BUTTON_XPATH
            )
            if login_buttons:
                return True

            if "login" in self._driver.current_url.lower():
                return True

            return False

        except Exception:
            return False

    async def _perform_login(self) -> None:
        """Виконати автоматичний логін на Higgsfield"""
        from app.core.config import settings

        email = settings.HIGGSFIELD_WEB_EMAIL
        password = settings.HIGGSFIELD_WEB_PASSWORD

        if not email or not password:
            raise HiggsFieldWebNavigationError(
                "Cannot auto-login: HIGGSFIELD_WEB_EMAIL or HIGGSFIELD_WEB_PASSWORD not set in .env"
            )

        logger.info(f"Performing auto-login as {email}...")

        try:
            # Перейти на сторінку логіну
            await asyncio.to_thread(self._driver.get, HIGGSFIELD_LOGIN_URL)
            await asyncio.sleep(3)

            # Виконати логін
            await asyncio.to_thread(self._sync_perform_login, email, password)

            # Почекати завершення логіну
            await asyncio.sleep(5)

            # Перевірити успішність
            if "login" not in self._driver.current_url.lower():
                logger.success("Auto-login successful!")
            else:
                raise HiggsFieldWebNavigationError("Auto-login failed - still on login page")

        except Exception as e:
            raise HiggsFieldWebNavigationError(
                f"Auto-login failed: {e}",
                cause=e
            )

    def _sync_perform_login(self, email: str, password: str) -> None:
        """Sync виконання логіну"""
        import time
        from selenium.webdriver.common.keys import Keys

        try:
            # Крок 1: Натиснути "Continue with Email" якщо є
            continue_email_btns = self._driver.find_elements(
                By.XPATH,
                LOGIN_SELECTORS.CONTINUE_EMAIL_XPATH
            )

            if continue_email_btns:
                logger.debug("Found 'Continue with Email' button, clicking...")
                self._driver.execute_script("arguments[0].click();", continue_email_btns[0])
                time.sleep(2)

            # Крок 2: Знайти email input
            email_inputs = self._driver.find_elements(
                By.CSS_SELECTOR,
                LOGIN_SELECTORS.EMAIL_INPUT
            )

            if not email_inputs:
                time.sleep(1)
                email_inputs = self._driver.find_elements(
                    By.CSS_SELECTOR,
                    LOGIN_SELECTORS.EMAIL_INPUT_FALLBACK
                )

            if not email_inputs:
                raise HiggsFieldWebNavigationError(
                    "Email input not found. Login page structure may have changed."
                )

            # Ввести email
            email_input = email_inputs[0]
            email_input.clear()
            email_input.send_keys(email)
            logger.debug("Email entered")
            time.sleep(0.5)

            # Крок 3: Знайти password input
            password_inputs = self._driver.find_elements(
                By.CSS_SELECTOR,
                LOGIN_SELECTORS.PASSWORD_INPUT
            )

            if password_inputs:
                password_input = password_inputs[0]
                password_input.clear()
                password_input.send_keys(password)
                logger.debug("Password entered")
                time.sleep(0.5)

            # Крок 4: Знайти і натиснути кнопку Submit
            submit_buttons = self._driver.find_elements(
                By.XPATH,
                LOGIN_SELECTORS.SUBMIT_BUTTON_XPATH
            )

            if submit_buttons:
                for btn in submit_buttons:
                    btn_text = btn.text.lower() if btn.text else ""
                    if "email" not in btn_text or "log" in btn_text or "sign" in btn_text:
                        self._driver.execute_script("arguments[0].click();", btn)
                        logger.debug(f"Login form submitted via button: '{btn.text}'")
                        break
            else:
                # Enter в password field
                if password_inputs:
                    password_inputs[0].send_keys(Keys.RETURN)
                    logger.debug("Login submitted via Enter key")

        except Exception as e:
            logger.error(f"Login form interaction failed: {e}")
            raise

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def find_button_by_text(self, text: str):
        """Знайти кнопку за текстом"""
        if not self._driver:
            return None

        buttons = self._driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if text.lower() in btn.text.lower():
                return btn
        return None

    def execute_script(self, script: str, *args):
        """Виконати JavaScript"""
        if not self._driver:
            return None
        return self._driver.execute_script(script, *args)

    def find_elements(self, by: By, value: str):
        """Знайти елементи"""
        if not self._driver:
            return []
        return self._driver.find_elements(by, value)

    def find_element(self, by: By, value: str):
        """Знайти елемент"""
        if not self._driver:
            return None
        return self._driver.find_element(by, value)

    @property
    def current_url(self) -> str:
        """Поточний URL"""
        if not self._driver:
            return ""
        return self._driver.current_url


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_adspower_client(
    api_key: str,
    profile_id: str,
    base_url: str = "http://local.adspower.net:50325"
) -> AdsPowerClient:
    """Factory для створення AdsPower клієнта"""
    config = AdsPowerConfig(
        api_key=api_key,
        profile_id=profile_id,
        base_url=base_url
    )
    return AdsPowerClient(config)
