const FileBrowser = {
    ...FileTreeBase,
    _tree: {
        treeId: 'file-tree', tabsId: 'file-tabs', crumbId: 'file-breadcrumb',
        itemClass: 'file-tree-item', childrenClass: 'file-tree-children',
        tabClass: 'file-tab', tabNameClass: 'tab-name', tabCloseClass: 'tab-close',
        childLoadingHtml: '<div class="file-tree-loading" style="padding:4px 8px;font-size:12px;">Loading...</div>',
        extraIcons: { '.stl': '🧊', '.obj': '🧊', '.zip': '📦' },
    },
    _treeData: null,
    _openTabs: [],       // [{path, name, content, language, binary, mimeType, hidden}]
    _activeTab: -1,
    _expandedDirs: new Set(),
    _maxTabs: 10,
    _fontSize: parseInt(localStorage.getItem('fileBrowserFontSize')) || 13,

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

    async refresh() {
        // Refresh the file tree (keep expanded dirs for UX continuity)
        this._treeData = null;
        await this._loadTree('');

        // Re-expand previously expanded directories
        for (const dirPath of this._expandedDirs) {
            const node = this._findTreeNode(this._treeData, dirPath);
            if (node && node.children === null) {
                try {
                    const data = await Api.request('GET', `/api/files/tree?path=${encodeURIComponent(dirPath)}`);
                    node.children = data.tree;
                } catch (err) { /* skip dirs that no longer exist */ }
            }
        }
        // Re-render tree with expanded state restored
        if (this._treeData) {
            const treeEl = document.getElementById('file-tree');
            this._renderTreeNodes(treeEl, this._treeData, 0);
        }

        // Refresh the active tab's content
        if (this._activeTab >= 0) {
            const tab = this._openTabs[this._activeTab];
            try {
                const data = await Api.request('GET', `/api/files/content?path=${encodeURIComponent(tab.path)}`);
                tab.content = data.content;
                tab.language = data.language;
                tab.binary = data.binary;
                tab.mimeType = data.mime_type || null;
                tab.hidden = data.hidden || false;
                tab.truncated = data.truncated || false;
                tab.size = data.size;
                tab.lines = data.lines;
                tab.viewer = data.viewer || null;
                tab.modelFormat = data.model_format || null;
                tab.archiveEntries = data.archive_entries || null;
                this._renderContent();
            } catch (err) { /* file may have been deleted */ }
        }

        this._updateTreeHighlight();
    },

    changeFontSize(delta) {
        this._fontSize = Math.max(9, Math.min(24, this._fontSize + delta));
        localStorage.setItem('fileBrowserFontSize', this._fontSize);
        const viewers = document.querySelectorAll('.file-code-viewer, .file-markdown-viewer');
        viewers.forEach(el => { el.style.fontSize = this._fontSize + 'px'; });
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
            this._renderTreeNodes(treeEl, data.tree, 0);
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

    _treeUrl(path) {
        return path ? `/api/files/tree?path=${encodeURIComponent(path)}` : '/api/files/tree';
    },

    _renderSymlinkNode(container, node, indent) {
        const item = this._newTreeItem(node, indent, 'symlink', 'file-tree-symlink');

        const target = node.symlink_target || 'unknown';
        item.innerHTML = `
            <span class="tree-icon">🔗</span>
            <span class="tree-name">${this._escapeHtml(node.name)}</span>
            <span class="tree-symlink-target" title="→ ${this._escapeHtml(target)}">→ ${this._escapeHtml(target)}</span>
        `;

        container.appendChild(item);
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
                viewer: data.viewer || null,
                modelFormat: data.model_format || null,
                archiveEntries: data.archive_entries || null,
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
            this._renderTreeNodes(treeEl, this._treeData, 0);
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
        // Cleanup previous 3D viewer if any
        if (this._cleanup3D) this._cleanup3D();

        const contentEl = document.getElementById('file-content');
        const fontControls = document.getElementById('file-font-controls');

        if (this._activeTab < 0) {
            contentEl.innerHTML = `
                <div class="file-empty-state">
                    <div class="file-empty-icon">📂</div>
                    <p>Select a file from the tree to view it</p>
                </div>`;
            if (fontControls) fontControls.style.display = 'none';
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
            if (fontControls) fontControls.style.display = 'none';
            return;
        }

        // 3D model viewer
        if (tab.viewer === '3d' && tab.content) {
            this._render3DModel(contentEl, tab);
            if (fontControls) fontControls.style.display = 'none';
            return;
        }

        // Archive contents viewer
        if (tab.viewer === 'archive' && tab.archiveEntries) {
            this._renderArchive(contentEl, tab);
            if (fontControls) fontControls.style.display = 'none';
            return;
        }

        // Image
        if (tab.binary && tab.mimeType && tab.mimeType.startsWith('image/') && tab.content) {
            contentEl.innerHTML = `
                <div class="file-image-viewer">
                    <img src="${tab.content}" alt="${this._escapeHtml(tab.name)}">
                    <div class="file-image-info">${this._formatSize(tab.size)}</div>
                </div>`;
            if (fontControls) fontControls.style.display = 'none';
            return;
        }

        // Binary (non-image)
        if (tab.binary) {
            contentEl.innerHTML = `
                <div class="file-binary-placeholder">
                    <div class="file-binary-icon">📦</div>
                    <p>Binary file — ${this._formatSize(tab.size)}</p>
                </div>`;
            if (fontControls) fontControls.style.display = 'none';
            return;
        }

        // Markdown
        if (tab.language === 'markdown') {
            this._renderMarkdown(contentEl, tab);
            if (fontControls) fontControls.style.display = 'flex';
            return;
        }

        // Code / text
        this._renderCode(contentEl, tab);
        if (fontControls) fontControls.style.display = 'flex';
    },

    _renderCode(container, tab) {
        let html = '';
        if (tab.truncated) {
            html += '<div class="file-truncated-banner">File truncated — showing first 1MB</div>';
        }

        const langClass = tab.language ? `language-${tab.language}` : 'language-none';
        const fontStyle = this._fontSize !== 13 ? ` style="font-size:${this._fontSize}px"` : '';
        html += `<pre class="file-code-viewer line-numbers"${fontStyle}><code class="${langClass}">${this._escapeHtml(tab.content)}</code></pre>`;
        container.innerHTML = html;

        // Trigger Prism highlighting
        if (typeof Prism !== 'undefined') {
            Prism.highlightAllUnder(container);
        }
    },

    _renderMarkdownContent(mdDiv, content, filePath) {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            mdDiv.innerHTML = DOMPurify.sanitize(marked.parse(content), {
                ADD_TAGS: ['img'],
                ADD_ATTR: ['src', 'alt', 'height', 'width'],
            });
        } else {
            mdDiv.textContent = content;
            return;
        }
        // Rewrite relative image paths to load via API
        if (filePath) {
            const dir = filePath.includes('/') ? filePath.substring(0, filePath.lastIndexOf('/')) : '';
            mdDiv.querySelectorAll('img').forEach(img => {
                const src = img.getAttribute('src');
                if (src && !src.startsWith('http') && !src.startsWith('data:') && !src.startsWith('/')) {
                    const imgPath = dir ? `${dir}/${src}` : src;
                    // Load image via API and replace src with base64
                    Api.request('GET', `/api/files/content?path=${encodeURIComponent(imgPath)}`).then(data => {
                        if (data.content && data.binary) {
                            img.src = data.content;
                        }
                    }).catch(() => {});
                }
            });
        }
        // Render mermaid diagrams (rewrite code blocks → div.mermaid, then run)
        mdDiv.querySelectorAll('code.language-mermaid').forEach(code => {
            const mermaidDiv = document.createElement('div');
            mermaidDiv.className = 'mermaid';
            mermaidDiv.textContent = code.textContent;
            code.parentElement.replaceWith(mermaidDiv);
        });
        DialogUtils.runMermaid(mdDiv);
    },

    _renderMarkdown(container, tab) {
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';

        const toggle = document.createElement('button');
        toggle.className = 'file-markdown-toggle';
        toggle.textContent = 'Source';
        let showSource = false;

        const mdDiv = document.createElement('div');
        mdDiv.className = 'file-markdown-viewer';
        if (this._fontSize !== 13) {
            mdDiv.style.fontSize = this._fontSize + 'px';
        }
        this._renderMarkdownContent(mdDiv, tab.content, tab.path);

        toggle.addEventListener('click', () => {
            showSource = !showSource;
            toggle.textContent = showSource ? 'Preview' : 'Source';
            if (showSource) {
                this._renderCode(mdDiv, { ...tab, language: 'markdown', truncated: false });
                mdDiv.className = '';
            } else {
                mdDiv.className = 'file-markdown-viewer';
                this._renderMarkdownContent(mdDiv, tab.content, tab.path);
            }
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(mdDiv);
        container.innerHTML = '';
        container.appendChild(wrapper);
    },

    async _render3DModel(container, tab) {
        container.innerHTML = `
            <div class="file-3d-viewer">
                <div class="file-3d-canvas-wrap">
                    <canvas id="three-canvas"></canvas>
                </div>
                <div class="file-3d-controls">
                    <span class="file-3d-info">${this._escapeHtml(tab.name)} — ${this._formatSize(tab.size)} — ${tab.modelFormat.toUpperCase()}</span>
                    <span class="file-3d-hint">Drag to rotate · Scroll to zoom · Shift+drag to pan</span>
                </div>
            </div>`;

        try {
            const THREE = await import('three');
            const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');

            const canvas = document.getElementById('three-canvas');
            const wrap = canvas.parentElement;
            const width = wrap.clientWidth || 800;
            const height = wrap.clientHeight || 600;

            // Scene setup
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(getComputedStyle(document.documentElement)
                .getPropertyValue('--bg-primary').trim() || '#1a1a2e');

            const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 10000);
            const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
            renderer.setSize(width, height);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

            // Controls
            const controls = new OrbitControls(camera, canvas);
            controls.enableDamping = true;
            controls.dampingFactor = 0.08;

            // Lighting
            scene.add(new THREE.AmbientLight(0xffffff, 0.6));
            const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
            dirLight.position.set(5, 10, 7);
            scene.add(dirLight);
            const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.3);
            dirLight2.position.set(-5, -3, -5);
            scene.add(dirLight2);

            // Decode base64 data
            const binaryStr = atob(tab.content);
            const bytes = new Uint8Array(binaryStr.length);
            for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

            let geometry;
            if (tab.modelFormat === 'stl') {
                const { STLLoader } = await import('three/addons/loaders/STLLoader.js');
                const loader = new STLLoader();
                geometry = loader.parse(bytes.buffer);
                const material = new THREE.MeshPhongMaterial({
                    color: 0x4a9eff, specular: 0x222222, shininess: 60,
                    flatShading: false,
                });
                geometry.computeVertexNormals();
                const mesh = new THREE.Mesh(geometry, material);
                scene.add(mesh);
            } else if (tab.modelFormat === 'obj') {
                const { OBJLoader } = await import('three/addons/loaders/OBJLoader.js');
                const loader = new OBJLoader();
                const text = new TextDecoder().decode(bytes);
                const obj = loader.parse(text);
                obj.traverse(child => {
                    if (child.isMesh) {
                        child.material = new THREE.MeshPhongMaterial({
                            color: 0x4a9eff, specular: 0x222222, shininess: 60,
                        });
                    }
                });
                scene.add(obj);
            }

            // Fit camera to model
            const box = new THREE.Box3().setFromObject(scene);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const dist = maxDim * 1.8;
            camera.position.set(center.x + dist * 0.5, center.y + dist * 0.5, center.z + dist);
            camera.lookAt(center);
            controls.target.copy(center);
            controls.update();

            // Animation loop
            let animId;
            const animate = () => {
                animId = requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            };
            animate();

            // Resize handling
            const observer = new ResizeObserver(() => {
                const w = wrap.clientWidth;
                const h = wrap.clientHeight;
                camera.aspect = w / h;
                camera.updateProjectionMatrix();
                renderer.setSize(w, h);
            });
            observer.observe(wrap);

            // Cleanup when tab changes
            this._cleanup3D = () => {
                cancelAnimationFrame(animId);
                observer.disconnect();
                renderer.dispose();
                controls.dispose();
                this._cleanup3D = null;
            };
        } catch (err) {
            container.innerHTML = `
                <div class="file-binary-placeholder">
                    <div class="file-binary-icon">🧊</div>
                    <p>Failed to load 3D model: ${this._escapeHtml(err.message)}</p>
                </div>`;
        }
    },

    _cleanup3D: null,

    _renderArchive(container, tab) {
        const entries = tab.archiveEntries || [];
        const fileEntries = entries.filter(e => !e.is_dir);
        const dirEntries = entries.filter(e => e.is_dir);
        const totalUncompressed = fileEntries.reduce((sum, e) => sum + (e.size || 0), 0);
        const totalCompressed = fileEntries.reduce((sum, e) => sum + (e.compressed_size || 0), 0);

        let html = `
            <div class="file-archive-viewer">
                <div class="file-archive-header">
                    <span class="file-archive-title">📦 ${this._escapeHtml(tab.name)}</span>
                    <span class="file-archive-stats">
                        ${fileEntries.length} files, ${dirEntries.length} folders —
                        ${this._formatSize(totalUncompressed)} uncompressed
                        ${totalCompressed ? `(${this._formatSize(totalCompressed)} compressed, ${totalUncompressed ? Math.round((1 - totalCompressed/totalUncompressed) * 100) : 0}% saved)` : ''}
                    </span>
                </div>
                <table class="file-archive-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Size</th>
                            <th>Compressed</th>
                            <th>Date</th>
                        </tr>
                    </thead>
                    <tbody>`;

        for (const entry of entries) {
            if (entry.error) {
                html += `<tr class="archive-error"><td colspan="4">${this._escapeHtml(entry.name)}</td></tr>`;
                continue;
            }
            if (entry.truncated) {
                html += `<tr class="archive-truncated"><td colspan="4">${this._escapeHtml(entry.name)}</td></tr>`;
                continue;
            }
            const icon = entry.is_dir ? '📁' : this._getFileIcon(entry.name);
            const indent = (entry.name.match(/\//g) || []).length;
            const displayName = entry.name.endsWith('/') ? entry.name.slice(0, -1) : entry.name;
            html += `
                <tr class="${entry.is_dir ? 'archive-dir' : ''}">
                    <td style="padding-left:${8 + indent * 12}px">${icon} ${this._escapeHtml(displayName)}</td>
                    <td>${entry.is_dir ? '—' : this._formatSize(entry.size)}</td>
                    <td>${entry.is_dir ? '—' : this._formatSize(entry.compressed_size)}</td>
                    <td>${entry.date || '—'}</td>
                </tr>`;
        }

        html += `</tbody></table></div>`;
        container.innerHTML = html;
    },

    _showError(message, path) {
        const contentEl = document.getElementById('file-content');
        contentEl.innerHTML = '';
        const div = document.createElement('div');
        div.className = 'file-error';
        const p = document.createElement('p');
        p.textContent = message;
        div.appendChild(p);
        if (path) {
            const btn = document.createElement('button');
            btn.textContent = 'Retry';
            btn.addEventListener('click', () => this._openFile(path, path.split('/').pop()));
            div.appendChild(btn);
        }
        contentEl.appendChild(div);
    },

    _formatSize(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
