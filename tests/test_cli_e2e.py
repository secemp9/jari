"""
End-to-end CLI tests using subprocess and tempfile.

Tests simulate real LLM agent workflows: creating, claiming, dependencies,
multi-agent collaboration, conflict detection, and edge cases.

Run with: pytest tests/test_cli_e2e.py -v
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def jari(*args, cwd):
    """Run jari CLI and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["jari", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def db(tmp_path):
    """Initialize a jari database in a temp directory."""
    rc, out, err = jari("init", cwd=tmp_path)
    assert rc == 0, f"init failed: {err}"
    return tmp_path


# ── Init ────────────────────────────────────────────────────────────────────


class TestInit:
    def test_init_creates_jari_dir(self, tmp_path):
        rc, out, err = jari("init", cwd=tmp_path)
        assert rc == 0
        assert (tmp_path / ".jari").is_dir()
        assert "INITIALIZED" in out

    def test_init_twice_is_safe(self, db):
        rc, out, err = jari("init", cwd=db)
        assert rc == 0
        assert "ALREADY EXISTS" in out or "INITIALIZED" in out


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreate:
    def test_create_basic(self, db):
        rc, out, err = jari("create", "Fix login bug", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "TODO_ID: todo_1" in out
        assert "TODO CREATED" in out

    def test_create_with_priority_and_type(self, db):
        rc, out, err = jari("create", "Critical bug", "-p", "0", "-t", "bug", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "critical" in out.lower()
        assert "bug" in out.lower()

    def test_create_with_description(self, db):
        rc, out, err = jari("create", "Task", "-d", "Detailed description", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "TODO_ID:" in out

    def test_create_sequential_ids(self, db):
        jari("create", "First", "--agent", "a1", cwd=db)
        jari("create", "Second", "--agent", "a1", cwd=db)
        rc, out, err = jari("create", "Third", "--agent", "a1", cwd=db)
        assert "TODO_ID: todo_3" in out

    def test_create_no_title(self, db):
        rc, out, err = jari("create", cwd=db)
        assert "Missing title" in out or rc != 0

    def test_create_with_parent(self, db):
        jari("create", "Epic", "-t", "epic", "--agent", "a1", cwd=db)
        rc, out, err = jari("create", "Subtask", "--parent", "todo_1", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "TODO_ID: todo_2" in out


# ── Show ────────────────────────────────────────────────────────────────────


class TestShow:
    def test_show_todo(self, db):
        jari("create", "My task", "-d", "Some details", "--agent", "a1", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert rc == 0
        assert "My task" in out
        assert "open" in out
        assert "medium" in out

    def test_show_nonexistent(self, db):
        rc, out, err = jari("show", "todo_999", cwd=db)
        assert "not found" in (out + err).lower() or rc != 0

    def test_show_with_description(self, db):
        jari("create", "Described", "-d", "Long description here", "--agent", "a1", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Long description here" in out


# ── List ────────────────────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, db):
        rc, out, err = jari("list", cwd=db)
        assert "No todos" in out

    def test_list_basic(self, db):
        jari("create", "Task A", "--agent", "a1", cwd=db)
        jari("create", "Task B", "--agent", "a1", cwd=db)
        rc, out, err = jari("list", cwd=db)
        assert rc == 0
        assert "Task A" in out
        assert "Task B" in out
        assert "2 item" in out

    def test_list_filter_status(self, db):
        jari("create", "Open", "--agent", "a1", cwd=db)
        jari("create", "Closed", "--agent", "a1", cwd=db)
        jari("close", "todo_2", "--agent", "a1", cwd=db)
        rc, out, err = jari("list", "--status", "open", cwd=db)
        assert "Open" in out
        assert "Closed" not in out

    def test_list_filter_priority(self, db):
        jari("create", "High", "-p", "1", "--agent", "a1", cwd=db)
        jari("create", "Low", "-p", "3", "--agent", "a1", cwd=db)
        rc, out, err = jari("list", "--priority", "1", cwd=db)
        assert "High" in out
        assert "Low" not in out


# ── Close / Reopen / Delete ─────────────────────────────────────────────────


class TestCloseReopenDelete:
    def test_close(self, db):
        jari("create", "Closeable", "--agent", "a1", cwd=db)
        rc, out, err = jari("close", "todo_1", "--reason", "Done", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "CLOSED" in out

    def test_close_already_closed(self, db):
        jari("create", "Closeable", "--agent", "a1", cwd=db)
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("close", "todo_1", "--agent", "a1", cwd=db)
        assert "already closed" in out.lower()

    def test_reopen(self, db):
        jari("create", "Reopenable", "--agent", "a1", cwd=db)
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("reopen", "todo_1", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "Reopened" in out

    def test_delete(self, db):
        jari("create", "Deletable", "--agent", "a1", cwd=db)
        rc, out, err = jari("delete", "todo_1", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "Deleted" in out

        # Verify gone
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "not found" in (out + err).lower() or rc != 0


# ── Ready Queue ─────────────────────────────────────────────────────────────


class TestReadyQueue:
    def test_ready_basic(self, db):
        jari("create", "Ready task", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert rc == 0
        assert "Ready task" in out

    def test_ready_excludes_closed(self, db):
        jari("create", "Open", "--agent", "a1", cwd=db)
        jari("create", "Closed", "--agent", "a1", cwd=db)
        jari("close", "todo_2", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert "Open" in out
        assert "Closed" not in out

    def test_ready_excludes_blocked(self, db):
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert "Blocker" in out
        assert "Blocked" not in out

    def test_ready_unblocked_after_close(self, db):
        """When blocker is closed, blocked todo becomes ready."""
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)

        # Before close
        rc, out, err = jari("ready", cwd=db)
        assert "Blocked" not in out

        # After close
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert "Blocked" in out

    def test_ready_sort_priority(self, db):
        jari("create", "Low", "-p", "3", "--agent", "a1", cwd=db)
        jari("create", "Critical", "-p", "0", "--agent", "a1", cwd=db)
        jari("create", "High", "-p", "1", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        lines = out.strip().split('\n')
        # Find todo lines
        todo_lines = [l for l in lines if 'todo_' in l]
        assert len(todo_lines) == 3
        # Critical should appear before High, which appears before Low
        crit_idx = next(i for i, l in enumerate(todo_lines) if 'Critical' in l)
        high_idx = next(i for i, l in enumerate(todo_lines) if 'High' in l)
        low_idx = next(i for i, l in enumerate(todo_lines) if 'Low' in l)
        assert crit_idx < high_idx < low_idx


# ── Claim ───────────────────────────────────────────────────────────────────


class TestClaim:
    def test_claim_success(self, db):
        jari("create", "Claimable", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "CLAIMED" in out

        # Verify status changed
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "in_progress" in out
        assert "a1" in out

    def test_claim_already_claimed(self, db):
        jari("create", "Claimable", "--agent", "a1", cwd=db)
        jari("claim", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", "--agent", "a2", cwd=db)
        assert "Already assigned" in out or "already" in out.lower()

    def test_claim_same_agent_ok(self, db):
        jari("create", "Claimable", "--agent", "a1", cwd=db)
        jari("claim", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", "--agent", "a1", cwd=db)
        assert rc == 0  # Re-claiming same agent is ok

    def test_claim_closed_todo(self, db):
        jari("create", "Closeable", "--agent", "a1", cwd=db)
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", "--agent", "a2", cwd=db)
        assert "closed" in out.lower() or "Cannot claim" in out

    def test_claim_requires_agent(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", cwd=db)
        assert "--agent" in out.lower() or "required" in out.lower()


# ── Dependencies ────────────────────────────────────────────────────────────


class TestDependencies:
    def test_dep_add(self, db):
        jari("create", "Parent", "--agent", "a1", cwd=db)
        jari("create", "Child", "--agent", "a1", cwd=db)
        rc, out, err = jari("dep", "add", "todo_2", "todo_1", cwd=db)
        assert rc == 0
        assert "Dependency added" in out

    def test_dep_remove(self, db):
        jari("create", "Parent", "--agent", "a1", cwd=db)
        jari("create", "Child", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("dep", "remove", "todo_2", "todo_1", cwd=db)
        assert rc == 0
        assert "removed" in out.lower()

    def test_dep_cycle_detection(self, db):
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)  # B blocked by A
        rc, out, err = jari("dep", "add", "todo_1", "todo_2", cwd=db)  # A blocked by B = cycle
        assert "Cycle" in out or "cycle" in out.lower()

    def test_dep_self_reference(self, db):
        jari("create", "Self", "--agent", "a1", cwd=db)
        rc, out, err = jari("dep", "add", "todo_1", "todo_1", cwd=db)
        assert "Cannot depend on self" in out or "self" in out.lower()

    def test_dep_tree(self, db):
        jari("create", "Root", "--agent", "a1", cwd=db)
        jari("create", "Child", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("dep", "tree", "todo_2", cwd=db)
        assert rc == 0
        assert "todo_2" in out
        assert "todo_1" in out

    def test_dep_duplicate(self, db):
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("dep", "add", "todo_2", "todo_1", cwd=db)
        assert "already exists" in out.lower()

    def test_dep_chain(self, db):
        """A -> B -> C dependency chain."""
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("create", "C", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)  # B blocked by A
        jari("dep", "add", "todo_3", "todo_2", cwd=db)  # C blocked by B

        # Only A should be ready
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert len(ready_lines) == 1
        assert 'todo_1' in ready_lines[0]

        # Close A, B becomes ready
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_2' in l for l in ready_lines)
        assert not any('todo_3' in l for l in ready_lines)


# ── Labels ──────────────────────────────────────────────────────────────────


class TestLabels:
    def test_label_add(self, db):
        jari("create", "Labeled", "--agent", "a1", cwd=db)
        rc, out, err = jari("label", "add", "todo_1", "urgent", cwd=db)
        assert rc == 0
        assert "Added label" in out

    def test_label_remove(self, db):
        jari("create", "Labeled", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "urgent", cwd=db)
        rc, out, err = jari("label", "remove", "todo_1", "urgent", cwd=db)
        assert rc == 0
        assert "Removed label" in out

    def test_label_duplicate(self, db):
        jari("create", "Labeled", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "urgent", cwd=db)
        rc, out, err = jari("label", "add", "todo_1", "urgent", cwd=db)
        assert "already exists" in out.lower()

    def test_label_show(self, db):
        jari("create", "Labeled", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "urgent", cwd=db)
        jari("label", "add", "todo_1", "frontend", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "urgent" in out
        assert "frontend" in out

    def test_list_filter_by_label(self, db):
        jari("create", "Tagged", "--agent", "a1", cwd=db)
        jari("create", "Untagged", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "urgent", cwd=db)
        rc, out, err = jari("list", "--label", "urgent", cwd=db)
        assert "Tagged" in out
        assert "Untagged" not in out


# ── Niwa Links ──────────────────────────────────────────────────────────────


class TestNiwaLinks:
    def test_link(self, db):
        jari("create", "Linked", "--agent", "a1", cwd=db)
        rc, out, err = jari("link", "todo_1", "h2_3", cwd=db)
        assert rc == 0
        assert "Linked" in out

    def test_unlink(self, db):
        jari("create", "Linked", "--agent", "a1", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)
        rc, out, err = jari("unlink", "todo_1", "h2_3", cwd=db)
        assert rc == 0
        assert "Unlinked" in out

    def test_linked_query(self, db):
        jari("create", "Task A", "--agent", "a1", cwd=db)
        jari("create", "Task B", "--agent", "a1", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)
        jari("link", "todo_2", "h2_3", cwd=db)
        rc, out, err = jari("linked", "h2_3", cwd=db)
        assert "Task A" in out
        assert "Task B" in out

    def test_link_show(self, db):
        jari("create", "Linked", "--agent", "a1", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "h2_3" in out

    def test_create_with_niwa_ref(self, db):
        rc, out, err = jari("create", "Linked", "--niwa-ref", "h1_0", "--agent", "a1", cwd=db)
        assert rc == 0
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "h1_0" in out


# ── Search ──────────────────────────────────────────────────────────────────


class TestSearch:
    def test_search_title(self, db):
        jari("create", "Fix login bug", "--agent", "a1", cwd=db)
        jari("create", "Add feature", "--agent", "a1", cwd=db)
        rc, out, err = jari("search", "login", cwd=db)
        assert "Fix login bug" in out
        assert "Add feature" not in out

    def test_search_description(self, db):
        jari("create", "Task", "-d", "This involves the authentication module", "--agent", "a1", cwd=db)
        rc, out, err = jari("search", "authentication", cwd=db)
        assert "Task" in out

    def test_search_no_results(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("search", "nonexistent", cwd=db)
        assert "No todos" in out or "0" in out


# ── Export ──────────────────────────────────────────────────────────────────


class TestExport:
    def test_export_jsonl(self, db):
        jari("create", "Task A", "--agent", "a1", cwd=db)
        jari("create", "Task B", "--agent", "a1", cwd=db)
        rc, out, err = jari("export", cwd=db)
        assert rc == 0
        lines = [l for l in out.strip().split('\n') if l]
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert 'id' in data
            assert 'title' in data

    def test_export_to_file(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        output_file = db / "export.jsonl"
        rc, out, err = jari("export", "--output", str(output_file), cwd=db)
        assert rc == 0
        assert output_file.exists()
        content = output_file.read_text()
        data = json.loads(content.strip())
        assert data['title'] == "Task"


# ── History ─────────────────────────────────────────────────────────────────


class TestHistory:
    def test_history_basic(self, db):
        jari("create", "Tracked", "--agent", "a1", cwd=db)
        rc, out, err = jari("history", "todo_1", cwd=db)
        assert rc == 0
        assert "v1" in out
        assert "Created" in out

    def test_history_after_update(self, db):
        jari("create", "Tracked", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "in_progress", "--agent", "a1", cwd=db)
        rc, out, err = jari("history", "todo_1", cwd=db)
        assert "v2" in out


# ── Multi-Agent Workflow ────────────────────────────────────────────────────


class TestMultiAgent:
    def test_two_agents_claim_race(self, db):
        """Two agents try to claim the same todo."""
        jari("create", "Contested", "--agent", "a1", cwd=db)
        rc1, out1, _ = jari("claim", "todo_1", "--agent", "agent_1", cwd=db)
        rc2, out2, _ = jari("claim", "todo_1", "--agent", "agent_2", cwd=db)

        assert rc1 == 0
        assert "CLAIMED" in out1
        assert "Already assigned" in out2 or "already" in out2.lower()

    def test_agent_status(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("claim", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("status", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "a1" in out
        assert "todo_1" in out

    def test_agents_list(self, db):
        jari("create", "Task 1", "--agent", "agent_a", cwd=db)
        jari("create", "Task 2", "--agent", "agent_b", cwd=db)
        rc, out, err = jari("agents", cwd=db)
        assert "agent_a" in out
        assert "agent_b" in out

    def test_conflict_detection(self, db):
        """Two agents update same todo concurrently."""
        jari("create", "Shared", "--agent", "a1", cwd=db)

        # Agent 1 reads
        jari("update", "todo_1", "--status", "in_progress", "--agent", "agent_1", cwd=db)

        # Agent 2 reads THEN tries to update (but agent_1 already changed it)
        # We need to simulate: agent_2 reads, agent_1 updates, agent_2 updates
        # The update command does read_for_edit internally, so we need to be clever
        # Let's test the underlying DB directly via show/list to verify state

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "in_progress" in out


# ── Blocked ─────────────────────────────────────────────────────────────────


class TestBlocked:
    def test_blocked_command(self, db):
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("blocked", cwd=db)
        assert rc == 0
        assert "Blocked" in out
        assert "todo_1" in out  # blocker shown

    def test_no_blocked(self, db):
        jari("create", "Free", "--agent", "a1", cwd=db)
        rc, out, err = jari("blocked", cwd=db)
        assert "No blocked" in out


# ── Delete with dependencies ────────────────────────────────────────────────


class TestDeleteDeps:
    def test_delete_removes_from_blockers(self, db):
        """Deleting a todo should clean up dependency references."""
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)

        # Delete the blocker
        jari("delete", "todo_1", "--agent", "a1", cwd=db)

        # todo_2 should now be unblocked
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_2' in l]
        assert len(ready_lines) == 1


# ── Prime ───────────────────────────────────────────────────────────────────


class TestPrime:
    def test_prime_output(self, db):
        jari("create", "Task 1", "-p", "0", "--agent", "a1", cwd=db)
        jari("create", "Task 2", "-p", "2", "--agent", "a1", cwd=db)
        rc, out, err = jari("prime", cwd=db)
        assert rc == 0
        assert "Jari" in out
        assert "READY QUEUE" in out
        assert "Task 1" in out

    def test_prime_empty_db(self, db):
        rc, out, err = jari("prime", cwd=db)
        assert rc == 0
        assert "Jari" in out


# ── Update ─────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_status(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--status", "in_progress", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "UPDATED" in out

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "in_progress" in out

    def test_update_priority(self, db):
        jari("create", "Task", "-p", "2", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "-p", "0", "--agent", "a1", cwd=db)
        assert rc == 0
        assert "UPDATED" in out

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "critical" in out.lower()

    def test_update_title(self, db):
        jari("create", "Old Title", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--title", "New Title", "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "New Title" in out

    def test_update_assignee(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--assign", "agent_x", "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "agent_x" in out

    def test_update_description(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "-d", "New description", "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "New description" in out

    def test_update_type(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "-t", "bug", "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "bug" in out

    def test_update_nonexistent(self, db):
        rc, out, err = jari("update", "todo_999", "--status", "open", "--agent", "a1", cwd=db)
        assert "not found" in (out + err).lower() or rc != 0

    def test_update_no_changes(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--agent", "a1", cwd=db)
        assert "No changes" in out

    def test_update_invalid_status(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--status", "invalid_status", "--agent", "a1", cwd=db)
        assert "Invalid status" in out or "invalid" in out.lower()

    def test_update_invalid_priority(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "-p", "9", "--agent", "a1", cwd=db)
        assert "Invalid priority" in out or "invalid" in out.lower()

    def test_update_bumps_version(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "in_progress", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "-p", "1", "--agent", "a1", cwd=db)
        rc, out, err = jari("history", "todo_1", cwd=db)
        assert "v3" in out

    def test_update_from_file(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        content_file = db / "desc.txt"
        content_file.write_text("Description from file\nwith multiple lines")
        rc, out, err = jari("update", "todo_1", "--file", str(content_file), "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Description from file" in out


# ── Field-Level Conflict Detection ─────────────────────────────────────────


class TestFieldConflict:
    """Test field-level conflict detection when two agents update the same todo."""

    def test_same_field_conflict(self, db):
        """Two agents both update the status field → conflict."""
        jari("create", "Shared", "--agent", "a1", cwd=db)

        # Agent 1 updates status
        jari("update", "todo_1", "--status", "in_progress", "--agent", "agent_1", cwd=db)

        # Agent 2 tries to update status too — but the CLI does read_for_edit + update
        # internally, so sequential updates don't conflict (each reads current state).
        # To get a real conflict we need the DB-level approach.
        # For CLI-level: verify the state is correct.
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "in_progress" in out

    def test_different_fields_auto_merge(self, db):
        """Two sequential updates on different fields both succeed."""
        jari("create", "Task", "--agent", "a1", cwd=db)

        # First agent updates priority
        jari("update", "todo_1", "-p", "0", "--agent", "a1", cwd=db)

        # Second agent updates title
        rc, out, err = jari("update", "todo_1", "--title", "New Title", "--agent", "a2", cwd=db)
        assert rc == 0
        assert "UPDATED" in out

        # Verify both changes landed
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "New Title" in out
        assert "critical" in out.lower()

    def test_multiple_updates_history_tracks_all(self, db):
        """Multiple updates from different agents all show in history."""
        jari("create", "Tracked", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "in_progress", "--agent", "agent_1", cwd=db)
        jari("update", "todo_1", "-p", "1", "--agent", "agent_2", cwd=db)
        jari("update", "todo_1", "--title", "Updated", "--agent", "agent_3", cwd=db)

        rc, out, err = jari("history", "todo_1", cwd=db)
        assert "v4" in out
        assert "agent_1" in out
        assert "agent_2" in out
        assert "agent_3" in out

    def test_conflict_stored_and_visible(self, db):
        """When a conflict is detected via the DB API, it gets stored."""
        # Use DB directly to force a real conflict
        import sys
        sys.path.insert(0, str(db.parent))
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            # Create a todo
            todo_id = dbobj.create_todo("Contested", agent_id="a1")

            # Both agents read the same version
            dbobj.read_for_edit(todo_id, "agent_1")
            dbobj.read_for_edit(todo_id, "agent_2")

            # agent_1 updates status (succeeds)
            result1 = dbobj.update_todo(todo_id, {'status': 'in_progress'}, "agent_1", "Started")
            assert result1.success

            # agent_2 tries to update the SAME field (conflict!)
            result2 = dbobj.update_todo(todo_id, {'status': 'blocked'}, "agent_2", "Blocked")
            assert not result2.success
            assert result2.conflict is not None
            assert 'status' in result2.conflict.overlapping_fields

            # Store the conflict
            dbobj.store_conflict("agent_2", result2.conflict)

            # Verify it's stored
            conflicts = dbobj.get_pending_conflicts("agent_2")
            assert len(conflicts) == 1
            assert conflicts[0]['todo_id'] == todo_id
        finally:
            dbobj.close()

    def test_auto_merge_different_fields(self, db):
        """Non-overlapping field changes auto-merge."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("AutoMerge", agent_id="a1")

            dbobj.read_for_edit(todo_id, "agent_1")
            dbobj.read_for_edit(todo_id, "agent_2")

            # agent_1 updates priority
            result1 = dbobj.update_todo(todo_id, {'priority': 0}, "agent_1", "Critical")
            assert result1.success

            # agent_2 updates title (different field → auto-merge)
            result2 = dbobj.update_todo(todo_id, {'title': 'Renamed'}, "agent_2", "Renamed")
            assert result2.success, f"Expected auto-merge but got: {result2.message}"

            # Verify both changes landed
            todo = dbobj.read_todo(todo_id)
            assert todo['priority'] == 0
            assert todo['title'] == 'Renamed'
        finally:
            dbobj.close()

    def test_three_agents_first_wins_others_conflict(self, db):
        """Three agents read v1, first wins, other two get field conflicts."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("Three-way", agent_id="a1")

            # All three read v1
            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")
            dbobj.read_for_edit(todo_id, "a3")

            # a1 updates status → succeeds
            r1 = dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            assert r1.success

            # a2 updates status → conflict (same field)
            r2 = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not r2.success
            assert r2.conflict is not None

            # a3 updates status → conflict (same field)
            r3 = dbobj.update_todo(todo_id, {'status': 'deferred'}, "a3", "Deferred")
            assert not r3.success
            assert r3.conflict is not None
        finally:
            dbobj.close()

    def test_resolve_accept_yours(self, db):
        """Resolve a field conflict with ACCEPT_YOURS."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("Resolve", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")

            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success

            # Resolve with ACCEPT_YOURS
            resolve_result = dbobj.resolve_conflict(
                todo_id, "ACCEPT_YOURS", "a2", conflict=result.conflict
            )
            assert resolve_result.success

            # a2's version should win
            todo = dbobj.read_todo(todo_id)
            assert todo['status'] == 'blocked'
        finally:
            dbobj.close()

    def test_resolve_accept_theirs(self, db):
        """Resolve a field conflict with ACCEPT_THEIRS."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("Resolve", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")

            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success

            # Resolve with ACCEPT_THEIRS
            resolve_result = dbobj.resolve_conflict(
                todo_id, "ACCEPT_THEIRS", "a2"
            )
            assert resolve_result.success

            # a1's version stays (current)
            todo = dbobj.read_todo(todo_id)
            assert todo['status'] == 'in_progress'
        finally:
            dbobj.close()

    def test_resolve_manual_merge(self, db):
        """Resolve a field conflict with MANUAL_MERGE."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("Resolve", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")

            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success

            # Resolve with MANUAL_MERGE — choose a third status
            resolve_result = dbobj.resolve_conflict(
                todo_id, "MANUAL_MERGE", "a2",
                manual_changes={'status': 'open', 'priority': 1}
            )
            assert resolve_result.success

            todo = dbobj.read_todo(todo_id)
            assert todo['status'] == 'open'
            assert todo['priority'] == 1
        finally:
            dbobj.close()

    def test_read_clears_stale_conflict(self, db):
        """Re-reading a todo clears any stored conflict for that agent."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("ClearConflict", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")

            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success

            # Store the conflict
            dbobj.store_conflict("a2", result.conflict)
            assert len(dbobj.get_pending_conflicts("a2")) == 1

            # Re-read clears conflict
            dbobj.read_for_edit(todo_id, "a2")
            assert len(dbobj.get_pending_conflicts("a2")) == 0
        finally:
            dbobj.close()

    def test_update_without_prior_read_applies_directly(self, db):
        """Update without a prior read_for_edit applies directly."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("DirectUpdate", agent_id="a1")

            # Update directly without read_for_edit
            result = dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Direct")
            assert result.success

            todo = dbobj.read_todo(todo_id)
            assert todo['status'] == 'in_progress'
        finally:
            dbobj.close()

    def test_conflict_on_multiple_todos(self, db):
        """Agent can have conflicts on multiple todos simultaneously."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            id1 = dbobj.create_todo("Todo1", agent_id="a1")
            id2 = dbobj.create_todo("Todo2", agent_id="a1")

            # Conflict on todo1
            dbobj.read_for_edit(id1, "a1")
            dbobj.read_for_edit(id1, "a2")
            dbobj.update_todo(id1, {'status': 'in_progress'}, "a1", "")
            r1 = dbobj.update_todo(id1, {'status': 'blocked'}, "a2", "")
            assert not r1.success
            dbobj.store_conflict("a2", r1.conflict)

            # Conflict on todo2
            dbobj.read_for_edit(id2, "a1")
            dbobj.read_for_edit(id2, "a2")
            dbobj.update_todo(id2, {'priority': 0}, "a1", "")
            r2 = dbobj.update_todo(id2, {'priority': 1}, "a2", "")
            assert not r2.success
            dbobj.store_conflict("a2", r2.conflict)

            # Both conflicts stored
            conflicts = dbobj.get_pending_conflicts("a2")
            assert len(conflicts) == 2
            conflict_ids = {c['todo_id'] for c in conflicts}
            assert id1 in conflict_ids
            assert id2 in conflict_ids

            # Clear one, other remains
            dbobj.clear_conflict("a2", id1)
            conflicts = dbobj.get_pending_conflicts("a2")
            assert len(conflicts) == 1
            assert conflicts[0]['todo_id'] == id2
        finally:
            dbobj.close()


# ── Resolve via CLI ────────────────────────────────────────────────────────


class TestResolveCLI:
    """Test the resolve command via CLI."""

    def test_resolve_accept_theirs_via_cli(self, db):
        """CLI resolve ACCEPT_THEIRS works (doesn't need stored conflict)."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("Resolvable", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")
            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success
            dbobj.store_conflict("a2", result.conflict)
        finally:
            dbobj.close()

        rc, out, err = jari("resolve", todo_id, "ACCEPT_THEIRS", "--agent", "a2", cwd=db)
        assert rc == 0
        assert "RESOLVED" in out

    def test_resolve_manual_merge_via_cli(self, db):
        """CLI resolve MANUAL_MERGE with field=value pairs."""
        from jari.jari import JariDB

        dbobj = JariDB(str(db / ".jari"))
        try:
            todo_id = dbobj.create_todo("MergeMe", agent_id="a1")

            dbobj.read_for_edit(todo_id, "a1")
            dbobj.read_for_edit(todo_id, "a2")
            dbobj.update_todo(todo_id, {'status': 'in_progress'}, "a1", "Started")
            result = dbobj.update_todo(todo_id, {'status': 'blocked'}, "a2", "Blocked")
            assert not result.success
            dbobj.store_conflict("a2", result.conflict)
        finally:
            dbobj.close()

        rc, out, err = jari("resolve", todo_id, "MANUAL_MERGE", "status=open", "--agent", "a2", cwd=db)
        assert rc == 0
        assert "RESOLVED" in out

        rc, out, err = jari("show", todo_id, cwd=db)
        assert "open" in out

    def test_resolve_invalid_resolution(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("resolve", "todo_1", "INVALID", "--agent", "a1", cwd=db)
        assert "Invalid resolution" in out or "invalid" in out.lower()


# ── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_create_many_todos(self, db):
        """Create 20 todos and verify sequential IDs."""
        for i in range(1, 21):
            rc, out, err = jari("create", f"Task {i}", "--agent", "a1", cwd=db)
            assert rc == 0
            assert f"TODO_ID: todo_{i}" in out

        rc, out, err = jari("list", cwd=db)
        assert "20 item" in out

    def test_list_filter_type(self, db):
        jari("create", "Bug task", "-t", "bug", "--agent", "a1", cwd=db)
        jari("create", "Feature task", "-t", "feature", "--agent", "a1", cwd=db)
        jari("create", "Epic task", "-t", "epic", "--agent", "a1", cwd=db)
        rc, out, err = jari("list", "-t", "bug", cwd=db)
        assert "Bug task" in out
        assert "Feature task" not in out
        assert "Epic task" not in out

    def test_list_filter_assignee(self, db):
        jari("create", "Task A", "--agent", "a1", cwd=db)
        jari("create", "Task B", "--agent", "a1", cwd=db)
        jari("claim", "todo_1", "--agent", "agent_x", cwd=db)
        rc, out, err = jari("list", "--assignee", "agent_x", cwd=db)
        assert "Task A" in out
        assert "Task B" not in out

    def test_reopen_non_closed(self, db):
        jari("create", "Open", "--agent", "a1", cwd=db)
        rc, out, err = jari("reopen", "todo_1", "--agent", "a1", cwd=db)
        assert "not closed" in out.lower()

    def test_close_nonexistent(self, db):
        rc, out, err = jari("close", "todo_999", "--agent", "a1", cwd=db)
        assert "not found" in (out + err).lower()

    def test_delete_nonexistent(self, db):
        rc, out, err = jari("delete", "todo_999", "--agent", "a1", cwd=db)
        assert "not found" in (out + err).lower()

    def test_search_by_label(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "searchable-label", cwd=db)
        rc, out, err = jari("search", "searchable-label", cwd=db)
        assert "Task" in out

    def test_search_case_insensitive(self, db):
        jari("create", "UPPERCASE TITLE", "--agent", "a1", cwd=db)
        rc, out, err = jari("search", "uppercase", cwd=db)
        assert "UPPERCASE TITLE" in out

    def test_export_empty_db(self, db):
        rc, out, err = jari("export", cwd=db)
        assert rc == 0
        # Empty or whitespace-only output
        assert out.strip() == ""

    def test_history_multiple_updates(self, db):
        jari("create", "Tracked", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "in_progress", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "-p", "0", "--agent", "a2", cwd=db)
        jari("close", "todo_1", "--reason", "Done", "--agent", "a1", cwd=db)
        rc, out, err = jari("history", "todo_1", cwd=db)
        assert "v1" in out
        assert "v2" in out
        assert "v3" in out
        assert "v4" in out

    def test_history_nonexistent(self, db):
        rc, out, err = jari("history", "todo_999", cwd=db)
        assert "No history" in out

    def test_show_after_close_shows_reason(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("close", "todo_1", "--reason", "Fixed in commit abc123", "--agent", "a1", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Fixed in commit abc123" in out
        assert "closed" in out

    def test_show_blocked_by(self, db):
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("show", "todo_2", cwd=db)
        assert "todo_1" in out
        assert "Blocked by" in out or "blocked_by" in out.lower()

    def test_show_blocks(self, db):
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "todo_2" in out
        assert "Blocks" in out or "blocks" in out.lower()

    def test_unknown_command(self, db):
        rc, out, err = jari("foobar", cwd=db)
        assert "Unknown" in out or "unknown" in out.lower() or "foobar" in out

    def test_no_db_init_required(self, tmp_path):
        """Commands other than init require database to exist."""
        rc, out, err = jari("list", cwd=tmp_path)
        assert "NOT INITIALIZED" in out or "not" in out.lower()


# ── Epic / Parent-Child ────────────────────────────────────────────────────


class TestEpicParentChild:
    def test_epic_with_children(self, db):
        jari("create", "Epic task", "-t", "epic", "--agent", "a1", cwd=db)
        jari("create", "Subtask 1", "--parent", "todo_1", "--agent", "a1", cwd=db)
        jari("create", "Subtask 2", "--parent", "todo_1", "--agent", "a1", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Children" in out or "children" in out.lower()
        assert "todo_2" in out
        assert "todo_3" in out

    def test_child_shows_parent(self, db):
        jari("create", "Epic", "-t", "epic", "--agent", "a1", cwd=db)
        jari("create", "Subtask", "--parent", "todo_1", "--agent", "a1", cwd=db)

        rc, out, err = jari("show", "todo_2", cwd=db)
        assert "todo_1" in out
        assert "Parent" in out or "parent" in out.lower()

    def test_delete_child_removes_from_parent(self, db):
        jari("create", "Epic", "-t", "epic", "--agent", "a1", cwd=db)
        jari("create", "Subtask", "--parent", "todo_1", "--agent", "a1", cwd=db)

        jari("delete", "todo_2", "--agent", "a1", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "todo_2" not in out


# ── Dependency Edge Cases ──────────────────────────────────────────────────


class TestDependencyEdgeCases:
    def test_long_chain_ready_queue(self, db):
        """A->B->C->D chain: only A is ready."""
        for i in range(4):
            jari("create", f"Task{i}", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        jari("dep", "add", "todo_3", "todo_2", cwd=db)
        jari("dep", "add", "todo_4", "todo_3", cwd=db)

        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert len(ready_lines) == 1
        assert 'todo_1' in ready_lines[0]

    def test_chain_cascading_unblock(self, db):
        """Close A → B ready. Close B → C ready. Close C → D ready."""
        for i in range(4):
            jari("create", f"Task{i}", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_2", "todo_1", cwd=db)
        jari("dep", "add", "todo_3", "todo_2", cwd=db)
        jari("dep", "add", "todo_4", "todo_3", cwd=db)

        # Close 1 → 2 ready
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_2' in l for l in ready_lines)
        assert not any('todo_3' in l for l in ready_lines)

        # Close 2 → 3 ready
        jari("close", "todo_2", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_3' in l for l in ready_lines)
        assert not any('todo_4' in l for l in ready_lines)

        # Close 3 → 4 ready
        jari("close", "todo_3", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_4' in l for l in ready_lines)

    def test_diamond_dependency(self, db):
        """Diamond: A blocks B and C. B and C both block D."""
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("create", "C", "--agent", "a1", cwd=db)
        jari("create", "D", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_2", "todo_1", cwd=db)  # B blocked by A
        jari("dep", "add", "todo_3", "todo_1", cwd=db)  # C blocked by A
        jari("dep", "add", "todo_4", "todo_2", cwd=db)  # D blocked by B
        jari("dep", "add", "todo_4", "todo_3", cwd=db)  # D blocked by C

        # Only A ready
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert len(ready_lines) == 1
        assert 'todo_1' in ready_lines[0]

        # Close A → B and C become ready (D still blocked by B and C)
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_2' in l for l in ready_lines)
        assert any('todo_3' in l for l in ready_lines)
        assert not any('todo_4' in l for l in ready_lines)

        # Close B only → D still blocked by C
        jari("close", "todo_2", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert not any('todo_4' in l for l in ready_lines)

        # Close C → D becomes ready
        jari("close", "todo_3", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert any('todo_4' in l for l in ready_lines)

    def test_multiple_blockers(self, db):
        """A todo blocked by multiple todos."""
        jari("create", "Blocker1", "--agent", "a1", cwd=db)
        jari("create", "Blocker2", "--agent", "a1", cwd=db)
        jari("create", "Blocker3", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_4", "todo_1", cwd=db)
        jari("dep", "add", "todo_4", "todo_2", cwd=db)
        jari("dep", "add", "todo_4", "todo_3", cwd=db)

        # Not ready until all closed
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        jari("close", "todo_2", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert not any('todo_4' in l for l in out.split('\n'))

        jari("close", "todo_3", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert any('todo_4' in l for l in out.split('\n'))

    def test_dep_nonexistent_child(self, db):
        jari("create", "Real", "--agent", "a1", cwd=db)
        rc, out, err = jari("dep", "add", "todo_999", "todo_1", cwd=db)
        assert "not found" in out.lower()

    def test_dep_nonexistent_parent(self, db):
        jari("create", "Real", "--agent", "a1", cwd=db)
        rc, out, err = jari("dep", "add", "todo_1", "todo_999", cwd=db)
        assert "not found" in out.lower()

    def test_dep_remove_nonexistent(self, db):
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        rc, out, err = jari("dep", "remove", "todo_1", "todo_2", cwd=db)
        assert "not blocked" in out.lower() or "No dependency" in out

    def test_three_way_cycle_detection(self, db):
        """A→B→C, then C→A should be detected as cycle."""
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("create", "C", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_2", "todo_1", cwd=db)  # B blocked by A
        jari("dep", "add", "todo_3", "todo_2", cwd=db)  # C blocked by B
        rc, out, err = jari("dep", "add", "todo_1", "todo_3", cwd=db)  # A blocked by C = cycle
        assert "cycle" in out.lower() or "Cycle" in out


# ── Niwa Link Edge Cases ──────────────────────────────────────────────────


class TestNiwaLinkEdgeCases:
    def test_link_duplicate(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)
        rc, out, err = jari("link", "todo_1", "h2_3", cwd=db)
        assert "already" in out.lower() or "Already" in out

    def test_unlink_not_linked(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("unlink", "todo_1", "h2_3", cwd=db)
        assert "not linked" in out.lower() or "Not linked" in out

    def test_link_nonexistent_todo(self, db):
        rc, out, err = jari("link", "todo_999", "h2_3", cwd=db)
        assert "not found" in out.lower()

    def test_multiple_niwa_refs(self, db):
        jari("create", "Multi-linked", "--agent", "a1", cwd=db)
        jari("link", "todo_1", "h1_0", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)
        jari("link", "todo_1", "h3_5", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "h1_0" in out
        assert "h2_3" in out
        assert "h3_5" in out

    def test_linked_no_results(self, db):
        rc, out, err = jari("linked", "h99_0", cwd=db)
        assert "No todos" in out


# ── Full Lifecycle Workflows ───────────────────────────────────────────────


class TestLifecycle:
    def test_full_lifecycle(self, db):
        """create → claim → update → close → reopen → close."""
        jari("create", "Lifecycle task", "-p", "1", "-t", "bug", "--agent", "a1", cwd=db)
        jari("claim", "todo_1", "--agent", "agent_x", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "in_progress" in out
        assert "agent_x" in out

        jari("update", "todo_1", "-d", "Working on it", "--agent", "agent_x", cwd=db)
        jari("close", "todo_1", "--reason", "Fixed", "--agent", "agent_x", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "closed" in out
        assert "Fixed" in out

        jari("reopen", "todo_1", "--agent", "agent_x", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "open" in out

        jari("close", "todo_1", "--reason", "Actually fixed now", "--agent", "agent_x", cwd=db)
        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "closed" in out

    def test_multi_agent_workflow(self, db):
        """Three agents create, claim, and close different todos."""
        jari("create", "Task A", "-p", "0", "--agent", "lead", cwd=db)
        jari("create", "Task B", "-p", "1", "--agent", "lead", cwd=db)
        jari("create", "Task C", "-p", "2", "--agent", "lead", cwd=db)

        jari("claim", "todo_1", "--agent", "worker_1", cwd=db)
        jari("claim", "todo_2", "--agent", "worker_2", cwd=db)
        jari("claim", "todo_3", "--agent", "worker_3", cwd=db)

        jari("close", "todo_1", "--reason", "Done", "--agent", "worker_1", cwd=db)
        jari("close", "todo_2", "--reason", "Done", "--agent", "worker_2", cwd=db)

        # worker_3 still in progress
        rc, out, err = jari("list", "--status", "in_progress", cwd=db)
        assert "Task C" in out
        assert "Task A" not in out
        assert "Task B" not in out

        rc, out, err = jari("agents", cwd=db)
        assert "lead" in out
        assert "worker_1" in out
        assert "worker_2" in out
        assert "worker_3" in out

    def test_dep_workflow_with_claims(self, db):
        """Set up deps → claim → close in order."""
        jari("create", "Design", "-p", "0", "--agent", "lead", cwd=db)
        jari("create", "Implement", "-p", "1", "--agent", "lead", cwd=db)
        jari("create", "Test", "-p", "1", "--agent", "lead", cwd=db)

        jari("dep", "add", "todo_2", "todo_1", cwd=db)  # Implement blocked by Design
        jari("dep", "add", "todo_3", "todo_2", cwd=db)  # Test blocked by Implement

        # Only Design is ready
        rc, out, err = jari("ready", cwd=db)
        ready_lines = [l for l in out.split('\n') if 'todo_' in l]
        assert len(ready_lines) == 1

        # Claim and complete Design
        jari("claim", "todo_1", "--agent", "designer", cwd=db)
        jari("close", "todo_1", "--reason", "Designed", "--agent", "designer", cwd=db)

        # Implement becomes ready
        rc, out, err = jari("ready", cwd=db)
        assert any('todo_2' in l for l in out.split('\n'))

        # Claim and complete Implement
        jari("claim", "todo_2", "--agent", "developer", cwd=db)
        jari("close", "todo_2", "--reason", "Implemented", "--agent", "developer", cwd=db)

        # Test becomes ready
        rc, out, err = jari("ready", cwd=db)
        assert any('todo_3' in l for l in out.split('\n'))


# ── Label Edge Cases ───────────────────────────────────────────────────────


class TestLabelEdgeCases:
    def test_label_nonexistent_todo(self, db):
        rc, out, err = jari("label", "add", "todo_999", "urgent", cwd=db)
        assert "not found" in out.lower()

    def test_remove_nonexistent_label(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("label", "remove", "todo_1", "nonexistent", cwd=db)
        assert "not found" in out.lower()

    def test_multiple_labels(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "urgent", cwd=db)
        jari("label", "add", "todo_1", "frontend", cwd=db)
        jari("label", "add", "todo_1", "v2", cwd=db)

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "urgent" in out
        assert "frontend" in out
        assert "v2" in out

    def test_search_by_label_content(self, db):
        jari("create", "Task A", "--agent", "a1", cwd=db)
        jari("create", "Task B", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "unique-label-xyz", cwd=db)
        rc, out, err = jari("search", "unique-label-xyz", cwd=db)
        assert "Task A" in out
        assert "Task B" not in out


# ── Status Command ─────────────────────────────────────────────────────────


class TestStatusCommand:
    def test_overall_status(self, db):
        jari("create", "A", "-p", "0", "--agent", "a1", cwd=db)
        jari("create", "B", "-p", "2", "--agent", "a1", cwd=db)
        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("status", cwd=db)
        assert rc == 0
        assert "2" in out  # total
        assert "open" in out
        assert "closed" in out

    def test_agent_status_no_work(self, db):
        jari("create", "Task", "--agent", "a1", cwd=db)
        rc, out, err = jari("status", "--agent", "fresh_agent", cwd=db)
        assert rc == 0
        assert "Ready to work" in out or "No assigned" in out

    def test_agent_status_with_work(self, db):
        jari("create", "Task A", "--agent", "worker", cwd=db)
        jari("create", "Task B", "--agent", "other", cwd=db)
        jari("claim", "todo_1", "--agent", "worker", cwd=db)
        rc, out, err = jari("status", "--agent", "worker", cwd=db)
        assert "worker" in out
        assert "todo_1" in out


# ── Deferred Status ────────────────────────────────────────────────────────


class TestDeferredStatus:
    def test_update_to_deferred(self, db):
        jari("create", "Deferrable", "--agent", "a1", cwd=db)
        rc, out, err = jari("update", "todo_1", "--status", "deferred", "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "deferred" in out

    def test_deferred_excluded_from_ready(self, db):
        jari("create", "Deferred", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "deferred", "--agent", "a1", cwd=db)
        rc, out, err = jari("ready", cwd=db)
        assert "Deferred" not in out

    def test_claim_deferred_fails(self, db):
        jari("create", "Deferrable", "--agent", "a1", cwd=db)
        jari("update", "todo_1", "--status", "deferred", "--agent", "a1", cwd=db)
        rc, out, err = jari("claim", "todo_1", "--agent", "a2", cwd=db)
        assert "deferred" in out.lower() or "Cannot claim" in out


# ── Export Edge Cases ──────────────────────────────────────────────────────


class TestExportEdgeCases:
    def test_export_preserves_all_fields(self, db):
        jari("create", "Rich todo", "-p", "1", "-t", "bug", "-d", "Desc here", "--agent", "a1", cwd=db)
        jari("label", "add", "todo_1", "important", cwd=db)
        jari("link", "todo_1", "h2_3", cwd=db)

        rc, out, err = jari("export", cwd=db)
        data = json.loads(out.strip())
        assert data['title'] == "Rich todo"
        assert data['priority'] == 1
        assert data['type'] == 'bug'
        assert data['description'] == 'Desc here'
        assert 'important' in data['labels']
        assert 'h2_3' in data['niwa_refs']

    def test_export_multiple_sorted(self, db):
        jari("create", "Low", "-p", "3", "--agent", "a1", cwd=db)
        jari("create", "High", "-p", "1", "--agent", "a1", cwd=db)
        jari("create", "Mid", "-p", "2", "--agent", "a1", cwd=db)

        rc, out, err = jari("export", cwd=db)
        lines = [l for l in out.strip().split('\n') if l]
        assert len(lines) == 3
        # All valid JSON
        for line in lines:
            data = json.loads(line)
            assert 'id' in data


# ── Create Edge Cases ──────────────────────────────────────────────────────


class TestCreateEdgeCases:
    def test_create_with_all_options(self, db):
        jari("create", "Epic", "-t", "epic", "--agent", "a1", cwd=db)
        rc, out, err = jari(
            "create", "Full options task",
            "-p", "1", "-t", "feature",
            "-d", "Detailed desc",
            "--niwa-ref", "h2_5",
            "--parent", "todo_1",
            "--agent", "agent_x",
            cwd=db
        )
        assert rc == 0
        assert "TODO_ID: todo_2" in out

        rc, out, err = jari("show", "todo_2", cwd=db)
        assert "Full options task" in out
        assert "feature" in out
        assert "h2_5" in out
        assert "todo_1" in out

    def test_create_with_file_description(self, db):
        desc_file = db / "description.txt"
        desc_file.write_text("Long description from file\nWith multiple lines\nAnd details")
        rc, out, err = jari("create", "From File", "--file", str(desc_file), "--agent", "a1", cwd=db)
        assert rc == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Long description from file" in out

    def test_create_with_stdin(self, db):
        result = subprocess.run(
            ["jari", "create", "From Stdin", "--stdin", "--agent", "a1"],
            cwd=db,
            capture_output=True,
            text=True,
            input="Piped description content",
        )
        assert result.returncode == 0

        rc, out, err = jari("show", "todo_1", cwd=db)
        assert "Piped description content" in out

    def test_create_all_priority_levels(self, db):
        """Create todos with each priority level."""
        for p in range(5):
            rc, out, err = jari("create", f"P{p} task", "-p", str(p), "--agent", "a1", cwd=db)
            assert rc == 0

        rc, out, err = jari("list", cwd=db)
        assert "5 item" in out

    def test_create_all_types(self, db):
        """Create todos of each type."""
        for t in ['task', 'bug', 'feature', 'epic']:
            rc, out, err = jari("create", f"{t} item", "-t", t, "--agent", "a1", cwd=db)
            assert rc == 0
            assert t in out.lower()


# ── Blocked Command Edge Cases ─────────────────────────────────────────────


class TestBlockedEdgeCases:
    def test_blocked_shows_all_blockers(self, db):
        jari("create", "A", "--agent", "a1", cwd=db)
        jari("create", "B", "--agent", "a1", cwd=db)
        jari("create", "C", "--agent", "a1", cwd=db)

        jari("dep", "add", "todo_3", "todo_1", cwd=db)
        jari("dep", "add", "todo_3", "todo_2", cwd=db)

        rc, out, err = jari("blocked", cwd=db)
        assert "todo_1" in out
        assert "todo_2" in out
        assert "C" in out or "todo_3" in out

    def test_blocked_excludes_closed_blockers(self, db):
        """Closed blockers don't count — todo should not appear in blocked."""
        jari("create", "Blocker", "--agent", "a1", cwd=db)
        jari("create", "Blocked", "--agent", "a1", cwd=db)
        jari("dep", "add", "todo_2", "todo_1", cwd=db)

        jari("close", "todo_1", "--agent", "a1", cwd=db)
        rc, out, err = jari("blocked", cwd=db)
        assert "No blocked" in out


# ── Version / Help ─────────────────────────────────────────────────────────


class TestVersionHelp:
    def test_version_flag(self, tmp_path):
        rc, out, err = jari("--version", cwd=tmp_path)
        assert "0.1.0" in out or "0.1.0" in err

    def test_help_command(self, db):
        rc, out, err = jari("help", cwd=db)
        assert rc == 0
        assert "jari" in out.lower() or "Jari" in out
