import pytest
from pathlib import Path

from src.web.file_routes import (
    parse_browserhidden,
    load_browserhidden_patterns,
    matches_browserhidden,
    _browserhidden_cache,
)


class TestValidateFileBrowserPath:
    """Tests for file browser path validation."""

    def test_rejects_absolute_path(self):
        from src.web.file_routes import validate_file_browser_path
        with pytest.raises(ValueError, match="absolute"):
            validate_file_browser_path("/etc/passwd", Path("/project"))

    def test_rejects_parent_traversal(self):
        from src.web.file_routes import validate_file_browser_path
        with pytest.raises(ValueError, match="traversal"):
            validate_file_browser_path("../etc/passwd", Path("/project"))

    def test_rejects_null_bytes(self):
        from src.web.file_routes import validate_file_browser_path
        with pytest.raises(ValueError, match="null"):
            validate_file_browser_path("file\x00.txt", Path("/project"))

    def test_accepts_valid_relative_path(self):
        from src.web.file_routes import validate_file_browser_path
        result = validate_file_browser_path("src/main.py", Path("/project"))
        assert result == Path("/project/src/main.py")

    def test_rejects_control_characters(self):
        from src.web.file_routes import validate_file_browser_path
        with pytest.raises(ValueError, match="control"):
            validate_file_browser_path("file\x01.txt", Path("/project"))

    def test_rejects_empty_path(self):
        from src.web.file_routes import validate_file_browser_path
        with pytest.raises(ValueError):
            validate_file_browser_path("", Path("/project"))


class TestIsSecretFile:
    def test_env_file(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file(".env") is True

    def test_env_local(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file(".env.local") is True

    def test_env_production(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file(".env.production") is True

    def test_pem_file(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("server.pem") is True

    def test_id_rsa(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("id_rsa") is True

    def test_normal_python_file(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("main.py") is False

    def test_normal_env_like_name(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("environment.py") is False


class TestDetectLanguage:
    def test_python(self):
        from src.web.file_routes import detect_language
        assert detect_language("main.py") == "python"

    def test_javascript(self):
        from src.web.file_routes import detect_language
        assert detect_language("app.js") == "javascript"

    def test_typescript(self):
        from src.web.file_routes import detect_language
        assert detect_language("index.ts") == "typescript"

    def test_unknown_extension(self):
        from src.web.file_routes import detect_language
        assert detect_language("data.xyz") is None

    def test_no_extension(self):
        from src.web.file_routes import detect_language
        assert detect_language("Makefile") is None


class TestIsExcluded:
    def test_git_dir_excluded(self):
        from src.web.file_routes import is_excluded_entry
        assert is_excluded_entry(".git", is_dir=True) is True

    def test_node_modules_excluded(self):
        from src.web.file_routes import is_excluded_entry
        assert is_excluded_entry("node_modules", is_dir=True) is True

    def test_ds_store_excluded(self):
        from src.web.file_routes import is_excluded_entry
        assert is_excluded_entry(".DS_Store", is_dir=False) is True

    def test_normal_dir_not_excluded(self):
        from src.web.file_routes import is_excluded_entry
        assert is_excluded_entry("src", is_dir=True) is False

    def test_normal_file_not_excluded(self):
        from src.web.file_routes import is_excluded_entry
        assert is_excluded_entry("main.py", is_dir=False) is False


class TestScanDirectory:
    def _make_tree(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hello')")
        (tmp_path / "src" / "utils").mkdir()
        (tmp_path / "src" / "utils" / "helpers.py").write_text("")
        (tmp_path / "README.md").write_text("# Project")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        (tmp_path / ".git").mkdir()
        (tmp_path / ".DS_Store").write_text("")
        return tmp_path

    def test_scans_top_level(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=1)
        names = [n["name"] for n in tree]
        assert "src" in names
        assert "README.md" in names

    def test_excludes_git_and_node_modules(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=1)
        names = [n["name"] for n in tree]
        assert ".git" not in names
        assert "node_modules" not in names

    def test_excludes_ds_store(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=2)
        all_names = []
        def collect(nodes):
            for n in nodes:
                all_names.append(n["name"])
                if n.get("children"):
                    collect(n["children"])
        collect(tree)
        assert ".DS_Store" not in all_names

    def test_dirs_sorted_before_files(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=1)
        types = [n["type"] for n in tree]
        dir_indices = [i for i, t in enumerate(types) if t == "dir"]
        file_indices = [i for i, t in enumerate(types) if t == "file"]
        if dir_indices and file_indices:
            assert max(dir_indices) < min(file_indices)

    def test_depth_limits_children(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=1)
        src = next(n for n in tree if n["name"] == "src")
        assert src["children"] is None

    def test_depth_2_includes_children(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=2)
        src = next(n for n in tree if n["name"] == "src")
        assert src["children"] is not None
        child_names = [c["name"] for c in src["children"]]
        assert "main.py" in child_names
        assert "utils" in child_names

    def test_relative_paths_in_output(self, tmp_path):
        from src.web.file_routes import scan_directory
        root = self._make_tree(tmp_path)
        tree = scan_directory(root, root, depth=2)
        src = next(n for n in tree if n["name"] == "src")
        assert src["path"] == "src"
        main = next(c for c in src["children"] if c["name"] == "main.py")
        assert main["path"] == "src/main.py"


class TestReadFileContent:
    """Tests for file content reading."""

    def test_reads_text_file(self, tmp_path):
        from src.web.file_routes import read_file_content
        (tmp_path / "hello.py").write_text("print('hello')")
        result = read_file_content(tmp_path / "hello.py", "hello.py")
        assert result["content"] == "print('hello')"
        assert result["binary"] is False
        assert result["language"] == "python"
        assert result["lines"] == 1

    def test_detects_binary_file(self, tmp_path):
        from src.web.file_routes import read_file_content
        (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
        result = read_file_content(tmp_path / "data.bin", "data.bin")
        assert result["binary"] is True
        assert result["content"] is None

    def test_reads_image_as_base64(self, tmp_path):
        from src.web.file_routes import read_file_content
        png_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        (tmp_path / "pixel.png").write_bytes(png_data)
        result = read_file_content(tmp_path / "pixel.png", "pixel.png")
        assert result["binary"] is True
        assert result["content"].startswith("data:image/png;base64,")
        assert result["mime_type"] == "image/png"

    def test_truncates_large_text(self, tmp_path):
        from src.web.file_routes import read_file_content
        large = "x" * 2_000_000
        (tmp_path / "big.txt").write_text(large)
        result = read_file_content(tmp_path / "big.txt", "big.txt")
        assert result["truncated"] is True
        assert len(result["content"]) <= 1_000_001

    def test_secret_file_hidden(self, tmp_path):
        from src.web.file_routes import read_file_content
        (tmp_path / ".env").write_text("SECRET_KEY=abc123")
        result = read_file_content(tmp_path / ".env", ".env")
        assert result["hidden"] is True
        assert result["content"] is None


class TestParseBrowsehidden:
    """Tests for .browserhidden file parsing."""

    def test_parses_simple_patterns(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("credentials.yaml\nmy-tokens.txt\n")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == ["credentials.yaml", "my-tokens.txt"]

    def test_ignores_comments(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("# This is a comment\n*.secret\n# Another comment\n")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == ["*.secret"]

    def test_ignores_empty_lines(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("*.yaml\n\n\n*.json\n")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == ["*.yaml", "*.json"]

    def test_strips_whitespace(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("  credentials.yaml  \n  *.key  \n")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == ["credentials.yaml", "*.key"]

    def test_returns_empty_for_missing_file(self, tmp_path):
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == []

    def test_returns_empty_for_empty_file(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == []

    def test_handles_comments_only_file(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("# just comments\n# nothing else\n")
        patterns = parse_browserhidden(tmp_path / ".browserhidden")
        assert patterns == []


class TestMatchesBrowsehidden:
    """Tests for pattern matching against .browserhidden patterns."""

    def test_matches_exact_filename(self):
        assert matches_browserhidden("credentials.yaml", "credentials.yaml", ["credentials.yaml"])

    def test_matches_glob_pattern(self):
        assert matches_browserhidden("tokens.txt", "tokens.txt", ["*.txt"])

    def test_no_match_returns_false(self):
        assert not matches_browserhidden("main.py", "main.py", ["*.txt"])

    def test_matches_path_pattern(self):
        assert matches_browserhidden("secret.json", "config/secrets/secret.json", ["config/secrets/*"])

    def test_path_pattern_no_match_different_dir(self):
        assert not matches_browserhidden("secret.json", "other/secret.json", ["config/secrets/*"])

    def test_matches_complex_glob(self):
        assert matches_browserhidden("my-tokens.txt", "my-tokens.txt", ["my-*"])

    def test_multiple_patterns(self):
        patterns = ["*.yaml", "*.secret", "tokens.*"]
        assert matches_browserhidden("creds.yaml", "creds.yaml", patterns)
        assert matches_browserhidden("api.secret", "api.secret", patterns)
        assert matches_browserhidden("tokens.json", "tokens.json", patterns)
        assert not matches_browserhidden("main.py", "main.py", patterns)


class TestLoadBrowsehiddenPatterns:
    """Tests for loading and caching .browserhidden patterns."""

    def setup_method(self):
        _browserhidden_cache.clear()

    def test_loads_patterns_from_project_root(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("*.secret\ncreds.yaml\n")
        patterns = load_browserhidden_patterns(tmp_path)
        assert patterns == ["*.secret", "creds.yaml"]

    def test_returns_empty_when_no_file(self, tmp_path):
        patterns = load_browserhidden_patterns(tmp_path)
        assert patterns == []

    def test_caches_by_mtime(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("*.secret\n")
        p1 = load_browserhidden_patterns(tmp_path)
        p2 = load_browserhidden_patterns(tmp_path)
        assert p1 == p2
        assert str(tmp_path) in _browserhidden_cache

    def test_invalidates_cache_on_mtime_change(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("*.secret\n")
        p1 = load_browserhidden_patterns(tmp_path)
        assert p1 == ["*.secret"]

        # Modify file
        import time
        time.sleep(0.05)  # Ensure mtime differs
        (tmp_path / ".browserhidden").write_text("*.yaml\n")
        # Force mtime change
        import os
        os.utime(tmp_path / ".browserhidden", (time.time() + 1, time.time() + 1))

        p2 = load_browserhidden_patterns(tmp_path)
        assert p2 == ["*.yaml"]

    def test_clears_cache_when_file_deleted(self, tmp_path):
        (tmp_path / ".browserhidden").write_text("*.secret\n")
        load_browserhidden_patterns(tmp_path)
        assert str(tmp_path) in _browserhidden_cache

        (tmp_path / ".browserhidden").unlink()
        patterns = load_browserhidden_patterns(tmp_path)
        assert patterns == []
        assert str(tmp_path) not in _browserhidden_cache


class TestIsSecretFileWithBrowsehidden:
    """Tests for is_secret_file with .browserhidden patterns."""

    def test_builtin_patterns_still_work(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file(".env") is True
        assert is_secret_file("server.pem") is True

    def test_extra_patterns_match(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("credentials.yaml", extra_patterns=["credentials.yaml"])

    def test_extra_glob_patterns_match(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("my-tokens.txt", extra_patterns=["my-*"])

    def test_extra_path_pattern_match(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("secret.json", "config/secrets/secret.json", ["config/secrets/*"])

    def test_no_extra_patterns_normal_behavior(self):
        from src.web.file_routes import is_secret_file
        assert is_secret_file("main.py") is False
        assert is_secret_file("main.py", extra_patterns=[]) is False


class TestScanDirectoryWithBrowsehidden:
    """Tests for scan_directory filtering with .browserhidden patterns."""

    def test_hides_matching_files(self, tmp_path):
        from src.web.file_routes import scan_directory
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "credentials.yaml").write_text("secret: true")
        tree = scan_directory(tmp_path, tmp_path, depth=1, browserhidden_patterns=["credentials.yaml"])
        names = [n["name"] for n in tree]
        assert "main.py" in names
        assert "credentials.yaml" not in names

    def test_hides_matching_dirs(self, tmp_path):
        from src.web.file_routes import scan_directory
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("")
        (tmp_path / "secret-config").mkdir()
        (tmp_path / "secret-config" / "keys.yaml").write_text("")
        tree = scan_directory(tmp_path, tmp_path, depth=2, browserhidden_patterns=["secret-config"])
        names = [n["name"] for n in tree]
        assert "src" in names
        assert "secret-config" not in names

    def test_hides_glob_matching_files(self, tmp_path):
        from src.web.file_routes import scan_directory
        (tmp_path / "app.py").write_text("")
        (tmp_path / "passwords.txt").write_text("hunter2")
        (tmp_path / "notes.txt").write_text("ok")
        tree = scan_directory(tmp_path, tmp_path, depth=1, browserhidden_patterns=["passwords.*"])
        names = [n["name"] for n in tree]
        assert "app.py" in names
        assert "notes.txt" in names
        assert "passwords.txt" not in names

    def test_no_patterns_shows_everything(self, tmp_path):
        from src.web.file_routes import scan_directory
        (tmp_path / "main.py").write_text("")
        (tmp_path / "credentials.yaml").write_text("")
        tree = scan_directory(tmp_path, tmp_path, depth=1, browserhidden_patterns=None)
        names = [n["name"] for n in tree]
        assert "main.py" in names
        assert "credentials.yaml" in names

    def test_hides_nested_files_via_path_pattern(self, tmp_path):
        from src.web.file_routes import scan_directory
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "public.yaml").write_text("")
        (tmp_path / "config" / "secrets.yaml").write_text("")
        tree = scan_directory(tmp_path, tmp_path, depth=2, browserhidden_patterns=["config/secrets.yaml"])
        config_node = next(n for n in tree if n["name"] == "config")
        child_names = [c["name"] for c in config_node["children"]]
        assert "public.yaml" in child_names
        assert "secrets.yaml" not in child_names


class TestReadFileContentWithBrowsehidden:
    """Tests for read_file_content with .browserhidden patterns."""

    def test_hides_file_matching_browserhidden(self, tmp_path):
        from src.web.file_routes import read_file_content
        (tmp_path / "credentials.yaml").write_text("secret: true")
        result = read_file_content(
            tmp_path / "credentials.yaml", "credentials.yaml",
            browserhidden_patterns=["credentials.yaml"],
        )
        assert result["hidden"] is True
        assert result["content"] is None

    def test_normal_file_not_hidden(self, tmp_path):
        from src.web.file_routes import read_file_content
        (tmp_path / "app.py").write_text("print('hi')")
        result = read_file_content(
            tmp_path / "app.py", "app.py",
            browserhidden_patterns=["credentials.yaml"],
        )
        assert result.get("hidden") is not True
        assert result["content"] == "print('hi')"
