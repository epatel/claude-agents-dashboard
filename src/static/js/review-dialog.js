/**
 * Review file browser — embedded file browser for the review dialog
 * that highlights changed files and shows diffs inline.
 */
const ReviewFileBrowser = {
    ...FileTreeBase,
    _tree: {
        treeId: 'rfb-tree', tabsId: 'rfb-tabs', crumbId: 'rfb-breadcrumb',
        itemClass: 'rfb-tree-item', childrenClass: 'rfb-tree-children',
        tabClass: 'rfb-tab', tabNameClass: 'rfb-tab-name', tabCloseClass: 'rfb-tab-close',
        childLoadingHtml: '<div style="padding:4px 8px;font-size:12px;color:var(--text-muted);">Loading…</div>',
    },
    _itemId: null,
    _treeData: null,
    _changedFiles: {},   // { path: { status, status_label, diff_lines } }
    _diffText: '',
    _openTabs: [],       // [{path, name, status, content, language, binary, mimeType, hidden}]
    _activeTab: -1,
    _expandedDirs: new Set(),
    _maxTabs: 10,

    async load(itemId, diffData) {
        this._itemId = itemId;
        this._openTabs = [];
        this._activeTab = -1;
        this._expandedDirs = new Set();
        this._treeData = null;
        this._diffText = diffData?.diff || '';
        this._changedFiles = this._indexChangedFiles(diffData?.files || [], this._diffText);

        // Wire up filter
        const filterInput = document.getElementById('rfb-filter');
        if (filterInput) {
            filterInput.value = '';
            filterInput.oninput = (e) => this._filterTree(e.target.value);
        }

        // Load tree
        await this._loadTree('');

        // Render empty viewer
        this._renderTabs();
        this._renderContent();
        this._renderBreadcrumb();
    },

    /** ``{ path: { status, status_label, diff_lines } }`` for the changed files, with their diff chunks. */
    _indexChangedFiles(files, diffText) {
        const changed = {};
        for (const f of files) {
            changed[f.path] = { status: f.status, status_label: f.status_label || f.status };
        }
        // Parse diff into per-file chunks
        const parsed = diffText ? DiffViewer.parseDiff(diffText) : [];
        for (const pf of parsed) {
            if (changed[pf.path]) changed[pf.path].diff_lines = pf.lines;
        }
        return changed;
    },

    async _loadTree(path) {
        const treeEl = document.getElementById('rfb-tree');
        treeEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:12px;">Loading…</div>';
        try {
            const data = await Api.request('GET', this._treeUrl(path));
            if (!path) this._treeData = data.tree;
            this._renderTreeNodes(treeEl, data.tree, 0);

            // Auto-expand directories containing changed files
            if (!path) await this._autoExpandChanged();
        } catch {
            treeEl.innerHTML = '<div style="padding:12px;color:var(--danger);font-size:12px;">Failed to load files</div>';
        }
    },

    _treeUrl(path) {
        const base = `/api/items/${this._itemId}/worktree/tree`;
        return path ? `${base}?path=${encodeURIComponent(path)}` : base;
    },

    _dirExtraHtml(node) {
        // Dot on directories that contain changed files
        const hasChanges = Object.keys(this._changedFiles).some(p => p.startsWith(node.path + '/'));
        return hasChanges ? '<span class="rfb-status-dot status-M" title="Contains changes"></span>' : '';
    },

    _decorateFileNode(item, node) {
        const change = this._changedFiles[node.path];
        if (!change) return '';
        item.classList.add('rfb-changed-file');
        return `<span class="rfb-status-dot status-${change.status}" title="${change.status_label}"></span>`;
    },

    _tabExtraHtml(tab) {
        const statusColor = { A: 'var(--success)', D: 'var(--danger)', M: 'var(--accent)' }[tab.status] || '';
        return statusColor ? `<span class="rfb-tab-status" style="background:${statusColor}"></span>` : '';
    },

    async _autoExpandChanged() {
        // Collect parent dirs of all changed files and expand them
        const dirsToExpand = this._changedFileDirs();
        if (dirsToExpand.size === 0) return;
        for (const d of dirsToExpand) this._expandedDirs.add(d);
        if (!this._treeData) return;
        // Fetch the children of expanded dirs the tree has not loaded yet,
        // or they would render expanded but empty
        await this._loadExpandedChildren(this._treeData);
        // Re-render tree with expansions
        const treeEl = document.getElementById('rfb-tree');
        this._renderTreeNodes(treeEl, this._treeData, 0);
    },

    /** Load (in place) the missing children of every expanded dir under ``nodes``. */
    async _loadExpandedChildren(nodes) {
        const expanded = nodes.filter(n => n.type === 'dir' && this._expandedDirs.has(n.path));
        await Promise.all(expanded.map(async (node) => {
            if (node.children === null) {
                try {
                    node.children = (await Api.request('GET', this._treeUrl(node.path))).tree;
                } catch {
                    return; // left unloaded; a click on the dir retries
                }
            }
            await this._loadExpandedChildren(node.children || []);
        }));
    },

    _changedFileDirs() {
        const dirs = new Set();
        for (const filePath of Object.keys(this._changedFiles)) {
            const parts = filePath.split('/');
            for (let i = 1; i < parts.length; i++) {
                dirs.add(parts.slice(0, i).join('/'));
            }
        }
        return dirs;
    },

    async _openFile(path, name) {
        const existingIdx = this._openTabs.findIndex(t => t.path === path);
        if (existingIdx >= 0) {
            this._switchTab(existingIdx);
            return;
        }

        const change = this._changedFiles[path];

        // For deleted files, show placeholder with diff
        if (change && change.status === 'D') {
            this._pushTab({
                path, name,
                status: 'D',
                content: null,
                diff_lines: change.diff_lines || [],
                language: null, binary: false, hidden: false,
            });
            return;
        }

        // Fetch content from worktree
        const contentEl = document.getElementById('rfb-content');
        contentEl.innerHTML = '<div style="padding:20px;color:var(--text-muted);">Loading…</div>';

        try {
            const data = await Api.request('GET', `/api/items/${this._itemId}/worktree/content?path=${encodeURIComponent(path)}`);
            this._pushTab(this._contentTab(path, name, change, data));
        } catch {
            contentEl.innerHTML = '<div style="padding:20px;color:var(--danger);">Failed to load file</div>';
        }
    },

    _contentTab(path, name, change, data) {
        return {
            path, name: name,
            status: change ? change.status : null,
            content: data.content,
            diff_lines: change?.diff_lines || null,
            language: data.language,
            binary: data.binary,
            mimeType: data.mime_type || null,
            hidden: data.hidden || false,
            truncated: data.truncated || false,
            size: data.size,
            lines: data.lines,
        };
    },

    /** Open ``tab`` as the active tab, closing the oldest when at the limit. */
    _pushTab(tab) {
        if (this._openTabs.length >= this._maxTabs) this._closeTab(0);
        this._openTabs.push(tab);
        this._switchTab(this._openTabs.length - 1);
    },

    _renderContent() {
        const contentEl = document.getElementById('rfb-content');

        if (this._activeTab < 0) {
            contentEl.innerHTML = `
                <div class="file-empty-state">
                    <div class="file-empty-icon">📂</div>
                    <p>Select a file from the tree to view it</p>
                </div>`;
            return;
        }

        const tab = this._openTabs[this._activeTab];
        const placeholder = this._placeholderHtml(tab);
        if (placeholder !== null) {
            contentEl.innerHTML = placeholder;
        } else if (tab.status === 'D' || this._hasDiff(tab)) {
            // Deleted file: its diff. Changed file: diff by default, with toggle to see full file.
            if (tab.status === 'D') this._renderDiff(contentEl, tab.diff_lines);
            else this._renderChangedFile(contentEl, tab);
        } else {
            // Normal code/text
            this._renderCode(contentEl, tab);
        }
    },

    /** Fixed HTML for tabs with nothing to render (deleted without diff, hidden, image, binary), else null. */
    _placeholderHtml(tab) {
        if (tab.status === 'D') {
            return this._hasLines(tab.diff_lines) ? null : `
                    <div class="rfb-deleted-placeholder">
                        <div class="rfb-deleted-icon">🗑️</div>
                        <p>This file was deleted</p>
                    </div>`;
        }
        if (tab.hidden) {
            return `<div class="file-empty-state"><div class="file-empty-icon">🔒</div><p>Hidden for security</p></div>`;
        }
        if (this._isImage(tab)) {
            return `<div style="padding:20px;text-align:center;"><img src="${tab.content}" alt="${this._escapeHtml(tab.name)}" style="max-width:100%;max-height:50vh;"></div>`;
        }
        if (tab.binary) {
            return `<div class="file-empty-state"><div class="file-empty-icon">📦</div><p>Binary file</p></div>`;
        }
        return null;
    },

    _hasLines(lines) {
        return !!lines && lines.length > 0;
    },

    _hasDiff(tab) {
        return !!tab.status && this._hasLines(tab.diff_lines);
    },

    _isImage(tab) {
        if (!tab.binary || !tab.content) return false;
        return !!tab.mimeType?.startsWith('image/');
    },

    _renderChangedFile(container, tab) {
        container.innerHTML = '';

        // Make container a flex column so viewArea gets a definite height
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.overflow = 'hidden';

        const toggleDiv = document.createElement('div');
        toggleDiv.className = 'rfb-view-toggle';

        const diffBtn = document.createElement('button');
        diffBtn.textContent = 'Diff';

        const inlineBtn = document.createElement('button');
        inlineBtn.textContent = 'Full File';
        inlineBtn.className = 'active';

        toggleDiv.appendChild(diffBtn);
        toggleDiv.appendChild(inlineBtn);
        container.appendChild(toggleDiv);

        const viewArea = document.createElement('div');
        viewArea.style.flex = '1';
        viewArea.style.minHeight = '0';  // allow flex shrinking below content size
        viewArea.style.overflow = 'hidden';
        container.appendChild(viewArea);

        this._renderInlineDiff(viewArea, tab);

        diffBtn.addEventListener('click', () => {
            diffBtn.classList.add('active');
            inlineBtn.classList.remove('active');
            this._renderDiff(viewArea, tab.diff_lines);
        });

        inlineBtn.addEventListener('click', () => {
            inlineBtn.classList.add('active');
            diffBtn.classList.remove('active');
            this._renderInlineDiff(viewArea, tab);
        });
    },

    _renderDiff(container, lines) {
        // Diff view scrolls naturally — no minimap
        container.style.overflow = 'auto';

        const wrapper = document.createElement('div');
        wrapper.className = 'rfb-inline-diff';
        for (const line of lines) wrapper.appendChild(DiffViewer.renderLine(line));
        container.innerHTML = '';
        container.appendChild(wrapper);
    },

    /**
     * Parse unified diff lines into structured hunks with line numbers.
     * Returns array of { oldStart, oldCount, newStart, newCount, lines: [{type, oldLine, newLine, text}] }
     */
    _parseDiffHunks(diffLines) {
        const hunks = [];
        let currentHunk = null;
        const pos = { oldLine: 0, newLine: 0 };

        for (const line of diffLines) {
            const header = this._parseHunkHeader(line);
            if (header) {
                currentHunk = header;
                pos.oldLine = header.oldStart;
                pos.newLine = header.newStart;
                hunks.push(header);
                continue;
            }
            // Skip lines before the first hunk and diff meta lines
            if (!currentHunk || this._isDiffMeta(line)) continue;
            currentHunk.lines.push(this._hunkLine(line, pos));
        }
        return hunks;
    },

    /** A new hunk for an ``@@ -a,b +c,d @@`` header line, else null (counts default to 1). */
    _parseHunkHeader(line) {
        const m = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
        if (!m) return null;
        const count = (s) => s !== undefined ? parseInt(s, 10) : 1;
        return {
            oldStart: parseInt(m[1], 10),
            oldCount: count(m[2]),
            newStart: parseInt(m[3], 10),
            newCount: count(m[4]),
            header: line,
            lines: [],
        };
    },

    _isDiffMeta(line) {
        return ['---', '+++', '\\'].some(prefix => line.startsWith(prefix));
    },

    /** One hunk line, numbered from ``pos`` (advanced past it). */
    _hunkLine(line, pos) {
        if (line.startsWith('+')) {
            return { type: 'add', oldLine: null, newLine: pos.newLine++, text: line.slice(1) };
        }
        if (line.startsWith('-')) {
            return { type: 'del', oldLine: pos.oldLine++, newLine: null, text: line.slice(1) };
        }
        // Context line (starts with space or is empty)
        const text = line.length > 0 ? line.slice(1) : '';
        return { type: 'context', oldLine: pos.oldLine++, newLine: pos.newLine++, text };
    },

    /**
     * Render GitHub-style inline diff: full file content with changes highlighted,
     * dual line number gutters (old/new), and a scrollbar minimap of the changes.
     */
    _renderInlineDiff(container, tab) {
        // Full file view — wrapper inside outer handles scrolling, minimap overlays
        container.style.overflow = 'hidden';

        const hunks = this._parseDiffHunks(tab.diff_lines || []);
        const fileLines = (tab.content || '').split('\n');
        // Remove trailing empty line from split if file ends with newline
        if (fileLines.length > 0 && fileLines[fileLines.length - 1] === '') {
            fileLines.pop();
        }
        const { addedLines, deletedByInsertPoint } = this._indexHunkChanges(hunks);
        const oldLineForNew = this._buildOldLineMap(hunks, fileLines.length);

        const table = document.createElement('table');
        table.className = 'inline-diff-table';
        // Deleted lines are shown just before the new line they precede
        const appendDeleted = (newLineNum) => {
            for (const dl of deletedByInsertPoint.get(newLineNum) || []) {
                table.appendChild(this._createDiffRow(dl.oldLine, null, 'del', dl.text));
            }
        };
        fileLines.forEach((lineText, i) => {
            const newLineNum = i + 1;
            appendDeleted(newLineNum);
            const isAdded = addedLines.has(newLineNum);
            table.appendChild(this._createDiffRow(
                isAdded ? null : oldLineForNew.get(newLineNum), newLineNum,
                isAdded ? 'add' : 'context', lineText,
            ));
        });
        appendDeleted(fileLines.length + 1);  // deletions at the very end of the file

        const wrapper = document.createElement('div');
        wrapper.className = 'rfb-inline-diff-full';
        wrapper.appendChild(table);

        // Wrap in outer container for minimap overlay
        const outer = document.createElement('div');
        outer.className = 'inline-diff-outer';
        outer.appendChild(wrapper);
        if (table.rows.length > 0) {
            outer.appendChild(this._buildDiffMinimap(table, wrapper));
        }

        container.innerHTML = '';
        container.appendChild(outer);
    },

    /**
     * Index a file's hunks: added lines by new line number, and deleted lines
     * grouped by the new line number they appear before.
     */
    _indexHunkChanges(hunks) {
        const addedLines = new Map();            // newLineNum -> hunk line
        const deletedByInsertPoint = new Map();  // newLineNum -> [deleted hunk lines]
        for (const hunk of hunks) {
            for (const hl of hunk.lines) {
                if (hl.type === 'add') {
                    addedLines.set(hl.newLine, hl);
                } else if (hl.type === 'del') {
                    const key = this._findInsertPoint(hunk, hl);
                    deletedByInsertPoint.set(key, [...(deletedByInsertPoint.get(key) || []), hl]);
                }
            }
        }
        return { addedLines, deletedByInsertPoint };
    },

    /** Scrollbar minimap: change bands, click-to-scroll and a draggable viewport. */
    _buildDiffMinimap(table, wrapper) {
        const minimap = document.createElement('div');
        minimap.className = 'inline-diff-minimap';
        const totalRows = table.rows.length;
        for (const run of this._changeRuns(table)) {
            const marker = document.createElement('div');
            marker.className = `inline-diff-minimap-marker inline-diff-minimap-${run.type}`;
            const span = ((run.end - run.start + 1) / totalRows) * 100;
            marker.style.top = `${(run.start / totalRows) * 100}%`;
            marker.style.height = `${Math.max(span, 0.3)}%`;
            minimap.appendChild(marker);
        }

        // Click on minimap scrolls to that position in the wrapper
        minimap.addEventListener('click', (e) => {
            const rect = minimap.getBoundingClientRect();
            const fraction = (e.clientY - rect.top) / rect.height;
            wrapper.scrollTop = fraction * wrapper.scrollHeight;
        });
        this._attachMinimapViewport(minimap, wrapper);
        return minimap;
    },

    /** Runs of adjacent added / deleted rows, merged into bands: [{type, start, end}]. */
    _changeRuns(table) {
        const runs = [];
        let runStart = -1;
        let runType = null;
        const rowCount = table.rows.length;
        for (let i = 0; i < rowCount; i++) {
            const classes = table.rows[i].classList;
            const color = classes.contains('inline-diff-add') ? 'add'
                : classes.contains('inline-diff-del') ? 'del' : null;
            if (color === runType && runStart >= 0) continue;  // the run continues
            if (runType) runs.push({ type: runType, start: runStart, end: i - 1 });
            runStart = color ? i : -1;
            runType = color;
        }
        if (runType) runs.push({ type: runType, start: runStart, end: rowCount - 1 });
        return runs;
    },

    /** Viewport indicator on the minimap that tracks scrolling and can be dragged. */
    _attachMinimapViewport(minimap, wrapper) {
        const viewport = document.createElement('div');
        viewport.className = 'inline-diff-minimap-viewport';
        minimap.appendChild(viewport);

        const updateViewport = () => {
            const sh = wrapper.scrollHeight;
            const ch = wrapper.clientHeight;
            if (sh <= ch) {
                viewport.style.display = 'none';
                return;
            }
            viewport.style.display = '';
            viewport.style.top = `${(wrapper.scrollTop / sh) * 100}%`;
            viewport.style.height = `${(ch / sh) * 100}%`;
        };
        wrapper.addEventListener('scroll', updateViewport, { passive: true });
        // Initial update after render
        requestAnimationFrame(updateViewport);

        // Drag viewport handle to scroll (replaces native scrollbar)
        let dragStartY = 0;
        let dragStartScrollTop = 0;
        const onDragMove = (e) => {
            e.preventDefault();
            const deltaY = e.clientY - dragStartY;
            const minimapRange = minimap.getBoundingClientRect().height;
            wrapper.scrollTop = dragStartScrollTop + (deltaY / minimapRange) * wrapper.scrollHeight;
        };
        const onDragEnd = () => {
            viewport.classList.remove('dragging');
            document.removeEventListener('mousemove', onDragMove);
            document.removeEventListener('mouseup', onDragEnd);
        };
        viewport.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            viewport.classList.add('dragging');
            dragStartY = e.clientY;
            dragStartScrollTop = wrapper.scrollTop;
            document.addEventListener('mousemove', onDragMove);
            document.addEventListener('mouseup', onDragEnd);
        });
    },

    /** Find the new line number before which a deleted line should appear */
    _findInsertPoint(hunk, deletedLine) {
        let insertPoint = hunk.newStart;
        for (const hl of hunk.lines) {
            if (hl === deletedLine) break;
            if (hl.type === 'add' || hl.type === 'context') {
                insertPoint = (hl.newLine || insertPoint) + 1;
            }
        }
        return insertPoint;
    },

    /** Build a map of newLineNum -> oldLineNum for context lines */
    _buildOldLineMap(hunks, totalNewLines) {
        const map = new Map();
        let oldLine = 1;
        let newLine = 1;
        let hunkIdx = 0;

        while (newLine <= totalNewLines) {
            const hunk = hunks[hunkIdx];
            if (hunk && newLine === hunk.newStart) {
                this._mapHunkContext(map, hunk);
                // Advance past the hunk
                oldLine = hunk.oldStart + hunk.oldCount;
                newLine = hunk.newStart + hunk.newCount;
                hunkIdx++;
            } else {
                map.set(newLine, oldLine);
                oldLine++;
                newLine++;
            }
        }
        return map;
    },

    /** Context lines keep their numbers; added / deleted lines have no pair. */
    _mapHunkContext(map, hunk) {
        for (const hl of hunk.lines) {
            if (hl.type === 'context') map.set(hl.newLine, hl.oldLine);
        }
    },

    _createDiffRow(oldNum, newNum, type, text) {
        const row = document.createElement('tr');
        row.className = `inline-diff-row inline-diff-${type}`;

        const oldGutter = document.createElement('td');
        oldGutter.className = 'inline-diff-gutter inline-diff-gutter-old';
        oldGutter.textContent = oldNum != null ? oldNum : '';

        const newGutter = document.createElement('td');
        newGutter.className = 'inline-diff-gutter inline-diff-gutter-new';
        newGutter.textContent = newNum != null ? newNum : '';

        const marker = document.createElement('td');
        marker.className = 'inline-diff-marker';
        marker.textContent = type === 'add' ? '+' : type === 'del' ? '-' : ' ';

        const content = document.createElement('td');
        content.className = 'inline-diff-content';

        const code = document.createElement('code');
        code.textContent = text;
        content.appendChild(code);

        row.appendChild(oldGutter);
        row.appendChild(newGutter);
        row.appendChild(marker);
        row.appendChild(content);
        return row;
    },

    _renderCode(container, tab) {
        const langClass = tab.language ? `language-${tab.language}` : 'language-none';
        let html = '';
        if (tab.truncated) {
            html += '<div style="padding:4px 12px;background:var(--bg-hover);font-size:11px;color:var(--text-muted);">File truncated — showing first 1MB</div>';
        }
        html += `<pre class="file-code-viewer line-numbers" style="margin:0;border-radius:0;"><code class="${langClass}">${this._escapeHtml(tab.content || '')}</code></pre>`;
        container.innerHTML = html;
        if (typeof Prism !== 'undefined') {
            Prism.highlightAllUnder(container);
        }
    },

};


/**
 * Review dialog functionality
 */
const ReviewDialog = {
    // Unscoped selectors: switching also resets the other dialogs' tabs (as before).
    _tabs: {
        tabs: '.review-tab',
        panels: '.review-tab-content',
        panelIdPrefix: 'review-tab-',
        logTab: 'log',
        logId: 'review-log',
    },

    async showReview(itemId) {
        const item = await DialogUtils.fetchItem(itemId);
        if (!item) return;

        document.getElementById('review-title').textContent = item.title;
        document.getElementById('review-column-badge').textContent = '👀 Review';

        // Description tab
        const descEl = document.getElementById('review-description');
        descEl.innerHTML = DialogUtils.renderMarkdown(item.description || '(no description)');
        DialogUtils.runMermaid(descEl);

        // Work log tab; its last agent_message fills the Result tab
        const log = await DialogUtils.loadWorkLog(itemId, document.getElementById('review-log'));
        const lastAgentMessage = log.findLast(e => e.entry_type === 'agent_message' && e.content) || null;
        this._renderResult(lastAgentMessage);

        // Diff tab and changed-file badges; the file browser reuses the diff data
        const diffData = await this._loadDiff(itemId);
        ReviewFileBrowser.load(itemId, diffData);
        this._updateFilesTabCount(diffData);

        const hasChanges = diffData?.files?.length > 0;
        document.getElementById('review-approve-btn').textContent = hasChanges ? '✓ Approve & Merge' : '✓ Done';

        // Preselect tab: when there are no file changes and the agent left a
        // closing message, surface it on the Result tab so it isn't lost when
        // pressing Done; otherwise fall back to the Work Log tab.
        this.switchReviewTab(!hasChanges && lastAgentMessage ? 'result' : 'log');
        this._wireReviewButtons(itemId, hasChanges);

        // Track current item ID for work log filtering
        DialogCore._currentItemId = itemId;
        DialogCore.open('review-dialog');
    },

    /** Show the Result tab with the agent's final message, or hide it. */
    _renderResult(lastAgentMessage) {
        const resultEl = document.getElementById('review-result');
        const resultTabBtn = document.getElementById('review-tab-btn-result');
        if (!resultEl || !resultTabBtn) return;
        if (!lastAgentMessage) {
            resultEl.innerHTML = '';
            resultTabBtn.style.display = 'none';
            return;
        }
        resultEl.innerHTML =
            `<div class="result-meta" style="opacity:0.7;font-size:12px;margin-bottom:8px">Final agent message — ${lastAgentMessage.timestamp}</div>` +
            `<div class="result-body">${DialogUtils.renderMarkdown(lastAgentMessage.content)}</div>`;
        DialogUtils.runMermaid(resultEl);
        resultTabBtn.style.display = '';
    },

    /** Render the diff and changed-file list; returns the diff data (null if the fetch failed). */
    async _loadDiff(itemId) {
        const diffContainer = document.getElementById('review-diff');
        diffContainer.innerHTML = '<p>Loading diff...</p>';
        let diffData = null;
        try {
            diffData = await Api.request('GET', `/api/items/${itemId}/diff`);
            DiffViewer.render(diffData.diff, diffContainer);
            this._renderChangedFiles(diffData.files);
        } catch (err) {
            diffContainer.innerHTML = `<p>Error loading diff: ${err.message}</p>`;
        }
        return diffData;
    },

    /** One badge per changed file; clicking it scrolls the Diff tab to that file. */
    _renderChangedFiles(files) {
        const filesContainer = document.getElementById('review-files');
        if (!files || files.length === 0) {
            filesContainer.innerHTML = '';
            return;
        }
        filesContainer.innerHTML = '<div class="changed-files-list">' +
            files.map(f => {
                const cls = f.status === 'A' ? 'file-added' : f.status === 'D' ? 'file-deleted' : 'file-modified';
                const escapedPath = f.path.replace(/"/g, '&quot;');
                return `<button type="button" class="file-badge ${cls}" data-target-file="${escapedPath}">${f.status_label || f.status} ${f.path}</button>`;
            }).join('') + '</div>';
        filesContainer.querySelectorAll('.file-badge[data-target-file]').forEach(btn => {
            btn.addEventListener('click', () => this._scrollToDiffFile(btn.dataset.targetFile));
        });
    },

    _scrollToDiffFile(targetPath) {
        ReviewDialog.switchReviewTab('diff');
        const diffContainer = document.getElementById('review-diff');
        const diffFile = diffContainer.querySelector(`.diff-file[data-file-path="${CSS.escape(targetPath)}"]`);
        if (!diffFile) return;
        // Ensure the diff body is expanded
        const body = diffFile.querySelector('.diff-file-body');
        if (body && body.style.display === 'none') {
            body.style.display = '';
        }
        diffFile.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },

    /** Changed-file count on the Files tab button. */
    _updateFilesTabCount(diffData) {
        const filesTab = document.querySelector('.review-tab[data-tab="files"]');
        if (!filesTab || !diffData?.files?.length) return;
        const badge = filesTab.querySelector('.column-count') || document.createElement('span');
        badge.className = 'column-count';
        badge.textContent = diffData.files.length;
        if (!filesTab.querySelector('.column-count')) filesTab.appendChild(badge);
    },

    _wireReviewButtons(itemId, hasChanges) {
        document.getElementById('review-approve-btn').onclick = async () => {
            if (hasChanges) {
                await Board.approveItem(itemId);
            } else {
                await Api.moveItem(itemId, 'done', 0);
            }
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
    },

    switchReviewTab(tabName) {
        DialogUtils.showTab(tabName, this._tabs);
    },
};
