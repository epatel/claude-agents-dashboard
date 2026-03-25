import pytest
from pathlib import Path


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
