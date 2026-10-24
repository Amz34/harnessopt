# harnessopt

![harnessopt overview](assets/harnessopt-overview.jpg)

[![CI](https://github.com/Amz34/harnessopt/actions/workflows/ci.yml/badge.svg)](https://github.com/Amz34/harnessopt/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`harnessopt` is a dependency-free Python CLI that audits and compacts AI coding-agent harness configurations (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `SKILL.md`, `MEMORY.md`, and `.mcp.json`), measuring always-loaded context token overhead and flagging security or duplication defects before every session.

## Why It Exists

Modern coding agents load instruction files, skill definitions, persistent memory notes, and Model Context Protocol (MCP) server schemas into the prompt window on every turn. As a project evolves, duplicate rules accumulate across files, stale file references drift out of sync, and MCP configs quietly accumulate unpinned package runners or literal credentials. `harnessopt` makes the harness layer measurable and deterministic with zero third-party packages.

## Quickstart

Requires Python 3.11+ (standard library only).

```bash
git clone https://github.com/Amz34/harnessopt.git
cd harnessopt

# Run the test suite
make test

# Audit a workspace directory (human-readable or JSON)
python3 -m harnessopt audit /path/to/workspace
python3 -m harnessopt audit /path/to/workspace --json --fail-on high

# Preview or apply non-destructive markdown compaction
python3 -m harnessopt compact /path/to/workspace --dry-run
python3 -m harnessopt compact /path/to/workspace
```

## Features

- **Layer-Aware Token Budgeting**: Classifies workspace artefacts into `instructions`, `skill`, `memory`, and `mcp` layers and reports per-file and per-layer token estimates.
- **MCP Security Checks**:
  - `inline_secret_in_env`: Flags literal API keys or tokens embedded inside MCP `env` blocks instead of `${VAR}` references.
  - `unrestricted_shell_server`: Flags MCP servers invoking raw shells (`bash -c`, `sh -c`, `cmd /c`) without a wrapper boundary.
  - `unpinned_mcp_package`: Flags `npx` / `uvx` / `bunx` MCP servers launched without an explicit `@version` pin.
  - `root_filesystem_scope`: Flags `/` root directory grants in MCP server arguments.
- **Instruction & Memory Hygiene**:
  - `duplicate_directive`: Detects identical bullet directives repeated across instruction, skill, and memory files.
  - `dead_path_reference`: Verifies that local relative paths (`./path/to/file.ext`) cited in harness rules actually exist in the workspace.
  - `oversized_harness_file` & `context_budget_exceeded`: Enforces configurable per-file (`--max-file-tokens`) and workspace (`--budget`) token ceilings.
- **Safe Markdown Compaction**: Strips decorative HTML comments (while preserving `<!-- claim-policy: ... -->` governance tags and fenced code blocks), collapses excessive blank lines, and removes duplicate bullet directives in place.

## How It Works

1. `harnessopt.scanner` walks the target workspace (skipping `.git`, `.venv`, `node_modules`, and build directories), classifies harness files by filename and path conventions, extracts markdown headings and normalized directive bullets outside fenced code blocks, and parses MCP JSON server definitions.
2. `harnessopt.auditor` evaluates each artefact against security, hygiene, and token-budget rules, deducting weighted severity penalties (`HIGH` = 20, `MEDIUM` = 8, `LOW` = 3) to produce a `0..100` readiness score.
3. `harnessopt.optimizer` splits markdown files around fenced code blocks so code samples remain untouched while redundant prose comments, blank-line runs, and repeated bullet rules are compacted deterministically.

## Limitations

- Token counts use a fast deterministic character/word heuristic (~4 characters per token) rather than a model-specific BPE tokenizer, keeping the tool completely free of native or third-party dependencies.
- Dead-path checks only inspect explicit relative backtick paths (`./...`) so illustrative snippets and URLs are not misclassified as broken files.

## License

MIT License — see [LICENSE](LICENSE).
