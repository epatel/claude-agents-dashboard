/**
 * Shared file-tree / tab / breadcrumb behaviour for the two file browsers:
 * FileBrowser (topbar "Files", project checkout) and ReviewFileBrowser
 * (review dialog "Files" tab, an item's worktree).
 *
 * Each browser spreads this in (`{ ...FileTreeBase, ... }`) and supplies:
 *   _tree               — element ids, CSS classes and loading markup (see below)
 *   _treeUrl(path)      — tree endpoint ('' = root)
 *   _renderContent()    — the content pane
 * and may override these optional hooks:
 *   _dirExtraHtml(node), _decorateFileNode(item, node) -> extra html,
 *   _tabExtraHtml(tab), _navigateToDir(dirPath) (makes crumbs clickable),
 *   _renderSymlinkNode(container, node, indent) (else symlinks render as files).
 *
 * _tree = { treeId, tabsId, crumbId, itemClass, childrenClass, tabClass,
 *           tabNameClass, tabCloseClass, childLoadingHtml, extraIcons }
 */
const FileTreeBase = {
    _iconMap: {
        '.py': '🐍', '.js': '📜', '.ts': '📜', '.html': '🌐', '.css': '🎨',
        '.json': '📋', '.md': '📝', '.yaml': '⚙️', '.yml': '⚙️',
        '.png': '🖼️', '.jpg': '🖼️', '.jpeg': '🖼️', '.gif': '🖼️', '.svg': '🖼️',
        '.sh': '💻', '.sql': '🗃️', '.toml': '⚙️', '.xml': '📄',
    },

    _dirExtraHtml(node) { return ''; },
    _decorateFileNode(item, node) { return ''; },
    _tabExtraHtml(tab) { return ''; },

    _renderTreeNodes(container, nodes, indent) {
        container.innerHTML = '';
        for (const node of nodes) {
            if (node.type === 'dir') {
                this._renderDirNode(container, node, indent);
            } else if (node.type === 'symlink' && this._renderSymlinkNode) {
                this._renderSymlinkNode(container, node, indent);
            } else {
                this._renderFileNode(container, node, indent);
            }
        }
    },

    /** A tree row element for ``node`` (file/symlink rows get extra indent for the arrow). */
    _newTreeItem(node, indent, type, extraClass = '') {
        const item = document.createElement('div');
        item.className = extraClass ? `${this._tree.itemClass} ${extraClass}` : this._tree.itemClass;
        item.style.paddingLeft = `${8 + indent * 16 + (type === 'dir' ? 0 : 18)}px`;
        item.dataset.path = node.path;
        item.dataset.type = type;
        return item;
    },

    _renderDirNode(container, node, indent) {
        const item = this._newTreeItem(node, indent, 'dir');

        const isExpanded = this._expandedDirs.has(node.path);
        item.innerHTML = `
            <span class="tree-arrow ${isExpanded ? 'expanded' : ''}">▶</span>
            <span class="tree-icon">📁</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
            ${this._dirExtraHtml(node)}
        `;
        item.addEventListener('click', () => this._toggleDir(node, item, indent));
        container.appendChild(item);

        // Children container
        const children = document.createElement('div');
        children.className = `${this._tree.childrenClass} ${isExpanded ? 'expanded' : ''}`;
        children.dataset.path = node.path;
        if (isExpanded && node.children) {
            this._renderTreeNodes(children, node.children, indent + 1);
        }
        container.appendChild(children);
    },

    _renderFileNode(container, node, indent) {
        const item = this._newTreeItem(node, indent, 'file');

        const extraHtml = this._decorateFileNode(item, node);
        // Highlight active file
        if (this._activeTab >= 0 && this._openTabs[this._activeTab]?.path === node.path) {
            item.classList.add('active');
        }
        item.innerHTML = `
            <span class="tree-icon">${this._getFileIcon(node.name)}</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
            ${extraHtml}
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
            return;
        }
        this._expandedDirs.add(node.path);
        childrenEl.classList.add('expanded');
        arrowEl.classList.add('expanded');

        // Lazy load if children haven't been fetched
        if (node.children === null) {
            childrenEl.innerHTML = this._tree.childLoadingHtml;
            try {
                const data = await Api.request('GET', this._treeUrl(node.path));
                node.children = data.tree;
            } catch {
                childrenEl.innerHTML = '<div style="padding:4px 8px;font-size:12px;color:var(--danger);">Failed to load</div>';
                return;
            }
        }
        this._renderTreeNodes(childrenEl, node.children, indent + 1);
    },

    _getFileIcon(filename) {
        const ext = filename.includes('.') ? '.' + filename.split('.').pop().toLowerCase() : '';
        return this._tree.extraIcons?.[ext] || this._iconMap[ext] || '📄';
    },

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
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
        const t = this._tree;
        const tabsEl = document.getElementById(t.tabsId);
        tabsEl.innerHTML = '';
        this._openTabs.forEach((tab, i) => {
            const el = document.createElement('div');
            el.className = `${t.tabClass} ${i === this._activeTab ? 'active' : ''}`;
            el.innerHTML = `
                ${this._tabExtraHtml(tab)}
                <span class="${t.tabNameClass}" title="${this._escapeHtml(tab.path)}">${this._escapeHtml(tab.name)}</span>
                <span class="${t.tabCloseClass}">&times;</span>
            `;
            el.querySelector(`.${t.tabNameClass}`).addEventListener('click', () => this._switchTab(i));
            el.querySelector(`.${t.tabCloseClass}`).addEventListener('click', (e) => {
                e.stopPropagation();
                this._closeTab(i);
            });
            tabsEl.appendChild(el);
        });
    },

    _renderBreadcrumb() {
        const crumbEl = document.getElementById(this._tree.crumbId);
        if (this._activeTab < 0) {
            crumbEl.classList.remove('visible');
            return;
        }
        crumbEl.classList.add('visible');
        const parts = this._openTabs[this._activeTab].path.split('/');
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
                if (this._navigateToDir) span.addEventListener('click', () => this._navigateToDir(dirPath));
            }
            crumbEl.appendChild(span);
        });
    },

    _updateTreeHighlight() {
        const itemClass = this._tree.itemClass;
        document.querySelectorAll(`.${itemClass}.active`).forEach(el => el.classList.remove('active'));
        if (this._activeTab < 0) return;
        const activePath = this._openTabs[this._activeTab].path;
        document.querySelectorAll(`.${itemClass}[data-type="file"]`).forEach(el => {
            if (el.dataset.path === activePath) el.classList.add('active');
        });
    },

    _filterTree(query) {
        const treeEl = document.getElementById(this._tree.treeId);
        const items = treeEl.querySelectorAll(`.${this._tree.itemClass}`);
        const childContainers = treeEl.querySelectorAll(`.${this._tree.childrenClass}`);
        const lowerQuery = query.toLowerCase().trim();

        // No query: show everything and restore the expanded/collapsed state
        const visiblePaths = lowerQuery ? this._pathsMatching(items, lowerQuery) : null;
        items.forEach(el => {
            const shown = visiblePaths ? visiblePaths.has(el.dataset.path || '') : true;
            el.style.display = shown ? '' : 'none';
        });
        childContainers.forEach(el => {
            const expanded = visiblePaths ? visiblePaths.has(el.dataset.path) : this._expandedDirs.has(el.dataset.path);
            el.classList.toggle('expanded', expanded);
        });
    },

    /** Paths of tree items whose name contains the query, plus all their parent dirs. */
    _pathsMatching(items, lowerQuery) {
        const matchingPaths = new Set();
        items.forEach(el => {
            const name = el.querySelector('.tree-name')?.textContent?.toLowerCase() || '';
            if (!name.includes(lowerQuery)) return;
            const path = el.dataset.path || '';
            matchingPaths.add(path);
            const parts = path.split('/');
            for (let i = 1; i < parts.length; i++) matchingPaths.add(parts.slice(0, i).join('/'));
        });
        return matchingPaths;
    },
};
