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

        const toggleDiv = document.createElement('div');
        toggleDiv.className = 'rfb-view-toggle';

        const diffBtn = document.createElement('button');
        diffBtn.textContent = 'Diff';
        diffBtn.className = 'active';

        const codeBtn = document.createElement('button');
        codeBtn.textContent = 'Full File';

        toggleDiv.appendChild(diffBtn);
        toggleDiv.appendChild(codeBtn);
        container.appendChild(toggleDiv);

        const viewArea = document.createElement('div');
        viewArea.style.flex = '1';
        viewArea.style.overflow = 'auto';
        container.appendChild(viewArea);

        this._renderDiff(viewArea, tab.diff_lines);

        diffBtn.addEventListener('click', () => {
            diffBtn.classList.add('active');
            codeBtn.classList.remove('active');
            this._renderDiff(viewArea, tab.diff_lines);
        });

        codeBtn.addEventListener('click', () => {
            codeBtn.classList.add('active');
            diffBtn.classList.remove('active');
            this._renderCode(viewArea, tab);
        });
    },

    _renderDiff(container, lines) {
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