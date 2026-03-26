/**
 * Core dialog utilities and confirmation dialogs
 */
const DialogCore = {
    // Track which log elements have auto-scroll enabled (default: true)
    _autoScrollEnabled: new WeakMap(),

    // Check if an element is scrolled to (or near) the bottom
    _isAtBottom(element, threshold = 30) {
        return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
    },

    // Attach scroll listener to a log element to track user scroll intent
    initAutoScroll(element) {
        if (!element || element._autoScrollInit) return;
        element._autoScrollInit = true;
        this._autoScrollEnabled.set(element, true);
        element.addEventListener('scroll', () => {
            this._autoScrollEnabled.set(element, this._isAtBottom(element));
        });
    },

    // Utility function for reliable auto-scroll (respects user scroll position)
    autoScroll(element) {
        if (!element) return;
        this.initAutoScroll(element);
        if (!this._autoScrollEnabled.get(element)) return;
        requestAnimationFrame(() => {
            element.scrollTop = element.scrollHeight;
        });
    },

    // Force scroll to bottom and re-enable auto-scroll (for explicit user actions like tab switches)
    forceAutoScroll(element) {
        if (!element) return;
        this.initAutoScroll(element);
        this._autoScrollEnabled.set(element, true);
        requestAnimationFrame(() => {
            element.scrollTop = element.scrollHeight;
        });
    },

    open(id) {
        const dialog = document.getElementById(id);
        if (dialog && !dialog.open) dialog.showModal();
    },

    close(id) {
        const dialog = document.getElementById(id);
        if (dialog && dialog.open) dialog.close();

        // Clear current item ID when closing item-specific dialogs
        if (id === 'detail-dialog' || id === 'review-dialog') {
            this._currentItemId = null;
        }
    },

    // --- Custom confirm dialog ---

    confirm(message, title = 'Confirm', okLabel = 'Delete') {
        return new Promise((resolve) => {
            document.getElementById('confirm-title').textContent = title;
            document.getElementById('confirm-message').textContent = message;
            const okBtn = document.getElementById('confirm-ok-btn');
            okBtn.textContent = okLabel;
            okBtn.className = okLabel === 'Delete' ? 'btn btn-danger' : 'btn btn-primary';
            const cancelBtn = document.getElementById('confirm-cancel-btn');

            const cleanup = (result) => {
                okBtn.onclick = null;
                cancelBtn.onclick = null;
                this.close('confirm-dialog');
                resolve(result);
            };

            okBtn.onclick = () => cleanup(true);
            cancelBtn.onclick = () => cleanup(false);
            this.open('confirm-dialog');
        });
    },

    _currentItemId: null,
};