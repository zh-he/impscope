# impscope — Python Dependency Impact Analyzer

A small, fast tool to analyze Python file dependencies and assess the impact of changes. Pure standard library, no external deps.

[English | [简体中文](README.zh-CN.md)]

## Features

- Impact analysis for a given file (direct & indirect dependents)
- Not-imported files report (files not imported by any other file)
- Dependency graph (most/least depended files, with sorting)
- Codebase statistics (totals)
- Exclude by glob patterns (e.g., `--exclude "tests/*"`)
- Impact since a Git commit (`since <commit>`) — union blast radius of changed files
- Text and JSON output formats
- Source roots support (`--source-root`, `--include-outside-roots`)
- Strict/heuristic import resolution (`--strict-resolution`)
- Fast & lightweight (pure Python, AST-based)
- Python 3.7+

## Installation

```bash
pip install impscope
```

Or install from source:

```bash
git clone https://github.com/zh-he/impscope.git
cd impscope
pip install -e .
```

## Quick Start

```bash
# Show dependency statistics (brief overview)
impscope stats

# Check the impact of changing a specific file
impscope impact models.py

# List files that are not imported by any other file
impscope unimported

# Show dependency graph (descending by default)
impscope graph

# Show least depended files
impscope graph --sort asc

# Analyze a specific directory and exclude tests/migrations
impscope stats --path src/ --exclude "tests/*" --exclude "*/migrations/*"

# Impact of files changed since last commit (Git required)
impscope since HEAD

# JSON output (great for CI)
impscope since main --format json
```

Tip: you can also run it as a module:

```bash
python -m impscope --help
```

## Usage

```text
impscope <command> [OPTIONS]

Commands:
  impact FILE           Analyze the impact of changing a specific file
  unimported            List files that are not imported by any other file
  graph                 Show dependency graph (top most/least depended files)
  stats                 Show comprehensive dependency statistics
  since COMMIT          Analyze union impact of Python files changed since COMMIT
                        (e.g., HEAD~1, <hash>, <branch>)

Global options:
  --path PATH                 Root path to analyze (default: current directory)
  --exclude GLOB              Glob pattern to exclude (repeatable)
                              e.g., --exclude "tests/*" --exclude "*/migrations/*"
  --format {text,json}        Output format (default: text)
  --full                      Do not truncate long lists in text output
  --limit N                   Max items per list in text output when not using --full (default: 10)
  --source-root DIR           Treat DIR (relative to --path) as an import root (repeatable)
  --include-outside-roots     When --source-root is provided, also include files outside those roots
  --strict-resolution         Only resolve imports that exactly match indexed modules
                              (no parent-package fallback)
  --version                   Show version information
  --help                      Show help message
```


## How It Works

`impscope` uses Python’s AST to:

1. Parse all Python files in your project
2. Extract `import` and `from ... import ...` statements (including relative imports)
3. Map files to modules (packages via `__init__.py`)
4. Build a dependency graph
5. Compute direct & indirect dependents (impact) via BFS

It handles:

- Regular imports (`import module`)
- From imports (`from module import name`)
- Relative imports (`from .module import name`, `from .. import x`)
- Packages and `__init__.py`
- Circular dependencies (no infinite recursion)
- Ignored directories: `.git`, `.venv`, `__pycache__`, `node_modules`, `dist`, `build`, etc.

### Excludes

- `--exclude` patterns are matched against relative paths (POSIX style), e.g. `src/app/models.py`.
- You can repeat `--exclude` multiple times:
  ```bash
  impscope stats --exclude "tests/*" --exclude "*/migrations/*"
  ```

### Source roots

- Use `--source-root` to treat one or more directories as import roots (relative to `--path`):
  ```bash
  impscope stats --path . --source-root src --source-root python
  ```
- With `--include-outside-roots`, files outside these roots are also scanned (module names computed relative to the project root).

### Since <commit>

- Requires Git to be available, and the path to be inside a Git repo.
- Uses `git diff --name-only --diff-filter=ACMR <commit>..HEAD` to collect changed `.py` files,
  then computes the union of direct/indirect dependents across those files.
- When `--path` points to a subdirectory, only changes within that directory tree are considered for display and impact.
- `--exclude` patterns also apply to the changed file list for consistent reporting.

## Import resolution notes (re: `from u import x` without dot)

- In Python 3, absolute imports are the default.
  Writing `from u import x` is treated as importing top-level module `u` on `sys.path`, not `pkg.u`.
- `impscope` follows this rule:
  - It resolves `from u import x` only if there is a module/package named `u` inside the analyzed root (`--path`).
  - If `u` actually lives under a package like `pkg/u.py` and there is no top-level `u`, `impscope` will not infer `pkg.u` from `from u import x`.
- Heuristic fallback (non-strict mode):
  - For `import pkg.sub.mod` it can fall back to the nearest existing parent (`pkg.sub`, then `pkg`).
  - For `from pkg import *`, it may map to `pkg` (or its nearest existing parent).
- Recommendations:
  - Within a package, prefer explicit relative imports: `from .u import x`.
  - Or use fully qualified absolute imports from your package root: `from pkg.u import x`.
  - Run `impscope` from the repository/package root so absolute imports can be mapped.

> Note: The “least depended files” view in `graph --sort asc` ranks files that have at least one dependent. Files with zero dependents are listed by the `unimported` command.

## Requirements

- Python 3.7+
- No external dependencies (standard library only)

## Contributing

Contributions are welcome! Please open an issue or pull request.

## License

MIT License
