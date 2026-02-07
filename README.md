# jari 砂利 — Task/Issue Tracker for LLM Agents

LMDB-backed task tracker with priorities, dependencies, conflict detection, and niwa integration.

## Install

```bash
# Recommended: installs CLI globally
pipx install jari
# or
uv tool install jari
```

## Quick Start

```bash
jari init
jari create "Fix login bug" -p 1 -t bug --agent claude_1
jari ready
jari claim todo_1 --agent claude_1
jari close todo_1 --reason "Fixed" --agent claude_1
```

## See Also

**[niwa(庭)](https://github.com/secemp9/niwa)** — Collaborative markdown editing for LLM agents. Jari can link todos directly to Niwa node IDs, so you can track tasks alongside the documents they relate to.

```bash
pipx install niwa
```

## Commands

Run `jari help` for the full command reference.
