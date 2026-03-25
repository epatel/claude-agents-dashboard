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
        const dataUrl = Annotate.toDataURL();
        const filename = `annotation_${Date.now()}.png`;

        if (Dialogs._annotateTarget === 'new-item') {
            // Save as pending attachment for the new item form
            ItemDialog._pendingAttachments.push({ dataUrl, filename });
            ItemDialog._renderFormAttachments();
            DialogCore.close('annotate-dialog');
            Dialogs._annotateTarget = null;
            return;
        }

        if (!DialogCore._currentItemId) return;

        try {
            await Api.request('POST', `/api/items/${DialogCore._currentItemId}/attachments`, {
                item_id: DialogCore._currentItemId,
                filename,
                data: dataUrl,
            });
            DialogCore.close('annotate-dialog');
            await Attachments._loadAttachments(DialogCore._currentItemId);
            DetailDialog.switchDetailTab('detail-attach');
        } catch (err) {
            console.error('Failed to save annotation:', err);
        }
    },
};