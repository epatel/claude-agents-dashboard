#!/bin/bash
# Check for annotation images in git staging area
# Usage: ./check-annotations.sh

echo "🔍 Checking for annotation images in staging area..."

# Check for staged annotation files
annotation_files=$(git status --porcelain | grep -E "^[AM].*annotation_.*\.(png|jpg|jpeg|gif|webp)")

if [ -n "$annotation_files" ]; then
    echo "❌ ERROR: Annotation images found in staging area:"
    echo "$annotation_files"
    echo ""
    echo "🚫 Policy violation: Do not commit annotated images when approving and merging tasks."
    echo "📋 Remove these files from staging before committing:"
    echo "   git reset HEAD <filename>"
    exit 1
else
    echo "✅ No annotation images found in staging area."
    echo "🎉 Safe to commit!"
    exit 0
fi