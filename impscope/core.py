"""
Core functionality for analyzing Python code dependencies
"""
import ast
import fnmatch
import re
import shutil
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to extract import statements from Python files"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.imports: List[Dict] = []
        self.from_imports: List[Dict] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                {
                    "module": alias.name,
                    "alias": alias.asname,
                    "lineno": node.lineno
                }
            )
        # Continue traversal for completeness (Import has alias children only)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module  # may be None for "from . import X"
        for alias in node.names:
            self.from_imports.append(
                {
                    "module": module,
                    "name": alias.name,  # may be "*"
                    "alias": alias.asname,
                    "level": node.level,  # 0 abs, >=1 relative
                    "lineno": node.lineno
                }
            )
        self.generic_visit(node)


class DependencyAnalyzer:
    """
    Main class for analyzing Python code dependencies.

    Steps:
      1) scan_directory: index Python files -> parse AST -> collect imports -> build module map
      2) _resolve_dependencies: resolve import targets to project files -> build graph
    """

    def __init__(
            self,
            root_path: str = ".",
            strict_resolution: bool = False,
            source_roots: Optional[List[str]] = None,
            include_outside_roots: bool = False
    ):
        """
        :param root_path: project root to scan
        :param strict_resolution:
            - If True: only resolve exact modules found in module_map.
              No fallback to parent packages (more precise, fewer edges).
            - If False (default): heuristic fallback to nearest existing parent package/module.
        :param source_roots: list of source root directories relative to root_path
            e.g., ["src"], ["src", "python"], ["lib/code"].
            When provided, only files under these roots are scanned and module
            names are computed relative to the matched root (src/pkg/mod.py -> pkg.mod).
        :param include_outside_roots: when source_roots is provided:
            - If False (default), files outside these roots are ignored.
            - If True, files outside roots are included and mapped from project root.
        """
        self.root_path: Path = Path(root_path).resolve()

        # Files indexed: rel_path -> file_info
        self.files: Dict[str, Dict] = {}

        # Graph
        # dependencies: file -> set(files it depends on)
        # dependents:   file -> set(files that depend on it)
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.dependents: Dict[str, Set[str]] = defaultdict(set)

        # Module maps
        # module_name -> rel_path (e.g., "pkg.sub.mod" -> "pkg/sub/mod.py")
        self.module_map: Dict[str, str] = {}
        # rel_path -> module_name
        self.path_to_module: Dict[str, str] = {}

        # Resolution behavior
        self.strict_resolution: bool = strict_resolution

        # Source roots config
        self.source_roots: List[Path] = []
        if source_roots:
            for sr in source_roots:
                sr_path = (self.root_path / sr).resolve()
                self.source_roots.append(sr_path)
                if not sr_path.exists():
                    print(f"Warning: source_root does not exist: {sr_path}", file=sys.stderr)
        self.include_outside_roots: bool = include_outside_roots

    # ----------------------------
    # Scanning & indexing
    # ----------------------------
    def scan_directory(
            self,
            ignore_dirs: Optional[List[str]] = None,
            exclude_globs: Optional[List[str]] = None
    ) -> None:
        """Scan directory for Python files and analyze them"""
        if ignore_dirs is None:
            ignore_dirs = [
                ".git", ".hg", ".svn",  # Version control
                ".venv", "venv", "env",  # Virtual environments
                "node_modules", "dist", "build",  # Build / distribution artifacts
                "__pycache__", ".mypy_cache", ".pytest_cache"  # Python caches
            ]
        exclude_globs = exclude_globs or []

        python_files: List[Path] = []

        def should_skip_dir(p: Path) -> bool:
            # Skip if any path part is in ignore_dirs
            try:
                return any(part in ignore_dirs for part in p.parts)
            except Exception:
                return False

        # Python 3.8-compatible check: whether `path` is under `base`
        def _is_under(path: Path, base: Path) -> bool:
            try:
                # Python 3.9+
                return path.is_relative_to(base)
            except AttributeError:
                # Fallback for Python 3.8 and below
                try:
                    path.resolve().relative_to(base)
                    return True
                except Exception:
                    return False

        # Choose search roots
        search_roots: List[Path]
        if self.source_roots:
            search_roots = [sr for sr in self.source_roots if sr.exists()]
            if not search_roots:
                print("Warning: No valid source_roots exist on disk. Nothing to scan.", file=sys.stderr)
                return
        else:
            search_roots = [self.root_path]

        # Walk each search root
        for base in search_roots:
            for file_path in base.rglob("*.py"):
                # Skip ignored directories by name
                if should_skip_dir(file_path):
                    continue

                # Normalize relative path (POSIX style) relative to project root
                try:
                    rel = str(file_path.relative_to(self.root_path)).replace("\\", "/")
                except Exception:
                    # If not under root_path (e.g., symlink or mount boundary), skip
                    continue

                # Apply user excludes (glob on relative path)
                if exclude_globs and any(fnmatch.fnmatch(rel, pat) for pat in exclude_globs):
                    continue

                # Optionally skip symlinked files to avoid surprises
                try:
                    if file_path.is_symlink():
                        continue
                except Exception:
                    pass

                python_files.append(file_path)

        # If include_outside_roots is False and source_roots present,
        # we have already scanned only inside roots, so nothing outside is present.
        # If include_outside_roots is True, also scan entire root_path for files
        # not included yet (outside source_roots).
        if self.source_roots and self.include_outside_roots:
            for file_path in self.root_path.rglob("*.py"):
                # Use compatibility helper instead of Path.is_relative_to (works on Py3.8+)
                if any(_is_under(file_path, sr) for sr in self.source_roots):
                    continue  # already covered
                if should_skip_dir(file_path):
                    continue
                try:
                    rel = str(file_path.relative_to(self.root_path)).replace("\\", "/")
                except Exception:
                    continue
                if exclude_globs and any(fnmatch.fnmatch(rel, pat) for pat in exclude_globs):
                    continue
                try:
                    if file_path.is_symlink():
                        continue
                except Exception:
                    pass
                python_files.append(file_path)

        # Deduplicate files (in case of overlapping roots)
        seen: Set[str] = set()
        unique_files: List[Path] = []
        for f in python_files:
            try:
                rel = str(f.relative_to(self.root_path)).replace("\\", "/")
            except Exception:
                continue
            if rel not in seen:
                seen.add(rel)
                unique_files.append(f)

        # First pass: collect files and build module map
        for file_path in unique_files:
            self._analyze_file(file_path)

        # Second pass: resolve dependencies with module map ready
        self._resolve_dependencies()

    def _analyze_file(self, file_path: Path) -> None:
        """Analyze a single Python file and index its module name"""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
            visitor = ImportVisitor(str(file_path))
            visitor.visit(tree)

            try:
                rel_path = file_path.relative_to(self.root_path)
            except Exception:
                # Should not happen because we filtered earlier
                return

            rel_str = str(rel_path).replace("\\", "/")

            # Determine if under a source_root (if configured)
            within_root_rel: Optional[Path] = self._rel_within_source_root(rel_path)

            if self.source_roots and within_root_rel is None and not self.include_outside_roots:
                print(
                    f"Info: Skipping file outside source_roots: {rel_str}",
                    file=sys.stderr
                )
                return

            # Use path within source root (if matched), else relative to project root
            path_for_module = within_root_rel if within_root_rel is not None else rel_path

            module_name = self._path_to_module(path_for_module)
            if not module_name:
                # e.g., top-level __init__.py (rare but possible) yields ""
                print(
                    f"Warning: Skipping file with empty module name: {rel_str}",
                    file=sys.stderr
                )
                return

            is_package = path_for_module.name == "__init__.py"

            self.files[rel_str] = {
                "path": file_path,
                "module": module_name,
                "is_package": is_package,
                "imports": visitor.imports,
                "from_imports": visitor.from_imports,
                "size": len(content.splitlines())
            }

            # Warn if duplicate module name maps to different files
            previous = self.module_map.get(module_name)
            if previous and previous != rel_str:
                print(
                    f"Warning: Duplicate module name '{module_name}' for {rel_str} "
                    f"(already mapped to {previous})",
                    file=sys.stderr,
                )

            self.module_map[module_name] = rel_str
            self.path_to_module[rel_str] = module_name

        except Exception as e:
            # Soft-fail: skip unreadable/broken files
            print(f"Error analyzing {file_path}: {e}", file=sys.stderr)

    def _rel_within_source_root(self, rel_path: Path) -> Optional[Path]:
        """
        If rel_path (relative to project root) is under any configured source_root,
        return the portion relative to that source_root. Else return None.
        """
        if not self.source_roots:
            return rel_path

        abs_path = (self.root_path / rel_path).resolve()
        for sr in self.source_roots:
            try:
                # Python 3.9+: Path.is_relative_to
                if abs_path.is_relative_to(sr):
                    return abs_path.relative_to(sr)
            except AttributeError:
                # Fallback for older Python: manual check
                try:
                    return abs_path.relative_to(sr)
                except Exception:
                    pass
        return None

    @staticmethod
    def _path_to_module(rel_path_within_root: Path) -> str:
        """Convert a path relative to a source root into a Python module name"""
        parts = rel_path_within_root.with_suffix("").parts
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    # ----------------------------
    # Resolution
    # ----------------------------
    def _resolve_dependencies(self) -> None:
        for file_path, file_info in self.files.items():
            self._resolve_file_dependencies(file_path, file_info)

    def _resolve_file_dependencies(self, file_path: str, file_info: dict) -> None:
        """Resolve dependencies for a single file"""
        current_module = file_info["module"]
        current_is_pkg = file_info["is_package"]

        # 'import module'
        for imp in file_info["imports"]:
            target = self._resolve_absolute_import(imp["module"])
            if target:
                self._link(file_path, target)

        # 'from module import name'
        for imp in file_info["from_imports"]:
            level = imp["level"]
            module = imp["module"]  # may be None for 'from . import X'
            name = imp["name"]

            target = self._resolve_from_import(level, module, name, current_module, current_is_pkg)
            if target:
                self._link(file_path, target)

    def _link(self, src_file: str, dst_file: str) -> None:
        """Register a dependency edge src -> dst"""
        if src_file == dst_file:
            # Avoid self loops if they ever arise
            return
        self.dependencies[src_file].add(dst_file)
        self.dependents[dst_file].add(src_file)

    def _resolve_absolute_import(self, module_name: str) -> Optional[str]:
        """
        Resolve 'import pkg.sub' (absolute imports only) to an indexed project file.

        Behavior:
          - If strict_resolution: only exact module matches (return None if not found).
          - Else: if module doesn't exist, fallback to nearest existing parent package.
        """
        if not module_name:
            return None

        if module_name in self.module_map:
            return self.module_map[module_name]

        if self.strict_resolution:
            return None

        # Heuristic: fallback to parent packages (pkg.sub.mod -> pkg.sub -> pkg)
        parts = module_name.split(".")
        for i in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in self.module_map:
                return self.module_map[candidate]

        return None

    def _resolve_from_import(
            self,
            level: int,
            module: Optional[str],
            name: str,
            current_module: str,
            current_is_pkg: bool,
    ) -> Optional[str]:
        """
        Resolve 'from module import name' (absolute or relative) to an indexed project file.

        Strategy:
          1) Build an effective base module per PEP 328 (relative dots).
          2) Try base+'.'+name as a submodule; if not present, try 'base' itself.
          3) For absolute 'from pkg import name', try 'pkg.name' first, else 'pkg'.
          4) If strict_resolution=False, allow fallback to nearest existing parent of base.
        """
        curr_parts = current_module.split(".") if current_module else []

        # When importing from a module file (not __init__), drop the last segment to get its package
        if not current_is_pkg and curr_parts:
            curr_parts = curr_parts[:-1]

        # Compute base for relative imports
        if level > 0:
            # Level indicates number of leading dots; per AST, level>=1 means at least one dot.
            # Ascend = level - 1 steps from current package
            ascend = max(0, level - 1)

            # If trying to go above the top, treat as unresolvable (avoid mapping to top-level by accident)
            if ascend > len(curr_parts):
                return None

            base_parts: List[str] = curr_parts[: len(curr_parts) - ascend]
            if module:
                base = ".".join(base_parts + module.split("."))
            else:
                base = ".".join(base_parts)
        else:
            # Absolute import
            base = module or ""

        # Handle star import: map to the base module if available
        if name == "*":
            if base in self.module_map:
                return self.module_map[base]
            if self.strict_resolution:
                return None

            # Heuristic fallback for absolute base: nearest existing parent of base
            if base:
                parts = base.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    parent = ".".join(parts[:i])
                    if parent in self.module_map:
                        return self.module_map[parent]
            return None

        # Prefer resolving explicit submodule first: base.name (or just name if base is empty)
        candidate_sub = f"{base}.{name}" if base else name
        if candidate_sub in self.module_map:
            return self.module_map[candidate_sub]

        # Fallback to the base module itself
        if base in self.module_map:
            return self.module_map[base]

        if self.strict_resolution:
            return None

        # Final heuristic fallback for absolute "from pkg import X": climb up parents of base
        if level == 0 and base:
            parts = base.split(".")
            for i in range(len(parts) - 1, 0, -1):
                parent = ".".join(parts[:i])
                if parent in self.module_map:
                    return self.module_map[parent]

        return None

    # ----------------------------
    # Public APIs
    # ----------------------------
    def get_impact_analysis(self, file_path: str) -> Dict:
        """Get impact analysis for a specific file (direct + indirect dependents)"""
        normalized = file_path.replace("\\", "/")

        # Accept partial matches like "models.py", but handle ambiguity deterministically
        if normalized not in self.files:
            endswith_matches = [f for f in self.files if f.endswith(normalized)]
            candidates = endswith_matches or [f for f in self.files if normalized in f]
            if not candidates:
                return {"error": f"File not found: {file_path}"}
            if len(candidates) > 1:
                return {"error": f"Ambiguous file path: {file_path}", "candidates": sorted(candidates)}
            normalized = candidates[0]

        direct_dependents = sorted(self.dependents.get(normalized, set()))

        # BFS to find indirect dependents
        indirect_dependents: List[str] = []
        visited = set(direct_dependents + [normalized])
        queue = deque(direct_dependents)

        while queue:
            current = queue.popleft()
            for dep in self.dependents.get(current, set()):
                if dep not in visited:
                    visited.add(dep)
                    indirect_dependents.append(dep)
                    queue.append(dep)

        return {
            "file": normalized,
            "direct_dependents": direct_dependents,
            "indirect_dependents": sorted(indirect_dependents),
            "total_impact": len(direct_dependents) + len(indirect_dependents),
        }

    def get_unimported_files(self) -> List[str]:
        """List files that are not imported by any other file (best-effort heuristic)."""
        unimported: List[str] = []
        main_guard_re = re.compile(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]')

        for rel_path, info in self.files.items():
            if not self.dependents.get(rel_path):
                # Heuristic: keep scripts with __main__ guard out of "unimported" list
                try:
                    text = info["path"].read_text(encoding="utf-8", errors="replace")
                    if main_guard_re.search(text):
                        continue
                except Exception:
                    # If we can't read the file now, treat as unimported
                    pass
                unimported.append(rel_path)
        return sorted(unimported)

    def get_most_depended_files(self, limit: int = 10, ascending: bool = False) -> List[Tuple[str, int]]:
        """
        Ranked by number of dependents (reverse in-degree).
        ascending=False -> largest first (default).
        ascending=True  -> smallest first.
        Stable tie-break by file path to ensure deterministic output.
        """
        file_scores = [(file_path, len(deps)) for file_path, deps in self.dependents.items()]
        if ascending:
            file_scores.sort(key=lambda x: (x[1], x[0]))
        else:
            file_scores.sort(key=lambda x: (-x[1], x[0]))
        return file_scores[:limit]


# ----------------------------
# Git integration (no third-party deps)
# ----------------------------
def get_changed_python_files(
        repo_root: Path,
        since_commit: str,
        exclude_globs: Optional[List[str]] = None,
) -> List[str]:
    """
    Return a list of changed *.py files (relative to repo_root, POSIX-style)
    between since_commit..HEAD, filtered by exclude_globs.

    Requirements:
      - 'git' must be available in PATH
      - repo_root must be inside a Git repo
    """
    exclude_globs = exclude_globs or []

    if shutil.which("git") is None:
        # Git not available
        return []

    # Run: git -C <repo_root> diff --name-only --diff-filter=ACMR <since>..HEAD -- '*.py'
    cmd = [
        "git", "-C", str(repo_root),
        "diff", "--name-only", "--diff-filter=ACMR",
        f"{since_commit}..HEAD", "--", "*.py"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = []
        for line in res.stdout.splitlines():
            path = line.strip()
            if not path.endswith(".py"):
                continue
            # Normalize to POSIX-style
            rel = path.replace("\\", "/")

            # Ensure path is within repo (best-effort)
            # (git diff gives paths relative to repo root by default)
            if any(fnmatch.fnmatch(rel, pat) for pat in exclude_globs):
                continue

            files.append(rel)

        # Unique + sorted for stable output
        return sorted(set(files))
    except subprocess.CalledProcessError:
        # Not a git repo, bad commit, or other error
        return []
