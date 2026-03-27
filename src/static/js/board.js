const Board = {
    // Client-side items cache
    items: {},

    init(initialItems) {
        for (const item of initialItems) {
            this.items[item.id] = item;
        }
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

    async startAgent(itemId) {
        try {
            await Api.startAgent(itemId);
        } catch (err) {
            console.error('Failed to start agent:', err);
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
            col.querySelectorAll('.card').forEach(card => card.remove());
        });
        for (const item of items) {
            this.updateCard(item);
        }
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
            actionsHtml = `<button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelAgent('${item.id}')">✕</button>`;
        } else if (col === 'review') {
            actionsHtml = `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); Board.approveItem('${item.id}')">✓ Approve</button>
                <button class="btn btn-xs" onclick="event.stopPropagation(); Board.requestChanges('${item.id}')">↩</button>
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); Board.cancelReview('${item.id}')">✕</button>`;
        } else if (col === 'done') {
            actionsHtml = `<button class="btn btn-xs" onclick="event.stopPropagation(); Board.moveItem('${item.id}', 'archive')" title="📦 Archive">📦 Archive</button>`;
        }

        div.innerHTML = `
            <div class="card-title">${this.escapeHtml(item.title)}</div>
            ${statusHtml}
            <div class="card-actions">${actionsHtml}</div>
        `;
        return div;
    },

    escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    },

    updateCard(item) {
        this.items[item.id] = item;

        // Remove old card if exists
        const oldCard = document.querySelector(`.card[data-id="${item.id}"]`);
        if (oldCard) oldCard.remove();

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
        delete this.items[itemId];
        const card = document.querySelector(`.card[data-id="${itemId}"]`);
        if (card) card.remove();
        this.updateCounts();
    },

    updateCounts() {
        document.querySelectorAll('.column').forEach(col => {
            const colName = col.dataset.column;
            const count = col.querySelectorAll('.card').length;
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
