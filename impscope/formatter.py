"""
Output formatting for impscope
"""
import json
from typing import Dict, List, Tuple

from .core import DependencyAnalyzer


class ImpactFormatter:
    """Format analysis results for output"""

    def __init__(self, format_type: str = "text", full: bool = False, limit: int = 10):
        self.format_type = format_type
        self.full = full  # if True, do not truncate long lists (text mode)
        self.limit = max(1, int(limit))  # min 1

    # -------- Impact Analysis --------
    def print_impact_analysis(self, result: Dict) -> None:
        if self.format_type == "json":
            print(json.dumps(result, indent=2))
            return

        if "error" in result:
            print(f"{result['error']}")
            return

        file_path = result["file"]
        direct_all = sorted(result.get("direct_dependents", []))
        indirect_all = sorted(result.get("indirect_dependents", []))
        total = result.get("total_impact", len(direct_all) + len(indirect_all))

        print(f"Impact Analysis for {file_path}")
        print("-" * 60)

        # Direct
        if direct_all:
            direct = direct_all if self.full else direct_all[: self.limit]
            print(f"Direct dependents ({len(direct_all)}):")
            if direct:
                for dep in direct[:-1]:
                    print(f"  ├── {dep}")
                print(f"  └── {direct[-1]}")
            if not self.full and len(direct_all) > len(direct):
                print(f"  └── ... and {len(direct_all) - len(direct)} more")
        else:
            print("Direct dependents: None")

        # Indirect
        if indirect_all:
            indirect = indirect_all if self.full else indirect_all[: self.limit]
            print(f"\nIndirect dependents ({len(indirect_all)}):")
            if indirect:
                for dep in indirect[:-1]:
                    print(f"  ├── {dep}")
                print(f"  └── {indirect[-1]}")
            if not self.full and len(indirect_all) > len(indirect):
                print(f"  └── ... and {len(indirect_all) - len(indirect)} more")
        else:
            print("\nIndirect dependents: None")

        print(f"\nTotal Impact: {total} files")

    # -------- Unimported Files --------
    def print_unimported_files(self, unimported_files: List[str]) -> None:
        if self.format_type == "json":
            print(json.dumps({"unimported_files": unimported_files}, indent=2))
            return

        unimported_all = sorted(unimported_files)
        print("Not Imported By Other Files")
        print("-" * 60)

        if not unimported_all:
            print("0 files are not imported by others.")
            return

        unimported = unimported_all if self.full else unimported_all[: self.limit]
        print(f"{len(unimported_all)} files are not imported by others:")
        if unimported:
            for file_path in unimported[:-1]:
                print(f"  ├── {file_path}")
            print(f"  └── {unimported[-1]}")
        if not self.full and len(unimported_all) > len(unimported):
            print(f"  └── ... and {len(unimported_all) - len(unimported)} more")

    # -------- Graph --------
    def print_dependency_graph(
            self,
            top_files: List[Tuple[str, int]],
            analyzer: DependencyAnalyzer,
            ascending: bool = False,
    ) -> None:
        if self.format_type == "json":
            # JSON: respect provided list; CLI decides how many to pass in
            most = top_files
            graph_data = {
                "order": "asc" if ascending else "desc",
                "most_depended": [{"file": f, "dependents": c} for f, c in most],
            }
            print(json.dumps(graph_data, indent=2))
            return

        title = "Dependency Graph — Least Depended Files" if ascending \
            else "Dependency Graph — Most Depended Files"
        print(title)
        print("-" * 60)

        if not top_files:
            print("No dependency relationships found")
            return

        items = top_files if self.full else top_files[: self.limit]
        for i, (file_path, count) in enumerate(items, 1):
            print(f"\n{i:2d}. {file_path}")
            print(f"     Dependents: {count}")

            # For each node's dependents, show a short preview unless full
            dependents_all = sorted(analyzer.dependents.get(file_path, set()))
            if dependents_all:
                if self.full:
                    for dep in dependents_all[:-1]:
                        print(f"     ├── {dep}")
                    print(f"     └── {dependents_all[-1]}")
                else:
                    preview = dependents_all[: min(3, self.limit)]
                    for dep in preview[:-1]:
                        print(f"     ├── {dep}")
                    print(f"     └── {preview[-1]}")
                    if len(dependents_all) > len(preview):
                        print(f"     └── ... and {len(dependents_all) - len(preview)} more")

    # -------- Statistics --------
    def print_statistics(self, analyzer: DependencyAnalyzer, ascending: bool = False) -> None:
        if self.format_type == "json":
            stats = self._get_stats_dict(analyzer, ascending)
            print(json.dumps(stats, indent=2))
            return

        total_files = len(analyzer.files)
        total_deps = sum(len(deps) for deps in analyzer.dependencies.values())
        files_with_deps = sum(1 for deps in analyzer.dependencies.values() if deps)

        print("Dependency Statistics")
        print("-" * 60)
        print(f"Total Python files: {total_files}")
        print(f"Total dependencies: {total_deps}")
        print(f"Files with dependencies: {files_with_deps}")

        top_files = analyzer.get_most_depended_files(
            limit=(len(analyzer.dependents) if self.full else self.limit),
            ascending=ascending
        )
        if top_files:
            header = "Least depended files:" if ascending else "Most depended files:"
            print(f"\n{header}")
            for file_path, count in top_files:
                print(f"  {count:2d} ← {file_path}")

        unimported_all = analyzer.get_unimported_files()
        print(f"\nNot imported by others: {len(unimported_all)}")
        if unimported_all:
            unimported = unimported_all if self.full else unimported_all[: self.limit]
            if unimported:
                for file_path in unimported[:-1]:
                    print(f"     ├── {file_path}")
                print(f"     └── {unimported[-1]}")
            if not self.full and len(unimported_all) > len(unimported):
                print(f"     └── ... and {len(unimported_all) - len(unimported)} more")

    # -------- Since report --------
    def print_since_report(self, since: str, changed: List[str], impacts: Dict[str, Dict]) -> None:
        """
        Pretty output for --since COMMIT report.
        impacts: mapping from changed file -> impact dict (same schema as print_impact_analysis input)
        """
        # Build union
        union_direct, union_indirect = set(), set()
        for result in impacts.values():
            union_direct.update(result.get("direct_dependents", []))
            union_indirect.update(result.get("indirect_dependents", []))

        union_total = len(union_direct | union_indirect)

        if self.format_type == "json":
            payload = {
                "since": since,
                "changed_files": changed,
                "union": {
                    "direct_dependents": sorted(union_direct),
                    "indirect_dependents": sorted(union_indirect),
                    "total_impact": union_total,
                },
                "impacts": impacts
            }
            print(json.dumps(payload, indent=2))
            return

        print(f"Impact Since {since}")
        print("-" * 60)

        # Changed files
        if not changed:
            print("Changed Python files:")
            print("  (none)")
        else:
            items = changed if self.full else changed[: self.limit]
            print("Changed Python files:")
            for f in items[:-1]:
                print(f"  ├── {f}")
            print(f"  └── {items[-1]}")
            if not self.full and len(changed) > len(items):
                print(f"  ... and {len(changed) - len(items)} more")

        print(f"\nUnion impact across changed files:")
        print(f"  Direct dependents:   {len(union_direct)}")
        print(f"  Indirect dependents: {len(union_indirect)}")
        print(f"  Total Impact:        {union_total} files")

        if not impacts:
            print("\nNo impacts could be resolved (not a git repo, bad commit, or files outside path).")
            return

        print("\nPer-file impact (changed → affected):")
        items = sorted(impacts.items(), key=lambda kv: kv[0])
        to_show = items if self.full else items[: self.limit]
        for file, result in to_show:
            total = result.get("total_impact", 0)
            print(f"  • {file}: {total} files")
        if not self.full and len(items) > len(to_show):
            print(f"  ... and {len(items) - len(to_show)} more")

    # -------- Default Brief --------
    def print_brief_stats(self, analyzer: DependencyAnalyzer) -> None:
        total_files = len(analyzer.files)
        total_deps = sum(len(deps) for deps in analyzer.dependencies.values())

        print("impscope — Python Dependency Impact Analyzer")
        print("-" * 60)
        print(f"Analyzed {total_files} Python files")
        print(f"Found {total_deps} dependencies")
        if total_files > 0:
            print("\nUse -h/--help to see all options, including global flags (e.g. --path, --exclude, --format)")
            print("\nCommon subcommands:")
            print("  impscope impact <file>     # Impact analysis")
            print("  impscope unimported        # Files not imported by others")
            print("  impscope stats             # Full statistics")
            print("  impscope graph             # Most/least depended files")
            print("  impscope since <commit>    # Impact since a commit/branch/hash")


    # -------- Helpers --------
    def _get_stats_dict(self, analyzer: DependencyAnalyzer, ascending: bool) -> Dict:
        # JSON stays full by design
        total_files = len(analyzer.files)
        total_deps = sum(len(deps) for deps in analyzer.dependencies.values())
        return {
            "total_files": total_files,
            "total_dependencies": total_deps,
            "order": "asc" if ascending else "desc",
            "most_depended_files": analyzer.get_most_depended_files(
                limit=(len(analyzer.dependents) if self.full else 10),
                ascending=ascending,
            ),
            "unimported_files": analyzer.get_unimported_files(),
        }
