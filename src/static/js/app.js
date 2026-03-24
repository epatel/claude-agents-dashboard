// Main application — initializes everything and manages WebSocket
const App = {
    ws: null,
    reconnectDelay: 1000,

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

        // Escape key closes dialogs
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal[open]').forEach(d => d.close());
            }
        });

        // Tooltips — position with JS to escape overflow containers
        let tipEl = null;
        document.addEventListener('mouseenter', (e) => {
            const t = e.target.closest('.tooltip');
            if (!t) return;
            const text = t.getAttribute('data-tip');
            if (!text) return;
            tipEl = document.createElement('div');
            tipEl.className = 'tooltip-popup';
            tipEl.textContent = text;
            document.body.appendChild(tipEl);
            const rect = t.getBoundingClientRect();
            const tipRect = tipEl.getBoundingClientRect();
            let top = rect.top - tipRect.height - 8;
            let left = rect.left + rect.width / 2 - tipRect.width / 2;
            // Keep on screen
            if (top < 4) top = rect.bottom + 8;
            if (left < 4) left = 4;
            if (left + tipRect.width > window.innerWidth - 4) left = window.innerWidth - tipRect.width - 4;
            tipEl.style.top = top + 'px';
            tipEl.style.left = left + 'px';
        }, true);
        document.addEventListener('mouseleave', (e) => {
            if (e.target.closest('.tooltip') && tipEl) {
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

        // Connect WebSocket
        this.connectWS();
    },

    connectWS() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}/ws`);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectDelay = 1000;
        };

        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this.handleEvent(msg.type, msg.data);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting...');
            setTimeout(() => this.connectWS(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 10000);
        };
    },

    handleEvent(type, data) {
        switch (type) {
            case 'item_created':
            case 'item_updated':
            case 'item_moved':
                Board.updateCard(data);
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
    },

    appendLog(data) {
        // Append to detail dialog log if it's open for this item
        const logEl = document.getElementById('detail-log');
        if (logEl) {
            const entry = document.createElement('div');
            entry.className = `log-entry log-entry-${data.entry_type}`;
            entry.innerHTML = `<span class="log-meta">[${data.entry_type}]</span> <div class="log-content">${Dialogs.renderMarkdown(data.content)}</div>`;
            logEl.appendChild(entry);
            logEl.scrollTop = logEl.scrollHeight;
        }
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
