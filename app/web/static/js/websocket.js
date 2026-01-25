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
                if (data.approval_type === 'video_pre_upscale') {
                    this._showVideoApprovalModal(data);
                } else {
                    this._showApprovalModal(data);
                }
                break;

            case 'video_approval_decision':
                this._handleVideoApprovalDecision(data);
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

    _showVideoApprovalModal(data) {
        // Create video approval modal
        const modal = document.getElementById('modal-container');
        if (!modal) return;

        const videoUrl = data.video_url || `/projects/${data.project_id}/assembled_video.mp4`;

        modal.innerHTML = `
            <div class="modal-backdrop fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
                <div class="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
                    <!-- Header -->
                    <div class="p-4 border-b border-gray-200 flex items-center justify-between">
                        <h2 class="text-xl font-bold text-gray-800 flex items-center gap-2">
                            <i data-lucide="film" class="w-6 h-6 text-purple-600"></i>
                            Video Review (Pre-Upscale)
                        </h2>
                        <button onclick="this.closest('.modal-backdrop').remove()" class="text-gray-400 hover:text-gray-600">
                            <i data-lucide="x" class="w-6 h-6"></i>
                        </button>
                    </div>

                    <!-- Video Preview (9:16 aspect ratio) -->
                    <div class="p-4 flex justify-center bg-gray-100">
                        <div class="w-full max-w-[270px] aspect-[9/16] rounded-lg overflow-hidden shadow-lg bg-black">
                            <video
                                src="${videoUrl}"
                                class="w-full h-full object-contain"
                                controls
                                autoplay
                                loop
                                muted>
                            </video>
                        </div>
                    </div>

                    <!-- Info -->
                    <div class="px-4 py-2 bg-blue-50 text-blue-700 text-sm">
                        <i data-lucide="info" class="w-4 h-4 inline mr-1"></i>
                        Review the assembled video before Topaz upscaling. Upscaling is time-consuming and cannot be undone.
                    </div>

                    <!-- Actions -->
                    <div class="p-4 bg-gray-50 flex flex-col gap-2">
                        <button
                            onclick="submitVideoApproval('approved')"
                            class="w-full py-3 px-4 bg-green-600 hover:bg-green-700 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors">
                            <i data-lucide="check" class="w-5 h-5"></i>
                            Approve & Start Upscaling
                        </button>

                        <button
                            onclick="submitVideoApproval('skip_upscale')"
                            class="w-full py-3 px-4 bg-yellow-500 hover:bg-yellow-600 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors">
                            <i data-lucide="fast-forward" class="w-5 h-5"></i>
                            Skip Upscaling (Mark Complete)
                        </button>

                        <button
                            onclick="submitVideoApproval('rejected')"
                            class="w-full py-3 px-4 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors">
                            <i data-lucide="x" class="w-5 h-5"></i>
                            Reject & Stop Pipeline
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Re-init Lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }

    _handleVideoApprovalDecision(data) {
        // Close modal
        const modal = document.querySelector('.modal-backdrop');
        if (modal) modal.remove();

        // Show toast based on decision
        const messages = {
            'approved': 'Video approved! Starting upscaling...',
            'skip_upscale': 'Upscaling skipped. Project marked as complete.',
            'rejected': 'Video rejected. Pipeline stopped.'
        };
        const types = {
            'approved': 'success',
            'skip_upscale': 'warning',
            'rejected': 'error'
        };

        this._showToast(messages[data.decision] || 'Decision recorded', types[data.decision] || 'info');
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

// Global function for video approval submission
async function submitVideoApproval(decision) {
    try {
        const response = await fetch('/api/control/video-approval', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ decision })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to submit approval');
        }

        // Modal will be closed by WebSocket event
    } catch (error) {
        console.error('Video approval error:', error);
        showToast(`Error: ${error.message}`, 'error');
    }
}
