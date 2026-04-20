(function () {
    'use strict';

    // Cycle order: BOTH → OFF → MAP → SPACING → BOTH → ...
    // First press from default (BOTH) goes to OFF, which is what you want when
    // a dialog (e.g. Settings) opens and you need the overlays out of the way.
    const MODES = [
        { name: 'BOTH',    map: true,  spacing: true  },
        { name: 'OFF',     map: false, spacing: false },
        { name: 'MAP',     map: true,  spacing: false },
        { name: 'SPACING', map: false, spacing: true  },
    ];

    let pill = null;
    let pillTimer = 0;
    let styleEl = null;

    function injectStyles() {
        if (styleEl) return;
        styleEl = document.createElement('style');
        styleEl.textContent = `
            .pmc-mode-pill {
                position: fixed;
                top: 14px;
                left: 50%;
                transform: translateX(-50%);
                z-index: 2147483647;
                background: rgba(20, 20, 20, 0.92);
                color: #fff;
                font-family: ui-monospace, Menlo, Consolas, monospace;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.5px;
                padding: 6px 14px;
                border-radius: 999px;
                box-shadow: 0 4px 14px rgba(0,0,0,0.45);
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.15s ease-out;
            }
            .pmc-mode-pill.pmc-show { opacity: 1; }
        `;
        document.head.appendChild(styleEl);
    }

    function topOpenDialog() {
        const dialogs = document.querySelectorAll('dialog[open]');
        let last = null;
        for (const d of dialogs) {
            try { if (d.matches(':modal')) last = d; } catch (_) { last = d; }
        }
        return last;
    }

    function pillParent() { return topOpenDialog() || document.body; }

    function ensurePill() {
        if (pill) return;
        pill = document.createElement('div');
        pill.className = 'pmc-mode-pill';
        pillParent().appendChild(pill);
    }

    function showPill(text) {
        injectStyles();
        ensurePill();
        // Re-parent each time so the pill renders above any open dialog.
        const parent = pillParent();
        if (pill.parentElement !== parent) parent.appendChild(pill);
        // <dialog> has overflow:hidden — switch from fixed to absolute when inside.
        pill.style.position = parent === document.body ? 'fixed' : 'absolute';
        pill.textContent = 'OVERLAY: ' + text;
        // Force reflow so transition replays.
        pill.classList.remove('pmc-show');
        void pill.offsetWidth;
        pill.classList.add('pmc-show');
        if (pillTimer) clearTimeout(pillTimer);
        pillTimer = setTimeout(function () {
            if (pill) pill.classList.remove('pmc-show');
        }, 1200);
    }

    function currentModeIndex() {
        const m = window.__projectMap && window.__projectMap.isActive();
        const s = window.__projectSpacing && window.__projectSpacing.isActive();
        for (let i = 0; i < MODES.length; i++) {
            if (MODES[i].map === !!m && MODES[i].spacing === !!s) return i;
        }
        return 0;
    }

    function applyMode(mode) {
        if (window.__projectMap) {
            mode.map ? window.__projectMap.activate() : window.__projectMap.deactivate();
        }
        if (window.__projectSpacing) {
            mode.spacing ? window.__projectSpacing.activate() : window.__projectSpacing.deactivate();
        }
        showPill(mode.name);
    }

    function cycle() {
        const next = MODES[(currentModeIndex() + 1) % MODES.length];
        applyMode(next);
    }

    document.addEventListener('keydown', function (e) {
        if (e.metaKey && e.shiftKey && (e.key === 'M' || e.key === 'm')) {
            e.preventDefault();
            cycle();
        }
    });

    window.__projectMapCoordinator = { cycle: cycle, applyMode: applyMode, MODES: MODES };
})();
