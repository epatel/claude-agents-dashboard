/**
 * Notification dialog — shows system errors/warnings (e.g. MCP server failures).
 */
const NotificationDialog = {
    _notifications: [],
    _pollInterval: null,

    init() {
        // Poll for notifications every 10s
        this._pollInterval = setInterval(() => this.refresh(), 10000);
        this.refresh();
    },

    async refresh() {
        try {
            const resp = await fetch('/api/notifications');
            if (!resp.ok) return;
            this._notifications = await resp.json();
            this._updateBadge();
        } catch { /* ignore */ }
    },

    _updateBadge() {
        const badge = document.getElementById('notification-badge');
        if (!badge) return;
        const count = this._notifications.length;
        badge.textContent = count;
        badge.style.display = count > 0 ? 'inline-flex' : 'none';

        // Pulse the bell when there are new notifications
        const btn = document.getElementById('notifications-btn');
        if (btn) {
            btn.classList.toggle('has-notifications', count > 0);
        }
    },

    open() {
        this.refresh().then(() => {
            this._renderList();
            DialogCore.open('notification-dialog');
        });
    },

    _renderList() {
        const container = document.getElementById('notification-list');
        if (!container) return;

        if (this._notifications.length === 0) {
            container.innerHTML = '<p class="notification-empty">No notifications</p>';
            return;
        }

        container.innerHTML = this._notifications.map(n => {
            const iconMap = { error: '!', warning: '!', info: 'i' };
            const icon = iconMap[n.level] || 'i';
            return `
                <div class="notification-item notification-${n.level}">
                    <span class="notification-icon">${icon}</span>
                    <div class="notification-body">
                        <span class="notification-message">${this._escapeHtml(n.message)}</span>
                        <span class="notification-meta">${n.timestamp}${n.source ? ' \u00b7 ' + this._escapeHtml(n.source) : ''}</span>
                    </div>
                    <button class="notification-dismiss" onclick="NotificationDialog.dismiss(${n.id})" title="Dismiss">&times;</button>
                </div>
            `;
        }).join('');
    },

    async dismiss(id) {
        try {
            await fetch(`/api/notifications/${id}`, { method: 'DELETE' });
            this._notifications = this._notifications.filter(n => n.id !== id);
            this._updateBadge();
            this._renderList();
        } catch { /* ignore */ }
    },

    async clearAll() {
        try {
            await fetch('/api/notifications', { method: 'DELETE' });
            this._notifications = [];
            this._updateBadge();
            this._renderList();
        } catch { /* ignore */ }
    },

    /** Add a notification from a WebSocket event. */
    addFromEvent(data) {
        this._notifications.push(data);
        this._updateBadge();
        // Re-render if dialog is open
        const dialog = document.getElementById('notification-dialog');
        if (dialog && dialog.open) {
            this._renderList();
        }
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },
};
