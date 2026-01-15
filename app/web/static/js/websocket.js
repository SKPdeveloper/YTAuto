/**
 * WebSocket Client for Real-time Updates
 *
 * Handles connection to backend WebSocket server and dispatches events
 * to update the UI in real-time.
 */

class WebSocketClient {
    constructor() {
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
        this.listeners = new Map();
        this.isConnecting = false;
    }

    /**
     * Connect to WebSocket server
     */
    connect() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WS] Already connected');
            return;
        }

        if (this.isConnecting) {
            console.log('[WS] Connection in progress');
            return;
        }

        this.isConnecting = true;

        // Build WebSocket URL
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        console.log(`[WS] Connecting to ${wsUrl}...`);

        try {
            this.ws = new WebSocket(wsUrl);
            this.ws.onopen = this._onOpen.bind(this);
            this.ws.onclose = this._onClose.bind(this);
            this.ws.onerror = this._onError.bind(this);
            this.ws.onmessage = this._onMessage.bind(this);
        } catch (e) {
            console.error('[WS] Connection error:', e);
            this.isConnecting = false;
            this._scheduleReconnect();
        }
    }

    /**
     * Disconnect from WebSocket server
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    /**
     * Subscribe to an event type
     * @param {string} event - Event name
     * @param {function} callback - Callback function
     */
    on(event, callback) {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, []);
        }
        this.listeners.get(event).push(callback);
    }

    /**
     * Unsubscribe from an event type
     * @param {string} event - Event name
     * @param {function} callback - Callback function
     */
    off(event, callback) {
        if (this.listeners.has(event)) {
            const callbacks = this.listeners.get(event);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        }
    }

    /**
     * Send message to server
     * @param {string} event - Event name
     * @param {object} data - Data to send
     */
    send(event, data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ event, data }));
        } else {
            console.warn('[WS] Not connected, cannot send message');
        }
    }

    // Private methods

    _onOpen() {
        console.log('[WS] Connected');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this._emit('connected', {});
        this._updateConnectionStatus(true);
    }

    _onClose(event) {
        console.log('[WS] Disconnected', event.code, event.reason);
        this.isConnecting = false;
        this._emit('disconnected', { code: event.code, reason: event.reason });
        this._updateConnectionStatus(false);
        this._scheduleReconnect();
    }

    _onError(error) {
        console.error('[WS] Error:', error);
        this.isConnecting = false;
        this._emit('error', { error });
    }

    _onMessage(event) {
        try {
            const message = JSON.parse(event.data);
            const { event: eventType, data } = message;

            console.log(`[WS] Event: ${eventType}`, data);

            // Emit to listeners
            this._emit(eventType, data);

            // Handle built-in events
            this._handleBuiltInEvent(eventType, data);

        } catch (e) {
            console.error('[WS] Failed to parse message:', e);
        }
    }

    _emit(event, data) {
        if (this.listeners.has(event)) {
            for (const callback of this.listeners.get(event)) {
                try {
                    callback(data);
                } catch (e) {
                    console.error(`[WS] Error in ${event} handler:`, e);
                }
            }
        }
    }

    _scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[WS] Max reconnect attempts reached');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => {
            this.connect();
        }, delay);
    }

    _updateConnectionStatus(connected) {
        const indicator = document.getElementById('ws-status');
        if (indicator) {
            if (connected) {
                indicator.classList.remove('bg-red-500');
                indicator.classList.add('bg-green-500');
                indicator.title = 'WebSocket Connected';
            } else {
                indicator.classList.remove('bg-green-500');
                indicator.classList.add('bg-red-500');
                indicator.title = 'WebSocket Disconnected';
            }
        }
    }

    _handleBuiltInEvent(event, data) {
        switch (event) {
            case 'project_created':
                this._showToast(`Project created: ${data.project_id}`, 'success');
                break;

            case 'stage_changed':
                this._updateStageStatus(data.project_id, data.stage);
                break;

            case 'stage_completed':
                this._showToast(`Stage completed: ${data.stage}`, 'success');
                break;

            case 'progress':
                this._updateProgress(data.project_id, data.progress_percent, data.message);
                break;

            case 'primary_candidates_ready':
                this._showPrimaryCandidates(data);
                break;

            case 'scene_image_ready':
                this._updateSceneImage(data);
                break;

            case 'scene_video_ready':
                this._updateSceneVideo(data);
                break;

            case 'approval_required':
                this._showApprovalModal(data);
                break;

            case 'error':
                this._showToast(`Error: ${data.error_message}`, 'error');
                break;

            case 'pipeline_completed':
                this._showToast('Pipeline completed!', 'success');
                this._refreshProject(data.project_id);
                break;

            case 'log':
                this._appendLog(data);
                break;
        }
    }

    _showToast(message, type = 'info') {
        if (typeof showToast === 'function') {
            showToast(message, type);
        }
    }

    _updateStageStatus(projectId, stage) {
        const stageEl = document.querySelector(`[data-project="${projectId}"][data-stage="${stage}"]`);
        if (stageEl) {
            stageEl.classList.add('pulse-soft');
        }
    }

    _updateProgress(projectId, percent, message) {
        const progressBar = document.querySelector(`[data-project="${projectId}"] .progress-bar`);
        if (progressBar) {
            progressBar.style.width = `${percent}%`;
        }

        const progressText = document.querySelector(`[data-project="${projectId}"] .progress-text`);
        if (progressText && message) {
            progressText.textContent = message;
        }
    }

    _showPrimaryCandidates(data) {
        // Trigger HTMX to load the candidates modal
        const container = document.getElementById('modal-container');
        if (container) {
            htmx.ajax('GET', `/api/project/${data.project_id}/candidates`, {
                target: '#modal-container',
                swap: 'innerHTML'
            });
        }
    }

    _updateSceneImage(data) {
        const sceneCard = document.querySelector(`[data-scene="${data.scene_number}"]`);
        if (sceneCard) {
            const img = sceneCard.querySelector('.scene-image');
            if (img) {
                img.src = `/projects/${data.project_id}/scene_${data.scene_number}/image.png?t=${Date.now()}`;
            }
        }
    }

    _updateSceneVideo(data) {
        const sceneCard = document.querySelector(`[data-scene="${data.scene_number}"]`);
        if (sceneCard) {
            sceneCard.classList.add('video-ready');
            const badge = sceneCard.querySelector('.status-badge');
            if (badge) {
                badge.textContent = 'Video Ready';
                badge.classList.remove('bg-yellow-100', 'text-yellow-800');
                badge.classList.add('bg-green-100', 'text-green-800');
            }
        }
    }

    _showApprovalModal(data) {
        htmx.ajax('GET', `/api/project/${data.project_id}/scene/${data.scene_number}/approve`, {
            target: '#modal-container',
            swap: 'innerHTML'
        });
    }

    _refreshProject(projectId) {
        const projectView = document.querySelector(`[data-project="${projectId}"]`);
        if (projectView) {
            htmx.trigger(projectView, 'refresh');
        }
    }

    _appendLog(data) {
        const logsContainer = document.getElementById('logs-container');
        if (logsContainer) {
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry log-${data.level} flex items-start space-x-2 py-1 text-sm`;

            const time = new Date().toLocaleTimeString();
            logEntry.innerHTML = `
                <span class="text-gray-400 font-mono">${time}</span>
                <span class="text-${data.level === 'error' ? 'red' : data.level === 'warning' ? 'yellow' : 'gray'}-600">
                    [${data.source || 'system'}]
                </span>
                <span class="text-gray-700">${data.message}</span>
            `;

            logsContainer.appendChild(logEntry);
            logsContainer.scrollTop = logsContainer.scrollHeight;
        }
    }
}

// Create global instance
window.wsClient = new WebSocketClient();

// Auto-connect when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.wsClient.connect();
});

// Reconnect on visibility change (when user returns to tab)
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        window.wsClient.connect();
    }
});
