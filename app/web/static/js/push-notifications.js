/**
 * Push Notifications Handler (Mobile-First)
 *
 * Підтримує:
 * - Web Push API (Android Chrome, iOS 16.4+ Safari в PWA режимі)
 * - Fallback через Vibration API + Audio
 * - Keep-alive для фонових повідомлень
 * - Persistent notifications
 */

const PushNotifications = {
    permission: 'default',
    serviceWorkerReady: false,
    swRegistration: null,
    isIOS: /iPad|iPhone|iPod/.test(navigator.userAgent),
    isAndroid: /Android/.test(navigator.userAgent),
    isPWA: window.matchMedia('(display-mode: standalone)').matches ||
           window.navigator.standalone === true,
    supportsNativePush: false,

    // Аудіо для fallback (base64 encoded short beep)
    alertAudio: null,

    /**
     * Ініціалізація системи повідомлень
     */
    async init() {
        console.log('[Push] Ініціалізація...');
        console.log(`[Push] Platform: ${this.isIOS ? 'iOS' : this.isAndroid ? 'Android' : 'Desktop'}`);
        console.log(`[Push] PWA mode: ${this.isPWA}`);

        // Перевірка підтримки Notification API
        if (!('Notification' in window)) {
            console.warn('[Push] Notification API не підтримується');
            this._initFallbackOnly();
            return false;
        }

        // iOS Safari (не PWA) — тільки fallback
        if (this.isIOS && !this.isPWA) {
            console.warn('[Push] iOS Safari без PWA — використовую fallback');
            this._showIOSInstallHint();
            this._initFallbackOnly();
            return false;
        }

        // Запит дозволу
        this.permission = Notification.permission;
        if (this.permission === 'default') {
            await this.requestPermission();
        }

        // Service Worker реєстрація
        if ('serviceWorker' in navigator) {
            try {
                this.swRegistration = await navigator.serviceWorker.register('/static/js/sw.js', {
                    scope: '/'
                });

                // Чекаємо поки SW буде активний
                if (this.swRegistration.installing) {
                    await new Promise(resolve => {
                        this.swRegistration.installing.addEventListener('statechange', e => {
                            if (e.target.state === 'activated') resolve();
                        });
                    });
                }

                this.serviceWorkerReady = true;
                console.log('[Push] Service Worker зареєстровано та активовано');

                // Перевірка чи підтримується native push
                this.supportsNativePush = 'showNotification' in ServiceWorkerRegistration.prototype;

            } catch (e) {
                console.error('[Push] Service Worker помилка:', e);
            }
        }

        // Ініціалізація fallback audio
        this._initAudio();

        // Реєстрація visibility change для keep-alive
        this._setupVisibilityHandler();

        // Перехоплення повідомлень від SW
        this._setupSWMessageHandler();

        console.log(`[Push] Готово. Permission: ${this.permission}, Native Push: ${this.supportsNativePush}`);

        return this.permission === 'granted';
    },

    /**
     * Запит дозволу на повідомлення
     */
    async requestPermission() {
        try {
            // iOS 16.4+ в PWA режимі
            if (this.isIOS && this.isPWA && 'Notification' in window) {
                this.permission = await Notification.requestPermission();
            } else {
                this.permission = await Notification.requestPermission();
            }

            console.log('[Push] Permission:', this.permission);

            if (this.permission === 'granted') {
                this.show('Сповіщення увімкнено', {
                    body: 'Ви отримуватимете оновлення про генерацію відео.',
                    icon: '/static/icons/icon-192.png',
                    tag: 'permission-granted',
                    silent: false
                });
            }

            return this.permission === 'granted';
        } catch (e) {
            console.error('[Push] Permission request failed:', e);
            return false;
        }
    },

    /**
     * Показ повідомлення
     */
    async show(title, options = {}) {
        const defaultOptions = {
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/badge-72.png',
            vibrate: [200, 100, 200, 100, 300],
            requireInteraction: false,
            silent: false,
            tag: 'ytauto-notification',
            renotify: true, // Дозволяє повторну вібрацію для того ж tag
            ...options
        };

        // ЗАВЖДИ показуємо якщо force=true (для критичних подій)
        const shouldShow = options.force || document.visibilityState !== 'visible';

        if (!shouldShow) {
            console.log('[Push] Сторінка видима, пропускаю notification');
            return;
        }

        // Спроба через Service Worker (найнадійніше на мобільних)
        if (this.serviceWorkerReady && this.swRegistration && this.supportsNativePush) {
            try {
                await this.swRegistration.showNotification(title, {
                    ...defaultOptions,
                    timestamp: Date.now(),
                    data: {
                        url: window.location.href,
                        ...options.data
                    }
                });
                console.log('[Push] SW notification shown:', title);
                return;
            } catch (e) {
                console.warn('[Push] SW showNotification failed:', e);
            }
        }

        // Fallback: звичайний Notification API
        if (this.permission === 'granted') {
            try {
                const notification = new Notification(title, defaultOptions);

                notification.onclick = () => {
                    window.focus();
                    notification.close();
                };

                console.log('[Push] Native notification shown:', title);
                return;
            } catch (e) {
                console.warn('[Push] Native Notification failed:', e);
            }
        }

        // Last resort: Vibration + Audio fallback
        this._fallbackAlert(title, options);
    },

    /**
     * Fallback сповіщення через вібрацію та звук
     */
    _fallbackAlert(title, options = {}) {
        console.log('[Push] Using fallback alert:', title);

        // Вібрація (Android та деякі iOS)
        if ('vibrate' in navigator) {
            const pattern = options.vibrate || [200, 100, 200, 100, 300];
            navigator.vibrate(pattern);
        }

        // Звуковий сигнал
        this._playAlertSound();

        // Візуальна індикація (document title blinking)
        this._blinkTitle(title);
    },

    /**
     * Ініціалізація audio для fallback
     */
    _initAudio() {
        try {
            // Створюємо аудіо контекст
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            this._audioContext = new AudioContext();

            // Pre-load test (для iOS потрібен user gesture)
            document.addEventListener('touchstart', () => {
                if (this._audioContext.state === 'suspended') {
                    this._audioContext.resume();
                }
            }, { once: true });

            document.addEventListener('click', () => {
                if (this._audioContext.state === 'suspended') {
                    this._audioContext.resume();
                }
            }, { once: true });

        } catch (e) {
            console.warn('[Push] Audio init failed:', e);
        }
    },

    /**
     * Відтворення звукового сигналу
     */
    _playAlertSound() {
        if (!this._audioContext) return;

        try {
            // Resume якщо suspended
            if (this._audioContext.state === 'suspended') {
                this._audioContext.resume();
            }

            const ctx = this._audioContext;
            const now = ctx.currentTime;

            // Три тони що підвищуються (привертають увагу)
            [440, 554, 659].forEach((freq, i) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();

                osc.connect(gain);
                gain.connect(ctx.destination);

                osc.frequency.value = freq;
                osc.type = 'sine';

                gain.gain.setValueAtTime(0.3, now + i * 0.15);
                gain.gain.exponentialRampToValueAtTime(0.01, now + i * 0.15 + 0.14);

                osc.start(now + i * 0.15);
                osc.stop(now + i * 0.15 + 0.15);
            });
        } catch (e) {
            console.warn('[Push] Audio play failed:', e);
        }
    },

    /**
     * Блимання заголовка сторінки
     */
    _blinkTitle(message) {
        const originalTitle = document.title;
        let isOriginal = true;
        let blinkCount = 0;
        const maxBlinks = 10;

        const interval = setInterval(() => {
            document.title = isOriginal ? `🔔 ${message}` : originalTitle;
            isOriginal = !isOriginal;
            blinkCount++;

            if (blinkCount >= maxBlinks || document.visibilityState === 'visible') {
                clearInterval(interval);
                document.title = originalTitle;
            }
        }, 500);
    },

    /**
     * Підказка для iOS користувачів
     */
    _showIOSInstallHint() {
        // Показуємо один раз на сесію
        if (sessionStorage.getItem('ios-pwa-hint-shown')) return;

        const hint = document.createElement('div');
        hint.innerHTML = `
            <div style="
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                background: linear-gradient(135deg, #1a1a2e, #16213e);
                color: #fff;
                padding: 16px;
                font-size: 14px;
                z-index: 99999;
                border-top: 2px solid #4a5568;
                display: flex;
                align-items: center;
                gap: 12px;
                font-family: -apple-system, system-ui, sans-serif;
            ">
                <span style="font-size: 24px;">📲</span>
                <div style="flex: 1;">
                    <strong>Для сповіщень</strong><br>
                    <span style="opacity: 0.8; font-size: 12px;">
                        Натисніть "Поділитися" → "На головний екран"
                    </span>
                </div>
                <button onclick="this.parentElement.remove(); sessionStorage.setItem('ios-pwa-hint-shown', '1');"
                    style="background: #4a5568; border: none; color: #fff; padding: 8px 12px; border-radius: 6px; cursor: pointer;">
                    OK
                </button>
            </div>
        `;
        document.body.appendChild(hint.firstElementChild);
        sessionStorage.setItem('ios-pwa-hint-shown', '1');
    },

    /**
     * Fallback mode (без native push)
     */
    _initFallbackOnly() {
        this._initAudio();
        this._setupVisibilityHandler();
        console.log('[Push] Fallback mode активовано');
    },

    /**
     * Обробка visibility change для keep-alive
     */
    _setupVisibilityHandler() {
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                // Сторінка стала видимою — можна зупинити блимання
                document.title = document.title.replace(/^🔔 /, '');
            }
        });

        // Періодичний keep-alive для WebSocket (запобігає disconnect на мобільних)
        if (this.isIOS || this.isAndroid) {
            setInterval(() => {
                // Ping WebSocket якщо сторінка у фоні
                if (document.visibilityState === 'hidden' && window.ws && window.ws.readyState === WebSocket.OPEN) {
                    window.ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 25000); // Кожні 25 секунд
        }
    },

    /**
     * Обробка повідомлень від Service Worker
     */
    _setupSWMessageHandler() {
        if (!('serviceWorker' in navigator)) return;

        navigator.serviceWorker.addEventListener('message', (event) => {
            const { type, data } = event.data || {};

            if (type === 'NOTIFICATION_CLICKED') {
                // Користувач клікнув на notification — фокусуємо вікно
                window.focus();
                if (data?.url) {
                    window.location.href = data.url;
                }
            }
        });
    }
};

// Ініціалізація при завантаженні
document.addEventListener('DOMContentLoaded', () => {
    PushNotifications.init();
});

// Глобальний доступ
window.PushNotifications = PushNotifications;
