"""jari 砂利 - Task/Issue Tracker for LLM Agent Workflows"""

__version__ = "0.3.0"

from .jari import JariDB
from .cli import main
from .models import EditResult, ConflictAnalysis
from .command import COMMAND_HELP, print_command_help
from .core import generate_claude_hooks_config, handle_hook_event, setup_claude_hooks, JARI_SYSTEM_PROMPT, ERROR_PROMPTS, print_error

__all__ = [
    'JariDB', 'main', 'EditResult', 'ConflictAnalysis',
    'COMMAND_HELP', 'print_command_help',
    'generate_claude_hooks_config', 'handle_hook_event', 'setup_claude_hooks',
    'JARI_SYSTEM_PROMPT', 'ERROR_PROMPTS', 'print_error',
    '__version__',
]
