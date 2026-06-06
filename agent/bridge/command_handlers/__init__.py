"""Per-domain command mixins for `bridge.commands.CommandHandler`.

This subpackage carries the per-`_cmd_*` handler implementations split out
of the original 4 258-LOC `bridge/commands.py`. The mixins are composed
via multiple inheritance by `CommandHandler` in the facade module; the
`__init__` / dispatcher / setters / stat-counters / dispatcher-side
helpers stay in `bridge/commands.py`.

Pattern matches PR #1687 (`bridge/database.py` → `bridge/db/*` mixins
composed by the `Database` facade) and PR #1675 (`bridge/api_server.py`
→ `bridge/api/routes_*.py`).

Demote-split tracked under issue #1305.
"""

from .agents_and_memory import AgentsAndMemoryMixin
from .board_and_voice import BoardAndVoiceMixin
from .cost_and_z4 import CostAndZ4Mixin
from .departments import DepartmentsMixin
from .jobs_and_factory import JobsAndFactoryMixin
from .lifecycle import LifecycleMixin
from .skills_and_hooks import SkillsAndHooksMixin
from .wiki import WikiMixin

__all__ = [
    "AgentsAndMemoryMixin",
    "BoardAndVoiceMixin",
    "CostAndZ4Mixin",
    "DepartmentsMixin",
    "JobsAndFactoryMixin",
    "LifecycleMixin",
    "SkillsAndHooksMixin",
    "WikiMixin",
]
