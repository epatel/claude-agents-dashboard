/**
 * Review dialog functionality
 */
const ReviewDialog = {
    async showReview(itemId) {
        const items = await Api.getItems();
        const item = items.find(i => i.id === itemId);
        if (!item) return;

        document.getElementById('review-title').textContent = `Review: ${item.title}`;

        // Populate description tab
        const descEl = document.getElementById('review-description');
        descEl.innerHTML = DialogUtils.renderMarkdown(item.description || '(no description)');

        // Populate work log tab
        const logEl = document.getElementById('review-log');
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

        // Preselect Work Log tab for review
        this.switchReviewTab('log');

        // Wire up buttons
        document.getElementById('review-approve-btn').onclick = async () => {
            await Board.approveItem(itemId);
            DialogCore.close('review-dialog');
        };
        document.getElementById('review-changes-btn').onclick = () => {
            DialogCore.close('review-dialog');
            RequestChangesDialog.openRequestChanges(itemId);
        };
        document.getElementById('review-cancel-btn').onclick = async () => {
            if (await DialogCore.confirm('Cancel this review? The work will be discarded and the item moved back to Todo.')) {
                await Board.cancelReview(itemId);
                DialogCore.close('review-dialog');
            }
        };

        // Track current item ID for work log filtering
        DialogCore._currentItemId = itemId;
        DialogCore.open('review-dialog');
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

            // Force scroll to end when switching to work log tab (explicit user action)
            if (tabName === 'log') {
                const logEl = document.getElementById('review-log');
                if (logEl && logEl.children.length > 0) {
                    DialogCore.forceAutoScroll(logEl);
                }
            }
        }
    },
};