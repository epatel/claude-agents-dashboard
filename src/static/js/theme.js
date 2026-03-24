const Theme = {
    STORAGE_KEY: 'agents-dashboard-theme',

    init() {
        const saved = localStorage.getItem(this.STORAGE_KEY) || 'auto';
        document.documentElement.setAttribute('data-theme', saved);
        document.getElementById('theme-toggle').addEventListener('click', () => this.toggle());
    },

    toggle() {
        const current = document.documentElement.getAttribute('data-theme');
        let next;
        if (current === 'auto' || current === 'light') {
            // Determine actual current appearance
            const isDark = current === 'dark' ||
                (current === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
            next = isDark ? 'light' : 'dark';
        } else {
            next = 'light';
        }
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem(this.STORAGE_KEY, next);
    },
};
