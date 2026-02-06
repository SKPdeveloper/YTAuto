/**
 * Service Worker для Push Notifications (Mobile-First)
 *
 * Обробляє:
 * - Background notifications
 * - Notification clicks та actions
 * - Offline caching (basic)
 * - Keep-alive для WebSocket
 */

const CACHE_NAME = 'ytauto-v2';
const CACHE_URLS = [
    '/control',
    '/static/icons/icon-192.png',
    '/static/icons/badge-72.png',
    '/static/manifest.json'
];

// ============================================================================
// INSTALL
// ============================================================================

self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(CACHE_URLS))
            .then(() => self.skipWaiting())
    );
});

// ============================================================================
// ACTIVATE
// ============================================================================

self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');

    event.waitUntil(
        Promise.all([
            // Очистка старих кешів
            caches.keys().then(keys => {
                return Promise.all(
                    keys.filter(key => key !== CACHE_NAME)
                        .map(key => caches.delete(key))
                );
            }),
            // Взяти контроль над всіма клієнтами
            self.clients.claim()
        ])
    );
});

// ============================================================================
// FETCH (Basic offline support)
// ============================================================================

self.addEventListener('fetch', (event) => {
    // Тільки GET запити
    if (event.request.method !== 'GET') return;

    // Пропускаємо API та WebSocket
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
        return;
    }

    event.respondWith(
        caches.match(event.request)
            .then(cached => cached || fetch(event.request))
            .catch(() => {
                // Offline fallback для HTML
                if (event.request.headers.get('accept')?.includes('text/html')) {
                    return caches.match('/control');
                }
            })
    );
});

// ============================================================================
// MESSAGE (від головного потоку)
// ============================================================================

self.addEventListener('message', (event) => {
    const { type, title, options } = event.data || {};

    if (type === 'SHOW_NOTIFICATION') {
        self.registration.showNotification(title, {
            ...options,
            timestamp: Date.now(),
            data: {
                url: options.data?.url || '/control',
                ...options.data
            }
        });
    }

    // Keep-alive ping
    if (type === 'PING') {
        event.source?.postMessage({ type: 'PONG' });
    }
});

// ============================================================================
// PUSH (серверні push повідомлення)
// ============================================================================

self.addEventListener('push', (event) => {
    console.log('[SW] Push received');

    if (!event.data) return;

    let data;
    try {
        data = event.data.json();
    } catch (e) {
        data = { title: 'Нове повідомлення', body: event.data.text() };
    }

    const options = {
        body: data.body || '',
        icon: data.icon || '/static/icons/icon-192.png',
        badge: '/static/icons/badge-72.png',
        vibrate: data.vibrate || [200, 100, 200, 100, 300],
        data: data.data || { url: '/control' },
        actions: data.actions || [],
        tag: data.tag || 'ytauto-push',
        renotify: true,
        requireInteraction: data.requireInteraction || false,
        timestamp: Date.now()
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'YTAuto', options)
    );
});

// ============================================================================
// NOTIFICATION CLICK
// ============================================================================

self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked:', event.notification.tag);

    const notification = event.notification;
    const action = event.action;
    const data = notification.data || {};

    notification.close();

    // Обробка action buttons
    if (action) {
        event.waitUntil(handleNotificationAction(action, data));
        return;
    }

    // Default: відкрити/фокусувати вікно
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(clientList => {
                // Шукаємо вже відкрите вікно
                for (const client of clientList) {
                    if (client.url.includes('/control') && 'focus' in client) {
                        // Повідомляємо клієнта
                        client.postMessage({
                            type: 'NOTIFICATION_CLICKED',
                            data: data
                        });
                        return client.focus();
                    }
                }

                // Відкриваємо нове вікно
                if (clients.openWindow) {
                    const url = data.url || '/control';
                    return clients.openWindow(url);
                }
            })
    );
});

// ============================================================================
// NOTIFICATION ACTIONS
// ============================================================================

async function handleNotificationAction(action, data) {
    const url = data.url || '/control';

    switch (action) {
        case 'view':
        case 'open':
            await clients.openWindow(url);
            break;

        case 'approve':
            // Швидке підтвердження через API
            try {
                await fetch('/api/control/approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        image_index: data.imageIndex || 0,
                        approval_type: data.approvalType || 'primary'
                    })
                });
            } catch (e) {
                console.error('[SW] Approve action failed:', e);
            }
            await clients.openWindow(url);
            break;

        case 'dismiss':
            // Просто закриваємо notification
            break;

        default:
            await clients.openWindow(url);
    }
}

// ============================================================================
// NOTIFICATION CLOSE
// ============================================================================

self.addEventListener('notificationclose', (event) => {
    console.log('[SW] Notification closed:', event.notification.tag);
});

// ============================================================================
// PERIODIC SYNC (для background updates на Android)
// ============================================================================

self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'check-pipeline') {
        event.waitUntil(checkPipelineStatus());
    }
});

async function checkPipelineStatus() {
    try {
        const response = await fetch('/api/control/current-state');
        const data = await response.json();

        if (data.awaiting_approval || data.awaiting_video_approval) {
            self.registration.showNotification('Потрібна дія', {
                body: 'Очікується підтвердження в Control Panel',
                icon: '/static/icons/icon-192.png',
                badge: '/static/icons/badge-72.png',
                tag: 'approval-reminder',
                vibrate: [200, 100, 200],
                requireInteraction: true,
                data: { url: '/control' }
            });
        }
    } catch (e) {
        console.error('[SW] Periodic sync failed:', e);
    }
}
