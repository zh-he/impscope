import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = REPO_ROOT / ".tmp-tests"
TEST_TMP_ROOT.mkdir(exist_ok=True)


def make_test_root(test_id: str) -> Path:
    safe_name = "".join(ch if ch.isalnum() else "_" for ch in test_id)
    root = TEST_TMP_ROOT / f"{safe_name}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_sample_project(root: Path) -> None:
    write(root / "pkg" / "__init__.py", "")
    write(root / "pkg" / "a.py", "VALUE = 1\n")
    write(root / "pkg" / "b.py", "import pkg.a\n")
    write(root / "pkg" / "c.py", "import pkg.b\n")


def run_impscope(args, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "impscope", *args],
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def init_git_project(root: Path) -> None:
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


@unittest.skipIf(shutil.which("git") is None, "git is required for CLI default report tests")
class CliDefaultReportTests(unittest.TestCase):
    def test_default_command_reports_current_python_change_impact(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)
        init_git_project(root)
        write(root / "pkg" / "a.py", "VALUE = 2\n")

        res = run_impscope(["--path", str(root)], REPO_ROOT)

        self.assertIn("Current Change Impact", res.stdout)
        self.assertIn("pkg/a.py", res.stdout)
        self.assertIn("Direct dependents:   1", res.stdout)
        self.assertIn("Indirect dependents: 1", res.stdout)

    def test_default_json_report_is_machine_readable(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)
        init_git_project(root)
        write(root / "pkg" / "a.py", "VALUE = 2\n")

        res = run_impscope(["--path", str(root), "--format", "json"], REPO_ROOT)
        payload = json.loads(res.stdout)

        self.assertEqual(payload["since"], "working tree")
        self.assertEqual(payload["changed_files"], ["pkg/a.py"])
        self.assertEqual(payload["union"]["direct_dependents"], ["pkg/b.py"])
        self.assertEqual(payload["union"]["indirect_dependents"], ["pkg/c.py"])
        self.assertEqual(payload["union"]["total_impact"], 2)


class CliCommandTests(unittest.TestCase):
    def test_stats_command_still_works_without_git(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        res = run_impscope(["--path", str(root), "stats"], REPO_ROOT)

        self.assertIn("Dependency Statistics", res.stdout)
        self.assertIn("Total Python files: 4", res.stdout)

    def test_impact_command_reports_expected_file(self) -> None:
        root = make_test_root(self.id())
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        create_sample_project(root)

        res = run_impscope(["--path", str(root), "impact", "pkg/a.py"], REPO_ROOT)

        self.assertIn("Impact Analysis for pkg/a.py", res.stdout)
        self.assertIn("pkg/b.py", res.stdout)
        self.assertIn("pkg/c.py", res.stdout)


if __name__ == "__main__":
    unittest.main()
