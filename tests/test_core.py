import io
import shutil
import subprocess
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

from impscope.core import (
    DependencyAnalyzer,
    get_changed_python_files,
    get_working_tree_python_files,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = REPO_ROOT / ".tmp-tests"
TEST_TMP_ROOT.mkdir(exist_ok=True)


def make_test_root(test_id: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in test_id)
    root = TEST_TMP_ROOT / f"{safe_name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)


def create_sample_project(root: Path) -> None:
    write(root / "pkg" / "__init__.py", "")
    write(root / "pkg" / "a.py", "VALUE = 1\n")
    write(root / "pkg" / "b.py", "import pkg.a\n")
    write(root / "pkg" / "c.py", "import pkg.b\n")


@unittest.skipIf(shutil.which("git") is None, "git is required for working tree tests")
class GitChangeTests(unittest.TestCase):
    def test_working_tree_changes_include_uncommitted_python_files(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)
        subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(
            [
                "git", "-C", str(root),
                "-c", "user.name=impscope-test",
                "-c", "user.email=impscope@example.test",
                "commit", "-m", "init",
            ],
            check=True,
            capture_output=True,
        )

        write(root / "pkg" / "a.py", "VALUE = 2\n")

        self.assertEqual(get_working_tree_python_files(root), ["pkg/a.py"])

    def test_changed_files_since_commit_are_relative_to_path(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)
        subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(
            [
                "git", "-C", str(root),
                "-c", "user.name=impscope-test",
                "-c", "user.email=impscope@example.test",
                "commit", "-m", "init",
            ],
            check=True,
            capture_output=True,
        )
        write(root / "pkg" / "a.py", "VALUE = 2\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
        subprocess.run(
            [
                "git", "-C", str(root),
                "-c", "user.name=impscope-test",
                "-c", "user.email=impscope@example.test",
                "commit", "-m", "change-a",
            ],
            check=True,
            capture_output=True,
        )

        self.assertEqual(get_changed_python_files(root / "pkg", "HEAD~1"), ["a.py"])


class DependencyAnalyzerTests(unittest.TestCase):
    def test_impact_analysis_reports_direct_and_indirect_dependents(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory()
        result = analyzer.get_impact_analysis("pkg/a.py")

        self.assertEqual(result["direct_dependents"], ["pkg/b.py"])
        self.assertEqual(result["indirect_dependents"], ["pkg/c.py"])
        self.assertEqual(result["total_impact"], 2)

    def test_impact_analysis_accepts_absolute_paths_under_root(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory()
        result = analyzer.get_impact_analysis(str(root / "pkg" / "a.py"))

        self.assertEqual(result["file"], "pkg/a.py")
        self.assertEqual(result["direct_dependents"], ["pkg/b.py"])
        self.assertEqual(result["indirect_dependents"], ["pkg/c.py"])

    def test_impact_analysis_rejects_absolute_paths_outside_root(self) -> None:
        root = make_test_root(self.id())
        outside = make_test_root(self.id() + ".outside")
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        create_sample_project(root)
        write(outside / "outside.py", "VALUE = 1\n")

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory()
        result = analyzer.get_impact_analysis(str(outside / "outside.py"))

        self.assertEqual(result["error"], f"File is outside analyzed root: {outside / 'outside.py'}")

    def test_exclude_globs_remove_files_from_graph(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory(exclude_globs=["pkg/c.py"])
        result = analyzer.get_impact_analysis("pkg/a.py")

        self.assertEqual(result["direct_dependents"], ["pkg/b.py"])
        self.assertEqual(result["indirect_dependents"], [])

    def test_scan_directory_resets_previous_scan_state(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory()
        analyzer.scan_directory(exclude_globs=["pkg/c.py"])
        result = analyzer.get_impact_analysis("pkg/a.py")

        self.assertNotIn("pkg/c.py", analyzer.files)
        self.assertEqual(result["direct_dependents"], ["pkg/b.py"])
        self.assertEqual(result["indirect_dependents"], [])

    def test_utf8_bom_python_files_are_parsed(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write(root / "bom.py", "import plain\n", encoding="utf-8-sig")
        write(root / "plain.py", "VALUE = 1\n")

        analyzer = DependencyAnalyzer(str(root))
        analyzer.scan_directory()

        self.assertIn("bom.py", analyzer.files)
        self.assertIn("plain.py", analyzer.files)

    def test_duplicate_modules_across_source_roots_emit_warning(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write(root / "src" / "pkg" / "utils.py", "VALUE = 'src'\n")
        write(root / "python" / "pkg" / "utils.py", "VALUE = 'python'\n")

        analyzer = DependencyAnalyzer(str(root), source_roots=["src", "python"])
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            analyzer.scan_directory()

        self.assertIn("Duplicate module name 'pkg.utils'", stderr.getvalue())
        self.assertIn(analyzer.module_map["pkg.utils"], {"src/pkg/utils.py", "python/pkg/utils.py"})

    def test_parse_errors_are_reported_and_bad_file_is_skipped(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write(root / "good.py", "VALUE = 1\n")
        write(root / "bad.py", "def broken(:\n")

        analyzer = DependencyAnalyzer(str(root))
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            analyzer.scan_directory()

        self.assertIn("Error analyzing", stderr.getvalue())
        self.assertIn("bad.py", stderr.getvalue())
        self.assertIn("good.py", analyzer.files)
        self.assertNotIn("bad.py", analyzer.files)

    def test_strict_resolution_disables_parent_package_fallback_for_from_import(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        write(root / "pkg" / "__init__.py", "")
        write(root / "consumer.py", "from pkg.missing import thing\n")

        loose = DependencyAnalyzer(str(root))
        loose.scan_directory()
        strict = DependencyAnalyzer(str(root), strict_resolution=True)
        strict.scan_directory()

        self.assertEqual(loose.dependencies["consumer.py"], {"pkg/__init__.py"})
        self.assertEqual(strict.dependencies.get("consumer.py", set()), set())


if __name__ == "__main__":
    unittest.main()
