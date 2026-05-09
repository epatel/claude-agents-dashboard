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
        // Anthropic models always start with "claude-"
        if (modelId.startsWith('claude-')) return false;
        // If it's in the server-rendered list, it's Anthropic
        const serverModels = window.__MODEL_NAMES__ || {};
        // Models that were in the initial server render are Anthropic
        if (window.__ANTHROPIC_MODEL_IDS__ && window.__ANTHROPIC_MODEL_IDS__.has(modelId)) return false;
        // Fallback: if not a known Anthropic model and contains / or : it's likely Ollama
        return !modelId.startsWith('claude-');
    },

    /**
     * Get provider label for a model.
     */
    _getModelProvider(modelId) {
        return this._isOllamaModel(modelId) ? 'Ollama' : 'Anthropic';
    },

    /**
     * Get HTML for a provider badge.
     */
    _getProviderBadgeHtml(modelId) {
        const provider = this._getModelProvider(modelId);
        const cls = provider === 'Ollama' ? 'provider-badge-ollama' : 'provider-badge-anthropic';
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
            // Rewrite ```mermaid fenced code blocks (rendered by marked as
            // <pre><code class="language-mermaid">...</code></pre>) into
            // <pre class="mermaid">...</pre> containers so mermaid.run() can
            // turn them into SVG diagrams. Without this rewrite the diagram
            // source shows as a plain code block (see worklog/result tabs).
            const tmp = document.createElement('div');
            tmp.innerHTML = sanitized;
            tmp.querySelectorAll('pre code.language-mermaid').forEach(codeEl => {
                const pre = codeEl.parentElement;
                if (!pre || !pre.parentElement) return;
                const diagram = codeEl.textContent;
                const mermaidEl = document.createElement('pre');
                mermaidEl.className = 'mermaid';
                // textContent so the diagram source survives a later innerHTML
                // round-trip without needing manual HTML escaping.
                mermaidEl.textContent = diagram;
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
     * Render any mermaid diagrams (`<pre class="mermaid">`) inside `container`.
     * Safe to call multiple times — mermaid skips nodes that already carry
     * `data-processed="true"`. No-ops if mermaid isn't loaded or container
     * has no mermaid blocks.
     */
    runMermaid(container) {
        if (typeof mermaid === 'undefined' || !container) return;
        const nodes = container.querySelectorAll
            ? container.querySelectorAll('pre.mermaid:not([data-processed="true"])')
            : null;
        if (!nodes || nodes.length === 0) return;
        try {
            const result = mermaid.run({ nodes });
            if (result && typeof result.catch === 'function') {
                result.catch(err => console.warn('mermaid render failed:', err));
            }
        } catch (err) {
            console.warn('mermaid render failed:', err);
        }
    },
};