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

        const columnLabels = {
            todo: '📝 Todo', doing: '🚧 Doing', questions: '❓ Questions',
            review: '👀 Review', done: '✅ Done', archive: '📦 Archive',
        };
        const badge = document.getElementById('detail-column-badge');
        badge.textContent = columnLabels[item.column_name] || item.column_name;

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

        // Show merge commit SHA for done/archive items
        if ((item.column_name === 'done' || item.column_name === 'archive') && item.merge_commit) {
            const shortSha = item.merge_commit.slice(0, 8);
            content += `<div class="detail-model-info"><strong>Merge commit:</strong> <code>${shortSha}</code></div>`;
        }

        body.innerHTML = content;

        // Header actions based on item state
        const editBtn = document.getElementById('detail-edit-btn');
        const deleteBtn = document.getElementById('detail-delete-btn');
        const actionsEl = document.getElementById('detail-header-actions');

        // Remove any previously added play/rerun/start-copy buttons
        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();
        const oldStartCopy = document.getElementById('detail-start-copy-btn');
        if (oldStartCopy) oldStartCopy.remove();
        const oldRerun = document.getElementById('detail-rerun-btn');
        if (oldRerun) oldRerun.remove();

        const isAgentActive = item.status === 'running' || item.status === 'resolving_conflicts' || item.status === 'paused';

        // Hide edit/delete when agent is active
        editBtn.style.display = isAgentActive ? 'none' : '';
        deleteBtn.style.display = isAgentActive ? 'none' : '';
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

        // Add play button and start copy button in Todo
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

            const startCopyBtn = document.createElement('button');
            startCopyBtn.id = 'detail-start-copy-btn';
            startCopyBtn.className = 'btn btn-sm';
            startCopyBtn.textContent = '▶⧉ Start Copy';
            startCopyBtn.title = 'Start a copy (keep original in Todo)';
            startCopyBtn.onclick = async () => {
                await Board.startCopyAgent(item.id);
                DialogCore.close('detail-dialog');
            };
            actionsEl.insertBefore(startCopyBtn, editBtn);
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
        const defaultTab = (isAgentActive || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc';
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

        // Preselect Work Log tab if agent is active or item is done, otherwise show description tab
        const isAgentActiveOrDone = item.status === 'running' || item.status === 'resolving_conflicts' || item.status === 'paused';
        const defaultTab = (isAgentActiveOrDone || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc';
        this.switchDetailTab(defaultTab);

        DialogCore.open('detail-dialog');
    },
};