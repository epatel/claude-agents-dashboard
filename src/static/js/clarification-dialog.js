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
                this._showPending(itemId, data);
            } else {
                // No pending clarification, show regular detail
                DetailDialog._showDetailDirect(itemId);
            }
        } catch (err) {
            console.error('Failed to load clarification:', err);
        }
    },

    /** Prompt prefixes that mark a permission request (`<prefix><name>|<reason>`), and their dialog. */
    _requestPrefixes: {
        '__permission_request__|': 'showPermissionRequest',
        '__tool_request__|': 'showToolPermissionRequest',
    },

    _showPending(itemId, data) {
        const prompt = data.prompt;
        const prefix = prompt && Object.keys(this._requestPrefixes).find((p) => prompt.startsWith(p));
        if (prefix) {
            const parts = prompt.split('|');
            this[this._requestPrefixes[prefix]](itemId, parts[1] || '', parts.slice(2).join('|') || '');
            return;
        }
        const choices = data.choices ? JSON.parse(data.choices) : [];
        this.showClarification(itemId, prompt || '(Agent is waiting for your response)', choices, data.context);
    },

    showClarification(itemId, prompt, choices, context) {
        this._restoreFormHTML();
        document.getElementById('clarify-item-id').value = itemId;
        const promptEl = document.getElementById('clarify-prompt');
        promptEl.innerHTML = DialogUtils.renderMarkdown(prompt);
        DialogUtils.runMermaid(promptEl);
        document.getElementById('clarify-response').value = '';

        const contextGroup = document.getElementById('clarify-context-group');
        const contextEl = document.getElementById('clarify-context');
        if (contextGroup && contextEl) {
            const ctxStr = (context == null) ? '' : String(context).trim();
            if (ctxStr) {
                contextEl.innerHTML = DialogUtils.renderMarkdown(ctxStr);
                DialogUtils.runMermaid(contextEl);
                contextGroup.style.display = '';
            } else {
                contextEl.innerHTML = '';
                contextGroup.style.display = 'none';
            }
        }

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
        this._showAccessRequest(itemId, reason,
            { kind: 'command', label: 'Command', value: command, approve: 'approveCommand', deny: 'denyCommand' });
    },

    approveCommand(itemId, command) {
        return this._answerAccessRequest(itemId, { approved: true, command: command });
    },

    denyCommand(itemId) {
        return this._answerAccessRequest(itemId, { approved: false });
    },

    showToolPermissionRequest(itemId, toolName, reason) {
        this._showAccessRequest(itemId, reason,
            { kind: 'tool', label: 'Tool', value: toolName, approve: 'approveTool', deny: 'denyTool' });
    },

    approveTool(itemId, toolName) {
        return this._answerAccessRequest(itemId, { approved: true, command: toolName });
    },

    denyTool(itemId) {
        return this._answerAccessRequest(itemId, { approved: false });
    },

    /** Command / tool permission prompt: Allow and Deny call ClarificationDialog[approve / deny]. */
    _showAccessRequest(itemId, reason, { kind, label, value, approve, deny }) {
        this._saveFormHTML();
        const form = document.getElementById('clarify-form');
        form.innerHTML = `
            <div class="form-group">
                <div style="margin-bottom: 12px;">
                    <strong>Agent requests ${kind} access</strong>
                </div>
                <div style="margin-bottom: 8px;">
                    ${label}: <code style="background:var(--bg-secondary);padding:2px 6px;border-radius:4px;">${value}</code>
                </div>
                <div style="margin-bottom: 16px; color: var(--text-muted);">
                    Reason: ${reason}
                </div>
            </div>
            <div class="modal-footer" style="display:flex;gap:8px;">
                <button type="button" class="btn btn-primary" onclick="ClarificationDialog.${approve}('${itemId}', '${value}')">
                    Allow
                </button>
                <button type="button" class="btn" onclick="ClarificationDialog.${deny}('${itemId}')">
                    Deny
                </button>
            </div>
        `;
        DialogCore.open('clarify-dialog');
    },

    async _answerAccessRequest(itemId, body) {
        await Api.request('POST', '/api/items/' + itemId + '/approve-command', body);
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