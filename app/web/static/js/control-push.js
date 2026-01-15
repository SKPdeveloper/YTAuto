/**
 * Control Panel Push Notifications
 *
 * Integrates with PushNotifications for control panel events.
 */

const ControlPush = {
    /**
     * Trigger push notification for control panel event
     */
    notify(event, data) {
        if (!window.PushNotifications) {
            console.warn('[ControlPush] PushNotifications not available');
            return;
        }

        const push = window.PushNotifications;

        switch(event) {
            case 'pipeline_started':
                push.show('PIPELINE STARTED', {
                    body: `Project: ${data.project_id || 'new'}`,
                    tag: 'pipeline-start',
                    force: true
                });
                break;

            case 'approval_required':
                push.show('APPROVAL REQUIRED', {
                    body: data.type === 'primary' ? 'Select PRIMARY reference' : 'Review scenes 2-6',
                    tag: 'approval',
                    requireInteraction: true,
                    force: true,
                    vibrate: [300, 100, 300, 100, 300]
                });
                break;

            case 'stage_changed':
                push.show('STAGE: ' + (data.stage || '').toUpperCase(), {
                    body: `Progress: ${data.progress || 0}%`,
                    tag: 'stage',
                    force: true
                });
                break;

            case 'scene_image_generated':
            case 'scene_updated':
                if (data.status === 'approved') {
                    push.show('IMAGE APPROVED', {
                        body: `Scene ${data.scene_num}`,
                        tag: `scene-${data.scene_num}`,
                        force: true
                    });
                }
                break;

            case 'scene_video_generated':
                push.show('VIDEO GENERATED', {
                    body: `Scene ${data.scene_num}`,
                    tag: `video-${data.scene_num}`,
                    force: true
                });
                break;

            case 'pipeline_completed':
                push.show('VIDEO READY', {
                    body: data.video_path || 'Final video complete',
                    tag: 'complete',
                    requireInteraction: true,
                    force: true,
                    vibrate: [500, 200, 500]
                });
                break;

            case 'pipeline_error':
                push.show('ERROR', {
                    body: data.message || 'Pipeline failed',
                    tag: 'error',
                    requireInteraction: true,
                    force: true
                });
                break;
        }
    }
};

// Expose globally
window.ControlPush = ControlPush;
