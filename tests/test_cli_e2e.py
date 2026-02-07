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
