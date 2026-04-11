// Main application — initializes everything and manages WebSocket
const App = {
    ws: null,
    reconnectDelay: 1000,
    maxReconnectDelay: 30000,
    reconnectAttempts: 0,
    maxReconnectAttempts: 50,
    connectionState: 'disconnected', // 'connecting', 'connected', 'disconnected', 'error'
    reconnectTimer: null,
    isPageVisible: true,
    _epicRefreshTimer: null,

    // Delegate auto-scroll to DialogCore
    autoScroll(element) {
        DialogCore.autoScroll(element);
    },

    init() {
        Theme.init();
        Sound.init();

        // Initialize board with server-rendered items (include data attrs so
        // renderDoneColumn() can group done cards by date instead of clearing them)
        const cards = document.querySelectorAll('.card');
        const items = [];
        cards.forEach(card => {
            const item = { id: card.dataset.id, column_name: card.dataset.column };
            if (card.dataset.status) item.status = card.dataset.status;
            if (card.dataset.title) item.title = card.dataset.title;
            if (card.dataset.doneAt) item.done_at = card.dataset.doneAt;
            if (card.dataset.updatedAt) item.updated_at = card.dataset.updatedAt;
            if (card.dataset.epicId) item.epic_id = card.dataset.epicId;
            if (card.dataset.startCopy === 'true') item.start_copy = true;
            items.push(item);
        });
        Board.init(items);

        // Wire up top bar buttons
        document.getElementById('new-item-btn')?.addEventListener('click', () => {
            Dialogs.openNewItem();
        });
        document.getElementById('notifications-btn')?.addEventListener('click', () => {
            Dialogs.openNotifications();
        });
        document.getElementById('config-btn')?.addEventListener('click', () => {
            Dialogs.openConfig();
        });

        // Initialize notification polling
        NotificationDialog.init();

        // Close dialogs on backdrop click
        document.querySelectorAll('.modal').forEach(dialog => {
            dialog.addEventListener('click', (e) => {
                if (e.target === dialog) dialog.close();
            });
        });

        // Escape key closes dialogs, Ctrl+R forces WebSocket reconnect
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal[open]').forEach(d => d.close());
            } else if (e.ctrlKey && e.key === 'r' && e.shiftKey) {
                e.preventDefault();
                this.forceReconnect();
            }
        });

        // Page visibility handling for connection management
        document.addEventListener('visibilitychange', () => {
            this.isPageVisible = !document.hidden;

            if (this.isPageVisible) {
                console.log('Page became visible, checking WebSocket connection');
                // If we're disconnected and page became visible, try to reconnect
                if (this.connectionState === 'disconnected' || this.connectionState === 'error') {
                    this.connectWS();
                }
            } else {
                console.log('Page became hidden, pausing reconnection attempts');
                // Clear any pending reconnect timers when page is hidden
                if (this.reconnectTimer) {
                    clearTimeout(this.reconnectTimer);
                    this.reconnectTimer = null;
                }
            }
        });

        // Allow clicking connection status to manually reconnect
        document.addEventListener('click', (e) => {
            if (e.target && e.target.id === 'connection-status') {
                this.forceReconnect();
            }
        });

        // Tooltips — append inside the nearest dialog (top layer) or body
        let tipEl = null;
        document.addEventListener('mouseenter', (e) => {
            if (!e.target || !e.target.closest) return;
            const t = e.target.closest('[data-tip-html]');
            if (!t) return;
            const html = t.getAttribute('data-tip-html');
            if (!html) return;
            tipEl = document.createElement('div');
            tipEl.className = 'tooltip-popup';
            tipEl.innerHTML = html;
            // Append inside the open dialog so it's in the top layer
            const dialog = t.closest('dialog[open]');
            const container = dialog || document.body;
            container.appendChild(tipEl);
            const rect = t.getBoundingClientRect();
            const tipRect = tipEl.getBoundingClientRect();
            let top = rect.top - tipRect.height - 8;
            let left = rect.left + rect.width / 2 - tipRect.width / 2;
            if (top < 4) top = rect.bottom + 8;
            if (left < 4) left = 4;
            if (left + tipRect.width > window.innerWidth - 4) left = window.innerWidth - tipRect.width - 4;
            tipEl.style.top = top + 'px';
            tipEl.style.left = left + 'px';
        }, true);
        document.addEventListener('mouseleave', (e) => {
            // Ensure we have an Element (not a text node or other node type)
            const target = e.target.nodeType === Node.ELEMENT_NODE ? e.target : e.target.parentElement;
            if (target && target.closest('[data-tip-html]') && tipEl) {
                tipEl.remove();
                tipEl = null;
            }
        }, true);

        // Collapse archive column by default
        const archiveCol = document.querySelector('.column[data-column="archive"]');
        if (archiveCol) {
            archiveCol.classList.add('collapsed');
            archiveCol.querySelector('.column-header').addEventListener('click', () => {
                archiveCol.classList.toggle('collapsed');
            });
        }

        // Handle page unload to cleanup WebSocket connection
        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });

        // Initialize shortcuts bar
        if (typeof Shortcuts !== 'undefined') {
            Shortcuts.init();
        }

        // Connect WebSocket
        this.connectWS();
    },

    cleanup() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.close(1000, 'Page unload');
        }

        this.connectionState = 'disconnected';
    },

    connectWS() {
        // Clear any existing reconnect timer
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        // Don't attempt to connect if we've exceeded max attempts
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`Max reconnection attempts (${this.maxReconnectAttempts}) exceeded`);
            this.connectionState = 'error';
            this.updateConnectionStatus();
            return;
        }

        // Don't reconnect if page is not visible (saves resources)
        if (!this.isPageVisible) {
            console.log('Page not visible, deferring WebSocket connection');
            return;
        }

        this.connectionState = 'connecting';
        this.updateConnectionStatus();

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';

        try {
            // Close existing connection if any
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.close();
            }

            this.ws = new WebSocket(`${protocol}//${location.host}/ws`);
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.connectionState = 'connected';
            this.reconnectDelay = 1000;
            this.reconnectAttempts = 0;
            this.updateConnectionStatus();
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this.handleEvent(msg.type, msg.data);
            } catch (error) {
                console.error('Failed to parse WebSocket message:', error);
            }
        };

        this.ws.onclose = (event) => {
            console.log(`WebSocket disconnected (code: ${event.code}, reason: ${event.reason})`);
            this.connectionState = 'disconnected';
            this.updateConnectionStatus();

            // Don't reconnect if it was a clean close initiated by us
            if (event.code === 1000) {
                return;
            }

            this.scheduleReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.connectionState = 'error';
            this.updateConnectionStatus();
        };
    },

    scheduleReconnect() {
        this.reconnectAttempts++;

        // Exponential backoff with jitter
        const jitter = Math.random() * 1000;
        const delay = Math.min(this.reconnectDelay + jitter, this.maxReconnectDelay);

        console.log(`Scheduling reconnect attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${Math.round(delay)}ms`);

        this.reconnectTimer = setTimeout(() => {
            this.connectWS();
        }, delay);

        // Exponential backoff
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
    },

    updateConnectionStatus() {
        // Add/update connection status indicator as a colored dot
        let statusEl = document.getElementById('connection-status');
        if (!statusEl) {
            statusEl = document.createElement('div');
            statusEl.id = 'connection-status';
            statusEl.style.cssText = `
                width: 8px;
                height: 8px;
                border-radius: 50%;
                margin-left: 8px;
                transition: all 0.3s ease;
                cursor: pointer;
            `;

            // Insert the dot after the theme toggle button
            const themeToggle = document.getElementById('theme-toggle');
            if (themeToggle && themeToggle.parentNode) {
                themeToggle.parentNode.appendChild(statusEl);
            } else {
                // Fallback to body if theme toggle not found
                document.body.appendChild(statusEl);
            }
        }

        const states = {
            'connecting': { text: 'Connecting...', color: '#ff9800' },
            'connected': { text: 'Connected', color: '#4caf50' },
            'disconnected': { text: 'Disconnected', color: '#f44336' },
            'error': { text: 'Connection Error', color: '#f44336' }
        };

        const state = states[this.connectionState] || states.disconnected;
        statusEl.style.backgroundColor = state.color;
        statusEl.style.boxShadow = `0 0 4px ${state.color}40`;

        // Add tooltip for accessibility
        statusEl.title = state.text;

        // Fade the dot when connected after a delay
        if (this.connectionState === 'connected') {
            setTimeout(() => {
                if (statusEl && this.connectionState === 'connected') {
                    statusEl.style.opacity = '0.6';
                }
            }, 2000);
        } else {
            statusEl.style.opacity = '1';
        }
    },

    // Manual reconnection method
    forceReconnect() {
        console.log('Forcing WebSocket reconnection...');
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;

        if (this.ws) {
            this.ws.close(1000, 'Manual reconnect');
        }

        setTimeout(() => this.connectWS(), 100);
    },

    _refreshEpicsDebounced() {
        clearTimeout(this._epicRefreshTimer);
        this._epicRefreshTimer = setTimeout(() => Board.loadEpics(), 500);
    },

    handleEvent(type, data) {
        switch (type) {
            case 'item_created':
            case 'item_updated':
            case 'item_moved':
                Board.updateCard(data);
                // Refresh epic progress — column changes affect done/total counts
                this._refreshEpicsDebounced();

                // Play notification sound only when an agent moves an item (not user actions)
                if (data._source === 'agent' && data.column_name && data.column_name !== 'doing' && data.column_name !== 'todo') {
                    Sound.playChime();
                }

                // Auto-transition: if the detail dialog is open for this item
                // and the task ended (moved column or status changed), transition
                // to the appropriate dialog (review, clarify, or refreshed detail)
                if (data.id && Dialogs._currentItemId === data.id) {
                    const detailDialog = document.getElementById('detail-dialog');
                    if (detailDialog && detailDialog.open) {
                        const itemId = data.id;
                        const movedOut = data.column_name && data.column_name !== 'doing';
                        const ended = data.status && data.status !== 'running' && data.status !== 'resolving_conflicts';
                        if (movedOut || ended) {
                            Dialogs.close('detail-dialog');
                            // showDetail auto-routes to review/questions dialogs based on column
                            Dialogs.showDetail(itemId);
                        }
                    }
                }
                break;
            case 'item_deleted':
                Board.removeCard(data.id);
                this._refreshEpicsDebounced();
                break;
            case 'agent_log':
                this.appendLog(data);
                this.incrementLogCount(data.item_id);
                break;
            case 'clarification_requested':
                Dialogs.showClarification(
                    data.item_id,
                    data.prompt,
                    data.choices ? JSON.parse(data.choices) : []
                );
                break;
            case 'permission_requested':
                ClarificationDialog.showPermissionRequest(
                    data.item_id, data.command, data.reason
                );
                break;
            case 'merge_blocked':
                ClarificationDialog.showMergeBlocked(data.item_id, data.message);
                break;
            case 'tool_permission_requested':
                ClarificationDialog.showToolPermissionRequest(
                    data.item_id, data.tool_name, data.reason
                );
                break;
            case 'dependencies_changed':
            case 'dependencies_resolved':
                // Refresh blocked status when dependencies change or are resolved
                Board.loadBlockedStatus().then(() => Board.renderTodoColumn());
                break;
            case 'blocked_status_changed':
                Board.updateBlockedStatus(data.blocked || {});
                break;
            case 'notification_added':
                NotificationDialog.addFromEvent(data);
                break;
            case 'shortcut_created':
                if (typeof Shortcuts !== 'undefined') {
                    Shortcuts.load().then(() => Shortcuts.render());
                }
                break;
            case 'yolo_mode_changed':
                Board.setYoloMode(data.item_id, data.active);
                break;
            case 'epic_created':
            case 'epic_updated':
            case 'epic_deleted':
                Board.loadEpics();
                if (type === 'epic_deleted') {
                    Board.loadAndRender();
                }
                break;
            default:
                console.log('Unknown event:', type, data);
        }

        // Update stats for relevant events
        if (window.statsManager) {
            window.statsManager.handleRealtimeUpdate(type, data);
        }
    },

    appendLog(data) {
        // Only append logs if they're for the currently open item
        if (!data.item_id || !Dialogs._currentItemId || data.item_id !== Dialogs._currentItemId) {
            return; // Skip logs for other items
        }

        // Append to detail dialog log if it's open for this item
        const detailLogEl = document.getElementById('detail-log');
        if (detailLogEl) {
            const entry = document.createElement('div');
            entry.className = `log-entry log-entry-${data.entry_type}`;
            entry.innerHTML = `<span class="log-meta">[${data.entry_type}]</span> <div class="log-content">${Dialogs.renderMarkdown(data.content)}</div>`;
            detailLogEl.appendChild(entry);
            // Use the reliable auto-scroll utility
            this.autoScroll(detailLogEl);
        }

        // Also append to review dialog log if it's open for this item
        const reviewLogEl = document.getElementById('review-log');
        if (reviewLogEl) {
            const entry = document.createElement('div');
            entry.className = `log-entry log-entry-${data.entry_type}`;
            entry.innerHTML = `<span class="log-meta">[${data.entry_type}]</span> <div class="log-content">${Dialogs.renderMarkdown(data.content)}</div>`;
            reviewLogEl.appendChild(entry);
            // Use the reliable auto-scroll utility
            this.autoScroll(reviewLogEl);
        }
    },

    incrementLogCount(itemId) {
        // Update the items cache so count survives card re-renders
        if (Board.items[itemId]) {
            Board.items[itemId].log_count = (Board.items[itemId].log_count || 0) + 1;
        }

        const el = document.querySelector(`[data-log-count="${itemId}"]`);
        if (el) {
            const current = parseInt(el.textContent.replace(/\D/g, ''), 10) || 0;
            el.textContent = `${current + 1}`;
        } else {
            // Card exists but no counter yet — add one inside card-bottom
            const card = document.querySelector(`.card[data-id="${itemId}"]`);
            if (card) {
                const bottom = card.querySelector('.card-bottom');
                if (bottom) {
                    const counter = document.createElement('div');
                    counter.className = 'card-log-count';
                    counter.setAttribute('data-log-count', itemId);
                    counter.textContent = '1';
                    bottom.appendChild(counter);
                }
            }
        }
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
