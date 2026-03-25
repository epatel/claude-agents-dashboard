// Enhanced debug version of the annotate paste functionality
const AnnotateDebug = {
    canvas: null,
    ctx: null,
    images: [],
    debugMode: true,

    init(canvasEl) {
        this.canvas = canvasEl;
        this.ctx = canvasEl.getContext('2d');
        this.images = [];
        this._setupDebugEvents();
        this.render();
        this.log('AnnotateDebug initialized');
    },

    log(message, type = 'info') {
        if (this.debugMode) {
            const timestamp = new Date().toLocaleTimeString();
            const logMessage = `[${timestamp}] [ANNOTATE-${type.toUpperCase()}] ${message}`;
            console.log(logMessage);

            // Also add to debug display if available
            const debugEl = document.getElementById('debug-output');
            if (debugEl) {
                debugEl.textContent += logMessage + '\n';
                debugEl.scrollTop = debugEl.scrollHeight;
            }
        }
    },

    _setupDebugEvents() {
        // Enhanced paste event with comprehensive debugging
        document.addEventListener('paste', (e) => {
            this.log('=== PASTE EVENT TRIGGERED ===');
            this.log(`Event target: ${e.target.tagName}${e.target.id ? '#' + e.target.id : ''}`);
            this.log(`Event currentTarget: ${e.currentTarget.tagName || 'document'}`);

            // Check dialog state with multiple methods
            const dialog = document.getElementById('annotate-dialog');
            this.log(`Dialog element found: ${!!dialog}`);

            if (dialog) {
                this.log(`Dialog.open property: ${dialog.open}`);
                this.log(`Dialog.hasAttribute('open'): ${dialog.hasAttribute('open')}`);
                this.log(`Dialog.style.display: ${dialog.style.display}`);
                this.log(`Dialog computed display: ${getComputedStyle(dialog).display}`);
                this.log(`Dialog offsetParent: ${!!dialog.offsetParent}`);

                // Check if dialog is actually visible
                const rect = dialog.getBoundingClientRect();
                this.log(`Dialog rect: ${rect.width}x${rect.height} at (${rect.left}, ${rect.top})`);
                this.log(`Dialog in viewport: ${rect.width > 0 && rect.height > 0}`);
            }

            // Original condition check
            if (!dialog || !dialog.open) {
                this.log(`PASTE REJECTED: dialog=${!!dialog}, dialog.open=${dialog?.open}`, 'warn');
                return;
            }

            this.log('Dialog check passed, processing paste...');
            this._onPasteDebug(e);
        });

        // Also add focused paste listeners for testing
        if (this.canvas) {
            this.canvas.addEventListener('paste', (e) => {
                this.log('Paste event received directly on canvas');
                this._onPasteDebug(e);
            });
        }

        this.log('Debug paste event listeners attached');
    },

    _onPasteDebug(e) {
        this.log('=== PROCESSING PASTE ===');
        e.preventDefault();

        const clipboardData = e.clipboardData;
        this.log(`ClipboardData: ${!!clipboardData}`);

        if (!clipboardData) {
            this.log('No clipboardData available', 'error');
            return;
        }

        const items = clipboardData.items;
        this.log(`Clipboard items: ${items ? items.length : 'none'}`);

        if (!items) {
            this.log('No clipboard items available', 'error');
            return;
        }

        // Log all clipboard items
        for (let i = 0; i < items.length; i++) {
            const item = items[i];
            this.log(`Item ${i}: type="${item.type}", kind="${item.kind}"`);
        }

        // Look for images
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                this.log(`Processing image item: ${item.type}`);

                const file = item.getAsFile();
                if (!file) {
                    this.log('Could not get file from clipboard item', 'error');
                    continue;
                }

                this.log(`Got file: name="${file.name}", size=${file.size}, type="${file.type}"`);

                const reader = new FileReader();
                reader.onload = (ev) => {
                    this.log('FileReader onload triggered');
                    const img = new Image();
                    img.onload = () => {
                        this.log(`Image loaded: ${img.width}x${img.height}`);

                        // Scale to fit canvas
                        let w = img.width, h = img.height;
                        const maxW = this.canvas.width * 0.8;
                        if (w > maxW) {
                            const scale = maxW / w;
                            w *= scale;
                            h *= scale;
                            this.log(`Image scaled to: ${w}x${h}`);
                        }

                        // Add to images array
                        const imageObj = {
                            img,
                            x: this.canvas.width / 2 - w / 2,
                            y: this.canvas.height / 2 - h / 2,
                            w, h,
                            selected: true
                        };

                        this.images.push(imageObj);
                        this.log(`Image added to images array. Total images: ${this.images.length}`);

                        this.render();
                        this.log('Canvas rendered with new image');
                    };
                    img.onerror = (err) => {
                        this.log(`Image load error: ${err}`, 'error');
                    };
                    img.src = ev.target.result;
                };
                reader.onerror = (err) => {
                    this.log(`FileReader error: ${err}`, 'error');
                };
                reader.readAsDataURL(file);
                break; // Only handle first image
            }
        }
    },

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
                if ((Math.floor(x / sz) + Math.floor(y / sz)) % 2) {
                    ctx.fillRect(x, y, sz, sz);
                }
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
            }
        }
    },

    // Helper methods for testing
    simulateDialogOpen() {
        const dialog = document.getElementById('annotate-dialog');
        if (dialog) {
            dialog.setAttribute('open', '');
            // For older browsers or custom dialog implementations
            dialog.open = true;
            this.log('Dialog state set to open for testing');
        }
    },

    simulateDialogClose() {
        const dialog = document.getElementById('annotate-dialog');
        if (dialog) {
            dialog.removeAttribute('open');
            dialog.open = false;
            this.log('Dialog state set to closed for testing');
        }
    },

    testPasteWithDebug() {
        this.log('=== MANUAL PASTE TEST ===');

        // Try to read clipboard manually
        if (navigator.clipboard && navigator.clipboard.read) {
            navigator.clipboard.read().then(clipboardItems => {
                this.log(`Manual clipboard read: ${clipboardItems.length} items`);

                for (let i = 0; i < clipboardItems.length; i++) {
                    const item = clipboardItems[i];
                    this.log(`Manual item ${i}: types = [${Array.from(item.types).join(', ')}]`);

                    for (const type of item.types) {
                        if (type.startsWith('image/')) {
                            item.getType(type).then(blob => {
                                this.log(`Got blob for ${type}: ${blob.size} bytes`);

                                const reader = new FileReader();
                                reader.onload = (e) => {
                                    const img = new Image();
                                    img.onload = () => {
                                        this.log(`Manual paste image: ${img.width}x${img.height}`);
                                        // Process the same way as paste event
                                        let w = img.width, h = img.height;
                                        const maxW = this.canvas.width * 0.8;
                                        if (w > maxW) {
                                            const scale = maxW / w;
                                            w *= scale;
                                            h *= scale;
                                        }

                                        this.images.push({
                                            img,
                                            x: this.canvas.width / 2 - w / 2,
                                            y: this.canvas.height / 2 - h / 2,
                                            w, h,
                                            selected: true
                                        });

                                        this.render();
                                        this.log('Manual paste successful!');
                                    };
                                    img.src = e.target.result;
                                };
                                reader.readAsDataURL(blob);
                            }).catch(err => {
                                this.log(`Error getting clipboard blob: ${err}`, 'error');
                            });
                        }
                    }
                }
            }).catch(err => {
                this.log(`Manual clipboard read failed: ${err}`, 'error');
            });
        } else {
            this.log('Clipboard API not available for manual reading', 'warn');
        }
    }
};

// Auto-initialize if canvas is available
document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('annotate-canvas') || document.getElementById('test-canvas');
    if (canvas) {
        AnnotateDebug.init(canvas);
    }
});