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
        document.querySelectorAll('#config-dialog .review-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.tab === tabName);
        });
        document.querySelectorAll('#config-dialog .config-tab-content').forEach(c => {
            c.style.display = c.dataset.configTab === tabName ? '' : 'none';
        });
    },

    async openConfig() {
        try {
            const config = await Api.request('GET', '/api/config');
            document.getElementById('config-model').value = config.model || window.__DEFAULT_MODEL__;
            document.getElementById('config-wip-limit').value = config.wip_limit || 0;
            document.getElementById('config-system-prompt').value = config.system_prompt || '';
            document.getElementById('config-project-context').value = config.project_context || '';
            document.getElementById('config-mcp-enabled').checked = config.mcp_enabled || false;
            const mcpServers = config.mcp_servers || '{}';
            document.getElementById('config-mcp-servers').value = typeof mcpServers === 'object' ? JSON.stringify(mcpServers, null, 2) : mcpServers;

            // Load Ollama settings
            document.getElementById('config-ollama-enabled').checked = config.ollama_enabled || false;
            document.getElementById('config-ollama-base-url').value = config.ollama_base_url || window.__DEFAULT_OLLAMA_URL__;

            // Reset connection status
            const statusEl = document.getElementById('ollama-connection-status');
            if (statusEl) statusEl.innerHTML = '';

            // Auto-fetch Ollama models if enabled (experimental only)
            if (config.ollama_enabled && window.__EXPERIMENTAL__) {
                this.refreshOllamaModels();
            }

            // Load plugins
            try {
                this._configPlugins = JSON.parse(config.plugins || '[]');
            } catch {
                this._configPlugins = [];
            }
            this._renderPluginsList();

            // Load allowed commands + yolo mode
            try {
                this._configAllowedCommands = JSON.parse(config.allowed_commands || '[]');
            } catch {
                this._configAllowedCommands = [];
            }
            document.getElementById('config-bash-yolo').checked = config.bash_yolo || false;
            this._renderAllowedCommandsList();
            this._updateYoloState(config.bash_yolo || false);

            // Load built-in tools
            try {
                this._configBuiltinTools = JSON.parse(config.allowed_builtin_tools || '[]');
            } catch {
                this._configBuiltinTools = [];
            }
            try {
                this._availableBuiltinTools = await Api.request('GET', '/api/config/available-tools');
            } catch {
                this._availableBuiltinTools = [
                    {name: 'WebSearch', label: 'Web Search', description: 'Search the web for information'},
                    {name: 'WebFetch', label: 'Web Fetch', description: 'Fetch content from URLs'},
                ];
            }
            this._renderBuiltinToolsList();

            // Load flame settings
            document.getElementById('config-flame-enabled').checked = config.flame_enabled !== false && config.flame_enabled !== 0;
            const intensitySlider = document.getElementById('config-flame-intensity');
            const intensityVal = parseFloat(config.flame_intensity_multiplier) || 1.0;
            intensitySlider.value = intensityVal;
            document.getElementById('config-flame-intensity-value').textContent = intensityVal.toFixed(1);

            // Load graphify settings
            document.getElementById('config-graphify-enabled').checked = config.graphify_enabled === true || config.graphify_enabled === 1;
            document.getElementById('config-graphify-auto-refresh').checked = config.graphify_auto_refresh !== false && config.graphify_auto_refresh !== 0;
            document.getElementById('config-graphify-backend').value = config.graphify_backend || 'ast';
            this.refreshGraphifyStatus();

            // Load skills library (installed + enabled flags)
            this.refreshSkills();

            // Populate Ollama models in the config model dropdown
            if (config.ollama_enabled && this._ollamaModels.length > 0) {
                this._updateModelSelect('config-model', false);
            } else {
                // Still populate from shared cache
                await DialogUtils.populateOllamaOptions(document.getElementById('config-model'));
            }

            this.switchConfigTab('general');
            DialogCore.open('config-dialog');
        } catch (err) {
            console.error('Failed to load config:', err);
        }
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

    _updateConnectionStatus(state, message) {
        const el = document.getElementById('ollama-connection-status');
        if (!el) return;
        const dotCls = state === 'connected' ? 'connected' : state === 'checking' ? 'checking' : 'disconnected';
        el.innerHTML = `<span class="ollama-status-dot ${dotCls}"></span>${message || ''}`;
    },

    async refreshOllamaModels() {
        const listEl = document.getElementById('ollama-models-list');
        if (listEl) listEl.innerHTML = '<span style="color:var(--text-muted);">Fetching models…</span>';
        this._updateConnectionStatus('checking', 'Connecting…');

        try {
            const result = await Api.request('GET', '/api/ollama/models?force=true');
            this._ollamaModels = result.models || [];
            this._ollamaEnabled = result.enabled !== false;

            if (result.error) {
                this._updateConnectionStatus('disconnected', 'Not available');
            } else {
                const count = this._ollamaModels.length;
                this._updateConnectionStatus('connected', `Connected (${count} model${count !== 1 ? 's' : ''})`);
            }

            if (listEl) {
                if (result.error) {
                    listEl.innerHTML = `<span style="color:var(--warning);">⚠ ${result.error}</span>`;
                } else if (this._ollamaModels.length === 0) {
                    listEl.innerHTML = '<span style="color:var(--text-muted);">No models found. Pull one with: <code>ollama pull qwen3.5</code></span>';
                } else {
                    listEl.innerHTML = this._ollamaModels.map(m => {
                        const sizeGB = m.size ? (m.size / 1e9).toFixed(1) + ' GB' : '';
                        return `<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:3px;">
                            <code style="flex:1;font-size:12px;">${m.name}</code>
                            <span style="font-size:11px;color:var(--text-muted);">${m.parameter_size || ''}</span>
                            <span style="font-size:11px;color:var(--text-muted);">${m.quantization_level || ''}</span>
                            <span style="font-size:11px;color:var(--text-muted);">${sizeGB}</span>
                        </div>`;
                    }).join('');
                }
            }

            // Update model names map for display
            for (const m of this._ollamaModels) {
                window.__MODEL_NAMES__[m.name] = m.display_name;
            }

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
            if (listEl) listEl.innerHTML = '<span style="color:var(--warning);">⚠ Failed to fetch models</span>';
        }
    },

    _updateModelDropdowns() {
        // Update both config-model and item-form-model selects
        this._updateModelSelect('config-model', false);
        this._updateModelSelect('item-form-model', true);
    },

    _updateModelSelect(selectId, hasDefaultOption) {
        const select = document.getElementById(selectId);
        if (!select) return;

        // Remember current selection
        const currentValue = select.value;

        // Remove existing Ollama optgroup if any
        const existingGroup = select.querySelector('optgroup[label="Ollama Models"]');
        if (existingGroup) existingGroup.remove();

        // Add Ollama models if enabled and available
        if (this._ollamaEnabled && this._ollamaModels.length > 0) {
            const optgroup = document.createElement('optgroup');
            optgroup.label = 'Ollama Models';
            for (const m of this._ollamaModels) {
                const opt = document.createElement('option');
                opt.value = m.name;
                const sizeStr = m.size ? ` (${(m.size / 1e9).toFixed(1)}GB)` : '';
                const paramStr = m.parameter_size ? `:${m.parameter_size}` : '';
                opt.textContent = `${m.display_name}${paramStr}${sizeStr}`;
                optgroup.appendChild(opt);
            }
            select.appendChild(optgroup);
        }

        // Restore selection
        select.value = currentValue;
        // If the value couldn't be set (removed option), fallback
        if (select.value !== currentValue) {
            select.value = hasDefaultOption ? '' : select.options[0]?.value || '';
        }
    },

    _renderGraphifyStatus(st) {
        const el = document.getElementById('graphify-status');
        const upgradeRow = document.getElementById('graphify-upgrade-row');
        if (!el) return;
        const installed = st.installed_version || 'not installed';
        const latest = st.latest_version;
        const behind = latest && st.installed_version && latest !== st.installed_version;
        const g = st.graph || {};
        let graphLine;
        if (st.building) {
            graphLine = '<span style="color:var(--accent);">● building…</span>';
        } else if (g.exists) {
            const built = g.last_built ? new Date(g.last_built).toLocaleString() : 'unknown';
            graphLine = `graph: ${g.nodes} nodes · ${g.edges} edges · ${g.communities} communities<br>last built ${built}`;
            if (g.cost && g.cost.total_output_tokens) {
                graphLine += `<br>semantic cost: ${g.cost.total_output_tokens.toLocaleString()} output tokens`;
            }
        } else {
            graphLine = '<span style="color:var(--text-muted);">no graph built yet</span>';
        }
        el.innerHTML = `graphify ${installed}${latest ? ` · latest ${latest}` : ''}${behind ? ' <span style="color:var(--warning);">(update available)</span>' : ' ✓'}<br>${graphLine}`;
        if (upgradeRow) upgradeRow.style.display = behind ? '' : 'none';
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
        el.innerHTML = skills.map(s => {
            const name = this._escapeHtml(s.name);
            const descText = s.description || 'No description provided.';
            const srcText = s.source ? `\n\nInstalled from: ${s.source}` : '\n\n(source not recorded — reinstall to capture)';
            const info = this._escapeHtml(descText + srcText);
            return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 12px;background:var(--bg-primary);border-radius:var(--radius-sm);margin-bottom:6px;">
                <span style="display:flex;align-items:center;gap:6px;flex:0 0 auto;min-width:0;max-width:78%;">
                    <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;color:var(--text-primary);">${name}</span>
                    <span title="${info}" style="flex:0 0 auto;cursor:help;color:var(--text-muted);font-size:13px;line-height:1;">&#9432;</span>
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
        const input = document.getElementById('skill-add-input');
        const value = (input ? input.value : '').trim();
        if (!value) return;
        const el = document.getElementById('skills-browse-list');
        if (el) el.textContent = 'Scanning repo…';
        let found;
        try {
            const data = await Api.request('POST', '/api/skills/discover', { spec: value });
            found = data.skills || [];
        } catch (err) {
            if (el) el.innerHTML = '<span style="color:var(--warning);">⚠ could not scan that repo (not found, or GitHub rate limit?)</span>';
            return;
        }
        if (found.length === 0) {
            if (el) el.innerHTML = '<span style="color:var(--text-muted);">No SKILL.md found in that repo/path.</span>';
            return;
        }
        if (found.length === 1) {
            if (el) el.innerHTML = '';
            await this.installExact(found[0].spec, found[0].name);
            if (input) input.value = '';
            return;
        }
        this._renderSkillChoices(el, found, `Found ${found.length} skills — choose which to install:`);
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