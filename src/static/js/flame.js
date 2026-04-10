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
    // Flame sources — fixed positions where flames originate
    _flameSources: [],

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

        // Create flame sources along the bottom edge
        this._initFlameSources();

        // Seed particles from flame sources
        for (let i = 0; i < 45; i++) {
            this._particles.push(this._newParticle(true));
        }

        this._raf = requestAnimationFrame((t) => this._loop(t));
    },

    _initFlameSources() {
        const w = this.canvas ? this.canvas.width : 800;
        // Create 8-12 flame sources spread along bottom
        const count = 8 + Math.floor(Math.random() * 5);
        this._flameSources = [];
        for (let i = 0; i < count; i++) {
            this._flameSources.push({
                x: (w / (count + 1)) * (i + 1) + (Math.random() - 0.5) * 40,
                spread: 15 + Math.random() * 25,   // horizontal spread of this flame
                strength: 0.5 + Math.random() * 0.5, // relative intensity
            });
        }
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
        // Reposition flame sources for new width
        this._initFlameSources();
    },

    _newParticle(randomY) {
        const w = this.canvas ? this.canvas.width : 800;
        const h = this.canvas ? this.canvas.height : 600;

        // Pick a flame source to emit from (clustered flames, not scattered)
        const src = this._flameSources.length > 0
            ? this._flameSources[Math.floor(Math.random() * this._flameSources.length)]
            : { x: Math.random() * w, spread: 30, strength: 1 };

        const startX = src.x + (Math.random() - 0.5) * src.spread * 2;
        const startY = randomY ? h * (0.5 + Math.random() * 0.5) : h + Math.random() * 10;

        return {
            x: startX,
            y: startY,
            // Mostly upward, very slight horizontal drift
            vx: (Math.random() - 0.5) * 0.4,
            vy: -(0.6 + Math.random() * 1.4),
            // Smaller, tighter particles for cohesive flames
            size: 10 + Math.random() * 30,
            life: 0,
            maxLife: 50 + Math.random() * 100,
            // Natural fire lifecycle: starts white/yellow, ages to orange, dies red
            // Store base hue offset — actual color computed from life ratio
            phase: Math.random() * Math.PI * 2,
            flickerRate: 2 + Math.random() * 3,
            sourceStrength: src.strength,
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

        // Draw warm ambient glow at the bottom
        const glowGrad = ctx.createLinearGradient(0, h, 0, h * 0.4);
        glowGrad.addColorStop(0, `hsla(20, 100%, 50%, ${intensity * 0.12})`);
        glowGrad.addColorStop(0.3, `hsla(30, 100%, 45%, ${intensity * 0.06})`);
        glowGrad.addColorStop(0.7, `hsla(15, 100%, 40%, ${intensity * 0.02})`);
        glowGrad.addColorStop(1, `hsla(10, 100%, 30%, 0)`);
        ctx.fillStyle = glowGrad;
        ctx.fillRect(0, 0, w, h);

        // Draw localized glow under each flame source
        for (const src of this._flameSources) {
            const glowRadius = (40 + src.spread) * (0.5 + intensity * 0.5);
            const srcGlow = ctx.createRadialGradient(src.x, h, 0, src.x, h, glowRadius);
            srcGlow.addColorStop(0, `hsla(30, 100%, 55%, ${intensity * 0.15 * src.strength})`);
            srcGlow.addColorStop(0.5, `hsla(20, 100%, 45%, ${intensity * 0.06 * src.strength})`);
            srcGlow.addColorStop(1, `hsla(10, 100%, 30%, 0)`);
            ctx.fillStyle = srcGlow;
            ctx.fillRect(src.x - glowRadius, h - glowRadius, glowRadius * 2, glowRadius);
        }

        // Update and draw flame particles
        const speed = 0.4 + intensity * 0.6;
        const particleAlpha = intensity * 0.8;

        // Additive blending for natural fire glow
        ctx.globalCompositeOperation = 'lighter';

        for (let i = this._particles.length - 1; i >= 0; i--) {
            const p = this._particles[i];
            p.life++;
            p.x += p.vx * speed;
            p.y += p.vy * speed;

            // Gentle flame flicker — subtle side-to-side, not erratic
            const flicker = Math.sin(time * 0.004 + p.phase) * 0.3
                          + Math.sin(time * 0.009 + p.phase * 1.7) * 0.15;
            p.x += flicker;

            // Slight upward acceleration (heat rises faster)
            p.vy -= 0.003;

            if (p.life > p.maxLife || p.y < -p.size) {
                this._particles[i] = this._newParticle(false);
                continue;
            }

            const lifeRatio = p.life / p.maxLife;
            // Flickering alpha — natural fire shimmer
            const shimmer = 0.8 + 0.2 * Math.sin(time * 0.006 * p.flickerRate + p.phase);
            const alpha = particleAlpha * Math.sin(lifeRatio * Math.PI) * 0.5 * shimmer * p.sourceStrength;
            if (alpha < 0.005) continue;

            const radius = p.size * (0.3 + intensity * 0.7) * (1 - lifeRatio * 0.3);

            // Natural fire color lifecycle:
            //   young (lifeRatio ~0): bright white/yellow core
            //   mid (lifeRatio ~0.4): orange
            //   old (lifeRatio ~0.8+): deep red, fading
            let hue, sat, lightness;
            if (lifeRatio < 0.25) {
                // White-yellow core (young flame)
                hue = 45 + lifeRatio * 40;       // 45 → 55
                sat = 60 + lifeRatio * 140;       // 60% → 95%
                lightness = 85 - lifeRatio * 80;  // 85% → 65%
            } else if (lifeRatio < 0.6) {
                // Orange body
                const t = (lifeRatio - 0.25) / 0.35;
                hue = 55 - t * 30;               // 55 → 25
                sat = 95 + t * 5;                 // 95% → 100%
                lightness = 65 - t * 15;          // 65% → 50%
            } else {
                // Red tips (dying flame)
                const t = (lifeRatio - 0.6) / 0.4;
                hue = 25 - t * 20;               // 25 → 5
                sat = 100;
                lightness = 50 - t * 15;          // 50% → 35%
            }

            // Radial gradient: bright center fading to edge
            const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
            grad.addColorStop(0, `hsla(${hue + 10}, ${sat - 10}%, ${Math.min(lightness + 15, 95)}%, ${alpha})`);
            grad.addColorStop(0.3, `hsla(${hue}, ${sat}%, ${lightness}%, ${alpha * 0.65})`);
            grad.addColorStop(0.7, `hsla(${hue - 8}, ${sat}%, ${lightness - 10}%, ${alpha * 0.2})`);
            grad.addColorStop(1, `hsla(${hue - 15}, ${sat}%, ${lightness - 20}%, 0)`);

            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
            ctx.fill();
        }

        // Reset composite operation
        ctx.globalCompositeOperation = 'source-over';

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
