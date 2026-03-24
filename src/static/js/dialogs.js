const Dialogs = {
    open(id) {
        const dialog = document.getElementById(id);
        if (dialog && !dialog.open) dialog.showModal();
    },

    close(id) {
        const dialog = document.getElementById(id);
        if (dialog && dialog.open) dialog.close();
    },

    openNewItem() {
        document.getElementById('item-dialog-title').textContent = 'New Item';
        document.getElementById('item-form-id').value = '';
        document.getElementById('item-form-title').value = '';
        document.getElementById('item-form-desc').value = '';
        this.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    openEditItem(item) {
        document.getElementById('item-dialog-title').textContent = 'Edit Item';
        document.getElementById('item-form-id').value = item.id;
        document.getElementById('item-form-title').value = item.title;
        document.getElementById('item-form-desc').value = item.description;
        this.open('item-dialog');
        document.getElementById('item-form-title').focus();
    },

    async submitItem(event) {
        event.preventDefault();
        const id = document.getElementById('item-form-id').value;
        const title = document.getElementById('item-form-title').value.trim();
        const description = document.getElementById('item-form-desc').value;

        if (!title) return;

        try {
            if (id) {
                await Api.updateItem(id, { title, description });
            } else {
                await Api.createItem(title, description);
            }
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
        const actionsEl = document.getElementById('detail-header-actions');

        // Remove any previously added play button
        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();

        const isRunning = item.status === 'running' || item.status === 'resolving_conflicts';

        // Hide edit when agent is active
        editBtn.style.display = isRunning ? 'none' : '';
        editBtn.onclick = () => {
            this.close('detail-dialog');
            this.openEditItem(item);
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
            } else {
                logEl.innerHTML = '<div class="log-entry">No work log entries</div>';
            }
        } catch {
            logEl.innerHTML = '';
        }

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
        };
        try {
            await Api.request('PUT', '/api/config', config);
            this.close('config-dialog');
        } catch (err) {
            console.error('Failed to save config:', err);
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
