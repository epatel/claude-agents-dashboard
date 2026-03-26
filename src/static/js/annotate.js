// To enable debugging: window.ANNOTATE_DEBUG = true; in browser console
const Annotate = {
    canvas: null,
    ctx: null,
    // Layers: background images and annotations
    images: [],       // {img, x, y, w, h, selected}
    annotations: [],  // {type, ...props, selected}
    tool: 'select',   // select, arrow, circle, rect, text
    color: '#ff3b30',
    lineWidth: 3,
    fontSize: 16,

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
        this._setupEvents();
        this.render();

        // Enable debugging by default to help troubleshoot paste issues
        window.ANNOTATE_DEBUG = true;
        if (window.ANNOTATE_DEBUG) console.log('Annotate canvas initialized, debugging enabled');
    },

    clear() {
        this.images = [];
        this.annotations = [];
        this.render();
    },

    cleanup() {
        // Remove document-level event listener to prevent memory leaks
        if (this._pasteHandler) {
            document.removeEventListener('paste', this._pasteHandler);
            this._pasteHandler = null;
        }
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
            // Try modern Clipboard API first
            if (navigator.clipboard && navigator.clipboard.read) {
                if (window.ANNOTATE_DEBUG) console.log('Using modern Clipboard API');
                const clipboardItems = await navigator.clipboard.read();

                for (const item of clipboardItems) {
                    if (window.ANNOTATE_DEBUG) console.log('Clipboard item types:', Array.from(item.types));

                    for (const type of item.types) {
                        if (type.startsWith('image/')) {
                            const blob = await item.getType(type);
                            this._processPastedImage(blob);
                            return true; // Successfully processed image
                        }
                    }
                }

                // No images found
                this._showPasteMessage('No images found in clipboard. Copy an image first.');
                return false;
            }
        } catch (error) {
            if (window.ANNOTATE_DEBUG) console.log('Clipboard API failed:', error);

            // Fall back to instructing user to use Ctrl+V
            this._showPasteMessage('Click here and press Ctrl+V (or Cmd+V) to paste image');

            // Focus the canvas to receive keyboard events
            this.canvas.focus();
            return false;
        }

        this._showPasteMessage('Clipboard access not available. Use Ctrl+V or drag and drop instead.');
        return false;
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

        // Paste images — listen on document because canvas elements don't
        // reliably receive paste events, even when focused.
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

        // Keyboard
        // Mouse wheel to scale selected image
        c.addEventListener('wheel', (e) => {
            const sel = this.images.find(i => i.selected);
            if (!sel) return;
            e.preventDefault();
            const factor = e.deltaY < 0 ? 1.08 : 0.92;
            const p = this._pos(e);
            // Scale around mouse position
            const oldW = sel.w, oldH = sel.h;
            sel.w *= factor;
            sel.h *= factor;
            sel.x -= (sel.w - oldW) * ((p.x - sel.x) / oldW);
            sel.y -= (sel.h - oldH) * ((p.y - sel.y) / oldH);
            this.render();
        }, { passive: false });

        c.setAttribute('tabindex', '0');
        c.addEventListener('keydown', (e) => {
            if (e.key === 'Delete' || e.key === 'Backspace') {
                this._deleteSelected();
                e.preventDefault();
            } else if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
                // Handle Ctrl+V / Cmd+V directly on canvas
                e.preventDefault();
                this.pasteFromClipboard();
            }
        });

        // Also listen for paste events directly on the canvas
        c.addEventListener('paste', (e) => {
            if (this._isAnnotateDialogOpen()) {
                this._onPaste(e);
            }
        });

        // Focus canvas when clicked to enable keyboard shortcuts
        c.addEventListener('click', () => {
            c.focus();
        });
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

        let foundImage = false;
        for (const item of items) {
            if (window.ANNOTATE_DEBUG) console.log('Item type:', item.type);
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (!file) {
                    if (window.ANNOTATE_DEBUG) console.log('Failed to get file from item');
                    continue;
                }

                this._processPastedImage(file);
                foundImage = true;
                break; // Only handle the first image
            }
        }

        if (!foundImage) {
            this._showPasteMessage('No images found in clipboard. Copy an image first.');
        }
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
        const p = this._pos(e);
        this._startX = p.x;
        this._startY = p.y;
        this.canvas.focus();

        if (this.tool === 'select') {
            // Check resize handles on selected images first
            const selImg = this.images.find(i => i.selected);
            if (selImg) {
                const handle = this._hitHandle(selImg, p.x, p.y);
                if (handle) {
                    this._resizing = { img: selImg, handle };
                    return;
                }
            }

            // Try to select an annotation or image
            this._deselectAll();
            const ann = this._hitAnnotation(p.x, p.y);
            if (ann) {
                ann.selected = true;
                this._dragging = ann;
                this._offsetX = p.x - (ann.x || ann.x1 || 0);
                this._offsetY = p.y - (ann.y || ann.y1 || 0);
                this.render();
                return;
            }
            const img = this._hitImage(p.x, p.y);
            if (img) {
                img.selected = true;
                this._dragging = img;
                this._offsetX = p.x - img.x;
                this._offsetY = p.y - img.y;
                this.render();
                return;
            }
            this.render();
        } else {
            // Start drawing
            this._drawing = { type: this.tool, x1: p.x, y1: p.y, x2: p.x, y2: p.y };
        }
    },

    _onMouseMove(e) {
        const p = this._pos(e);

        // Resize handle drag
        if (this._resizing) {
            const { img, handle } = this._resizing;
            const aspect = img.img.width / img.img.height;
            if (handle === 'se') {
                img.w = Math.max(30, p.x - img.x);
                img.h = img.w / aspect;
            } else if (handle === 'sw') {
                const newW = Math.max(30, (img.x + img.w) - p.x);
                img.x = img.x + img.w - newW;
                img.w = newW;
                img.h = img.w / aspect;
            } else if (handle === 'ne') {
                img.w = Math.max(30, p.x - img.x);
                const newH = img.w / aspect;
                img.y = img.y + img.h - newH;
                img.h = newH;
            } else if (handle === 'nw') {
                const newW = Math.max(30, (img.x + img.w) - p.x);
                const newH = newW / aspect;
                img.x = img.x + img.w - newW;
                img.y = img.y + img.h - newH;
                img.w = newW;
                img.h = newH;
            }
            this.render();
            return;
        }

        if (this._dragging) {
            const d = this._dragging;
            if (d.img) {
                // Moving an image
                d.x = p.x - this._offsetX;
                d.y = p.y - this._offsetY;
            } else if (d.type === 'text') {
                d.x = p.x - this._offsetX;
                d.y = p.y - this._offsetY;
            } else if (d.type === 'arrow') {
                const dx = p.x - this._startX;
                const dy = p.y - this._startY;
                d.x1 += dx; d.y1 += dy;
                d.x2 += dx; d.y2 += dy;
                this._startX = p.x;
                this._startY = p.y;
            } else if (d.type === 'circle' || d.type === 'rect') {
                const dx = p.x - this._startX;
                const dy = p.y - this._startY;
                d.x += dx; d.y += dy;
                this._startX = p.x;
                this._startY = p.y;
            }
            this.render();
            return;
        }

        if (this._drawing) {
            this._drawing.x2 = p.x;
            this._drawing.y2 = p.y;
            this.render();
            this._drawShape(this._drawing);
        }
    },

    _onMouseUp(e) {
        if (this._resizing) {
            this._resizing = null;
            this.render();
            return;
        }
        if (this._drawing) {
            const d = this._drawing;
            const dx = Math.abs(d.x2 - d.x1);
            const dy = Math.abs(d.y2 - d.y1);
            if (dx > 5 || dy > 5) {
                if (d.type === 'arrow') {
                    this.annotations.push({
                        type: 'arrow', x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2,
                        color: this.color, lineWidth: this.lineWidth, selected: false,
                    });
                } else if (d.type === 'circle') {
                    const cx = (d.x1 + d.x2) / 2, cy = (d.y1 + d.y2) / 2;
                    const rx = dx / 2, ry = dy / 2;
                    this.annotations.push({
                        type: 'circle', x: cx, y: cy, rx, ry,
                        color: this.color, lineWidth: this.lineWidth, selected: false,
                    });
                } else if (d.type === 'rect') {
                    this.annotations.push({
                        type: 'rect', x: Math.min(d.x1, d.x2), y: Math.min(d.y1, d.y2),
                        w: dx, h: dy,
                        color: this.color, lineWidth: this.lineWidth, selected: false,
                    });
                }
            }
            this._drawing = null;
            this.render();
        }
        this._dragging = null;
    },

    _onDblClick(e) {
        if (this.tool === 'text' || this.tool === 'select') {
            const p = this._pos(e);
            const text = prompt('Enter text:');
            if (text) {
                this.annotations.push({
                    type: 'text', x: p.x, y: p.y, text,
                    color: this.color, fontSize: this.fontSize, selected: false,
                });
                this.render();
            }
        }
    },

    // --- Hit testing ---

    _hitImage(x, y) {
        for (let i = this.images.length - 1; i >= 0; i--) {
            const im = this.images[i];
            if (x >= im.x && x <= im.x + im.w && y >= im.y && y <= im.y + im.h) return im;
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
            if (a.type === 'text') {
                this.ctx.font = `${a.fontSize || this.fontSize}px sans-serif`;
                const m = this.ctx.measureText(a.text);
                const fontSize = a.fontSize || this.fontSize;
                // Use consistent hit testing with new text baseline
                if (x >= a.x && x <= a.x + m.width && y >= a.y && y <= a.y + fontSize) return a;
            } else if (a.type === 'arrow') {
                const dist = this._distToLine(x, y, a.x1, a.y1, a.x2, a.y2);
                if (dist < 10) return a;
            } else if (a.type === 'circle') {
                const dx = (x - a.x) / a.rx, dy = (y - a.y) / a.ry;
                const d = Math.sqrt(dx * dx + dy * dy);
                if (Math.abs(d - 1) < 0.2) return a;
            } else if (a.type === 'rect') {
                // Hit on border
                const near = (x >= a.x - 5 && x <= a.x + a.w + 5 && y >= a.y - 5 && y <= a.y + a.h + 5) &&
                    !(x >= a.x + 5 && x <= a.x + a.w - 5 && y >= a.y + 5 && y <= a.y + a.h - 5);
                if (near) return a;
            }
        }
        return null;
    },

    _distToLine(px, py, x1, y1, x2, y2) {
        const A = px - x1, B = py - y1, C = x2 - x1, D = y2 - y1;
        const dot = A * C + B * D;
        const lenSq = C * C + D * D;
        let t = lenSq ? dot / lenSq : -1;
        t = Math.max(0, Math.min(1, t));
        const dx = px - (x1 + t * C), dy = py - (y1 + t * D);
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
        const ctx = this.ctx;
        const c = this.canvas;
        ctx.clearRect(0, 0, c.width, c.height);

        // Checkerboard background
        ctx.fillStyle = '#f0f0f0';
        ctx.fillRect(0, 0, c.width, c.height);
        const sz = 16;
        ctx.fillStyle = '#e0e0e0';
        for (let y = 0; y < c.height; y += sz) {
            for (let x = 0; x < c.width; x += sz) {
                if ((Math.floor(x / sz) + Math.floor(y / sz)) % 2) ctx.fillRect(x, y, sz, sz);
            }
        }

        // Draw images
        for (const im of this.images) {
            ctx.drawImage(im.img, im.x, im.y, im.w, im.h);
            if (im.selected) {
                ctx.strokeStyle = '#0071e3';
                ctx.lineWidth = 2;
                ctx.setLineDash([5, 3]);
                ctx.strokeRect(im.x - 2, im.y - 2, im.w + 4, im.h + 4);
                ctx.setLineDash([]);
                this._drawHandles(im);
            }
        }

        // Draw annotations in layers to prevent overlap issues
        // First draw shapes (arrows, circles, rectangles)
        for (const a of this.annotations) {
            if (a.type !== 'text') {
                this._drawShape(a);
                if (a.selected) {
                    ctx.strokeStyle = '#0071e3';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 3]);
                    if (a.type === 'arrow') {
                        ctx.strokeRect(Math.min(a.x1, a.x2) - 5, Math.min(a.y1, a.y2) - 5,
                            Math.abs(a.x2 - a.x1) + 10, Math.abs(a.y2 - a.y1) + 10);
                    } else if (a.type === 'circle') {
                        ctx.strokeRect(a.x - a.rx - 3, a.y - a.ry - 3, a.rx * 2 + 6, a.ry * 2 + 6);
                    } else if (a.type === 'rect') {
                        ctx.strokeRect(a.x - 3, a.y - 3, a.w + 6, a.h + 6);
                    }
                    ctx.setLineDash([]);
                }
            }
        }

        // Then draw text annotations on top to prevent overlap
        for (const a of this.annotations) {
            if (a.type === 'text') {
                this._drawShape(a);
                if (a.selected) {
                    ctx.strokeStyle = '#0071e3';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 3]);
                    ctx.font = `${a.fontSize || this.fontSize}px sans-serif`;
                    const m = ctx.measureText(a.text);
                    const padding = 2;
                    // Use consistent text baseline for selection box
                    ctx.strokeRect(a.x - padding, a.y - padding, m.width + (padding * 2), (a.fontSize || this.fontSize) + (padding * 2));
                    ctx.setLineDash([]);
                }
            }
        }

        // Draw in-progress shape
        if (this._drawing) {
            this._drawShape(this._drawing);
        }
    },

    _drawShape(s) {
        const ctx = this.ctx;
        ctx.strokeStyle = s.color || this.color;
        ctx.fillStyle = s.color || this.color;
        ctx.lineWidth = s.lineWidth || this.lineWidth;
        ctx.setLineDash([]);

        if (s.type === 'arrow') {
            const { x1, y1, x2, y2 } = s;
            const angle = Math.atan2(y2 - y1, x2 - x1);
            const headLen = 10 + (s.lineWidth || this.lineWidth) * 2;
            const headHalf = 0.4;
            // Shorten the line so it stops at the arrowhead base
            const baseX = x2 - headLen * Math.cos(angle);
            const baseY = y2 - headLen * Math.sin(angle);
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
        } else if (s.type === 'circle') {
            const cx = s.x ?? (s.x1 + s.x2) / 2;
            const cy = s.y ?? (s.y1 + s.y2) / 2;
            const rx = s.rx ?? Math.abs(s.x2 - s.x1) / 2;
            const ry = s.ry ?? Math.abs(s.y2 - s.y1) / 2;
            ctx.beginPath();
            ctx.ellipse(cx, cy, Math.max(rx, 1), Math.max(ry, 1), 0, 0, Math.PI * 2);
            ctx.stroke();
        } else if (s.type === 'rect') {
            const x = s.x ?? Math.min(s.x1, s.x2);
            const y = s.y ?? Math.min(s.y1, s.y2);
            const w = s.w ?? Math.abs(s.x2 - s.x1);
            const h = s.h ?? Math.abs(s.y2 - s.y1);
            ctx.strokeRect(x, y, w, h);
        } else if (s.type === 'text') {
            const fontSize = s.fontSize || this.fontSize;
            ctx.font = `${fontSize}px sans-serif`;
            ctx.textBaseline = 'top';

            // Add text background to prevent overlap with lines/shapes
            const metrics = ctx.measureText(s.text);
            const padding = 4; // Increased padding for better clearance
            const bgX = s.x - padding;
            const bgY = s.y - padding;
            const bgW = metrics.width + (padding * 2);
            const bgH = fontSize + (padding * 2);

            // Draw solid background with border to prevent overlap
            ctx.fillStyle = 'rgba(255, 255, 255, 1)'; // Made fully opaque
            ctx.fillRect(bgX, bgY, bgW, bgH);

            // Add subtle border for better definition
            ctx.strokeStyle = 'rgba(0, 0, 0, 0.1)';
            ctx.lineWidth = 1;
            ctx.strokeRect(bgX, bgY, bgW, bgH);

            // Draw text with original color
            ctx.fillStyle = s.color || this.color;
            ctx.fillText(s.text, s.x, s.y);
        }
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
};
