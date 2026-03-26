/**
 * Detail view dialog functionality
 */
const DetailDialog = {
    async showDetail(itemId) {
        // Fetch latest item data
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        // If item is in review, show review dialog instead
        if (item.column_name === 'review') {
            return ReviewDialog.showReview(itemId);
        }

        // If item is in questions, reopen the questions dialog
        if (item.column_name === 'questions') {
            return ClarificationDialog.reopenClarification(itemId);
        }

        document.getElementById('detail-title').textContent = item.title;

        const body = document.getElementById('detail-body');

        // Build content with description and model info
        let content = DialogUtils.renderMarkdown(item.description || '(no description)');

        // Add model information if available
        if (item.model) {
            const modelDisplayName = DialogUtils._getModelDisplayName(item.model);
            content += `<div class="detail-model-info"><strong>Model:</strong> ${modelDisplayName}</div>`;
        } else {
            // Show default model from config
            try {
                const config = await Api.request('GET', '/api/config');
                const defaultModel = config.model || 'claude-sonnet-4-20250514';
                const modelDisplayName = DialogUtils._getModelDisplayName(defaultModel);
                content += `<div class="detail-model-info"><strong>Model:</strong> ${modelDisplayName} (default)</div>`;
            } catch (err) {
                console.warn('Failed to fetch config for default model display:', err);
            }
        }

        body.innerHTML = content;

        // Header actions based on item state
        const editBtn = document.getElementById('detail-edit-btn');
        const deleteBtn = document.getElementById('detail-delete-btn');
        const actionsEl = document.getElementById('detail-header-actions');

        // Remove any previously added play/rerun buttons
        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();
        const oldRerun = document.getElementById('detail-rerun-btn');
        if (oldRerun) oldRerun.remove();

        const isRunning = item.status === 'running' || item.status === 'resolving_conflicts';

        // Hide edit/delete when agent is active
        editBtn.style.display = isRunning ? 'none' : '';
        deleteBtn.style.display = isRunning ? 'none' : '';
        editBtn.onclick = () => {
            DialogCore.close('detail-dialog');
            ItemDialog.openEditItem(item);
        };
        deleteBtn.onclick = async () => {
            DialogCore.close('detail-dialog');
            const ok = await DialogCore.confirm(`Delete "${item.title}"?`);
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
                DialogCore.close('detail-dialog');
            };
            actionsEl.insertBefore(playBtn, editBtn);
        }

        // Add re-run button in Done
        if (item.column_name === 'done') {
            const rerunBtn = document.createElement('button');
            rerunBtn.id = 'detail-rerun-btn';
            rerunBtn.className = 'btn btn-sm btn-primary';
            rerunBtn.textContent = '↻ Re-run';
            rerunBtn.onclick = async () => {
                await Board.rerunItem(item.id);
                DialogCore.close('detail-dialog');
            };
            actionsEl.insertBefore(rerunBtn, editBtn);
        }

        // Load work log
        const logEl = document.getElementById('detail-log');
        try {
            const log = await Api.getWorkLog(itemId);
            if (log.length > 0) {
                logEl.innerHTML = log.map(e =>
                    `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${DialogUtils.renderMarkdown(e.content)}</div></div>`
                ).join('');
                // Scroll to end after initial load
                DialogCore.forceAutoScroll(logEl);
            } else {
                logEl.innerHTML = '<div class="log-entry">No work log entries</div>';
            }
        } catch {
            logEl.innerHTML = '';
        }

        // Load attachments
        DialogCore._currentItemId = itemId;
        await Attachments._loadAttachments(itemId);

        // Preselect Work Log tab if agent is running or item is done, otherwise show description tab
        const defaultTab = (isRunning || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc';
        this.switchDetailTab(defaultTab);

        DialogCore.open('detail-dialog');
    },

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

            // Force scroll to end when switching to work log tab (explicit user action)
            if (tabName === 'detail-wlog') {
                const logEl = document.getElementById('detail-log');
                if (logEl && logEl.children.length > 0) {
                    DialogCore.forceAutoScroll(logEl);
                }
            }
        }
    },

    async _showDetailDirect(itemId) {
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        document.getElementById('detail-title').textContent = item.title;
        document.getElementById('detail-body').innerHTML = DialogUtils.renderMarkdown(item.description || '(no description)');

        const editBtn = document.getElementById('detail-edit-btn');
        editBtn.style.display = '';
        editBtn.onclick = () => { DialogCore.close('detail-dialog'); ItemDialog.openEditItem(item); };

        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();

        const logEl = document.getElementById('detail-log');
        try {
            const log = await Api.getWorkLog(itemId);
            logEl.innerHTML = log.length > 0
                ? log.map(e => `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${DialogUtils.renderMarkdown(e.content)}</div></div>`).join('')
                : '<div class="log-entry">No work log entries</div>';
            // Scroll to end after initial load
            if (log.length > 0) {
                DialogCore.forceAutoScroll(logEl);
            }
        } catch { logEl.innerHTML = ''; }

        // Preselect Work Log tab if agent is running or item is done, otherwise show description tab
        const isRunning = item.status === 'running' || item.status === 'resolving_conflicts';
        const defaultTab = (isRunning || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc';
        this.switchDetailTab(defaultTab);

        DialogCore.open('detail-dialog');
    },
};