// Shortcuts bar — quick-launch bash commands from the bottom bar
const Shortcuts = {
    shortcuts: [],
    _pollTimers: {},    // shortcut_id → interval timer
    _runState: {},      // shortcut_id → { status, output, exit_code }
    _autoReset: {},     // shortcut_id → true if auto-reset enabled

    /** Per run status: status line, CSS suffix (status line + bar button), reset button label. */
    _statusViews: {
        running: { text: () => '⟳ Running...', cls: 'running', resetLabel: 'Stop' },
        failed: { text: (s) => `✕ Failed (exit code: ${s.exit_code})`, cls: 'failed', resetLabel: 'Reset' },
        stopped: { text: () => '⏹ Stopped', cls: 'failed', resetLabel: 'Reset' },
        done: { text: () => '✓ Completed', cls: 'done', resetLabel: 'Reset' },
    },

    _statusView(state) {
        return state && Object.hasOwn(this._statusViews, state.status) ? this._statusViews[state.status] : null;
    },

    _isRunning(state) {
        return !!state && state.status === 'running';
    },

    /** A run that already has something to show: still running, or finished with output. */
    _hasRunToShow(state) {
        if (this._isRunning(state)) return true;
        return this._statusView(state) !== null && !!state.output;
    },

    _stopPolling(id) {
        if (!this._pollTimers[id]) return;
        clearInterval(this._pollTimers[id]);
        delete this._pollTimers[id];
    },

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
            btns.appendChild(this._shortcutButton(sc));
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

    _shortcutButton(sc) {
        const btn = document.createElement('button');
        btn.className = 'shortcut-btn';
        btn.textContent = sc.name;
        btn.title = sc.command;
        btn.dataset.id = sc.id;
        btn.dataset.mapName = 'shortcuts.btn-shortcut';
        // Reflect current run state
        const view = this._statusView(this._runState[sc.id]);
        if (view) btn.classList.add(`shortcut-${view.cls}`);
        btn.addEventListener('click', () => this.runOrShow(sc));
        return btn;
    },

    async runOrShow(sc) {
        // Already running, or a finished log: show it instead of re-running
        if (this._hasRunToShow(this._runState[sc.id])) {
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
        this._stopPolling(sc.id);

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
                    this._stopPolling(sc.id);

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
        if (this._isRunning(this._runState[sc.id]) && !this._pollTimers[sc.id]) {
            this._startPolling(sc);
        }
    },

    _updateProgressContent(shortcutId) {
        const dialog = document.getElementById('shortcut-progress-dialog');
        if (!this._isShowing(dialog, shortcutId)) return;

        const state = this._runState[shortcutId] || { status: 'idle', output: '', exit_code: null };
        this._renderProgressOutput(state.output);
        this._renderProgressButtons(state);
        this._renderProgressStatus(state);
    },

    _isShowing(dialog, shortcutId) {
        if (!dialog || !dialog.open) return false;
        return dialog.dataset.shortcutId === shortcutId;
    },

    /** Output, kept scrolled to the bottom if it was there. */
    _renderProgressOutput(output) {
        const outputEl = document.getElementById('shortcut-progress-output');
        const isAtBottom = outputEl.scrollHeight - outputEl.scrollTop - outputEl.clientHeight < 30;
        if (output) {
            outputEl.innerHTML = this._ansiToHtml(output);
        } else {
            outputEl.textContent = '(waiting for output...)';
        }
        if (isAtBottom) {
            outputEl.scrollTop = outputEl.scrollHeight;
        }
    },

    /** Stop while running, Reset once finished; Auto-reset only while running. */
    _renderProgressButtons(state) {
        const view = this._statusView(state);
        const resetBtn = document.getElementById('shortcut-reset-btn');
        if (resetBtn) {
            if (view) resetBtn.textContent = view.resetLabel;
            resetBtn.style.display = view ? '' : 'none';
        }
        const autoResetBtn = document.getElementById('shortcut-auto-reset-btn');
        if (autoResetBtn) {
            autoResetBtn.style.display = state.status === 'running' ? '' : 'none';
        }
    },

    _renderProgressStatus(state) {
        const statusEl = document.getElementById('shortcut-progress-status');
        const view = this._statusView(state);
        statusEl.textContent = view ? view.text(state) : '';
        statusEl.className = view ? `shortcut-status shortcut-status-${view.cls}` : 'shortcut-status';
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

        if (this._isRunning(this._runState[id])) {
            // Stop the process but keep the log visible
            try {
                await Api.request('POST', `/api/shortcuts/${id}/stop`);
            } catch { /* ignore */ }
            // Let polling pick up the stopped state and update UI
            return;
        }

        // Reset: clear everything (for stopped/done/failed states)

        this._stopPolling(id);

        // Reset server-side state
        try {
            await Api.request('POST', `/api/shortcuts/${id}/reset`);
        } catch { /* ignore */ }

        // Clear client-side state
        delete this._runState[id];

        // Reset dialog UI
        document.getElementById('shortcut-progress-output').textContent = '(waiting for output...)';
        this._renderProgressStatus({ status: 'idle' });

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
        const fields = this._formFields('shortcut-add');
        if (!fields) return;
        await this._save(() => Api.request('POST', '/api/shortcuts', fields),
            () => this.closeAddDialog(), 'Failed to add shortcut: ', false);
    },

    /** Trimmed name and command from ``<prefix>-name`` / ``<prefix>-command``, or null if either is empty. */
    _formFields(prefix) {
        const name = document.getElementById(`${prefix}-name`).value.trim();
        const command = document.getElementById(`${prefix}-command`).value.trim();
        if (!name || !command) return null;
        return { name, command };
    },

    /** Send a change, then close its dialog and reload; alert on failure. */
    async _save(request, close, failureMessage, refreshManageList) {
        try {
            await request();
            close();
            await this.load();
            this.render();
            if (refreshManageList) this._renderManageList();
        } catch (e) {
            alert(failureMessage + e.message);
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
            this._stopPolling(id);
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

        const fields = this._formFields('shortcut-edit');
        if (!fields) return;
        await this._save(() => Api.request('PUT', `/api/shortcuts/${id}`, fields),
            () => this.closeEditDialog(), 'Failed to update shortcut: ', true);
    },

    _setupCtrlEnter(textareaId, dialog) {
        const ta = document.getElementById(textareaId);
        if (!ta) return;
        // Remove previous listener if any
        if (ta._ctrlEnterHandler) ta.removeEventListener('keydown', ta._ctrlEnterHandler);
        ta._ctrlEnterHandler = (e) => {
            if (this._isCtrlEnter(e)) {
                e.preventDefault();
                const form = ta.closest('form');
                if (form) form.requestSubmit();
            }
        };
        ta.addEventListener('keydown', ta._ctrlEnterHandler);
    },

    _isCtrlEnter(e) {
        if (e.key !== 'Enter') return false;
        return e.ctrlKey || e.metaKey;
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

        // Walk the text: plain runs are escaped, escape sequences update the style.
        const r = { out: '', openSpan: false, style: this._plainStyle() };
        let i = 0;
        while (i < text.length) {
            i = text[i] === this._ESC ? this._ansiEscape(text, i, r) : this._ansiText(text, i, r);
        }
        if (r.openSpan) r.out += '</span>';
        return r.out;
    },

    _ESC: '\u001b',

    /** The 16 system colors: 30–37 / 40–47, then the bright 90–97 / 100–107. */
    _ansiPalette: [
        '#000000', '#cd3131', '#0dbc79', '#e5e510', '#2472c8', '#bc3fbc', '#11a8cd', '#e5e5e5',
        '#666666', '#f14c4c', '#23d18b', '#f5f543', '#3b8eea', '#d670d6', '#29b8db', '#ffffff',
    ],

    _sgrChanges: null,  // SGR code → style fields it sets; built on first use

    _sgrChange(code) {
        if (!this._sgrChanges) this._sgrChanges = this._buildSgrChanges();
        return this._sgrChanges[code];
    },

    _buildSgrChanges() {
        const changes = {
            1: { bold: true }, 2: { dim: true }, 3: { italic: true }, 4: { underline: true },
            22: { bold: false, dim: false }, 23: { italic: false }, 24: { underline: false },
            39: { fg: null }, 49: { bg: null },
        };
        this._ansiPalette.forEach((color, n) => {
            const fg = n < 8 ? 30 + n : 90 + n - 8;
            changes[fg] = { fg: color };
            changes[fg + 10] = { bg: color };
        });
        return changes;
    },

    _plainStyle() {
        return { fg: null, bg: null, bold: false, dim: false, italic: false, underline: false };
    },

    // xterm 256-color palette: 0-15 (system) + 16-231 (216 cube) + 232-255 (grayscale)
    _palette256(n) {
        if (n < 16) return this._ansiPalette[n];
        if (n < 232) {
            n -= 16;
            const r = Math.floor(n / 36), g = Math.floor((n % 36) / 6), b = n % 6;
            const c = (v) => v === 0 ? 0 : 55 + v * 40;
            return `rgb(${c(r)},${c(g)},${c(b)})`;
        }
        const v = 8 + (n - 232) * 10;
        return `rgb(${v},${v},${v})`;
    },

    /** Extended color at ``codes[i]``: 38;5;N (256-color) or 38;2;R;G;B (truecolor). */
    _extendedColor(codes, i) {
        const mode = codes[i + 1];
        if (mode === 5 && codes[i + 2] !== undefined) {
            return { color: this._palette256(codes[i + 2]), used: 2 };
        }
        if (mode === 2 && codes[i + 4] !== undefined) {
            return { color: `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`, used: 4 };
        }
        return null;
    },

    // Apply one SGR parameter list (e.g. "1;31" or "38;5;202") to `style`; returns the new style.
    _applySGR(style, params) {
        const codes = params === '' ? [0] : params.split(';').map(Number);
        for (let i = 0; i < codes.length; i++) {
            const c = codes[i];
            if (c === 0 || Number.isNaN(c)) {
                style = this._plainStyle();
                continue;
            }
            const ext = (c === 38 || c === 48) ? this._extendedColor(codes, i) : null;
            if (ext) {
                style[c === 38 ? 'fg' : 'bg'] = ext.color;
                i += ext.used;
            } else {
                Object.assign(style, this._sgrChange(c));
            }
        }
        return style;
    },

    _styleActive(s) {
        return s.fg || s.bg || s.bold || s.dim || s.italic || s.underline;
    },

    _styleCss(s) {
        const parts = [];
        if (s.fg) parts.push(`color:${s.fg}`);
        if (s.bg) parts.push(`background-color:${s.bg}`);
        if (s.bold) parts.push('font-weight:bold');
        if (s.dim) parts.push('opacity:0.7');
        if (s.italic) parts.push('font-style:italic');
        if (s.underline) parts.push('text-decoration:underline');
        return parts.join(';');
    },

    /** Plain text up to the next ESC; returns where it ended. */
    _ansiText(text, i, r) {
        const next = text.indexOf(this._ESC, i);
        const end = next === -1 ? text.length : next;
        const escaped = this._esc(text.slice(i, end));
        if (!this._styleActive(r.style)) {
            this._closeSpan(r);
        } else if (!r.openSpan) {
            r.out += `<span style="${this._styleCss(r.style)}">`;
            r.openSpan = true;
        }
        r.out += escaped;
        return end;
    },

    _closeSpan(r) {
        if (r.openSpan) { r.out += '</span>'; r.openSpan = false; }
    },

    /**
     * One escape sequence at ``text[i]``; returns where it ended. SGR (CSI … m)
     * changes the style; other CSI (cursor moves, erase, …) and OSC
     * (ESC ] … BEL or ESC \) sequences are stripped.
     */
    _ansiEscape(text, i, r) {
        const rest = text.slice(i);
        const csi = /^\u001b\[([0-9;?]*)([@-~])/.exec(rest);
        if (csi) {
            if (csi[2] === 'm') {
                this._closeSpan(r);
                r.style = this._applySGR(r.style, csi[1]);
            }
            return i + csi[0].length;
        }
        const osc = /^\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/.exec(rest);
        if (osc) return i + osc[0].length;
        // Two-char escape (e.g. ESC =), or a lone ESC at the end.
        return i + 1 < text.length ? i + 2 : i + 1;
    },
};
