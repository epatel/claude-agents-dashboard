/**
 * Main Dialogs coordinator - delegates to modular dialog components
 *
 * This file serves as the main entry point for all dialog functionality,
 * maintaining backward compatibility while delegating to specialized modules.
 */

// Import all dialog modules (these would normally be script tags in HTML)
// In a real implementation, these would be loaded via script tags or a module system

const Dialogs = {
    // Core utilities - delegate to DialogCore
    autoScroll: (element) => DialogCore.autoScroll(element),
    open: (id) => DialogCore.open(id),
    close: (id) => DialogCore.close(id),
    confirm: (message, title, okLabel) => DialogCore.confirm(message, title, okLabel),

    // Item dialog - delegate to ItemDialog
    openNewItem: () => ItemDialog.openNewItem(),
    openEditItem: (item) => ItemDialog.openEditItem(item),
    submitItem: (event) => ItemDialog.submitItem(event),
    submitItemAndStart: (event) => ItemDialog.submitItemAndStart(event),
    removePendingAttachment: (index) => ItemDialog.removePendingAttachment(index),
    openAnnotateForNewItem: () => ItemDialog.openAnnotateForNewItem(),

    // Detail dialog - delegate to DetailDialog
    showDetail: (itemId) => DetailDialog.showDetail(itemId),
    switchDetailTab: (tabName) => DetailDialog.switchDetailTab(tabName),

    // Review dialog - delegate to ReviewDialog
    showReview: (itemId) => ReviewDialog.showReview(itemId),
    switchReviewTab: (tabName) => ReviewDialog.switchReviewTab(tabName),

    // Clarification dialog - delegate to ClarificationDialog
    reopenClarification: (itemId) => ClarificationDialog.reopenClarification(itemId),
    showClarification: (itemId, prompt, choices) => ClarificationDialog.showClarification(itemId, prompt, choices),
    submitClarification: (event) => ClarificationDialog.submitClarification(event),

    // Request changes dialog - delegate to RequestChangesDialog
    openRequestChanges: (itemId) => RequestChangesDialog.openRequestChanges(itemId),
    submitChanges: (event) => RequestChangesDialog.submitChanges(event),

    // Config dialog - delegate to ConfigDialog
    openConfig: () => ConfigDialog.openConfig(),
    switchConfigTab: (tabName) => ConfigDialog.switchConfigTab(tabName),
    addPlugin: () => ConfigDialog.addPlugin(),
    removePlugin: (index) => ConfigDialog.removePlugin(index),
    submitConfig: (event) => ConfigDialog.submitConfig(event),

    // Attachments - delegate to Attachments
    viewAttachment: (src, filename) => Attachments.viewAttachment(src, filename),
    deleteAttachment: (attachmentId, itemId) => Attachments.deleteAttachment(attachmentId, itemId),

    // Annotation canvas - delegate to AnnotationCanvas
    openAnnotateCanvas: () => AnnotationCanvas.openAnnotateCanvas(),
    setAnnotateTool: (tool) => AnnotationCanvas.setAnnotateTool(tool),
    saveAnnotation: () => AnnotationCanvas.saveAnnotation(),

    // Utility functions - delegate to DialogUtils
    renderMarkdown: (text) => DialogUtils.renderMarkdown(text),

    // Expose internal state for backward compatibility
    get _currentItemId() { return DialogCore._currentItemId; },
    set _currentItemId(value) { DialogCore._currentItemId = value; },

    get _pendingAttachments() { return ItemDialog._pendingAttachments; },
    set _pendingAttachments(value) { ItemDialog._pendingAttachments = value; },

    get _configPlugins() { return ConfigDialog._configPlugins; },
    set _configPlugins(value) { ConfigDialog._configPlugins = value; },

    // Legacy methods for backward compatibility
    _getModelDisplayName: (modelId) => DialogUtils._getModelDisplayName(modelId),
    _updateDefaultModelDisplay: () => ItemDialog._updateDefaultModelDisplay(),
    _loadAttachments: (itemId) => Attachments._loadAttachments(itemId),
    _showDetailDirect: (itemId) => DetailDialog._showDetailDirect(itemId),
    _renderFormAttachments: () => ItemDialog._renderFormAttachments(),
    _loadFormAttachments: (itemId) => ItemDialog._loadFormAttachments(itemId),
    _renderPluginsList: () => ConfigDialog._renderPluginsList(),

    // Properties that need to be accessible for cross-module communication
    _annotateTarget: null,
};
