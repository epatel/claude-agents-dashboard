const Theme = {
    STORAGE_KEY: 'agents-dashboard-theme',
    _mediaQuery: null,

    init() {
        const preference = localStorage.getItem(this.STORAGE_KEY) || 'auto';
        this._applyPreference(preference);
        this.updateToggleTitle(preference);
        document.getElementById('theme-toggle').addEventListener('click', () => this.toggle());

        // Listen for system preference changes (affects auto mode)
        this._mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        this._mediaQuery.addEventListener('change', () => {
            if (this.getPreference() === 'auto') {
                this._applyPreference('auto');
            }
        });
    },

    getPreference() {
        return document.documentElement.getAttribute('data-theme-preference') || 'auto';
    },

    /** Resolve 'auto' to explicit light/dark via matchMedia, then set data-theme */
    _applyPreference(preference) {
        const resolved = this._resolveTheme(preference);
        document.documentElement.setAttribute('data-theme', resolved);
        document.documentElement.setAttribute('data-theme-preference', preference);
    },

    _resolveTheme(preference) {
        if (preference === 'auto') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return preference;
    },

    toggle() {
        const current = this.getPreference();
        // Cycle: light → dark → system → light
        const next = current === 'light' ? 'dark' : current === 'dark' ? 'auto' : 'light';
        this._applyPreference(next);
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
