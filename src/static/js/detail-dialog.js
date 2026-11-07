/**
 * Detail view dialog functionality
 */
const DetailDialog = {
    _tabs: {
        tabs: '#detail-dialog .review-tab',
        panels: '#detail-dialog .review-tab-content',
        panelIdPrefix: 'detail-tab-',
        logTab: 'detail-wlog',
        logId: 'detail-log',
    },

    _columnLabels: {
        todo: '📝 Todo', doing: '🚧 Doing', questions: '❓ Questions',
        review: '👀 Review', done: '✅ Done', archive: '📦 Archive',
    },

    /** Header buttons added per item (removed again on every open). */
    _extraButtonIds: ['detail-play-btn', 'detail-start-copy-btn', 'detail-rerun-btn', 'detail-copy-link-btn'],

    async showDetail(itemId) {
        // Fetch latest item data
        const item = await DialogUtils.fetchItem(itemId);
        if (!item) return;

        // Review and Questions items have their own dialogs
        if (item.column_name === 'review') {
            return ReviewDialog.showReview(itemId);
        }
        if (item.column_name === 'questions') {
            return ClarificationDialog.reopenClarification(itemId);
        }

        document.getElementById('detail-title').textContent = item.title;
        document.getElementById('detail-column-badge').textContent =
            this._columnLabels[item.column_name] || item.column_name;

        // Description, model and merge commit
        const body = document.getElementById('detail-body');
        const description = DialogUtils.renderMarkdown(item.description || '(no description)');
        body.innerHTML = description + await this._modelInfoHtml(item) + this._mergeCommitHtml(item);
        DialogUtils.runMermaid(body);
        this._wireCopyShaButtons(body);

        const isAgentActive = this._isAgentActive(item);
        this._setupHeaderActions(item, isAgentActive);
        this._setupAutoApprove(item);
        this._setupResumeForm(item.status === 'paused' ? itemId : '');

        await DialogUtils.loadWorkLog(itemId, document.getElementById('detail-log'));

        // Load attachments
        DialogCore._currentItemId = itemId;
        await Attachments._loadAttachments(itemId);

        // Preselect Work Log tab if agent is running or item is done, otherwise show description tab
        this.switchDetailTab((isAgentActive || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc');
        DialogCore.open('detail-dialog');
    },

    _isAgentActive(item) {
        return item.status === 'running' || item.status === 'resolving_conflicts' || item.status === 'paused';
    },

    /** The item's model, or the configured default (omitted if the config can't be read). */
    async _modelInfoHtml(item) {
        if (item.model) return this._modelLineHtml(item.model, '');
        try {
            const config = await Api.request('GET', '/api/config');
            return this._modelLineHtml(config.model || window.__DEFAULT_MODEL__, ' (default)');
        } catch (err) {
            console.warn('Failed to fetch config for default model display:', err);
            return '';
        }
    },

    _modelLineHtml(model, suffix) {
        const modelDisplayName = DialogUtils._getModelDisplayName(model);
        const providerBadge = DialogUtils._getProviderBadgeHtml(model);
        return `<div class="detail-model-info"><strong>Model:</strong> ${modelDisplayName} ${providerBadge}${suffix}</div>`;
    },

    /** Merge commit SHA (with a copy button) for done / archive items. */
    _mergeCommitHtml(item) {
        const merged = item.column_name === 'done' || item.column_name === 'archive';
        if (!merged || !item.merge_commit) return '';
        const shortSha = item.merge_commit.slice(0, 8);
        return `<div class="detail-model-info detail-git-info"><div class="detail-info-row"><strong>Merge commit:</strong> <code class="sha-text" title="${item.merge_commit}">${shortSha}</code> <button type="button" class="copy-sha-btn" data-copy="${item.merge_commit}" title="Copy full SHA"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button></div></div>`;
    },

    _wireCopyShaButtons(body) {
        body.querySelectorAll('.copy-sha-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                await this._copyText(btn.dataset.copy);
                // Flash a check mark
                const orig = btn.innerHTML;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
                setTimeout(() => { btn.innerHTML = orig; }, 1500);
            });
        });
    },

    /** Copy to the clipboard, falling back to execCommand outside secure contexts. */
    async _copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
    },

    /** Edit / delete (hidden while the agent is active) plus the column's extra buttons. */
    _setupHeaderActions(item, isAgentActive) {
        const editBtn = document.getElementById('detail-edit-btn');
        const deleteBtn = document.getElementById('detail-delete-btn');
        const actionsEl = document.getElementById('detail-header-actions');

        for (const id of this._extraButtonIds) {
            const old = document.getElementById(id);
            if (old) old.remove();
        }

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

        for (const btn of this._columnButtons(item)) {
            actionsEl.insertBefore(btn, editBtn);
        }
    },

    /** Todo: Start / Start Copy. Done: Copy link / Re-run. */
    _columnButtons(item) {
        const thenClose = (action) => async () => {
            await action();
            DialogCore.close('detail-dialog');
        };
        if (item.column_name === 'todo') {
            return [
                this._headerButton('detail-play-btn', 'btn btn-sm btn-primary', { text: '▶ Start Agent' },
                    thenClose(() => Board.startAgent(item.id))),
                this._headerButton('detail-start-copy-btn', 'btn btn-sm',
                    { text: '▶⧉ Start Copy', title: 'Start a copy (keep original in Todo)' },
                    thenClose(() => Board.startCopyAgent(item.id))),
            ];
        }
        if (item.column_name === 'done') {
            const copyLinkBtn = this._headerButton('detail-copy-link-btn', 'btn btn-sm',
                { html: '&#128279;', title: 'Copy item detail link' }, null);
            copyLinkBtn.onclick = async () => {
                const url = `${window.location.origin}/api/items/${item.id}`;
                try {
                    await navigator.clipboard.writeText(url);
                    copyLinkBtn.textContent = '✓';
                    setTimeout(() => { copyLinkBtn.innerHTML = '&#128279;'; }, 1500);
                } catch (err) {
                    console.error('Failed to copy link:', err);
                }
            };
            return [
                copyLinkBtn,
                this._headerButton('detail-rerun-btn', 'btn btn-sm btn-primary', { text: '↻ Re-run' },
                    thenClose(() => Board.rerunItem(item.id))),
            ];
        }
        return [];
    },

    _headerButton(id, className, { text, html, title }, onclick) {
        const btn = document.createElement('button');
        btn.id = id;
        btn.className = className;
        if (html) btn.innerHTML = html;
        else btn.textContent = text;
        if (title) btn.title = title;
        btn.onclick = onclick;
        return btn;
    },

    // Auto-approve toggle: visible while item is in Doing so the user can
    // change the mode mid-flight (it's read when the agent finishes).
    _setupAutoApprove(item) {
        const wrap = document.getElementById('detail-auto-approve-wrap');
        const select = document.getElementById('detail-auto-approve');
        if (!wrap || !select) return;
        if (item.column_name !== 'doing') {
            this._hideAutoApprove();
            return;
        }
        let mode = this._autoApproveMode(item);
        select.value = String(mode);
        wrap.style.display = '';
        select.onchange = async () => {
            const newValue = parseInt(select.value, 10);
            const prev = mode;
            try {
                await Api.updateItem(item.id, { auto_approve: newValue });
                item.auto_approve = newValue;
                mode = newValue;
            } catch (err) {
                console.error('Failed to update auto_approve:', err);
                select.value = String(prev);
            }
        };
    },

    /**
     * Stored as tri-state int (0=Off, 1=With Review, 2=Direct). Older
     * items may have it as a boolean — coerce truthy → 1.
     */
    _autoApproveMode(item) {
        if (item.auto_approve === true) return 1;
        if (item.auto_approve === false || item.auto_approve == null) return 0;
        const mode = parseInt(item.auto_approve, 10);
        return [0, 1, 2].includes(mode) ? mode : 0;
    },

    _hideAutoApprove() {
        const wrap = document.getElementById('detail-auto-approve-wrap');
        const select = document.getElementById('detail-auto-approve');
        if (wrap) wrap.style.display = 'none';
        if (select) select.onchange = null;
    },

    // Continue form: only visible for paused items (``pausedItemId`` set). Lets
    // the user send an optional note that the agent receives on resume.
    _setupResumeForm(pausedItemId) {
        const resumeForm = document.getElementById('detail-resume-form');
        const resumeMessage = document.getElementById('detail-resume-message');
        if (!resumeForm || !resumeMessage) return;
        resumeForm.style.display = pausedItemId ? '' : 'none';
        resumeForm.dataset.itemId = pausedItemId;
        if (pausedItemId) resumeMessage.value = '';
    },

    async submitResume(event) {
        if (event) event.preventDefault();
        const form = document.getElementById('detail-resume-form');
        const messageEl = document.getElementById('detail-resume-message');
        const itemId = form ? form.dataset.itemId : '';
        if (!itemId) return;
        const message = (messageEl && messageEl.value || '').trim() || null;
        DialogCore.close('detail-dialog');
        await Board.resumeAgent(itemId, message);
    },

    switchDetailTab(tabName) {
        DialogUtils.showTab(tabName, this._tabs);
    },

    /** Fallback view for items in the Questions column (no model / column buttons). */
    async _showDetailDirect(itemId) {
        const item = await DialogUtils.fetchItem(itemId);
        if (!item) return;

        document.getElementById('detail-title').textContent = item.title;
        const detailBodyEl = document.getElementById('detail-body');
        detailBodyEl.innerHTML = DialogUtils.renderMarkdown(item.description || '(no description)');
        DialogUtils.runMermaid(detailBodyEl);

        const editBtn = document.getElementById('detail-edit-btn');
        const deleteBtn = document.getElementById('detail-delete-btn');
        const isQuestions = item.column_name === 'questions';
        editBtn.style.display = isQuestions ? 'none' : '';
        deleteBtn.style.display = isQuestions ? 'none' : '';
        editBtn.onclick = () => { DialogCore.close('detail-dialog'); ItemDialog.openEditItem(item); };

        const oldPlay = document.getElementById('detail-play-btn');
        if (oldPlay) oldPlay.remove();

        this._hideAutoApprove();
        // Questions items are never paused — but hide the resume form so it
        // never carries over from a previous open of a paused item.
        this._setupResumeForm('');

        await DialogUtils.loadWorkLog(itemId, document.getElementById('detail-log'));

        this.switchDetailTab((this._isAgentActive(item) || item.column_name === 'done') ? 'detail-wlog' : 'detail-desc');
        DialogCore.open('detail-dialog');
    },
};
