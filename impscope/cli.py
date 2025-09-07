"""
Command-line interface for impscope
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import DependencyAnalyzer, get_changed_python_files
from .formatter import ImpactFormatter


def create_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="impscope",
        description="Python Dependency Impact Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  impscope impact models.py                   # Analyze impact of changing models.py
  impscope unimported                         # List files not imported by others
  impscope graph                              # Show dependency graph (top most depended files)
  impscope stats                              # Show dependency statistics
  impscope stats --sort asc                   # Stats sorted ascending
  impscope since HEAD~1                       # Impact of files changed since a commit
  impscope --path . --source-root src impact foo.py
  impscope --exclude "tests/*" --exclude "*.pyi" stats
  impscope --format json impact models.py     # Machine-readable output
  impscope --full --limit 50 graph            # Do not truncate lists; show more items in text
        """
    )

    # Global options (must appear before the subcommand)
    parser.add_argument(
        "--path",
        default=".",
        help="Root path to analyze (default: current directory)"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help='Glob patterns to exclude (repeatable). Example: --exclude "tests/*"'
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text or json (default: text)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Do not truncate long lists in text output (JSON is always full)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max items to show per list in text output when not using --full (default: 10)"
    )
    parser.add_argument(
        "--source-root",
        dest="source_roots",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Directory treated as an import root (relative to --path). Repeatable. "
            "Example: --source-root src --source-root python"
        )
    )
    parser.add_argument(
        "--include-outside-roots",
        action="store_true",
        help="When --source-root is provided, also include Python files outside those roots"
    )
    parser.add_argument(
        "--strict-resolution",
        action="store_true",
        help=(
            "Only resolve imports that exactly match indexed modules "
            "(no parent-package fallback)"
        )
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"impscope {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # impact
    sp_impact = subparsers.add_parser(
        "impact",
        help="Analyze the impact of changing a specific file",
        description="Analyze the impact of changing a specific file"
    )
    sp_impact.add_argument(
        "file",
        metavar="FILE",
        help="Path to the Python file to analyze (relative to --path or absolute)"
    )

    # unimported
    subparsers.add_parser(
        "unimported",
        help="List files that are not imported by any other file",
        description="List files that are not imported by any other file"
    )

    # graph
    sp_graph = subparsers.add_parser(
        "graph",
        help="Show dependency graph (top most depended files)",
        description="Show dependency graph (top most depended files)"
    )

    sp_graph.add_argument(
        "--sort",
        choices=["asc", "desc"],
        default="desc",
        help="Sort order for ranked list (default: desc)"
    )

    # stats
    sp_stats = subparsers.add_parser(
        "stats",
        help="Show comprehensive dependency statistics",
        description="Show comprehensive dependency statistics"
    )
    sp_stats.add_argument(
        "--sort",
        choices=["asc", "desc"],
        default="desc",
        help="Sort order for ranked list (default: desc)"
    )

    # since
    sp_since = subparsers.add_parser(
        "since",
        help="Analyze union impact of files changed since a commit",
        description="Analyze union impact of Python files changed since a commit/branch/hash"
    )
    sp_since.add_argument(
        "commit",
        metavar="COMMIT",
        help="Commit-ish to compare against (e.g., HEAD~1, <hash>, <branch>)",
    )

    return parser


def make_analyzer(args: argparse.Namespace) -> tuple[DependencyAnalyzer, ImpactFormatter, Path]:
    """Initialize analyzer and formatter from global args."""
    root = Path(args.path)
    if not root.exists():
        print(f"Error: Path '{args.path}' does not exist")
        sys.exit(1)

    analyzer = DependencyAnalyzer(
        str(root),
        strict_resolution=args.strict_resolution,
        source_roots=args.source_roots or None,
        include_outside_roots=args.include_outside_roots
    )
    formatter = ImpactFormatter(
        format_type=args.format,
        full=args.full,
        limit=args.limit
    )
    return analyzer, formatter, root


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    analyzer, formatter, root = make_analyzer(args)

    try:
        analyzer.scan_directory(exclude_globs=args.exclude)

        if not analyzer.files:
            print("No Python files found in the specified directory")
            sys.exit(1)

        if args.command == "impact":
            result = analyzer.get_impact_analysis(args.file)
            formatter.print_impact_analysis(result)
            return

        if args.command == "unimported":
            unimported_files = analyzer.get_unimported_files()
            formatter.print_unimported_files(unimported_files)
            return

        if args.command == "graph":
            ascending = args.sort == "asc"
            # For text mode, let --full/--limit influence how many we fetch.
            graph_limit = len(analyzer.dependents) if args.full else max(args.limit, 10)
            top_files = analyzer.get_most_depended_files(
                limit=graph_limit,
                ascending=ascending
            )
            formatter.print_dependency_graph(top_files, analyzer, ascending=ascending)
            return

        if args.command == "stats":
            ascending = args.sort == "asc"
            formatter.print_statistics(analyzer, ascending=ascending)
            return

        if args.command == "since":
            changed = get_changed_python_files(
                repo_root=root,
                since_commit=args.commit,
                exclude_globs=args.exclude
            )
            impacts: dict[str, dict] = {}
            for rel in changed:
                result = analyzer.get_impact_analysis(rel)
                if "error" not in result:
                    impacts[rel] = result
            formatter.print_since_report(args.commit, changed, impacts)
            return

        formatter.print_brief_stats(analyzer)

    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors to user
        print(f"Error during analysis: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()