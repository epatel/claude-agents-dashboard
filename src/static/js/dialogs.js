const Dialogs = {
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

    // Pending attachments for new items (before they have an ID)
    _pendingAttachments: [],

    openNewItem() {
        document.getElementById('item-dialog-title').textContent = 'New Item';
        document.getElementById('item-form-id').value = '';
        document.getElementById('item-form-title').value = '';
        document.getElementById('item-form-desc').value = '';
        this._pendingAttachments = [];
        this._renderFormAttachments();
        this.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    openEditItem(item) {
        document.getElementById('item-dialog-title').textContent = 'Edit Item';
        document.getElementById('item-form-id').value = item.id;
        document.getElementById('item-form-title').value = item.title;
        document.getElementById('item-form-desc').value = item.description;
        this._pendingAttachments = [];
        this._renderFormAttachments();
        // Load existing attachments for edit
        if (item.id) {
            this._loadFormAttachments(item.id);
        }
        this.open('item-dialog');
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
                    <button type="button" class="btn btn-xs btn-delete" onclick="Dialogs.removePendingAttachment(${i})" style="opacity:1">✕</button>
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
        this.setAnnotateTool('select');
        this._annotateTarget = 'new-item';
        this.open('annotate-dialog');
    },

    async submitItem(event) {
        event.preventDefault();
        const id = document.getElementById('item-form-id').value;
        const title = document.getElementById('item-form-title').value.trim();
        const description = document.getElementById('item-form-desc').value;

        if (!title) return;

        try {
            let itemId = id;
            if (id) {
                await Api.updateItem(id, { title, description });
            } else {
                const item = await Api.createItem(title, description);
                itemId = item.id;
            }

            // Upload pending attachments
            for (const a of this._pendingAttachments) {
                await Api.request('POST', `/api/items/${itemId}/attachments`, {
                    item_id: itemId,
                    filename: a.filename,
                    data: a.dataUrl,
                });
            }
            this._pendingAttachments = [];

            this.close('item-dialog');
        } catch (err) {
            console.error('Failed to save item:', err);
        }
    },

    async showDetail(itemId) {
        // Fetch latest item data
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        // If item is in review, show review dialog instead
        if (item.column_name === 'review') {
            return this.showReview(itemId);
        }

        // If item is in clarify, reopen the clarification dialog
        if (item.column_name === 'clarify') {
            return this.reopenClarification(itemId);
        }

        document.getElementById('detail-title').textContent = item.title;

        const body = document.getElementById('detail-body');
        body.innerHTML = this.renderMarkdown(item.description || '(no description)');

        // Header actions based on item state
        const editBtn = document.getElementById('detail-edit-btn');
        const deleteBtn = document.getElementById('detail-delete-btn');
        const actionsEl = document.getElementById('detail-header-actions');

        // Remove any previously added play button
        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();

        const isRunning = item.status === 'running' || item.status === 'resolving_conflicts';

        // Hide edit/delete when agent is active
        editBtn.style.display = isRunning ? 'none' : '';
        deleteBtn.style.display = isRunning ? 'none' : '';
        editBtn.onclick = () => {
            this.close('detail-dialog');
            this.openEditItem(item);
        };
        deleteBtn.onclick = async () => {
            this.close('detail-dialog');
            const ok = await Dialogs.confirm(`Delete "${item.title}"?`);
            if (!ok) return;
            try {
                await Api.deleteItem(item.id);
                Board.removeCard(item.id);
            } catch (err) {
                console.error('Failed to delete item:', err);
            }
        };

        // Add play button in Todo
        if (item.column_name === 'todo') {
            const playBtn = document.createElement('button');
            playBtn.id = 'detail-play-btn';
            playBtn.className = 'btn btn-sm btn-primary';
            playBtn.textContent = '▶ Start Agent';
            playBtn.onclick = async () => {
                await Board.startAgent(item.id);
                this.close('detail-dialog');
            };
            actionsEl.insertBefore(playBtn, editBtn);
        }

        // Load work log
        const logEl = document.getElementById('detail-log');
        try {
            const log = await Api.getWorkLog(itemId);
            if (log.length > 0) {
                logEl.innerHTML = log.map(e =>
                    `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${this.renderMarkdown(e.content)}</div></div>`
                ).join('');
                // Scroll to end after loading
                this.autoScroll(logEl);
            } else {
                logEl.innerHTML = '<div class="log-entry">No work log entries</div>';
            }
        } catch {
            logEl.innerHTML = '';
        }

        // Load attachments
        this._currentItemId = itemId;
        await this._loadAttachments(itemId);

        // Reset to description tab
        this.switchDetailTab('detail-desc');

        this.open('detail-dialog');
    },

    // --- Review dialog ---

    async showReview(itemId) {
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        document.getElementById('review-title').textContent = `Review: ${item.title}`;

        // Populate description tab
        const descEl = document.getElementById('review-description');
        descEl.innerHTML = this.renderMarkdown(item.description || '(no description)');

        // Populate work log tab
        const logEl = document.getElementById('review-log');
        try {
            const log = await Api.getWorkLog(itemId);
            if (log.length > 0) {
                logEl.innerHTML = log.map(e =>
                    `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${this.renderMarkdown(e.content)}</div></div>`
                ).join('');
                // Scroll to end after loading
                this.autoScroll(logEl);
            } else {
                logEl.innerHTML = '<div class="log-entry">No work log entries</div>';
            }
        } catch {
            logEl.innerHTML = '';
        }

        // Load diff tab
        const diffContainer = document.getElementById('review-diff');
        diffContainer.innerHTML = '<p>Loading diff...</p>';

        try {
            const data = await Api.request('GET', `/api/items/${itemId}/diff`);
            DiffViewer.render(data.diff, diffContainer);

            const filesContainer = document.getElementById('review-files');
            if (data.files && data.files.length > 0) {
                filesContainer.innerHTML = '<div class="changed-files-list">' +
                    data.files.map(f => {
                        const cls = f.status === 'A' ? 'file-added' : f.status === 'D' ? 'file-deleted' : 'file-modified';
                        return `<span class="file-badge ${cls}">${f.status_label || f.status} ${f.path}</span>`;
                    }).join('') + '</div>';
            } else {
                filesContainer.innerHTML = '';
            }
        } catch (err) {
            diffContainer.innerHTML = `<p>Error loading diff: ${err.message}</p>`;
        }

        // Reset to description tab
        this.switchReviewTab('description');

        // Wire up buttons
        document.getElementById('review-approve-btn').onclick = async () => {
            await Board.approveItem(itemId);
            this.close('review-dialog');
        };
        document.getElementById('review-changes-btn').onclick = () => {
            this.close('review-dialog');
            this.openRequestChanges(itemId);
        };

        this.open('review-dialog');
    },

    switchReviewTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.review-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });
        // Show/hide tab content
        document.querySelectorAll('.review-tab-content').forEach(c => {
            c.style.display = 'none';
            c.classList.remove('active');
        });
        const active = document.getElementById(`review-tab-${tabName}`);
        if (active) {
            active.style.display = '';
            active.classList.add('active');

            // Auto-scroll to end when switching to work log tab
            if (tabName === 'log') {
                const logEl = document.getElementById('review-log');
                if (logEl && logEl.children.length > 0) {
                    this.autoScroll(logEl);
                }
            }
        }
    },

    // --- Clarification dialog ---

    async reopenClarification(itemId) {
        // Fetch pending clarification from DB
        try {
            const data = await Api.request('GET', `/api/items/${itemId}/clarification`);
            if (data && data.id) {
                const choices = data.choices ? JSON.parse(data.choices) : [];
                this.showClarification(itemId, data.prompt || '(Agent is waiting for your input)', choices);
            } else {
                // No pending clarification, show regular detail
                this._showDetailDirect(itemId);
            }
        } catch (err) {
            console.error('Failed to load clarification:', err);
        }
    },

    async _showDetailDirect(itemId) {
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        document.getElementById('detail-title').textContent = item.title;
        document.getElementById('detail-body').innerHTML = this.renderMarkdown(item.description || '(no description)');

        const editBtn = document.getElementById('detail-edit-btn');
        editBtn.style.display = '';
        editBtn.onclick = () => { this.close('detail-dialog'); this.openEditItem(item); };

        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();

        const logEl = document.getElementById('detail-log');
        try {
            const log = await Api.getWorkLog(itemId);
            logEl.innerHTML = log.length > 0
                ? log.map(e => `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${this.renderMarkdown(e.content)}</div></div>`).join('')
                : '<div class="log-entry">No work log entries</div>';
            // Scroll to end after loading
            if (log.length > 0) {
                this.autoScroll(logEl);
            }
        } catch { logEl.innerHTML = ''; }

        this.open('detail-dialog');
    },

    showClarification(itemId, prompt, choices) {
        document.getElementById('clarify-item-id').value = itemId;
        document.getElementById('clarify-prompt').textContent = prompt;
        document.getElementById('clarify-response').value = '';

        const choicesEl = document.getElementById('clarify-choices');
        if (choices && choices.length > 0) {
            choicesEl.innerHTML = choices.map(c =>
                `<button class="btn btn-sm" style="margin: 4px 8px;" onclick="document.getElementById('clarify-response').value='${c.replace(/'/g, "\\'")}';">${c}</button>`
            ).join('');
        } else {
            choicesEl.innerHTML = '';
        }

        this.open('clarify-dialog');
    },

    async submitClarification(event) {
        event.preventDefault();
        const itemId = document.getElementById('clarify-item-id').value;
        const response = document.getElementById('clarify-response').value.trim();
        if (!response) return;

        try {
            await Api.request('POST', `/api/items/${itemId}/clarify`, { response });
            this.close('clarify-dialog');
        } catch (err) {
            console.error('Failed to submit clarification:', err);
        }
    },

    // --- Request changes dialog ---

    openRequestChanges(itemId) {
        document.getElementById('changes-item-id').value = itemId;
        document.getElementById('changes-text').value = '';
        this.open('changes-dialog');
        document.getElementById('changes-text').focus();
    },

    async submitChanges(event) {
        event.preventDefault();
        const itemId = document.getElementById('changes-item-id').value;
        const text = document.getElementById('changes-text').value.trim();
        if (!text) return;

        try {
            await Api.requestChanges(itemId, [text]);
            this.close('changes-dialog');
        } catch (err) {
            console.error('Failed to request changes:', err);
        }
    },

    // --- Config dialog ---

    async openConfig() {
        try {
            const config = await Api.request('GET', '/api/config');
            document.getElementById('config-model').value = config.model || 'claude-sonnet-4-20250514';
            document.getElementById('config-system-prompt').value = config.system_prompt || '';
            document.getElementById('config-project-context').value = config.project_context || '';
            document.getElementById('config-mcp-enabled').checked = config.mcp_enabled || false;
            document.getElementById('config-mcp-servers').value = config.mcp_servers || '[]';
            this.open('config-dialog');
        } catch (err) {
            console.error('Failed to load config:', err);
        }
    },

    async submitConfig(event) {
        event.preventDefault();
        const config = {
            model: document.getElementById('config-model').value,
            system_prompt: document.getElementById('config-system-prompt').value,
            project_context: document.getElementById('config-project-context').value,
            mcp_enabled: document.getElementById('config-mcp-enabled').checked,
            mcp_servers: document.getElementById('config-mcp-servers').value,
        };
        try {
            await Api.request('PUT', '/api/config', config);
            this.close('config-dialog');
        } catch (err) {
            console.error('Failed to save config:', err);
        }
    },

    // --- Detail tabs ---

    switchDetailTab(tabName) {
        document.querySelectorAll('#detail-dialog .review-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });
        document.querySelectorAll('#detail-dialog .review-tab-content').forEach(c => {
            c.style.display = 'none';
            c.classList.remove('active');
        });
        const active = document.getElementById(`detail-tab-${tabName}`);
        if (active) {
            active.style.display = '';
            active.classList.add('active');

            // Auto-scroll to end when switching to work log tab
            if (tabName === 'detail-wlog') {
                const logEl = document.getElementById('detail-log');
                if (logEl && logEl.children.length > 0) {
                    this.autoScroll(logEl);
                }
            }
        }
    },

    // --- Attachments ---

    _currentItemId: null,

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
                    <img src="/api/assets/${a.asset_path.split('/').pop()}" alt="${a.filename}" class="attachment-img" onclick="Dialogs.viewAttachment('/api/assets/${a.asset_path.split('/').pop()}', '${a.filename}')">
                    <div class="attachment-info">
                        <span class="attachment-name">${a.filename}</span>
                        <button class="btn btn-xs" onclick="Dialogs.deleteAttachment(${a.id}, '${itemId}')" title="Delete" style="opacity:0.5">&#128465;</button>
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
        this.open('view-attach-dialog');
    },

    async deleteAttachment(attachmentId, itemId) {
        if (!await Dialogs.confirm('Delete this attachment?')) return;
        try {
            await Api.request('DELETE', `/api/attachments/${attachmentId}`);
            await this._loadAttachments(itemId);
        } catch (err) {
            console.error('Failed to delete attachment:', err);
        }
    },

    // --- Annotation canvas ---

    openAnnotateCanvas() {
        const canvas = document.getElementById('annotate-canvas');
        Annotate.init(canvas);
        this.setAnnotateTool('select');
        this._annotateTarget = null;
        this.open('annotate-dialog');
    },

    setAnnotateTool(tool) {
        Annotate.tool = tool;
        document.querySelectorAll('.annotate-tool').forEach(b => {
            b.classList.toggle('active', b.dataset.tool === tool);
        });
    },

    async saveAnnotation() {
        const dataUrl = Annotate.toDataURL();
        const filename = `annotation_${Date.now()}.png`;

        if (this._annotateTarget === 'new-item') {
            // Save as pending attachment for the new item form
            this._pendingAttachments.push({ dataUrl, filename });
            this._renderFormAttachments();
            this.close('annotate-dialog');
            this._annotateTarget = null;
            return;
        }

        if (!this._currentItemId) return;

        try {
            await Api.request('POST', `/api/items/${this._currentItemId}/attachments`, {
                item_id: this._currentItemId,
                filename,
                data: dataUrl,
            });
            this.close('annotate-dialog');
            await this._loadAttachments(this._currentItemId);
            this.switchDetailTab('detail-attach');
        } catch (err) {
            console.error('Failed to save annotation:', err);
        }
    },

    // --- Markdown rendering ---

    renderMarkdown(text) {
        if (typeof marked !== 'undefined') {
            return marked.parse(text || '');
        }
        // Fallback: escape HTML and convert newlines
        const d = document.createElement('div');
        d.textContent = text || '';
        return d.innerHTML.replace(/\n/g, '<br>');
    },
};
