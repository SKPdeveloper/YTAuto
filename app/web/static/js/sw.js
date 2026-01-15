/**
 * Service Worker for Push Notifications
 *
 * Handles background notifications when the browser tab is closed.
 */

const CACHE_NAME = 'ytauto-v1';

// Install event
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    self.skipWaiting();
});

// Activate event
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(clients.claim());
});

// Message event (from main thread)
self.addEventListener('message', (event) => {
    if (event.data.type === 'SHOW_NOTIFICATION') {
        const { title, options } = event.data;

        self.registration.showNotification(title, {
            ...options,
            timestamp: Date.now()
        });
    }
});

// Notification click event
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked:', event.notification.tag);

    event.notification.close();

    const data = event.notification.data || {};

    // Handle action buttons
    if (event.action) {
        handleNotificationAction(event.action, data);
        return;
    }

    // Default: open the app
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((clientList) => {
                // Check if there's already a window open
                for (const client of clientList) {
                    if ('focus' in client) {
                        // Navigate to project if specified
                        if (data.projectId) {
                            client.navigate(`/channel/project/${data.projectId}`);
                        }
                        return client.focus();
                    }
                }

                // No window open, create one
                if (clients.openWindow) {
                    const url = data.projectId
                        ? `/channel/project/${data.projectId}`
                        : '/';
                    return clients.openWindow(url);
                }
            })
    );
});

// Handle notification actions
function handleNotificationAction(action, data) {
    switch (action) {
        case 'view':
            clients.openWindow(`/channel/project/${data.projectId}`);
            break;

        case 'select':
            clients.openWindow(`/channel/project/${data.projectId}#candidates`);
            break;

        case 'approve':
            clients.openWindow(`/channel/project/${data.projectId}#scene-${data.sceneNumber}`);
            break;

        case 'dismiss':
            // Just close the notification
            break;

        default:
            clients.openWindow('/');
    }
}

// Push event (for future server-side push)
self.addEventListener('push', (event) => {
    if (!event.data) return;

    try {
        const data = event.data.json();

        const options = {
            body: data.body || '',
            icon: data.icon || '/static/icons/icon-192.png',
            badge: '/static/icons/badge-72.png',
            vibrate: [200, 100, 200],
            data: data.data || {},
            actions: data.actions || [],
            tag: data.tag || 'ytauto-push',
            requireInteraction: data.requireInteraction || false
        };

        event.waitUntil(
            self.registration.showNotification(data.title || 'YTAuto', options)
        );
    } catch (e) {
        console.error('[SW] Push event error:', e);
    }
});

// Notification close event
self.addEventListener('notificationclose', (event) => {
    console.log('[SW] Notification closed:', event.notification.tag);
});
