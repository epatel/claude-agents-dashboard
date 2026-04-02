const Api = {
    async request(method, url, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        if (!res.ok) {
            const text = await res.text();
            throw new Error(`${method} ${url}: ${res.status} ${text}`);
        }
        return res.json();
    },

    getItems() {
        return this.request('GET', '/api/items');
    },

    createItem(title, description = '', model = null, epic_id = null) {
        const payload = { title, description };
        if (model) payload.model = model;
        if (epic_id) payload.epic_id = epic_id;
        return this.request('POST', '/api/items', payload);
    },

    updateItem(id, data) {
        return this.request('PATCH', `/api/items/${id}`, data);
    },

    deleteItem(id) {
        return this.request('DELETE', `/api/items/${id}`);
    },

    moveItem(id, column_name, position) {
        return this.request('POST', `/api/items/${id}/move`, { column_name, position });
    },

    startAgent(id) {
        return this.request('POST', `/api/items/${id}/start`);
    },

    startCopyAgent(id) {
        return this.request('POST', `/api/items/${id}/start-copy`);
    },

    cancelAgent(id) {
        return this.request('POST', `/api/items/${id}/cancel`);
    },

    pauseAgent(id) {
        return this.request('POST', `/api/items/${id}/pause`);
    },

    resumeAgent(id) {
        return this.request('POST', `/api/items/${id}/resume`);
    },

    retryAgent(id) {
        return this.request('POST', `/api/items/${id}/retry`);
    },

    approveItem(id) {
        return this.request('POST', `/api/items/${id}/approve`);
    },

    requestChanges(id, comments) {
        return this.request('POST', `/api/items/${id}/request-changes`, { comments });
    },

    cancelReview(id) {
        return this.request('POST', `/api/items/${id}/cancel-review`);
    },

    getWorkLog(id) {
        return this.request('GET', `/api/items/${id}/log`);
    },

    getAttachments(id) {
        return this.request('GET', `/api/items/${id}/attachments`);
    },

    createAttachment(itemId, filename, data) {
        return this.request('POST', `/api/items/${itemId}/attachments`, {
            item_id: itemId,
            filename: filename,
            data: data,
        });
    },

    archiveByDate(date) {
        return this.request('POST', '/api/items/archive-by-date', { date });
    },

    deleteByDate(date, columnName) {
        return this.request('POST', '/api/items/delete-by-date', { date, column_name: columnName });
    },

    searchWorklog(query) {
        return this.request('GET', `/api/search/worklog?q=${encodeURIComponent(query)}`);
    },
};
