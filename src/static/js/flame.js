/**
 * Flame background animation behind board columns.
 *
 * Intensity is driven by a formula combining:
 *   - active agents count
 *   - tokens/min  (rolling 60s window)
 *   - messages/min (rolling 60s window)
 *   - tools/min   (rolling 60s window)
 *
 * The result is written to CSS custom properties on <main class="board">
 * and rendered via a <canvas> element positioned behind the columns.
 */
const Flame = {
    canvas: null,
    ctx: null,
    enabled: true,
    intensityMultiplier: 1.0,
    _raf: null,
    _lastTime: 0,

    // Activity tracking (rolling window)
    _activityLog: [],        // { ts, tokens, messages, tools }
    _prevStats: null,
    _currentIntensity: 0,    // 0..1 smoothed
    _targetIntensity: 0,

    // Flame particles
    _particles: [],

    init() {
        // Create canvas behind board
        const board = document.querySelector('.board');
        if (!board) return;

        this.canvas = document.createElement('canvas');
        this.canvas.className = 'flame-canvas';
        board.parentNode.insertBefore(this.canvas, board);

        this.ctx = this.canvas.getContext('2d');
        this._resize();
        window.addEventListener('resize', () => this._resize());

        // Seed particles
        for (let i = 0; i < 80; i++) {
            this._particles.push(this._newParticle(true));
        }

        this._raf = requestAnimationFrame((t) => this._loop(t));
    },

    destroy() {
        if (this._raf) cancelAnimationFrame(this._raf);
        if (this.canvas) this.canvas.remove();
        this.canvas = null;
        this.ctx = null;
    },

    /** Call from StatsManager when stats refresh */
    updateFromStats(data) {
        if (!data) return;
        const now = Date.now();
        const { usage, activity } = data;

        // Record current cumulative values
        const current = {
            ts: now,
            tokens: usage.total_tokens || 0,
            messages: usage.total_messages || 0,
            tools: usage.tool_calls || 0,
        };

        if (this._prevStats) {
            const dt = (now - this._prevStats.ts) / 60000; // minutes
            if (dt > 0) {
                const tokPerMin = (current.tokens - this._prevStats.tokens) / dt;
                const msgPerMin = (current.messages - this._prevStats.messages) / dt;
                const toolsPerMin = (current.tools - this._prevStats.tools) / dt;

                this._activityLog.push({ ts: now, tokPerMin, msgPerMin, toolsPerMin });
            }
        }
        this._prevStats = current;

        // Trim activity log to last 120 seconds
        const cutoff = now - 120000;
        this._activityLog = this._activityLog.filter(e => e.ts > cutoff);

        // Compute rolling averages
        let avgTok = 0, avgMsg = 0, avgTools = 0;
        if (this._activityLog.length > 0) {
            for (const e of this._activityLog) {
                avgTok += e.tokPerMin;
                avgMsg += e.msgPerMin;
                avgTools += e.toolsPerMin;
            }
            avgTok /= this._activityLog.length;
            avgMsg /= this._activityLog.length;
            avgTools /= this._activityLog.length;
        }

        const activeAgents = activity.active_agents || 0;

        // Intensity formula:
        //   base from active agents (each contributes 0.15)
        //   + token rate contribution (normalized: 10k tok/min = 0.3)
        //   + message rate contribution (5 msg/min = 0.2)
        //   + tool rate contribution (10 tools/min = 0.2)
        // Clamped to [0, 1]
        const raw = (activeAgents * 0.15)
            + Math.min(avgTok / 10000, 1) * 0.3
            + Math.min(avgMsg / 5, 1) * 0.2
            + Math.min(avgTools / 10, 1) * 0.2;

        this._targetIntensity = Math.min(raw * this.intensityMultiplier, 1);
    },

    /** Call when config is loaded/updated */
    applyConfig(config) {
        this.enabled = config.flame_enabled !== false && config.flame_enabled !== 0;
        this.intensityMultiplier = parseFloat(config.flame_intensity_multiplier) || 1.0;

        if (this.canvas) {
            this.canvas.style.display = this.enabled ? '' : 'none';
        }
    },

    _resize() {
        if (!this.canvas) return;
        const board = document.querySelector('.board');
        if (!board) return;
        const rect = board.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.canvas.style.width = rect.width + 'px';
        this.canvas.style.height = rect.height + 'px';
    },

    _newParticle(randomY) {
        const w = this.canvas ? this.canvas.width : 800;
        const h = this.canvas ? this.canvas.height : 600;
        return {
            x: Math.random() * w,
            y: randomY ? Math.random() * h : h + Math.random() * 40,
            vx: (Math.random() - 0.5) * 0.8,
            vy: -(0.5 + Math.random() * 1.5),
            size: 20 + Math.random() * 50,
            life: 0,
            maxLife: 80 + Math.random() * 120,
            hue: Math.random() < 0.6 ? 20 + Math.random() * 20 : 5 + Math.random() * 10,  // orange or red
        };
    },

    _loop(time) {
        if (!this.canvas || !this.enabled) {
            this._raf = requestAnimationFrame((t) => this._loop(t));
            return;
        }

        const dt = time - this._lastTime;
        this._lastTime = time;
        if (dt > 100) {
            this._raf = requestAnimationFrame((t) => this._loop(t));
            return;
        }

        // Smooth intensity transition
        const smoothing = 0.02;
        this._currentIntensity += (this._targetIntensity - this._currentIntensity) * smoothing;

        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;

        ctx.clearRect(0, 0, w, h);

        const intensity = this._currentIntensity;
        if (intensity < 0.001) {
            this._raf = requestAnimationFrame((t) => this._loop(t));
            return;
        }

        // Draw glow at the bottom
        const glowGrad = ctx.createLinearGradient(0, h, 0, h * 0.3);
        glowGrad.addColorStop(0, `hsla(20, 100%, 50%, ${intensity * 0.15})`);
        glowGrad.addColorStop(0.4, `hsla(30, 100%, 50%, ${intensity * 0.06})`);
        glowGrad.addColorStop(1, `hsla(0, 100%, 50%, 0)`);
        ctx.fillStyle = glowGrad;
        ctx.fillRect(0, 0, w, h);

        // Update and draw particles
        const speed = 0.3 + intensity * 0.7;
        const particleAlpha = intensity * 0.7;

        for (let i = this._particles.length - 1; i >= 0; i--) {
            const p = this._particles[i];
            p.life++;
            p.x += p.vx * speed;
            p.y += p.vy * speed;
            // Slight wobble
            p.x += Math.sin(time * 0.002 + i) * 0.3;

            if (p.life > p.maxLife || p.y < -p.size) {
                this._particles[i] = this._newParticle(false);
                continue;
            }

            const lifeRatio = p.life / p.maxLife;
            const alpha = particleAlpha * Math.sin(lifeRatio * Math.PI) * 0.6;
            if (alpha < 0.005) continue;

            const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.size * (0.5 + intensity * 0.5));
            grad.addColorStop(0, `hsla(${p.hue + lifeRatio * 20}, 100%, ${55 + lifeRatio * 15}%, ${alpha})`);
            grad.addColorStop(0.4, `hsla(${p.hue + 10}, 100%, 50%, ${alpha * 0.4})`);
            grad.addColorStop(1, `hsla(${p.hue}, 100%, 30%, 0)`);

            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size * (0.5 + intensity * 0.5), 0, Math.PI * 2);
            ctx.fill();
        }

        this._raf = requestAnimationFrame((t) => this._loop(t));
    },
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Load config first, then init
    fetch('/api/config')
        .then(r => r.json())
        .then(config => {
            Flame.applyConfig(config);
            Flame.init();
        })
        .catch(() => {
            Flame.init();
        });
});
