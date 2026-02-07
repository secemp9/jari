"""jari.command - Help text for CLI commands."""


COMMAND_HELP = {
    'init': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: init                                                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Initialize a new jari database                                      ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari init                                                   ║
║                                                                              ║
║ WHAT IT DOES:                                                                ║
║   - Creates .jari/ directory                                                 ║
║   - Initializes LMDB database with 4 sub-databases                          ║
║                                                                              ║
║ NEXT STEP:                                                                   ║
║   jari create "My task" --agent <name>                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'create': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: create                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Create a new todo/task/bug/feature                                  ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari create "Title" [options]                                ║
║                                                                              ║
║ OPTIONS:                                                                     ║
║   -d "desc"          Description                                             ║
║   -p 0-4             Priority (0=critical..4=backlog, default=2)             ║
║   -t type            Type (task|bug|feature|epic, default=task)              ║
║   --agent name       Agent creating this todo                                ║
║   --niwa-ref id      Link to niwa node                                       ║
║   --parent id        Parent todo (for epics)                                 ║
║   --file path        Read description from file                              ║
║   --stdin            Read description from stdin                             ║
║                                                                              ║
║ EXAMPLES:                                                                    ║
║   jari create "Fix login bug" -p 1 -t bug --agent claude_1    ║
║   jari create "New feature" -d "Details here" --agent a1       ║
║   jari create "Epic" -t epic --agent a1                        ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'show': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: show                                                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: View detailed information about a todo                              ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari show <todo_id>                                          ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari show todo_1                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'update': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: update                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Update a todo's fields (with conflict detection)                    ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari update <todo_id> [options] --agent <name>               ║
║                                                                              ║
║ OPTIONS:                                                                     ║
║   --status X         open|in_progress|blocked|closed|deferred                ║
║   --priority N       0=critical, 1=high, 2=medium, 3=low, 4=backlog         ║
║   --title "X"        New title                                               ║
║   --description "X"  New description                                         ║
║   --assign agent     Assign to agent                                         ║
║   -t type            Change type                                             ║
║                                                                              ║
║ EXAMPLES:                                                                    ║
║   jari update todo_1 --status in_progress --agent a1           ║
║   jari update todo_1 --priority 0 --agent a1                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'close': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: close                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Close a todo                                                        ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari close <todo_id> [--reason "text"] --agent <name>        ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari close todo_1 --reason "Fixed in commit abc" --agent a1  ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'list': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: list                                                                ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: List todos with optional filters                                    ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari list [--status X] [--priority N] [--assignee X]         ║
║             [--type X] [--label X]                                           ║
║                                                                              ║
║ EXAMPLES:                                                                    ║
║   jari list                                                    ║
║   jari list --status open --priority 1                         ║
║   jari list --assignee claude_1                                ║
║   jari list --label urgent                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'ready': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: ready                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Show todos ready to work on (no active blockers)                    ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari ready                                                   ║
║   jari ready --agent <name>     # Filter to your assignments   ║
║                                                                              ║
║ SORT ORDER: Priority (critical first), then age (oldest first)               ║
║ EXCLUDES: Closed, deferred, and actively blocked todos                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'claim': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: claim                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Atomically claim a todo (set assignee + in_progress)                ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari claim <todo_id> --agent <name>                          ║
║                                                                              ║
║ FAILS IF:                                                                    ║
║   - Already assigned to another agent                                        ║
║   - Todo is closed or deferred                                               ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari claim todo_1 --agent claude_1                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'blocked': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: blocked                                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Show all blocked todos with blocker info                            ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari blocked                                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'dep': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: dep                                                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Manage dependencies between todos                                   ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari dep add <child> <parent>    # child blocked by parent   ║
║   jari dep remove <child> <parent> # remove dependency         ║
║   jari dep tree <id>               # show dependency tree      ║
║                                                                              ║
║ CYCLE DETECTION: Automatically prevents circular dependencies                ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari dep add todo_2 todo_1    # todo_2 blocked by todo_1     ║
║   jari dep tree todo_2          # see dependency tree          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'label': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: label                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Add or remove labels from todos                                     ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari label add <todo_id> <label>                             ║
║   jari label remove <todo_id> <label>                          ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari label add todo_1 urgent                                 ║
║   jari label remove todo_1 urgent                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'link': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: link / unlink / linked                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Link todos to niwa markdown nodes                                   ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari link <todo_id> <niwa_node_id>                           ║
║   jari unlink <todo_id> <niwa_node_id>                         ║
║   jari linked <niwa_node_id>                                   ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari link todo_1 h2_3                                        ║
║   jari linked h2_3          # show todos for niwa node         ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'status': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: status                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Check agent's status or overall database stats                      ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari status                     # Overall stats              ║
║   jari status --agent <name>      # Agent-specific status      ║
║                                                                              ║
║ SHOWS:                                                                       ║
║   - Assigned todos                                                           ║
║   - Pending conflicts                                                        ║
║   - Recent edits                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'agents': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: agents                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: List all agents that have used this database                        ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari agents                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'search': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: search                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Full-text search across title, description, labels                  ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari search <query>                                          ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari search "login"                                          ║
║   jari search "bug"                                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'export': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: export                                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Export all todos as JSONL                                            ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari export                          # Print to stdout       ║
║   jari export --output file.jsonl      # Save to file          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'history': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: history                                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: View version history for a todo                                     ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari history <todo_id>                                       ║
║                                                                              ║
║ EXAMPLE:                                                                     ║
║   jari history todo_1                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'prime': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: prime                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Output workflow context for LLM injection (~500-1000 tokens)        ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari prime                                                   ║
║                                                                              ║
║ This outputs a concise summary of database state, ready queue, and           ║
║ workflow instructions suitable for injecting into an LLM context.            ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
    'setup': """
╔══════════════════════════════════════════════════════════════════════════════╗
║ COMMAND: setup                                                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: Install/remove Claude Code hooks                                    ║
║                                                                              ║
║ USAGE:                                                                       ║
║   jari setup claude            # Install hooks                 ║
║   jari setup claude --remove   # Remove hooks                  ║
║                                                                              ║
║ HOOKS INSTALLED:                                                             ║
║   SessionStart - Injects usage guide + database status                       ║
║   PreCompact   - Preserves context before compaction                         ║
║   Stop         - Reminds about open high-priority todos                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
""",
}


def print_command_help(command: str):
    """Print detailed help for a specific command."""
    if command in COMMAND_HELP:
        print(COMMAND_HELP[command])
    else:
        print(f"No detailed help for '{command}'. Run 'jari help' for full guide.")
