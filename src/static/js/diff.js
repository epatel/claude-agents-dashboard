const DiffViewer = {
    render(diffText, container) {
        if (!diffText) {
            container.innerHTML = '<p class="diff-empty">No file changes — agent completed without modifying files. Check the work log for output.</p>';
            return;
        }

        const files = this.parseDiff(diffText);
        container.innerHTML = '';

        for (const file of files) {
            const fileEl = document.createElement('div');
            fileEl.className = 'diff-file';
            fileEl.dataset.filePath = file.path;

            const header = document.createElement('div');
            header.className = 'diff-file-header';
            header.textContent = file.path;
            header.onclick = () => {
                const body = fileEl.querySelector('.diff-file-body');
                body.style.display = body.style.display === 'none' ? '' : 'none';
            };
            fileEl.appendChild(header);

            const body = document.createElement('div');
            body.className = 'diff-file-body';

            for (const line of file.lines) {
                const lineEl = document.createElement('div');
                lineEl.className = 'diff-line';
                if (line.startsWith('+') && !line.startsWith('+++')) {
                    lineEl.classList.add('diff-add');
                } else if (line.startsWith('-') && !line.startsWith('---')) {
                    lineEl.classList.add('diff-del');
                } else if (line.startsWith('@@')) {
                    lineEl.classList.add('diff-hunk');
                }
                lineEl.textContent = line;
                body.appendChild(lineEl);
            }

            fileEl.appendChild(body);
            container.appendChild(fileEl);
        }
    },

    parseDiff(text) {
        const files = [];
        let current = null;

        for (const line of text.split('\n')) {
            if (line.startsWith('diff --git')) {
                const match = line.match(/b\/(.+)$/);
                current = { path: match ? match[1] : '?', lines: [] };
                files.push(current);
            } else if (current) {
                current.lines.push(line);
            }
        }
        return files;
    },
};
