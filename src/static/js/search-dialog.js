/**
 * Spotlight-style search dialog for finding items across all columns
 */
const SearchDialog = {
    _activeIndex: -1,
    _columns: ['todo', 'doing', 'questions', 'review', 'done', 'archive'],
    _enabledColumns: new Set(['todo', 'doing', 'questions', 'review', 'done', 'archive']),
    _searchTimer: null,

    _columnLabels: {
        todo: '📝 Todo',
        doing: '🚧 Doing',
        questions: '❓ Questions',
        review: '👀 Review',
        done: '✅ Done',
        archive: '📦 Archive',
    },

    _allEnabled() {
        return this._columns.every(c => this._enabledColumns.has(c));
    },

    open() {
        const dialog = document.getElementById('search-dialog');
        if (!dialog) return;
        this._renderFilters();
        this._clearResults();
        this._activeIndex = -1;
        dialog.showModal();
        const input = document.getElementById('search-input');
        input.value = '';
        input.focus();
        input.oninput = () => { this._activeIndex = -1; this._search(); };
        input.onkeydown = (e) => this._handleKey(e);
        document.getElementById('search-worklog').onchange = () => { this._activeIndex = -1; this._search(); };
        dialog.onclick = (e) => { if (e.target === dialog) this.close(); };
    },

    close() {
        const dialog = document.getElementById('search-dialog');
        if (dialog && dialog.open) dialog.close();
    },

    _handleKey(e) {
        const items = document.querySelectorAll('.search-result-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this._activeIndex = Math.min(this._activeIndex + 1, items.length - 1);
            this._updateActiveItem(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this._activeIndex = Math.max(this._activeIndex - 1, 0);
            this._updateActiveItem(items);
        } else if (e.key === 'Enter' && this._activeIndex >= 0) {
            e.preventDefault();
            items[this._activeIndex].click();
        }
    },

    _updateActiveItem(items) {
        items.forEach((el, i) => el.classList.toggle('active', i === this._activeIndex));
        if (this._activeIndex >= 0 && items[this._activeIndex]) {
            items[this._activeIndex].scrollIntoView({ block: 'nearest' });
        }
    },

    _renderFilters() {
        const container = document.getElementById('search-filters');
        container.innerHTML = '';

        const allBtn = document.createElement('button');
        allBtn.className = 'search-filter-btn' + (this._allEnabled() ? ' active' : '');
        allBtn.textContent = 'All';
        allBtn.onclick = () => {
            if (this._allEnabled()) {
                this._enabledColumns.clear();
            } else {
                this._columns.forEach(c => this._enabledColumns.add(c));
            }
            this._afterFilterChange();
        };
        container.appendChild(allBtn);

        for (const col of this._columns) {
            const btn = document.createElement('button');
            btn.className = 'search-filter-btn' + (this._enabledColumns.has(col) ? ' active' : '');
            btn.textContent = this._columnLabels[col];
            btn.onclick = () => {
                if (this._enabledColumns.has(col)) {
                    this._enabledColumns.delete(col);
                } else {
                    this._enabledColumns.add(col);
                }
                this._afterFilterChange();
            };
            container.appendChild(btn);
        }
    },

    _afterFilterChange() {
        this._renderFilters();
        this._activeIndex = -1;
        this._search();
        document.getElementById('search-input').focus();
    },

    _search() {
        const query = (document.getElementById('search-input').value || '').toLowerCase().trim();
        const includeWorklog = document.getElementById('search-worklog').checked;

        if (!query) {
            this._clearResults();
            return;
        }

        // Search items locally, then render item results immediately
        const items = this._matchingItems(query);
        this._renderResults(items, query, []);

        // If worklog search enabled, debounce the API call
        if (includeWorklog && query.length >= 2) {
            clearTimeout(this._searchTimer);
            this._searchTimer = setTimeout(() => this._searchWorklog(query, items), 200);
        }
    },

    /** Items in enabled columns whose title or description contains ``query``, in board order. */
    _matchingItems(query) {
        const items = Object.values(Board.items).filter(item => {
            if (!this._enabledColumns.has(item.column_name)) return false;
            const title = (item.title || '').toLowerCase();
            const desc = (item.description || '').toLowerCase();
            return title.includes(query) || desc.includes(query);
        });
        return items.sort((a, b) => {
            const ca = this._columns.indexOf(a.column_name);
            const cb = this._columns.indexOf(b.column_name);
            if (ca !== cb) return ca - cb;
            return (a.position || 0) - (b.position || 0);
        });
    },

    async _searchWorklog(query, items) {
        try {
            const worklogResults = await Api.searchWorklog(query);
            // Filter worklog results by enabled columns and exclude items already shown
            const itemIds = new Set(items.map(i => i.id));
            const filtered = worklogResults.filter(r =>
                this._enabledColumns.has(r.column_name) && !itemIds.has(r.item_id)
            );
            // Re-render with worklog results
            this._renderResults(items, query, filtered);
        } catch (err) {
            console.error('Worklog search failed:', err);
        }
    },

    _renderResults(items, query, worklogMatches) {
        const results = document.getElementById('search-results');
        results.innerHTML = '';

        const totalCount = items.length + worklogMatches.length;
        if (totalCount === 0) {
            results.innerHTML = '<div class="search-empty">No matching items</div>';
            return;
        }
        results.appendChild(this._textDiv('search-count', `${totalCount} result${totalCount !== 1 ? 's' : ''}`));

        // Item matches
        for (const item of items) results.appendChild(this._itemRow(item, query));

        // Worklog matches (items found only via work log)
        if (worklogMatches.length === 0) return;
        results.appendChild(this._textDiv('search-divider', 'Work log matches'));
        for (const match of worklogMatches) results.appendChild(this._worklogRow(match, query));
    },

    _itemRow(item, query) {
        return this._resultRow(item.id, item.column_name,
            this._highlight(item.title || '', query), this._getSnippet(item.description || '', query));
    },

    _worklogRow(match, query) {
        return this._resultRow(match.item_id, match.column_name,
            this._escapeHtml(match.title || ''), this._getSnippet(match.content || '', query));
    },

    _textDiv(className, text) {
        const el = document.createElement('div');
        el.className = className;
        el.textContent = text;
        return el;
    },

    /** One result row; clicking it closes the search and opens the item. */
    _resultRow(itemId, column, titleHtml, snippetHtml) {
        const colLabel = this._columnLabels[column] || column;
        const row = document.createElement('div');
        row.className = 'search-result-item';
        row.onclick = () => { this.close(); Dialogs.showDetail(itemId); };
        row.innerHTML = `
                <div class="search-result-main">
                    <div class="search-result-title">${titleHtml}</div>
                    ${snippetHtml ? `<div class="search-result-desc">${snippetHtml}</div>` : ''}
                </div>
                <span class="search-result-column">${colLabel}</span>
            `;
        return row;
    },

    _highlight(text, query) {
        if (!query) return this._escapeHtml(text);
        const escaped = this._escapeHtml(text);
        const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        return escaped.replace(regex, '<mark>$1</mark>');
    },

    _getSnippet(text, query) {
        if (!text || !query) return '';
        const lower = text.toLowerCase();
        const idx = lower.indexOf(query);
        if (idx === -1) return '';
        const start = Math.max(0, idx - 50);
        const end = Math.min(text.length, idx + query.length + 50);
        let snippet = (start > 0 ? '\u2026' : '') + text.slice(start, end) + (end < text.length ? '\u2026' : '');
        return this._highlight(snippet, query);
    },

    _clearResults() {
        document.getElementById('search-results').innerHTML = '<div class="search-empty">Type to search across all items</div>';
    },

    _escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    },
};
