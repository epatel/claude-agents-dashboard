// To enable debugging: window.ANNOTATE_DEBUG = true; in browser console
const Annotate = {
    canvas: null,
    ctx: null,
    // Layers: background images and annotations
    images: [],       // {img, x, y, w, h, selected}
    annotations: [],  // {type, ...props, selected}
    tool: 'select',   // select, arrow, circle, rect, text, freehand
    color: '#ff3b30',
    fillColor: null,  // null = no fill; set to a color string to fill shapes
    lineWidth: 3,
    fontSize: 16,
    textBackground: false,
    drawOnImage: false, // When true, drawings are baked into the image layer (not annotations)

    // Interaction state
    _dragging: null,
    _drawing: null,
    _resizing: null,
    _startX: 0,
    _startY: 0,
    _offsetX: 0,
    _offsetY: 0,

    init(canvasEl) {
        this.canvas = canvasEl;
        this.ctx = canvasEl.getContext('2d');
        this.images = [];
        this.annotations = [];
        this.tool = 'select';
        this.drawOnImage = false;
        const drawOnImageCb = document.getElementById('annotate-draw-on-image');
        if (drawOnImageCb) drawOnImageCb.checked = false;
        this._ensurePasteShim();
        this._setupEvents();
        this.render();
        // Move focus to the paste shim so Cmd/Ctrl+V is dispatched against an
        // editable target — that suppresses Safari/Chrome's "Paste" permission
        // overlay that otherwise appears over the canvas on macOS.
        this.focusPasteTarget();

        // Opt-in debugging: set window.ANNOTATE_DEBUG = true in the console.
        if (window.ANNOTATE_DEBUG) console.log('Annotate canvas initialized, debugging enabled');
    },

    // Hidden contenteditable element that owns keyboard focus while the
    // annotate dialog is open. Browsers only fire paste events silently when
    // the target is editable; an unfocused or non-editable focus target
    // (a <canvas>) triggers the macOS "Paste" permission button overlay.
    _ensurePasteShim() {
        if (this._pasteShim && document.contains(this._pasteShim)) return;
        const wrap = this.canvas.closest('.annotate-canvas-wrap') || this.canvas.parentElement;
        if (!wrap) return;
        wrap.style.position = wrap.style.position || 'relative';
        const shim = document.createElement('div');
        shim.id = 'annotate-paste-shim';
        shim.contentEditable = 'true';
        shim.setAttribute('aria-hidden', 'true');
        shim.setAttribute('spellcheck', 'false');
        shim.style.cssText = [
            'position:absolute',
            'left:0', 'top:0',
            'width:1px', 'height:1px',
            'opacity:0',
            'pointer-events:none',
            'outline:none',
            'overflow:hidden',
            'white-space:nowrap',
            'caret-color:transparent',
            'user-select:none',
            '-webkit-user-select:none',
        ].join(';');
        wrap.appendChild(shim);

        // Delete/Backspace removes selected images/annotations.
        shim.addEventListener('keydown', (e) => {
            if (e.key === 'Delete' || e.key === 'Backspace') {
                this._deleteSelected && this._deleteSelected();
                e.preventDefault();
            }
        });
        // Stop the contenteditable from accumulating any pasted/typed content.
        const sweep = () => { if (shim.firstChild) shim.textContent = ''; };
        shim.addEventListener('input', sweep);
        shim.addEventListener('paste', () => setTimeout(sweep, 0));
        this._pasteShim = shim;
    },

    // Public: focus the shim so a subsequent Cmd/Ctrl+V is treated as a
    // regular paste on an editable element (no permission overlay).
    focusPasteTarget() {
        if (!this._pasteShim) this._ensurePasteShim();
        if (this._pasteShim) {
            this._pasteShim.textContent = '';
            try { this._pasteShim.focus({ preventScroll: true }); } catch (_) { this._pasteShim.focus(); }
        }
    },

    clear() {
        this.images = [];
        this.annotations = [];
        this.render();
    },

    cleanup() {
        // Close any open text editor
        this._closeTextEditor(false);
        // Remove document-level event listener to prevent memory leaks
        if (this._pasteHandler) {
            document.removeEventListener('paste', this._pasteHandler);
            this._pasteHandler = null;
        }
        // Remove the paste shim (recreated on next init).
        if (this._pasteShim && this._pasteShim.parentNode) {
            this._pasteShim.parentNode.removeChild(this._pasteShim);
        }
        this._pasteShim = null;
        this._eventsAttached = false;
    },

    // Enhanced dialog detection that works across different browsers and states
    _isAnnotateDialogOpen() {
        const dialog = document.getElementById('annotate-dialog');
        if (!dialog) {
            if (window.ANNOTATE_DEBUG) console.log('Paste: Dialog element not found');
            return false;
        }

        // Check multiple ways the dialog could be open
        const isOpen = dialog.open ||
                      dialog.hasAttribute('open') ||
                      (dialog.style.display !== 'none' && dialog.style.display !== '') ||
                      dialog.offsetParent !== null ||
                      getComputedStyle(dialog).display !== 'none';

        if (window.ANNOTATE_DEBUG) {
            console.log('Dialog state check:', {
                element: !!dialog,
                open: dialog.open,
                hasOpenAttr: dialog.hasAttribute('open'),
                styleDisplay: dialog.style.display,
                offsetParent: !!dialog.offsetParent,
                computedDisplay: getComputedStyle(dialog).display,
                finalIsOpen: isOpen
            });
        }

        return isOpen;
    },

    // Manual paste function that can be called by a button
    async pasteFromClipboard() {
        if (window.ANNOTATE_DEBUG) console.log('Manual paste triggered');

        try {
            // Modern Clipboard API only
            if (!(navigator.clipboard && navigator.clipboard.read)) {
                this._showPasteMessage('Clipboard access not available. Use Ctrl+V or drag and drop instead.');
                return false;
            }
            if (window.ANNOTATE_DEBUG) console.log('Using modern Clipboard API');
            const blob = await this._firstClipboardImage(await navigator.clipboard.read());
            if (blob) {
                this._processPastedImage(blob);
                return true;
            }
            this._showPasteMessage('No images found in clipboard. Copy an image first.');
            return false;
        } catch (error) {
            if (window.ANNOTATE_DEBUG) console.log('Clipboard API failed:', error);

            // Fall back to instructing user to use Ctrl+V
            this._showPasteMessage('Click here and press Ctrl+V (or Cmd+V) to paste image');

            // Focus the editable paste shim so the next Cmd/Ctrl+V is treated
            // as a regular paste (no permission overlay).
            this.focusPasteTarget();
            return false;
        }
    },

    /** The first image blob among Clipboard API items, or null. */
    async _firstClipboardImage(clipboardItems) {
        for (const item of clipboardItems) {
            if (window.ANNOTATE_DEBUG) console.log('Clipboard item types:', Array.from(item.types));
            const type = Array.from(item.types).find(t => t.startsWith('image/'));
            if (type) return item.getType(type);
        }
        return null;
    },

    // Show a temporary message to the user
    _showPasteMessage(message, duration = 3000) {
        // Remove any existing message
        const existing = document.getElementById('paste-message');
        if (existing) existing.remove();

        // Create message element
        const msgEl = document.createElement('div');
        msgEl.id = 'paste-message';
        msgEl.textContent = message;
        msgEl.style.cssText = `
            position: absolute;
            top: 10px;
            left: 50%;
            transform: translateX(-50%);
            background: #333;
            color: white;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 12px;
            z-index: 1000;
            pointer-events: none;
        `;

        // Add to canvas container
        const canvasWrap = document.querySelector('.annotate-canvas-wrap');
        if (canvasWrap) {
            canvasWrap.style.position = 'relative';
            canvasWrap.appendChild(msgEl);

            // Auto remove after duration
            setTimeout(() => {
                if (msgEl.parentNode) {
                    msgEl.remove();
                }
            }, duration);
        }
    },

    _setupEvents() {
        const c = this.canvas;

        // Prevent duplicate listeners on repeated init() calls
        if (this._eventsAttached) return;
        this._eventsAttached = true;

        c.addEventListener('mousedown', (e) => this._onMouseDown(e));
        c.addEventListener('mousemove', (e) => this._onMouseMove(e));
        c.addEventListener('mouseup', (e) => this._onMouseUp(e));
        c.addEventListener('dblclick', (e) => this._onDblClick(e));

        // Drop images
        c.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
        c.addEventListener('drop', (e) => this._onDrop(e));

        this._installPasteHandler();

        // Mouse wheel to scale selected image
        c.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });

        c.setAttribute('tabindex', '0');
        c.addEventListener('keydown', (e) => {
            if (e.key === 'Delete' || e.key === 'Backspace') {
                this._deleteSelected();
                e.preventDefault();
            }
            // Don't intercept Ctrl+V / Cmd+V — let the browser dispatch a native
            // paste event so the document `paste` listener (above) reads
            // clipboardData directly. Calling navigator.clipboard.read() here
            // triggers the browser's "Paste" permission button overlay.
        });

        // Also listen for paste events directly on the canvas
        c.addEventListener('paste', (e) => {
            if (this._isAnnotateDialogOpen()) {
                this._onPaste(e);
            }
        });

        // Focus the hidden paste shim (not the canvas) so Cmd/Ctrl+V targets
        // an editable element and the browser does NOT show the "Paste"
        // permission button overlay over the canvas.
        c.addEventListener('mousedown', () => {
            if (!this._activeTextEditor) this.focusPasteTarget();
        });
        c.addEventListener('click', () => {
            if (!this._activeTextEditor) this.focusPasteTarget();
        });
    },

    // Paste images — listen on document because canvas elements don't
    // reliably receive paste events, even when focused.
    _installPasteHandler() {
        // Remove any existing paste listener to prevent duplicates
        if (this._pasteHandler) {
            document.removeEventListener('paste', this._pasteHandler);
        }
        this._pasteHandler = (e) => {
            // Only handle paste when the annotate dialog is open
            if (!this._isAnnotateDialogOpen()) {
                if (window.ANNOTATE_DEBUG) console.log('Paste: Dialog not open');
                return;
            }

            if (window.ANNOTATE_DEBUG) console.log('Paste: Processing image from clipboard');
            this._onPaste(e);
        };
        document.addEventListener('paste', this._pasteHandler);
    },

    /** Scale the selected image around the mouse position. */
    _onWheel(e) {
        const sel = this.images.find(i => i.selected);
        if (!sel) return;
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.08 : 0.92;
        const p = this._pos(e);
        const oldW = sel.w, oldH = sel.h;
        sel.w *= factor;
        sel.h *= factor;
        sel.x -= (sel.w - oldW) * ((p.x - sel.x) / oldW);
        sel.y -= (sel.h - oldH) * ((p.y - sel.y) / oldH);
        this.render();
    },

    _pos(e) {
        const r = this.canvas.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    },

    // --- Drop images ---

    _onDrop(e) {
        e.preventDefault();
        const files = e.dataTransfer.files;
        for (const file of files) {
            if (!file.type.startsWith('image/')) continue;
            const reader = new FileReader();
            reader.onload = (ev) => {
                const img = new Image();
                img.onload = () => {
                    // Scale to fit canvas width if needed
                    let w = img.width, h = img.height;
                    const maxW = this.canvas.width * 0.8;
                    if (w > maxW) {
                        const scale = maxW / w;
                        w *= scale;
                        h *= scale;
                    }
                    const pos = this._pos(e);
                    this.images.push({
                        img, x: pos.x - w / 2, y: pos.y - h / 2,
                        w, h, selected: false,
                    });
                    this.render();
                };
                img.src = ev.target.result;
            };
            reader.readAsDataURL(file);
        }
    },

    // --- Paste images ---

    _onPaste(e) {
        e.preventDefault();
        if (window.ANNOTATE_DEBUG) console.log('_onPaste called');

        const items = e.clipboardData?.items;
        if (!items) {
            if (window.ANNOTATE_DEBUG) console.log('No clipboard items found');
            this._showPasteMessage('No clipboard data found');
            return;
        }

        if (window.ANNOTATE_DEBUG) console.log(`Found ${items.length} clipboard items`);

        const file = this._firstImageFile(items);
        if (file) {
            this._processPastedImage(file); // Only handle the first image
        } else {
            this._showPasteMessage('No images found in clipboard. Copy an image first.');
        }
    },

    /** The first clipboard item that is an image and yields a file, or null. */
    _firstImageFile(items) {
        for (const item of items) {
            if (window.ANNOTATE_DEBUG) console.log('Item type:', item.type);
            if (!item.type.startsWith('image/')) continue;
            const file = item.getAsFile();
            if (file) return file;
            if (window.ANNOTATE_DEBUG) console.log('Failed to get file from item');
        }
        return null;
    },

    // Common function to process pasted images (from clipboard events or API)
    _processPastedImage(file) {
        if (window.ANNOTATE_DEBUG) console.log('Processing pasted image:', file.name || 'unnamed', file.type, file.size || file.size);

        const reader = new FileReader();
        reader.onload = (ev) => {
            if (window.ANNOTATE_DEBUG) console.log('FileReader loaded image data');
            const img = new Image();
            img.onload = () => {
                if (window.ANNOTATE_DEBUG) console.log('Image loaded:', img.width, 'x', img.height);

                // Scale to fit canvas width if needed
                let w = img.width, h = img.height;
                const maxW = this.canvas.width * 0.8;
                const maxH = this.canvas.height * 0.8;

                if (w > maxW || h > maxH) {
                    const scaleW = maxW / w;
                    const scaleH = maxH / h;
                    const scale = Math.min(scaleW, scaleH);
                    w *= scale;
                    h *= scale;
                }

                // Center the pasted image on canvas
                const centerX = this.canvas.width / 2;
                const centerY = this.canvas.height / 2;

                // Deselect all existing items
                this.images.forEach(im => im.selected = false);
                this.annotations.forEach(a => a.selected = false);

                // Add the new image (selected)
                this.images.push({
                    img,
                    x: centerX - w / 2,
                    y: centerY - h / 2,
                    w, h, selected: true,
                });

                this.render();
                this._showPasteMessage('Image pasted successfully!', 2000);

                if (window.ANNOTATE_DEBUG) console.log('Image successfully pasted and rendered');
            };
            img.onerror = (err) => {
                if (window.ANNOTATE_DEBUG) console.error('Image loading error:', err);
                this._showPasteMessage('Error loading pasted image');
            };
            img.src = ev.target.result;
        };
        reader.onerror = (err) => {
            if (window.ANNOTATE_DEBUG) console.error('FileReader error:', err);
            this._showPasteMessage('Error reading pasted image');
        };
        reader.readAsDataURL(file);
    },

    // --- Mouse handlers ---

    _onMouseDown(e) {
        // If a text editor is open, close it on any canvas click
        if (this._activeTextEditor) {
            e.stopPropagation();
            this._closeTextEditor(true);
            return;
        }

        const p = this._pos(e);
        this._startX = p.x;
        this._startY = p.y;

        // Don't focus paste shim when about to open text editor (it steals textarea focus).
        // Use the editable shim — not the canvas — so Cmd/Ctrl+V doesn't trigger
        // the browser's "Paste" permission overlay over the canvas.
        if (this.tool !== 'text') {
            this.focusPasteTarget();
        }

        if (this.tool === 'select') {
            this._selectAt(p);
        } else if (this.tool === 'text') {
            e.stopPropagation();
            this._openTextEditor(p.x, p.y, null);
        } else if (this.tool === 'freehand') {
            this._drawing = { type: 'freehand', points: [{ x: p.x, y: p.y }] };
        } else {
            // Include fillColor for the live preview
            this._drawing = { type: this.tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y, fillColor: this.fillColor };
        }
    },

    /** Select tool: grab a resize handle, else select and start dragging what's under p. */
    _selectAt(p) {
        // Check resize handles on the selected image first
        const selImg = this.images.find(i => i.selected);
        const handle = selImg && this._hitHandle(selImg, p.x, p.y);
        if (handle) {
            this._resizing = { img: selImg, handle };
            return;
        }

        // Annotations sit above images
        this._deselectAll();
        const target = this._hitAnnotation(p.x, p.y) || this._hitImage(p.x, p.y);
        if (target) {
            target.selected = true;
            this._dragging = target;
            this._offsetX = p.x - (target.x || target.x1 || 0);
            this._offsetY = p.y - (target.y || target.y1 || 0);
        }
        this.render();
    },

    _onMouseMove(e) {
        const p = this._pos(e);
        if (this._resizing) {
            this._resizeImage(this._resizing, p);
            this.render();
        } else if (this._dragging) {
            this._dragTo(this._dragging, p);
            this.render();
        } else if (this._drawing) {
            if (this._drawing.type === 'freehand') {
                this._drawing.points.push({ x: p.x, y: p.y });
            } else {
                this._drawing.x2 = p.x;
                this._drawing.y2 = p.y;
            }
            this.render();
            this._drawShape(this._drawing);
        }
    },

    /** Drag a corner handle, keeping the aspect ratio and the opposite corner fixed. */
    _resizeImage({ img, handle }, p) {
        const aspect = img.img.width / img.img.height;
        const west = handle.endsWith('w');
        const north = handle.startsWith('n');
        const newW = Math.max(30, west ? (img.x + img.w) - p.x : p.x - img.x);
        const newH = newW / aspect;
        if (west) img.x = img.x + img.w - newW;
        if (north) img.y = img.y + img.h - newH;
        img.w = newW;
        img.h = newH;
    },

    /** Images and text follow the grab offset; other shapes move by the mouse delta. */
    _dragTo(d, p) {
        if (d.img || d.type === 'text') {
            d.x = p.x - this._offsetX;
            d.y = p.y - this._offsetY;
            return;
        }
        this._moveShape(d, p.x - this._startX, p.y - this._startY);
        this._startX = p.x;
        this._startY = p.y;
    },

    _moveShape(d, dx, dy) {
        if (d.type === 'arrow') {
            d.x1 += dx; d.y1 += dy;
            d.x2 += dx; d.y2 += dy;
            return;
        }
        if (d.type === 'freehand') {
            for (const pt of d.points) { pt.x += dx; pt.y += dy; }
        }
        d.x += dx; d.y += dy;  // freehand bounds, circle centre, rect corner
    },

    _onMouseUp(e) {
        if (this._resizing) {
            this._resizing = null;
            this.render();
            return;
        }
        if (this._drawing) {
            const shape = this._shapeFromDrawing(this._drawing);
            if (shape) this.annotations.push(this._styledAnnotation(shape));
            this._drawing = null;
            this.render();
        }
        this._dragging = null;
    },

    /** The annotation geometry for a finished drawing, or null if it is too small. */
    _shapeFromDrawing(d) {
        if (d.type === 'freehand') {
            // Simplify and save freehand path if it has enough points
            if (d.points.length <= 2) return null;
            const points = this._simplifyPoints(d.points, 2);
            const bounds = this._getPointsBounds(points);
            return { type: 'freehand', points, x: bounds.x, y: bounds.y, w: bounds.w, h: bounds.h };
        }
        const dx = Math.abs(d.x2 - d.x1);
        const dy = Math.abs(d.y2 - d.y1);
        if (dx <= 5 && dy <= 5) return null;
        switch (d.type) {
            case 'arrow': return { type: 'arrow', x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2 };
            case 'circle': return { type: 'circle', x: (d.x1 + d.x2) / 2, y: (d.y1 + d.y2) / 2, rx: dx / 2, ry: dy / 2 };
            case 'rect': return { type: 'rect', x: Math.min(d.x1, d.x2), y: Math.min(d.y1, d.y2), w: dx, h: dy };
            default: return null;
        }
    },

    /** Add the current colour / width / layer (and fill, for circles and rects). */
    _styledAnnotation(shape) {
        const fill = (shape.type === 'circle' || shape.type === 'rect') ? { fillColor: this.fillColor } : {};
        return {
            ...shape, color: this.color, ...fill,
            lineWidth: this.lineWidth, selected: false, layer: this._drawLayer(),
        };
    },

    /** New drawings go on the image layer when "draw on image" is checked. */
    _drawLayer() {
        return this.drawOnImage ? 'image' : 'annotation';
    },

    _onDblClick(e) {
        if (this.tool === 'text' || this.tool === 'select') {
            e.stopPropagation();
            const p = this._pos(e);
            // Check if double-clicking an existing text annotation to edit it
            const hitText = this.annotations.find(a =>
                a.type === 'text' && this._hitTextBounds(a, p.x, p.y)
            );
            if (hitText) {
                this._openTextEditor(hitText.x, hitText.y, hitText);
            } else if (this.tool === 'text') {
                this._openTextEditor(p.x, p.y, null);
            }
        }
    },

    _hitTextBounds(a, x, y) {
        const { maxWidth, totalHeight } = this._measureText(a);
        return x >= a.x && x <= a.x + maxWidth && y >= a.y && y <= a.y + totalHeight;
    },

    /** Set the text annotation's font on the context and measure its lines. */
    _measureText(a) {
        const fontSize = a.fontSize || this.fontSize;
        const lineHeight = fontSize * 1.3;
        const lines = (a.text || '').split('\n');
        this.ctx.font = `${fontSize}px sans-serif`;
        let maxWidth = 0;
        for (const line of lines) {
            maxWidth = Math.max(maxWidth, this.ctx.measureText(line).width);
        }
        return { lines, lineHeight, maxWidth, totalHeight: lines.length * lineHeight };
    },

    _openTextEditor(canvasX, canvasY, existingAnnotation) {
        // Remove any existing text editor
        this._closeTextEditor(false);

        const canvasRect = this.canvas.getBoundingClientRect();
        const fontSize = existingAnnotation?.fontSize || this.fontSize;
        const withBg = existingAnnotation ? (existingAnnotation.fillColor || existingAnnotation.background) : this.fillColor;

        const textarea = document.createElement('textarea');
        textarea.className = 'annotate-text-editor';
        textarea.value = existingAnnotation?.text || '';
        // Position relative to canvas within .annotate-canvas-wrap
        const offsetX = this.canvas.offsetLeft + canvasX;
        const offsetY = this.canvas.offsetTop + canvasY;
        textarea.style.cssText = `
            position: absolute;
            left: ${offsetX}px;
            top: ${offsetY}px;
            font-size: ${fontSize}px;
            font-family: sans-serif;
            color: ${existingAnnotation?.color || this.color};
            background: ${this._textEditorBackground(withBg)};
            border: 1px dashed #0071e3;
            outline: none;
            padding: 2px 4px;
            min-width: 60px;
            min-height: ${fontSize + 8}px;
            resize: none;
            overflow: hidden;
            z-index: 100;
            line-height: 1.3;
            white-space: pre;
        `;

        // Auto-grow the textarea
        const autoGrow = () => {
            textarea.style.height = 'auto';
            textarea.style.height = textarea.scrollHeight + 'px';
            textarea.style.width = 'auto';
            textarea.style.width = Math.max(60, textarea.scrollWidth + 10) + 'px';
        };

        textarea.addEventListener('input', autoGrow);

        // Prevent clicks on textarea from closing the dialog
        textarea.addEventListener('click', (e) => e.stopPropagation());
        textarea.addEventListener('mousedown', (e) => e.stopPropagation());

        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                this._closeTextEditor(false);
            }
            // Allow Enter for new lines (no special handling needed)
        });

        // Click-outside is handled by _onMouseDown on the canvas.
        // No document-level listener needed.

        // Store editor state
        this._activeTextEditor = {
            textarea,
            canvasX,
            canvasY,
            existingAnnotation,
            fontSize,
            withBg,
        };

        // Add to canvas wrapper so click events don't escape to the dialog backdrop
        const canvasWrap = this.canvas.closest('.annotate-canvas-wrap') || this.canvas.parentElement;
        canvasWrap.style.position = 'relative';
        canvasWrap.appendChild(textarea);

        // Focus after a tick to win over any canvas click/focus events
        setTimeout(() => {
            textarea.focus();
            autoGrow();
        }, 0);
    },

    /** A colour string, white for the legacy boolean ``background``, or transparent. */
    _textEditorBackground(withBg) {
        if (!withBg) return 'transparent';
        return typeof withBg === 'string' ? withBg : 'rgba(255,255,255,0.95)';
    },

    _closeTextEditor(save) {
        if (!this._activeTextEditor) return;

        const { textarea, canvasX, canvasY, existingAnnotation, fontSize, withBg } = this._activeTextEditor;
        const text = textarea.value.trim();

        if (save && text) {
            if (existingAnnotation) {
                // Update existing annotation
                existingAnnotation.text = text;
                existingAnnotation.fontSize = fontSize;
            } else {
                // Create new annotation
                this.annotations.push({
                    type: 'text', x: canvasX, y: canvasY, text,
                    color: this.color, fontSize,
                    fillColor: withBg || null, selected: false,
                    layer: this._drawLayer(),
                });
            }
            this.render();
        }

        // Cleanup
        textarea.remove();
        this._activeTextEditor = null;
        // Return focus to the paste shim (not canvas) to keep Cmd/Ctrl+V working
        // without showing the browser's "Paste" permission overlay.
        this.focusPasteTarget();
    },

    // --- Hit testing ---

    _hitImage(x, y) {
        for (let i = this.images.length - 1; i >= 0; i--) {
            const im = this.images[i];
            if (this._inBox(x, y, im, 0)) return im;
        }
        return null;
    },

    _hitHandle(im, x, y) {
        const hs = 7; // handle size
        const corners = {
            nw: { x: im.x, y: im.y },
            ne: { x: im.x + im.w, y: im.y },
            sw: { x: im.x, y: im.y + im.h },
            se: { x: im.x + im.w, y: im.y + im.h },
        };
        for (const [name, c] of Object.entries(corners)) {
            if (Math.abs(x - c.x) < hs && Math.abs(y - c.y) < hs) return name;
        }
        return null;
    },

    _drawHandles(im) {
        const ctx = this.ctx;
        const hs = 5;
        ctx.fillStyle = '#0071e3';
        const corners = [
            [im.x, im.y], [im.x + im.w, im.y],
            [im.x, im.y + im.h], [im.x + im.w, im.y + im.h],
        ];
        for (const [cx, cy] of corners) {
            ctx.fillRect(cx - hs, cy - hs, hs * 2, hs * 2);
        }
    },

    _hitAnnotation(x, y) {
        for (let i = this.annotations.length - 1; i >= 0; i--) {
            const a = this.annotations[i];
            const hit = this._annotationHits[a.type];
            if (hit && hit.call(this, a, x, y)) return a;
        }
        return null;
    },

    /** Per-type hit tests, called with ``this`` = Annotate. */
    _annotationHits: {
        text(a, x, y) {
            return this._hitTextBounds(a, x, y);
        },
        arrow(a, x, y) {
            return this._distToLine({ x, y }, { x: a.x1, y: a.y1 }, { x: a.x2, y: a.y2 }) < 10;
        },
        circle(a, x, y) {
            const dx = (x - a.x) / a.rx, dy = (y - a.y) / a.ry;
            const d = Math.sqrt(dx * dx + dy * dy);
            return a.fillColor ? d <= 1.1 : Math.abs(d - 1) < 0.2;
        },
        rect(a, x, y) {
            // Filled: anywhere inside; stroke-only: on the border
            const near = this._inBox(x, y, a, 5);
            return a.fillColor ? near : near && !this._inBox(x, y, a, -5);
        },
        freehand(a, x, y) {
            // Distance to each line segment
            const p = { x, y };
            for (let j = 0; j < a.points.length - 1; j++) {
                if (this._distToLine(p, a.points[j], a.points[j + 1]) < 10) return true;
            }
            return false;
        },
    },

    /** Is (x, y) inside box {x, y, w, h} grown by ``pad`` on every side (negative shrinks)? */
    _inBox(x, y, box, pad) {
        return x >= box.x - pad && x <= box.x + box.w + pad
            && y >= box.y - pad && y <= box.y + box.h + pad;
    },

    /** Distance from point p to the segment a–b. */
    _distToLine(p, a, b) {
        const A = p.x - a.x, B = p.y - a.y, C = b.x - a.x, D = b.y - a.y;
        const dot = A * C + B * D;
        const lenSq = C * C + D * D;
        let t = lenSq ? dot / lenSq : -1;
        t = Math.max(0, Math.min(1, t));
        const dx = p.x - (a.x + t * C), dy = p.y - (a.y + t * D);
        return Math.sqrt(dx * dx + dy * dy);
    },

    _deselectAll() {
        this.images.forEach(i => i.selected = false);
        this.annotations.forEach(a => a.selected = false);
    },

    _deleteSelected() {
        this.images = this.images.filter(i => !i.selected);
        this.annotations = this.annotations.filter(a => !a.selected);
        this.render();
    },

    // --- Rendering ---

    render() {
        this._drawCheckerboard();
        for (const im of this.images) this._drawImage(im);

        // Image-layer annotations (drawn "on" the image), then annotation-layer
        // shapes, then annotation-layer text on top to prevent overlap.
        const passes = [
            a => a.layer === 'image',
            a => a.layer !== 'image' && a.type !== 'text',
            a => a.layer !== 'image' && a.type === 'text',
        ];
        for (const inPass of passes) {
            for (const a of this.annotations) {
                if (inPass(a)) this._drawAnnotation(a);
            }
        }

        // Draw in-progress shape
        if (this._drawing) {
            this._drawShape(this._drawing);
        }
    },

    _drawCheckerboard() {
        const ctx = this.ctx;
        const c = this.canvas;
        ctx.clearRect(0, 0, c.width, c.height);
        ctx.fillStyle = '#f0f0f0';
        ctx.fillRect(0, 0, c.width, c.height);
        const sz = 16;
        ctx.fillStyle = '#e0e0e0';
        for (let y = 0; y < c.height; y += sz) {
            for (let x = 0; x < c.width; x += sz) {
                if ((Math.floor(x / sz) + Math.floor(y / sz)) % 2) ctx.fillRect(x, y, sz, sz);
            }
        }
    },

    /** A background image, with a dashed frame and resize handles when selected. */
    _drawImage(im) {
        const ctx = this.ctx;
        ctx.drawImage(im.img, im.x, im.y, im.w, im.h);
        if (!im.selected) return;
        ctx.strokeStyle = '#0071e3';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(im.x - 2, im.y - 2, im.w + 4, im.h + 4);
        ctx.setLineDash([]);
        this._drawHandles(im);
    },

    /** An annotation, with dashed selection bounds when selected. */
    _drawAnnotation(a) {
        const ctx = this.ctx;
        this._drawShape(a);
        if (!a.selected) return;
        ctx.strokeStyle = '#0071e3';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        this._drawSelectionBounds(a);
        ctx.setLineDash([]);
    },

    _drawSelectionBounds(a) {
        const ctx = this.ctx;
        if (a.type === 'arrow') {
            ctx.strokeRect(Math.min(a.x1, a.x2) - 5, Math.min(a.y1, a.y2) - 5,
                Math.abs(a.x2 - a.x1) + 10, Math.abs(a.y2 - a.y1) + 10);
        } else if (a.type === 'circle') {
            ctx.strokeRect(a.x - a.rx - 3, a.y - a.ry - 3, a.rx * 2 + 6, a.ry * 2 + 6);
        } else if (a.type === 'rect' || a.type === 'freehand') {
            ctx.strokeRect(a.x - 3, a.y - 3, a.w + 6, a.h + 6);
        } else if (a.type === 'text') {
            const { maxWidth, totalHeight } = this._measureText(a);
            const padding = 2;
            ctx.strokeRect(a.x - padding, a.y - padding, maxWidth + padding * 2, totalHeight + padding * 2);
        }
    },

    _drawShape(s) {
        const ctx = this.ctx;
        ctx.strokeStyle = s.color || this.color;
        ctx.fillStyle = s.color || this.color;
        ctx.lineWidth = s.lineWidth || this.lineWidth;
        ctx.setLineDash([]);
        const paint = this._shapePainters[s.type];
        if (paint) paint.call(this, ctx, s);
    },

    /**
     * Per-type painters, called with ``this`` = Annotate. Circles and rects take
     * either finished geometry (x/y/rx/ry, x/y/w/h) or an in-progress drag (x1..y2).
     */
    _shapePainters: {
        arrow(ctx, s) {
            const { x1, y1, x2, y2 } = s;
            const angle = Math.atan2(y2 - y1, x2 - x1);
            const headLen = 10 + (s.lineWidth || this.lineWidth) * 2;
            const headHalf = 0.4;
            // Shorten the line so it stops just inside the arrowhead
            const overlap = headLen * 0.3;
            const baseX = x2 - (headLen - overlap) * Math.cos(angle);
            const baseY = y2 - (headLen - overlap) * Math.sin(angle);
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(baseX, baseY);
            ctx.stroke();
            // Arrowhead as a filled triangle from tip
            ctx.beginPath();
            ctx.moveTo(x2, y2);
            ctx.lineTo(x2 - headLen * Math.cos(angle - headHalf), y2 - headLen * Math.sin(angle - headHalf));
            ctx.lineTo(x2 - headLen * Math.cos(angle + headHalf), y2 - headLen * Math.sin(angle + headHalf));
            ctx.closePath();
            ctx.fill();
        },
        circle(ctx, s) {
            const cx = s.x ?? (s.x1 + s.x2) / 2;
            const cy = s.y ?? (s.y1 + s.y2) / 2;
            const rx = s.rx ?? Math.abs(s.x2 - s.x1) / 2;
            const ry = s.ry ?? Math.abs(s.y2 - s.y1) / 2;
            ctx.beginPath();
            ctx.ellipse(cx, cy, Math.max(rx, 1), Math.max(ry, 1), 0, 0, Math.PI * 2);
            if (s.fillColor) {
                ctx.fillStyle = s.fillColor;
                ctx.fill();
            }
            ctx.stroke();
        },
        rect(ctx, s) {
            const x = s.x ?? Math.min(s.x1, s.x2);
            const y = s.y ?? Math.min(s.y1, s.y2);
            const w = s.w ?? Math.abs(s.x2 - s.x1);
            const h = s.h ?? Math.abs(s.y2 - s.y1);
            if (s.fillColor) {
                ctx.fillStyle = s.fillColor;
                ctx.fillRect(x, y, w, h);
            }
            ctx.strokeRect(x, y, w, h);
        },
        freehand(ctx, s) {
            if (!s.points || s.points.length <= 1) return;
            ctx.beginPath();
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.moveTo(s.points[0].x, s.points[0].y);
            for (let i = 1; i < s.points.length; i++) {
                ctx.lineTo(s.points[i].x, s.points[i].y);
            }
            ctx.stroke();
        },
        text(ctx, s) {
            const { lines, lineHeight, maxWidth, totalHeight } = this._measureText(s);
            ctx.textBaseline = 'top';
            if (s.fillColor || s.background) {
                // Filled background with a faint border
                const padding = 4;
                const box = [s.x - padding, s.y - padding, maxWidth + padding * 2, totalHeight + padding * 2];
                ctx.fillStyle = s.fillColor || 'rgba(255, 255, 255, 0.95)';
                ctx.fillRect(...box);
                ctx.strokeStyle = 'rgba(0, 0, 0, 0.1)';
                ctx.lineWidth = 1;
                ctx.strokeRect(...box);
            } else {
                // Light outline for readability without a background
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
                ctx.lineWidth = 3;
                ctx.lineJoin = 'round';
                lines.forEach((line, i) => ctx.strokeText(line, s.x, s.y + i * lineHeight));
            }
            ctx.fillStyle = s.color || this.color;
            lines.forEach((line, i) => ctx.fillText(line, s.x, s.y + i * lineHeight));
        },
    },

    // --- Freehand helpers ---

    _simplifyPoints(points, tolerance) {
        // Ramer-Douglas-Peucker simplification to reduce point count
        if (points.length <= 2) return points.slice();

        let maxDist = 0, maxIdx = 0;
        const first = points[0], last = points[points.length - 1];

        for (let i = 1; i < points.length - 1; i++) {
            const dist = this._distToLine(points[i], first, last);
            if (dist > maxDist) {
                maxDist = dist;
                maxIdx = i;
            }
        }

        if (maxDist > tolerance) {
            const left = this._simplifyPoints(points.slice(0, maxIdx + 1), tolerance);
            const right = this._simplifyPoints(points.slice(maxIdx), tolerance);
            return left.slice(0, -1).concat(right);
        }
        return [first, last];
    },

    _getPointsBounds(points) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const p of points) {
            if (p.x < minX) minX = p.x;
            if (p.y < minY) minY = p.y;
            if (p.x > maxX) maxX = p.x;
            if (p.y > maxY) maxY = p.y;
        }
        return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
    },

    // --- Export ---

    toDataURL() {
        // Render without selection highlights
        this._deselectAll();
        this.render();
        return this.canvas.toDataURL('image/png');
    },

    async toBlob() {
        this._deselectAll();
        this.render();
        return new Promise(resolve => this.canvas.toBlob(resolve, 'image/png'));
    },

    toBackgroundDataURL() {
        // Background images + image-layer drawings (no annotation layer)
        const imageLayer = this.annotations.filter(a => a.layer === 'image');
        if (this.images.length === 0 && imageLayer.length === 0) return null;
        return this._renderJpeg(imageLayer);
    },

    toAnnotatedDataURL() {
        // Background images + all annotations combined
        if (this.images.length === 0 && this.annotations.length === 0) return null;
        return this._renderJpeg(this.annotations);
    },

    /** Background images plus ``annotations`` on white (JPG has no transparency), as a JPG data URL. */
    _renderJpeg(annotations) {
        const tmpCanvas = document.createElement('canvas');
        tmpCanvas.width = this.canvas.width;
        tmpCanvas.height = this.canvas.height;
        const tmpCtx = tmpCanvas.getContext('2d');
        tmpCtx.fillStyle = '#ffffff';
        tmpCtx.fillRect(0, 0, tmpCanvas.width, tmpCanvas.height);

        for (const img of this.images) {
            tmpCtx.drawImage(img.img, img.x, img.y, img.w, img.h);
        }

        // _drawShape paints on this.ctx; point it at the temporary canvas
        const origCtx = this.ctx;
        this.ctx = tmpCtx;
        for (const ann of annotations) this._drawShape(ann);
        this.ctx = origCtx;

        return tmpCanvas.toDataURL('image/jpeg', 0.85);
    },

    getAnnotationSummary() {
        // Return a human-readable count of annotation-layer items only
        // (image-layer drawings are part of the base image, not annotations)
        const annotationLayer = this.annotations.filter(a => a.layer !== 'image');
        if (annotationLayer.length === 0) return '';

        const counts = {};
        for (const ann of annotationLayer) {
            const type = ann.type;
            counts[type] = (counts[type] || 0) + 1;
        }

        const labels = { arrow: 'arrow', circle: 'circle', rect: 'rectangle', text: 'text label', freehand: 'freehand' };
        const parts = [];
        for (const [type, count] of Object.entries(counts)) {
            const label = labels[type] || type;
            parts.push(`${count} ${label}${count > 1 ? 's' : ''}`);
        }
        return parts.join(', ');
    },
};
