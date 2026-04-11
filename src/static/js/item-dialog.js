/**
 * Item creation and editing dialog functionality
 */
const ItemDialog = {
    // Pending attachments for new items (before they have an ID)
    _pendingAttachments: [],
    // HTML for existing (already-saved) attachments shown during edit
    _existingAttachmentsHtml: '',
    // Selected dependency item IDs
    _selectedDeps: [],

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
        this._selectedDeps = [];
        this._renderDepChips();
        this._initDepPicker(null);
        this._setAutoStart(false);
        this._setStartCopy(false);
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
        // Load existing dependencies for edit
        this._selectedDeps = [];
        this._renderDepChips();
        this._initDepPicker(item.id);
        this._setAutoStart(!!item.auto_start);
        this._setStartCopy(!!item.start_copy);
        if (item.id) {
            await this._loadDependencies(item.id);
        }
        // Load existing attachments for edit
        if (item.id) {
            this._loadFormAttachments(item.id);
        }
        await this._updateDefaultModelDisplay();
        // Hide play button for existing items
        const playBtn = document.getElementById('item-play-btn');
        if (playBtn) playBtn.style.display = 'none';
        // Disable "Save & Start" if item is blocked by dependencies
        this._updateSaveStartButton(item.id);
        DialogCore.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    _updateSaveStartButton(itemId) {
        const saveStartBtn = document.getElementById('item-save-start-btn');
        if (!saveStartBtn) return;
        if (itemId && Board.isItemBlocked(itemId)) {
            const blockers = Board.getBlockingItems(itemId).map(b => b.title).join(', ');
            saveStartBtn.disabled = true;
            saveStartBtn.title = `Blocked by: ${blockers}`;
            saveStartBtn.classList.add('btn-disabled');
        } else {
            saveStartBtn.disabled = false;
            saveStartBtn.title = 'Save & Start';
            saveStartBtn.classList.remove('btn-disabled');
        }
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

        const auto_start = this._getAutoStart();
        const start_copy = this._getStartCopy();

        try {
            let itemId = id;
            if (id) {
                const updateData = { title, description, epic_id, auto_start, start_copy };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                const item = await Api.createItem(title, description, model, epic_id, auto_start, start_copy);
                itemId = item.id;
            }

            // Save dependencies
            await Api.request('PUT', `/api/items/${itemId}/dependencies`, {
                required_item_ids: this._selectedDeps,
            });

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
        const start_copy = this._getStartCopy();

        if (!title) return;

        // Block starting if item has unresolved dependencies
        if (id && Board.isItemBlocked(id)) {
            const blockers = Board.getBlockingItems(id).map(b => b.title).join(', ');
            console.warn(`Cannot start blocked item ${id}. Blocked by: ${blockers}`);
            return;
        }

        try {
            let itemId = id;
            if (id) {
                // For existing items, just update
                const updateData = { title, description, epic_id, start_copy };
                if (model !== null) updateData.model = model;
                await Api.updateItem(id, updateData);
            } else {
                // For new items, create first
                const item = await Api.createItem(title, description, model, epic_id, false, start_copy);
                itemId = item.id;
            }

            // Save dependencies
            await Api.request('PUT', `/api/items/${itemId}/dependencies`, {
                required_item_ids: this._selectedDeps,
            });

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

    // --- Dependency picker ---

    async _loadDependencies(itemId) {
        try {
            const deps = await Api.request('GET', `/api/items/${itemId}/dependencies`);
            this._selectedDeps = deps.map(d => d.id);
            this._renderDepChips();
            this._renderDepList(); // refresh list to hide already-selected
            this._updateAutoStartVisibility();
        } catch (e) {
            console.error('Failed to load dependencies:', e);
        }
    },

    _initDepPicker(currentItemId) {
        this._depCurrentItemId = currentItemId;
        const input = document.getElementById('item-form-deps-search');
        const list = document.getElementById('item-form-deps-list');
        if (!input || !list) return;

        // Remove old listeners by replacing element
        const fresh = input.cloneNode(true);
        input.parentNode.replaceChild(fresh, input);

        fresh.addEventListener('focus', () => {
            this._renderDepList();
            list.hidden = false;
        });
        fresh.addEventListener('input', () => {
            this._renderDepList();
            list.hidden = false;
        });
        // Close list on outside click (but not on the list itself)
        fresh.addEventListener('blur', (e) => {
            // Small delay so click on list item registers before hide
            setTimeout(() => { list.hidden = true; }, 150);
        });
    },

    _getAvailableDepItems() {
        const exclude = new Set(this._selectedDeps);
        if (this._depCurrentItemId) exclude.add(this._depCurrentItemId);
        const query = (document.getElementById('item-form-deps-search')?.value || '').toLowerCase();

        return Object.values(Board.items || {})
            .filter(item => {
                if (exclude.has(item.id)) return false;
                if (item.column_name === 'archive') return false;
                if (query && !item.title.toLowerCase().includes(query)) return false;
                return true;
            })
            .sort((a, b) => a.title.localeCompare(b.title));
    },

    _statusLabel(item) {
        const map = {
            todo: 'Todo',
            doing: 'Doing',
            review: 'Review',
            done: 'Done',
            running: 'Running',
            paused: 'Paused',
            conflict: 'Conflict',
            questions: 'Questions',
        };
        return map[item.status] || map[item.column_name] || item.column_name;
    },

    _statusClass(item) {
        // Map to a CSS-friendly class
        const s = item.status || item.column_name;
        return s ? `dep-status-${s}` : '';
    },

    _renderDepList() {
        const list = document.getElementById('item-form-deps-list');
        if (!list) return;
        const items = this._getAvailableDepItems();

        if (items.length === 0) {
            list.innerHTML = '<div class="dep-picker-empty">No matching items</div>';
            return;
        }

        list.innerHTML = items.map(item => `
            <div class="dep-picker-option" onmousedown="ItemDialog._addDep('${item.id}')">
                <span class="dep-picker-option-title">${this._escHtml(item.title)}</span>
                <span class="dep-status-badge ${this._statusClass(item)}">${this._statusLabel(item)}</span>
            </div>
        `).join('');
    },

    _renderDepChips() {
        const container = document.getElementById('item-form-deps-chips');
        if (!container) return;

        if (this._selectedDeps.length === 0) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = this._selectedDeps.map(depId => {
            const item = Board.items?.[depId];
            const title = item ? this._escHtml(item.title) : depId;
            const statusCls = item ? this._statusClass(item) : '';
            const statusLbl = item ? this._statusLabel(item) : '?';
            return `<span class="dep-chip">
                <span class="dep-chip-title">${title}</span>
                <span class="dep-status-badge ${statusCls}">${statusLbl}</span>
                <button type="button" class="dep-chip-remove" onclick="ItemDialog._removeDep('${depId}')" title="Remove">&times;</button>
            </span>`;
        }).join('');
    },

    _addDep(itemId) {
        if (!this._selectedDeps.includes(itemId)) {
            this._selectedDeps.push(itemId);
            this._renderDepChips();
            this._renderDepList();
            this._updateAutoStartVisibility();
        }
        const input = document.getElementById('item-form-deps-search');
        if (input) { input.value = ''; input.focus(); }
    },

    _removeDep(itemId) {
        this._selectedDeps = this._selectedDeps.filter(id => id !== itemId);
        this._renderDepChips();
        this._renderDepList();
        this._updateAutoStartVisibility();
    },

    _setAutoStart(value) {
        const cb = document.getElementById('item-form-auto-start');
        if (cb) cb.checked = value;
        this._updateAutoStartVisibility();
    },

    _getAutoStart() {
        const cb = document.getElementById('item-form-auto-start');
        return cb ? cb.checked : false;
    },

    _setStartCopy(value) {
        const cb = document.getElementById('item-form-start-copy');
        if (cb) cb.checked = value;
    },

    _getStartCopy() {
        const cb = document.getElementById('item-form-start-copy');
        return cb ? cb.checked : false;
    },

    _updateAutoStartVisibility() {
        const wrap = document.getElementById('auto-start-wrap');
        if (wrap) wrap.style.display = this._selectedDeps.length > 0 ? '' : 'none';
    },

    _escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
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