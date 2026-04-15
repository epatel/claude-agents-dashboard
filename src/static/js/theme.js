const Theme = {
    STORAGE_KEY: 'agents-dashboard-theme',

    init() {
        const saved = localStorage.getItem(this.STORAGE_KEY) || 'auto';
        document.documentElement.setAttribute('data-theme', saved);
        this.updateToggleTitle(saved);
        document.getElementById('theme-toggle').addEventListener('click', () => this.toggle());
    },

    toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        // Cycle: auto → light → dark → auto
        const next = current === 'auto' ? 'light' : current === 'light' ? 'dark' : 'auto';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem(this.STORAGE_KEY, next);
        this.updateToggleTitle(next);
    },

    updateToggleTitle(mode) {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        const labels = { auto: 'Theme: System', light: 'Theme: Light', dark: 'Theme: Dark' };
        btn.title = labels[mode] || labels.auto;
    },
};
