"""jari.models - Data models for todo/issue tracking."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple


@dataclass
class ConflictAnalysis:
    """Field-level conflict analysis for LLM resolution."""
    todo_id: str
    todo_title: str

    # Version info
    your_base_version: int
    current_version: int

    # Field-level changes
    your_changes: Dict[str, Tuple]   # field -> (old_value, new_value)
    their_changes: Dict[str, Tuple]  # field -> (old_value, new_value)
    overlapping_fields: List[str]    # fields changed by both

    # Agent info
    your_agent_id: str
    other_agents: List[str]

    # Auto-merge
    auto_merge_possible: bool
    auto_merged_fields: Optional[Dict] = None

    def to_llm_prompt(self) -> str:
        """Generate a structured prompt for LLM to resolve the conflict."""
        prompt = f"""## CONFLICT DETECTED - Resolution Required

### Context
- **Todo**: `{self.todo_id}` - "{self.todo_title}"
- **Your base version**: {self.your_base_version}
- **Current version**: {self.current_version}
- **Other editors**: {', '.join(self.other_agents) or 'Unknown'}

### YOUR CHANGES (from base version {self.your_base_version}):
"""
        for field_name, (old, new) in self.your_changes.items():
            prompt += f"  - **{field_name}**: `{old}` → `{new}`\n"

        prompt += f"""
### THEIR CHANGES (current version {self.current_version}):
"""
        for field_name, (old, new) in self.their_changes.items():
            prompt += f"  - **{field_name}**: `{old}` → `{new}`\n"

        if self.overlapping_fields:
            prompt += f"""
### OVERLAPPING FIELDS (both changed):
"""
            for f in self.overlapping_fields:
                yours = self.your_changes.get(f, (None, None))[1]
                theirs = self.their_changes.get(f, (None, None))[1]
                prompt += f"  - **{f}**: yours=`{yours}`, theirs=`{theirs}`\n"
        else:
            prompt += "\nNo overlapping fields - changes are in different fields.\n"

        prompt += """
### RESOLUTION OPTIONS

1. **ACCEPT_YOURS**: Overwrite with your changes (discards their changes)
2. **ACCEPT_THEIRS**: Keep current version (discards your changes)
3. **MANUAL_MERGE**: Provide specific field values to merge

Please respond with ONE of:
- `ACCEPT_YOURS`
- `ACCEPT_THEIRS`
- `MANUAL_MERGE` followed by field=value pairs
"""
        return prompt


@dataclass
class EditResult:
    """Result of a todo operation."""
    success: bool
    todo_id: str
    new_version: Optional[int] = None
    message: str = ""
    conflict: Optional[ConflictAnalysis] = None

    def needs_resolution(self) -> bool:
        return self.conflict is not None and not self.success
