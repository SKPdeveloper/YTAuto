/**
 * Dashboard UI Logic
 *
 * Handles user interactions, scene management, and prompt editing.
 */

// Scene Management
const SceneManager = {
    /**
     * Select a candidate image for PRIMARY scene
     */
    selectCandidate(projectId, candidateIndex) {
        htmx.ajax('POST', `/api/project/${projectId}/select-candidate`, {
            values: { candidate_index: candidateIndex },
            target: '#modal-container',
            swap: 'innerHTML'
        }).then(() => {
            showToast('Candidate selected', 'success');
        });
    },

    /**
     * Approve a scene image
     */
    approveScene(projectId, sceneNumber) {
        htmx.ajax('POST', `/api/project/${projectId}/scene/${sceneNumber}/approve`, {
            target: `[data-scene="${sceneNumber}"]`,
            swap: 'outerHTML'
        }).then(() => {
            showToast(`Scene ${sceneNumber} approved`, 'success');
        });
    },

    /**
     * Reject and regenerate a scene image
     */
    rejectScene(projectId, sceneNumber, reason) {
        htmx.ajax('POST', `/api/project/${projectId}/scene/${sceneNumber}/reject`, {
            values: { reason: reason },
            target: `[data-scene="${sceneNumber}"]`,
            swap: 'outerHTML'
        }).then(() => {
            showToast(`Scene ${sceneNumber} queued for regeneration`, 'info');
        });
    },

    /**
     * Open prompt editor for a scene
     */
    editPrompt(projectId, sceneNumber) {
        htmx.ajax('GET', `/api/project/${projectId}/scene/${sceneNumber}/edit`, {
            target: '#modal-container',
            swap: 'innerHTML'
        });
    },

    /**
     * Save edited prompt
     */
    savePrompt(projectId, sceneNumber, promptType, newPrompt) {
        htmx.ajax('POST', `/api/project/${projectId}/scene/${sceneNumber}/prompt`, {
            values: {
                prompt_type: promptType,
                prompt: newPrompt
            },
            target: '#modal-container',
            swap: 'innerHTML'
        }).then(() => {
            showToast('Prompt saved', 'success');
        });
    }
};

// Project Management
const ProjectManager = {
    /**
     * Start a new project
     */
    startProject(channelId, topic) {
        htmx.ajax('POST', `/api/channel/${channelId}/project`, {
            values: { topic: topic },
            target: '#projects-list',
            swap: 'afterbegin'
        }).then(() => {
            showToast('Project started', 'success');
            closeModal();
        });
    },

    /**
     * Resume a paused project
     */
    resumeProject(projectId) {
        htmx.ajax('POST', `/api/project/${projectId}/resume`, {
            target: `[data-project="${projectId}"]`,
            swap: 'outerHTML'
        }).then(() => {
            showToast('Project resumed', 'info');
        });
    },

    /**
     * Pause a running project
     */
    pauseProject(projectId) {
        htmx.ajax('POST', `/api/project/${projectId}/pause`, {
            target: `[data-project="${projectId}"]`,
            swap: 'outerHTML'
        }).then(() => {
            showToast('Project paused', 'info');
        });
    },

    /**
     * Delete a project
     */
    deleteProject(projectId) {
        if (confirm('Are you sure you want to delete this project?')) {
            htmx.ajax('DELETE', `/api/project/${projectId}`, {
                target: `[data-project="${projectId}"]`,
                swap: 'outerHTML'
            }).then(() => {
                showToast('Project deleted', 'success');
            });
        }
    }
};

// Modal Helpers
function closeModal() {
    const modal = document.querySelector('.modal-backdrop');
    if (modal) {
        modal.remove();
    }
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Escape to close modal
    if (e.key === 'Escape') {
        closeModal();
    }

    // Ctrl+Enter to submit forms in modal
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const modal = document.querySelector('.modal-backdrop');
        if (modal) {
            const submitBtn = modal.querySelector('[type="submit"]');
            if (submitBtn) {
                submitBtn.click();
            }
        }
    }
});

// Image Preview
function openImagePreview(imageSrc) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black/90 z-50 flex items-center justify-center cursor-pointer';
    overlay.onclick = () => overlay.remove();

    overlay.innerHTML = `
        <img src="${imageSrc}" class="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl">
        <button class="absolute top-4 right-4 text-white hover:text-gray-300">
            <i data-lucide="x" class="w-8 h-8"></i>
        </button>
    `;

    document.body.appendChild(overlay);
    lucide.createIcons();
}

// Video Preview
function openVideoPreview(videoSrc) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 bg-black/90 z-50 flex items-center justify-center';
    overlay.onclick = (e) => {
        if (e.target === overlay) overlay.remove();
    };

    overlay.innerHTML = `
        <div class="relative">
            <video src="${videoSrc}" controls autoplay class="max-w-[90vw] max-h-[90vh] rounded-lg shadow-2xl"></video>
            <button onclick="this.parentElement.parentElement.remove()" class="absolute -top-4 -right-4 bg-white rounded-full p-2 text-gray-800 hover:bg-gray-100">
                <i data-lucide="x" class="w-6 h-6"></i>
            </button>
        </div>
    `;

    document.body.appendChild(overlay);
    lucide.createIcons();
}

// Logs Viewer
const LogsViewer = {
    container: null,
    autoScroll: true,

    init() {
        this.container = document.getElementById('logs-container');
        if (this.container) {
            // Auto-scroll when new logs arrive
            wsClient.on('log', () => {
                if (this.autoScroll) {
                    this.scrollToBottom();
                }
            });
        }
    },

    scrollToBottom() {
        if (this.container) {
            this.container.scrollTop = this.container.scrollHeight;
        }
    },

    toggleAutoScroll() {
        this.autoScroll = !this.autoScroll;
        const btn = document.getElementById('autoscroll-btn');
        if (btn) {
            btn.classList.toggle('text-green-600', this.autoScroll);
            btn.classList.toggle('text-gray-400', !this.autoScroll);
        }
    },

    clear() {
        if (this.container) {
            this.container.innerHTML = '';
        }
    },

    filter(level) {
        const entries = this.container?.querySelectorAll('.log-entry');
        entries?.forEach(entry => {
            if (level === 'all') {
                entry.style.display = '';
            } else {
                entry.style.display = entry.classList.contains(`log-${level}`) ? '' : 'none';
            }
        });
    }
};

// Progress Tracker
const ProgressTracker = {
    stages: [
        'script_generation',
        'image_generation',
        'image_validation',
        'video_generation',
        'post_processing'
    ],

    update(projectId, currentStage, progress) {
        const container = document.querySelector(`[data-project="${projectId}"] .stages-tracker`);
        if (!container) return;

        const currentIndex = this.stages.indexOf(currentStage);

        this.stages.forEach((stage, index) => {
            const stageEl = container.querySelector(`[data-stage="${stage}"]`);
            if (!stageEl) return;

            // Remove all status classes
            stageEl.classList.remove('completed', 'active', 'pending');

            if (index < currentIndex) {
                stageEl.classList.add('completed');
            } else if (index === currentIndex) {
                stageEl.classList.add('active');
                // Update progress bar if present
                const bar = stageEl.querySelector('.stage-progress');
                if (bar) {
                    bar.style.width = `${progress}%`;
                }
            } else {
                stageEl.classList.add('pending');
            }
        });
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    LogsViewer.init();

    // Listen for WebSocket events
    if (window.wsClient) {
        wsClient.on('stage_changed', (data) => {
            ProgressTracker.update(data.project_id, data.stage, 0);
        });

        wsClient.on('progress', (data) => {
            ProgressTracker.update(data.project_id, data.stage, data.progress_percent);
        });
    }
});

// Expose to window for inline handlers
window.SceneManager = SceneManager;
window.ProjectManager = ProjectManager;
window.closeModal = closeModal;
window.openImagePreview = openImagePreview;
window.openVideoPreview = openVideoPreview;
window.LogsViewer = LogsViewer;
window.ProgressTracker = ProgressTracker;
