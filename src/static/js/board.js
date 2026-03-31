const Board = {
    // Client-side items cache
    items: {},

    // Track collapsed state of done day groups (date string -> boolean)
    _collapsedDoneGroups: {},

    init(initialItems) {
        for (const item of initialItems) {
            this.items[item.id] = item;
        }
        this.renderDoneColumn();
        this.updateCounts();
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
        if (!await Dialogs.confirm(`Archive all items from ${dateStr}?`)) return;
        try {
            await Api.archiveByDate(dateStr);
        } catch (err) {
            console.error('Failed to archive items:', err);
        }
    },

    async startAgent(itemId) {
        try {
            await Api.startAgent(itemId);
        } catch (err) {
            console.error('Failed to start agent:', err);
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
        const items = await Api.getItems();
        this.items = {};
        // Clear all column cards
        document.querySelectorAll('.column-cards').forEach(col => {
            col.innerHTML = '';
        });
        for (const item of items) {
            this.items[item.id] = item;
            if (item.column_name !== 'done') {
                const targetCol = document.querySelector(`.column-cards[data-column="${item.column_name}"]`);
                if (targetCol) {
                    targetCol.appendChild(this.renderCard(item));
                }
            }
        }
        this.renderDoneColumn();
        this.updateCounts();
    },

    renderCard(item) {
        const div = document.createElement('div');
        div.className = 'card';
        div.dataset.id = item.id;
        div.draggable = true;
        div.ondragstart = (e) => Board.handleDragStart(e);
        div.onclick = () => Dialogs.showDetail(item.id);

        let statusHtml = '';
        if (item.status) {
            const labels = {
                running: '<span class="spinner"></span> Running',
                paused: '⏸ Paused',
                failed: '✕ Failed',
                cancelled: '⊘ Cancelled',
                conflict: '⚠ Merge conflict',
                resolving_conflicts: '<span class="spinner"></span> Resolving conflicts',
            };
            statusHtml = `<div class="card-status card-status-${item.status}">${labels[item.status] || item.status}</div>`;
        }

        let actionsHtml = '';
        const col = item.column_name;
        const deleteBtn = `<button class="btn btn-xs btn-delete" onclick="event.stopPropagation(); Board.deleteItem('${item.id}')" title="Delete">✕</button>`;
        if (col === 'todo') {
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.startAgent('${item.id}')">▶</button>${deleteBtn}`;
        } else if (col === 'doing' && item.status === 'failed') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.retryAgent('${item.id}')" title="Retry">↻ Retry</button>
                <button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'todo')" title="Move to 📝 Todo">→ 📝 Todo</button>`;
        } else if (col === 'doing' && item.status === 'running') {
            actionsHtml = `<button class="btn btn-xs btn-warning" onclick="event.stopPropagation(); Board.pauseAgent('${item.id}')" title="Pause">⏸</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')">✕</button>`;
        } else if (col === 'doing' && item.status === 'paused') {
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.resumeAgent('${item.id}')" title="Resume">▶</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')">✕</button>`;
        } else if (col === 'review') {
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.approveItem('${item.id}')">✓ Approve</button>
                <button class="btn btn-xs" onclick="event.stopPropagation(); Board.requestChanges('${item.id}')">↩</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelReview('${item.id}')">✕</button>`;
        } else if (col === 'done') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.rerunItem('${item.id}')" title="Re-run">↻</button>`
                + `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦</button>`;
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
            <div class="card-title">${this.escapeHtml(item.title)}</div>
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

    renderDoneColumn() {
        const col = document.querySelector('.column-cards[data-column="done"]');
        if (!col) return;

        // Collect done items
        const doneItems = Object.values(this.items).filter(i => i.column_name === 'done');

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
            } else {
                // Compact title list when collapsed
                const titleList = document.createElement('div');
                titleList.className = 'done-day-titles';
                for (const item of items) {
                    const titleRow = document.createElement('div');
                    titleRow.className = 'done-day-title-row';
                    titleRow.textContent = item.title;
                    titleRow.onclick = (e) => { e.stopPropagation(); Dialogs.showDetail(item.id); };
                    titleList.appendChild(titleRow);
                }
                group.appendChild(titleList);
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
        // Preserve log_count from previous state if not in new data
        const prev = this.items[item.id];
        if (prev && prev.log_count && !item.log_count) {
            item.log_count = prev.log_count;
        }
        this.items[item.id] = item;

        // Remove old card if exists
        const oldCard = document.querySelector(`.card[data-id="${item.id}"]`);
        if (oldCard) oldCard.remove();

        // Done column uses grouped rendering
        if (item.column_name === 'done') {
            this.renderDoneColumn();
            this.updateCounts();
            return;
        }

        // If item was previously in done, re-render done column to remove it
        if (prev && prev.column_name === 'done' && item.column_name !== 'done') {
            this.renderDoneColumn();
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
        const wasInDone = this.items[itemId] && this.items[itemId].column_name === 'done';
        delete this.items[itemId];
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (card) card.remove();
        if (wasInDone) this.renderDoneColumn();
        this.updateCounts();
    },

    updateCounts() {
        document.querySelectorAll('.column').forEach(col => {
            const colName = col.dataset.column;
            let count;
            if (colName === 'done') {
                // Count from items cache since cards may be hidden in collapsed groups
                count = Object.values(this.items).filter(i => i.column_name === 'done').length;
            } else {
                count = col.querySelectorAll('.card').length;
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
