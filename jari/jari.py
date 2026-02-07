"""jari.jari - Core LMDB-backed task/issue database."""

import json
import time
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

try:
    import lmdb
except ImportError:
    print("Please install lmdb: pip install lmdb")
    raise

from .models import ConflictAnalysis, EditResult


class JariDB:
    """
    Task/Issue tracker with LMDB storage and field-level conflict detection.

    Uses LMDB for:
    - Fast concurrent reads (multiple readers)
    - Atomic writes (single writer, but very fast)
    - Memory-mapped I/O
    - ACID transactions
    """

    VALID_STATUSES = ('open', 'in_progress', 'blocked', 'closed', 'deferred')
    VALID_TYPES = ('task', 'bug', 'feature', 'epic')
    VALID_PRIORITIES = (0, 1, 2, 3, 4)
    PRIORITY_NAMES = {0: 'critical', 1: 'high', 2: 'medium', 3: 'low', 4: 'backlog'}

    def __init__(self, db_path: str = ".jari"):
        self.db_path = Path(db_path)
        self.db_path.mkdir(exist_ok=True)

        self.env = lmdb.open(
            str(self.db_path / "data.lmdb"),
            map_size=1024 * 1024 * 1024,  # 1GB
            max_dbs=5,
            writemap=True,
            metasync=False,
            sync=False,
        )

        with self.env.begin(write=True) as txn:
            self.todos_db = self.env.open_db(b'todos', txn=txn)
            self.history_db = self.env.open_db(b'history', txn=txn)
            self.pending_db = self.env.open_db(b'pending', txn=txn)
            self.meta_db = self.env.open_db(b'meta', txn=txn)

    def _serialize(self, obj: Any) -> bytes:
        return json.dumps(obj, default=str).encode('utf-8')

    def _deserialize(self, data: bytes) -> Any:
        return json.loads(data.decode('utf-8'))

    def close(self):
        """Close the database."""
        self.env.close()

    # =========================================================================
    # ID GENERATION
    # =========================================================================

    def next_todo_id(self) -> str:
        """Generate the next sequential todo ID (todo_1, todo_2, ...)."""
        pattern = re.compile(r'^todo_(\d+)$')
        max_idx = 0
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, _ in cursor:
                m = pattern.match(key.decode())
                if m:
                    max_idx = max(max_idx, int(m.group(1)))
        return f"todo_{max_idx + 1}"

    # =========================================================================
    # CRUD OPERATIONS
    # =========================================================================

    def create_todo(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        todo_type: str = "task",
        agent_id: str = "system",
        niwa_refs: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> str:
        """Create a new todo. Returns the todo_id."""
        todo_id = self.next_todo_id()

        with self.env.begin(write=True) as txn:
            todo = {
                'id': todo_id,
                'title': title,
                'description': description,
                'status': 'open',
                'priority': priority,
                'type': todo_type,
                'assignee': None,
                'created_by': agent_id,
                'created_at': time.time(),
                'updated_at': time.time(),
                'closed_at': None,
                'close_reason': None,
                'niwa_refs': niwa_refs or [],
                'blocked_by': [],
                'blocks': [],
                'parent_id': parent_id,
                'children': [],
                'labels': labels or [],
                'version': 1,
                'edit_history': [{
                    'version': 1,
                    'agent': agent_id,
                    'timestamp': time.time(),
                    'summary': 'Created',
                    'changes': {},
                }],
            }

            txn.put(todo_id.encode(), self._serialize(todo), db=self.todos_db)

            # Update parent's children list if parent specified
            if parent_id:
                parent_data = txn.get(parent_id.encode(), db=self.todos_db)
                if parent_data:
                    parent = self._deserialize(parent_data)
                    if todo_id not in parent['children']:
                        parent['children'].append(todo_id)
                        txn.put(parent_id.encode(), self._serialize(parent), db=self.todos_db)

            # Store initial version in history
            history_key = f"{todo_id}:v1".encode()
            txn.put(history_key, self._serialize(todo), db=self.history_db)

        return todo_id

    def read_todo(self, todo_id: str) -> Optional[Dict]:
        """Read a todo (lock-free, concurrent safe)."""
        with self.env.begin() as txn:
            data = txn.get(todo_id.encode(), db=self.todos_db)
            return self._deserialize(data) if data else None

    def read_for_edit(self, todo_id: str, agent_id: str) -> Optional[Dict]:
        """Read a todo with intent to edit. Registers agent's read version."""
        with self.env.begin(write=True) as txn:
            data = txn.get(todo_id.encode(), db=self.todos_db)
            if not data:
                return None

            todo = self._deserialize(data)

            # Record this agent's read
            pending_key = f"{todo_id}:{agent_id}".encode()
            pending = {
                'agent_id': agent_id,
                'todo_id': todo_id,
                'read_version': todo['version'],
                'read_at': time.time(),
                'base_snapshot': todo.copy(),
            }
            txn.put(pending_key, self._serialize(pending), db=self.pending_db)

            # Clear any stored conflict for this agent+todo
            conflict_key = f"conflicts:{agent_id}".encode()
            conflict_data = txn.get(conflict_key, db=self.meta_db)
            if conflict_data:
                conflicts = self._deserialize(conflict_data)
                conflicts = [c for c in conflicts if c.get('todo_id') != todo_id]
                if conflicts:
                    txn.put(conflict_key, self._serialize(conflicts), db=self.meta_db)
                else:
                    txn.delete(conflict_key, db=self.meta_db)

            return todo

    def update_todo(
        self,
        todo_id: str,
        changes: Dict,
        agent_id: str,
        summary: str = "",
    ) -> EditResult:
        """Update a todo with field-level conflict detection."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(
                    success=False,
                    todo_id=todo_id,
                    message=f"Todo {todo_id} not found"
                )

            todo = self._deserialize(todo_data)
            current_version = todo['version']

            # Get agent's pending read info
            pending_key = f"{todo_id}:{agent_id}".encode()
            pending_data = txn.get(pending_key, db=self.pending_db)

            if not pending_data:
                # No prior read - apply directly
                return self._apply_update(txn, todo, changes, agent_id, summary)

            pending = self._deserialize(pending_data)
            base_version = pending['read_version']
            base_snapshot = pending['base_snapshot']

            # Clean up pending
            txn.delete(pending_key, db=self.pending_db)

            if base_version == current_version:
                # No conflict
                return self._apply_update(txn, todo, changes, agent_id, summary)

            # CONFLICT - analyze field-level
            conflict = self._analyze_conflict(
                base_snapshot=base_snapshot,
                your_changes=changes,
                current_todo=todo,
                your_agent_id=agent_id,
            )

            if conflict.auto_merge_possible:
                # Auto-merge: apply non-overlapping changes
                merged_changes = conflict.auto_merged_fields or {}
                return self._apply_update(
                    txn, todo, merged_changes, agent_id,
                    f"Auto-merged (system): {summary}"
                )

            # Conflict requires resolution
            return EditResult(
                success=False,
                todo_id=todo_id,
                message="Conflict detected - resolution required",
                conflict=conflict,
            )

    def _apply_update(
        self,
        txn,
        todo: Dict,
        changes: Dict,
        agent_id: str,
        summary: str,
    ) -> EditResult:
        """Apply changes to a todo."""
        old_version = todo['version']

        # Apply field changes
        for field_name, value in changes.items():
            if field_name in ('id', 'version', 'edit_history', 'created_at', 'created_by'):
                continue  # Protected fields
            todo[field_name] = value

        todo['version'] += 1
        todo['updated_at'] = time.time()

        # Add to edit history
        todo['edit_history'].append({
            'version': todo['version'],
            'agent': agent_id,
            'timestamp': time.time(),
            'summary': summary,
            'changes': {k: str(v) for k, v in changes.items()},
        })
        todo['edit_history'] = todo['edit_history'][-20:]

        # Save
        txn.put(todo['id'].encode(), self._serialize(todo), db=self.todos_db)

        # Save to history
        history_key = f"{todo['id']}:v{todo['version']}".encode()
        txn.put(history_key, self._serialize(todo), db=self.history_db)

        return EditResult(
            success=True,
            todo_id=todo['id'],
            new_version=todo['version'],
            message=f"Updated. Version: {old_version} -> {todo['version']}"
        )

    def _analyze_conflict(
        self,
        base_snapshot: Dict,
        your_changes: Dict,
        current_todo: Dict,
        your_agent_id: str,
    ) -> ConflictAnalysis:
        """Analyze field-level conflict between your changes and current state."""
        # Fields we compare
        trackable_fields = (
            'title', 'description', 'status', 'priority', 'type',
            'assignee', 'niwa_refs', 'blocked_by', 'blocks',
            'parent_id', 'children', 'labels', 'close_reason',
        )

        your_field_changes = {}
        their_field_changes = {}
        overlapping = []

        # What you changed from base
        for field_name, new_value in your_changes.items():
            if field_name in trackable_fields:
                base_value = base_snapshot.get(field_name)
                if base_value != new_value:
                    your_field_changes[field_name] = (base_value, new_value)

        # What they changed from base
        for field_name in trackable_fields:
            base_value = base_snapshot.get(field_name)
            current_value = current_todo.get(field_name)
            if base_value != current_value:
                their_field_changes[field_name] = (base_value, current_value)

        # Find overlapping fields
        for field_name in your_field_changes:
            if field_name in their_field_changes:
                overlapping.append(field_name)

        # Auto-merge possible only if no overlapping fields
        auto_merged = None
        if not overlapping:
            # Merge: apply your changes on top of current
            auto_merged = {}
            for field_name, (_, new_value) in your_field_changes.items():
                auto_merged[field_name] = new_value
            # Also include their changes (already in current)
            # We just apply our non-overlapping changes

        # Get other agents
        other_agents = []
        for entry in current_todo.get('edit_history', []):
            if entry['version'] > base_snapshot['version']:
                if entry['agent'] != your_agent_id:
                    other_agents.append(entry['agent'])

        return ConflictAnalysis(
            todo_id=current_todo['id'],
            todo_title=current_todo['title'],
            your_base_version=base_snapshot['version'],
            current_version=current_todo['version'],
            your_changes=your_field_changes,
            their_changes=their_field_changes,
            overlapping_fields=overlapping,
            your_agent_id=your_agent_id,
            other_agents=list(set(other_agents)),
            auto_merge_possible=auto_merged is not None,
            auto_merged_fields=auto_merged,
        )

    def close_todo(self, todo_id: str, reason: str = "", agent_id: str = "system") -> EditResult:
        """Close a todo."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if todo['status'] == 'closed':
                return EditResult(success=False, todo_id=todo_id, message="Todo already closed")

            changes = {
                'status': 'closed',
                'closed_at': time.time(),
                'close_reason': reason or 'Completed',
            }
            return self._apply_update(txn, todo, changes, agent_id, f"Closed: {reason or 'Completed'}")

    def reopen_todo(self, todo_id: str, agent_id: str = "system") -> EditResult:
        """Reopen a closed todo."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if todo['status'] != 'closed':
                return EditResult(success=False, todo_id=todo_id, message="Todo is not closed")

            changes = {
                'status': 'open',
                'closed_at': None,
                'close_reason': None,
            }
            return self._apply_update(txn, todo, changes, agent_id, "Reopened")

    def delete_todo(self, todo_id: str, agent_id: str = "system") -> EditResult:
        """Delete a todo."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)

            # Remove from parent's children
            if todo.get('parent_id'):
                parent_data = txn.get(todo['parent_id'].encode(), db=self.todos_db)
                if parent_data:
                    parent = self._deserialize(parent_data)
                    parent['children'] = [c for c in parent['children'] if c != todo_id]
                    txn.put(todo['parent_id'].encode(), self._serialize(parent), db=self.todos_db)

            # Remove from blockers/blockees
            for blocked_id in todo.get('blocked_by', []):
                other_data = txn.get(blocked_id.encode(), db=self.todos_db)
                if other_data:
                    other = self._deserialize(other_data)
                    other['blocks'] = [b for b in other['blocks'] if b != todo_id]
                    txn.put(blocked_id.encode(), self._serialize(other), db=self.todos_db)

            for blocks_id in todo.get('blocks', []):
                other_data = txn.get(blocks_id.encode(), db=self.todos_db)
                if other_data:
                    other = self._deserialize(other_data)
                    other['blocked_by'] = [b for b in other['blocked_by'] if b != todo_id]
                    txn.put(blocks_id.encode(), self._serialize(other), db=self.todos_db)

            txn.delete(todo_id.encode(), db=self.todos_db)

            return EditResult(
                success=True,
                todo_id=todo_id,
                message=f"Deleted {todo_id}: {todo['title']}"
            )

    def list_todos(self, filters: Optional[Dict] = None) -> List[Dict]:
        """List all todos, optionally filtered."""
        todos = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                if filters:
                    match = True
                    if 'status' in filters and todo['status'] != filters['status']:
                        match = False
                    if 'priority' in filters and todo['priority'] != filters['priority']:
                        match = False
                    if 'assignee' in filters and todo.get('assignee') != filters['assignee']:
                        match = False
                    if 'type' in filters and todo['type'] != filters['type']:
                        match = False
                    if 'label' in filters and filters['label'] not in todo.get('labels', []):
                        match = False
                    if not match:
                        continue
                todos.append(todo)
        return sorted(todos, key=lambda t: (t['priority'], t['created_at']))

    # =========================================================================
    # READY QUEUE & WORKFLOW
    # =========================================================================

    def get_ready_queue(self, agent_id: Optional[str] = None) -> List[Dict]:
        """Get todos ready to work on: open/in_progress with no active blockers."""
        ready = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            all_todos = {}
            for key, value in cursor:
                todo = self._deserialize(value)
                all_todos[todo['id']] = todo

            for todo in all_todos.values():
                if todo['status'] not in ('open', 'in_progress'):
                    continue

                # Check blockers: only count non-closed blockers
                has_active_blocker = False
                for blocker_id in todo.get('blocked_by', []):
                    blocker = all_todos.get(blocker_id)
                    if blocker and blocker['status'] != 'closed':
                        has_active_blocker = True
                        break

                if has_active_blocker:
                    continue

                if agent_id and todo.get('assignee') and todo['assignee'] != agent_id:
                    continue

                ready.append(todo)

        return sorted(ready, key=lambda t: (t['priority'], t['created_at']))

    def claim_todo(self, todo_id: str, agent_id: str) -> EditResult:
        """Atomic claim: set assignee + in_progress, fail if already claimed."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)

            if todo['status'] in ('closed', 'deferred'):
                return EditResult(
                    success=False, todo_id=todo_id,
                    message=f"Cannot claim: todo is {todo['status']}"
                )

            if todo.get('assignee') and todo['assignee'] != agent_id:
                return EditResult(
                    success=False, todo_id=todo_id,
                    message=f"Already assigned to {todo['assignee']}"
                )

            changes = {
                'assignee': agent_id,
                'status': 'in_progress',
            }
            return self._apply_update(txn, todo, changes, agent_id, f"Claimed by {agent_id}")

    def get_blocked_todos(self) -> List[Dict]:
        """Get all blocked todos with blocker info."""
        blocked = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            all_todos = {}
            for key, value in cursor:
                todo = self._deserialize(value)
                all_todos[todo['id']] = todo

            for todo in all_todos.values():
                if todo['status'] == 'closed':
                    continue

                active_blockers = []
                for blocker_id in todo.get('blocked_by', []):
                    blocker = all_todos.get(blocker_id)
                    if blocker and blocker['status'] != 'closed':
                        active_blockers.append({
                            'id': blocker_id,
                            'title': blocker['title'],
                            'status': blocker['status'],
                            'assignee': blocker.get('assignee'),
                        })

                if active_blockers:
                    todo_info = todo.copy()
                    todo_info['active_blockers'] = active_blockers
                    blocked.append(todo_info)

        return sorted(blocked, key=lambda t: (t['priority'], t['created_at']))

    # =========================================================================
    # DEPENDENCIES
    # =========================================================================

    def add_dependency(self, child_id: str, parent_id: str, agent_id: str = "system") -> EditResult:
        """Add dependency: child blocked by parent. Cycle-checked."""
        with self.env.begin(write=True) as txn:
            child_data = txn.get(child_id.encode(), db=self.todos_db)
            parent_data = txn.get(parent_id.encode(), db=self.todos_db)

            if not child_data:
                return EditResult(success=False, todo_id=child_id, message=f"Child {child_id} not found")
            if not parent_data:
                return EditResult(success=False, todo_id=child_id, message=f"Parent {parent_id} not found")
            if child_id == parent_id:
                return EditResult(success=False, todo_id=child_id, message="Cannot depend on self")

            child = self._deserialize(child_data)
            parent = self._deserialize(parent_data)

            if parent_id in child.get('blocked_by', []):
                return EditResult(
                    success=False, todo_id=child_id,
                    message=f"Dependency already exists: {child_id} blocked by {parent_id}"
                )

            # Cycle check
            if self._check_cycle(txn, child_id, parent_id):
                return EditResult(
                    success=False, todo_id=child_id,
                    message=f"Cycle detected: adding {child_id} -> {parent_id} would create a loop"
                )

            child['blocked_by'].append(parent_id)
            parent['blocks'].append(child_id)
            child['updated_at'] = time.time()
            parent['updated_at'] = time.time()

            txn.put(child_id.encode(), self._serialize(child), db=self.todos_db)
            txn.put(parent_id.encode(), self._serialize(parent), db=self.todos_db)

            return EditResult(
                success=True, todo_id=child_id,
                message=f"Dependency added: {child_id} blocked by {parent_id}"
            )

    def remove_dependency(self, child_id: str, parent_id: str, agent_id: str = "system") -> EditResult:
        """Remove dependency: child no longer blocked by parent."""
        with self.env.begin(write=True) as txn:
            child_data = txn.get(child_id.encode(), db=self.todos_db)
            parent_data = txn.get(parent_id.encode(), db=self.todos_db)

            if not child_data:
                return EditResult(success=False, todo_id=child_id, message=f"Child {child_id} not found")
            if not parent_data:
                return EditResult(success=False, todo_id=child_id, message=f"Parent {parent_id} not found")

            child = self._deserialize(child_data)
            parent = self._deserialize(parent_data)

            if parent_id not in child.get('blocked_by', []):
                return EditResult(
                    success=False, todo_id=child_id,
                    message=f"No dependency: {child_id} is not blocked by {parent_id}"
                )

            child['blocked_by'] = [b for b in child['blocked_by'] if b != parent_id]
            parent['blocks'] = [b for b in parent['blocks'] if b != child_id]
            child['updated_at'] = time.time()
            parent['updated_at'] = time.time()

            txn.put(child_id.encode(), self._serialize(child), db=self.todos_db)
            txn.put(parent_id.encode(), self._serialize(parent), db=self.todos_db)

            return EditResult(
                success=True, todo_id=child_id,
                message=f"Dependency removed: {child_id} no longer blocked by {parent_id}"
            )

    def _check_cycle(self, txn, child_id: str, potential_parent_id: str) -> bool:
        """Check if adding child->parent dependency creates a cycle via DFS."""
        visited = set()
        stack = [potential_parent_id]

        while stack:
            current = stack.pop()
            if current == child_id:
                return True  # Cycle!
            if current in visited:
                continue
            visited.add(current)

            # Follow blocked_by edges from current
            data = txn.get(current.encode(), db=self.todos_db)
            if data:
                todo = self._deserialize(data)
                # If current is blocked by X, then X -> current in the dep graph
                # We need to check: does parent_id eventually depend on child_id?
                # So we traverse "blocks" edges (who does current block?)
                # Actually: we check if child_id is reachable from parent_id
                # via blocked_by edges. parent_id.blocked_by -> ... -> child_id?
                for blocker_id in todo.get('blocked_by', []):
                    if blocker_id not in visited:
                        stack.append(blocker_id)

        return False

    def get_dependency_tree(self, todo_id: str) -> Optional[Dict]:
        """Get dependency tree for a todo."""
        with self.env.begin() as txn:
            return self._build_dep_tree(txn, todo_id, set())

    def _build_dep_tree(self, txn, todo_id: str, visited: set) -> Optional[Dict]:
        """Recursively build dependency tree."""
        if todo_id in visited:
            return {'id': todo_id, 'title': '(cycle)', 'status': '?', 'deps': []}

        visited.add(todo_id)
        data = txn.get(todo_id.encode(), db=self.todos_db)
        if not data:
            return None

        todo = self._deserialize(data)
        node = {
            'id': todo['id'],
            'title': todo['title'],
            'status': todo['status'],
            'priority': todo['priority'],
            'assignee': todo.get('assignee'),
            'deps': [],
        }

        for blocker_id in todo.get('blocked_by', []):
            dep = self._build_dep_tree(txn, blocker_id, visited)
            if dep:
                node['deps'].append(dep)

        return node

    # =========================================================================
    # NIWA INTEGRATION
    # =========================================================================

    def link_to_niwa(self, todo_id: str, niwa_node_id: str, agent_id: str = "system") -> EditResult:
        """Link a todo to a niwa node."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if niwa_node_id in todo.get('niwa_refs', []):
                return EditResult(
                    success=False, todo_id=todo_id,
                    message=f"Already linked to {niwa_node_id}"
                )

            todo['niwa_refs'].append(niwa_node_id)
            todo['updated_at'] = time.time()
            txn.put(todo_id.encode(), self._serialize(todo), db=self.todos_db)

            return EditResult(
                success=True, todo_id=todo_id,
                message=f"Linked {todo_id} to niwa node {niwa_node_id}"
            )

    def unlink_from_niwa(self, todo_id: str, niwa_node_id: str, agent_id: str = "system") -> EditResult:
        """Unlink a todo from a niwa node."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if niwa_node_id not in todo.get('niwa_refs', []):
                return EditResult(
                    success=False, todo_id=todo_id,
                    message=f"Not linked to {niwa_node_id}"
                )

            todo['niwa_refs'] = [r for r in todo['niwa_refs'] if r != niwa_node_id]
            todo['updated_at'] = time.time()
            txn.put(todo_id.encode(), self._serialize(todo), db=self.todos_db)

            return EditResult(
                success=True, todo_id=todo_id,
                message=f"Unlinked {todo_id} from niwa node {niwa_node_id}"
            )

    def get_todos_for_niwa_node(self, niwa_node_id: str) -> List[Dict]:
        """Get all todos linked to a niwa node."""
        results = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                if niwa_node_id in todo.get('niwa_refs', []):
                    results.append(todo)
        return results

    # =========================================================================
    # LABELS
    # =========================================================================

    def add_label(self, todo_id: str, label: str, agent_id: str = "system") -> EditResult:
        """Add a label to a todo."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if label in todo.get('labels', []):
                return EditResult(success=False, todo_id=todo_id, message=f"Label '{label}' already exists")

            todo['labels'].append(label)
            todo['updated_at'] = time.time()
            txn.put(todo_id.encode(), self._serialize(todo), db=self.todos_db)

            return EditResult(success=True, todo_id=todo_id, message=f"Added label '{label}'")

    def remove_label(self, todo_id: str, label: str, agent_id: str = "system") -> EditResult:
        """Remove a label from a todo."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)
            if label not in todo.get('labels', []):
                return EditResult(success=False, todo_id=todo_id, message=f"Label '{label}' not found")

            todo['labels'] = [l for l in todo['labels'] if l != label]
            todo['updated_at'] = time.time()
            txn.put(todo_id.encode(), self._serialize(todo), db=self.todos_db)

            return EditResult(success=True, todo_id=todo_id, message=f"Removed label '{label}'")

    # =========================================================================
    # CONFLICT RESOLUTION
    # =========================================================================

    def resolve_conflict(
        self,
        todo_id: str,
        resolution: str,
        agent_id: str,
        manual_changes: Optional[Dict] = None,
        conflict: Optional[ConflictAnalysis] = None,
    ) -> EditResult:
        """Resolve a conflict."""
        with self.env.begin(write=True) as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return EditResult(success=False, todo_id=todo_id, message="Todo not found")

            todo = self._deserialize(todo_data)

            if resolution == "ACCEPT_YOURS":
                if not conflict:
                    return EditResult(success=False, todo_id=todo_id, message="Need conflict object for ACCEPT_YOURS")
                changes = {k: v for k, (_, v) in conflict.your_changes.items()}
                return self._apply_update(txn, todo, changes, agent_id, f"Conflict resolved: accepted {agent_id}'s version")

            elif resolution == "ACCEPT_THEIRS":
                return EditResult(
                    success=True,
                    todo_id=todo_id,
                    new_version=todo['version'],
                    message="Conflict resolved: kept current version"
                )

            elif resolution == "MANUAL_MERGE":
                if not manual_changes:
                    return EditResult(success=False, todo_id=todo_id, message="Manual changes required for MANUAL_MERGE")
                return self._apply_update(txn, todo, manual_changes, agent_id, f"Conflict resolved: manual merge by {agent_id}")

            else:
                return EditResult(success=False, todo_id=todo_id, message=f"Unknown resolution: {resolution}")

    def store_conflict(self, agent_id: str, conflict: ConflictAnalysis):
        """Store a conflict for later resolution."""
        with self.env.begin(write=True) as txn:
            conflict_key = f"conflicts:{agent_id}".encode()
            existing = txn.get(conflict_key, db=self.meta_db)
            conflicts = self._deserialize(existing) if existing else []

            conflicts = [c for c in conflicts if c.get('todo_id') != conflict.todo_id]
            conflicts.append({
                'todo_id': conflict.todo_id,
                'todo_title': conflict.todo_title,
                'your_base_version': conflict.your_base_version,
                'current_version': conflict.current_version,
                'your_changes': {k: list(v) for k, v in conflict.your_changes.items()},
                'their_changes': {k: list(v) for k, v in conflict.their_changes.items()},
                'overlapping_fields': conflict.overlapping_fields,
                'auto_merge_possible': conflict.auto_merge_possible,
                'stored_at': time.time(),
            })

            txn.put(conflict_key, self._serialize(conflicts), db=self.meta_db)

    def get_pending_conflicts(self, agent_id: Optional[str] = None) -> List[Dict]:
        """Get all pending conflicts."""
        conflicts = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.meta_db)
            for key, value in cursor:
                key_str = key.decode()
                if key_str.startswith('conflicts:'):
                    agent = key_str.split(':', 1)[1]
                    if agent_id is None or agent == agent_id:
                        agent_conflicts = self._deserialize(value)
                        for c in agent_conflicts:
                            c['agent_id'] = agent
                            conflicts.append(c)
        return conflicts

    def clear_conflict(self, agent_id: str, todo_id: str):
        """Clear a resolved conflict."""
        with self.env.begin(write=True) as txn:
            conflict_key = f"conflicts:{agent_id}".encode()
            existing = txn.get(conflict_key, db=self.meta_db)
            if existing:
                conflicts = self._deserialize(existing)
                conflicts = [c for c in conflicts if c.get('todo_id') != todo_id]
                if conflicts:
                    txn.put(conflict_key, self._serialize(conflicts), db=self.meta_db)
                else:
                    txn.delete(conflict_key, db=self.meta_db)

    # =========================================================================
    # AGENT STATUS
    # =========================================================================

    def get_agent_status(self, agent_id: str) -> Dict:
        """Get comprehensive status for an agent."""
        status = {
            'agent_id': agent_id,
            'assigned_todos': [],
            'created_todos': [],
            'pending_conflicts': [],
            'recent_edits': [],
        }

        with self.env.begin() as txn:
            # Scan todos for assignments and creations
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                if todo.get('assignee') == agent_id:
                    status['assigned_todos'].append({
                        'id': todo['id'],
                        'title': todo['title'],
                        'status': todo['status'],
                        'priority': todo['priority'],
                    })
                if todo.get('created_by') == agent_id:
                    status['created_todos'].append({
                        'id': todo['id'],
                        'title': todo['title'],
                        'status': todo['status'],
                    })

                for edit in todo.get('edit_history', []):
                    if edit.get('agent') == agent_id and edit.get('timestamp', 0) > time.time() - 3600:
                        status['recent_edits'].append({
                            'todo_id': todo['id'],
                            'version': edit['version'],
                            'timestamp': edit['timestamp'],
                            'summary': edit.get('summary'),
                        })

            # Check conflicts
            conflict_key = f"conflicts:{agent_id}".encode()
            conflict_data = txn.get(conflict_key, db=self.meta_db)
            if conflict_data:
                status['pending_conflicts'] = self._deserialize(conflict_data)

        status['recent_edits'].sort(key=lambda x: x['timestamp'], reverse=True)
        return status

    def list_all_agents(self) -> List[Dict]:
        """List all agents that have interacted with this database."""
        agents = {}
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                for edit in todo.get('edit_history', []):
                    agent = edit.get('agent', 'unknown')
                    if agent not in agents:
                        agents[agent] = {
                            'agent_id': agent,
                            'edit_count': 0,
                            'todos_touched': set(),
                            'first_seen': edit.get('timestamp'),
                            'last_seen': edit.get('timestamp'),
                        }
                    agents[agent]['edit_count'] += 1
                    agents[agent]['todos_touched'].add(todo['id'])
                    ts = edit.get('timestamp')
                    if ts:
                        if ts < agents[agent]['first_seen']:
                            agents[agent]['first_seen'] = ts
                        if ts > agents[agent]['last_seen']:
                            agents[agent]['last_seen'] = ts

        for agent in agents.values():
            agent['todos_touched'] = list(agent['todos_touched'])

        return list(agents.values())

    def validate_agent_name(self, agent_id: str) -> Tuple[bool, str]:
        """Validate agent name."""
        if not agent_id:
            return False, "Agent name cannot be empty"
        if len(agent_id) > 50:
            return False, "Agent name too long (max 50 chars)"
        if agent_id == "default_agent":
            return False, "Please specify a unique agent name with --agent"
        if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
            return False, "Agent name can only contain letters, numbers, underscore, hyphen"
        return True, "OK"

    # =========================================================================
    # SEARCH & EXPORT
    # =========================================================================

    def search_todos(self, query: str, case_sensitive: bool = False) -> List[Dict]:
        """Full-text search across title, description, labels."""
        results = []
        if not case_sensitive:
            query = query.lower()

        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                title = todo.get('title', '')
                description = todo.get('description', '')
                labels = ' '.join(todo.get('labels', []))

                search_text = f"{title} {description} {labels}"
                if not case_sensitive:
                    search_text = search_text.lower()

                if query in search_text:
                    results.append(todo)

        return results

    def export_jsonl(self, output_path: Optional[str] = None) -> str:
        """Export all todos as JSONL."""
        lines = []
        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                lines.append(json.dumps(todo, default=str))

        content = '\n'.join(lines) + '\n' if lines else ''

        if output_path:
            with open(output_path, 'w') as f:
                f.write(content)
            return f"Exported {len(lines)} todos to {output_path}"
        return content

    def get_todo_history(self, todo_id: str) -> List[Dict]:
        """Get version history for a todo."""
        history = []
        with self.env.begin() as txn:
            todo_data = txn.get(todo_id.encode(), db=self.todos_db)
            if not todo_data:
                return []

            todo = self._deserialize(todo_data)
            for entry in todo.get('edit_history', []):
                hist = {
                    'version': entry.get('version'),
                    'agent': entry.get('agent'),
                    'timestamp': entry.get('timestamp'),
                    'summary': entry.get('summary'),
                    'changes': entry.get('changes', {}),
                }

                # Check history DB for full snapshot
                history_key = f"{todo_id}:v{entry.get('version')}".encode()
                history_data = txn.get(history_key, db=self.history_db)
                hist['has_snapshot'] = history_data is not None

                history.append(hist)

        return sorted(history, key=lambda x: x.get('version', 0), reverse=True)

    def get_db_stats(self) -> Dict:
        """Get database statistics."""
        stats = {
            'total': 0,
            'by_status': {},
            'by_priority': {},
            'by_type': {},
            'pending_conflicts': 0,
        }

        with self.env.begin() as txn:
            cursor = txn.cursor(db=self.todos_db)
            for key, value in cursor:
                todo = self._deserialize(value)
                stats['total'] += 1
                s = todo['status']
                stats['by_status'][s] = stats['by_status'].get(s, 0) + 1
                p = self.PRIORITY_NAMES.get(todo['priority'], str(todo['priority']))
                stats['by_priority'][p] = stats['by_priority'].get(p, 0) + 1
                t = todo['type']
                stats['by_type'][t] = stats['by_type'].get(t, 0) + 1

            cursor = txn.cursor(db=self.meta_db)
            for key, value in cursor:
                if key.decode().startswith('conflicts:'):
                    conflicts = self._deserialize(value)
                    stats['pending_conflicts'] += len(conflicts)

        return stats
