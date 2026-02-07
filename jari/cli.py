"""jari.cli - Command-line interface for the jari task tracker."""

import os
import sys
import argparse
import json
from datetime import datetime
from pathlib import Path

from . import __version__
from .command import print_command_help
from .core import JARI_SYSTEM_PROMPT, handle_hook_event, print_error, setup_claude_hooks
from .models import ConflictAnalysis
from .jari import JariDB


def main():

    COMMANDS_HELP = """
commands:
  init                  Initialize a new database
  create "Title"        Create a new todo
  show <id>             View todo details
  update <id>           Update a todo
  close <id>            Close a todo
  reopen <id>           Reopen a closed todo
  delete <id>           Delete a todo
  list                  List all todos (with filters)
  ready                 Show ready queue (no active blockers)
  claim <id>            Atomic claim (assign + in_progress)
  blocked               Show all blocked todos
  dep add <a> <b>       Add dependency (a blocked by b)
  dep remove <a> <b>    Remove dependency
  dep tree <id>         Show dependency tree
  label add <id> <l>    Add label
  label remove <id> <l> Remove label
  link <id> <niwa_id>   Link todo to niwa node
  unlink <id> <niwa_id> Unlink from niwa node
  linked <niwa_id>      Show todos linked to niwa node
  status                Agent status
  agents                List all agents
  search <query>        Full-text search
  export                Export as JSONL
  history <id>          Version history
  prime                 Output workflow context for LLM
  setup claude          Install Claude Code hooks
  help [command]        Show help

examples:
  jari init && jari create "Fix login bug" -p 1 -t bug --agent claude_1
  jari list --status open --priority 1
  jari ready
  jari claim todo_1 --agent claude_1
  jari dep add todo_2 todo_1
  jari close todo_1 --reason "Fixed in commit abc" --agent claude_1
"""

    parser = argparse.ArgumentParser(
        description="Jari 砂利 - Task/Issue Tracker for LLM Agent Workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=COMMANDS_HELP
    )
    parser.add_argument('-v', '--version', action='version', version=f'jari {__version__}')
    parser.add_argument('command', nargs='?', default='help', metavar='COMMAND',
                       help='Command to run (see commands below)')
    parser.add_argument('args', nargs='*', help='Command arguments')
    parser.add_argument('--agent', default='default_agent', help='Agent ID (use a unique name!)')
    parser.add_argument('-d', '--description', default='', help='Todo description')
    parser.add_argument('-p', '--priority', type=int, default=None, help='Priority (0=critical, 1=high, 2=medium, 3=low, 4=backlog)')
    parser.add_argument('-t', '--type', default=None, dest='todo_type', help='Type (task|bug|feature|epic)')
    parser.add_argument('--status', default=None, help='Filter by status')
    parser.add_argument('--assignee', default=None, help='Filter by assignee')
    parser.add_argument('--label', default=None, help='Filter by label')
    parser.add_argument('--title', default=None, help='New title (for update)')
    parser.add_argument('--assign', default=None, help='Assign to agent (for update)')
    parser.add_argument('--reason', default=None, help='Close reason')
    parser.add_argument('--niwa-ref', default=None, help='Niwa node reference')
    parser.add_argument('--parent', default=None, help='Parent todo ID (for epics)')
    parser.add_argument('--output', default=None, help='Output file path')
    parser.add_argument('--remove', action='store_true', help='Remove hook configuration')
    parser.add_argument('--hook-event', default=None, help='Hook event name (internal)')
    parser.add_argument('--file', default=None, help='Read content from file')
    parser.add_argument('--stdin', action='store_true', help='Read content from stdin')

    args = parser.parse_args()

    # Help
    if args.command == 'help':
        if args.args:
            print_command_help(args.args[0])
        else:
            print(JARI_SYSTEM_PROMPT)
        return

    # Setup - doesn't need database
    if args.command == 'setup':
        if not args.args:
            print_command_help('setup')
            return

        target = args.args[0].lower()
        if target == 'claude':
            project_dir = os.getcwd()
            success, message = setup_claude_hooks(project_dir, remove=args.remove)
            if success:
                if args.remove:
                    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ CLAUDE CODE HOOKS REMOVED                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {message:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
                else:
                    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ CLAUDE CODE HOOKS INSTALLED                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {message:<76} ║
║                                                                              ║
║ HOOKS INSTALLED:                                                             ║
║   • SessionStart - Injects Jari usage guide + status on session start        ║
║   • PreCompact   - Preserves Jari context before context compaction          ║
║   • Stop         - Reminds about open todos                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ SETUP FAILED                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {message:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            return
        else:
            print(f"Unknown setup target: {target}. Use: jari setup claude")
            return

    # Hook command
    if args.command == 'hook':
        if not args.hook_event:
            print("Hook event not specified.", file=sys.stderr)
            sys.exit(1)
        exit_code = handle_hook_event(args.hook_event)
        sys.exit(exit_code)

    # Check database existence
    db_exists = Path(".jari/data.lmdb").exists()

    if args.command != 'init' and not db_exists:
        print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ DATABASE NOT INITIALIZED                                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Run: jari init                                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
        return

    db = JariDB()

    # Validate agent name
    agent_commands = ['create', 'update', 'close', 'reopen', 'delete', 'claim', 'status']
    if args.command in agent_commands and args.agent != 'default_agent':
        valid, msg = db.validate_agent_name(args.agent)
        if not valid:
            print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ INVALID AGENT NAME                                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {msg:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            db.close()
            return

    try:
        # ==================================================================
        # INIT
        # ==================================================================
        if args.command == 'init':
            if db_exists:
                print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ℹ️  DATABASE ALREADY EXISTS                                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ A database already exists at .jari/                                          ║
║                                                                              ║
║ Use: jari list   or   jari create "Title" --agent <name>                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ DATABASE INITIALIZED                                                      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Created database at .jari/                                                   ║
║                                                                              ║
║ NEXT: jari create "My first task" --agent <name>                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

        # ==================================================================
        # CREATE
        # ==================================================================
        elif args.command == 'create':
            if not args.args:
                print_error('no_title')
                return

            title = args.args[0]
            description = args.description
            # Support description from --file or --stdin
            if args.file:
                try:
                    with open(args.file, 'r') as f:
                        description = f.read()
                except Exception as e:
                    print(f"Cannot read file: {e}")
                    return
            elif args.stdin:
                description = sys.stdin.read()
            elif len(args.args) >= 2 and not args.description:
                description = args.args[1]

            priority = args.priority if args.priority is not None else 2
            todo_type = args.todo_type if args.todo_type else 'task'
            niwa_refs = [args.niwa_ref] if args.niwa_ref else None
            labels = None

            todo_id = db.create_todo(
                title=title,
                description=description,
                priority=priority,
                todo_type=todo_type,
                agent_id=args.agent,
                niwa_refs=niwa_refs,
                parent_id=args.parent,
                labels=labels,
            )

            priority_name = db.PRIORITY_NAMES.get(priority, str(priority))
            print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ TODO CREATED                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ ID:       {todo_id:<65} ║
║ Title:    {title[:65]:<65} ║
║ Priority: {priority_name:<65} ║
║ Type:     {todo_type:<65} ║
║ Agent:    {args.agent:<65} ║
╚══════════════════════════════════════════════════════════════════════════════╝

TODO_ID: {todo_id}
""")

        # ==================================================================
        # SHOW
        # ==================================================================
        elif args.command == 'show':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]
            todo = db.read_todo(todo_id)
            if not todo:
                print_error('todo_not_found', {'provided_id': todo_id})
                return

            priority_name = db.PRIORITY_NAMES.get(todo['priority'], str(todo['priority']))
            created = datetime.fromtimestamp(todo['created_at']).strftime('%Y-%m-%d %H:%M') if todo.get('created_at') else '?'
            updated = datetime.fromtimestamp(todo['updated_at']).strftime('%Y-%m-%d %H:%M') if todo.get('updated_at') else '?'
            closed = datetime.fromtimestamp(todo['closed_at']).strftime('%Y-%m-%d %H:%M') if todo.get('closed_at') else '-'

            status_icon = {
                'open': '⬚', 'in_progress': '▶', 'blocked': '⊘',
                'closed': '✓', 'deferred': '⏸'
            }.get(todo['status'], '?')

            print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ {status_icon} {todo['id']} — {todo['title'][:60]:<63} ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Status:     {todo['status']:<63} ║
║ Priority:   {priority_name:<63} ║
║ Type:       {todo['type']:<63} ║
║ Assignee:   {(todo.get('assignee') or '-'):<63} ║
║ Created by: {todo['created_by']:<63} ║
║ Created:    {created:<63} ║
║ Updated:    {updated:<63} ║
║ Closed:     {closed:<63} ║
║ Version:    {todo['version']:<63} ║""")

            if todo.get('close_reason'):
                print(f"║ Reason:     {todo['close_reason'][:63]:<63} ║")

            if todo.get('labels'):
                print(f"║ Labels:     {', '.join(todo['labels'])[:63]:<63} ║")

            if todo.get('niwa_refs'):
                print(f"║ Niwa refs:  {', '.join(todo['niwa_refs'])[:63]:<63} ║")

            if todo.get('blocked_by'):
                print(f"║ Blocked by: {', '.join(todo['blocked_by'])[:63]:<63} ║")

            if todo.get('blocks'):
                print(f"║ Blocks:     {', '.join(todo['blocks'])[:63]:<63} ║")

            if todo.get('parent_id'):
                print(f"║ Parent:     {todo['parent_id']:<63} ║")

            if todo.get('children'):
                print(f"║ Children:   {', '.join(todo['children'])[:63]:<63} ║")

            print("╚══════════════════════════════════════════════════════════════════════════════╝")

            if todo.get('description'):
                print(f"""
DESCRIPTION:
─────────────────────────────────────────────────────────────────────────────────
{todo['description']}
─────────────────────────────────────────────────────────────────────────────────
""")

        # ==================================================================
        # UPDATE
        # ==================================================================
        elif args.command == 'update':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]

            changes = {}
            if args.status:
                if args.status not in db.VALID_STATUSES:
                    print(f"Invalid status: {args.status}. Valid: {', '.join(db.VALID_STATUSES)}")
                    return
                changes['status'] = args.status
            if args.priority is not None:
                if args.priority not in db.VALID_PRIORITIES:
                    print(f"Invalid priority: {args.priority}. Valid: 0-4")
                    return
                changes['priority'] = args.priority
            if args.title:
                changes['title'] = args.title
            if args.description:
                changes['description'] = args.description
            if args.assign:
                changes['assignee'] = args.assign
            if args.todo_type:
                if args.todo_type not in db.VALID_TYPES:
                    print(f"Invalid type: {args.todo_type}. Valid: {', '.join(db.VALID_TYPES)}")
                    return
                changes['type'] = args.todo_type

            # Support description from file/stdin
            if args.file:
                try:
                    with open(args.file, 'r') as f:
                        changes['description'] = f.read()
                except Exception as e:
                    print(f"Cannot read file: {e}")
                    return
            elif args.stdin:
                changes['description'] = sys.stdin.read()

            if not changes:
                print("No changes specified. Use --status, --priority, --title, --description, --assign, --type")
                return

            # Read for edit first (for conflict detection)
            todo = db.read_for_edit(todo_id, args.agent)
            if not todo:
                print_error('todo_not_found', {'provided_id': todo_id})
                return

            summary = f"Updated: {', '.join(changes.keys())}"
            result = db.update_todo(todo_id, changes, args.agent, summary)

            if result.success:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ TODO UPDATED                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {result.message:<76} ║
║ Agent: {args.agent:<69} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            elif result.conflict:
                db.store_conflict(args.agent, result.conflict)
                print("=" * 80)
                print("⚠️  CONFLICT DETECTED!")
                print("=" * 80)
                print(result.conflict.to_llm_prompt())
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ HOW TO RESOLVE:                                                              ║
║   jari resolve {todo_id} ACCEPT_YOURS --agent {args.agent:<24} ║
║   jari resolve {todo_id} ACCEPT_THEIRS --agent {args.agent:<23} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ❌ UPDATE FAILED                                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {result.message:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

        # ==================================================================
        # CLOSE
        # ==================================================================
        elif args.command == 'close':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]
            reason = args.reason or ''
            result = db.close_todo(todo_id, reason, args.agent)

            if result.success:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ TODO CLOSED                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {result.message:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"❌ {result.message}")

        # ==================================================================
        # REOPEN
        # ==================================================================
        elif args.command == 'reopen':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]
            result = db.reopen_todo(todo_id, args.agent)

            if result.success:
                print(f"✅ Reopened {todo_id}")
            else:
                print(f"❌ {result.message}")

        # ==================================================================
        # DELETE
        # ==================================================================
        elif args.command == 'delete':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]
            result = db.delete_todo(todo_id, args.agent)

            if result.success:
                print(f"✅ {result.message}")
            else:
                print(f"❌ {result.message}")

        # ==================================================================
        # LIST
        # ==================================================================
        elif args.command == 'list':
            filters = {}
            if args.status:
                filters['status'] = args.status
            if args.priority is not None:
                filters['priority'] = args.priority
            if args.assignee:
                filters['assignee'] = args.assignee
            if args.todo_type:
                filters['type'] = args.todo_type
            if args.label:
                filters['label'] = args.label

            todos = db.list_todos(filters if filters else None)

            if not todos:
                print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ No todos found.                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ 📋 TODOS: {len(todos)} item(s){' ' * 63}║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
                _print_todo_table(todos, db)

        # ==================================================================
        # READY
        # ==================================================================
        elif args.command == 'ready':
            agent_filter = args.agent if args.agent != 'default_agent' else None
            ready = db.get_ready_queue(agent_filter)

            if not ready:
                print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ No ready todos. All items are blocked, closed, or deferred.                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ 🚀 READY QUEUE: {len(ready)} todo(s) ready to work on{' ' * 48}║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
                _print_todo_table(ready, db)
                print(f"\nTo claim: jari claim <id> --agent <name>")

        # ==================================================================
        # CLAIM
        # ==================================================================
        elif args.command == 'claim':
            if not args.args:
                print_error('no_todo_id')
                return

            todo_id = args.args[0]
            if args.agent == 'default_agent':
                print("❌ --agent required for claim")
                return

            result = db.claim_todo(todo_id, args.agent)

            if result.success:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ CLAIMED                                                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {result.message:<76} ║
║ Todo: {todo_id:<70} ║
║ Agent: {args.agent:<69} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"❌ {result.message}")

        # ==================================================================
        # BLOCKED
        # ==================================================================
        elif args.command == 'blocked':
            blocked = db.get_blocked_todos()

            if not blocked:
                print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║ No blocked todos.                                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ⊘ BLOCKED TODOS: {len(blocked)}{' ' * 58}║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
                for todo in blocked:
                    blockers = todo.get('active_blockers', [])
                    blocker_str = ', '.join(f"{b['id']}({b['status']})" for b in blockers)
                    print(f"  [{todo['id']}] {todo['title'][:40]}")
                    print(f"    Blocked by: {blocker_str}")

        # ==================================================================
        # DEP
        # ==================================================================
        elif args.command == 'dep':
            if not args.args:
                print("Usage: jari dep add|remove|tree <args>")
                return

            subcmd = args.args[0]

            if subcmd == 'add':
                if len(args.args) < 3:
                    print("Usage: jari dep add <child_id> <parent_id>")
                    return
                child_id, parent_id = args.args[1], args.args[2]
                result = db.add_dependency(child_id, parent_id, args.agent)
                if result.success:
                    print(f"✅ {result.message}")
                else:
                    print(f"❌ {result.message}")

            elif subcmd == 'remove':
                if len(args.args) < 3:
                    print("Usage: jari dep remove <child_id> <parent_id>")
                    return
                child_id, parent_id = args.args[1], args.args[2]
                result = db.remove_dependency(child_id, parent_id, args.agent)
                if result.success:
                    print(f"✅ {result.message}")
                else:
                    print(f"❌ {result.message}")

            elif subcmd == 'tree':
                if len(args.args) < 2:
                    print("Usage: jari dep tree <todo_id>")
                    return
                todo_id = args.args[1]
                tree = db.get_dependency_tree(todo_id)
                if tree:
                    _print_dep_tree(tree)
                else:
                    print(f"Todo {todo_id} not found")

            else:
                print(f"Unknown dep subcommand: {subcmd}. Use: add, remove, tree")

        # ==================================================================
        # LABEL
        # ==================================================================
        elif args.command == 'label':
            if not args.args:
                print("Usage: jari label add|remove <todo_id> <label>")
                return

            subcmd = args.args[0]

            if subcmd == 'add':
                if len(args.args) < 3:
                    print("Usage: jari label add <todo_id> <label>")
                    return
                todo_id, label = args.args[1], args.args[2]
                result = db.add_label(todo_id, label, args.agent)
                if result.success:
                    print(f"✅ {result.message}")
                else:
                    print(f"❌ {result.message}")

            elif subcmd == 'remove':
                if len(args.args) < 3:
                    print("Usage: jari label remove <todo_id> <label>")
                    return
                todo_id, label = args.args[1], args.args[2]
                result = db.remove_label(todo_id, label, args.agent)
                if result.success:
                    print(f"✅ {result.message}")
                else:
                    print(f"❌ {result.message}")

            else:
                print(f"Unknown label subcommand: {subcmd}. Use: add, remove")

        # ==================================================================
        # LINK / UNLINK / LINKED
        # ==================================================================
        elif args.command == 'link':
            if len(args.args) < 2:
                print("Usage: jari link <todo_id> <niwa_node_id>")
                return
            todo_id, niwa_id = args.args[0], args.args[1]
            result = db.link_to_niwa(todo_id, niwa_id, args.agent)
            if result.success:
                print(f"✅ {result.message}")
            else:
                print(f"❌ {result.message}")

        elif args.command == 'unlink':
            if len(args.args) < 2:
                print("Usage: jari unlink <todo_id> <niwa_node_id>")
                return
            todo_id, niwa_id = args.args[0], args.args[1]
            result = db.unlink_from_niwa(todo_id, niwa_id, args.agent)
            if result.success:
                print(f"✅ {result.message}")
            else:
                print(f"❌ {result.message}")

        elif args.command == 'linked':
            if not args.args:
                print("Usage: jari linked <niwa_node_id>")
                return
            niwa_id = args.args[0]
            todos = db.get_todos_for_niwa_node(niwa_id)
            if not todos:
                print(f"No todos linked to niwa node {niwa_id}")
            else:
                print(f"\nTodos linked to niwa node [{niwa_id}]:")
                _print_todo_table(todos, db)

        # ==================================================================
        # RESOLVE
        # ==================================================================
        elif args.command == 'resolve':
            if not args.args or len(args.args) < 2:
                print("Usage: jari resolve <todo_id> ACCEPT_YOURS|ACCEPT_THEIRS|MANUAL_MERGE --agent <name>")
                return

            todo_id = args.args[0]
            resolution = args.args[1].upper()

            valid_resolutions = ['ACCEPT_YOURS', 'ACCEPT_THEIRS', 'MANUAL_MERGE']
            if resolution not in valid_resolutions:
                print(f"Invalid resolution: {resolution}. Use: {', '.join(valid_resolutions)}")
                return

            # Look up stored conflict
            stored_conflict = None
            stored_conflicts = db.get_pending_conflicts(args.agent)
            for sc in stored_conflicts:
                if sc.get('todo_id') == todo_id:
                    your_changes = {k: tuple(v) for k, v in sc.get('your_changes', {}).items()}
                    their_changes = {k: tuple(v) for k, v in sc.get('their_changes', {}).items()}
                    stored_conflict = ConflictAnalysis(
                        todo_id=sc['todo_id'],
                        todo_title=sc.get('todo_title', ''),
                        your_base_version=sc.get('your_base_version', 0),
                        current_version=sc.get('current_version', 0),
                        your_changes=your_changes,
                        their_changes=their_changes,
                        overlapping_fields=sc.get('overlapping_fields', []),
                        your_agent_id=args.agent,
                        other_agents=[],
                        auto_merge_possible=sc.get('auto_merge_possible', False),
                    )
                    break

            manual_changes = None
            if resolution == 'MANUAL_MERGE':
                # Parse field=value from remaining args
                if len(args.args) > 2:
                    manual_changes = {}
                    for arg in args.args[2:]:
                        if '=' in arg:
                            k, v = arg.split('=', 1)
                            manual_changes[k] = v
                if not manual_changes:
                    print("MANUAL_MERGE requires field=value pairs. Example: jari resolve todo_1 MANUAL_MERGE status=open priority=1")
                    return

            result = db.resolve_conflict(
                todo_id, resolution, args.agent,
                manual_changes=manual_changes,
                conflict=stored_conflict,
            )

            if result.success:
                db.clear_conflict(args.agent, todo_id)
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ ✅ CONFLICT RESOLVED                                                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ {result.message:<76} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
            else:
                print(f"❌ {result.message}")

        # ==================================================================
        # STATUS
        # ==================================================================
        elif args.command == 'status':
            agent = args.agent if args.agent != 'default_agent' else None
            if not agent:
                # Show overall stats
                stats = db.get_db_stats()
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ 📊 DATABASE STATUS                                                           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ Total todos: {stats['total']:<62} ║
║ Pending conflicts: {stats['pending_conflicts']:<56} ║
╠══════════════════════════════════════════════════════════════════════════════╣""")
                for s, count in sorted(stats['by_status'].items()):
                    print(f"║   {s:<12}: {count:<61} ║")
                print("╠══════════════════════════════════════════════════════════════════════════════╣")
                for p, count in sorted(stats['by_priority'].items()):
                    print(f"║   {p:<12}: {count:<61} ║")
                print("╚══════════════════════════════════════════════════════════════════════════════╝")
            else:
                status = db.get_agent_status(agent)
                print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ 📊 AGENT STATUS: {agent:<58} ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
                if status['assigned_todos']:
                    print("📋 ASSIGNED TODOS:")
                    print("─" * 78)
                    for t in status['assigned_todos']:
                        pname = db.PRIORITY_NAMES.get(t['priority'], '?')
                        print(f"  [{t['id']}] {t['title'][:40]} ({t['status']}, {pname})")
                    print()

                if status['pending_conflicts']:
                    print("⚠️  PENDING CONFLICTS:")
                    print("─" * 78)
                    for c in status['pending_conflicts']:
                        print(f"  [{c['todo_id']}] \"{c.get('todo_title', '?')[:40]}\"")
                    print()

                if status['recent_edits']:
                    print("✏️  RECENT EDITS:")
                    print("─" * 78)
                    for e in status['recent_edits'][:5]:
                        ts = datetime.fromtimestamp(e['timestamp']).strftime('%H:%M:%S')
                        print(f"  [{e['todo_id']}] v{e['version']} at {ts}: {e.get('summary', '(none)')[:40]}")
                    print()

                if not status['assigned_todos'] and not status['pending_conflicts']:
                    print("✅ No assigned todos or conflicts. Ready to work!")

        # ==================================================================
        # AGENTS
        # ==================================================================
        elif args.command == 'agents':
            agents = db.list_all_agents()
            if not agents:
                print("No agents have used this database yet.")
            else:
                print(f"\n👥 REGISTERED AGENTS: {len(agents)}\n")
                for a in agents:
                    first = datetime.fromtimestamp(a['first_seen']).strftime('%m-%d %H:%M') if a['first_seen'] else '?'
                    last = datetime.fromtimestamp(a['last_seen']).strftime('%m-%d %H:%M') if a['last_seen'] else '?'
                    print(f"  {a['agent_id']:<20} edits={a['edit_count']:<5} first={first}  last={last}  todos={', '.join(a['todos_touched'][:3])}")

        # ==================================================================
        # SEARCH
        # ==================================================================
        elif args.command == 'search':
            if not args.args:
                print("Usage: jari search <query>")
                return

            query = args.args[0]
            results = db.search_todos(query)

            if not results:
                print(f"No todos matching \"{query}\"")
            else:
                print(f"\n🔍 SEARCH RESULTS: {len(results)} todo(s) for \"{query}\"\n")
                _print_todo_table(results, db)

        # ==================================================================
        # EXPORT
        # ==================================================================
        elif args.command == 'export':
            result = db.export_jsonl(args.output)
            if args.output:
                print(f"✅ {result}")
            else:
                print(result, end='')

        # ==================================================================
        # HISTORY
        # ==================================================================
        elif args.command == 'history':
            if not args.args:
                print("Usage: jari history <todo_id>")
                return

            todo_id = args.args[0]
            history = db.get_todo_history(todo_id)

            if not history:
                print(f"No history for {todo_id}")
            else:
                print(f"\n📜 HISTORY: [{todo_id}]\n")
                for h in history:
                    ts = datetime.fromtimestamp(h['timestamp']).strftime('%Y-%m-%d %H:%M:%S') if h.get('timestamp') else '?'
                    snapshot = "✓ snapshot" if h.get('has_snapshot') else "✗ no snapshot"
                    changes_str = ', '.join(f"{k}={v}" for k, v in h.get('changes', {}).items())[:50]
                    print(f"  v{h['version']} | {ts} | {h.get('agent', '?')} | {h.get('summary', '(none)')[:30]} | {snapshot}")
                    if changes_str:
                        print(f"       {changes_str}")

        # ==================================================================
        # PRIME
        # ==================================================================
        elif args.command == 'prime':
            from .core import generate_prime_output
            print(generate_prime_output(db))

        # ==================================================================
        # UNKNOWN
        # ==================================================================
        else:
            print_error('unknown_command')
            print(f"\nYou entered: '{args.command}'")

    finally:
        db.close()


def _print_todo_table(todos: list, db: JariDB):
    """Print a formatted table of todos."""
    status_icons = {
        'open': '⬚', 'in_progress': '▶', 'blocked': '⊘',
        'closed': '✓', 'deferred': '⏸'
    }
    print(f" {'ID':<10} {'St':>2} {'Pri':<5} {'Type':<8} {'Assignee':<15} {'Title':<35}")
    print(f" {'─'*10} {'─'*2} {'─'*5} {'─'*8} {'─'*15} {'─'*35}")
    for todo in todos:
        icon = status_icons.get(todo['status'], '?')
        pname = db.PRIORITY_NAMES.get(todo['priority'], '?')[:5]
        assignee = (todo.get('assignee') or '-')[:15]
        title = todo['title'][:35]
        print(f" {todo['id']:<10} {icon:>2} {pname:<5} {todo['type']:<8} {assignee:<15} {title}")


def _print_dep_tree(node: dict, depth: int = 0):
    """Print dependency tree recursively."""
    indent = "  " * depth
    status_icons = {
        'open': '⬚', 'in_progress': '▶', 'blocked': '⊘',
        'closed': '✓', 'deferred': '⏸'
    }
    icon = status_icons.get(node['status'], '?')
    assignee = f" @{node['assignee']}" if node.get('assignee') else ""
    print(f"{indent}{icon} [{node['id']}] {node['title'][:40]}{assignee}")
    for dep in node.get('deps', []):
        _print_dep_tree(dep, depth + 1)
