// Notification sound module — plays a chime when agents finish
const Sound = {
    STORAGE_KEY: 'agents-dashboard-sound',
    _audioCtx: null,

    init() {
        const btn = document.getElementById('sound-toggle');
        if (btn) {
            btn.addEventListener('click', () => this.toggle());
            this._updateButton();
        }
    },

    isEnabled() {
        return localStorage.getItem(this.STORAGE_KEY) !== 'off';
    },

    toggle() {
        const enabled = this.isEnabled();
        localStorage.setItem(this.STORAGE_KEY, enabled ? 'off' : 'on');
        this._updateButton();
        // Play a short preview when turning on
        if (!enabled) this.playChime();
    },

    _updateButton() {
        const btn = document.getElementById('sound-toggle');
        if (!btn) return;
        const enabled = this.isEnabled();
        btn.title = enabled ? 'Sound on (click to mute)' : 'Sound off (click to unmute)';
        btn.querySelector('.sound-on').style.display = enabled ? 'inline' : 'none';
        btn.querySelector('.sound-off').style.display = enabled ? 'none' : 'inline';
    },

    _getAudioContext() {
        if (!this._audioCtx) {
            this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        return this._audioCtx;
    },

    // Pleasant two-tone chime using Web Audio API
    playChime() {
        if (!this.isEnabled()) return;
        try {
            const ctx = this._getAudioContext();
            const now = ctx.currentTime;

            // Two-note chime: C5 then E5
            const notes = [
                { freq: 523.25, start: 0, duration: 0.15 },
                { freq: 659.25, start: 0.12, duration: 0.2 },
            ];

            notes.forEach(({ freq, start, duration }) => {
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();

                osc.type = 'sine';
                osc.frequency.value = freq;

                gain.gain.setValueAtTime(0, now + start);
                gain.gain.linearRampToValueAtTime(0.15, now + start + 0.02);
                gain.gain.exponentialRampToValueAtTime(0.001, now + start + duration);

                osc.connect(gain);
                gain.connect(ctx.destination);

                osc.start(now + start);
                osc.stop(now + start + duration + 0.01);
            });
        } catch (e) {
            // Audio not available — silently ignore
        }
    },
};
