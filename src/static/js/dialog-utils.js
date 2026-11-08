/**
 * Dialog utility functions
 */
const DialogUtils = {
    // --- Model display helpers ---

    _getModelDisplayName(modelId) {
        const modelNames = window.__MODEL_NAMES__ || {};
        return modelNames[modelId] || modelId;
    },

    /**
     * Determine if a model ID is an Ollama model.
     * Anthropic models follow patterns like "claude-*" or contain "claude".
     */
    _isOllamaModel(modelId) {
        if (!modelId) return false;
        if (this._isCachedOllamaModel(modelId)) return true;
        if (this._isNonOllamaFamily(modelId)) return false;
        // Models that were in the initial server render are Anthropic; anything
        // else is taken to be Ollama.
        const anthropicIds = window.__ANTHROPIC_MODEL_IDS__;
        return !(anthropicIds && anthropicIds.has(modelId));
    },

    _isCachedOllamaModel(modelId) {
        return this._ollamaCache.fetched && this._ollamaCache.models.some(m => m.name === modelId);
    },

    /**
     * Anthropic models always start with "claude-"; Kimi models ("kimi-*") run on
     * the Kimi Agent SDK runtime, and Tiiny models ("tiiny/*") on the Tiiny
     * device — none of them are Ollama.
     */
    _isNonOllamaFamily(modelId) {
        return ['claude-', 'kimi-', 'tiiny/'].some(prefix => modelId.startsWith(prefix));
    },

    /**
     * Determine if a model ID is a Kimi model (Kimi Agent SDK runtime, experimental).
     */
    _isKimiModel(modelId) {
        return !!modelId && modelId.startsWith('kimi-');
    },

    /**
     * Determine if a model ID is a Tiiny model (local Tiiny device, experimental).
     */
    _isTiinyModel(modelId) {
        return !!modelId && modelId.startsWith('tiiny/');
    },

    /**
     * True for models served by a local provider (Ollama or Tiiny).
     */
    _isLocalModel(modelId) {
        return this._isTiinyModel(modelId) || this._isOllamaModel(modelId);
    },

    /**
     * Get provider label for a model.
     */
    _getModelProvider(modelId) {
        if (this._isKimiModel(modelId)) return 'Kimi';
        if (this._isTiinyModel(modelId)) return 'Tiiny';
        return this._isOllamaModel(modelId) ? 'Ollama' : 'Anthropic';
    },

    /**
     * Get HTML for a provider badge.
     */
    _getProviderBadgeHtml(modelId) {
        const provider = this._getModelProvider(modelId);
        const cls = provider === 'Ollama' ? 'provider-badge-ollama'
            : provider === 'Kimi' ? 'provider-badge-kimi'
            : provider === 'Tiiny' ? 'provider-badge-tiiny'
            : 'provider-badge-anthropic';
        return `<span class="provider-badge ${cls}">${provider}</span>`;
    },

    // --- Ollama model discovery ---

    _ollamaCache: { models: [], enabled: false, fetched: false },

    fetchOllamaModels() {
        return this._fetchModels('/api/ollama/models', '_ollamaCache');
    },

    /**
     * Append Ollama models as an optgroup to a <select> element.
     * Removes any existing Ollama optgroup first.
     */
    populateOllamaOptions(selectEl) {
        return this._populateModelOptions(selectEl, {
            label: 'Ollama Models', cacheKey: '_ollamaCache', fetch: 'fetchOllamaModels',
            optionText: (m) => {
                const sizeStr = m.size ? ` (${(m.size / 1e9).toFixed(1)}GB)` : '';
                const paramStr = m.parameter_size ? `:${m.parameter_size}` : '';
                return `${m.display_name}${paramStr}${sizeStr}`;
            },
        });
    },

    // --- Tiiny model discovery ---

    _tiinyCache: { models: [], enabled: false, fetched: false },

    fetchTiinyModels() {
        return this._fetchModels('/api/tiiny/models', '_tiinyCache');
    },

    /**
     * Append Tiiny models as an optgroup to a <select> element.
     * Removes any existing Tiiny optgroup first.
     */
    populateTiinyOptions(selectEl) {
        return this._populateModelOptions(selectEl, {
            label: 'Tiiny Models', cacheKey: '_tiinyCache', fetch: 'fetchTiinyModels',
            optionText: (m) => m.display_name,
        });
    },

    // --- Shared local-provider model discovery (Ollama, Tiiny) ---

    /**
     * Load a provider's model list into `this[cacheKey]` and the global model-name
     * map. On failure the previous cache stays. Returns the cache.
     */
    async _fetchModels(url, cacheKey) {
        try {
            const result = await Api.request('GET', url);
            this[cacheKey] = {
                models: result.models || [],
                enabled: result.enabled !== false,
                fetched: true,
            };
            for (const m of this[cacheKey].models) {
                window.__MODEL_NAMES__[m.name] = m.display_name;
            }
        } catch {
            // keep the previous cache
        }
        return this[cacheKey];
    },

    /**
     * Replace the `label` optgroup of `selectEl` with the cached models (fetched on
     * first use through `this[fetch]()`). Local providers are experimental, so
     * nothing happens unless the experimental flag is on.
     */
    async _populateModelOptions(selectEl, { label, cacheKey, fetch, optionText }) {
        if (!selectEl || !window.__EXPERIMENTAL__) return;
        if (!this[cacheKey].fetched) {
            await this[fetch]();
        }
        const existing = selectEl.querySelector(`optgroup[label="${label}"]`);
        if (existing) existing.remove();
        const cache = this[cacheKey];
        if (cache.enabled && cache.models.length > 0) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = label;
            for (const m of cache.models) {
                const opt = document.createElement('option');
                opt.value = m.name;
                opt.textContent = optionText(m);
                optgroup.appendChild(opt);
            }
            selectEl.appendChild(optgroup);
        }
    },

    // --- Markdown rendering ---

    renderMarkdown(text) {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const html = marked.parse(text || '');
            const sanitized = DOMPurify.sanitize(html);
            // Convert ```mermaid fenced blocks (marked emits <pre><code
            // class="language-mermaid">) into <div class="mermaid"> so
            // mermaid.run() picks them up. <div> (not <pre>) avoids the
            // dark code-block styling that would mask successful renders.
            const tmp = document.createElement('div');
            tmp.innerHTML = sanitized;
            tmp.querySelectorAll('pre code.language-mermaid').forEach(codeEl => {
                const pre = codeEl.parentElement;
                if (!pre || !pre.parentElement) return;
                const mermaidEl = document.createElement('div');
                mermaidEl.className = 'mermaid';
                mermaidEl.textContent = codeEl.textContent;
                pre.replaceWith(mermaidEl);
            });
            return tmp.innerHTML;
        }
        // Fallback: escape HTML and convert newlines
        const d = document.createElement('div');
        d.textContent = text || '';
        return d.innerHTML.replace(/\n/g, '<br>');
    },

    /**
     * Render mermaid diagrams inside `container`; on failure show raw source.
     *
     * Uses `mermaid.render(id, text)` rather than `mermaid.run({ nodes })`
     * because `run()` measures text dimensions in-place — and our review
     * dialog tabs (Result, Work Log) start with `display: none`, where
     * `getBoundingClientRect` returns 0 and the SVG collapses to a small
     * dark rectangle. `render()` uses an offscreen temp container appended
     * to `document.body`, so layout works regardless of where the
     * destination node lives.
     */
    runMermaid(container) {
        if (typeof mermaid === 'undefined' || !container) return;
        const nodes = container.querySelectorAll('div.mermaid:not([data-processed="true"])');
        if (nodes.length === 0) return;

        const showFallback = (node, source) => {
            node.classList.remove('mermaid');
            node.classList.add('mermaid-failed');
            const pre = document.createElement('pre');
            const code = document.createElement('code');
            code.className = 'language-mermaid';
            code.textContent = source;
            pre.appendChild(code);
            node.replaceChildren(pre);
        };

        nodes.forEach((node, i) => {
            const source = node.textContent;
            const id = `mermaid-${Date.now()}-${i}-${Math.random().toString(36).slice(2, 8)}`;
            // Mark immediately so a re-entrant call doesn't double-render.
            node.setAttribute('data-processed', 'true');
            try {
                const p = mermaid.render(id, source);
                Promise.resolve(p)
                    .then(({ svg, bindFunctions }) => {
                        node.innerHTML = svg;
                        if (bindFunctions) bindFunctions(node);
                    })
                    .catch(err => {
                        console.warn('mermaid render failed:', err);
                        showFallback(node, source);
                    });
            } catch (err) {
                console.warn('mermaid render failed:', err);
                showFallback(node, source);
            }
        });
    },

    /** The item with ``itemId`` from a fresh board fetch, or undefined. */
    async fetchItem(itemId) {
        const items = await Api.getItems();
        return items.find(i => i.id === itemId);
    },

    /**
     * Render an item's work log into ``logEl`` and scroll it to the end.
     * Returns the entries ([] when loading or rendering fails; the log is then blank).
     */
    async loadWorkLog(itemId, logEl) {
        try {
            const log = await Api.getWorkLog(itemId);
            if (log.length > 0) {
                logEl.innerHTML = log.map(e =>
                    `<div class="log-entry log-entry-${e.entry_type}"><span class="log-meta">[${e.timestamp}] ${e.entry_type}:</span> <div class="log-content">${this.renderMarkdown(e.content)}</div></div>`
                ).join('');
                this.runMermaid(logEl);
                DialogCore.forceAutoScroll(logEl);
            } else {
                logEl.innerHTML = '<div class="log-entry">No work log entries</div>';
            }
            return log;
        } catch {
            logEl.innerHTML = '';
            return [];
        }
    },

    /** Mark the tab buttons matching ``selector`` active iff their data-tab is ``tabName``. */
    markActiveTab(selector, tabName) {
        document.querySelectorAll(selector).forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });
    },

    /**
     * Show one panel of a tabbed dialog. ``spec``: tab button / panel selectors, the
     * panel id prefix, and the work-log tab + element (scrolled to the end when shown —
     * an explicit user action).
     */
    showTab(tabName, { tabs, panels, panelIdPrefix, logTab, logId }) {
        this.markActiveTab(tabs, tabName);
        document.querySelectorAll(panels).forEach(c => {
            c.style.display = 'none';
            c.classList.remove('active');
        });
        const active = document.getElementById(panelIdPrefix + tabName);
        if (!active) return;
        active.style.display = '';
        active.classList.add('active');
        const logEl = tabName === logTab && document.getElementById(logId);
        if (logEl && logEl.children.length > 0) {
            DialogCore.forceAutoScroll(logEl);
        }
    },
};
