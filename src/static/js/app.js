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
        Board.init(this._serverRenderedItems());
        this._wireTopBar();
        // Initialize notification polling
        NotificationDialog.init();
        this._wireDialogKeys();
        this._wireConnectionHandling();
        this._wireTooltips();
        this._collapseArchiveColumn();
        this._wireUnload();

        // Initialize shortcuts bar
        if (typeof Shortcuts !== 'undefined') {
            Shortcuts.init();
        }

        // Connect WebSocket
        this.connectWS();
    },

    /** Card ``data-*`` attribute → item field, copied when present. */
    _cardFields: [
        ['status', 'status'], ['title', 'title'], ['doneAt', 'done_at'],
        ['updatedAt', 'updated_at'], ['epicId', 'epic_id'],
    ],

    // Items for the server-rendered cards (include data attrs so
    // renderDoneColumn() can group done cards by date instead of clearing them)
    _serverRenderedItems() {
        return Array.from(document.querySelectorAll('.card'), card => {
            const item = { id: card.dataset.id, column_name: card.dataset.column };
            for (const [attr, field] of this._cardFields) {
                if (card.dataset[attr]) item[field] = card.dataset[attr];
            }
            if (card.dataset.startCopy === 'true') item.start_copy = true;
            return item;
        });
    },

    _wireTopBar() {
        document.getElementById('new-item-btn')?.addEventListener('click', () => {
            Dialogs.openNewItem();
        });
        document.getElementById('notifications-btn')?.addEventListener('click', () => {
            Dialogs.openNotifications();
        });
        document.getElementById('config-btn')?.addEventListener('click', () => {
            Dialogs.openConfig();
        });
    },

    /** Backdrop click and Escape close dialogs; Ctrl+Shift+R forces a WebSocket reconnect. */
    _wireDialogKeys() {
        document.querySelectorAll('.modal').forEach(dialog => {
            dialog.addEventListener('click', (e) => {
                if (e.target === dialog) dialog.close();
            });
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal[open]').forEach(d => d.close());
            } else if (this._isReconnectKey(e)) {
                e.preventDefault();
                this.forceReconnect();
            }
        });
    },

    _isReconnectKey(e) {
        if (e.key !== 'r') return false;
        return e.ctrlKey && e.shiftKey;
    },

    /** Reconnect when the page becomes visible; click the status dot to reconnect. */
    _wireConnectionHandling() {
        document.addEventListener('visibilitychange', () => this._onVisibilityChange());
        document.addEventListener('click', (e) => {
            if (e.target && e.target.id === 'connection-status') {
                this.forceReconnect();
            }
        });
    },

    _onVisibilityChange() {
        this.isPageVisible = !document.hidden;
        if (this.isPageVisible) {
            console.log('Page became visible, checking WebSocket connection');
            // If we're disconnected and page became visible, try to reconnect
            if (this.connectionState === 'disconnected' || this.connectionState === 'error') {
                this.connectWS();
            }
            return;
        }
        console.log('Page became hidden, pausing reconnection attempts');
        // Clear any pending reconnect timers when page is hidden
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    },

    // Tooltips — append inside the nearest dialog (top layer) or body
    _wireTooltips() {
        let tipEl = null;
        document.addEventListener('mouseenter', (e) => {
            if (!e.target || !e.target.closest) return;
            const t = e.target.closest('[data-tip-html]');
            const html = t && t.getAttribute('data-tip-html');
            if (html) tipEl = this._showTooltip(t, html);
        }, true);
        document.addEventListener('mouseleave', (e) => {
            // Ensure we have an Element (not a text node or other node type)
            const target = e.target.nodeType === Node.ELEMENT_NODE ? e.target : e.target.parentElement;
            if (!tipEl || !target) return;
            if (target.closest('[data-tip-html]')) {
                tipEl.remove();
                tipEl = null;
            }
        }, true);
    },

    /** A tooltip for ``t``, above it (below if no room) and kept inside the window. */
    _showTooltip(t, html) {
        const tipEl = document.createElement('div');
        tipEl.className = 'tooltip-popup';
        tipEl.innerHTML = html;
        // Append inside the open dialog so it's in the top layer
        (t.closest('dialog[open]') || document.body).appendChild(tipEl);
        const rect = t.getBoundingClientRect();
        const tipRect = tipEl.getBoundingClientRect();
        let top = rect.top - tipRect.height - 8;
        if (top < 4) top = rect.bottom + 8;
        const maxLeft = window.innerWidth - tipRect.width - 4;
        let left = Math.max(4, rect.left + rect.width / 2 - tipRect.width / 2);
        if (left > maxLeft) left = maxLeft;
        tipEl.style.top = top + 'px';
        tipEl.style.left = left + 'px';
        return tipEl;
    },

    // Collapse archive column by default
    _collapseArchiveColumn() {
        const archiveCol = document.querySelector('.column[data-column="archive"]');
        if (!archiveCol) return;
        archiveCol.classList.add('collapsed');
        archiveCol.querySelector('.column-header').addEventListener('click', () => {
            archiveCol.classList.toggle('collapsed');
        });
    },

    // Handle page unload to cleanup WebSocket connection.
    // Both events are registered because 'pagehide' fires more
    // reliably in WKWebView (macOS wrapper) while 'beforeunload'
    // is the traditional fallback for regular browsers.
    _wireUnload() {
        window.addEventListener('beforeunload', () => {
            this.cleanup();
        });
        window.addEventListener('pagehide', () => {
            this.cleanup();
        });
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
                // Respond to server heartbeat pings to keep connection alive
                if (msg.type === 'ping') {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({type: 'pong'}));
                    }
                    return;
                }
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

    _connectionStates: {
        'connecting': { text: 'Connecting...', color: '#ff9800' },
        'connected': { text: 'Connected', color: '#4caf50' },
        'disconnected': { text: 'Disconnected', color: '#f44336' },
        'error': { text: 'Connection Error', color: '#f44336' }
    },

    updateConnectionStatus() {
        const statusEl = this._connectionStatusEl();
        const states = this._connectionStates;
        const state = Object.hasOwn(states, this.connectionState) ? states[this.connectionState] : states.disconnected;
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

    /** The connection status dot, created after the theme toggle (or in body) on first use. */
    _connectionStatusEl() {
        const existing = document.getElementById('connection-status');
        if (existing) return existing;
        const statusEl = document.createElement('div');
        statusEl.id = 'connection-status';
        statusEl.style.cssText = `
                width: 8px;
                height: 8px;
                border-radius: 50%;
                margin-left: 8px;
                transition: all 0.3s ease;
                cursor: pointer;
            `;
        // Insert the dot after the theme toggle button, falling back to body
        const themeToggle = document.getElementById('theme-toggle');
        (themeToggle?.parentNode || document.body).appendChild(statusEl);
        return statusEl;
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

    /** WebSocket event type → handler method (called with ``data, type``). */
    _eventHandlers: {
        item_created: '_onItemChanged',
        item_updated: '_onItemChanged',
        item_moved: '_onItemChanged',
        item_deleted: '_onItemDeleted',
        agent_log: '_onAgentLog',
        clarification_requested: '_onClarificationRequested',
        permission_requested: '_onPermissionRequested',
        merge_blocked: '_onMergeBlocked',
        tool_permission_requested: '_onToolPermissionRequested',
        dependencies_changed: '_onDependenciesChanged',
        dependencies_resolved: '_onDependenciesChanged',
        blocked_status_changed: '_onBlockedStatusChanged',
        notification_added: '_onNotificationAdded',
        shortcut_created: '_onShortcutCreated',
        yolo_mode_changed: '_onYoloModeChanged',
        auto_review_changed: '_onAutoReviewChanged',
        epic_created: '_onEpicChanged',
        epic_updated: '_onEpicChanged',
        epic_deleted: '_onEpicChanged',
        graph_build_progress: '_onGraphProgress',
        graph_ready: '_onGraphProgress',
    },

    handleEvent(type, data) {
        if (Object.hasOwn(this._eventHandlers, type)) {
            this[this._eventHandlers[type]](data, type);
        } else {
            console.log('Unknown event:', type, data);
        }

        // Update stats for relevant events
        if (window.statsManager) {
            window.statsManager.handleRealtimeUpdate(type, data);
        }
    },

    _onItemChanged(data) {
        Board.updateCard(data);
        // Re-render epic sidebar immediately — progress is computed live
        // from Board.items, so the archive button on a freshly-completed
        // epic appears without waiting for the debounced API refresh.
        Board._renderEpicPanel();
        // Still refresh epic progress from server (debounced) — covers
        // any case where the items cache lags behind (e.g. WS gaps).
        this._refreshEpicsDebounced();

        // Play notification sound only when an agent moves an item (not user actions)
        if (data._source === 'agent' && this._leftActiveColumns(data)) {
            Sound.playChime();
        }
        this._refreshOpenDetail(data);
    },

    /** The item moved to a column other than Todo / Doing. */
    _leftActiveColumns(data) {
        if (!data.column_name) return false;
        return data.column_name !== 'doing' && data.column_name !== 'todo';
    },

    // Auto-transition: if the detail dialog is open for this item
    // and the task ended (moved column or status changed), transition
    // to the appropriate dialog (review, clarify, or refreshed detail)
    _refreshOpenDetail(data) {
        if (!data.id || Dialogs._currentItemId !== data.id) return;
        const detailDialog = document.getElementById('detail-dialog');
        if (!detailDialog || !detailDialog.open) return;
        if (this._movedOutOfDoing(data) || this._runEnded(data)) {
            Dialogs.close('detail-dialog');
            // showDetail auto-routes to review/questions dialogs based on column
            Dialogs.showDetail(data.id);
        }
    },

    _movedOutOfDoing(data) {
        return data.column_name && data.column_name !== 'doing';
    },

    _runEnded(data) {
        if (!data.status) return false;
        return data.status !== 'running' && data.status !== 'resolving_conflicts';
    },

    _onItemDeleted(data) {
        Board.removeCard(data.id);
        Board._renderEpicPanel();
        this._refreshEpicsDebounced();
    },

    _onAgentLog(data) {
        this.appendLog(data);
        this.incrementLogCount(data.item_id);
    },

    _onClarificationRequested(data) {
        Dialogs.showClarification(
            data.item_id,
            data.prompt,
            data.choices ? JSON.parse(data.choices) : [],
            data.context
        );
    },

    _onPermissionRequested(data) {
        ClarificationDialog.showPermissionRequest(data.item_id, data.command, data.reason);
    },

    _onMergeBlocked(data) {
        ClarificationDialog.showMergeBlocked(data.item_id, data.message);
    },

    _onToolPermissionRequested(data) {
        ClarificationDialog.showToolPermissionRequest(data.item_id, data.tool_name, data.reason);
    },

    // Refresh blocked status when dependencies change or are resolved
    _onDependenciesChanged() {
        Board.loadBlockedStatus().then(() => Board.renderTodoColumn());
    },

    _onBlockedStatusChanged(data) {
        Board.updateBlockedStatus(data.blocked || {});
    },

    _onNotificationAdded(data) {
        NotificationDialog.addFromEvent(data);
    },

    _onShortcutCreated() {
        if (typeof Shortcuts !== 'undefined') {
            Shortcuts.load().then(() => Shortcuts.render());
        }
    },

    _onYoloModeChanged(data) {
        Board.setYoloMode(data.item_id, data.active);
    },

    _onAutoReviewChanged(data) {
        Board.setAutoReviewing(data.item_id, data.active);
    },

    _onEpicChanged(data, type) {
        Board.loadEpics();
        if (type === 'epic_deleted') {
            Board.loadAndRender();
        }
    },

    // Refresh the Graphify settings tab status if the dialog is open
    _onGraphProgress() {
        if (typeof ConfigDialog !== 'undefined' && document.getElementById('graphify-status')) {
            ConfigDialog.refreshGraphifyStatus();
        }
    },

    appendLog(data) {
        // Only append logs if they're for the currently open item
        if (!this._isCurrentItem(data.item_id)) return;
        // Append to the detail and review dialog logs (whichever exist)
        for (const id of ['detail-log', 'review-log']) {
            const logEl = document.getElementById(id);
            if (logEl) this._appendLogEntry(logEl, data);
        }
    },

    _isCurrentItem(itemId) {
        if (!itemId || !Dialogs._currentItemId) return false;
        return itemId === Dialogs._currentItemId;
    },

    _appendLogEntry(logEl, data) {
        const entry = document.createElement('div');
        entry.className = `log-entry log-entry-${data.entry_type}`;
        entry.innerHTML = `<span class="log-meta">[${data.entry_type}]</span> <div class="log-content">${Dialogs.renderMarkdown(data.content)}</div>`;
        logEl.appendChild(entry);
        Dialogs.runMermaid(entry);
        // Use the reliable auto-scroll utility
        this.autoScroll(logEl);
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
            this._addLogCounter(itemId);
        }
    },

    // Card exists but no counter yet — add one inside card-bottom
    _addLogCounter(itemId) {
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        const bottom = card && card.querySelector('.card-bottom');
        if (!bottom) return;
        const counter = document.createElement('div');
        counter.className = 'card-log-count';
        counter.setAttribute('data-log-count', itemId);
        counter.textContent = '1';
        bottom.appendChild(counter);
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
