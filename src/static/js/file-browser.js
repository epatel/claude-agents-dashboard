const FileBrowser = {
    _treeData: null,
    _openTabs: [],       // [{path, name, content, language, binary, mimeType, hidden}]
    _activeTab: -1,
    _expandedDirs: new Set(),
    _maxTabs: 10,

    init() {
        const filterInput = document.getElementById('file-tree-filter');
        if (filterInput) {
            filterInput.addEventListener('input', (e) => this._filterTree(e.target.value));
            filterInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    e.target.value = '';
                    this._filterTree('');
                }
            });
        }

        // Close dialog on Escape
        const dialog = document.getElementById('file-browser-dialog');
        if (dialog) {
            dialog.addEventListener('close', () => {
                // Reset filter on close
                const filter = document.getElementById('file-tree-filter');
                if (filter) filter.value = '';
            });
        }

        // Ctrl/Cmd + F focuses filter when dialog is open
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                const dialog = document.getElementById('file-browser-dialog');
                if (dialog && dialog.open) {
                    e.preventDefault();
                    const filter = document.getElementById('file-tree-filter');
                    if (filter) filter.focus();
                }
            }
        });

        // Arrow key navigation in tree
        const treeEl = document.getElementById('file-tree');
        if (treeEl) {
            treeEl.setAttribute('tabindex', '0');
            treeEl.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    this._navigateTree(e.key === 'ArrowDown' ? 1 : -1);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    this._activateCurrentTreeItem();
                }
            });
        }
    },

    open() {
        const dialog = document.getElementById('file-browser-dialog');
        if (!dialog) return;
        dialog.showModal();
        if (!this._treeData) {
            this._loadTree('');
        }
    },

    close() {
        const dialog = document.getElementById('file-browser-dialog');
        if (dialog) dialog.close();
    },

    async _loadTree(path) {
        const treeEl = document.getElementById('file-tree');
        treeEl.innerHTML = '<div class="file-tree-loading">Loading...</div>';
        try {
            const url = path ? `/api/files/tree?path=${encodeURIComponent(path)}` : '/api/files/tree';
            const data = await Api.request('GET', url);
            if (!path) {
                this._treeData = data.tree;
            }
            this._renderTree(treeEl, data.tree, 0);
        } catch (err) {
            treeEl.innerHTML = '';
            const errDiv = document.createElement('div');
            errDiv.className = 'file-error';
            errDiv.innerHTML = '<p>Failed to load files</p>';
            const retryBtn = document.createElement('button');
            retryBtn.textContent = 'Retry';
            retryBtn.addEventListener('click', () => this._loadTree(path));
            errDiv.appendChild(retryBtn);
            treeEl.appendChild(errDiv);
        }
    },

    _renderTree(container, nodes, indent) {
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
        item.className = 'file-tree-item';
        item.style.paddingLeft = `${8 + indent * 16}px`;
        item.dataset.path = node.path;
        item.dataset.type = 'dir';

        const isExpanded = this._expandedDirs.has(node.path);
        item.innerHTML = `
            <span class="tree-arrow ${isExpanded ? 'expanded' : ''}">▶</span>
            <span class="tree-icon">📁</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
        `;

        item.addEventListener('click', () => this._toggleDir(node, item, indent));
        container.appendChild(item);

        // Children container
        const children = document.createElement('div');
        children.className = `file-tree-children ${isExpanded ? 'expanded' : ''}`;
        children.dataset.path = node.path;

        if (isExpanded && node.children) {
            this._renderTree(children, node.children, indent + 1);
        }
        container.appendChild(children);
    },

    _renderFileNode(container, node, indent) {
        const item = document.createElement('div');
        item.className = 'file-tree-item';
        item.style.paddingLeft = `${8 + indent * 16 + 18}px`; // Extra for arrow space
        item.dataset.path = node.path;
        item.dataset.type = 'file';

        const icon = this._getFileIcon(node.name);
        item.innerHTML = `
            <span class="tree-icon">${icon}</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
        `;

        // Highlight active file
        if (this._activeTab >= 0 && this._openTabs[this._activeTab]?.path === node.path) {
            item.classList.add('active');
        }

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

            // Lazy load if children haven't been fetched
            if (node.children === null) {
                childrenEl.innerHTML = '<div class="file-tree-loading" style="padding:4px 8px;font-size:12px;">Loading...</div>';
                try {
                    const data = await Api.request('GET', `/api/files/tree?path=${encodeURIComponent(node.path)}`);
                    node.children = data.tree;
                    this._renderTree(childrenEl, node.children, indent + 1);
                } catch (err) {
                    childrenEl.innerHTML = '<div style="padding:4px 8px;font-size:12px;color:var(--danger);">Failed to load</div>';
                }
            } else {
                this._renderTree(childrenEl, node.children, indent + 1);
            }
        }
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

    async _openFile(path, name) {
        // Check if already open in a tab
        const existingIdx = this._openTabs.findIndex(t => t.path === path);
        if (existingIdx >= 0) {
            this._switchTab(existingIdx);
            return;
        }

        // Show loading state
        const contentEl = document.getElementById('file-content');
        contentEl.innerHTML = '<div class="file-loading">Loading...</div>';

        // Fetch file content
        try {
            const data = await Api.request('GET', `/api/files/content?path=${encodeURIComponent(path)}`);
            const tab = {
                path: data.path,
                name: name,
                content: data.content,
                language: data.language,
                binary: data.binary,
                mimeType: data.mime_type || null,
                hidden: data.hidden || false,
                truncated: data.truncated || false,
                size: data.size,
                lines: data.lines,
            };

            // Enforce max tabs
            if (this._openTabs.length >= this._maxTabs) {
                this._closeTab(0);
            }

            this._openTabs.push(tab);
            this._switchTab(this._openTabs.length - 1);
        } catch (err) {
            this._showError(`Failed to load file: ${path}`, path);
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
        const tabsEl = document.getElementById('file-tabs');
        tabsEl.innerHTML = '';
        this._openTabs.forEach((tab, i) => {
            const el = document.createElement('div');
            el.className = `file-tab ${i === this._activeTab ? 'active' : ''}`;
            el.innerHTML = `
                <span class="tab-name" title="${this._escapeHtml(tab.path)}">${this._escapeHtml(tab.name)}</span>
                <span class="tab-close">&times;</span>
            `;
            el.querySelector('.tab-name').addEventListener('click', () => this._switchTab(i));
            el.querySelector('.tab-close').addEventListener('click', (e) => {
                e.stopPropagation();
                this._closeTab(i);
            });
            tabsEl.appendChild(el);
        });
    },

    _renderBreadcrumb() {
        const crumbEl = document.getElementById('file-breadcrumb');
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
            if (i < parts.length - 1) {
                span.className = 'crumb';
                const dirPath = parts.slice(0, i + 1).join('/');
                span.addEventListener('click', () => this._navigateToDir(dirPath));
            }
            crumbEl.appendChild(span);
        });
    },

    async _navigateToDir(dirPath) {
        // Expand the directory in the tree, triggering lazy loads as needed
        const parts = dirPath.split('/');
        let current = '';
        for (const part of parts) {
            current = current ? `${current}/${part}` : part;
            this._expandedDirs.add(current);
        }

        // Find the tree node and lazy-load if needed
        const node = this._findTreeNode(this._treeData, dirPath);
        if (node && node.children === null) {
            try {
                const data = await Api.request('GET', `/api/files/tree?path=${encodeURIComponent(dirPath)}`);
                node.children = data.tree;
            } catch (err) {
                // Silently fail — tree will show expanded but empty
            }
        }

        // Re-render tree to show expanded state
        if (this._treeData) {
            const treeEl = document.getElementById('file-tree');
            this._renderTree(treeEl, this._treeData, 0);
        }
    },

    _findTreeNode(nodes, path) {
        if (!nodes) return null;
        for (const node of nodes) {
            if (node.path === path) return node;
            if (node.children && path.startsWith(node.path + '/')) {
                const found = this._findTreeNode(node.children, path);
                if (found) return found;
            }
        }
        return null;
    },

    _renderContent() {
        const contentEl = document.getElementById('file-content');

        if (this._activeTab < 0) {
            contentEl.innerHTML = `
                <div class="file-empty-state">
                    <div class="file-empty-icon">📂</div>
                    <p>Select a file from the tree to view it</p>
                </div>`;
            return;
        }

        const tab = this._openTabs[this._activeTab];

        // Hidden (secret) file
        if (tab.hidden) {
            contentEl.innerHTML = `
                <div class="file-hidden-placeholder">
                    <div class="file-binary-icon">🔒</div>
                    <p>Hidden for security</p>
                </div>`;
            return;
        }

        // Image
        if (tab.binary && tab.mimeType && tab.mimeType.startsWith('image/') && tab.content) {
            contentEl.innerHTML = `
                <div class="file-image-viewer">
                    <img src="${tab.content}" alt="${this._escapeHtml(tab.name)}">
                    <div class="file-image-info">${this._formatSize(tab.size)}</div>
                </div>`;
            return;
        }

        // Binary (non-image)
        if (tab.binary) {
            contentEl.innerHTML = `
                <div class="file-binary-placeholder">
                    <div class="file-binary-icon">📦</div>
                    <p>Binary file — ${this._formatSize(tab.size)}</p>
                </div>`;
            return;
        }

        // Markdown
        if (tab.language === 'markdown') {
            this._renderMarkdown(contentEl, tab);
            return;
        }

        // Code / text
        this._renderCode(contentEl, tab);
    },

    _renderCode(container, tab) {
        let html = '';
        if (tab.truncated) {
            html += '<div class="file-truncated-banner">File truncated — showing first 1MB</div>';
        }

        const langClass = tab.language ? `language-${tab.language}` : 'language-none';
        html += `<pre class="file-code-viewer line-numbers"><code class="${langClass}">${this._escapeHtml(tab.content)}</code></pre>`;
        container.innerHTML = html;

        // Trigger Prism highlighting
        if (typeof Prism !== 'undefined') {
            Prism.highlightAllUnder(container);
        }
    },

    _renderMarkdown(container, tab) {
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';

        // Toggle button
        const toggle = document.createElement('button');
        toggle.className = 'file-markdown-toggle';
        toggle.textContent = 'Source';
        let showSource = false;

        const mdDiv = document.createElement('div');
        mdDiv.className = 'file-markdown-viewer';
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            mdDiv.innerHTML = DOMPurify.sanitize(marked.parse(tab.content));
        } else {
            mdDiv.textContent = tab.content;
        }

        toggle.addEventListener('click', () => {
            showSource = !showSource;
            toggle.textContent = showSource ? 'Preview' : 'Source';
            if (showSource) {
                this._renderCode(mdDiv, { ...tab, language: 'markdown', truncated: false });
                mdDiv.className = '';
            } else {
                mdDiv.className = 'file-markdown-viewer';
                if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
                    mdDiv.innerHTML = DOMPurify.sanitize(marked.parse(tab.content));
                }
            }
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(mdDiv);
        container.innerHTML = '';
        container.appendChild(wrapper);
    },

    _showError(message, path) {
        const contentEl = document.getElementById('file-content');
        contentEl.innerHTML = `
            <div class="file-error">
                <p>${this._escapeHtml(message)}</p>
                ${path ? `<button onclick="FileBrowser._openFile('${path}', '${path.split('/').pop()}')">Retry</button>` : ''}
            </div>`;
    },

    _updateTreeHighlight() {
        document.querySelectorAll('.file-tree-item.active').forEach(el => el.classList.remove('active'));
        if (this._activeTab >= 0) {
            const activePath = this._openTabs[this._activeTab].path;
            document.querySelectorAll('.file-tree-item[data-type="file"]').forEach(el => {
                if (el.dataset.path === activePath) {
                    el.classList.add('active');
                }
            });
        }
    },

    _formatSize(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    },

    _filterTree(query) {
        const treeEl = document.getElementById('file-tree');
        const items = treeEl.querySelectorAll('.file-tree-item');
        const childContainers = treeEl.querySelectorAll('.file-tree-children');
        const lowerQuery = query.toLowerCase().trim();

        if (!lowerQuery) {
            // Show everything
            items.forEach(el => el.style.display = '');
            childContainers.forEach(el => {
                // Restore expanded/collapsed state
                const path = el.dataset.path;
                if (this._expandedDirs.has(path)) {
                    el.classList.add('expanded');
                } else {
                    el.classList.remove('expanded');
                }
            });
            return;
        }

        // First pass: mark matching items
        const matchingPaths = new Set();
        items.forEach(el => {
            const name = el.querySelector('.tree-name')?.textContent?.toLowerCase() || '';
            const path = el.dataset.path || '';
            if (name.includes(lowerQuery)) {
                matchingPaths.add(path);
                // Also mark all parent paths as having matches
                const parts = path.split('/');
                for (let i = 1; i < parts.length; i++) {
                    matchingPaths.add(parts.slice(0, i).join('/'));
                }
            }
        });

        // Second pass: show/hide based on matches
        items.forEach(el => {
            const path = el.dataset.path || '';
            el.style.display = matchingPaths.has(path) ? '' : 'none';
        });

        // Expand all parent directories of matches
        childContainers.forEach(el => {
            const path = el.dataset.path;
            if (matchingPaths.has(path)) {
                el.classList.add('expanded');
            } else {
                el.classList.remove('expanded');
            }
        });
    },

    _navigateTree(direction) {
        const items = Array.from(document.querySelectorAll('.file-tree-item'))
            .filter(el => el.style.display !== 'none');
        if (items.length === 0) return;

        const focused = document.querySelector('.file-tree-item.focused');
        let idx = focused ? items.indexOf(focused) : -1;
        if (focused) focused.classList.remove('focused');

        idx += direction;
        if (idx < 0) idx = 0;
        if (idx >= items.length) idx = items.length - 1;

        items[idx].classList.add('focused');
        items[idx].scrollIntoView({ block: 'nearest' });
    },

    _activateCurrentTreeItem() {
        const focused = document.querySelector('.file-tree-item.focused');
        if (focused) focused.click();
    },
};

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => FileBrowser.init());
} else {
    FileBrowser.init();
}
