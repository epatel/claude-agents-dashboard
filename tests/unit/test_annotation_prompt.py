"""Tests for annotation attachment prompt grouping."""
import pytest
from src.agent.session import build_attachment_prompt


def test_paired_annotations_grouped():
    """Paired annotation files produce grouped prompt with summary."""
    attachments = [
        {"filename": "annotation_123_original.jpg", "dest": "/w/annotation_123_original.jpg",
         "annotation_summary": "2 arrows, 1 circle"},
        {"filename": "annotation_123_annotated.jpg", "dest": "/w/annotation_123_annotated.jpg",
         "annotation_summary": None},
    ]
    result = build_attachment_prompt(attachments)
    assert "clean screenshot" in result
    assert "annotation markers" in result
    assert "2 arrows, 1 circle" in result
    assert "annotation_123_original.jpg" in result
    assert "annotation_123_annotated.jpg" in result


def test_single_attachment_no_grouping():
    """Non-annotation attachments use simple format."""
    attachments = [
        {"filename": "screenshot.png", "dest": "/w/screenshot.png", "annotation_summary": None},
    ]
    result = build_attachment_prompt(attachments)
    assert "/w/screenshot.png" in result
    assert "clean screenshot" not in result


def test_only_original_no_annotated():
    """Original-only (no annotations drawn) uses simple format."""
    attachments = [
        {"filename": "annotation_456_original.jpg", "dest": "/w/annotation_456_original.jpg",
         "annotation_summary": None},
    ]
    result = build_attachment_prompt(attachments)
    assert "/w/annotation_456_original.jpg" in result
    assert "annotation markers" not in result


def test_mixed_attachments():
    """Mix of paired annotations and plain attachments."""
    attachments = [
        {"filename": "annotation_123_original.jpg", "dest": "/w/annotation_123_original.jpg",
         "annotation_summary": "1 arrow"},
        {"filename": "annotation_123_annotated.jpg", "dest": "/w/annotation_123_annotated.jpg",
         "annotation_summary": None},
        {"filename": "diagram.png", "dest": "/w/diagram.png", "annotation_summary": None},
    ]
    result = build_attachment_prompt(attachments)
    assert "1 arrow" in result
    assert "clean screenshot" in result
    assert "/w/diagram.png" in result


def test_empty_attachments():
    """No attachments returns empty string."""
    result = build_attachment_prompt([])
    assert result == ""
