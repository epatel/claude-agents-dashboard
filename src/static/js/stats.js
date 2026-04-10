/**
 * Stats tracking and display functionality
 */
class StatsManager {
    constructor() {
        this.updateInterval = 10000; // Update every 10 seconds
        this.intervalId = null;
    }

    /**
     * Initialize stats tracking
     */
    init() {
        this.updateStats();
        this.startAutoUpdate();
    }

    /**
     * Fetch and update stats from API
     */
    async updateStats() {
        try {
            const response = await fetch('/api/stats');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            this.displayStats(data);
        } catch (error) {
            console.error('Failed to fetch stats:', error);
            // Show error state
            this.displayError();
        }
    }

    /**
     * Display stats in the UI
     */
    displayStats(data) {
        const { usage, activity } = data;

        // Feed flame animation
        if (typeof Flame !== 'undefined') {
            Flame.updateFromStats(data);
        }

        // Update usage stats
        this.updateElement('total-cost', `$${usage.total_cost_usd.toFixed(2)}`);
        this.updateElement('total-tokens', this.formatNumber(usage.total_tokens || 0));
        this.updateElement('total-messages', this.formatNumber(usage.total_messages));
        this.updateElement('tool-calls', this.formatNumber(usage.tool_calls));
        this.updateElement('active-agents', activity.active_agents);
        this.updateElement('completed-today', usage.completed_today);

        // Add tooltips with more detail
        this.updateTooltips(data);
    }

    /**
     * Update a single stat element
     */
    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    /**
     * Format numbers for display (e.g., 1000 -> 1K)
     */
    formatNumber(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(1) + 'M';
        }
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }

    /**
     * Update tooltips with detailed information
     */
    updateTooltips(data) {
        const { usage, activity, breakdown } = data;

        // Cost tooltip
        const costEl = document.getElementById('total-cost');
        if (costEl) {
            costEl.title = `Estimated cost across all agents\nUsing Claude Agent SDK — actual billing\ngoes to your Anthropic subscription`;
        }

        // Tokens tooltip
        const tokensEl = document.getElementById('total-tokens');
        if (tokensEl) {
            const input = usage.input_tokens || 0;
            const output = usage.output_tokens || 0;
            tokensEl.title = `Total tokens used\nInput: ${input.toLocaleString()}\nOutput: ${output.toLocaleString()}`;
        }

        // Messages tooltip
        const messagesEl = document.getElementById('total-messages');
        if (messagesEl) {
            const details = Object.entries(breakdown)
                .map(([type, count]) => `${type}: ${count}`)
                .join('\n');
            messagesEl.title = `Message breakdown:\n${details}`;
        }

        // Tool calls tooltip
        const toolsEl = document.getElementById('tool-calls');
        if (toolsEl) {
            toolsEl.title = `Total tool/function calls made by agents`;
        }

        // Active agents tooltip
        const activeEl = document.getElementById('active-agents');
        if (activeEl) {
            const itemCounts = Object.entries(activity.items_by_status || {})
                .map(([status, count]) => `${status}: ${count}`)
                .join(', ');
            activeEl.title = `Currently running agents\nItems: ${itemCounts}`;
        }

        // Completed today tooltip
        const todayEl = document.getElementById('completed-today');
        if (todayEl) {
            todayEl.title = `Items completed today`;
        }
    }

    /**
     * Display error state
     */
    displayError() {
        const statsBar = document.getElementById('stats-bar');
        if (statsBar) {
            statsBar.style.opacity = '0.5';
            statsBar.title = 'Failed to load stats';
        }
    }

    /**
     * Start automatic stats updates
     */
    startAutoUpdate() {
        this.intervalId = setInterval(() => {
            this.updateStats();
        }, this.updateInterval);
    }

    /**
     * Stop automatic stats updates
     */
    stopAutoUpdate() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

    /**
     * Handle real-time updates from WebSocket
     */
    handleRealtimeUpdate(event, data) {
        // Update stats when relevant events occur
        if (['agent_log', 'item_created', 'item_updated', 'item_moved'].includes(event)) {
            // Debounce rapid updates
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => {
                this.updateStats();
            }, 1000);
        }
    }
}

// Global stats manager instance
window.statsManager = new StatsManager();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.statsManager.init();
});

// Clean up on page unload
window.addEventListener('beforeunload', () => {
    window.statsManager.stopAutoUpdate();
});