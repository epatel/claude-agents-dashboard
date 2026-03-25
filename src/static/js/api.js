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

    createItem(title, description = '', model = null) {
        const payload = { title, description };
        if (model) payload.model = model;
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

    cancelAgent(id) {
        return this.request('POST', `/api/items/${id}/cancel`);
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
};
