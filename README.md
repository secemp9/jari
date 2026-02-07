# jari(砂利)

**Task/issue tracker for LLM agent workflows**

```bash
# Recommended: installs CLI globally
pipx install jari
# or
uv tool install jari
```

Jari (砂利, "gravel") is a CLI task tracker built for multi-agent AI workflows. It handles priorities, dependencies, atomic claims, field-level conflict detection, and integrates with [niwa(庭)](https://github.com/secemp9/niwa) for linking todos to markdown document sections.

Built on LMDB for high-performance concurrent access, with the same storage patterns as niwa.

## Features

- **Ready Queue**: Automatically surfaces unblocked todos sorted by priority
- **Atomic Claim**: Race-safe task assignment — first agent wins
- **Dependencies**: Blocked-by relationships with cycle detection
- **Conflict Detection**: Field-level tracking detects when agents update the same fields
- **Auto-Merge**: Non-overlapping field changes merge automatically
- **Priorities**: 5 levels (critical, high, medium, low, backlog)
- **Labels**: Tag todos for filtering and search
- **Niwa Integration**: Link todos to niwa node IDs (h1_0, h2_3, etc.)
- **Epic/Subtask**: Parent-child relationships for organizing work
- **Version History**: Full audit trail of every change
- **Search**: Full-text search across titles, descriptions, and labels
- **LLM-Friendly**: Structured error messages and workflow context injection
- **Claude Code Integration**: Hooks for session start, compaction, and stop

## Installation

```bash
# Recommended: install as global CLI tool
pipx install jari
# or with uv
uv tool install jari

# Or from source
git clone https://github.com/secemp9/jari
cd jari
pip install .

# For development (editable install)
pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Initialize database
jari init

# 2. Create some todos
jari create "Design auth system" -p 0 -t feature --agent lead
jari create "Implement login" -p 1 -t task --agent lead
jari create "Write tests" -p 1 -t task --agent lead

# 3. Set up dependencies
jari dep add todo_2 todo_1    # Implement blocked by Design
jari dep add todo_3 todo_2    # Tests blocked by Implement

# 4. Check what's ready
jari ready

# 5. Claim and work
jari claim todo_1 --agent claude_1
jari close todo_1 --reason "Design complete" --agent claude_1

# 6. Next task is now unblocked
jari ready
```

## Commands

### Setup
| Command | Description |
|---------|-------------|
| `init` | Initialize a new database |
| `setup claude` | Set up Claude Code hooks integration |
| `setup claude --remove` | Remove Claude Code hooks |

### Create & View
| Command | Description |
|---------|-------------|
| `create "Title" [-p 0-4] [-t type] [-d "desc"] [--agent name]` | Create a new todo |
| `show <id>` | View todo details |
| `list [--status X] [--priority N] [--assignee X] [--type X] [--label X]` | List todos with filters |
| `search <query>` | Full-text search |

### Workflow
| Command | Description |
|---------|-------------|
| `ready` | Show ready queue (no active blockers, sorted by priority) |
| `claim <id> --agent <name>` | Atomic claim: assign + set in_progress |
| `blocked` | Show all blocked todos with blocker info |
| `update <id> [--status X] [--priority N] [--title X] [--assign X] [--agent name]` | Update a todo |
| `close <id> [--reason "done"] [--agent name]` | Close a todo |
| `reopen <id> [--agent name]` | Reopen a closed todo |
| `delete <id> [--agent name]` | Delete a todo |

### Dependencies
| Command | Description |
|---------|-------------|
| `dep add <child> <parent>` | Add dependency (child blocked by parent, cycle-checked) |
| `dep remove <child> <parent>` | Remove dependency |
| `dep tree <id>` | Show dependency tree |

### Labels
| Command | Description |
|---------|-------------|
| `label add <id> <label>` | Add label to todo |
| `label remove <id> <label>` | Remove label from todo |

### Niwa Integration
| Command | Description |
|---------|-------------|
| `link <todo_id> <niwa_node_id>` | Link todo to niwa node |
| `unlink <todo_id> <niwa_node_id>` | Unlink from niwa node |
| `linked <niwa_node_id>` | Show todos linked to a niwa node |

### Agent Status
| Command | Description |
|---------|-------------|
| `status --agent <name>` | Check assigned todos, conflicts, recent edits |
| `status` | Overall database stats |
| `conflicts --agent <name>` | List unresolved conflicts |
| `agents` | List all agents who've used this DB |

### History & Output
| Command | Description |
|---------|-------------|
| `history <id>` | View version history |
| `export [--output file.jsonl]` | Export all todos as JSONL |
| `prime` | Output workflow context for LLM injection |
| `help [command]` | Show help |

## Multi-Agent Workflow

```
Agent A: creates todos              Agent B: checks ready queue
    │                                     │
    ▼                                     ▼
Agent A: sets dependencies           Agent B: claims todo_1
    │                                     │
    ▼                                     ▼
Agent A: claims todo_3               Agent B: closes todo_1
    │                                     │
    ▼                                     ▼
BLOCKED (todo_3 blocked by todo_1)   SUCCESS → todo_2 now unblocked!
    │
    ▼
Agent A: checks ready queue → todo_3 now ready!
```

## Conflict Detection

Jari uses field-level conflict detection. When two agents read the same todo version and both try to update:

- **Different fields** → auto-merged silently (e.g., one changes priority, other changes title)
- **Same field** → conflict stored for resolution

```bash
# Agent 1 updates priority
jari update todo_1 -p 0 --agent agent_1

# Agent 2 tries to update priority too → CONFLICT
jari update todo_1 -p 1 --agent agent_2

# Resolve the conflict
jari resolve todo_1 ACCEPT_YOURS --agent agent_2
jari resolve todo_1 ACCEPT_THEIRS --agent agent_2
jari resolve todo_1 MANUAL_MERGE status=open priority=1 --agent agent_2
```

## Ready Queue

The ready queue shows todos that are actionable — open or in_progress, with no active (non-closed) blockers:

```bash
jari ready
# Output: sorted by priority (critical first), then by age

# Claim atomically (fails if another agent already claimed)
jari claim todo_1 --agent my_agent
```

## Dependencies

Dependencies are blocked-by relationships with automatic cycle detection:

```bash
# todo_2 can't start until todo_1 is closed
jari dep add todo_2 todo_1

# Diamond dependency: D blocked by both B and C
jari dep add todo_4 todo_2
jari dep add todo_4 todo_3

# View the dependency tree
jari dep tree todo_4

# Cycle detection prevents: A→B→C→A
jari dep add todo_1 todo_3    # Error: Cycle detected!
```

## Complex Content

For descriptions with quotes, newlines, or special characters, use `--file` or `--stdin`:

```bash
# Create with description from file
jari create "Task" --file description.md --agent me

# Update description from file
jari update todo_1 --file new_desc.md --agent me

# Create with piped input
echo "Detailed description" | jari create "Task" --stdin --agent me
```

## Niwa Integration

Link todos to [niwa](https://github.com/secemp9/niwa) document nodes:

```bash
# Link a todo to a niwa section
jari link todo_1 h2_3

# See all todos for a niwa node
jari linked h2_3

# Create with niwa reference
jari create "Update auth docs" --niwa-ref h2_5 --agent me
```

## Todo IDs

Todos follow the pattern `todo_{index}`:

```
[todo_1] critical  "Design auth system"  (open, assigned: lead)
[todo_2] high      "Implement login"     (blocked by todo_1)
[todo_3] high      "Write tests"         (blocked by todo_2)
[todo_4] medium    "Update docs"         (open)
```

Use `list` to see all todos, `ready` for actionable ones, or `search` to find by content.

## Claude Code Integration

Jari integrates with Claude Code via hooks for automatic context awareness:

```bash
# Set up Claude Code hooks
jari setup claude

# Remove hooks later
jari setup claude --remove
```

### What the hooks do

| Hook | Trigger | Action |
|------|---------|--------|
| **SessionStart** | Session begins | Injects Jari usage guide + current status |
| **PreCompact** | Before `/compact` | Preserves Jari context after compaction |
| **Stop** | Session ending | Reminds about open todos |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Jari CLI                              │
├─────────────────────────────────────────────────────────────┤
│  Task Model                                                  │
│  ├── Todos (title, status, priority, type, assignee)         │
│  ├── Dependencies (blocked_by/blocks with cycle detection)   │
│  ├── Versions (each update increments version)               │
│  ├── Agents (track who created/edited/claimed what)          │
│  ├── Labels (arbitrary tags for filtering)                   │
│  └── Conflicts (field-level, stored for resolution)          │
├─────────────────────────────────────────────────────────────┤
│  Storage (LMDB)                                              │
│  ├── todos_db     - Todo records                             │
│  ├── history_db   - Version snapshots                        │
│  ├── pending_db   - Pending reads by agent                   │
│  └── meta_db      - Conflicts and metadata                   │
├─────────────────────────────────────────────────────────────┤
│  Claude Code Hooks                                           │
│  └── SessionStart, PreCompact, Stop                          │
└─────────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- **Field-level conflict detection**: Compares each field independently — auto-merges when changes don't overlap, conflicts when they do
- **LMDB storage**: Memory-mapped for fast concurrent access, ACID transactions
- **Atomic claim**: Single write transaction for race-safe task assignment
- **DFS cycle detection**: Prevents circular dependencies before they're added
- **Agent isolation**: Each agent's pending reads and conflicts are tracked separately

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=jari --cov-report=html
```

145 tests covering:
- CRUD operations (create, show, list, update, close, reopen, delete)
- Ready queue (priority sorting, blocker exclusion, cascading unblock)
- Atomic claim (success, race condition, closed/deferred rejection)
- Dependencies (add, remove, chains, diamonds, cycle detection)
- Field-level conflict detection (same field, different fields, auto-merge)
- Conflict resolution (ACCEPT_YOURS, ACCEPT_THEIRS, MANUAL_MERGE)
- Labels (add, remove, filter, search)
- Niwa integration (link, unlink, query)
- Epic/parent-child relationships
- Full lifecycle workflows
- Edge cases and error handling

## See Also

**[niwa(庭)](https://github.com/secemp9/niwa)** — Collaborative markdown editing for LLM agents. Jari can link todos directly to Niwa node IDs, so you can track tasks alongside the documents they relate to.

```bash
pipx install niwa
```

## Name

Jari (砂利) means "gravel" in Japanese. In a zen garden (庭, niwa), gravel is raked into deliberate patterns. Jari helps organize your tasks with the same deliberate structure — priorities, dependencies, and conflict-aware collaboration across multiple agents.

## License

MIT
