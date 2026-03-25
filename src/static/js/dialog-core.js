/**
 * Core dialog utilities and confirmation dialogs
 */
const DialogCore = {
    // Utility function for reliable auto-scroll
    autoScroll(element) {
        if (!element) return;
        // Use requestAnimationFrame for better performance and reliability
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