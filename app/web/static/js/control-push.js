/**
 * Control Panel Push Notifications
 *
 * Інтеграція з PushNotifications для подій control panel.
 * Підтримує мобільні пристрої через vibration та audio fallback.
 */

const ControlPush = {
    // Черга повідомлень якщо PushNotifications ще не готовий
    _pendingQueue: [],
    _ready: false,

    /**
     * Ініціалізація
     */
    init() {
        // Чекаємо готовності PushNotifications
        const checkReady = setInterval(() => {
            if (window.PushNotifications && window.PushNotifications.permission !== undefined) {
                this._ready = true;
                clearInterval(checkReady);

                // Обробляємо чергу
                this._pendingQueue.forEach(item => {
                    this.notify(item.event, item.data);
                });
                this._pendingQueue = [];

                console.log('[ControlPush] Готово');
            }
        }, 100);

        // Timeout після 5 секунд
        setTimeout(() => {
            clearInterval(checkReady);
            if (!this._ready) {
                console.warn('[ControlPush] PushNotifications не ініціалізовано, використовую fallback');
                this._ready = true;
            }
        }, 5000);
    },

    /**
     * Відправка push notification для події
     */
    notify(event, data) {
        // Якщо не готово — в чергу
        if (!this._ready) {
            this._pendingQueue.push({ event, data });
            return;
        }

        const push = window.PushNotifications;
        if (!push) {
            console.warn('[ControlPush] PushNotifications недоступний');
            return;
        }

        // Визначаємо параметри залежно від події
        let notification = null;

        switch (event) {
            case 'pipeline_started':
                notification = {
                    title: '🚀 PIPELINE ЗАПУЩЕНО',
                    options: {
                        body: `Проєкт: ${data.project_id || 'новий'}`,
                        tag: 'pipeline-start',
                        force: true,
                        vibrate: [100, 50, 100]
                    }
                };
                break;

            case 'project_created':
                notification = {
                    title: '📁 ПРОЄКТ СТВОРЕНО',
                    options: {
                        body: data.project_id,
                        tag: 'project-created',
                        force: true
                    }
                };
                break;

            case 'approval_required':
                notification = {
                    title: '⚠️ ПОТРІБНЕ ПІДТВЕРДЖЕННЯ',
                    options: {
                        body: data.type === 'primary'
                            ? 'Оберіть PRIMARY reference'
                            : 'Перегляньте сцени 2-6',
                        tag: 'approval-required',
                        requireInteraction: true,
                        force: true,
                        vibrate: [300, 100, 300, 100, 300, 100, 500],
                        data: {
                            url: '/control',
                            approvalType: data.type
                        }
                    }
                };
                break;

            case 'video_approval_required':
                notification = {
                    title: '🎬 ВІДЕО ГОТОВЕ ДО ПЕРЕВІРКИ',
                    options: {
                        body: 'Підтвердіть перед Topaz обробкою',
                        tag: 'video-approval',
                        requireInteraction: true,
                        force: true,
                        vibrate: [300, 100, 300, 100, 500],
                        data: { url: '/control' }
                    }
                };
                break;

            case 'stage_changed':
                // Не показуємо notification для кожного stage
                // Тільки логуємо
                console.log(`[ControlPush] Stage: ${data.stage} (${data.progress}%)`);
                return;

            case 'scene_updated':
            case 'scene_video_ready':
                // Тихі оновлення — без push
                if (data.status === 'approved') {
                    notification = {
                        title: '✅ СЦЕНА ГОТОВА',
                        options: {
                            body: `Сцена ${data.scene_num || data.scene_number}`,
                            tag: `scene-${data.scene_num || data.scene_number}`,
                            force: false, // Не показувати якщо сторінка активна
                            vibrate: [50, 30, 50]
                        }
                    };
                }
                break;

            case 'merge_status':
                if (!data.success) {
                    notification = {
                        title: '🔄 MERGE RETRY',
                        options: {
                            body: `Спроба ${data.total_attempts}: ${data.missing_fields?.length || 0} полів відсутні`,
                            tag: 'merge-status',
                            force: false
                        }
                    };
                }
                break;

            case 'pipeline_completed':
                notification = {
                    title: '🎉 ВІДЕО ГОТОВЕ!',
                    options: {
                        body: data.video_path || 'Фінальне відео завершено',
                        tag: 'pipeline-complete',
                        requireInteraction: true,
                        force: true,
                        vibrate: [200, 100, 200, 100, 400, 200, 600],
                        data: { url: '/control' }
                    }
                };
                break;

            case 'topaz_completed':
                notification = {
                    title: '✨ TOPAZ ЗАВЕРШЕНО',
                    options: {
                        body: '4K відео готове до публікації',
                        tag: 'topaz-complete',
                        requireInteraction: true,
                        force: true,
                        vibrate: [200, 100, 200, 100, 400],
                        data: { url: '/control' }
                    }
                };
                break;

            case 'topaz_progress':
                // Тихе оновлення
                console.log(`[ControlPush] Topaz: ${data.message}`);
                return;

            case 'pipeline_error':
                // Не показуємо для abort (нова тема)
                const msg = (data.message || '').toLowerCase();
                if (msg.includes('abort') || msg.includes('new topic')) {
                    return;
                }
                notification = {
                    title: '❌ ПОМИЛКА',
                    options: {
                        body: data.message || 'Pipeline зупинено',
                        tag: 'pipeline-error',
                        requireInteraction: true,
                        force: true,
                        vibrate: [500, 200, 500]
                    }
                };
                break;

            case 'pipeline_reset':
                notification = {
                    title: '🔄 PIPELINE СКИНУТО',
                    options: {
                        body: 'Почато новий проєкт',
                        tag: 'pipeline-reset',
                        force: true
                    }
                };
                break;

            case 'render_complete':
                notification = {
                    title: '🎬 РЕНДЕР ЗАВЕРШЕНО',
                    options: {
                        body: data.project_id,
                        tag: 'render-complete',
                        force: true
                    }
                };
                break;

            default:
                console.log(`[ControlPush] Невідома подія: ${event}`);
                return;
        }

        // Відправляємо notification
        if (notification) {
            push.show(notification.title, notification.options);
        }
    }
};

// Ініціалізація
document.addEventListener('DOMContentLoaded', () => {
    ControlPush.init();
});

// Глобальний доступ
window.ControlPush = ControlPush;
