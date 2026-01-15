/**
 * Push Notifications Handler
 *
 * Enables browser push notifications that work even when the browser tab is closed.
 * Uses the Notifications API and Service Workers.
 */

const PushNotifications = {
    permission: Notification.permission,
    serviceWorker: null,

    /**
     * Initialize push notifications
     */
    async init() {
        // Check if notifications are supported
        if (!('Notification' in window)) {
            console.warn('[Push] Notifications not supported');
            return false;
        }

        // Request permission if not granted
        if (this.permission === 'default') {
            await this.requestPermission();
        }

        // Register service worker for background notifications
        if ('serviceWorker' in navigator) {
            try {
                this.serviceWorker = await navigator.serviceWorker.register('/static/js/sw.js');
                console.log('[Push] Service worker registered');
            } catch (e) {
                console.error('[Push] Service worker registration failed:', e);
            }
        }

        // Listen for WebSocket events and show notifications
        this._setupListeners();

        return this.permission === 'granted';
    },

    /**
     * Request notification permission
     */
    async requestPermission() {
        try {
            this.permission = await Notification.requestPermission();
            console.log('[Push] Permission:', this.permission);

            if (this.permission === 'granted') {
                this.show('Notifications Enabled', {
                    body: 'You will receive updates about your video generation.',
                    icon: '/static/icons/icon-192.png'
                });
            }
        } catch (e) {
            console.error('[Push] Permission request failed:', e);
        }
    },

    /**
     * Show a notification
     */
    show(title, options = {}) {
        if (this.permission !== 'granted') {
            console.warn('[Push] Permission not granted');
            return;
        }

        // Don't show if page is visible (WebSocket toast is enough)
        if (document.visibilityState === 'visible' && !options.force) {
            return;
        }

        const defaultOptions = {
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/badge-72.png',
            vibrate: [200, 100, 200],
            requireInteraction: false,
            silent: false,
            tag: 'ytauto-notification',
            ...options
        };

        try {
            // Use service worker for background notifications
            if (this.serviceWorker && this.serviceWorker.active) {
                this.serviceWorker.active.postMessage({
                    type: 'SHOW_NOTIFICATION',
                    title: title,
                    options: defaultOptions
                });
            } else {
                // Fallback to regular notification
                new Notification(title, defaultOptions);
            }
        } catch (e) {
            console.error('[Push] Failed to show notification:', e);
        }
    },

    /**
     * Show notification with action buttons
     */
    showWithActions(title, options = {}, actions = []) {
        const notificationOptions = {
            ...options,
            actions: actions.map(action => ({
                action: action.id,
                title: action.title,
                icon: action.icon
            }))
        };

        this.show(title, notificationOptions);
    },

    /**
     * Setup listeners for WebSocket events
     */
    _setupListeners() {
        if (!window.wsClient) {
            console.warn('[Push] WebSocket client not found');
            return;
        }

        // Project events
        wsClient.on('project_created', (data) => {
            this.show('New Project Created', {
                body: `Project ${data.project_id} started`,
                tag: `project-${data.project_id}`
            });
        });

        wsClient.on('pipeline_completed', (data) => {
            this.show('Video Ready!', {
                body: `Project ${data.project_id} completed successfully`,
                tag: `project-${data.project_id}`,
                requireInteraction: true,
                data: { projectId: data.project_id, action: 'view' }
            });
        });

        // Stage events
        wsClient.on('stage_changed', (data) => {
            const stageNames = {
                'script_generation': 'Script Generation',
                'image_generation': 'Image Generation',
                'image_validation': 'Image Validation',
                'video_generation': 'Video Generation',
                'post_processing': 'Post-Processing'
            };

            this.show('Stage Started', {
                body: `${stageNames[data.stage] || data.stage} in progress`,
                tag: `stage-${data.project_id}`
            });
        });

        wsClient.on('stage_completed', (data) => {
            this.show('Stage Completed', {
                body: `${data.stage} finished successfully`,
                tag: `stage-${data.project_id}`
            });
        });

        // Approval events
        wsClient.on('primary_candidates_ready', (data) => {
            this.show('Candidates Ready', {
                body: `Scene 1: ${data.candidate_count || 4} candidates ready for selection`,
                tag: `approval-${data.project_id}`,
                requireInteraction: true,
                data: { projectId: data.project_id, action: 'select' }
            });
        });

        wsClient.on('approval_required', (data) => {
            this.show('Approval Required', {
                body: `Scene ${data.scene_number} needs your approval`,
                tag: `approval-${data.project_id}-${data.scene_number}`,
                requireInteraction: true,
                data: { projectId: data.project_id, sceneNumber: data.scene_number, action: 'approve' }
            });
        });

        // Error events
        wsClient.on('error', (data) => {
            this.show('Error', {
                body: data.error_message || 'An error occurred',
                tag: `error-${data.project_id || 'general'}`,
                requireInteraction: true
            });
        });

        // Scene events
        wsClient.on('scene_image_ready', (data) => {
            this.show('Image Generated', {
                body: `Scene ${data.scene_number} image is ready`,
                tag: `scene-${data.project_id}-${data.scene_number}`
            });
        });

        wsClient.on('scene_video_ready', (data) => {
            this.show('Video Generated', {
                body: `Scene ${data.scene_number} video is ready`,
                tag: `scene-${data.project_id}-${data.scene_number}`
            });
        });
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    PushNotifications.init();
});

// Export to window
window.PushNotifications = PushNotifications;
