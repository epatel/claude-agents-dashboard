/**
 * Dialog utility functions
 */
const DialogUtils = {
    // --- Model display helpers ---

    _getModelDisplayName(modelId) {
        const modelNames = window.__MODEL_NAMES__ || {};
        return modelNames[modelId] || modelId;
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