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
            document.getElementById('config-model').value = config.model || 'claude-sonnet-4-20250514';
            document.getElementById('config-system-prompt').value = config.system_prompt || '';
            document.getElementById('config-project-context').value = config.project_context || '';
            document.getElementById('config-mcp-enabled').checked = config.mcp_enabled || false;
            document.getElementById('config-mcp-servers').value = config.mcp_servers || '{}';

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