/**
 * Configuration dialog functionality
 */
const ConfigDialog = {
    // Plugins state
    _configPlugins: [],

    // Allowed commands state
    _configAllowedCommands: [],

    // Built-in tools state
    _configBuiltinTools: [],
    _availableBuiltinTools: [],

    // Cached Ollama models
    _ollamaModels: [],
    _ollamaEnabled: false,

    switchConfigTab(tabName) {
        DialogUtils.markActiveTab('#config-dialog .review-tab', tabName);
        document.querySelectorAll('#config-dialog .config-tab-content').forEach(c => {
            c.style.display = c.dataset.configTab === tabName ? '' : 'none';
        });
    },

    async openConfig() {
        try {
            const config = await Api.request('GET', '/api/config');
            this._loadGeneral(config);
            this._loadOllama(config);
            this._loadTiiny(config);
            this._configPlugins = this._parseJsonList(config.plugins);
            this._renderPluginsList();
            this._loadAllowedCommands(config);
            await this._loadBuiltinTools(config);
            this._loadFlame(config);
            this._loadGraphify(config);
            // Load skills library (installed + enabled flags)
            this.refreshSkills();
            await this._populateConfigModels(config);

            this.switchConfigTab('general');
            DialogCore.open('config-dialog');
        } catch (err) {
            console.error('Failed to load config:', err);
        }
    },

    _el(id) {
        return document.getElementById(id);
    },

    /** A JSON list stored as a string (``[]`` when missing or malformed). */
    _parseJsonList(json) {
        try {
            return JSON.parse(json || '[]');
        } catch {
            return [];
        }
    },

    /** Settings that default to on: only an explicit false / 0 turns them off. */
    _defaultOn(value) {
        return value !== false && value !== 0;
    },

    _loadGeneral(config) {
        this._el('config-model').value = config.model || window.__DEFAULT_MODEL__;
        this._el('config-wip-limit').value = config.wip_limit || 0;
        this._el('config-system-prompt').value = config.system_prompt || '';
        this._el('config-project-context').value = config.project_context || '';
        this._el('config-mcp-enabled').checked = !!config.mcp_enabled;
        const mcpServers = config.mcp_servers || '{}';
        this._el('config-mcp-servers').value = typeof mcpServers === 'object' ? JSON.stringify(mcpServers, null, 2) : mcpServers;
    },

    _loadOllama(config) {
        this._el('config-ollama-enabled').checked = !!config.ollama_enabled;
        this._el('config-ollama-base-url').value = config.ollama_base_url || window.__DEFAULT_OLLAMA_URL__;
        this._el('config-ollama-load-claude-md').checked = !!config.ollama_load_claude_md;

        // Reset connection status
        const statusEl = this._el('ollama-connection-status');
        if (statusEl) statusEl.innerHTML = '';

        // Auto-fetch Ollama models if enabled (experimental only)
        if (config.ollama_enabled && window.__EXPERIMENTAL__) {
            this.refreshOllamaModels();
        }
    },

    _loadTiiny(config) {
        this._el('config-tiiny-enabled').checked = !!config.tiiny_enabled;
        this._el('config-tiiny-base-url').value = config.tiiny_base_url || window.__DEFAULT_TIINY_URL__;
        this._el('config-tiiny-load-claude-md').checked = !!config.tiiny_load_claude_md;
        this._setTiinyStatus('', '');
        this._el('tiiny-test-result').innerHTML = '';
        if (config.tiiny_enabled && window.__EXPERIMENTAL__) {
            this.refreshTiinyModels();
        }
    },

    _loadAllowedCommands(config) {
        this._configAllowedCommands = this._parseJsonList(config.allowed_commands);
        this._el('config-bash-yolo').checked = !!config.bash_yolo;
        this._renderAllowedCommandsList();
        this._updateYoloState(!!config.bash_yolo);
    },

    _defaultBuiltinTools: [
        {name: 'WebSearch', label: 'Web Search', description: 'Search the web for information'},
        {name: 'WebFetch', label: 'Web Fetch', description: 'Fetch content from URLs'},
    ],

    async _loadBuiltinTools(config) {
        this._configBuiltinTools = this._parseJsonList(config.allowed_builtin_tools);
        try {
            this._availableBuiltinTools = await Api.request('GET', '/api/config/available-tools');
        } catch {
            this._availableBuiltinTools = this._defaultBuiltinTools.map(tool => ({ ...tool }));
        }
        this._renderBuiltinToolsList();
    },

    _loadFlame(config) {
        this._el('config-flame-enabled').checked = this._defaultOn(config.flame_enabled);
        const intensityVal = parseFloat(config.flame_intensity_multiplier) || 1.0;
        this._el('config-flame-intensity').value = intensityVal;
        this._el('config-flame-intensity-value').textContent = intensityVal.toFixed(1);
    },

    _loadGraphify(config) {
        this._el('config-graphify-enabled').checked = config.graphify_enabled === true || config.graphify_enabled === 1;
        this._el('config-graphify-auto-refresh').checked = this._defaultOn(config.graphify_auto_refresh);
        this._el('config-graphify-backend').value = config.graphify_backend || 'ast';
        this.refreshGraphifyStatus();
    },

    /** Add the local-provider models to the config model dropdown. */
    async _populateConfigModels(config) {
        const select = this._el('config-model');
        if (config.ollama_enabled && this._ollamaModels.length > 0) {
            this._updateModelSelect('config-model', false);
        } else {
            // Still populate from shared cache
            await DialogUtils.populateOllamaOptions(select);
        }
        await DialogUtils.populateTiinyOptions(select);
    },

    _renderPluginsList() {
        const container = document.getElementById('config-plugins-list');
        if (this._configPlugins.length === 0) {
            container.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:8px 0;">No plugins configured. Add plugin directory paths below.</div>';
            return;
        }
        container.innerHTML = this._configPlugins.map((p, i) => {
            const path = typeof p === 'string' ? p : p.path;
            return `<div class="plugin-entry" style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:4px;">
                <span style="font-family:var(--font-mono);font-size:12px;flex:1;word-break:break-all;">${path}</span>
                <button type="button" class="btn btn-xs" onclick="ConfigDialog.removePlugin(${i})" title="Remove plugin" style="opacity:0.6;min-width:auto;">&#10005;</button>
            </div>`;
        }).join('');
    },

    addPlugin() {
        const input = document.getElementById('config-plugin-path-input');
        const path = input.value.trim();
        if (!path) return;

        this._configPlugins.push({ path });
        this._renderPluginsList();
        input.value = '';
    },

    removePlugin(index) {
        this._configPlugins.splice(index, 1);
        this._renderPluginsList();
    },

    _renderAllowedCommandsList() {
        const container = document.getElementById('config-allowed-commands-list');
        if (this._configAllowedCommands.length === 0) {
            container.innerHTML = '<div class="text-muted" style="font-size:13px;">No commands configured. Agents can request access at runtime.</div>';
            return;
        }
        container.innerHTML = this._configAllowedCommands.map((cmd, i) => `
            <div class="plugin-entry" style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                <code style="flex:1;background:var(--bg-secondary);padding:2px 8px;border-radius:4px;">${cmd}</code>
                <button class="btn btn-sm" onclick="ConfigDialog.removeAllowedCommand(${i})" title="Remove">&#10005;</button>
            </div>
        `).join('');
    },

    addAllowedCommand() {
        const input = document.getElementById('config-allowed-command-input');
        const cmd = input.value.trim().split(/\s+/)[0];
        if (!cmd) return;
        if (this._configAllowedCommands.includes(cmd)) return;
        this._configAllowedCommands.push(cmd);
        this._renderAllowedCommandsList();
        input.value = '';
    },

    removeAllowedCommand(index) {
        this._configAllowedCommands.splice(index, 1);
        this._renderAllowedCommandsList();
    },

    async toggleYolo(checked) {
        if (checked) {
            const confirmed = await DialogCore.confirm(
                'YOLO mode grants agents unrestricted bash access with no permission checks. '
                + 'All commands will be logged but cannot be blocked. '
                + 'Only enable this in trusted environments.',
                '⚠️ Enable YOLO Mode?',
                'Enable YOLO Mode'
            );
            if (!confirmed) {
                document.getElementById('config-bash-yolo').checked = false;
                return;
            }
        }
        this._updateYoloState(checked);
    },

    _updateYoloState(yolo) {
        const list = document.getElementById('config-allowed-commands-list');
        const input = document.getElementById('config-allowed-command-input');
        const addBtn = input?.nextElementSibling;
        if (list) list.style.opacity = yolo ? '0.4' : '1';
        if (input) input.disabled = yolo;
        if (addBtn) addBtn.disabled = yolo;
    },

    _renderBuiltinToolsList() {
        const container = document.getElementById('config-builtin-tools-list');
        if (!container) return;
        if (this._availableBuiltinTools.length === 0) {
            container.innerHTML = '<div class="text-muted" style="font-size:13px;">No optional tools available.</div>';
            return;
        }
        container.innerHTML = this._availableBuiltinTools.map(tool => {
            const checked = this._configBuiltinTools.includes(tool.name) ? 'checked' : '';
            return `<label style="font-size:12px;font-weight:normal;margin-top:8px;">
                ${tool.label}
                <input type="checkbox" ${checked} onchange="ConfigDialog.toggleBuiltinTool('${tool.name}', this.checked)" style="cursor:pointer;">
            </label>`;
        }).join('');
    },

    toggleBuiltinTool(name, enabled) {
        if (enabled && !this._configBuiltinTools.includes(name)) {
            this._configBuiltinTools.push(name);
        } else if (!enabled) {
            this._configBuiltinTools = this._configBuiltinTools.filter(t => t !== name);
        }
    },

    /** A status dot (connected / checking / disconnected) plus a message. */
    _statusDotHtml(state, message) {
        const dotCls = state === 'connected' || state === 'checking' ? state : 'disconnected';
        return `<span class="ollama-status-dot ${dotCls}"></span>${message || ''}`;
    },

    _updateConnectionStatus(state, message) {
        const el = this._el('ollama-connection-status');
        if (el) el.innerHTML = this._statusDotHtml(state, message);
    },

    /** Escape text for HTML (falsy values render as empty). */
    _escText(s) {
        return String(s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    },

    _warningHtml(message) {
        return `<span style="color:var(--warning);">⚠ ${message}</span>`;
    },

    _mutedHtml(message) {
        return `<span style="color:var(--text-muted);">${message}</span>`;
    },

    /** Register display names for fetched local models. */
    _rememberModelNames(models) {
        for (const m of models) {
            window.__MODEL_NAMES__[m.name] = m.display_name;
        }
    },

    async refreshOllamaModels() {
        const listEl = this._el('ollama-models-list');
        if (listEl) listEl.innerHTML = this._mutedHtml('Fetching models…');
        this._updateConnectionStatus('checking', 'Connecting…');

        try {
            const result = await Api.request('GET', '/api/ollama/models?force=true');
            this._ollamaModels = result.models || [];
            this._ollamaEnabled = result.enabled !== false;

            const count = this._ollamaModels.length;
            if (result.error) {
                this._updateConnectionStatus('disconnected', 'Not available');
            } else {
                this._updateConnectionStatus('connected', `Connected (${count} model${count !== 1 ? 's' : ''})`);
            }
            if (listEl) listEl.innerHTML = this._ollamaListHtml(result.error, this._ollamaModels);

            this._rememberModelNames(this._ollamaModels);
            // Sync with shared DialogUtils cache
            DialogUtils._ollamaCache = {
                models: this._ollamaModels,
                enabled: this._ollamaEnabled,
                fetched: true,
            };
            // Update all model dropdowns
            this._updateModelDropdowns();
        } catch (err) {
            console.error('Failed to fetch Ollama models:', err);
            this._updateConnectionStatus('disconnected', 'Not available');
            if (listEl) listEl.innerHTML = this._warningHtml('Failed to fetch models');
        }
    },

    _ollamaListHtml(error, models) {
        if (error) return this._warningHtml(error);
        if (models.length === 0) {
            return this._mutedHtml('No models found. Pull one with: <code>ollama pull qwen3.5</code>');
        }
        return models.map(m => this._ollamaModelRow(m)).join('');
    },

    _ollamaModelRow(m) {
        const sizeGB = m.size ? (m.size / 1e9).toFixed(1) + ' GB' : '';
        return `<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:3px;">
                            <code style="flex:1;font-size:12px;">${m.name}</code>
                            <span style="font-size:11px;color:var(--text-muted);">${m.parameter_size || ''}</span>
                            <span style="font-size:11px;color:var(--text-muted);">${m.quantization_level || ''}</span>
                            <span style="font-size:11px;color:var(--text-muted);">${sizeGB}</span>
                        </div>`;
    },

    _setTiinyStatus(state, message) {
        const el = this._el('tiiny-connection-status');
        if (el) el.innerHTML = state ? this._statusDotHtml(state, message) : '';
    },

    async refreshTiinyModels() {
        const listEl = this._el('tiiny-models-list');
        const keyEl = this._el('tiiny-key-status');
        if (listEl) listEl.innerHTML = this._mutedHtml('Fetching models…');
        this._setTiinyStatus('checking', 'Connecting…');
        try {
            const result = await Api.request('GET', '/api/tiiny/models?force=true');
            const models = result.models || [];
            if (keyEl) keyEl.innerHTML = this._tiinyKeyHtml(result.key_present);
            this._setTiinyStatus(...(result.error ? ['disconnected', 'Not available'] : ['connected', 'Reachable']));
            if (listEl) listEl.innerHTML = this._tiinyListHtml(result.error, models);
            this._rememberModelNames(models);
            DialogUtils._tiinyCache = { models, enabled: result.enabled !== false, fetched: true };
            this._updateModelDropdowns();
        } catch (err) {
            console.error('Failed to fetch Tiiny models:', err);
            this._setTiinyStatus('disconnected', 'Not available');
            if (listEl) listEl.innerHTML = this._warningHtml('Failed to fetch models');
        }
    },

    _tiinyKeyHtml(keyPresent) {
        return keyPresent
            ? '<span style="color:var(--success, #4caf50);">✓ API key found</span>'
            : this._warningHtml('No API key found');
    },

    _tiinyListHtml(error, models) {
        const rows = models.map(m => `<div style="padding:4px 8px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:3px;"><code style="font-size:12px;">${this._escText(m.name)}</code></div>`).join('');
        return (error ? `<div style="color:var(--warning);margin-bottom:4px;">⚠ ${this._escText(error)}</div>` : '') + rows;
    },

    async testTiinyConnection() {
        const out = this._el('tiiny-test-result');
        if (out) out.innerHTML = this._mutedHtml('Sending "Reply with the word OK"… (first call after a model load can be slow)');
        try {
            const result = await Api.request('POST', '/api/tiiny/test', {
                base_url: this._el('config-tiiny-base-url').value,
            });
            if (out) {
                out.innerHTML = result.ok
                    ? `<span style="color:var(--success, #4caf50);">✓ ${this._escText(result.model || 'model')} replied: “${this._escText(result.reply)}”</span>`
                    : this._warningHtml(this._escText(result.message));
            }
        } catch (err) {
            if (out) out.innerHTML = this._warningHtml('Test request failed');
        }
    },

    _updateModelDropdowns() {
        // Update both config-model and item-form-model selects
        this._updateModelSelect('config-model', false);
        this._updateModelSelect('item-form-model', true);
    },

    _updateModelSelect(selectId, hasDefaultOption) {
        const select = this._el(selectId);
        if (!select) return;

        // Remember current selection
        const currentValue = select.value;

        // Ollama models if enabled, then Tiiny models (from the shared cache)
        this._replaceOptgroup(select, 'Ollama Models', this._ollamaEnabled ? this._ollamaModels : [], m => {
            const sizeStr = m.size ? ` (${(m.size / 1e9).toFixed(1)}GB)` : '';
            const paramStr = m.parameter_size ? `:${m.parameter_size}` : '';
            return `${m.display_name}${paramStr}${sizeStr}`;
        });
        const tiiny = DialogUtils._tiinyCache;
        this._replaceOptgroup(select, 'Tiiny Models', tiiny.enabled ? tiiny.models : [], m => m.display_name);

        // Restore selection; if the option is gone, fall back
        select.value = currentValue;
        if (select.value !== currentValue) {
            select.value = hasDefaultOption ? '' : select.options[0]?.value || '';
        }
    },

    /** Drop the ``label`` optgroup, then re-add it with ``models`` (none if empty). */
    _replaceOptgroup(select, label, models, optionText) {
        const existing = select.querySelector(`optgroup[label="${label}"]`);
        if (existing) existing.remove();
        if (models.length === 0) return;
        const optgroup = document.createElement('optgroup');
        optgroup.label = label;
        for (const m of models) {
            const opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = optionText(m);
            optgroup.appendChild(opt);
        }
        select.appendChild(optgroup);
    },

    _renderGraphifyStatus(st) {
        const el = this._el('graphify-status');
        const upgradeRow = this._el('graphify-upgrade-row');
        if (!el) return;
        const latest = st.latest_version;
        const behind = latest && st.installed_version && latest !== st.installed_version;
        el.innerHTML = `${this._graphifyVersionHtml(st, behind)}<br>${this._graphLineHtml(st)}`;
        if (upgradeRow) upgradeRow.style.display = behind ? '' : 'none';
    },

    _graphifyVersionHtml(st, behind) {
        const installed = st.installed_version || 'not installed';
        const latest = st.latest_version ? ` · latest ${st.latest_version}` : '';
        const mark = behind ? ' <span style="color:var(--warning);">(update available)</span>' : ' ✓';
        return `graphify ${installed}${latest}${mark}`;
    },

    _graphLineHtml(st) {
        const g = st.graph || {};
        if (st.building) return '<span style="color:var(--accent);">● building…</span>';
        if (!g.exists) return this._mutedHtml('no graph built yet');
        const built = g.last_built ? new Date(g.last_built).toLocaleString() : 'unknown';
        let line = `graph: ${g.nodes} nodes · ${g.edges} edges · ${g.communities} communities<br>last built ${built}`;
        if (g.cost && g.cost.total_output_tokens) {
            line += `<br>semantic cost: ${g.cost.total_output_tokens.toLocaleString()} output tokens`;
        }
        return line;
    },

    async refreshGraphifyStatus() {
        const el = document.getElementById('graphify-status');
        if (el) el.textContent = 'Loading…';
        try {
            const st = await Api.request('GET', '/api/graphify/status');
            this._renderGraphifyStatus(st);
        } catch (err) {
            if (el) el.innerHTML = '<span style="color:var(--warning);">⚠ failed to load status</span>';
        }
    },

    async installGraphify() {
        const confirmed = await DialogCore.confirm(
            'This upgrades the graphify package in the dashboard\'s Python environment. It may take a minute.',
            'Upgrade graphify?',
            'Upgrade'
        );
        if (!confirmed) return;
        const el = document.getElementById('graphify-status');
        if (el) el.textContent = 'Upgrading…';
        try {
            await Api.request('POST', '/api/graphify/install');
        } catch (err) {
            console.error('graphify install failed:', err);
        }
        this.refreshGraphifyStatus();
    },

    async buildGraph(semantic) {
        if (semantic) {
            const confirmed = await DialogCore.confirm(
                'Semantic enrichment runs an LLM over the codebase and can cost hundreds of thousands of tokens. AST builds are free. Continue with semantic?',
                'Build semantic graph?',
                'Build (semantic)'
            );
            if (!confirmed) return;
        }
        try {
            await Api.request('POST', '/api/graphify/build', { semantic: !!semantic });
            const el = document.getElementById('graphify-status');
            if (el) el.innerHTML = '<span style="color:var(--accent);">● building… (progress streams live)</span>';
        } catch (err) {
            console.error('graphify build failed:', err);
        }
    },

    _escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    },

    _renderInstalledSkills(skills) {
        const el = document.getElementById('skills-installed-list');
        if (!el) return;
        if (!skills || skills.length === 0) {
            el.innerHTML = '<div style="color:var(--text-muted);padding:4px 0;">No skills installed yet. Add one below.</div>';
            return;
        }
        this._installedSkills = skills;
        el.innerHTML = skills.map(s => {
            const name = this._escapeHtml(s.name);
            return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 12px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:6px;">
                <span style="display:flex;align-items:center;gap:6px;flex:0 0 auto;min-width:0;max-width:78%;">
                    <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;color:var(--text-primary);">${name}</span>
                    <span title="Details & source" onclick="ConfigDialog.showSkillInfo('${name}')" style="flex:0 0 auto;cursor:pointer;color:var(--text-muted);font-size:13px;line-height:1;">&#9432;</span>
                </span>
                <span style="display:flex;align-items:center;gap:12px;flex:0 0 auto;">
                    <input type="checkbox" ${s.enabled ? 'checked' : ''} title="Enable for this project" onchange="ConfigDialog.toggleSkill('${name}', this.checked)" style="cursor:pointer;margin:0;">
                    <button type="button" class="btn btn-xs" title="Remove from library" onclick="ConfigDialog.removeSkill('${name}')" style="opacity:0.55;min-width:auto;padding:2px 8px;">&#10005;</button>
                </span>
            </div>`;
        }).join('');
    },

    // Shared renderer for installable choices (browse results + multi-skill repos).
    _renderSkillChoices(el, skills, header) {
        if (!el) return;
        const rows = skills.map(s => {
            const name = this._escapeHtml(s.name);
            const desc = this._escapeHtml(s.description || '');
            const spec = this._escapeHtml(s.spec || '');
            const sub = s.path ? this._escapeHtml(s.path) : '';
            return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 12px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:6px;">
                <div style="flex:0 0 auto;min-width:0;max-width:80%;">
                    <div style="font-size:13px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}${sub ? ` <span style="color:var(--text-muted);font-size:11px;">${sub}</span>` : ''}</div>
                    <div style="font-size:11px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${desc}">${desc}</div>
                </div>
                <button type="button" class="btn btn-xs" onclick="ConfigDialog.installExact('${spec}','${name}')" style="flex:0 0 auto;min-width:auto;">Install</button>
            </div>`;
        }).join('');
        const head = header ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">${this._escapeHtml(header)}</div>` : '';
        el.innerHTML = head + rows;
    },

    // Resolve an install spec (owner/repo[/path][@ref] or a URL) to a GitHub URL.
    _sourceUrl(spec) {
        if (!spec) return null;
        if (/^https?:\/\//.test(spec)) return spec;
        let s = spec, ref = null;
        const at = s.lastIndexOf('@');
        if (at > 0) { ref = s.slice(at + 1); s = s.slice(0, at); }
        const parts = s.split('/').filter(Boolean);
        if (parts.length < 2) return null;
        const [owner, repo, ...rest] = parts;
        const path = rest.join('/');
        let url = `https://github.com/${owner}/${repo}`;
        if (ref && path) url += `/tree/${ref}/${path}`;
        else if (ref) url += `/tree/${ref}`;
        else if (path) url += `/tree/HEAD/${path}`;
        return url;
    },

    showSkillInfo(name) {
        const s = (this._installedSkills || []).find(x => x.name === name);
        if (!s) return;
        document.getElementById('skill-info-name').textContent = s.name;
        document.getElementById('skill-info-desc').textContent = s.description || 'No description provided.';
        const srcEl = document.getElementById('skill-info-source');
        if (s.source) {
            const url = this._sourceUrl(s.source);
            srcEl.innerHTML = url
                ? `<a href="${this._escapeHtml(url)}" target="_blank" rel="noopener" style="color:var(--accent);">${this._escapeHtml(s.source)}</a>`
                : this._escapeHtml(s.source);
        } else {
            srcEl.innerHTML = '<span style="color:var(--text-muted);">source not recorded — reinstall to capture</span>';
        }
        DialogCore.open('skill-info-dialog');
    },

    async refreshSkills() {
        const el = document.getElementById('skills-installed-list');
        if (el) el.textContent = 'Loading…';
        try {
            const data = await Api.request('GET', '/api/skills');
            this._renderInstalledSkills(data.installed || []);
        } catch (err) {
            if (el) el.innerHTML = '<span style="color:var(--warning);">⚠ failed to load skills</span>';
        }
    },

    async toggleSkill(name, enabled) {
        try {
            await Api.request('POST', `/api/skills/${encodeURIComponent(name)}/enabled`, { enabled: !!enabled });
        } catch (err) {
            console.error('toggle skill failed:', err);
            this.refreshSkills();
        }
    },

    async removeSkill(name) {
        const confirmed = await DialogCore.confirm(
            `Remove skill "${name}" from the library? It will also be disabled for this project.`,
            'Remove skill?', 'Remove'
        );
        if (!confirmed) return;
        try {
            await Api.request('DELETE', `/api/skills/${encodeURIComponent(name)}`);
        } catch (err) {
            console.error('remove skill failed:', err);
        }
        this.refreshSkills();
    },

    // "Add by URL" — scan the repo/path for SKILL.md files, then install or
    // present a picker when a repo contains more than one skill.
    async installSkill() {
        const input = this._el('skill-add-input');
        const value = (input ? input.value : '').trim();
        if (!value) return;
        const el = this._el('skills-browse-list');
        if (el) el.textContent = 'Scanning repo…';
        const found = await this._discoverSkills(value, el);
        if (!found) return;
        if (found.length > 1) {
            this._renderSkillChoices(el, found, `Found ${found.length} skills — choose which to install:`);
            return;
        }
        if (el) el.innerHTML = '';
        await this.installExact(found[0].spec, found[0].name);
        if (input) input.value = '';
    },

    /** Skills found at ``spec``, or null (with a message in ``el``) when none or the scan failed. */
    async _discoverSkills(spec, el) {
        const found = await Api.request('POST', '/api/skills/discover', { spec })
            .then(data => data.skills || [])
            .catch(() => null);
        if (found && found.length > 0) return found;
        if (el) {
            el.innerHTML = found
                ? this._mutedHtml('No SKILL.md found in that repo/path.')
                : this._warningHtml('could not scan that repo (not found, or GitHub rate limit?)');
        }
        return null;
    },

    // Install one resolved skill spec (from browse, a repo scan, or a single hit).
    async installExact(spec, name) {
        const confirmed = await DialogCore.confirm(
            `Install "${name || spec}"? Installing a third-party skill adds its instructions to your agents when enabled.`,
            'Install skill?', 'Install'
        );
        if (!confirmed) return;
        const el = document.getElementById('skills-installed-list');
        if (el) el.textContent = 'Installing…';
        try {
            const res = await Api.request('POST', '/api/skills/install', { spec });
            if (res && res.ok === false) {
                if (el) el.innerHTML = `<span style="color:var(--warning);">⚠ Install failed: ${this._escapeHtml(res.error || 'unknown error')}</span>`;
                return;
            }
        } catch (err) {
            console.error('install skill failed:', err);
        }
        this.refreshSkills();
    },

    async browseSkills() {
        const el = document.getElementById('skills-browse-list');
        if (el) el.textContent = 'Loading…';
        try {
            const data = await Api.request('GET', '/api/skills/browse?source=anthropic');
            const skills = data.skills || [];
            if (skills.length === 0) {
                el.innerHTML = '<span style="color:var(--text-muted);">No skills found.</span>';
                return;
            }
            this._renderSkillChoices(el, skills, null);
        } catch (err) {
            if (el) el.innerHTML = '<span style="color:var(--warning);">⚠ failed to load (GitHub rate limit?)</span>';
        }
    },

    async submitConfig(event) {
        event.preventDefault();
        const config = {
            model: document.getElementById('config-model').value,
            system_prompt: document.getElementById('config-system-prompt').value,
            project_context: document.getElementById('config-project-context').value,
            mcp_enabled: document.getElementById('config-mcp-enabled').checked,
            mcp_servers: document.getElementById('config-mcp-servers').value,
            plugins: JSON.stringify(this._configPlugins),
            allowed_commands: JSON.stringify(this._configAllowedCommands),
            bash_yolo: document.getElementById('config-bash-yolo').checked,
            allowed_builtin_tools: JSON.stringify(this._configBuiltinTools),
            flame_enabled: document.getElementById('config-flame-enabled').checked,
            flame_intensity_multiplier: parseFloat(document.getElementById('config-flame-intensity').value) || 1.0,
            ollama_enabled: document.getElementById('config-ollama-enabled').checked,
            ollama_base_url: document.getElementById('config-ollama-base-url').value || 'http://localhost:11434',
            ollama_load_claude_md: document.getElementById('config-ollama-load-claude-md').checked,
            tiiny_enabled: document.getElementById('config-tiiny-enabled').checked,
            tiiny_base_url: document.getElementById('config-tiiny-base-url').value || window.__DEFAULT_TIINY_URL__,
            tiiny_load_claude_md: document.getElementById('config-tiiny-load-claude-md').checked,
            wip_limit: parseInt(document.getElementById('config-wip-limit').value, 10) || 0,
            graphify_enabled: document.getElementById('config-graphify-enabled').checked,
            graphify_auto_refresh: document.getElementById('config-graphify-auto-refresh').checked,
            graphify_backend: document.getElementById('config-graphify-backend').value || 'ast',
        };
        try {
            await Api.request('PUT', '/api/config', config);
            // Apply flame settings immediately
            if (typeof Flame !== 'undefined') {
                Flame.applyConfig(config);
            }
            DialogCore.close('config-dialog');
        } catch (err) {
            console.error('Failed to save config:', err);
        }
    },
};