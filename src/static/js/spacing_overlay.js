(function () {
    'use strict';

    const STORAGE_KEY = 'project-spacing-overlay-active';
    // Default OFF on first load — user cycles to SPACING via Cmd+Shift+M.
    const initial = sessionStorage.getItem(STORAGE_KEY) === '1';

    const COLORS = {
        padding: 'rgba(76, 175, 80, 0.28)',     // green
        paddingLabel: '#2e7d32',
        margin: 'rgba(255, 152, 0, 0.28)',      // orange
        marginLabel: '#e65100',
        gap: 'rgba(33, 150, 243, 0.30)',        // blue
        gapLabel: '#0277bd',
    };

    let active = false;
    let badge = null;
    let layer = null;
    let styleEl = null;
    let lastTarget = null;
    let rafId = 0;

    function injectStyles() {
        if (styleEl) return;
        styleEl = document.createElement('style');
        styleEl.textContent = `
            .ps-overlay-badge {
                position: fixed;
                top: 8px;
                right: 88px;
                z-index: 2147483646;
                background: #2196f3;
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
            .ps-overlay-badge:hover { background: #1e88e5; }
            .ps-layer {
                position: fixed;
                inset: 0;
                pointer-events: none;
                z-index: 2147483645;
            }
            .ps-band {
                position: absolute;
                box-sizing: border-box;
            }
            .ps-label {
                position: absolute;
                font-family: ui-monospace, Menlo, Consolas, monospace;
                font-size: 10px;
                font-weight: 600;
                color: #fff;
                padding: 2px 5px;
                border-radius: 3px;
                white-space: nowrap;
                box-shadow: 0 1px 3px rgba(0,0,0,0.35);
                transform: translate(-50%, -50%);
                pointer-events: none;
            }
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

    function overlayParent() { return topOpenDialog() || document.body; }

    function reparent() {
        const parent = overlayParent();
        const inDialog = parent !== document.body;
        if (badge) {
            if (badge.parentElement !== parent) parent.appendChild(badge);
            badge.style.position = inDialog ? 'absolute' : 'fixed';
        }
        if (layer && layer.parentElement !== parent) parent.appendChild(layer);
    }

    function ensureBadge() {
        if (badge) return;
        badge = document.createElement('div');
        badge.className = 'ps-overlay-badge';
        badge.textContent = 'SPACING ON';
        badge.title = 'Click to dismiss for this session';
        badge.addEventListener('click', deactivate);
        overlayParent().appendChild(badge);
    }

    function ensureLayer() {
        if (layer) return;
        layer = document.createElement('div');
        layer.className = 'ps-layer';
        overlayParent().appendChild(layer);
    }

    function px(n) { return Math.round(n) + 'px'; }

    function clearLayer() {
        if (layer) layer.innerHTML = '';
    }

    function makeBand(left, top, width, height, bg) {
        const b = document.createElement('div');
        b.className = 'ps-band';
        b.style.left = left + 'px';
        b.style.top = top + 'px';
        b.style.width = Math.max(0, width) + 'px';
        b.style.height = Math.max(0, height) + 'px';
        b.style.background = bg;
        return b;
    }

    function makeLabel(cx, cy, text, bg) {
        const l = document.createElement('div');
        l.className = 'ps-label';
        l.textContent = text;
        l.style.left = cx + 'px';
        l.style.top = cy + 'px';
        l.style.background = bg;
        return l;
    }

    function drawBoxModel(rect, cs) {
        const pt = parseFloat(cs.paddingTop) || 0;
        const pr = parseFloat(cs.paddingRight) || 0;
        const pb = parseFloat(cs.paddingBottom) || 0;
        const pl = parseFloat(cs.paddingLeft) || 0;
        const mt = parseFloat(cs.marginTop) || 0;
        const mr = parseFloat(cs.marginRight) || 0;
        const mb = parseFloat(cs.marginBottom) || 0;
        const ml = parseFloat(cs.marginLeft) || 0;

        const left = rect.left, top = rect.top, w = rect.width, h = rect.height;

        // Padding bands (inside the element)
        if (pt > 0) {
            layer.appendChild(makeBand(left, top, w, pt, COLORS.padding));
            layer.appendChild(makeLabel(left + w / 2, top + pt / 2, `padding-top: ${px(pt)}`, COLORS.paddingLabel));
        }
        if (pb > 0) {
            layer.appendChild(makeBand(left, top + h - pb, w, pb, COLORS.padding));
            layer.appendChild(makeLabel(left + w / 2, top + h - pb / 2, `padding-bottom: ${px(pb)}`, COLORS.paddingLabel));
        }
        if (pl > 0) {
            layer.appendChild(makeBand(left, top + pt, pl, h - pt - pb, COLORS.padding));
            layer.appendChild(makeLabel(left + pl / 2, top + h / 2, `padding-left: ${px(pl)}`, COLORS.paddingLabel));
        }
        if (pr > 0) {
            layer.appendChild(makeBand(left + w - pr, top + pt, pr, h - pt - pb, COLORS.padding));
            layer.appendChild(makeLabel(left + w - pr / 2, top + h / 2, `padding-right: ${px(pr)}`, COLORS.paddingLabel));
        }

        // Margin bands (outside the element)
        if (mt > 0) {
            layer.appendChild(makeBand(left, top - mt, w, mt, COLORS.margin));
            layer.appendChild(makeLabel(left + w / 2, top - mt / 2, `margin-top: ${px(mt)}`, COLORS.marginLabel));
        }
        if (mb > 0) {
            layer.appendChild(makeBand(left, top + h, w, mb, COLORS.margin));
            layer.appendChild(makeLabel(left + w / 2, top + h + mb / 2, `margin-bottom: ${px(mb)}`, COLORS.marginLabel));
        }
        if (ml > 0) {
            layer.appendChild(makeBand(left - ml, top, ml, h, COLORS.margin));
            layer.appendChild(makeLabel(left - ml / 2, top + h / 2, `margin-left: ${px(ml)}`, COLORS.marginLabel));
        }
        if (mr > 0) {
            layer.appendChild(makeBand(left + w, top, mr, h, COLORS.margin));
            layer.appendChild(makeLabel(left + w + mr / 2, top + h / 2, `margin-right: ${px(mr)}`, COLORS.marginLabel));
        }
    }

    function drawGap(el, rect, cs) {
        const display = cs.display;
        const isFlex = display === 'flex' || display === 'inline-flex';
        const isGrid = display === 'grid' || display === 'inline-grid';
        if (!isFlex && !isGrid) return;

        const rowGap = parseFloat(cs.rowGap) || 0;
        const colGap = parseFloat(cs.columnGap) || 0;
        if (rowGap <= 0 && colGap <= 0) return;

        // Visualize gap by overlaying bands between adjacent visible children
        const children = Array.from(el.children).filter(function (c) {
            const r = c.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        });
        if (children.length < 2) return;

        const rects = children.map(function (c) { return c.getBoundingClientRect(); });

        // Determine direction(s)
        const flexDir = (cs.flexDirection || 'row').replace('-reverse', '');
        const horiz = isGrid ? colGap > 0 : (flexDir === 'row' && colGap > 0);
        const vert = isGrid ? rowGap > 0 : (flexDir === 'column' && rowGap > 0);

        // For flex-row we also have to consider wrap → row gap between wrapped lines.
        // Keep it pragmatic: compare adjacent rects and draw a band where there's a real gap.
        for (let i = 0; i < rects.length - 1; i++) {
            const a = rects[i];
            const b = rects[i + 1];
            // Horizontal neighbors (same row, adjacent x)
            if (horiz && Math.abs(a.top - b.top) < 1 && b.left > a.right) {
                const gw = b.left - a.right;
                if (gw > 0) {
                    layer.appendChild(makeBand(a.right, a.top, gw, a.height, COLORS.gap));
                    layer.appendChild(makeLabel(a.right + gw / 2, a.top + a.height / 2, `gap: ${px(gw)}`, COLORS.gapLabel));
                }
            }
            // Vertical neighbors (same col, adjacent y)
            if ((vert || (isFlex && cs.flexWrap !== 'nowrap')) && b.top > a.bottom) {
                const gh = b.top - a.bottom;
                if (gh > 0 && Math.abs(a.left - b.left) < a.width) {
                    layer.appendChild(makeBand(a.left, a.bottom, a.width, gh, COLORS.gap));
                    layer.appendChild(makeLabel(a.left + a.width / 2, a.bottom + gh / 2, `gap: ${px(gh)}`, COLORS.gapLabel));
                }
            }
        }
    }

    function render(el) {
        clearLayer();
        if (!el || el === badge || (badge && badge.contains(el))) return;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        const cs = getComputedStyle(el);
        drawBoxModel(rect, cs);
        drawGap(el, rect, cs);
    }

    function onMouseMove(e) {
        if (!active) return;
        reparent();
        const el = e.target;
        if (el === lastTarget) return;
        lastTarget = el;
        if (rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(function () { render(el); });
    }

    function onScrollOrResize() {
        if (!active || !lastTarget) return;
        if (rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(function () { render(lastTarget); });
    }

    function activate() {
        try { sessionStorage.setItem(STORAGE_KEY, '1'); } catch (_) {}
        if (active) return;
        active = true;
        injectStyles();
        ensureBadge();
        ensureLayer();
        document.addEventListener('mousemove', onMouseMove, true);
        document.addEventListener('close', reparent, true);  // <dialog> close bubbles
        window.addEventListener('scroll', onScrollOrResize, true);
        window.addEventListener('resize', onScrollOrResize, true);
        console.log('[project-spacing] overlay ON. Click badge to dismiss.');
    }

    function deactivate() {
        try { sessionStorage.setItem(STORAGE_KEY, '0'); } catch (_) {}
        if (!active) return;
        active = false;
        if (badge) { badge.remove(); badge = null; }
        if (layer) { layer.remove(); layer = null; }
        document.removeEventListener('mousemove', onMouseMove, true);
        document.removeEventListener('close', reparent, true);
        window.removeEventListener('scroll', onScrollOrResize, true);
        window.removeEventListener('resize', onScrollOrResize, true);
        lastTarget = null;
        console.log('[project-spacing] overlay OFF.');
    }

    function toggle() { active ? deactivate() : activate(); }

    window.__projectSpacing = {
        activate: activate,
        deactivate: deactivate,
        toggle: toggle,
        isActive: function () { return active; },
    };

    function start() { if (initial) activate(); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
