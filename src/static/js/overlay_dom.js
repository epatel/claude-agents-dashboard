(function () {
    'use strict';

    // DOM helpers shared by the --ui-map overlays (map_overlay.js, spacing_overlay.js,
    // map_coordinator.js). Loaded before them.

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

    // Move ``el`` (if any) into ``parent``. With ``setPosition``, switch it between
    // fixed and absolute: a modal <dialog> has overflow:hidden, which clips
    // fixed-position children to the dialog's box, so inside one the element is
    // positioned against the dialog instead of the viewport.
    function placeIn(el, parent, setPosition) {
        if (!el) return;
        if (el.parentElement !== parent) parent.appendChild(el);
        if (setPosition) el.style.position = parent === document.body ? 'fixed' : 'absolute';
    }

    // The "<MODE> ON" corner badge; clicking it dismisses the overlay.
    function createBadge(className, text, onClick) {
        const badge = document.createElement('div');
        badge.className = className;
        badge.textContent = text;
        badge.title = 'Click to dismiss for this session';
        badge.addEventListener('click', onClick);
        overlayParent().appendChild(badge);
        return badge;
    }

    window.__overlayDom = {
        topOpenDialog: topOpenDialog,
        overlayParent: overlayParent,
        placeIn: placeIn,
        createBadge: createBadge,
    };
})();
