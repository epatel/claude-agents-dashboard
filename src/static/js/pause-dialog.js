/**
 * Pause Agent dialog — lets the user optionally attach a note that gets
 * prepended to the resume prompt (e.g. "investigate a different approach").
 */
const PauseDialog = {
    openPause(itemId) {
        document.getElementById('pause-item-id').value = itemId;
        document.getElementById('pause-message').value = '';
        DialogCore.open('pause-dialog');
        document.getElementById('pause-message').focus();
    },

    async submitPause(event) {
        if (event) event.preventDefault();
        const itemId = document.getElementById('pause-item-id').value;
        const message = document.getElementById('pause-message').value.trim();
        await PauseDialog._send(itemId, message || null);
    },

    async submitPauseWithoutNote() {
        const itemId = document.getElementById('pause-item-id').value;
        await PauseDialog._send(itemId, null);
    },

    async _send(itemId, message) {
        // Mirror Board.pauseAgent's "stopping" UI feedback so the card visibly
        // reacts the moment the user commits to pausing.
        if (typeof Board !== 'undefined' && Board.applyStoppingState) {
            Board.applyStoppingState(itemId, 'Pausing…');
        }
        DialogCore.close('pause-dialog');
        try {
            await Api.pauseAgent(itemId, message);
        } catch (err) {
            console.error('Failed to pause agent:', err);
        }
    },
};
