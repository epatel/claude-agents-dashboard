/**
 * Attachments management functionality
 */
const Attachments = {
    async _loadAttachments(itemId) {
        const container = document.getElementById('detail-attachments');
        const countEl = document.getElementById('detail-attach-count');
        try {
            const attachments = await Api.request('GET', `/api/items/${itemId}/attachments`);
            countEl.textContent = attachments.length;
            if (attachments.length === 0) {
                container.innerHTML = '<p class="diff-empty">No attachments yet. Click "Add Annotated Image" to create one.</p>';
                return;
            }
            container.innerHTML = attachments.map(a => `
                <div class="attachment-card">
                    <img src="/api/assets/${a.asset_path.split('/').pop()}" alt="${a.filename}" class="attachment-img" onclick="Attachments.viewAttachment('/api/assets/${a.asset_path.split('/').pop()}', '${a.filename}')">
                    <div class="attachment-info">
                        <span class="attachment-name">${a.filename}</span>
                        <button class="btn btn-xs" onclick="Attachments.deleteAttachment(${a.id}, '${itemId}')" title="Delete" style="opacity:0.5">&#128465;</button>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            container.innerHTML = '<p>Error loading attachments</p>';
        }
    },

    viewAttachment(src, filename) {
        document.getElementById('view-attach-title').textContent = filename || 'Attachment';
        document.getElementById('view-attach-img').src = src;
        DialogCore.open('view-attach-dialog');
    },

    async deleteAttachment(attachmentId, itemId) {
        if (!await DialogCore.confirm('Delete this attachment?')) return;
        try {
            await Api.request('DELETE', `/api/attachments/${attachmentId}`);
            await this._loadAttachments(itemId);
        } catch (err) {
            console.error('Failed to delete attachment:', err);
        }
    },
};