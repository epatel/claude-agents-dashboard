/**
 * Request changes dialog functionality
 */
const RequestChangesDialog = {
    openRequestChanges(itemId) {
        document.getElementById('changes-item-id').value = itemId;
        document.getElementById('changes-text').value = '';
        DialogCore.open('changes-dialog');
        document.getElementById('changes-text').focus();
    },

    async submitChanges(event) {
        event.preventDefault();
        const itemId = document.getElementById('changes-item-id').value;
        const text = document.getElementById('changes-text').value.trim();
        if (!text) return;

        try {
            await Api.requestChanges(itemId, [text]);
            DialogCore.close('changes-dialog');
        } catch (err) {
            console.error('Failed to request changes:', err);
        }
    },
};