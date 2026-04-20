(function () {
    'use strict';

    const STORAGE_KEY = 'project-map-overlay-active';
    // Default OFF on first load — user cycles to MAP via Cmd+Shift+M.
    // sessionStorage persists the last active choice within the tab.
    const initial = sessionStorage.getItem(STORAGE_KEY) === '1';

    let active = false;
    let tooltip = null;
    let badge = null;
    let lastHover = null;
    let styleEl = null;

    function injectStyles() {
        if (styleEl) return;
        styleEl = document.createElement('style');
        styleEl.textContent = `
            .pm-overlay-badge {
                position: fixed;
                top: 8px;
                right: 8px;
                z-index: 2147483646;
                background: #ff5722;
                color: #fff;
                font-family: ui-monospace, Menlo, Consolas, monospace;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
                padding: 5px 10px;
                border-radius: 4px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.35);
                cursor: pointer;
                user-select: none;
            }
            .pm-overlay-badge:hover { background: #f4511e; }
            .pm-overlay-tooltip {
                position: fixed;
                z-index: 2147483647;
                background: #111;
                color: #fff;
                font-family: ui-monospace, Menlo, Consolas, monospace;
                font-size: 12px;
                padding: 5px 9px;
                border-radius: 4px;
                pointer-events: none;
                box-shadow: 0 4px 14px rgba(0,0,0,0.45);
                white-space: nowrap;
                max-width: 90vw;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            [data-map-name].pm-hover {
                outline: 2px dashed #ff5722 !important;
                outline-offset: 1px;
            }
            .pm-overlay-tooltip.pm-flash { background: #2e7d32; }
        `;
        document.head.appendChild(styleEl);
    }

    function topOpenDialog() {
        // Modal <dialog> renders in the browser's top layer and obscures any
        // z-indexed element. Re-parent overlay into it so overlay visuals win.
        const dialogs = document.querySelectorAll('dialog[open]');
        let last = null;
        for (const d of dialogs) {
            try { if (d.matches(':modal')) last = d; } catch (_) { last = d; }
        }
        return last;
    }

    function overlayParent() { return topOpenDialog() || document.body; }

    function reparent() {
        const parent = overlayParent();
        const inDialog = parent !== document.body;
        if (badge) {
            if (badge.parentElement !== parent) parent.appendChild(badge);
            // Modal <dialog> has overflow:hidden which clips fixed-position children
            // to the dialog's box. Switch to absolute so the badge sits at the
            // dialog's top-right (still visible) rather than the viewport's.
            badge.style.position = inDialog ? 'absolute' : 'fixed';
        }
        if (tooltip) {
            if (tooltip.parentElement !== parent) parent.appendChild(tooltip);
            tooltip.style.position = inDialog ? 'absolute' : 'fixed';
        }
    }

    function ensureBadge() {
        if (badge) return;
        badge = document.createElement('div');
        badge.className = 'pm-overlay-badge';
        badge.textContent = 'MAP ON';
        badge.title = 'Click to dismiss for this session';
        badge.addEventListener('click', deactivate);
        overlayParent().appendChild(badge);
    }

    function ensureTooltip() {
        if (tooltip) return;
        tooltip = document.createElement('div');
        tooltip.className = 'pm-overlay-tooltip';
        tooltip.style.display = 'none';
        overlayParent().appendChild(tooltip);
    }

    function findNamedAncestor(el) {
        while (el && el !== document.body) {
            if (el.dataset && el.dataset.mapName) return el;
            el = el.parentElement;
        }
        return null;
    }

    function positionTooltip(clientX, clientY) {
        const margin = 14;
        const w = tooltip.offsetWidth;
        const h = tooltip.offsetHeight;
        let x = clientX + margin;
        let y = clientY + margin;
        if (x + w + 4 > window.innerWidth) x = clientX - w - margin;
        if (y + h + 4 > window.innerHeight) y = clientY - h - margin;
        // When parented to a dialog (position: absolute), translate viewport
        // coords into the dialog's local coord system.
        const parent = tooltip.parentElement;
        if (parent && parent !== document.body) {
            const drect = parent.getBoundingClientRect();
            x -= drect.left;
            y -= drect.top;
        }
        tooltip.style.left = Math.max(4, x) + 'px';
        tooltip.style.top = Math.max(4, y) + 'px';
    }

    function onMouseMove(e) {
        if (!active) return;
        reparent();
        const el = findNamedAncestor(e.target);
        if (lastHover && lastHover !== el) lastHover.classList.remove('pm-hover');
        if (!el || el === badge) {
            tooltip.style.display = 'none';
            lastHover = null;
            return;
        }
        el.classList.add('pm-hover');
        lastHover = el;
        tooltip.textContent = el.dataset.mapName + '  (click to copy)';
        tooltip.style.display = 'block';
        positionTooltip(e.clientX, e.clientY);
    }

    function onClick(e) {
        if (!active) return;
        if (badge && (e.target === badge || badge.contains(e.target))) return;
        const el = findNamedAncestor(e.target);
        if (!el) return;
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        const name = el.dataset.mapName;
        try { navigator.clipboard.writeText(name); } catch (_) {}
        tooltip.textContent = 'copied: ' + name;
        tooltip.classList.add('pm-flash');
        setTimeout(function () { if (tooltip) tooltip.classList.remove('pm-flash'); }, 650);
    }

    function activate() {
        try { sessionStorage.setItem(STORAGE_KEY, '1'); } catch (_) {}
        if (active) return;
        active = true;
        injectStyles();
        ensureBadge();
        ensureTooltip();
        document.addEventListener('mousemove', onMouseMove, true);
        document.addEventListener('click', onClick, true);
        document.addEventListener('close', reparent, true);  // <dialog> close bubbles
        console.log('[project-map] overlay ON. Click badge to dismiss. window.__projectMap.listNames() to enumerate.');
    }

    function deactivate() {
        try { sessionStorage.setItem(STORAGE_KEY, '0'); } catch (_) {}
        if (!active) return;
        active = false;
        if (lastHover) lastHover.classList.remove('pm-hover');
        lastHover = null;
        if (badge) { badge.remove(); badge = null; }
        if (tooltip) { tooltip.remove(); tooltip = null; }
        document.removeEventListener('mousemove', onMouseMove, true);
        document.removeEventListener('click', onClick, true);
        document.removeEventListener('close', reparent, true);
        console.log('[project-map] overlay OFF.');
    }

    function toggle() { active ? deactivate() : activate(); }

    function listNames() {
        const els = document.querySelectorAll('[data-map-name]');
        const names = Array.from(els).map(function (el) { return el.dataset.mapName; }).sort();
        console.table(names);
        return names;
    }

    window.__projectMap = {
        activate: activate,
        deactivate: deactivate,
        toggle: toggle,
        listNames: listNames,
        isActive: function () { return active; },
    };

    function start() { if (initial) activate(); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
