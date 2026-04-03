/**
 * Questions dialog functionality — handles agent questions and permission requests
 */
const ClarificationDialog = {
    _originalFormHTML: null,

    _saveFormHTML() {
        if (!this._originalFormHTML) {
            this._originalFormHTML = document.getElementById('clarify-form').innerHTML;
        }
    },

    _restoreFormHTML() {
        if (this._originalFormHTML) {
            document.getElementById('clarify-form').innerHTML = this._originalFormHTML;
            this._originalFormHTML = null;
        }
    },

    async reopenClarification(itemId) {
        // Check if this is a merge_blocked item
        const item = Board.items[itemId];
        if (item && item.status === 'merge_blocked') {
            this.showMergeBlocked(itemId,
                'Cannot merge because the target repo has uncommitted changes. '
                + 'Please commit or stash your changes, then try again.');
            return;
        }

        // Fetch pending clarification from DB
        try {
            const data = await Api.request('GET', `/api/items/${itemId}/clarification`);
            if (data && data.id) {
                // Check if this is a permission request
                if (data.prompt && data.prompt.startsWith('__permission_request__|')) {
                    const parts = data.prompt.split('|');
                    const command = parts[1] || '';
                    const reason = parts.slice(2).join('|') || '';
                    this.showPermissionRequest(itemId, command, reason);
                } else if (data.prompt && data.prompt.startsWith('__tool_request__|')) {
                    const parts = data.prompt.split('|');
                    const toolName = parts[1] || '';
                    const reason = parts.slice(2).join('|') || '';
                    this.showToolPermissionRequest(itemId, toolName, reason);
                } else {
                    const choices = data.choices ? JSON.parse(data.choices) : [];
                    this.showClarification(itemId, data.prompt || '(Agent is waiting for your response)', choices);
                }
            } else {
                // No pending clarification, show regular detail
                DetailDialog._showDetailDirect(itemId);
            }
        } catch (err) {
            console.error('Failed to load clarification:', err);
        }
    },

    showClarification(itemId, prompt, choices) {
        this._restoreFormHTML();
        document.getElementById('clarify-item-id').value = itemId;
        document.getElementById('clarify-prompt').innerHTML = DialogUtils.renderMarkdown(prompt);
        document.getElementById('clarify-response').value = '';

        const choicesEl = document.getElementById('clarify-choices');
        if (choices && choices.length > 0) {
            choicesEl.innerHTML = choices.map(c =>
                `<button class="btn btn-sm" style="margin: 4px 8px;" onclick="document.getElementById('clarify-response').value='${c.replace(/'/g, "\\'")}';">${c}</button>`
            ).join('');
        } else {
            choicesEl.innerHTML = '';
        }

        DialogCore.open('clarify-dialog');
    },

    showPermissionRequest(itemId, command, reason) {
        this._saveFormHTML();
        const form = document.getElementById('clarify-form');
        form.innerHTML = `
            <div class="form-group">
                <div style="margin-bottom: 12px;">
                    <strong>Agent requests command access</strong>
                </div>
                <div style="margin-bottom: 8px;">
                    Command: <code style="background:var(--bg-secondary);padding:2px 6px;border-radius:4px;">${command}</code>
                </div>
                <div style="margin-bottom: 16px; color: var(--text-muted);">
                    Reason: ${reason}
                </div>
            </div>
            <div class="modal-footer" style="display:flex;gap:8px;">
                <button type="button" class="btn btn-primary" onclick="ClarificationDialog.approveCommand('${itemId}', '${command}')">
                    Allow
                </button>
                <button type="button" class="btn" onclick="ClarificationDialog.denyCommand('${itemId}')">
                    Deny
                </button>
            </div>
        `;
        DialogCore.open('clarify-dialog');
    },

    async approveCommand(itemId, command) {
        await Api.request('POST', '/api/items/' + itemId + '/approve-command', {
            approved: true, command: command
        });
        DialogCore.close('clarify-dialog');
        this._restoreFormHTML();
    },

    async denyCommand(itemId) {
        await Api.request('POST', '/api/items/' + itemId + '/approve-command', {
            approved: false
        });
        DialogCore.close('clarify-dialog');
        this._restoreFormHTML();
    },

    showToolPermissionRequest(itemId, toolName, reason) {
        this._saveFormHTML();
        const form = document.getElementById('clarify-form');
        form.innerHTML = `
            <div class="form-group">
                <div style="margin-bottom: 12px;">
                    <strong>Agent requests tool access</strong>
                </div>
                <div style="margin-bottom: 8px;">
                    Tool: <code style="background:var(--bg-secondary);padding:2px 6px;border-radius:4px;">${toolName}</code>
                </div>
                <div style="margin-bottom: 16px; color: var(--text-muted);">
                    Reason: ${reason}
                </div>
            </div>
            <div class="modal-footer" style="display:flex;gap:8px;">
                <button type="button" class="btn btn-primary" onclick="ClarificationDialog.approveTool('${itemId}', '${toolName}')">
                    Allow
                </button>
                <button type="button" class="btn" onclick="ClarificationDialog.denyTool('${itemId}')">
                    Deny
                </button>
            </div>
        `;
        DialogCore.open('clarify-dialog');
    },

    async approveTool(itemId, toolName) {
        await Api.request('POST', '/api/items/' + itemId + '/approve-command', {
            approved: true, command: toolName
        });
        DialogCore.close('clarify-dialog');
        this._restoreFormHTML();
    },

    async denyTool(itemId) {
        await Api.request('POST', '/api/items/' + itemId + '/approve-command', {
            approved: false
        });
        DialogCore.close('clarify-dialog');
        this._restoreFormHTML();
    },

    showMergeBlocked(itemId, message) {
        this._saveFormHTML();
        const form = document.getElementById('clarify-form');
        form.innerHTML = `
            <div class="form-group">
                <div style="margin-bottom: 12px;">
                    <strong>Merge blocked</strong>
                </div>
                <div style="margin-bottom: 16px; color: var(--text-secondary);">
                    ${message}
                </div>
            </div>
            <div class="modal-footer" style="display:flex;gap:8px;">
                <button type="button" class="btn btn-primary" onclick="ClarificationDialog.retryMerge('${itemId}')">
                    Fixed, try again
                </button>
                <button type="button" class="btn" onclick="DialogCore.close('clarify-dialog'); ClarificationDialog._restoreFormHTML();">
                    Dismiss
                </button>
            </div>
        `;
        DialogCore.open('clarify-dialog');
    },

    async retryMerge(itemId) {
        DialogCore.close('clarify-dialog');
        this._restoreFormHTML();
        try {
            await Api.request('POST', `/api/items/${itemId}/retry-merge`);
        } catch (err) {
            console.error('Failed to retry merge:', err);
        }
    },

    async submitClarification(event) {
        event.preventDefault();
        const itemId = document.getElementById('clarify-item-id').value;
        const response = document.getElementById('clarify-response').value.trim();
        if (!response) return;

        try {
            await Api.request('POST', `/api/items/${itemId}/clarify`, { response });
            DialogCore.close('clarify-dialog');
        } catch (err) {
            console.error('Failed to submit clarification:', err);
        }
    },
};