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

    // Utility function for reliable auto-scroll
    autoScroll(element) {
        if (!element) return;
        // Use requestAnimationFrame for better performance and reliability
        requestAnimationFrame(() => {
            element.scrollTop = element.scrollHeight;
        });
    },

    init() {
        Theme.init();

        // Initialize board with server-rendered items
        const cards = document.querySelectorAll('.card');
        const items = [];
        cards.forEach(card => {
            items.push({ id: card.dataset.id });
        });
        Board.init(items);

        // Wire up top bar buttons
        document.getElementById('new-item-btn').addEventListener('click', () => {
            Dialogs.openNewItem();
        });
        document.getElementById('config-btn').addEventListener('click', () => {
            Dialogs.openConfig();
        });

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
            const t = e.target.closest('.tooltip');
            if (!t) return;
            const html = t.getAttribute('data-tip-html');
            const text = t.getAttribute('data-tip');
            if (!html && !text) return;
            tipEl = document.createElement('div');
            tipEl.className = 'tooltip-popup';
            if (html) {
                tipEl.innerHTML = html;
            } else {
                tipEl.textContent = text;
            }
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
            if (target && target.closest('.tooltip') && tipEl) {
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
        // Add/update connection status indicator
        let statusEl = document.getElementById('connection-status');
        if (!statusEl) {
            statusEl = document.createElement('div');
            statusEl.id = 'connection-status';
            statusEl.style.cssText = `
                position: fixed;
                top: 10px;
                right: 10px;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                z-index: 1000;
                transition: all 0.3s ease;
            `;
            document.body.appendChild(statusEl);
        }

        const states = {
            'connecting': { text: 'Connecting...', color: '#ff9800', bg: '#fff3e0' },
            'connected': { text: 'Connected', color: '#4caf50', bg: '#e8f5e8' },
            'disconnected': { text: 'Disconnected', color: '#f44336', bg: '#ffebee' },
            'error': { text: 'Connection Error', color: '#f44336', bg: '#ffebee' }
        };

        const state = states[this.connectionState] || states.disconnected;
        statusEl.textContent = state.text;
        statusEl.style.color = state.color;
        statusEl.style.backgroundColor = state.bg;
        statusEl.style.border = `1px solid ${state.color}`;

        // Hide the status indicator when connected after a delay
        if (this.connectionState === 'connected') {
            setTimeout(() => {
                if (statusEl && this.connectionState === 'connected') {
                    statusEl.style.opacity = '0.3';
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

    handleEvent(type, data) {
        switch (type) {
            case 'item_created':
            case 'item_updated':
            case 'item_moved':
                Board.updateCard(data);

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
                            // showDetail auto-routes to review/clarify dialogs based on column
                            Dialogs.showDetail(itemId);
                        }
                    }
                }
                break;
            case 'item_deleted':
                Board.removeCard(data.id);
                break;
            case 'agent_log':
                this.appendLog(data);
                break;
            case 'clarification_requested':
                Dialogs.showClarification(
                    data.item_id,
                    data.prompt,
                    data.choices ? JSON.parse(data.choices) : []
                );
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
};

document.addEventListener('DOMContentLoaded', () => App.init());
