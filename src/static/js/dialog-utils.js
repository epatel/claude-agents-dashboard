/**
 * Dialog utility functions
 */
const DialogUtils = {
    // --- Model display helpers ---

    _getModelDisplayName(modelId) {
        const modelNames = window.__MODEL_NAMES__ || {};
        return modelNames[modelId] || modelId;
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
                opt.textContent = m.display_name;
                optgroup.appendChild(opt);
            }
            selectEl.appendChild(optgroup);
        }
    },

    // --- Markdown rendering ---

    renderMarkdown(text) {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const html = marked.parse(text || '');
            return DOMPurify.sanitize(html);
        }
        // Fallback: escape HTML and convert newlines
        const d = document.createElement('div');
        d.textContent = text || '';
        return d.innerHTML.replace(/\n/g, '<br>');
    },
};