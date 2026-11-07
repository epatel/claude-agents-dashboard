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

    /** A coloured band over ``[left, top, width, height]``. */
    function makeBand(box, bg) {
        const b = document.createElement('div');
        b.className = 'ps-band';
        b.style.left = box[0] + 'px';
        b.style.top = box[1] + 'px';
        b.style.width = Math.max(0, box[2]) + 'px';
        b.style.height = Math.max(0, box[3]) + 'px';
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

    /** One measured band plus its label; ``kind`` is padding / margin / gap. */
    function drawMeasured(kind, box, labelAt, text) {
        layer.appendChild(makeBand(box, COLORS[kind]));
        layer.appendChild(makeLabel(labelAt[0], labelAt[1], text, COLORS[kind + 'Label']));
    }

    /** ``[property, size, band box, label point]`` for each padding and margin side, in draw order. */
    function boxModelBands(rect, cs) {
        const size = function (prop) { return parseFloat(cs[prop]) || 0; };
        const pt = size('paddingTop'), pr = size('paddingRight');
        const pb = size('paddingBottom'), pl = size('paddingLeft');
        const mt = size('marginTop'), mr = size('marginRight');
        const mb = size('marginBottom'), ml = size('marginLeft');
        const left = rect.left, top = rect.top, w = rect.width, h = rect.height;
        return [
            // Padding bands (inside the element)
            ['padding-top', pt, [left, top, w, pt], [left + w / 2, top + pt / 2]],
            ['padding-bottom', pb, [left, top + h - pb, w, pb], [left + w / 2, top + h - pb / 2]],
            ['padding-left', pl, [left, top + pt, pl, h - pt - pb], [left + pl / 2, top + h / 2]],
            ['padding-right', pr, [left + w - pr, top + pt, pr, h - pt - pb], [left + w - pr / 2, top + h / 2]],
            // Margin bands (outside the element)
            ['margin-top', mt, [left, top - mt, w, mt], [left + w / 2, top - mt / 2]],
            ['margin-bottom', mb, [left, top + h, w, mb], [left + w / 2, top + h + mb / 2]],
            ['margin-left', ml, [left - ml, top, ml, h], [left - ml / 2, top + h / 2]],
            ['margin-right', mr, [left + w, top, mr, h], [left + w + mr / 2, top + h / 2]],
        ];
    }

    function drawBoxModel(rect, cs) {
        for (const [prop, size, box, labelAt] of boxModelBands(rect, cs)) {
            if (size > 0) drawMeasured(prop.split('-')[0], box, labelAt, `${prop}: ${px(size)}`);
        }
    }

    const GAP_LAYOUTS = { flex: 'flex', 'inline-flex': 'flex', grid: 'grid', 'inline-grid': 'grid' };

    /**
     * Which gaps to look for: ``{horiz, vert}``, or null when the element is not
     * a flex / grid container with a gap. Wrapping flex containers also get
     * vertical gaps (between wrapped lines).
     */
    function gapAxes(cs) {
        const layout = GAP_LAYOUTS[cs.display];
        if (!layout) return null;

        const rowGap = parseFloat(cs.rowGap) || 0;
        const colGap = parseFloat(cs.columnGap) || 0;
        if (rowGap <= 0 && colGap <= 0) return null;

        if (layout === 'grid') return { horiz: colGap > 0, vert: rowGap > 0 };
        return flexGapAxes(cs, rowGap, colGap);
    }

    function flexGapAxes(cs, rowGap, colGap) {
        const flexDir = (cs.flexDirection || 'row').replace('-reverse', '');
        return {
            horiz: flexDir === 'row' && colGap > 0,
            vert: (flexDir === 'column' && rowGap > 0) || cs.flexWrap !== 'nowrap',
        };
    }

    function visibleChildRects(el) {
        return Array.from(el.children)
            .map(function (c) { return c.getBoundingClientRect(); })
            .filter(function (r) { return r.width > 0 && r.height > 0; });
    }

    /** Horizontal neighbours: same row, ``b`` starts right of ``a``. */
    function drawRowGap(a, b) {
        if (Math.abs(a.top - b.top) >= 1 || b.left <= a.right) return;
        const gw = b.left - a.right;
        drawMeasured('gap', [a.right, a.top, gw, a.height], [a.right + gw / 2, a.top + a.height / 2], `gap: ${px(gw)}`);
    }

    /** Vertical neighbours: ``b`` starts below ``a`` and overlaps its column. */
    function drawColumnGap(a, b) {
        const gh = b.top - a.bottom;
        if (gh <= 0 || Math.abs(a.left - b.left) >= a.width) return;
        drawMeasured('gap', [a.left, a.bottom, a.width, gh], [a.left + a.width / 2, a.bottom + gh / 2], `gap: ${px(gh)}`);
    }

    // Visualize gap by overlaying bands between adjacent visible children.
    // Keep it pragmatic: compare adjacent rects and draw a band where there's a real gap.
    function drawGap(el, cs) {
        const axes = gapAxes(cs);
        if (!axes) return;
        const rects = visibleChildRects(el);
        for (let i = 0; i < rects.length - 1; i++) {
            if (axes.horiz) drawRowGap(rects[i], rects[i + 1]);
            if (axes.vert) drawColumnGap(rects[i], rects[i + 1]);
        }
    }

    /** The badge or anything inside it (``contains`` includes the node itself). */
    function isOnBadge(el) { return badge !== null && badge.contains(el); }

    function render(el) {
        clearLayer();
        if (!el || isOnBadge(el)) return;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        const cs = getComputedStyle(el);
        drawBoxModel(rect, cs);
        drawGap(el, cs);
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
