# impscope — Python 依赖影响分析器

一个小而快的工具，用于分析 Python 文件间的依赖关系，并评估改动带来的影响范围。纯标准库实现，无外部依赖。

[[English](README.md)|简体中文]

## 特性

- 指定文件的影响分析（直接 & 间接依赖者）
- 未被其它文件导入的文件报告
- 依赖图（最多/最少被依赖文件，可指定排序）
- 代码库统计（总量与均值）
- 支持按通配符排除文件/目录（`--exclude "tests/*"` 等）
- 基于 Git 的改动影响（`--since <commit>`）：统计本次改动的“联合波及面”
- 支持文本与 JSON 输出
- 纯 Python，AST 解析，速度快
- 支持 Python 3.7+

## 安装

```bash
pip install impscope
```

或从源码安装：

```bash
git clone https://github.com/zh-he/impscope.git
cd impscope
pip install -e .
```

## 快速开始

```bash
# 分析当前目录（简要统计）
impscope

# 查看修改某个文件的影响范围
impscope --impact models.py

# 列出没有被其它文件导入的文件
impscope --unimported

# 展示依赖统计（默认按被依赖数降序）
impscope --stats

# 展示“最少被依赖”的文件
impscope --graph --sort asc

# 指定路径并排除测试/迁移等目录
impscope --path src/ --stats --exclude "tests/*" --exclude "*/migrations/*"

# 基于 Git 的增量影响（上一次提交以来改动的 .py 文件）
impscope --since HEAD

# 输出 JSON（便于 CI 使用）
impscope --since main --format json
```

提示：也可以以模块形式运行：

```bash
python -m impscope --help
```


## 命令行选项

```text
impscope [OPTIONS]

Options:
  --impact FILE          Analyze the impact of changing a specific file
  --unimported           List files that are not imported by any other file
                         (aliases: --not-imported, --unused)
  --graph                Show dependency graph (top most/least depended files)
  --stats                Show comprehensive dependency statistics
  --since COMMIT         Analyze the union impact of Python files changed
                         since COMMIT (e.g., HEAD~1, <hash>, <branch>)
  --path PATH            Root path to analyze (default: current directory)
  --exclude GLOB         Glob pattern to exclude (repeatable)
                         e.g., --exclude "tests/*" --exclude "*/migrations/*"
  --format FORMAT        Output format: text or json (default: text)
  --sort {asc,desc}      Sort order for ranked lists in --stats/--graph
                         (default: desc)
  --version              Show version information
  --help                 Show help message
```

## 工作原理

`impscope` 使用 Python AST 来：

1. 解析项目中的全部 `.py` 文件
2. 提取 `import` 与 `from ... import ...`（含相对导入）
3. 将文件映射为模块（包通过 `__init__.py` 识别）
4. 构建依赖图（文件 → 其依赖的文件）
5. 使用 BFS 计算直接/间接“被依赖者”（影响范围）

支持：

- 绝对导入（`import module`）
- from 导入（`from module import name`）
- 相对导入（`from .module import name`, `from .. import x`）
- 包与 `__init__.py`
- 循环依赖（不会陷入死循环）
- 默认忽略目录：`.git`、`.venv`、`__pycache__`、`node_modules`、`dist`、`build` 等

### `--exclude` 规则

- 模式匹配的是**相对路径（POSIX 风格）**，如 `src/app/models.py`。
- 可多次传入：
  ```bash
  impscope --stats --exclude "tests/*" --exclude "*/migrations/*"
  ```

- Source roots

  - 使用 `--source-root` 将一个或多个目录视为“导入根”（相对于 `--path`）：

  ```
  impscope stats --path . --source-root src --source-root python
  ```

  - 若加上 `--include-outside-roots`，会**同时**扫描根之外的 Python 文件（这些文件的模块名按项目根计算）。

  ### Since <commit>

  - 需要系统安装 Git，且 `--path` 位于 Git 仓库内。
  - 使用 `git diff --name-only --diff-filter=ACMR <commit>..HEAD -- '*.py'` 收集改动的 `.py` 文件，随后计算这些文件影响范围的**并集**（直接/间接被依赖者）。
  - 当 `--path` 指向子目录时，仅统计并展示该子树内的改动与影响。
  - `--exclude` 也会应用到“改动文件列表”，口径一致。

  ### Import 解析说明（关于没有点号的 `from u import x`）

  - 在 Python 3 中，**绝对导入**是默认语义。`from u import x` 会按 `sys.path` 的顶层模块去解析 `u`，而不是 `pkg.u`。
  - `impscope` 遵循该规则：
    - 只有当被分析路径内**存在顶层模块/包 `u`** 时，`from u import x` 才会被解析；
    - 若真实结构是 `pkg/u.py` 且不存在顶层 `u`，`impscope` 不会把 `from u import x` 推断为 `from pkg.u import x`。
  - 非严格模式（启发式）回退：
    - 对 `import pkg.sub.mod` 可回退到最近存在的父级（`pkg.sub`、`pkg`）；
    - 对 `from pkg import *`，可能映射到 `pkg`（或其最近存在的父级）。
  - 推荐做法：
    - 在包内使用**显式相对导入**：`from .u import x`；
    - 或使用从包根开始的**全限定绝对导入**：`from pkg.u import x`；
    - 从仓库/包根运行 `impscope`，以便映射绝对导入。

  > 注：`graph --sort asc` 的“最少被依赖文件”只会对**至少有 1 个被依赖者**的文件进行排序；完全**零被依赖**的文件由 `unimported` 命令列出。

## 要求

- Python 3.7+

- 无外部依赖（仅标准库）

## 贡献

欢迎提 Issue 或 PR，一起把工具打磨得更好。

## 许可协议

MIT License
