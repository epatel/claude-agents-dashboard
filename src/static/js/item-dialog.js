/**
 * Item creation and editing dialog functionality
 */
const ItemDialog = {
    // Pending attachments for new items (before they have an ID)
    _pendingAttachments: [],

    async openNewItem() {
        document.getElementById('item-dialog-title').textContent = 'New Item';
        document.getElementById('item-form-id').value = '';
        document.getElementById('item-form-title').value = '';
        document.getElementById('item-form-desc').value = '';
        document.getElementById('item-form-model').value = '';
        this._pendingAttachments = [];
        this._renderFormAttachments();
        await this._updateDefaultModelDisplay();
        // Show play button for new items
        const playBtn = document.getElementById('item-play-btn');
        if (playBtn) playBtn.style.display = '';
        DialogCore.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    async openEditItem(item) {
        document.getElementById('item-dialog-title').textContent = 'Edit Item';
        document.getElementById('item-form-id').value = item.id;
        document.getElementById('item-form-title').value = item.title;
        document.getElementById('item-form-desc').value = item.description;
        document.getElementById('item-form-model').value = item.model || '';
        this._pendingAttachments = [];
        this._renderFormAttachments();
        // Load existing attachments for edit
        if (item.id) {
            this._loadFormAttachments(item.id);
        }
        await this._updateDefaultModelDisplay();
        // Hide play button for existing items
        const playBtn = document.getElementById('item-play-btn');
        if (playBtn) playBtn.style.display = 'none';
        DialogCore.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    async _loadFormAttachments(itemId) {
        try {
            const attachments = await Api.request('GET', `/api/items/${itemId}/attachments`);
            const container = document.getElementById('item-form-attachments');
            if (attachments.length > 0) {
                container.innerHTML = attachments.map(a => `
                    <div class="attachment-card">
                        <img src="/api/assets/${a.asset_path.split('/').pop()}" alt="${a.filename}" class="attachment-img">
                        <div class="attachment-info">
                            <span class="attachment-name">${a.filename}</span>
                        </div>
                    </div>
                `).join('') + (container.innerHTML || '');
            }
        } catch {}
    },

    _renderFormAttachments() {
        const container = document.getElementById('item-form-attachments');
        if (this._pendingAttachments.length === 0) {
            container.innerHTML = '';
            return;
        }
        container.innerHTML = this._pendingAttachments.map((a, i) => `
            <div class="attachment-card">
                <img src="${a.dataUrl}" alt="${a.filename}" class="attachment-img">
                <div class="attachment-info">
                    <span class="attachment-name">${a.filename}</span>
                    <button type="button" class="btn btn-xs btn-delete" onclick="ItemDialog.removePendingAttachment(${i})" style="opacity:1">✕</button>
                </div>
            </div>
        `).join('');
    },

    removePendingAttachment(index) {
        this._pendingAttachments.splice(index, 1);
        this._renderFormAttachments();
    },

    openAnnotateForNewItem() {
        const canvas = document.getElementById('annotate-canvas');
        Annotate.init(canvas);
        Dialogs.setAnnotateTool('select');
        Dialogs._annotateTarget = 'new-item';
        DialogCore.open('annotate-dialog');

        // Focus canvas after a brief delay to ensure dialog is fully open
        setTimeout(() => {
            canvas.focus();
        }, 100);
    },

    async submitItem(event) {
        event.preventDefault();
        const id = document.getElementById('item-form-id').value;
        const title = document.getElementById('item-form-title').value.trim();
        const description = document.getElementById('item-form-desc').value;
        const model = document.getElementById('item-form-model').value || null;

        if (!title) return;

        try {
            let itemId = id;
            if (id) {
                const updateData = { title, description };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                const item = await Api.createItem(title, description, model);
                itemId = item.id;
            }

            // Upload pending attachments
            for (const a of this._pendingAttachments) {
                await Api.request('POST', `/api/items/${itemId}/attachments`, {
                    item_id: itemId,
                    filename: a.filename,
                    data: a.dataUrl,
                    annotation_summary: a.annotation_summary || null,
                });
            }
            this._pendingAttachments = [];

            DialogCore.close('item-dialog');
        } catch (err) {
            console.error('Failed to save item:', err);
        }
    },

    async submitItemAndStart(event) {
        event.preventDefault();
        const id = document.getElementById('item-form-id').value;
        const title = document.getElementById('item-form-title').value.trim();
        const description = document.getElementById('item-form-desc').value;
        const model = document.getElementById('item-form-model').value || null;

        if (!title) return;

        try {
            let itemId = id;
            if (id) {
                // For existing items, just update
                const updateData = { title, description };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                // For new items, create first
                const item = await Api.createItem(title, description, model);
                itemId = item.id;
            }

            // Upload pending attachments
            for (const a of this._pendingAttachments) {
                await Api.request('POST', `/api/items/${itemId}/attachments`, {
                    item_id: itemId,
                    filename: a.filename,
                    data: a.dataUrl,
                    annotation_summary: a.annotation_summary || null,
                });
            }
            this._pendingAttachments = [];

            // Move to doing column and start agent (this works for both new and existing items)
            await Api.moveItem(itemId, 'doing', 0);
            await Api.startAgent(itemId);

            DialogCore.close('item-dialog');
        } catch (err) {
            console.error('Failed to save and start item:', err);
        }
    },

    async _updateDefaultModelDisplay() {
        try {
            const config = await Api.request('GET', '/api/config');
            const defaultModel = config.model || 'claude-sonnet-4-20250514';
            const displayName = DialogUtils._getModelDisplayName(defaultModel);

            // Update the first option in the model select dropdown
            const modelSelect = document.getElementById('item-form-model');
            const defaultOption = modelSelect.querySelector('option[value=""]');
            if (defaultOption) {
                defaultOption.textContent = `Use Global Default (${displayName})`;
            }
        } catch (err) {
            console.error('Failed to fetch config for model display:', err);
            // Keep the original text if we can't fetch the config
        }
    },
};