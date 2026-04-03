/**
 * Item creation and editing dialog functionality
 */
const ItemDialog = {
    // Pending attachments for new items (before they have an ID)
    _pendingAttachments: [],
    // HTML for existing (already-saved) attachments shown during edit
    _existingAttachmentsHtml: '',

    async openNewItem() {
        document.getElementById('item-dialog-title').textContent = 'New Item';
        document.getElementById('item-form-id').value = '';
        document.getElementById('item-form-title').value = '';
        document.getElementById('item-form-desc').value = '';
        document.getElementById('item-form-model').value = '';
        document.getElementById('item-form-epic').value = '';
        this.hideInlineEpicCreate();
        await this._populateEpicDropdown(null);
        this._pendingAttachments = [];
        this._existingAttachmentsHtml = '';
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
        document.getElementById('item-form-epic').value = item.epic_id || '';
        this.hideInlineEpicCreate();
        await this._populateEpicDropdown(item.epic_id);
        this._pendingAttachments = [];
        this._existingAttachmentsHtml = '';
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
            if (attachments.length > 0) {
                this._existingAttachmentsHtml = attachments.map(a => `
                    <div class="attachment-card" data-attachment-id="${a.id}">
                        <img src="/api/assets/${a.asset_path.split('/').pop()}" alt="${a.filename}" class="attachment-img">
                        <div class="attachment-info">
                            <span class="attachment-name">${a.filename}</span>
                            <button type="button" class="btn btn-xs" onclick="ItemDialog.deleteExistingAttachment(${a.id}, '${itemId}')" title="Delete" style="opacity:0.5">&#128465;</button>
                        </div>
                    </div>
                `).join('');
                this._renderFormAttachments();
            }
        } catch {}
    },

    _renderFormAttachments() {
        const container = document.getElementById('item-form-attachments');
        const pendingHtml = this._pendingAttachments.map((a, i) => `
            <div class="attachment-card">
                <img src="${a.dataUrl}" alt="${a.filename}" class="attachment-img">
                <div class="attachment-info">
                    <span class="attachment-name">${a.filename}</span>
                    <button type="button" class="btn btn-xs btn-delete" onclick="ItemDialog.removePendingAttachment(${i})" style="opacity:1">✕</button>
                </div>
            </div>
        `).join('');
        container.innerHTML = this._existingAttachmentsHtml + pendingHtml;
    },

    removePendingAttachment(index) {
        this._pendingAttachments.splice(index, 1);
        this._renderFormAttachments();
    },

    async deleteExistingAttachment(attachmentId, itemId) {
        if (!await DialogCore.confirm('Delete this attachment?')) return;
        try {
            await Api.request('DELETE', `/api/attachments/${attachmentId}`);
            const card = document.querySelector(`#item-form-attachments .attachment-card[data-attachment-id="${attachmentId}"]`);
            if (card) card.remove();
        } catch (err) {
            console.error('Failed to delete attachment:', err);
        }
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
        const epic_id = document.getElementById('item-form-epic').value || null;

        if (!title) return;

        try {
            let itemId = id;
            if (id) {
                const updateData = { title, description, epic_id };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                const item = await Api.createItem(title, description, model, epic_id);
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
        const epic_id = document.getElementById('item-form-epic').value || null;

        if (!title) return;

        try {
            let itemId = id;
            if (id) {
                // For existing items, just update
                const updateData = { title, description, epic_id };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                // For new items, create first
                const item = await Api.createItem(title, description, model, epic_id);
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

    async _populateEpicDropdown(selectedEpicId) {
        const select = document.getElementById('item-form-epic');
        if (!select) return;

        try {
            const epics = await Api.request('GET', '/api/epics');
            select.innerHTML = '<option value="">No Epic</option>';
            for (const epic of epics) {
                // Hide fully-archived epics (unless this item is assigned to it)
                const p = epic.progress || {};
                const archived = (p.archive || 0);
                if (archived > 0 && (p.total || 0) === 0 && epic.id !== selectedEpicId) continue;

                const opt = document.createElement('option');
                opt.value = epic.id;
                opt.textContent = epic.title;
                if (epic.id === selectedEpicId) opt.selected = true;
                select.appendChild(opt);
            }
        } catch (e) {
            console.error('Failed to load epics:', e);
        }
    },

    showInlineEpicCreate() {
        const container = document.getElementById('epic-inline-create');
        if (!container) return;
        container.classList.add('visible');
        document.getElementById('epic-create-title').value = '';
        this._selectedEpicColor = 'blue';
        this._renderColorSwatches();
        document.getElementById('epic-create-title').focus();
    },

    hideInlineEpicCreate() {
        const container = document.getElementById('epic-inline-create');
        if (container) container.classList.remove('visible');
    },

    _renderColorSwatches() {
        const container = document.getElementById('epic-color-swatches');
        if (!container) return;
        const colors = ['red', 'orange', 'amber', 'green', 'teal', 'blue', 'purple', 'pink'];
        container.innerHTML = colors.map(c =>
            `<div class="epic-color-swatch${c === this._selectedEpicColor ? ' selected' : ''}"
                  style="background: var(--epic-${c})"
                  onclick="ItemDialog._selectEpicColor('${c}')"></div>`
        ).join('');
    },

    _selectEpicColor(color) {
        this._selectedEpicColor = color;
        this._renderColorSwatches();
    },

    async createEpicInline() {
        const title = document.getElementById('epic-create-title').value.trim();
        if (!title) return;

        try {
            const epic = await Api.request('POST', '/api/epics', {
                title,
                color: this._selectedEpicColor || 'blue',
            });
            this.hideInlineEpicCreate();
            await this._populateEpicDropdown(epic.id);
            Board.loadEpics();
        } catch (e) {
            console.error('Failed to create epic:', e);
        }
    },

    _selectedEpicColor: 'blue',

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