// Shortcuts bar — quick-launch bash commands from the bottom bar
const Shortcuts = {
    shortcuts: [],
    _pollTimers: {},    // shortcut_id → interval timer
    _runState: {},      // shortcut_id → { status, output, exit_code }
    _autoReset: {},     // shortcut_id → true if auto-reset enabled

    async init() {
        await this.load();
        this.render();
    },

    async load() {
        try {
            this.shortcuts = await Api.request('GET', '/api/shortcuts');
        } catch {
            this.shortcuts = [];
        }
    },

    render() {
        const bar = document.getElementById('shortcuts-bar');
        if (!bar) return;

        const btns = bar.querySelector('.shortcuts-buttons');
        btns.innerHTML = '';

        for (const sc of this.shortcuts) {
            const btn = document.createElement('button');
            btn.className = 'shortcut-btn';
            btn.textContent = sc.name;
            btn.title = sc.command;
            btn.dataset.id = sc.id;
            btn.dataset.mapName = 'shortcuts.btn-shortcut';

            // Reflect current run state
            const state = this._runState[sc.id];
            if (state) {
                if (state.status === 'running') {
                    btn.classList.add('shortcut-running');
                } else if (state.status === 'failed' || state.status === 'stopped') {
                    btn.classList.add('shortcut-failed');
                } else if (state.status === 'done') {
                    btn.classList.add('shortcut-done');
                }
            }

            btn.addEventListener('click', () => this.runOrShow(sc));
            btns.appendChild(btn);
        }

        const visible = this.shortcuts.length > 0;
        bar.style.display = visible ? '' : 'none';

        // Toggle floating add button visibility and body class for layout
        const floatingBtn = document.getElementById('shortcuts-add-floating');
        if (floatingBtn) {
            floatingBtn.style.display = visible ? 'none' : '';
        }
        document.body.classList.toggle('has-shortcuts', visible);
    },

    async runOrShow(sc) {
        const state = this._runState[sc.id];
        if (state && state.status === 'running') {
            // Already running — just show progress dialog
            this.showProgress(sc);
            return;
        }

        // If there's a finished log, show it instead of re-running
        if (state && (state.status === 'done' || state.status === 'failed' || state.status === 'stopped') && state.output) {
            this.showProgress(sc);
            return;
        }

        // Clear previous state
        this._runState[sc.id] = { status: 'running', output: '', exit_code: null };
        this.render();

        try {
            await Api.request('POST', `/api/shortcuts/${sc.id}/run`);
        } catch (e) {
            this._runState[sc.id] = { status: 'failed', output: `Failed to start: ${e.message}`, exit_code: -1 };
            this.render();
            this.showProgress(sc);
            return;
        }

        // Show progress dialog and start polling
        this.showProgress(sc);
        this._startPolling(sc);
    },

    _startPolling(sc) {
        // Clear existing timer if any
        if (this._pollTimers[sc.id]) {
            clearInterval(this._pollTimers[sc.id]);
        }

        const poll = async () => {
            try {
                const data = await Api.request('GET', `/api/shortcuts/${sc.id}/output`);
                this._runState[sc.id] = {
                    status: data.status,
                    output: data.output,
                    exit_code: data.exit_code
                };

                // Update the dialog if it's open for this shortcut
                this._updateProgressContent(sc.id);

                if (data.status !== 'running') {
                    clearInterval(this._pollTimers[sc.id]);
                    delete this._pollTimers[sc.id];

                    // Auto-reset: clear state so next click re-runs (only on success)
                    if (this._autoReset[sc.id]) {
                        if (data.status === 'done') {
                            delete this._runState[sc.id];
                        }
                        delete this._autoReset[sc.id];
                    }

                    this.render();
                }
            } catch {
                // Ignore polling errors
            }
        };

        // Poll immediately then every 500ms
        poll();
        this._pollTimers[sc.id] = setInterval(poll, 500);
    },

    showProgress(sc) {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!dialog) return;

        document.getElementById('shortcut-progress-title').textContent = sc.name;
        const cmdEl = document.getElementById('shortcut-progress-command');
        cmdEl.textContent = `$ ${sc.command}`;
        cmdEl.style.whiteSpace = 'pre-wrap';
        dialog.dataset.shortcutId = sc.id;

        if (!dialog.open) {
            dialog.showModal();
        }

        // Update content AFTER dialog is open (guard in _updateProgressContent
        // checks dialog.open and bails out if closed)
        this._updateProgressContent(sc.id);

        // If it was a finished state (failed/done), and user clicks button again,
        // restart polling in case the process was re-run
        const state = this._runState[sc.id];
        if (state && state.status === 'running' && !this._pollTimers[sc.id]) {
            this._startPolling(sc);
        }
    },

    _updateProgressContent(shortcutId) {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!dialog || !dialog.open || dialog.dataset.shortcutId !== shortcutId) return;

        const state = this._runState[shortcutId] || { status: 'idle', output: '', exit_code: null };
        const outputEl = document.getElementById('shortcut-progress-output');
        const statusEl = document.getElementById('shortcut-progress-status');
        const resetBtn = document.getElementById('shortcut-reset-btn');
        const autoResetBtn = document.getElementById('shortcut-auto-reset-btn');

        // Update output — auto-scroll if at bottom
        const isAtBottom = outputEl.scrollHeight - outputEl.scrollTop - outputEl.clientHeight < 30;
        if (state.output) {
            outputEl.innerHTML = this._ansiToHtml(state.output);
        } else {
            outputEl.textContent = '(waiting for output...)';
        }
        if (isAtBottom) {
            outputEl.scrollTop = outputEl.scrollHeight;
        }

        // Update reset/stop button label based on state
        if (resetBtn) {
            if (state.status === 'running') {
                resetBtn.textContent = 'Stop';
                resetBtn.style.display = '';
            } else if (state.status === 'done' || state.status === 'failed' || state.status === 'stopped') {
                resetBtn.textContent = 'Reset';
                resetBtn.style.display = '';
            } else {
                resetBtn.style.display = 'none';
            }
        }

        // Auto-reset button only available while running
        if (autoResetBtn) {
            autoResetBtn.style.display = state.status === 'running' ? '' : 'none';
        }

        // Update status indicator
        if (state.status === 'running') {
            statusEl.textContent = '⟳ Running...';
            statusEl.className = 'shortcut-status shortcut-status-running';
        } else if (state.status === 'failed') {
            statusEl.textContent = `✕ Failed (exit code: ${state.exit_code})`;
            statusEl.className = 'shortcut-status shortcut-status-failed';
        } else if (state.status === 'stopped') {
            statusEl.textContent = '⏹ Stopped';
            statusEl.className = 'shortcut-status shortcut-status-failed';
        } else if (state.status === 'done') {
            statusEl.textContent = '✓ Completed';
            statusEl.className = 'shortcut-status shortcut-status-done';
        } else {
            statusEl.textContent = '';
            statusEl.className = 'shortcut-status';
        }
    },

    closeProgress() {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!dialog) return;
        dialog.close();
    },

    autoResetAndClose() {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!dialog) return;
        const id = dialog.dataset.shortcutId;
        if (id) {
            this._autoReset[id] = true;
        }
        dialog.close();
    },

    async resetShortcut() {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!dialog) return;
        const id = dialog.dataset.shortcutId;
        if (!id) return;

        const state = this._runState[id];
        const isRunning = state && state.status === 'running';

        if (isRunning) {
            // Stop the process but keep the log visible
            try {
                await Api.request('POST', `/api/shortcuts/${id}/stop`);
            } catch { /* ignore */ }
            // Let polling pick up the stopped state and update UI
            return;
        }

        // Reset: clear everything (for stopped/done/failed states)

        // Stop polling
        if (this._pollTimers[id]) {
            clearInterval(this._pollTimers[id]);
            delete this._pollTimers[id];
        }

        // Reset server-side state
        try {
            await Api.request('POST', `/api/shortcuts/${id}/reset`);
        } catch { /* ignore */ }

        // Clear client-side state
        delete this._runState[id];

        // Reset dialog UI
        document.getElementById('shortcut-progress-output').textContent = '(waiting for output...)';
        const statusEl = document.getElementById('shortcut-progress-status');
        statusEl.textContent = '';
        statusEl.className = 'shortcut-status';

        // Re-render buttons to remove running/done/failed styling
        this.render();

        // Close the dialog
        dialog.close();
    },

    // --- Add shortcut ---
    showAddDialog() {
        const dialog = document.getElementById('shortcut-add-dialog');
        if (!dialog) return;
        document.getElementById('shortcut-add-name').value = '';
        document.getElementById('shortcut-add-command').value = '';
        dialog.showModal();
        // Ctrl+Enter to submit from textarea
        this._setupCtrlEnter('shortcut-add-command', dialog);
    },

    closeAddDialog() {
        const dialog = document.getElementById('shortcut-add-dialog');
        if (dialog) dialog.close();
    },

    async submitAdd(event) {
        event.preventDefault();
        const name = document.getElementById('shortcut-add-name').value.trim();
        const command = document.getElementById('shortcut-add-command').value.trim();
        if (!name || !command) return;

        try {
            await Api.request('POST', '/api/shortcuts', { name, command });
            this.closeAddDialog();
            await this.load();
            this.render();
        } catch (e) {
            alert('Failed to add shortcut: ' + e.message);
        }
    },

    // --- Manage shortcuts ---
    showManageDialog() {
        const dialog = document.getElementById('shortcut-manage-dialog');
        if (!dialog) return;
        this._renderManageList();
        dialog.showModal();
    },

    closeManageDialog() {
        const dialog = document.getElementById('shortcut-manage-dialog');
        if (dialog) dialog.close();
    },

    _renderManageList() {
        const list = document.getElementById('shortcut-manage-list');
        if (!list) return;

        if (this.shortcuts.length === 0) {
            list.innerHTML = '<p style="color:var(--text-secondary);text-align:center;padding:20px;">No shortcuts yet</p>';
            return;
        }

        list.innerHTML = '';
        for (const sc of this.shortcuts) {
            const row = document.createElement('div');
            row.className = 'shortcut-manage-row';
            row.innerHTML = `
                <div class="shortcut-manage-info">
                    <span class="shortcut-manage-name">${this._esc(sc.name)}</span>
                    <code class="shortcut-manage-cmd" style="white-space:pre-wrap;">${this._esc(sc.command)}</code>
                </div>
                <div class="shortcut-manage-actions">
                    <button class="btn btn-sm" onclick="Shortcuts.showEditDialog('${this._esc(sc.id)}')">Edit</button>
                    <button class="btn btn-sm btn-danger" onclick="Shortcuts.deleteShortcut('${this._esc(sc.id)}')">Remove</button>
                </div>
            `;
            list.appendChild(row);
        }
    },

    async deleteShortcut(id) {
        try {
            await Api.request('DELETE', `/api/shortcuts/${id}`);
            // Stop polling if running
            if (this._pollTimers[id]) {
                clearInterval(this._pollTimers[id]);
                delete this._pollTimers[id];
            }
            delete this._runState[id];
            await this.load();
            this.render();
            this._renderManageList();
        } catch (e) {
            alert('Failed to delete shortcut: ' + e.message);
        }
    },

    // --- Edit shortcut ---
    showEditDialog(id) {
        const sc = this.shortcuts.find(s => s.id === id);
        if (!sc) return;
        const dialog = document.getElementById('shortcut-edit-dialog');
        if (!dialog) return;
        dialog.dataset.shortcutId = id;
        document.getElementById('shortcut-edit-name').value = sc.name;
        document.getElementById('shortcut-edit-command').value = sc.command;
        dialog.showModal();
        // Ctrl+Enter to submit from textarea
        this._setupCtrlEnter('shortcut-edit-command', dialog);
    },

    closeEditDialog() {
        const dialog = document.getElementById('shortcut-edit-dialog');
        if (dialog) dialog.close();
    },

    async submitEdit(event) {
        event.preventDefault();
        const dialog = document.getElementById('shortcut-edit-dialog');
        if (!dialog) return;
        const id = dialog.dataset.shortcutId;
        if (!id) return;

        const name = document.getElementById('shortcut-edit-name').value.trim();
        const command = document.getElementById('shortcut-edit-command').value.trim();
        if (!name || !command) return;

        try {
            await Api.request('PUT', `/api/shortcuts/${id}`, { name, command });
            this.closeEditDialog();
            await this.load();
            this.render();
            this._renderManageList();
        } catch (e) {
            alert('Failed to update shortcut: ' + e.message);
        }
    },

    _setupCtrlEnter(textareaId, dialog) {
        const ta = document.getElementById(textareaId);
        if (!ta) return;
        // Remove previous listener if any
        ta._ctrlEnterHandler && ta.removeEventListener('keydown', ta._ctrlEnterHandler);
        ta._ctrlEnterHandler = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const form = ta.closest('form');
                if (form) form.requestSubmit();
            }
        };
        ta.addEventListener('keydown', ta._ctrlEnterHandler);
    },

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    },

    // Convert ANSI SGR escape sequences in `text` to HTML <span> tags.
    // Handles standard 16 colors, bright variants, 256-color and truecolor
    // foreground/background, plus bold/dim/italic/underline. Other escape
    // sequences (cursor moves, erase, etc.) are stripped. The output is
    // safe to assign to .innerHTML — non-SGR text is HTML-escaped.
    _ansiToHtml(text) {
        if (!text) return '';

        // Collapse \r\n → \n and handle bare \r (rewrite current line) by
        // dropping everything before it on the same line, which mirrors
        // how a terminal would render carriage-returned progress bars.
        text = text.replace(/\r\n/g, '\n').replace(/^[^\n]*\r(?!\n)/gm, '');

        // SGR colors — standard 16
        const FG = {
            30: '#000000', 31: '#cd3131', 32: '#0dbc79', 33: '#e5e510',
            34: '#2472c8', 35: '#bc3fbc', 36: '#11a8cd', 37: '#e5e5e5',
            90: '#666666', 91: '#f14c4c', 92: '#23d18b', 93: '#f5f543',
            94: '#3b8eea', 95: '#d670d6', 96: '#29b8db', 97: '#ffffff',
        };
        const BG = {
            40: '#000000', 41: '#cd3131', 42: '#0dbc79', 43: '#e5e510',
            44: '#2472c8', 45: '#bc3fbc', 46: '#11a8cd', 47: '#e5e5e5',
            100: '#666666', 101: '#f14c4c', 102: '#23d18b', 103: '#f5f543',
            104: '#3b8eea', 105: '#d670d6', 106: '#29b8db', 107: '#ffffff',
        };
        // xterm 256-color palette: 0-15 (system) + 16-231 (216 cube) + 232-255 (grayscale)
        const sys256 = [
            '#000000', '#cd3131', '#0dbc79', '#e5e510', '#2472c8', '#bc3fbc', '#11a8cd', '#e5e5e5',
            '#666666', '#f14c4c', '#23d18b', '#f5f543', '#3b8eea', '#d670d6', '#29b8db', '#ffffff',
        ];
        const palette256 = (n) => {
            if (n < 16) return sys256[n];
            if (n < 232) {
                n -= 16;
                const r = Math.floor(n / 36), g = Math.floor((n % 36) / 6), b = n % 6;
                const c = (v) => v === 0 ? 0 : 55 + v * 40;
                return `rgb(${c(r)},${c(g)},${c(b)})`;
            }
            const v = 8 + (n - 232) * 10;
            return `rgb(${v},${v},${v})`;
        };

        // State: a stack of style attributes the current span carries.
        let style = { fg: null, bg: null, bold: false, dim: false, italic: false, underline: false };
        const styleStr = (s) => {
            const parts = [];
            if (s.fg) parts.push(`color:${s.fg}`);
            if (s.bg) parts.push(`background-color:${s.bg}`);
            if (s.bold) parts.push('font-weight:bold');
            if (s.dim) parts.push('opacity:0.7');
            if (s.italic) parts.push('font-style:italic');
            if (s.underline) parts.push('text-decoration:underline');
            return parts.join(';');
        };
        const isActive = (s) => s.fg || s.bg || s.bold || s.dim || s.italic || s.underline;

        // Apply one SGR parameter list (e.g. "1;31" or "38;5;202") to `style`.
        const applySGR = (params) => {
            const codes = params === '' ? [0] : params.split(';').map(Number);
            for (let i = 0; i < codes.length; i++) {
                const c = codes[i];
                if (c === 0 || Number.isNaN(c)) {
                    style = { fg: null, bg: null, bold: false, dim: false, italic: false, underline: false };
                } else if (c === 1) style.bold = true;
                else if (c === 2) style.dim = true;
                else if (c === 3) style.italic = true;
                else if (c === 4) style.underline = true;
                else if (c === 22) { style.bold = false; style.dim = false; }
                else if (c === 23) style.italic = false;
                else if (c === 24) style.underline = false;
                else if (c === 39) style.fg = null;
                else if (c === 49) style.bg = null;
                else if (FG[c] !== undefined) style.fg = FG[c];
                else if (BG[c] !== undefined) style.bg = BG[c];
                else if (c === 38 || c === 48) {
                    // Extended color: 38;5;N (256-color) or 38;2;R;G;B (truecolor)
                    const target = c === 38 ? 'fg' : 'bg';
                    const mode = codes[i + 1];
                    if (mode === 5 && codes[i + 2] !== undefined) {
                        style[target] = palette256(codes[i + 2]);
                        i += 2;
                    } else if (mode === 2 && codes[i + 4] !== undefined) {
                        style[target] = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
                        i += 4;
                    }
                }
            }
        };

        // Walk the text. Match SGR (CSI ... m) and strip other CSI / OSC sequences.
        // \x1b[ ... letter is CSI; \x1b] ... \x07|\x1b\\ is OSC.
        const ESC = '\u001b';
        let out = '';
        let openSpan = false;
        const pushText = (chunk) => {
            if (!chunk) return;
            const escaped = this._esc(chunk);
            if (isActive(style)) {
                if (!openSpan) {
                    out += `<span style="${styleStr(style)}">`;
                    openSpan = true;
                }
                out += escaped;
            } else {
                if (openSpan) { out += '</span>'; openSpan = false; }
                out += escaped;
            }
        };
        const reopenSpan = () => {
            if (openSpan) { out += '</span>'; openSpan = false; }
        };

        let i = 0;
        while (i < text.length) {
            const ch = text[i];
            if (ch !== ESC) {
                // Find next ESC and emit the chunk in one go.
                const next = text.indexOf(ESC, i);
                const end = next === -1 ? text.length : next;
                pushText(text.slice(i, end));
                i = end;
                continue;
            }
            // ESC sequence — try CSI first.
            const csi = /^\u001b\[([0-9;?]*)([@-~])/.exec(text.slice(i));
            if (csi) {
                const [match, params, final] = csi;
                if (final === 'm') {
                    reopenSpan();
                    applySGR(params);
                }
                // All other CSI sequences (cursor moves, erase, etc.) are stripped.
                i += match.length;
                continue;
            }
            // OSC: ESC ] ... BEL or ESC \
            const osc = /^\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/.exec(text.slice(i));
            if (osc) { i += osc[0].length; continue; }
            // Two-char escape (e.g. ESC =).
            if (i + 1 < text.length) { i += 2; continue; }
            i += 1;
        }
        if (openSpan) out += '</span>';
        return out;
    }
};
