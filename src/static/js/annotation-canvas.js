/**
 * Annotation canvas functionality
 */
const AnnotationCanvas = {
    openAnnotateCanvas() {
        const canvas = document.getElementById('annotate-canvas');
        Annotate.init(canvas);
        this.setAnnotateTool('select');
        Dialogs._annotateTarget = null;
        DialogCore.open('annotate-dialog');

        // Focus the hidden paste shim after the dialog is fully open so that
        // Cmd/Ctrl+V is dispatched against an editable target — this prevents
        // Safari/Chrome on macOS from showing the "Paste" permission overlay.
        setTimeout(() => {
            Annotate.focusPasteTarget();
        }, 100);
    },

    setAnnotateTool(tool) {
        Annotate.tool = tool;
        document.querySelectorAll('.annotate-tool').forEach(b => {
            b.classList.toggle('active', b.dataset.tool === tool);
        });
    },

    async saveAnnotation() {
        const originalDataUrl = Annotate.toBackgroundDataURL();
        const annotatedDataUrl = Annotate.toAnnotatedDataURL();
        const summary = Annotate.getAnnotationSummary();
        const ts = Date.now();

        // Handle new-item pending attachments flow
        if (Dialogs._annotateTarget === 'new-item') {
            for (const layer of this._annotationLayers(originalDataUrl, annotatedDataUrl, summary, ts)) {
                ItemDialog._pendingAttachments.push(this._pendingAttachment(layer, summary));
            }
            ItemDialog._renderFormAttachments();
            DialogCore.close('annotate-dialog');
            Dialogs._annotateTarget = null;
            return;
        }

        if (!DialogCore._currentItemId) return;

        try {
            for (const layer of this._annotationLayers(originalDataUrl, annotatedDataUrl, summary, ts)) {
                await this._uploadLayer(layer, summary);
            }
            DialogCore.close('annotate-dialog');
            await Attachments._loadAttachments(DialogCore._currentItemId);
            DetailDialog.switchDetailTab('detail-attach');
        } catch (err) {
            console.error('Failed to save annotation:', err);
        }
    },

    /**
     * The images to save, in order: the clean screenshot (original), then the
     * annotated version only if annotations were actually made. If neither
     * layer has content, one combined export (legacy behavior).
     */
    _annotationLayers(originalDataUrl, annotatedDataUrl, summary, ts) {
        if (!originalDataUrl && !annotatedDataUrl) {
            return [{ kind: 'combined', dataUrl: Annotate.toDataURL(), filename: `annotation_${ts}.png` }];
        }
        const layers = [];
        if (originalDataUrl) {
            const filename = summary ? `annotation_${ts}_original.jpg` : `annotation_${ts}.jpg`;
            layers.push({ kind: 'original', dataUrl: originalDataUrl, filename });
        }
        if (annotatedDataUrl && summary) {
            layers.push({ kind: 'annotated', dataUrl: annotatedDataUrl, filename: `annotation_${ts}_annotated.jpg` });
        }
        return layers;
    },

    _pendingAttachment(layer, summary) {
        const entry = { dataUrl: layer.dataUrl, filename: layer.filename };
        if (layer.kind !== 'combined') {
            entry.annotation_summary = layer.kind === 'original' ? (summary || null) : null;
        }
        return entry;
    },

    _uploadLayer(layer, summary) {
        const itemId = DialogCore._currentItemId;
        const body = { item_id: itemId, filename: layer.filename, data: layer.dataUrl };
        if (layer.kind === 'original') body.annotation_summary = summary || null;
        return Api.request('POST', `/api/items/${itemId}/attachments`, body);
    },
};