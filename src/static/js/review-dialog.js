/**
 * Review file browser — embedded file browser for the review dialog
 * that highlights changed files and shows diffs inline.
 */
const ReviewFileBrowser = {
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
        this._changedFiles = {};
        this._diffText = diffData?.diff || '';

        // Index changed files
        if (diffData?.files) {
            for (const f of diffData.files) {
                this._changedFiles[f.path] = {
                    status: f.status,
                    status_label: f.status_label || f.status,
                };
            }
        }

        // Parse diff into per-file chunks
        if (this._diffText) {
            const parsed = DiffViewer.parseDiff(this._diffText);
            for (const pf of parsed) {
                if (this._changedFiles[pf.path]) {
                    this._changedFiles[pf.path].diff_lines = pf.lines;
                }
            }
        }

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

    async _loadTree(path) {
        const treeEl = document.getElementById('rfb-tree');
        treeEl.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:12px;">Loading…</div>';
        try {
            const url = path
                ? `/api/items/${this._itemId}/worktree/tree?path=${encodeURIComponent(path)}`
                : `/api/items/${this._itemId}/worktree/tree`;
            const data = await Api.request('GET', url);
            if (!path) this._treeData = data.tree;
            this._renderTreeNodes(treeEl, data.tree, 0);

            // Auto-expand directories containing changed files
            if (!path) this._autoExpandChanged();
        } catch {
            treeEl.innerHTML = '<div style="padding:12px;color:var(--danger);font-size:12px;">Failed to load files</div>';
        }
    },

    _autoExpandChanged() {
        // Collect parent dirs of all changed files and expand them
        const dirsToExpand = new Set();
        for (const filePath of Object.keys(this._changedFiles)) {
            const parts = filePath.split('/');
            for (let i = 1; i < parts.length; i++) {
                dirsToExpand.add(parts.slice(0, i).join('/'));
            }
        }
        if (dirsToExpand.size > 0) {
            for (const d of dirsToExpand) this._expandedDirs.add(d);
            // Re-render tree with expansions
            const treeEl = document.getElementById('rfb-tree');
            if (this._treeData) this._renderTreeNodes(treeEl, this._treeData, 0);
        }
    },

    _renderTreeNodes(container, nodes, indent) {
        container.innerHTML = '';
        for (const node of nodes) {
            if (node.type === 'dir') {
                this._renderDirNode(container, node, indent);
            } else {
                this._renderFileNode(container, node, indent);
            }
        }
    },

    _renderDirNode(container, node, indent) {
        const item = document.createElement('div');
        item.className = 'rfb-tree-item';
        item.style.paddingLeft = `${8 + indent * 16}px`;
        item.dataset.path = node.path;
        item.dataset.type = 'dir';

        const isExpanded = this._expandedDirs.has(node.path);

        // Check if this dir contains changed files
        const hasChanges = Object.keys(this._changedFiles).some(p => p.startsWith(node.path + '/'));

        item.innerHTML = `
            <span class="tree-arrow ${isExpanded ? 'expanded' : ''}">▶</span>
            <span class="tree-icon">📁</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
            ${hasChanges ? '<span class="rfb-status-dot status-M" title="Contains changes"></span>' : ''}
        `;
        item.addEventListener('click', () => this._toggleDir(node, item, indent));
        container.appendChild(item);

        const children = document.createElement('div');
        children.className = `rfb-tree-children ${isExpanded ? 'expanded' : ''}`;
        children.dataset.path = node.path;
        if (isExpanded && node.children) {
            this._renderTreeNodes(children, node.children, indent + 1);
        }
        container.appendChild(children);
    },

    _renderFileNode(container, node, indent) {
        const item = document.createElement('div');
        item.className = 'rfb-tree-item';
        item.style.paddingLeft = `${8 + indent * 16 + 18}px`;
        item.dataset.path = node.path;
        item.dataset.type = 'file';

        const change = this._changedFiles[node.path];
        if (change) item.classList.add('rfb-changed-file');

        // Highlight active file
        if (this._activeTab >= 0 && this._openTabs[this._activeTab]?.path === node.path) {
            item.classList.add('active');
        }

        const icon = this._getFileIcon(node.name);
        const statusDot = change
            ? `<span class="rfb-status-dot status-${change.status}" title="${change.status_label}"></span>`
            : '';

        item.innerHTML = `
            <span class="tree-icon">${icon}</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
            ${statusDot}
        `;
        item.addEventListener('click', () => this._openFile(node.path, node.name));
        container.appendChild(item);
    },

    async _toggleDir(node, itemEl, indent) {
        const isExpanded = this._expandedDirs.has(node.path);
        const childrenEl = itemEl.nextElementSibling;
        const arrowEl = itemEl.querySelector('.tree-arrow');

        if (isExpanded) {
            this._expandedDirs.delete(node.path);
            childrenEl.classList.remove('expanded');
            arrowEl.classList.remove('expanded');
        } else {
            this._expandedDirs.add(node.path);
            childrenEl.classList.add('expanded');
            arrowEl.classList.add('expanded');
            if (node.children === null) {
                childrenEl.innerHTML = '<div style="padding:4px 8px;font-size:12px;color:var(--text-muted);">Loading…</div>';
                try {
                    const data = await Api.request('GET', `/api/items/${this._itemId}/worktree/tree?path=${encodeURIComponent(node.path)}`);
                    node.children = data.tree;
                    this._renderTreeNodes(childrenEl, node.children, indent + 1);
                } catch {
                    childrenEl.innerHTML = '<div style="padding:4px 8px;font-size:12px;color:var(--danger);">Failed to load</div>';
                }
            } else {
                this._renderTreeNodes(childrenEl, node.children, indent + 1);
            }
        }
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
            const tab = {
                path, name,
                status: 'D',
                content: null,
                diff_lines: change.diff_lines || [],
                language: null, binary: false, hidden: false,
            };
            if (this._openTabs.length >= this._maxTabs) this._closeTab(0);
            this._openTabs.push(tab);
            this._switchTab(this._openTabs.length - 1);
            return;
        }

        // Fetch content from worktree
        const contentEl = document.getElementById('rfb-content');
        contentEl.innerHTML = '<div style="padding:20px;color:var(--text-muted);">Loading…</div>';

        try {
            const data = await Api.request('GET', `/api/items/${this._itemId}/worktree/content?path=${encodeURIComponent(path)}`);
            const tab = {
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
            if (this._openTabs.length >= this._maxTabs) this._closeTab(0);
            this._openTabs.push(tab);
            this._switchTab(this._openTabs.length - 1);
        } catch {
            contentEl.innerHTML = '<div style="padding:20px;color:var(--danger);">Failed to load file</div>';
        }
    },

    _switchTab(index) {
        this._activeTab = index;
        this._renderTabs();
        this._renderContent();
        this._renderBreadcrumb();
        this._updateTreeHighlight();
    },

    _closeTab(index) {
        this._openTabs.splice(index, 1);
        if (this._openTabs.length === 0) {
            this._activeTab = -1;
        } else if (this._activeTab >= this._openTabs.length) {
            this._activeTab = this._openTabs.length - 1;
        } else if (this._activeTab > index) {
            this._activeTab--;
        }
        this._renderTabs();
        this._renderContent();
        this._renderBreadcrumb();
        this._updateTreeHighlight();
    },

    _renderTabs() {
        const tabsEl = document.getElementById('rfb-tabs');
        tabsEl.innerHTML = '';
        this._openTabs.forEach((tab, i) => {
            const el = document.createElement('div');
            el.className = `rfb-tab ${i === this._activeTab ? 'active' : ''}`;

            const statusColor = tab.status === 'A' ? 'var(--success)' : tab.status === 'D' ? 'var(--danger)' : tab.status === 'M' ? 'var(--accent)' : '';
            const statusDot = statusColor ? `<span class="rfb-tab-status" style="background:${statusColor}"></span>` : '';

            el.innerHTML = `
                ${statusDot}
                <span class="rfb-tab-name" title="${this._escapeHtml(tab.path)}">${this._escapeHtml(tab.name)}</span>
                <span class="rfb-tab-close">&times;</span>
            `;
            el.querySelector('.rfb-tab-name').addEventListener('click', () => this._switchTab(i));
            el.querySelector('.rfb-tab-close').addEventListener('click', (e) => {
                e.stopPropagation();
                this._closeTab(i);
            });
            tabsEl.appendChild(el);
        });
    },

    _renderBreadcrumb() {
        const crumbEl = document.getElementById('rfb-breadcrumb');
        if (this._activeTab < 0) {
            crumbEl.classList.remove('visible');
            return;
        }
        crumbEl.classList.add('visible');
        const tab = this._openTabs[this._activeTab];
        const parts = tab.path.split('/');
        crumbEl.innerHTML = '';
        parts.forEach((part, i) => {
            if (i > 0) {
                const sep = document.createElement('span');
                sep.className = 'separator';
                sep.textContent = '/';
                crumbEl.appendChild(sep);
            }
            const span = document.createElement('span');
            span.textContent = part;
            if (i < parts.length - 1) span.className = 'crumb';
            crumbEl.appendChild(span);
        });
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

        // Deleted file
        if (tab.status === 'D') {
            if (tab.diff_lines && tab.diff_lines.length > 0) {
                this._renderDiff(contentEl, tab.diff_lines);
            } else {
                contentEl.innerHTML = `
                    <div class="rfb-deleted-placeholder">
                        <div class="rfb-deleted-icon">🗑️</div>
                        <p>This file was deleted</p>
                    </div>`;
            }
            return;
        }

        // Hidden
        if (tab.hidden) {
            contentEl.innerHTML = `<div class="file-empty-state"><div class="file-empty-icon">🔒</div><p>Hidden for security</p></div>`;
            return;
        }

        // Image
        if (tab.binary && tab.mimeType?.startsWith('image/') && tab.content) {
            contentEl.innerHTML = `<div style="padding:20px;text-align:center;"><img src="${tab.content}" alt="${this._escapeHtml(tab.name)}" style="max-width:100%;max-height:50vh;"></div>`;
            return;
        }

        // Binary
        if (tab.binary) {
            contentEl.innerHTML = `<div class="file-empty-state"><div class="file-empty-icon">📦</div><p>Binary file</p></div>`;
            return;
        }

        // Changed file — show diff by default, with toggle to see full file
        if (tab.status && tab.diff_lines && tab.diff_lines.length > 0) {
            this._renderChangedFile(contentEl, tab);
            return;
        }

        // Normal code/text
        this._renderCode(contentEl, tab);
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
        for (const line of lines) {
            const lineEl = document.createElement('div');
            lineEl.className = 'diff-line';
            if (line.startsWith('+') && !line.startsWith('+++')) {
                lineEl.classList.add('diff-add');
            } else if (line.startsWith('-') && !line.startsWith('---')) {
                lineEl.classList.add('diff-del');
            } else if (line.startsWith('@@')) {
                lineEl.classList.add('diff-hunk');
            }
            lineEl.textContent = line;
            wrapper.appendChild(lineEl);
        }
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
        let oldLine = 0;
        let newLine = 0;

        for (const line of diffLines) {
            const hunkMatch = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
            if (hunkMatch) {
                currentHunk = {
                    oldStart: parseInt(hunkMatch[1], 10),
                    oldCount: hunkMatch[2] !== undefined ? parseInt(hunkMatch[2], 10) : 1,
                    newStart: parseInt(hunkMatch[3], 10),
                    newCount: hunkMatch[4] !== undefined ? parseInt(hunkMatch[4], 10) : 1,
                    header: line,
                    lines: [],
                };
                oldLine = currentHunk.oldStart;
                newLine = currentHunk.newStart;
                hunks.push(currentHunk);
                continue;
            }

            if (!currentHunk) continue;
            // Skip diff meta lines
            if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('\\')) continue;

            if (line.startsWith('+')) {
                currentHunk.lines.push({ type: 'add', oldLine: null, newLine: newLine, text: line.slice(1) });
                newLine++;
            } else if (line.startsWith('-')) {
                currentHunk.lines.push({ type: 'del', oldLine: oldLine, newLine: null, text: line.slice(1) });
                oldLine++;
            } else {
                // Context line (starts with space or is empty)
                const text = line.length > 0 ? line.slice(1) : '';
                currentHunk.lines.push({ type: 'context', oldLine: oldLine, newLine: newLine, text });
                oldLine++;
                newLine++;
            }
        }
        return hunks;
    },

    /**
     * Render GitHub-style inline diff: full file content with changes highlighted,
     * dual line number gutters (old/new), and expandable context.
     */
    _renderInlineDiff(container, tab) {
        // Full file view — wrapper inside outer handles scrolling, minimap overlays
        container.style.overflow = 'hidden';

        const hunks = this._parseDiffHunks(tab.diff_lines || []);
        const fileContent = tab.content || '';
        const fileLines = fileContent.split('\n');
        // Remove trailing empty line from split if file ends with newline
        if (fileLines.length > 0 && fileLines[fileLines.length - 1] === '') {
            fileLines.pop();
        }

        // Build a map of new-line-number -> hunk line info for changed lines
        // and old-line-number -> hunk line info for deleted lines
        const addedLines = new Map();    // newLineNum -> {text}
        const deletedLines = [];         // [{oldLine, newLine (insert before), text}]
        const contextRanges = [];        // [{newStart, newEnd}] — ranges covered by hunks

        for (const hunk of hunks) {
            let hunkNewStart = Infinity;
            let hunkNewEnd = 0;
            for (const hl of hunk.lines) {
                if (hl.type === 'add') {
                    addedLines.set(hl.newLine, hl);
                    hunkNewStart = Math.min(hunkNewStart, hl.newLine);
                    hunkNewEnd = Math.max(hunkNewEnd, hl.newLine);
                } else if (hl.type === 'del') {
                    deletedLines.push({ ...hl, insertBeforeNew: this._findInsertPoint(hunk, hl) });
                    if (hl.oldLine !== null) {
                        hunkNewStart = Math.min(hunkNewStart, this._findInsertPoint(hunk, hl));
                    }
                } else if (hl.type === 'context') {
                    hunkNewStart = Math.min(hunkNewStart, hl.newLine);
                    hunkNewEnd = Math.max(hunkNewEnd, hl.newLine);
                }
            }
            if (hunkNewStart !== Infinity) {
                contextRanges.push({ newStart: hunkNewStart, newEnd: hunkNewEnd });
            }
        }

        // Group deleted lines by their insertion point (before which new line they appear)
        const deletedByInsertPoint = new Map();
        for (const dl of deletedLines) {
            const key = dl.insertBeforeNew;
            if (!deletedByInsertPoint.has(key)) deletedByInsertPoint.set(key, []);
            deletedByInsertPoint.get(key).push(dl);
        }

        // Build the full rendered output
        const wrapper = document.createElement('div');
        wrapper.className = 'rfb-inline-diff-full';

        // Create table for alignment
        const table = document.createElement('table');
        table.className = 'inline-diff-table';

        // Show all lines — full file view
        const visibleNewLines = new Set();
        for (let i = 1; i <= fileLines.length; i++) {
            visibleNewLines.add(i);
        }

        // For computing old line numbers for unchanged lines, track the offset
        // oldLine = newLine - offset, where offset changes with adds/dels
        const oldLineForNew = this._buildOldLineMap(hunks, fileLines.length);

        let lastRenderedLine = 0;

        for (let newLineNum = 1; newLineNum <= fileLines.length; newLineNum++) {
            // Insert deleted lines that go before this new line
            if (deletedByInsertPoint.has(newLineNum)) {
                for (const dl of deletedByInsertPoint.get(newLineNum)) {
                    const row = this._createDiffRow(dl.oldLine, null, 'del', dl.text);
                    table.appendChild(row);
                }
            }

            if (!visibleNewLines.has(newLineNum)) {
                // If we just rendered lines and now hit a gap, show a separator
                if (lastRenderedLine > 0 && visibleNewLines.has(lastRenderedLine)) {
                    const sepRow = this._createSeparatorRow(newLineNum);
                    table.appendChild(sepRow);
                }
                continue;
            }

            // Show separator at the start if we're skipping initial lines
            if (lastRenderedLine === 0 && newLineNum > 1) {
                const sepRow = this._createSeparatorRow(1);
                table.appendChild(sepRow);
            }
            // Show separator if there's a gap from the last rendered line
            if (lastRenderedLine > 0 && newLineNum > lastRenderedLine + 1 && !visibleNewLines.has(lastRenderedLine + 1)) {
                // Already handled above
            }

            const lineText = fileLines[newLineNum - 1];
            const isAdded = addedLines.has(newLineNum);
            const oldNum = oldLineForNew.get(newLineNum);
            const type = isAdded ? 'add' : 'context';

            const row = this._createDiffRow(isAdded ? null : oldNum, newLineNum, type, lineText);
            table.appendChild(row);
            lastRenderedLine = newLineNum;
        }

        // Handle deleted lines at the very end of the file
        const afterLast = fileLines.length + 1;
        if (deletedByInsertPoint.has(afterLast)) {
            for (const dl of deletedByInsertPoint.get(afterLast)) {
                const row = this._createDiffRow(dl.oldLine, null, 'del', dl.text);
                table.appendChild(row);
            }
        }

        // If file ends before the last visible, show trailing separator
        if (lastRenderedLine < fileLines.length && lastRenderedLine > 0) {
            const sepRow = this._createSeparatorRow(lastRenderedLine + 1);
            table.appendChild(sepRow);
        }

        wrapper.appendChild(table);

        // Wrap in outer container for minimap overlay
        const outer = document.createElement('div');
        outer.className = 'inline-diff-outer';
        outer.appendChild(wrapper);

        // Build scrollbar minimap showing change locations
        const totalRows = table.rows.length;
        if (totalRows > 0) {
            const minimap = document.createElement('div');
            minimap.className = 'inline-diff-minimap';

            // Merge adjacent same-type markers into bands for cleaner look
            let runStart = -1;
            let runType = null;
            const addMarker = (type, startIdx, endIdx) => {
                const marker = document.createElement('div');
                marker.className = `inline-diff-minimap-marker inline-diff-minimap-${type}`;
                const topPct = (startIdx / totalRows) * 100;
                const span = ((endIdx - startIdx + 1) / totalRows) * 100;
                marker.style.top = `${topPct}%`;
                marker.style.height = `${Math.max(span, 0.3)}%`;
                minimap.appendChild(marker);
            };

            for (let i = 0; i < totalRows; i++) {
                const row = table.rows[i];
                let color = null;
                if (row.classList.contains('inline-diff-add')) color = 'add';
                else if (row.classList.contains('inline-diff-del')) color = 'del';

                if (color === runType && runStart >= 0) {
                    // Continue the run
                } else {
                    // Flush previous run
                    if (runType) addMarker(runType, runStart, i - 1);
                    runStart = color ? i : -1;
                    runType = color;
                }
            }
            if (runType) addMarker(runType, runStart, totalRows - 1);

            // Click on minimap scrolls to that position in the wrapper
            minimap.addEventListener('click', (e) => {
                const rect = minimap.getBoundingClientRect();
                const fraction = (e.clientY - rect.top) / rect.height;
                wrapper.scrollTop = fraction * wrapper.scrollHeight;
            });

            // Show viewport indicator
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
                const topPct = (wrapper.scrollTop / sh) * 100;
                const heightPct = (ch / sh) * 100;
                viewport.style.top = `${topPct}%`;
                viewport.style.height = `${heightPct}%`;
            };
            wrapper.addEventListener('scroll', updateViewport, { passive: true });
            // Initial update after render
            requestAnimationFrame(updateViewport);

            // Drag viewport handle to scroll (replaces native scrollbar)
            let dragStartY = 0;
            let dragStartScrollTop = 0;
            const onDragMove = (e) => {
                e.preventDefault();
                const minimapRect = minimap.getBoundingClientRect();
                const deltaY = e.clientY - dragStartY;
                const scrollRange = wrapper.scrollHeight - wrapper.clientHeight;
                const minimapRange = minimapRect.height;
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

            outer.appendChild(minimap);
        }

        container.innerHTML = '';
        container.appendChild(outer);
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
            if (hunkIdx < hunks.length && newLine === hunks[hunkIdx].newStart) {
                const hunk = hunks[hunkIdx];
                for (const hl of hunk.lines) {
                    if (hl.type === 'context') {
                        map.set(hl.newLine, hl.oldLine);
                    } else if (hl.type === 'add') {
                        // Added lines have no old line number
                    }
                    // del lines don't have new line numbers
                }
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

    _createSeparatorRow(lineNum) {
        const row = document.createElement('tr');
        row.className = 'inline-diff-row inline-diff-separator';

        const td = document.createElement('td');
        td.colSpan = 4;
        td.className = 'inline-diff-expand';
        td.innerHTML = `<span class="inline-diff-expand-icon">⋯</span>`;

        row.appendChild(td);
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

    _updateTreeHighlight() {
        document.querySelectorAll('.rfb-tree-item.active').forEach(el => el.classList.remove('active'));
        if (this._activeTab >= 0) {
            const activePath = this._openTabs[this._activeTab].path;
            document.querySelectorAll('.rfb-tree-item[data-type="file"]').forEach(el => {
                if (el.dataset.path === activePath) el.classList.add('active');
            });
        }
    },

    _filterTree(query) {
        const treeEl = document.getElementById('rfb-tree');
        const items = treeEl.querySelectorAll('.rfb-tree-item');
        const childContainers = treeEl.querySelectorAll('.rfb-tree-children');
        const lq = query.toLowerCase().trim();

        if (!lq) {
            items.forEach(el => el.style.display = '');
            childContainers.forEach(el => {
                const path = el.dataset.path;
                el.classList.toggle('expanded', this._expandedDirs.has(path));
            });
            return;
        }

        const matchingPaths = new Set();
        items.forEach(el => {
            const name = el.querySelector('.tree-name')?.textContent?.toLowerCase() || '';
            const path = el.dataset.path || '';
            if (name.includes(lq)) {
                matchingPaths.add(path);
                const parts = path.split('/');
                for (let i = 1; i < parts.length; i++) matchingPaths.add(parts.slice(0, i).join('/'));
            }
        });

        items.forEach(el => {
            el.style.display = matchingPaths.has(el.dataset.path || '') ? '' : 'none';
        });
        childContainers.forEach(el => {
            el.classList.toggle('expanded', matchingPaths.has(el.dataset.path));
        });
    },

    _getFileIcon(filename) {
        const ext = filename.includes('.') ? '.' + filename.split('.').pop().toLowerCase() : '';
        const iconMap = {
            '.py': '🐍', '.js': '📜', '.ts': '📜', '.html': '🌐', '.css': '🎨',
            '.json': '📋', '.md': '📝', '.yaml': '⚙️', '.yml': '⚙️',
            '.png': '🖼️', '.jpg': '🖼️', '.jpeg': '🖼️', '.gif': '🖼️', '.svg': '🖼️',
            '.sh': '💻', '.sql': '🗃️', '.toml': '⚙️', '.xml': '📄',
        };
        return iconMap[ext] || '📄';
    },

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },
};


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

        let diffData = null;
        try {
            diffData = await Api.request('GET', `/api/items/${itemId}/diff`);
            DiffViewer.render(diffData.diff, diffContainer);

            const filesContainer = document.getElementById('review-files');
            if (diffData.files && diffData.files.length > 0) {
                filesContainer.innerHTML = '<div class="changed-files-list">' +
                    diffData.files.map(f => {
                        const cls = f.status === 'A' ? 'file-added' : f.status === 'D' ? 'file-deleted' : 'file-modified';
                        const escapedPath = f.path.replace(/"/g, '&quot;');
                        return `<button type="button" class="file-badge ${cls}" data-target-file="${escapedPath}">${f.status_label || f.status} ${f.path}</button>`;
                    }).join('') + '</div>';

                // Wire up scroll-to-diff on click
                filesContainer.querySelectorAll('.file-badge[data-target-file]').forEach(btn => {
                    btn.addEventListener('click', () => {
                        // Switch to diff tab first
                        ReviewDialog.switchReviewTab('diff');
                        // Find matching diff-file element and scroll to it
                        const targetPath = btn.dataset.targetFile;
                        const diffContainer = document.getElementById('review-diff');
                        const diffFile = diffContainer.querySelector(`.diff-file[data-file-path="${CSS.escape(targetPath)}"]`);
                        if (diffFile) {
                            // Ensure the diff body is expanded
                            const body = diffFile.querySelector('.diff-file-body');
                            if (body && body.style.display === 'none') {
                                body.style.display = '';
                            }
                            diffFile.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }
                    });
                });
            } else {
                filesContainer.innerHTML = '';
            }
        } catch (err) {
            diffContainer.innerHTML = `<p>Error loading diff: ${err.message}</p>`;
        }

        // Load review file browser (reuses diff data to avoid double fetch)
        ReviewFileBrowser.load(itemId, diffData);

        // Update Files tab badge with changed file count
        const filesTab = document.querySelector('.review-tab[data-tab="files"]');
        if (filesTab && diffData?.files?.length) {
            const badge = filesTab.querySelector('.column-count') || document.createElement('span');
            badge.className = 'column-count';
            badge.textContent = diffData.files.length;
            if (!filesTab.querySelector('.column-count')) filesTab.appendChild(badge);
        }

        // Update approve button based on whether there are file changes
        const approveBtn = document.getElementById('review-approve-btn');
        const hasChanges = diffData?.files?.length > 0;
        approveBtn.textContent = hasChanges ? '✓ Approve & Merge' : '✓ Done';

        // Preselect Work Log tab for review
        this.switchReviewTab('log');

        // Wire up buttons
        approveBtn.onclick = async () => {
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