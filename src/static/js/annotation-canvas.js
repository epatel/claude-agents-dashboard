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

        // Focus canvas after a brief delay to ensure dialog is fully open
        setTimeout(() => {
            canvas.focus();
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
            if (originalDataUrl) {
                ItemDialog._pendingAttachments.push({
                    dataUrl: originalDataUrl,
                    filename: `annotation_${ts}_original.jpg`,
                    annotation_summary: summary || null,
                });
            }
            if (annotatedDataUrl) {
                ItemDialog._pendingAttachments.push({
                    dataUrl: annotatedDataUrl,
                    filename: `annotation_${ts}_annotated.jpg`,
                    annotation_summary: null,
                });
            }
            // Fallback: if neither layer has content, export combined (legacy behavior)
            if (!originalDataUrl && !annotatedDataUrl) {
                const dataUrl = Annotate.toDataURL();
                ItemDialog._pendingAttachments.push({
                    dataUrl,
                    filename: `annotation_${ts}.png`,
                });
            }
            ItemDialog._renderFormAttachments();
            DialogCore.close('annotate-dialog');
            Dialogs._annotateTarget = null;
            return;
        }

        if (!DialogCore._currentItemId) return;

        try {
            // Upload original (clean screenshot)
            if (originalDataUrl) {
                await Api.request('POST', `/api/items/${DialogCore._currentItemId}/attachments`, {
                    item_id: DialogCore._currentItemId,
                    filename: `annotation_${ts}_original.jpg`,
                    data: originalDataUrl,
                    annotation_summary: summary || null,
                });
            }
            // Upload annotated version (screenshot + annotations baked in)
            if (annotatedDataUrl) {
                await Api.request('POST', `/api/items/${DialogCore._currentItemId}/attachments`, {
                    item_id: DialogCore._currentItemId,
                    filename: `annotation_${ts}_annotated.jpg`,
                    data: annotatedDataUrl,
                });
            }
            // Fallback: if neither layer has content, export combined
            if (!originalDataUrl && !annotatedDataUrl) {
                const dataUrl = Annotate.toDataURL();
                await Api.request('POST', `/api/items/${DialogCore._currentItemId}/attachments`, {
                    item_id: DialogCore._currentItemId,
                    filename: `annotation_${ts}.png`,
                    data: dataUrl,
                });
            }
            DialogCore.close('annotate-dialog');
            await Attachments._loadAttachments(DialogCore._currentItemId);
            DetailDialog.switchDetailTab('detail-attach');
        } catch (err) {
            console.error('Failed to save annotation:', err);
        }
    },
};