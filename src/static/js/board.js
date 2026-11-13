const Board = {
    // Client-side items cache
    items: {},

    // Track collapsed state of done/archive day groups (date string -> boolean)
    _collapsedDoneGroups: {},
    _collapsedArchiveGroups: {},

    // Epic state
    _epics: [],
    _epicFilter: null,  // currently filtered epic_id or null
    _epicPanelExpanded: localStorage.getItem('epicPanelExpanded') === 'true',
    _collapsedTodoEpicGroups: {},

    // Blocked status: item_id -> [{id, title}, ...] of blocking items
    _blockedItems: {},

    // Track items running in YOLO mode
    _yoloItems: new Set(),

    // Track items currently being inspected by the auto-review agent.
    // Used to render a "Reviewing" badge on review-column cards while a
    // separate read-only review session is in flight.
    _autoReviewingItems: new Set(),

    // djb2 hash mapped to a hue; must match Python's _repo_hue in app.py so
    // server-rendered cards and JS-rendered cards agree on repo color.
    repoHue(name) {
        let h = 5381;
        const s = String(name || '');
        for (let i = 0; i < s.length; i++) {
            h = ((h * 33) + s.charCodeAt(i)) >>> 0;
        }
        return h % 360;
    },

    async init(initialItems) {
        for (const item of initialItems) {
            this.items[item.id] = item;
        }
        // Fetch full item data from API to supplement data-attribute-based
        // initial items. This ensures fields like start_copy (which may not
        // be present in data attributes on older cached templates) are loaded.
        await this.refreshItemData();
        await this.loadEpics();
        await this.loadBlockedStatus();
        await this.loadYoloItems();
        await this.loadAutoReviewingItems();
        this.renderTodoColumn();
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },

    async refreshItemData() {
        try {
            const items = await Api.getItems();
            for (const item of items) {
                // Merge API data into existing items, preserving any
                // client-side-only fields (e.g. log_count from data attrs)
                this.items[item.id] = { ...this.items[item.id], ...item };
            }
        } catch (e) {
            console.error('Failed to refresh item data:', e);
        }
    },

    async loadYoloItems() {
        try {
            const ids = await Api.request('GET', '/api/yolo-items');
            this._yoloItems = new Set(ids);
        } catch { /* ignore */ }
    },

    async loadAutoReviewingItems() {
        try {
            const ids = await Api.request('GET', '/api/auto-reviewing-items');
            this._autoReviewingItems = new Set(ids);
            // Inject the badge into any cards already rendered server-side
            // (review-column cards exist in the DOM before init() runs).
            for (const itemId of this._autoReviewingItems) {
                this._applyAutoReviewBadge(itemId, true);
            }
        } catch { /* ignore */ }
    },

    setAutoReviewing(itemId, active) {
        if (active) {
            this._autoReviewingItems.add(itemId);
        } else {
            this._autoReviewingItems.delete(itemId);
        }
        this._applyAutoReviewBadge(itemId, active);
    },

    // Surgically add/remove the "Reviewing" status badge on an existing
    // review-column card without re-rendering the whole card. Mirrors the
    // approach used for YOLO badges so we don't fight the server-rendered
    // initial DOM.
    _applyAutoReviewBadge(itemId, active) {
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (!card) return;
        // Don't overlay the reviewing badge if the item already has a real
        // status (e.g. conflict, merge_blocked) — that takes precedence.
        const existingStatus = card.querySelector('.card-status');
        const isReviewing = !!existingStatus && existingStatus.classList.contains('card-status-reviewing');
        if (!active) {
            if (isReviewing) existingStatus.remove();
            return;
        }
        if (!existingStatus) this._insertReviewingBadge(card);
    },

    _insertReviewingBadge(card) {
        const badge = document.createElement('div');
        badge.className = 'card-status card-status-reviewing';
        badge.dataset.mapName = 'card.status';
        badge.innerHTML = '<span class="spinner"></span> Reviewing';
        const titleEl = card.querySelector('.card-title');
        if (titleEl && titleEl.parentNode) {
            titleEl.parentNode.insertBefore(badge, titleEl.nextSibling);
        }
    },

    setYoloMode(itemId, active) {
        if (active) {
            this._yoloItems.add(itemId);
        } else {
            this._yoloItems.delete(itemId);
        }
        // Update the card's YOLO badge
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (card) {
            const existing = card.querySelector('.card-yolo-badge');
            if (active && !existing) {
                const statusEl = card.querySelector('.card-status');
                if (statusEl) {
                    const badge = document.createElement('span');
                    badge.className = 'card-yolo-badge';
                    badge.textContent = '⚡ YOLO';
                    statusEl.appendChild(badge);
                }
            } else if (!active && existing) {
                existing.remove();
            }
        }
    },

    async loadBlockedStatus() {
        try {
            this._blockedItems = await Api.request('GET', '/api/items/blocked-status');
        } catch (e) {
            console.error('Failed to load blocked status:', e);
            this._blockedItems = {};
        }
    },

    isItemBlocked(itemId) {
        const blockers = this._blockedItems[itemId];
        return blockers && blockers.length > 0;
    },

    getBlockingItems(itemId) {
        return this._blockedItems[itemId] || [];
    },

    updateBlockedStatus(blockedStatus) {
        this._blockedItems = blockedStatus;
        this.renderTodoColumn();
    },

    // --- Drag and drop ---

    _dropIndicator: null,

    _getOrCreateIndicator() {
        if (!this._dropIndicator) {
            const el = document.createElement('div');
            el.className = 'drop-indicator';
            this._dropIndicator = el;
        }
        return this._dropIndicator;
    },

    _removeIndicator() {
        if (this._dropIndicator && this._dropIndicator.parentNode) {
            this._dropIndicator.parentNode.removeChild(this._dropIndicator);
        }
        // Remove all spacing classes
        document.querySelectorAll('.drag-space-before').forEach(c => {
            c.classList.remove('drag-space-before');
        });
    },

    _getInsertPosition(col, y) {
        const cards = [...col.querySelectorAll('.card:not(.dragging)')];
        for (let i = 0; i < cards.length; i++) {
            const rect = cards[i].getBoundingClientRect();
            if (y < rect.top + rect.height / 2) {
                return { index: i, before: cards[i] };
            }
        }
        return { index: cards.length, before: null };
    },

    handleDragStart(event) {
        const card = event.target.closest('.card');
        if (!card) return;
        card.classList.add('dragging');
        event.dataTransfer.setData('text/plain', card.dataset.id);
        event.dataTransfer.effectAllowed = 'move';
    },

    handleDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        const col = event.target.closest('.column-cards');
        if (!col) return;

        col.classList.add('drag-over');

        // Show drop indicator and space cards apart at insertion point
        const indicator = this._getOrCreateIndicator();
        const { before } = this._getInsertPosition(col, event.clientY);

        // Remove old spacing
        col.querySelectorAll('.drag-space-before').forEach(c => {
            c.classList.remove('drag-space-before');
        });

        if (before) {
            col.insertBefore(indicator, before);
            before.classList.add('drag-space-before');
        } else {
            col.appendChild(indicator);
        }
    },

    handleDragLeave(event) {
        const col = event.target.closest('.column-cards');
        if (!col) return;
        // Only remove if actually leaving the column (not entering a child)
        const related = event.relatedTarget;
        if (related && col.contains(related)) return;
        col.classList.remove('drag-over');
        this._removeIndicator();
    },

    handleDragEnd(event) {
        document.querySelectorAll('.card.dragging').forEach(c => c.classList.remove('dragging'));
        document.querySelectorAll('.column-cards.drag-over').forEach(c => c.classList.remove('drag-over'));
        this._removeIndicator();
    },

    async handleDrop(event) {
        event.preventDefault();
        const col = event.target.closest('.column-cards');
        if (col) col.classList.remove('drag-over');
        this._removeIndicator();

        const itemId = event.dataTransfer.getData('text/plain');
        if (!itemId || !col) return;

        const columnName = col.dataset.column;
        const { index: position } = this._getInsertPosition(col, event.clientY);

        // Remove dragging state
        document.querySelectorAll('.card.dragging').forEach(c => c.classList.remove('dragging'));

        try {
            await Api.moveItem(itemId, columnName, position);
        } catch (err) {
            console.error('Failed to move item:', err);
            location.reload();
        }
    },

    // --- Actions ---

    async moveItem(itemId, targetColumn) {
        try {
            await Api.moveItem(itemId, targetColumn, 0);
        } catch (err) {
            console.error('Failed to move item:', err);
        }
    },

    async archiveByDate(dateStr) {
        if (!await Dialogs.confirm(`Archive all items from ${dateStr}?`, 'Confirm', 'Archive')) return;
        try {
            await Api.archiveByDate(dateStr);
        } catch (err) {
            console.error('Failed to archive items:', err);
        }
    },

    async deleteEpicTodos(epicId, epicTitle) {
        if (!await Dialogs.confirm(`Delete all todo items in "${epicTitle}"?`, 'Confirm', 'Delete')) return;
        try {
            await Api.request('POST', '/api/items/delete-by-epic', { epic_id: epicId });
            await this.loadEpics();
            await this.loadAndRender();
        } catch (err) {
            console.error('Failed to delete epic todos:', err);
        }
    },


    async deleteByDate(dateStr, columnName) {
        if (!await Dialogs.confirm(`Delete all ${columnName} items from ${dateStr}?`)) return;
        try {
            await Api.deleteByDate(dateStr, columnName);
        } catch (err) {
            console.error('Failed to delete items:', err);
        }
    },

    async startAgent(itemId) {
        await this._startUnlessBlocked(itemId, () => Api.startAgent(itemId), 'Failed to start agent:');
    },

    async startCopyAgent(itemId) {
        await this._startUnlessBlocked(itemId, () => Api.startCopyAgent(itemId), 'Failed to start copy of agent:');
    },

    /** Run ``start`` unless the item is blocked by unresolved dependencies. */
    async _startUnlessBlocked(itemId, start, failureMessage) {
        if (this.isItemBlocked(itemId)) {
            const blockers = this.getBlockingItems(itemId).map(b => b.title).join(', ');
            console.warn(`Cannot start blocked item ${itemId}. Blocked by: ${blockers}`);
            return;
        }
        try {
            await start();
        } catch (err) {
            console.error(failureMessage, err);
        }
    },

    // Apply an immediate visual "stopping" state on the card while the
    // backend processes a pause/cancel. Cleared when the server's
    // item_updated WebSocket event triggers a full re-render via updateCard().
    applyStoppingState(itemId, label) {
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (!card) return;
        card.classList.add('is-stopping');
        const statusEl = card.querySelector('.card-status');
        if (statusEl) {
            statusEl.className = 'card-status card-status-stopping';
            statusEl.innerHTML = `<span class="spinner"></span> ${label}`;
        }
        card.querySelectorAll('.card-actions .btn').forEach(btn => {
            btn.disabled = true;
            btn.classList.add('btn-disabled');
        });
    },

    async pauseAgent(itemId) {
        // Pause is a single-click action: stop the agent immediately. To send
        // a course-correction note, the user opens the work log (detail
        // dialog) on a paused item and submits the Continue form.
        this.applyStoppingState(itemId, 'Pausing…');
        try {
            await Api.pauseAgent(itemId, null);
        } catch (err) {
            console.error('Failed to pause agent:', err);
        }
    },

    async resumeAgent(itemId, message = null) {
        try {
            await Api.resumeAgent(itemId, message);
        } catch (err) {
            console.error('Failed to resume agent:', err);
        }
    },

    async cancelAgent(itemId) {
        this.applyStoppingState(itemId, 'Cancelling…');
        try {
            await Api.cancelAgent(itemId);
        } catch (err) {
            console.error('Failed to cancel agent:', err);
        }
    },

    async retryAgent(itemId) {
        try {
            await Api.retryAgent(itemId);
        } catch (err) {
            console.error('Failed to retry agent:', err);
        }
    },

    async approveItem(itemId) {
        try {
            await Api.approveItem(itemId);
        } catch (err) {
            console.error('Failed to approve item:', err);
        }
    },

    async deleteItem(itemId) {
        if (!await Dialogs.confirm('Delete this item?')) return;
        try {
            await Api.deleteItem(itemId);
        } catch (err) {
            console.error('Failed to delete item:', err);
        }
    },

    requestChanges(itemId) {
        Dialogs.openRequestChanges(itemId);
    },

    async cancelReview(itemId) {
        try {
            await Api.cancelReview(itemId);
        } catch (err) {
            console.error('Failed to cancel review:', err);
        }
    },

    async rerunItem(itemId) {
        try {
            // Fetch fresh item data from the API (cache may only have {id})
            const items = await Api.getItems();
            const originalItem = items.find(i => i.id === itemId);
            if (!originalItem) {
                console.error('Item not found:', itemId);
                return;
            }

            // Create a new item with the same title, description, model,
            // epic, repo, auto-start, start-as-copy, and auto-approve
            // settings. Without forwarding these the user's intent (e.g. to
            // auto-approve the rerun, or to keep it in the same epic) gets
            // silently dropped on every retry.
            const newItem = await Api.createItem(
                originalItem.title,
                originalItem.description || '',
                originalItem.model,
                originalItem.epic_id || null,
                !!originalItem.auto_start,
                !!originalItem.start_copy,
                originalItem.repo || null,
                // auto_approve is a tri-state int (0/1/2). Forward the mode as-is
                // so a "Direct" item stays Direct, a "With Review" item stays
                // With Review, etc. on the rerun.
                Number(originalItem.auto_approve) || 0,
            );

            // Copy attachments from the original item to the new item
            try {
                const attachments = await Api.getAttachments(itemId);
                await Promise.all(attachments.map(a => this._copyAttachment(a, newItem.id)));
            } catch (attachmentErr) {
                console.error('Failed to copy attachments:', attachmentErr);
                // Continue even if attachments fail - the item is still created
            }

            // Refresh the board to show the new item
            await this.loadAndRender();

        } catch (err) {
            console.error('Failed to re-run item:', err);
        }
    },

    /** Copy one attachment's asset onto another item; a missing asset (404) is skipped. */
    async _copyAttachment(attachment, toItemId) {
        const response = await fetch(`/api/assets/${attachment.asset_path.split('/').pop()}`);
        if (!response.ok) return;
        const blob = await response.blob();
        await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onloadend = async () => {
                try {
                    await Api.createAttachment(toItemId, attachment.filename, reader.result);
                } catch (attachErr) {
                    console.error('Failed to copy attachment:', attachErr);
                }
                resolve(); // resolve anyway so we still refresh
            };
            reader.onerror = () => resolve();
            reader.readAsDataURL(blob);
        });
    },

    // --- Re-rendering ---

    async loadAndRender() {
        const [items] = await Promise.all([
            Api.getItems(),
            this.loadBlockedStatus(),
        ]);
        this.items = {};
        // Clear all column cards
        document.querySelectorAll('.column-cards').forEach(col => {
            col.innerHTML = '';
        });
        for (const item of items) {
            this.items[item.id] = item;
            if (!this._groupedColumns.includes(item.column_name)) {
                const targetCol = document.querySelector(`.column-cards[data-column="${item.column_name}"]`);
                if (targetCol) {
                    targetCol.appendChild(this.renderCard(item));
                }
            }
        }
        this.renderTodoColumn();
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },

    renderCard(item) {
        const div = document.createElement('div');
        div.className = 'card';
        div.dataset.id = item.id;
        div.dataset.column = item.column_name;
        div.dataset.status = item.status || '';
        div.dataset.title = item.title;
        div.dataset.doneAt = item.done_at || '';
        div.dataset.updatedAt = item.updated_at || '';
        div.dataset.mapName = 'card';
        div.draggable = true;
        div.ondragstart = (e) => Board.handleDragStart(e);
        div.onclick = () => Dialogs.showDetail(item.id);

        // Blocked badge / disabled start button for todo items
        const isBlocked = item.column_name === 'todo' && this.isItemBlocked(item.id);
        div.innerHTML = `
            ${this._cardEpicBadgeHtml(item)}
            ${this._cardRepoBadgeHtml(item)}
            <div class="card-title" data-map-name="card.title">${this.escapeHtml(item.title)}</div>
            ${isBlocked ? this._cardBlockedHtml(item) : ''}
            ${this._cardStatusHtml(item)}
            <div class="card-bottom">
                <div class="card-actions" data-map-name="card.actions">${this._cardActionsHtml(item, isBlocked)}</div>
                ${this._cardModelBadgeHtml(item)}
                ${this._cardTimestampHtml(item)}
                ${this._cardLogCountHtml(item)}
            </div>
        `;
        return div;
    },

    _cardEpicBadgeHtml(item) {
        // Hidden while filtering by epic, and in Todo (grouped by epic already)
        if (this._epicFilter || item.column_name === 'todo') return '';
        if (!item.epic_id) return '';
        const epic = this._epics.find(e => e.id === item.epic_id);
        if (!epic) return '';
        return `<div class="card-epic-badge" data-map-name="card.epic-badge"><span class="epic-dot" style="background: var(--epic-${epic.color})"></span>${this.escapeHtml(epic.title)}</div>`;
    },

    /** Multi-repo badge (matches server-rendered card.html; uses same djb2 hue). */
    _cardRepoBadgeHtml(item) {
        if (!item.repo) return '';
        const hue = Board.repoHue(item.repo);
        const repoEsc = this.escapeHtml(item.repo);
        return `<span class="card-repo-badge" data-map-name="card.repo-badge" data-repo="${repoEsc}" style="--repo-hue: ${hue}" title="Repo: ${repoEsc}">${repoEsc}</span>`;
    },

    _cardStatusLabels: {
        running: '<span class="spinner"></span> Running',
        queued: '⏳ Queued',
        paused: '⏸ Paused',
        failed: '✕ Failed',
        cancelled: '⊘ Cancelled',
        conflict: '⚠ Merge conflict',
        merge_blocked: '⚠ Merge blocked',
        resolving_conflicts: '<span class="spinner"></span> Resolving conflicts',
    },

    _cardStatusHtml(item) {
        if (item.status) {
            const isActive = item.status === 'running' || item.status === 'resolving_conflicts';
            const yoloBadge = isActive && this._yoloItems.has(item.id)
                ? '<span class="card-yolo-badge">⚡ YOLO</span>' : '';
            return `<div class="card-status card-status-${item.status}" data-map-name="card.status">${this._cardStatusLabels[item.status] || item.status}${yoloBadge}</div>`;
        }
        if (item.column_name === 'review' && this._autoReviewingItems.has(item.id)) {
            // Review column item with no DB status but an auto-review agent
            // is actively inspecting its diff — surface that to the user the
            // same way Running is surfaced for Doing.
            return `<div class="card-status card-status-reviewing" data-map-name="card.status"><span class="spinner"></span> Reviewing</div>`;
        }
        return '';
    },

    _cardBlockedHtml(item) {
        const blockers = this.getBlockingItems(item.id);
        const names = blockers.map(b => this.escapeHtml(b.title)).join(', ');
        const items = blockers.map(b => `<span class="blocked-item">🔒 ${this.escapeHtml(b.title)}</span>`).join('');
        return `<div class="card-blocked-badge" data-map-name="card.blocked-badge" title="Requires: ${names}">${items}</div>`;
    },

    _cardActionsHtml(item, isBlocked) {
        const deleteBtn = `<button class="btn btn-xs btn-delete" data-map-name="card.btn-delete" onclick="event.stopPropagation(); Board.deleteItem('${item.id}')" title="Delete">✕</button>`;
        switch (item.column_name) {
            case 'todo': return this._todoActionsHtml(item, isBlocked) + deleteBtn;
            case 'doing': return this._doingActionsHtml(item);
            case 'review': return this._reviewActionsHtml(item);
            case 'questions':
                return `<button class="btn btn-xs" data-map-name="card.btn-archive" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦 Archive</button>`;
            case 'done':
                return `<button class="btn btn-xs" data-map-name="card.btn-rerun" onclick="event.stopPropagation(); Board.rerunItem('${item.id}')" title="Re-run">↻</button>`
                    + `<button class="btn btn-xs" data-map-name="card.btn-archive" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦 Archive</button>`;
            case 'archive': return deleteBtn;
            default: return '';
        }
    },

    /** Start (or start-copy) button; disabled with a "Blocked by" tooltip when blocked. */
    _todoActionsHtml(item, isBlocked) {
        const blockedTooltip = isBlocked
            ? `Blocked by: ${this.getBlockingItems(item.id).map(b => b.title).join(', ')}`
            : 'Start agent';
        const disabledAttr = isBlocked ? ' disabled' : '';
        const disabledClass = isBlocked ? ' btn-disabled' : '';
        if (item.start_copy) {
            return `<button class="btn btn-xs btn-primary${disabledClass}" data-map-name="card.btn-start-copy" onclick="event.stopPropagation(); Board.startCopyAgent('${item.id}')" title="${isBlocked ? this.escapeHtml(blockedTooltip) : 'Start Copy (keep original in Todo)'}"${disabledAttr}>▶⧉</button>`;
        }
        return `<button class="btn btn-xs btn-primary${disabledClass}" data-map-name="card.btn-start" onclick="event.stopPropagation(); Board.startAgent('${item.id}')" title="${this.escapeHtml(blockedTooltip)}"${disabledAttr}>▶</button>`;
    },

    _doingActionsHtml(item) {
        const cancelBtn = `<button class="btn btn-xs btn-danger" data-map-name="card.btn-cancel" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')" title="Cancel">✕</button>`;
        switch (item.status) {
            case 'queued': return cancelBtn;
            case 'failed':
                return `<button class="btn btn-xs" data-map-name="card.btn-retry" onclick="event.stopPropagation(); Board.retryAgent('${item.id}')" title="Retry">↻ Retry</button>
                <button class="btn btn-xs" data-map-name="card.btn-move-to-todo" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'todo')" title="Move to 📝 Todo">→ 📝 Todo</button>`;
            case 'running':
                return `<button class="btn btn-xs btn-warning" data-map-name="card.btn-pause" onclick="event.stopPropagation(); Board.pauseAgent('${item.id}')" title="Pause">⏸</button>
                ${cancelBtn}`;
            case 'paused':
                return `<button class="btn btn-xs btn-primary" data-map-name="card.btn-resume" onclick="event.stopPropagation(); Board.resumeAgent('${item.id}')" title="Resume">▶</button>
                ${cancelBtn}`;
            default: return '';
        }
    },

    _reviewActionsHtml(item) {
        const hasChanges = item.has_file_changes !== 0;
        const approveLabel = hasChanges ? '✓ Approve' : '✓ Done';
        const approveTitle = hasChanges ? 'Approve & Merge' : 'Done';
        const approveName = hasChanges ? 'card.btn-approve' : 'card.btn-done';
        // Even when there are no file changes, route through the review
        // dialog so the agent's closing message is surfaced on the Result
        // tab instead of being lost when pressing Done from the card.
        const approveAction = hasChanges
            ? `Board.approveItem('${item.id}')`
            : `ReviewDialog.showReview('${item.id}')`;
        return `<button class="btn btn-xs btn-primary" data-map-name="${approveName}" onclick="event.stopPropagation(); ${approveAction}" title="${approveTitle}">${approveLabel}</button>
                <button class="btn btn-xs" data-map-name="card.btn-request-changes" onclick="event.stopPropagation(); Board.requestChanges('${item.id}')" title="Request changes">↩</button>
                <button class="btn btn-xs btn-danger" data-map-name="card.btn-cancel-review" onclick="event.stopPropagation(); Board.cancelReview('${item.id}')" title="Cancel review">✕</button>`;
    },

    _cardLogCountHtml(item) {
        if (item.column_name !== 'doing' || !(item.log_count > 0)) return '';
        return `<div class="card-log-count" data-map-name="card.log-count" data-log-count="${item.id}">${item.log_count}</div>`;
    },

    _cardTimestampHtml(item) {
        const ts = item.done_at || item.updated_at;
        if (item.column_name !== 'done' || !ts) return '';
        const timeStr = new Date(ts + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        return `<span class="card-timestamp" data-map-name="card.timestamp">${timeStr}</span>`;
    },

    /** Model badge — only for local (Ollama / Tiiny) models. */
    _cardModelBadgeHtml(item) {
        if (!item.model || !DialogUtils._isLocalModel(item.model)) return '';
        const shortName = DialogUtils._getModelDisplayName(item.model);
        return `<span class="card-model-badge" data-map-name="card.model-badge" title="${item.model}">${shortName}</span>`;
    },

    _getDoneDateKey(item) {
        const ts = item.done_at || item.updated_at;
        if (!ts) return 'Unknown';
        const d = new Date(ts + 'Z');
        return d.toISOString().split('T')[0]; // YYYY-MM-DD
    },

    _formatDateLabel(dateStr) {
        const today = new Date();
        const todayStr = today.toISOString().split('T')[0];
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const yesterdayStr = yesterday.toISOString().split('T')[0];

        if (dateStr === todayStr) return 'Today';
        if (dateStr === yesterdayStr) return 'Yesterday';
        if (dateStr === 'Unknown') return 'Unknown date';
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    },

    _isTodayGroup(dateStr) {
        const today = new Date().toISOString().split('T')[0];
        return dateStr === today;
    },

    toggleEpicPanel() {
        this._epicPanelExpanded = !this._epicPanelExpanded;
        localStorage.setItem('epicPanelExpanded', this._epicPanelExpanded);
        this._renderEpicPanel();
    },

    async loadEpics() {
        try {
            this._epics = await Api.request('GET', '/api/epics');
        } catch (e) {
            console.error('Failed to load epics:', e);
            this._epics = [];
        }
        this._renderEpicPanel();
    },

    // Compute epic progress live from Board.items so the archive button
    // reflects the current state on every WS event without waiting for a
    // debounced /api/epics refresh. Falls back to epic.progress (server-side
    // count) only when items haven't loaded yet.
    _computeEpicProgress(epicId, fallback) {
        const items = Object.values(this.items).filter(i => i.epic_id === epicId);
        if (items.length === 0 && fallback) return fallback;
        const p = { todo: 0, doing: 0, questions: 0, review: 0, done: 0, archive: 0, total: 0 };
        for (const it of items) {
            if (Object.prototype.hasOwnProperty.call(p, it.column_name)) {
                p[it.column_name] += 1;
            }
            if (it.column_name !== 'archive') p.total += 1;
        }
        return p;
    },

    _isEpicFullyArchived(epic) {
        const p = this._computeEpicProgress(epic.id, epic.progress) || {};
        const archived = (p.archive || 0);
        // Epic has items and all are archived (total excludes archive, so check it's 0)
        return archived > 0 && (p.total || 0) === 0;
    },

    _renderEpicPanel() {
        const toggle = document.querySelector('.epic-panel-toggle');
        const panel = document.getElementById('epic-panel');
        if (!toggle || !panel) return;

        toggle.classList.toggle('expanded', this._epicPanelExpanded);
        panel.classList.toggle('visible', this._epicPanelExpanded);
        if (!this._epicPanelExpanded) return;

        let html = '';
        for (const epic of this._epics) {
            if (!this._isEpicFullyArchived(epic)) html += this._epicCardHtml(epic);
        }
        if (this._epicFilter) {
            html += `<button class="epic-filter-clear" onclick="Board.clearEpicFilter()">Clear filter</button>`;
        }
        panel.innerHTML = html;
        this._wireEpicPanel(panel);
    },

    /** One epic in the panel: progress bar, and an Archive button once every item is done. */
    _epicCardHtml(epic) {
        const p = this._computeEpicProgress(epic.id, epic.progress) || {};
        const done = (p.done || 0);
        const total = (p.total || 0);
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        const isActive = this._epicFilter === epic.id;
        const isComplete = total > 0 && done === total;
        const archiveBtn = isComplete
            ? `<button class="epic-archive-btn" title="Archive all items in this epic" data-epic-id="${epic.id}" data-epic-title="${Board.escapeHtml(epic.title)}">Archive</button>`
            : '';
        return `
                <div class="epic-card${isActive ? ' active' : ''}${isComplete ? ' complete' : ''}" data-epic-id="${epic.id}">
                    <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                    <span class="epic-card-title">${Board.escapeHtml(epic.title)}</span>
                    <div class="epic-progress-bar">
                        <div class="epic-progress-fill" style="width: ${pct}%; background: var(--epic-${epic.color})"></div>
                    </div>
                    <span class="epic-progress-count">${done}/${total}</span>
                    ${archiveBtn}
                </div>
            `;
    },

    // Wire up handlers — using delegation on the cards so the archive
    // button can stop propagation and not trigger the filter-by-epic click.
    _wireEpicPanel(panel) {
        panel.querySelectorAll('.epic-card').forEach(card => {
            const epicId = card.dataset.epicId;
            card.addEventListener('click', (e) => {
                if (e.target.closest('.epic-archive-btn')) return;
                Board.filterByEpic(epicId);
            });
        });
        panel.querySelectorAll('.epic-archive-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                Board.archiveEpic(btn.dataset.epicId, btn.dataset.epicTitle);
            });
        });
    },

    async archiveEpic(epicId, epicTitle) {
        if (!await Dialogs.confirm(`Archive all items in "${epicTitle}"?`, 'Confirm', 'Archive')) return;
        try {
            const res = await Api.request('POST', '/api/items/archive-by-epic', { epic_id: epicId });
            if (this._epicFilter === epicId) this.clearEpicFilter();
            await this.loadEpics();
        } catch (err) {
            console.error('Failed to archive epic:', err);
            await Dialogs.alert('Failed to archive epic items.');
        }
    },

    filterByEpic(epicId) {
        if (this._epicFilter === epicId) {
            this.clearEpicFilter();
            return;
        }
        this._epicFilter = epicId;
        this._renderEpicPanel();
        this._applyEpicFilter();
    },

    clearEpicFilter() {
        this._epicFilter = null;
        this._renderEpicPanel();
        this._applyEpicFilter();
    },

    /** Columns rendered by their own grouping code (not as a flat card list). */
    _groupedColumns: ['todo', 'done', 'archive'],

    _applyEpicFilter() {
        // Show/hide cards based on epic filter in non-grouped columns
        document.querySelectorAll('.column-cards').forEach(col => {
            if (this._groupedColumns.includes(col.dataset.column)) return;
            col.querySelectorAll('.card').forEach(card => {
                card.style.display = this._matchesEpicFilter(this.items[card.dataset.id]) ? '' : 'none';
            });
        });
        // Re-render columns that use grouped rendering
        this.renderTodoColumn();
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },

    _matchesEpicFilter(item) {
        if (!this._epicFilter) return true;
        return !!item && item.epic_id === this._epicFilter;
    },

    renderTodoColumn() {
        const col = document.querySelector('.column-cards[data-column="todo"]');
        if (!col) return;

        const todoItems = Object.values(this.items).filter(i => i.column_name === 'todo');
        const filtered = todoItems.filter(i => this._matchesEpicFilter(i));

        col.innerHTML = '';
        // If filtered to one epic or no epics exist, render flat
        if (this._epicFilter || this._epics.length === 0) {
            this._appendCardsByPosition(col, filtered);
            return;
        }

        // Group by epic; epic groups in epic position order, "No Epic" at the bottom
        const { epicGroups, noEpic } = this._groupByEpic(filtered);
        for (const epic of this._epics) {
            const items = epicGroups[epic.id];
            if (!items || items.length === 0) continue;
            col.appendChild(this._renderTodoGroup(epic.id, items, `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                ${Board.escapeHtml(epic.title)}
                <button class="todo-epic-delete" title="Delete all todos in this epic">&times;</button>
                <span class="todo-epic-count">${items.length}</span>
            `, () => Board.deleteEpicTodos(epic.id, epic.title)));
        }
        if (noEpic.length > 0) {
            col.appendChild(this._renderTodoGroup('__none__', noEpic, `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                No Epic
                <span class="todo-epic-count" style="margin-left: auto">${noEpic.length}</span>
            `));
        }
    },

    _groupByEpic(items) {
        const epicGroups = {};
        const noEpic = [];
        for (const item of items) {
            if (item.epic_id) (epicGroups[item.epic_id] ||= []).push(item);
            else noEpic.push(item);
        }
        return { epicGroups, noEpic };
    },

    /** A collapsible Todo group; ``onDelete`` wires the header's delete button (epics only). */
    _renderTodoGroup(groupKey, items, headerHtml, onDelete = null) {
        const isCollapsed = this._collapsedTodoEpicGroups[groupKey] || false;
        const group = document.createElement('div');
        group.className = 'todo-epic-group';

        const header = document.createElement('div');
        header.className = 'todo-epic-header' + (isCollapsed ? '' : ' expanded');
        header.innerHTML = headerHtml;
        header.addEventListener('click', (e) => {
            if (e.target.closest('.todo-epic-delete')) return;
            this._collapsedTodoEpicGroups[groupKey] = !isCollapsed;
            this.renderTodoColumn();
        });
        if (onDelete) {
            header.querySelector('.todo-epic-delete').addEventListener('click', (e) => {
                e.stopPropagation();
                onDelete();
            });
        }
        group.appendChild(header);

        if (!isCollapsed) this._appendCardsByPosition(group, items);
        return group;
    },

    _appendCardsByPosition(container, items) {
        items.sort((a, b) => (a.position || 0) - (b.position || 0));
        for (const item of items) {
            container.appendChild(this.renderCard(item));
        }
    },

    renderDoneColumn() {
        this._renderDayGroupedColumn({
            column: 'done',
            collapsedState: this._collapsedDoneGroups,
            // default: today expanded, others collapsed
            defaultCollapsed: (dateStr) => !this._isTodayGroup(dateStr),
            headerButtonHtml: (dateStr) => `<button class="btn btn-xs done-day-archive" data-map-name="board.day-group.btn-archive-all" onclick="event.stopPropagation(); Board.archiveByDate('${dateStr}')" title="Archive all from ${this._formatDateLabel(dateStr)}">📦</button>`,
            rerender: () => this.renderDoneColumn(),
        });
    },

    renderArchiveColumn() {
        this._renderDayGroupedColumn({
            column: 'archive',
            collapsedState: this._collapsedArchiveGroups,
            defaultCollapsed: () => true,  // default: all collapsed
            headerButtonHtml: (dateStr) => `<button class="btn btn-xs btn-delete done-day-archive" data-map-name="board.day-group.btn-delete-all" onclick="event.stopPropagation(); Board.deleteByDate('${dateStr}', 'archive')" title="Delete all from ${this._formatDateLabel(dateStr)}">✕</button>`,
            rerender: () => this.renderArchiveColumn(),
        });
    },

    /** Done / Archive: cards grouped into collapsible per-day groups, newest day first. */
    _renderDayGroupedColumn(opts) {
        const col = document.querySelector(`.column-cards[data-column="${opts.column}"]`);
        if (!col) return;

        let columnItems = Object.values(this.items).filter(i => i.column_name === opts.column);
        if (this._epicFilter) columnItems = columnItems.filter(i => i.epic_id === this._epicFilter);
        const groups = {};
        for (const item of columnItems) {
            (groups[this._getDoneDateKey(item)] ||= []).push(item);
        }

        col.innerHTML = '';
        for (const dateStr of this._sortedDateKeys(groups)) {
            col.appendChild(this._renderDayGroup(dateStr, groups[dateStr], opts));
        }
    },

    _renderDayGroup(dateStr, items, { collapsedState, defaultCollapsed, headerButtonHtml, rerender }) {
        const isCollapsed = dateStr in collapsedState ? collapsedState[dateStr] : defaultCollapsed(dateStr);

        const group = document.createElement('div');
        group.className = 'done-day-group' + (isCollapsed ? ' collapsed' : '');
        group.dataset.date = dateStr;
        group.dataset.mapName = 'board.day-group';

        const header = document.createElement('div');
        header.className = 'done-day-header';
        header.dataset.mapName = 'board.day-group.header';
        header.innerHTML = `
                <svg class="done-day-chevron${isCollapsed ? '' : ' expanded'}" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="done-day-label" data-map-name="board.day-group.label">${this._formatDateLabel(dateStr)}</span>
                <span class="done-day-count" data-map-name="board.day-group.count">${items.length}</span>
                ${headerButtonHtml(dateStr)}
            `;
        header.addEventListener('click', () => {
            collapsedState[dateStr] = !isCollapsed;
            rerender();
        });
        group.appendChild(header);

        if (!isCollapsed) group.appendChild(this._dayGroupCards(items));
        return group;
    },

    /** The day's cards, newest first (done_at, falling back to updated_at). */
    _dayGroupCards(items) {
        const stamp = (item) => item.done_at || item.updated_at || '';
        items.sort((a, b) => stamp(b).localeCompare(stamp(a)));
        const cardsContainer = document.createElement('div');
        cardsContainer.className = 'done-day-cards';
        for (const item of items) {
            cardsContainer.appendChild(this.renderCard(item));
        }
        return cardsContainer;
    },

    /** Date keys, most recent first, with 'Unknown' last. */
    _sortedDateKeys(groups) {
        return Object.keys(groups).sort((a, b) => {
            if (a === 'Unknown') return 1;
            if (b === 'Unknown') return -1;
            return b.localeCompare(a);
        });
    },

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    },

    updateCard(item) {
        const prev = this.items[item.id];
        this._carryOverCardFields(prev, item);
        this.items[item.id] = item;

        // Remove old card if exists
        const oldCard = document.querySelector(`.card[data-id="${item.id}"]`);
        if (oldCard) oldCard.remove();

        // Todo / Done / Archive use grouped rendering: re-render the grouped
        // column the card left, then the one it entered (or insert the card
        // into a plain column at its position).
        const prevColumn = prev?.column_name;
        if (prevColumn && prevColumn !== item.column_name) this._renderGroupedColumn(prevColumn);
        if (!this._renderGroupedColumn(item.column_name)) this._insertCard(item);
        this.updateCounts();
    },

    /** Keep fields a partial update leaves out (log_count, start_copy). */
    _carryOverCardFields(prev, item) {
        if (!prev) return;
        if (prev.log_count && !item.log_count) item.log_count = prev.log_count;
        if (prev.start_copy && item.start_copy === undefined) item.start_copy = prev.start_copy;
    },

    /** Re-render a grouped column (todo / done / archive); false for any other column. */
    _renderGroupedColumn(column) {
        const render = {
            todo: () => this.renderTodoColumn(),
            done: () => this.renderDoneColumn(),
            archive: () => this.renderArchiveColumn(),
        }[column];
        if (!render) return false;
        render();
        return true;
    },

    /** Insert the card into its (plain) column at item.position. */
    _insertCard(item) {
        const targetCol = document.querySelector(`.column-cards[data-column="${item.column_name}"]`);
        if (!targetCol) return;
        const newCard = this.renderCard(item);
        const cards = targetCol.querySelectorAll('.card');
        if (item.position < cards.length) {
            targetCol.insertBefore(newCard, cards[item.position]);
        } else {
            targetCol.appendChild(newCard);
        }
    },

    removeCard(itemId) {
        const prev = this.items[itemId];
        delete this.items[itemId];
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (card) card.remove();
        if (prev && prev.column_name === 'todo') this.renderTodoColumn();
        if (prev && prev.column_name === 'done') this.renderDoneColumn();
        if (prev && prev.column_name === 'archive') this.renderArchiveColumn();
        this.updateCounts();
    },

    updateCounts() {
        document.querySelectorAll('.column').forEach(col => {
            const colName = col.dataset.column;
            let count;
            if (colName === 'done' || colName === 'todo') {
                // Count from items cache since cards may be hidden in collapsed groups
                const items = Object.values(this.items).filter(i => i.column_name === colName);
                count = this._epicFilter
                    ? items.filter(i => i.epic_id === this._epicFilter).length
                    : items.length;
            } else if (colName === 'archive') {
                const items = Object.values(this.items).filter(i => i.column_name === 'archive');
                count = this._epicFilter
                    ? items.filter(i => i.epic_id === this._epicFilter).length
                    : items.length;
            } else {
                count = col.querySelectorAll('.card:not([style*="display: none"])').length;
            }
            const badge = col.querySelector('.column-count');
            if (badge) badge.textContent = count;
        });
    },
};

// Wire up drag events on column cards
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.column-cards').forEach(el => {
        el.addEventListener('dragleave', (e) => Board.handleDragLeave(e));
    });
    // Global dragend to clean up if drop happens outside
    document.addEventListener('dragend', (e) => Board.handleDragEnd(e));
});
