# Commit Policy

> **Load when**: about to run `git commit`, or your changes touch annotated images / agent merge artifacts.
> **Skip when**: not committing.

## Annotated Images Policy

**Do not commit annotated images when approving and merging tasks.**

The dashboard exports annotation attachments into `agents-lab/assets/` as `annotation_<ts>_original.jpg` (clean) and `annotation_<ts>_annotated.jpg` (overlay) when there is an annotation summary, or a single `annotation_<ts>.png` when there is not. The `agents-lab/` directory is excluded from the target project's `.gitignore` — but only in **single-repo mode** (`src/main.py:156`); a multi-repo workspace gets no auto-entry, so this policy matters more there. Either way it is the safety net for annotation files an agent accidentally writes inside a worktree.

### Rules:
1. All annotation images matching the pattern `annotation_*.*` are excluded via `.gitignore`
2. Before approving or merging any task, verify that no annotation images are included in the commit
3. Annotation images are temporary artifacts and should not be persisted in the repository

### Covered File Patterns:
- `annotation_*.png`
- `annotation_*.jpg`
- `annotation_*.jpeg`
- `annotation_*.gif`
- `annotation_*.webp`

### Verification Script:
Run the following command before commits to ensure no annotation files are staged:

```bash
git status --porcelain | grep -E "annotation_.*\.(png|jpg|jpeg|gif|webp)"
```

If this command returns any results, remove the annotation files from staging before committing.

### Implementation:
- ✅ Added annotation patterns to `.gitignore`
- ✅ Created policy documentation
- 📝 Manual verification required during merge/approval process

---

**See also**: none — commit conventions stand alone.