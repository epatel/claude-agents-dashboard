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
        // Check cache first
        if (this._ollamaCache.fetched && this._ollamaCache.models.some(m => m.name === modelId)) {
            return true;
        }
        // Anthropic models always start with "claude-"; Kimi models ("kimi-*")
        // run on the Kimi Agent SDK runtime, not Ollama.
        if (modelId.startsWith('claude-') || this._isKimiModel(modelId)) return false;
        // If it's in the server-rendered list, it's Anthropic
        const serverModels = window.__MODEL_NAMES__ || {};
        // Models that were in the initial server render are Anthropic
        if (window.__ANTHROPIC_MODEL_IDS__ && window.__ANTHROPIC_MODEL_IDS__.has(modelId)) return false;
        // Fallback: if not a known Anthropic model and contains / or : it's likely Ollama
        return !modelId.startsWith('claude-');
    },

    /**
     * Determine if a model ID is a Kimi model (Kimi Agent SDK runtime, experimental).
     */
    _isKimiModel(modelId) {
        return !!modelId && modelId.startsWith('kimi-');
    },

    /**
     * Get provider label for a model.
     */
    _getModelProvider(modelId) {
        if (this._isKimiModel(modelId)) return 'Kimi';
        return this._isOllamaModel(modelId) ? 'Ollama' : 'Anthropic';
    },

    /**
     * Get HTML for a provider badge.
     */
    _getProviderBadgeHtml(modelId) {
        const provider = this._getModelProvider(modelId);
        const cls = provider === 'Ollama' ? 'provider-badge-ollama'
            : provider === 'Kimi' ? 'provider-badge-kimi'
            : 'provider-badge-anthropic';
        return `<span class="provider-badge ${cls}">${provider}</span>`;
    },

    // --- Ollama model discovery ---

    _ollamaCache: { models: [], enabled: false, fetched: false },

    async fetchOllamaModels() {
        try {
            const result = await Api.request('GET', '/api/ollama/models');
            this._ollamaCache = {
                models: result.models || [],
                enabled: result.enabled !== false,
                fetched: true,
            };
            // Update global model names map
            for (const m of this._ollamaCache.models) {
                window.__MODEL_NAMES__[m.name] = m.display_name;
            }
            return this._ollamaCache;
        } catch {
            return this._ollamaCache;
        }
    },

    /**
     * Append Ollama models as an optgroup to a <select> element.
     * Removes any existing Ollama optgroup first.
     */
    async populateOllamaOptions(selectEl) {
        if (!selectEl) return;
        // Ollama is experimental — skip if not enabled
        if (!window.__EXPERIMENTAL__) return;

        // Fetch if not yet cached
        if (!this._ollamaCache.fetched) {
            await this.fetchOllamaModels();
        }

        // Remove existing Ollama optgroup
        const existing = selectEl.querySelector('optgroup[label="Ollama Models"]');
        if (existing) existing.remove();

        if (this._ollamaCache.enabled && this._ollamaCache.models.length > 0) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = 'Ollama Models';
            for (const m of this._ollamaCache.models) {
                const opt = document.createElement('option');
                opt.value = m.name;
                const sizeStr = m.size ? ` (${(m.size / 1e9).toFixed(1)}GB)` : '';
                const paramStr = m.parameter_size ? `:${m.parameter_size}` : '';
                opt.textContent = `${m.display_name}${paramStr}${sizeStr}`;
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
};