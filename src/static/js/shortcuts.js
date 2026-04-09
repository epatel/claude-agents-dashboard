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
        document.getElementById('shortcut-progress-command').textContent = `$ ${sc.command}`;
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
        outputEl.textContent = state.output || '(waiting for output...)';
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
                    <code class="shortcut-manage-cmd">${this._esc(sc.command)}</code>
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

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }
};
