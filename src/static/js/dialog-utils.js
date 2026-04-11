/**
 * Dialog utility functions
 */
const DialogUtils = {
    // --- Model display helpers ---

    _getModelDisplayName(modelId) {
        const modelNames = {
            'claude-sonnet-4-20250514': 'Claude Sonnet 4',
            'claude-sonnet-4-20250514+advisor': 'Claude Sonnet 4 + Advisor',
            'claude-opus-4-6': 'Claude Opus 4.6',
            'claude-haiku-4-5-20251001': 'Claude Haiku 4.5'
        };
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