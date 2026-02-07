"""jari.core - Claude hooks, prime output, error messages, system prompt."""

import json
from pathlib import Path
from typing import Optional, Tuple
import sys

from .jari import JariDB


def generate_claude_hooks_config() -> dict:
    """Generate Claude Code hooks configuration for jari integration."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "jari hook --hook-event SessionStart",
                            "timeout": 5
                        }
                    ]
                }
            ],
            "PreCompact": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "jari hook --hook-event PreCompact",
                            "timeout": 5
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "jari hook --hook-event Stop",
                            "timeout": 5
                        }
                    ]
                }
            ],
        }
    }


def get_jari_usage_guide() -> str:
    """Generate a concise usage guide for Claude to remember after compaction."""
    return """[Jari 砂利 - Task/Issue Tracker for LLM Agents]

This project uses Jari for task/issue tracking with conflict detection.

QUICK REFERENCE (prefix all with 'jari'):
  jari create "Title" [-p 0-4] [-t task|bug|feature|epic] --agent <name>
  jari list [--status X] [--priority N] [--assignee X]
  jari show <id>                            # View details
  jari update <id> --status X --agent <name>  # Update fields
  jari close <id> --reason "text" --agent <name>
  jari ready                                # Ready queue (no blockers)
  jari claim <id> --agent <name>            # Atomic claim
  jari blocked                              # Show blocked todos
  jari dep add <child> <parent>             # Add dependency
  jari dep tree <id>                        # Dependency tree
  jari search <query>                       # Full-text search
  jari status --agent <name>                # Agent status
  jari prime                                # Workflow context for LLM

PRIORITIES: 0=critical, 1=high, 2=medium, 3=low, 4=backlog
STATUSES: open | in_progress | blocked | closed | deferred

WORKFLOW:
  1. `jari ready` to see what to work on
  2. `jari claim <id> --agent <name>` to claim a todo
  3. Work on it, then `jari close <id> --agent <name>`
  4. `jari ready` for next task

IMPORTANT:
  - Always use --agent with a unique name
  - Use `jari ready` to find unblocked, priority-sorted work
  - Dependencies: `jari dep add child parent` (child blocked by parent)"""


def handle_hook_event(event_name: str, hook_input: Optional[dict] = None) -> int:
    """Handle a Claude Code hook event. Returns exit code."""
    if hook_input is None:
        try:
            hook_input = json.load(sys.stdin)
        except (json.JSONDecodeError, EOFError):
            hook_input = {}

    db_exists = Path(".jari/data.lmdb").exists()

    if event_name == "SessionStart":
        usage_guide = get_jari_usage_guide()

        if db_exists:
            try:
                db = JariDB()
                stats = db.get_db_stats()
                db.close()

                status_info = (
                    f"\n\n[Jari Status] {stats['total']} todos"
                )
                by_status = ', '.join(f"{k}={v}" for k, v in stats['by_status'].items())
                if by_status:
                    status_info += f" ({by_status})"
                if stats['pending_conflicts'] > 0:
                    status_info += f"\n⚠️  {stats['pending_conflicts']} pending conflict(s)"

                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": usage_guide + status_info
                    }
                }
                print(json.dumps(output))
            except Exception as e:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": usage_guide + f"\n\n[Jari Status] Could not check: {e}"
                    }
                }
                print(json.dumps(output))
        else:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": usage_guide + "\n\n[Jari Status] No database. Run `jari init` to start."
                }
            }
            print(json.dumps(output))
        return 0

    elif event_name == "PreCompact":
        usage_guide = get_jari_usage_guide()
        status_info = ""

        if db_exists:
            try:
                db = JariDB()
                stats = db.get_db_stats()
                db.close()
                by_status = ', '.join(f"{k}={v}" for k, v in stats['by_status'].items())
                status_info = f"\n\n[Jari Status at Compaction] {stats['total']} todos ({by_status})"
            except Exception:
                status_info = "\n\n[Jari Status] Database exists but could not check."

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": (
                    "[PRESERVING JARI CONTEXT FOR POST-COMPACTION]\n\n"
                    + usage_guide
                    + status_info
                )
            }
        }
        print(json.dumps(output))
        return 0

    elif event_name == "Stop":
        if not db_exists:
            return 0

        try:
            db = JariDB()
            stats = db.get_db_stats()
            db.close()

            open_count = stats['by_status'].get('open', 0) + stats['by_status'].get('in_progress', 0)
            if open_count > 0 or stats['pending_conflicts'] > 0:
                parts = []
                if open_count > 0:
                    parts.append(f"{open_count} open/in-progress todo(s)")
                if stats['pending_conflicts'] > 0:
                    parts.append(f"{stats['pending_conflicts']} conflict(s)")

                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "Stop",
                        "additionalContext": f"[Jari Reminder] {', '.join(parts)}. Run `jari ready` or `jari status --agent <name>`."
                    }
                }
                print(json.dumps(output))
        except Exception:
            pass

        return 0

    return 0


def generate_prime_output(db: JariDB) -> str:
    """Generate ~500-1000 tokens of workflow context for LLM injection."""
    stats = db.get_db_stats()
    ready = db.get_ready_queue()
    blocked = db.get_blocked_todos()

    output = []
    output.append("[Jari 砂利 - Task Tracker Context]")
    output.append("")

    # Stats
    by_status = ', '.join(f"{k}={v}" for k, v in sorted(stats['by_status'].items()))
    output.append(f"DATABASE: {stats['total']} todos ({by_status})")
    if stats['pending_conflicts'] > 0:
        output.append(f"⚠️  CONFLICTS: {stats['pending_conflicts']} pending")
    output.append("")

    # Ready queue
    if ready:
        output.append(f"READY QUEUE ({len(ready)} items, priority-sorted):")
        for todo in ready[:10]:
            pname = db.PRIORITY_NAMES.get(todo['priority'], '?')
            assignee = f" @{todo['assignee']}" if todo.get('assignee') else ""
            labels = f" [{','.join(todo['labels'])}]" if todo.get('labels') else ""
            output.append(f"  [{todo['id']}] {pname}: {todo['title'][:50]}{assignee}{labels}")
        if len(ready) > 10:
            output.append(f"  ... and {len(ready) - 10} more")
        output.append("")

    # Blocked
    if blocked:
        output.append(f"BLOCKED ({len(blocked)} items):")
        for todo in blocked[:5]:
            blockers = [b['id'] for b in todo.get('active_blockers', [])]
            output.append(f"  [{todo['id']}] {todo['title'][:40]} <- blocked by {', '.join(blockers)}")
        output.append("")

    # Quick reference
    output.append("COMMANDS: create, list, show, update, close, ready, claim, dep, search, status")
    output.append("WORKFLOW: ready -> claim -> work -> close -> ready")

    return '\n'.join(output)


def setup_claude_hooks(project_dir: str, remove: bool = False) -> Tuple[bool, str]:
    """Set up or remove Claude Code hooks configuration."""
    claude_dir = Path(project_dir) / ".claude"
    settings_file = claude_dir / "settings.json"

    if remove:
        if not settings_file.exists():
            return True, "No Claude Code settings found - nothing to remove."

        try:
            with open(settings_file, 'r') as f:
                config = json.load(f)
        except json.JSONDecodeError:
            return False, f"Could not parse {settings_file}"

        if 'hooks' in config:
            hooks = config.get('hooks', {})
            our_hooks = False
            for event_hooks in hooks.values():
                for matcher_config in event_hooks:
                    for hook in matcher_config.get('hooks', []):
                        cmd = hook.get('command', '')
                        if 'jari hook' in cmd or 'jari.cli hook' in cmd:
                            our_hooks = True
                            break

            if our_hooks:
                del config['hooks']
                if config:
                    with open(settings_file, 'w') as f:
                        json.dump(config, f, indent=2)
                    return True, f"Removed jari hooks from {settings_file}"
                else:
                    settings_file.unlink()
                    if not any(claude_dir.iterdir()):
                        claude_dir.rmdir()
                    return True, f"Removed {settings_file}"
            else:
                return True, "No jari hooks found - nothing to remove."
        else:
            return True, "No hooks in settings - nothing to remove."

    # Setup hooks
    hooks_config = generate_claude_hooks_config()

    claude_dir.mkdir(exist_ok=True)

    if settings_file.exists():
        try:
            with open(settings_file, 'r') as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            existing = {}

        if 'hooks' in existing:
            for event, event_hooks in hooks_config['hooks'].items():
                if event in existing['hooks']:
                    existing_commands = []
                    for matcher_config in existing['hooks'][event]:
                        for hook in matcher_config.get('hooks', []):
                            existing_commands.append(hook.get('command', ''))
                    for new_matcher_config in event_hooks:
                        for hook in new_matcher_config.get('hooks', []):
                            if hook.get('command', '') not in existing_commands:
                                existing['hooks'][event].append(new_matcher_config)
                else:
                    existing['hooks'][event] = event_hooks
        else:
            existing['hooks'] = hooks_config['hooks']
        config = existing
    else:
        config = hooks_config

    with open(settings_file, 'w') as f:
        json.dump(config, f, indent=2)

    return True, f"Created {settings_file} with jari hooks"


JARI_SYSTEM_PROMPT = """
╔══════════════════════════════════════════════════════════════════════════════╗
║              JARI 砂利 (GRAVEL) - LLM AGENT TASK TRACKER GUIDE               ║
╚══════════════════════════════════════════════════════════════════════════════╝

Jari is a task/issue tracker designed for AI agent workflows.
It tracks todos with priorities, dependencies, assignments, and conflict detection.

## CORE WORKFLOW

┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. See what's ready:    jari ready                                          │
│ 2. Claim a task:        jari claim <id> --agent <name>                      │
│ 3. Work on it                                                               │
│ 4. Close when done:     jari close <id> --reason "done" --agent <name>      │
│ 5. Next task:           jari ready                                          │
└─────────────────────────────────────────────────────────────────────────────┘

## ALL COMMANDS

╔═══════════════╦══════════════════════════════════════════════════════════════╗
║ COMMAND       ║ PURPOSE                                                      ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ SETUP:        ║                                                              ║
║ init          ║ Initialize database (run once)                               ║
║ setup claude  ║ Install Claude Code hooks                                    ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ CRUD:         ║                                                              ║
║ create        ║ Create a todo (-p priority, -t type, --agent)                ║
║ show <id>     ║ View todo details                                            ║
║ update <id>   ║ Update fields (--status, --priority, --title, --assign)      ║
║ close <id>    ║ Close a todo (--reason)                                      ║
║ reopen <id>   ║ Reopen a closed todo                                         ║
║ delete <id>   ║ Delete a todo                                                ║
║ list          ║ List todos (--status, --priority, --assignee, --type)        ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ WORKFLOW:     ║                                                              ║
║ ready         ║ Ready queue: no blockers, sorted by priority+age             ║
║ claim <id>    ║ Atomic claim: assignee + in_progress                         ║
║ blocked       ║ Show blocked todos with blocker info                         ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ DEPENDENCIES: ║                                                              ║
║ dep add a b   ║ a blocked by b (cycle-checked)                               ║
║ dep remove a b║ Remove dependency                                            ║
║ dep tree <id> ║ Show dependency tree                                         ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ LABELS:       ║                                                              ║
║ label add     ║ Add label to todo                                            ║
║ label remove  ║ Remove label from todo                                       ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ NIWA:         ║                                                              ║
║ link          ║ Link todo to niwa node                                       ║
║ unlink        ║ Unlink from niwa node                                        ║
║ linked        ║ Show todos for niwa node                                     ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ AGENT:        ║                                                              ║
║ status        ║ Agent status or database stats                               ║
║ agents        ║ List all agents                                              ║
╠═══════════════╬══════════════════════════════════════════════════════════════╣
║ UTILITY:      ║                                                              ║
║ search        ║ Full-text search                                             ║
║ export        ║ JSONL export                                                 ║
║ history <id>  ║ Version history                                              ║
║ prime         ║ Workflow context for LLM (~500-1000 tokens)                  ║
║ help [cmd]    ║ Show help                                                    ║
╚═══════════════╩══════════════════════════════════════════════════════════════╝

## PRIORITIES
  0 = critical, 1 = high, 2 = medium (default), 3 = low, 4 = backlog

## STATUSES
  open → in_progress → closed
  open → blocked (has active blockers)
  open → deferred (postponed)

## CONFLICT DETECTION
  When two agents update the same todo concurrently:
  - Field-level analysis: if changes touch different fields → auto-merge
  - If same fields changed → conflict requiring resolution
  - Resolution: ACCEPT_YOURS | ACCEPT_THEIRS | MANUAL_MERGE field=value

## EXAMPLE WORKFLOW

```bash
# Initialize
jari init

# Create tasks
jari create "Fix login bug" -p 1 -t bug --agent claude_1
jari create "Add OAuth" -p 2 -t feature --agent claude_1
jari dep add todo_2 todo_1    # OAuth blocked by login fix

# Work on ready items
jari ready                    # Shows todo_1 (todo_2 is blocked)
jari claim todo_1 --agent claude_1
# ... do the work ...
jari close todo_1 --reason "Fixed" --agent claude_1

# Now todo_2 is unblocked
jari ready                    # Shows todo_2
jari claim todo_2 --agent claude_1
```

## COMMON MISTAKES
╔════════════════════════════════════╦═════════════════════════════════════════╗
║ MISTAKE                            ║ FIX                                     ║
╠════════════════════════════════════╬═════════════════════════════════════════╣
║ Forgetting --agent                 ║ Always use --agent <unique_name>        ║
║ Working on blocked todo            ║ Use `jari ready` for unblocked items    ║
║ Circular dependency                ║ Cycle detection prevents this           ║
║ Claiming already-claimed todo      ║ Check assignee with `jari show <id>`   ║
╚════════════════════════════════════╩═════════════════════════════════════════╝
"""


ERROR_PROMPTS = {
    'no_title': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ ERROR: Missing title                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ USAGE:                                                                       ║
║   jari create "Title" [-p priority] [-t type] --agent <name>   ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari create "Fix login bug" -p 1 -t bug --agent claude_1    ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'no_todo_id': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ ERROR: Missing todo_id                                                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ You need to specify which todo to operate on.                                ║
║                                                                              ║
║ Find todo IDs with:                                                          ║
║   jari list                                                    ║
║   jari ready                                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'todo_not_found': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ ERROR: Todo not found                                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ The todo_id you specified doesn't exist.                                     ║
║                                                                              ║
║ Find valid IDs:                                                              ║
║   jari list                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'unknown_command': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ ERROR: Unknown command                                                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Run: jari help                                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
}


def print_error(error_type: str, context: dict = None, show_full_guide: bool = False):
    """Print an LLM-friendly error message with guidance."""
    if show_full_guide:
        print(JARI_SYSTEM_PROMPT)
        print("\n" + "=" * 80)
        print("❌ ERROR OCCURRED - SEE DETAILS BELOW")
        print("=" * 80 + "\n")

    if error_type in ERROR_PROMPTS:
        print(ERROR_PROMPTS[error_type])
    else:
        print(f"Error: {error_type}")

    if context:
        print("\nContext:")
        for k, v in context.items():
            print(f"  {k}: {v}")
