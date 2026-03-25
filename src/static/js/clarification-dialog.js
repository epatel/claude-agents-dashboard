/**
 * Clarification dialog functionality
 */
const ClarificationDialog = {
    async reopenClarification(itemId) {
        // Fetch pending clarification from DB
        try {
            const data = await Api.request('GET', `/api/items/${itemId}/clarification`);
            if (data && data.id) {
                const choices = data.choices ? JSON.parse(data.choices) : [];
                this.showClarification(itemId, data.prompt || '(Agent is waiting for your input)', choices);
            } else {
                // No pending clarification, show regular detail
                DetailDialog._showDetailDirect(itemId);
            }
        } catch (err) {
            console.error('Failed to load clarification:', err);
        }
    },

    showClarification(itemId, prompt, choices) {
        document.getElementById('clarify-item-id').value = itemId;
        document.getElementById('clarify-prompt').textContent = prompt;
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