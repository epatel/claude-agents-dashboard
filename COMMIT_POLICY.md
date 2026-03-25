# Commit Policy

## Annotated Images Policy

**Do not commit annotated images when approving and merging tasks.**

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