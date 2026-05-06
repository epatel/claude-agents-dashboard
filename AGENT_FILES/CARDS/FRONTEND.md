# Frontend

Vanilla JS in `src/static/js/`, **no build step**.

- Jinja2 server-renders the initial board (`templates/base.html`, `templates/board.html`, `templates/partials/card.html`)
- JS handles updates via WebSocket + fetch
- `dialogs.js` coordinates the specialized dialog modules (clarification, config, detail, item, notification, request-changes, review, search, file-browser, attachments, shortcuts, annotate)
- `dialog-core.js` + `dialog-utils.js` are the shared infrastructure

**Sync requirement**: JavaScript-rendered cards (in `board.js`) and the server-rendered Jinja2 `partials/card.html` partial must stay in sync.
