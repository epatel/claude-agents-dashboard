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
        if (this.isItemBlocked(itemId)) {
            const blockers = this.getBlockingItems(itemId).map(b => b.title).join(', ');
            console.warn(`Cannot start blocked item ${itemId}. Blocked by: ${blockers}`);
            return;
        }
        try {
            await Api.startAgent(itemId);
        } catch (err) {
            console.error('Failed to start agent:', err);
        }
    },

    async startCopyAgent(itemId) {
        if (this.isItemBlocked(itemId)) {
            const blockers = this.getBlockingItems(itemId).map(b => b.title).join(', ');
            console.warn(`Cannot start blocked item ${itemId}. Blocked by: ${blockers}`);
            return;
        }
        try {
            await Api.startCopyAgent(itemId);
        } catch (err) {
            console.error('Failed to start copy of agent:', err);
        }
    },

    async pauseAgent(itemId) {
        try {
            await Api.pauseAgent(itemId);
        } catch (err) {
            console.error('Failed to pause agent:', err);
        }
    },

    async resumeAgent(itemId) {
        try {
            await Api.resumeAgent(itemId);
        } catch (err) {
            console.error('Failed to resume agent:', err);
        }
    },

    async cancelAgent(itemId) {
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

            // Create a new item with the same title, description, and model
            const newItem = await Api.createItem(
                originalItem.title,
                originalItem.description || '',
                originalItem.model
            );

            // Copy attachments from the original item to the new item
            try {
                const attachments = await Api.getAttachments(itemId);
                const copyPromises = attachments.map(attachment => {
                    return fetch(`/api/assets/${attachment.asset_path.split('/').pop()}`)
                        .then(response => response.blob())
                        .then(blob => new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = async () => {
                                try {
                                    await Api.createAttachment(newItem.id, attachment.filename, reader.result);
                                    resolve();
                                } catch (attachErr) {
                                    console.error('Failed to copy attachment:', attachErr);
                                    resolve(); // resolve anyway so we still refresh
                                }
                            };
                            reader.onerror = () => resolve();
                            reader.readAsDataURL(blob);
                        }));
                });
                await Promise.all(copyPromises);
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
            if (item.column_name !== 'done' && item.column_name !== 'archive' && item.column_name !== 'todo') {
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
        div.draggable = true;
        div.ondragstart = (e) => Board.handleDragStart(e);
        div.onclick = () => Dialogs.showDetail(item.id);

        // Epic badge
        let epicBadgeHtml = '';
        if (item.epic_id && !this._epicFilter && item.column_name !== 'todo') {
            const epic = this._epics.find(e => e.id === item.epic_id);
            if (epic) {
                epicBadgeHtml = `<div class="card-epic-badge"><span class="epic-dot" style="background: var(--epic-${epic.color})"></span>${this.escapeHtml(epic.title)}</div>`;
            }
        }

        let statusHtml = '';
        if (item.status) {
            const labels = {
                running: '<span class="spinner"></span> Running',
                paused: '⏸ Paused',
                failed: '✕ Failed',
                cancelled: '⊘ Cancelled',
                conflict: '⚠ Merge conflict',
                merge_blocked: '⚠ Merge blocked',
                resolving_conflicts: '<span class="spinner"></span> Resolving conflicts',
            };
            const yoloBadge = (item.status === 'running' || item.status === 'resolving_conflicts') && this._yoloItems.has(item.id)
                ? '<span class="card-yolo-badge">⚡ YOLO</span>' : '';
            statusHtml = `<div class="card-status card-status-${item.status}">${labels[item.status] || item.status}${yoloBadge}</div>`;
        }

        // Blocked badge for todo items
        let blockedHtml = '';
        const isBlocked = item.column_name === 'todo' && this.isItemBlocked(item.id);
        if (isBlocked) {
            const blockers = this.getBlockingItems(item.id);
            const names = blockers.map(b => this.escapeHtml(b.title)).join(', ');
            const items = blockers.map(b => `<span class="blocked-item">🔒 ${this.escapeHtml(b.title)}</span>`).join('');
            blockedHtml = `<div class="card-blocked-badge" title="Requires: ${names}">${items}</div>`;
        }

        let actionsHtml = '';
        const col = item.column_name;
        const deleteBtn = `<button class="btn btn-xs btn-delete" onclick="event.stopPropagation(); Board.deleteItem('${item.id}')" title="Delete">✕</button>`;
        if (col === 'todo') {
            const blockedTooltip = isBlocked
                ? `Blocked by: ${this.getBlockingItems(item.id).map(b => b.title).join(', ')}`
                : 'Start agent';
            const disabledAttr = isBlocked ? ' disabled' : '';
            const disabledClass = isBlocked ? ' btn-disabled' : '';
            if (item.start_copy) {
                actionsHtml = `<button class="btn btn-xs btn-primary${disabledClass}" onclick="event.stopPropagation(); Board.startCopyAgent('${item.id}')" title="${isBlocked ? this.escapeHtml(blockedTooltip) : 'Start Copy (keep original in Todo)'}"${disabledAttr}>▶⧉</button>${deleteBtn}`;
            } else {
                actionsHtml = `<button class="btn btn-xs btn-primary${disabledClass}" onclick="event.stopPropagation(); Board.startAgent('${item.id}')" title="${this.escapeHtml(blockedTooltip)}"${disabledAttr}>▶</button>${deleteBtn}`;
            }
        } else if (col === 'doing' && item.status === 'failed') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.retryAgent('${item.id}')" title="Retry">↻ Retry</button>
                <button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'todo')" title="Move to 📝 Todo">→ 📝 Todo</button>`;
        } else if (col === 'doing' && item.status === 'running') {
            actionsHtml = `<button class="btn btn-xs btn-warning" onclick="event.stopPropagation(); Board.pauseAgent('${item.id}')" title="Pause">⏸</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')" title="Cancel">✕</button>`;
        } else if (col === 'doing' && item.status === 'paused') {
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.resumeAgent('${item.id}')" title="Resume">▶</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')" title="Cancel">✕</button>`;
        } else if (col === 'review') {
            const hasChanges = item.has_file_changes !== 0;
            const approveLabel = hasChanges ? '✓ Approve' : '✓ Done';
            const approveTitle = hasChanges ? 'Approve & Merge' : 'Done';
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.approveItem('${item.id}')" title="${approveTitle}">${approveLabel}</button>
                <button class="btn btn-xs" onclick="event.stopPropagation(); Board.requestChanges('${item.id}')" title="Request changes">↩</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelReview('${item.id}')" title="Cancel review">✕</button>`;
        } else if (col === 'questions') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦 Archive</button>`;
        } else if (col === 'done') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.rerunItem('${item.id}')" title="Re-run">↻</button>`
                + `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦 Archive</button>`;
        } else if (col === 'archive') {
            actionsHtml = deleteBtn;
        }

        let logCountHtml = '';
        if (col === 'doing' && item.log_count > 0) {
            logCountHtml = `<div class="card-log-count" data-log-count="${item.id}">${item.log_count}</div>`;
        }

        let timestampHtml = '';
        if (col === 'done' && (item.done_at || item.updated_at)) {
            const d = new Date((item.done_at || item.updated_at) + 'Z');
            const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            timestampHtml = `<span class="card-timestamp">${timeStr}</span>`;
        }

        div.innerHTML = `
            ${epicBadgeHtml}
            <div class="card-title">${this.escapeHtml(item.title)}</div>
            ${blockedHtml}
            ${statusHtml}
            <div class="card-bottom">
                <div class="card-actions">${actionsHtml}</div>
                ${timestampHtml}
                ${logCountHtml}
            </div>
        `;
        return div;
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

    _isEpicFullyArchived(epic) {
        const p = epic.progress || {};
        const archived = (p.archive || 0);
        // Epic has items and all are archived (total excludes archive, so check it's 0)
        return archived > 0 && (p.total || 0) === 0;
    },

    _renderEpicPanel() {
        const toggle = document.querySelector('.epic-panel-toggle');
        const panel = document.getElementById('epic-panel');
        if (!toggle || !panel) return;

        if (this._epicPanelExpanded) {
            toggle.classList.add('expanded');
            panel.classList.add('visible');
        } else {
            toggle.classList.remove('expanded');
            panel.classList.remove('visible');
            return;
        }

        let html = '';
        for (const epic of this._epics) {
            if (this._isEpicFullyArchived(epic)) continue;
            const p = epic.progress || {};
            const done = (p.done || 0);
            const total = (p.total || 0);
            const pct = total > 0 ? Math.round((done / total) * 100) : 0;
            const isActive = this._epicFilter === epic.id;
            html += `
                <div class="epic-card${isActive ? ' active' : ''}" onclick="Board.filterByEpic('${epic.id}')">
                    <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                    <span class="epic-card-title">${Board.escapeHtml(epic.title)}</span>
                    <div class="epic-progress-bar">
                        <div class="epic-progress-fill" style="width: ${pct}%; background: var(--epic-${epic.color})"></div>
                    </div>
                    <span class="epic-progress-count">${done}/${total}</span>
                </div>
            `;
        }

        if (this._epicFilter) {
            html += `<button class="epic-filter-clear" onclick="Board.clearEpicFilter()">Clear filter</button>`;
        }

        panel.innerHTML = html;
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

    _applyEpicFilter() {
        // Show/hide cards based on epic filter in non-grouped columns
        document.querySelectorAll('.column-cards').forEach(col => {
            const colName = col.dataset.column;
            // Skip columns that use custom rendering
            if (colName === 'todo' || colName === 'done' || colName === 'archive') return;
            col.querySelectorAll('.card').forEach(card => {
                const itemId = card.dataset.id;
                const item = this.items[itemId];
                if (!this._epicFilter || (item && item.epic_id === this._epicFilter)) {
                    card.style.display = '';
                } else {
                    card.style.display = 'none';
                }
            });
        });
        // Re-render columns that use grouped rendering
        this.renderTodoColumn();
        this.renderDoneColumn();
        this.renderArchiveColumn();
        this.updateCounts();
    },

    renderTodoColumn() {
        const col = document.querySelector('.column-cards[data-column="todo"]');
        if (!col) return;

        const todoItems = Object.values(this.items).filter(i => i.column_name === 'todo');

        // Apply epic filter
        const filtered = this._epicFilter
            ? todoItems.filter(i => i.epic_id === this._epicFilter)
            : todoItems;

        // If filtered to one epic or no epics exist, render flat
        if (this._epicFilter || this._epics.length === 0) {
            col.innerHTML = '';
            filtered.sort((a, b) => (a.position || 0) - (b.position || 0));
            for (const item of filtered) {
                col.appendChild(this.renderCard(item));
            }
            return;
        }

        // Group by epic
        const epicGroups = {};
        const noEpic = [];
        for (const item of filtered) {
            if (item.epic_id) {
                if (!epicGroups[item.epic_id]) epicGroups[item.epic_id] = [];
                epicGroups[item.epic_id].push(item);
            } else {
                noEpic.push(item);
            }
        }

        col.innerHTML = '';

        // Render epic groups in epic position order
        for (const epic of this._epics) {
            const items = epicGroups[epic.id];
            if (!items || items.length === 0) continue;

            const isCollapsed = this._collapsedTodoEpicGroups[epic.id] || false;

            const group = document.createElement('div');
            group.className = 'todo-epic-group';

            const header = document.createElement('div');
            header.className = 'todo-epic-header' + (isCollapsed ? '' : ' expanded');
            header.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="epic-dot" style="background: var(--epic-${epic.color})"></span>
                ${Board.escapeHtml(epic.title)}
                <button class="todo-epic-delete" title="Delete all todos in this epic">&times;</button>
                <span class="todo-epic-count">${items.length}</span>
            `;
            header.addEventListener('click', (e) => {
                if (e.target.closest('.todo-epic-delete')) return;
                this._collapsedTodoEpicGroups[epic.id] = !isCollapsed;
                this.renderTodoColumn();
            });
            header.querySelector('.todo-epic-delete').addEventListener('click', (e) => {
                e.stopPropagation();
                Board.deleteEpicTodos(epic.id, epic.title);
            });
            group.appendChild(header);

            if (!isCollapsed) {
                items.sort((a, b) => (a.position || 0) - (b.position || 0));
                for (const item of items) {
                    group.appendChild(this.renderCard(item));
                }
            }

            col.appendChild(group);
        }

        // "No Epic" group at the bottom
        if (noEpic.length > 0) {
            const group = document.createElement('div');
            group.className = 'todo-epic-group';
            const isCollapsed = this._collapsedTodoEpicGroups['__none__'] || false;
            const header = document.createElement('div');
            header.className = 'todo-epic-header' + (isCollapsed ? '' : ' expanded');
            header.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                No Epic
                <span class="todo-epic-count" style="margin-left: auto">${noEpic.length}</span>
            `;
            header.addEventListener('click', () => {
                this._collapsedTodoEpicGroups['__none__'] = !isCollapsed;
                this.renderTodoColumn();
            });
            group.appendChild(header);

            if (!isCollapsed) {
                noEpic.sort((a, b) => (a.position || 0) - (b.position || 0));
                for (const item of noEpic) {
                    group.appendChild(this.renderCard(item));
                }
            }
            col.appendChild(group);
        }
    },

    renderDoneColumn() {
        const col = document.querySelector('.column-cards[data-column="done"]');
        if (!col) return;

        // Collect done items
        let doneItems = Object.values(this.items).filter(i => i.column_name === 'done');
        if (this._epicFilter) doneItems = doneItems.filter(i => i.epic_id === this._epicFilter);

        // Group by date
        const groups = {};
        for (const item of doneItems) {
            const key = this._getDoneDateKey(item);
            if (!groups[key]) groups[key] = [];
            groups[key].push(item);
        }

        // Sort date keys descending (most recent first)
        const sortedDates = Object.keys(groups).sort((a, b) => {
            if (a === 'Unknown') return 1;
            if (b === 'Unknown') return -1;
            return b.localeCompare(a);
        });

        // Clear column
        col.innerHTML = '';

        for (const dateStr of sortedDates) {
            const items = groups[dateStr];
            const isToday = this._isTodayGroup(dateStr);
            const isCollapsed = dateStr in this._collapsedDoneGroups
                ? this._collapsedDoneGroups[dateStr]
                : !isToday; // default: today expanded, others collapsed

            // Create group container
            const group = document.createElement('div');
            group.className = 'done-day-group' + (isCollapsed ? ' collapsed' : '');
            group.dataset.date = dateStr;

            // Group header
            const header = document.createElement('div');
            header.className = 'done-day-header';
            header.innerHTML = `
                <svg class="done-day-chevron${isCollapsed ? '' : ' expanded'}" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="done-day-label">${this._formatDateLabel(dateStr)}</span>
                <span class="done-day-count">${items.length}</span>
                <button class="btn btn-xs done-day-archive" onclick="event.stopPropagation(); Board.archiveByDate('${dateStr}')" title="Archive all from ${this._formatDateLabel(dateStr)}">📦</button>
            `;
            header.addEventListener('click', () => {
                this._collapsedDoneGroups[dateStr] = !isCollapsed;
                this.renderDoneColumn();
            });

            group.appendChild(header);

            // Sort items within group by done_at descending (fallback to updated_at)
            items.sort((a, b) => (b.done_at || b.updated_at || '').localeCompare(a.done_at || a.updated_at || ''));

            if (!isCollapsed) {
                // Full card rendering when expanded
                const cardsContainer = document.createElement('div');
                cardsContainer.className = 'done-day-cards';
                for (const item of items) {
                    cardsContainer.appendChild(this.renderCard(item));
                }
                group.appendChild(cardsContainer);
            }

            col.appendChild(group);
        }
    },

    renderArchiveColumn() {
        const col = document.querySelector('.column-cards[data-column="archive"]');
        if (!col) return;

        let archiveItems = Object.values(this.items).filter(i => i.column_name === 'archive');
        if (this._epicFilter) archiveItems = archiveItems.filter(i => i.epic_id === this._epicFilter);

        const groups = {};
        for (const item of archiveItems) {
            const key = this._getDoneDateKey(item);
            if (!groups[key]) groups[key] = [];
            groups[key].push(item);
        }

        const sortedDates = Object.keys(groups).sort((a, b) => {
            if (a === 'Unknown') return 1;
            if (b === 'Unknown') return -1;
            return b.localeCompare(a);
        });

        col.innerHTML = '';

        for (const dateStr of sortedDates) {
            const items = groups[dateStr];
            const isCollapsed = dateStr in this._collapsedArchiveGroups
                ? this._collapsedArchiveGroups[dateStr]
                : true; // default: all collapsed

            const group = document.createElement('div');
            group.className = 'done-day-group' + (isCollapsed ? ' collapsed' : '');
            group.dataset.date = dateStr;

            const header = document.createElement('div');
            header.className = 'done-day-header';
            header.innerHTML = `
                <svg class="done-day-chevron${isCollapsed ? '' : ' expanded'}" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 4 10 8 6 12"/></svg>
                <span class="done-day-label">${this._formatDateLabel(dateStr)}</span>
                <span class="done-day-count">${items.length}</span>
                <button class="btn btn-xs btn-delete done-day-archive" onclick="event.stopPropagation(); Board.deleteByDate('${dateStr}', 'archive')" title="Delete all from ${this._formatDateLabel(dateStr)}">✕</button>
            `;
            header.addEventListener('click', () => {
                this._collapsedArchiveGroups[dateStr] = !isCollapsed;
                this.renderArchiveColumn();
            });

            group.appendChild(header);

            items.sort((a, b) => (b.done_at || b.updated_at || '').localeCompare(a.done_at || a.updated_at || ''));

            if (!isCollapsed) {
                const cardsContainer = document.createElement('div');
                cardsContainer.className = 'done-day-cards';
                for (const item of items) {
                    cardsContainer.appendChild(this.renderCard(item));
                }
                group.appendChild(cardsContainer);
            }

            col.appendChild(group);
        }
    },

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    },

    updateCard(item) {
        // Merge with previous state to preserve fields not in the update
        const prev = this.items[item.id];
        if (prev) {
            // Preserve log_count from previous state if not in new data
            if (prev.log_count && !item.log_count) {
                item.log_count = prev.log_count;
            }
            // Preserve start_copy from previous state if not in new data
            if (prev.start_copy && item.start_copy === undefined) {
                item.start_copy = prev.start_copy;
            }
        }
        this.items[item.id] = item;

        // Remove old card if exists
        const oldCard = document.querySelector(`.card[data-id="${item.id}"]`);
        if (oldCard) oldCard.remove();

        // Done and archive columns use grouped rendering
        if (item.column_name === 'done' || item.column_name === 'archive') {
            if (prev && prev.column_name === 'done' && item.column_name !== 'done') {
                this.renderDoneColumn();
            }
            if (prev && prev.column_name === 'archive' && item.column_name !== 'archive') {
                this.renderArchiveColumn();
            }
            if (prev && prev.column_name === 'todo' && item.column_name !== 'todo') {
                this.renderTodoColumn();
            }
            if (item.column_name === 'done') this.renderDoneColumn();
            if (item.column_name === 'archive') this.renderArchiveColumn();
            this.updateCounts();
            return;
        }

        // Todo column uses grouped rendering
        if (item.column_name === 'todo') {
            if (prev && prev.column_name === 'done') this.renderDoneColumn();
            if (prev && prev.column_name === 'archive') this.renderArchiveColumn();
            this.renderTodoColumn();
            this.updateCounts();
            return;
        }

        // If item was previously in todo, re-render that column
        if (prev && prev.column_name === 'todo' && item.column_name !== 'todo') {
            this.renderTodoColumn();
        }

        // If item was previously in done/archive, re-render that column to remove it
        if (prev && prev.column_name === 'done' && item.column_name !== 'done') {
            this.renderDoneColumn();
        }
        if (prev && prev.column_name === 'archive' && item.column_name !== 'archive') {
            this.renderArchiveColumn();
        }

        // Add new card to correct column
        const targetCol = document.querySelector(`.column-cards[data-column="${item.column_name}"]`);
        if (targetCol) {
            const newCard = this.renderCard(item);
            // Insert at correct position
            const cards = targetCol.querySelectorAll('.card');
            if (item.position < cards.length) {
                targetCol.insertBefore(newCard, cards[item.position]);
            } else {
                targetCol.appendChild(newCard);
            }
        }

        this.updateCounts();
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
