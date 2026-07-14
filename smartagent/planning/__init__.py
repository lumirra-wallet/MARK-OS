"""
Planning subpackage.

Defines MARK's goal and task planning capability: tracking longer-running
goals for the owner and breaking them down into concrete, orderable tasks
the brain can act on (directly, or via skills/automation). Kept separate
from `brain` so planning strategy can evolve independently of message
handling.

No real planning logic is implemented yet — this subpackage currently
only defines the placeholder shape of `GoalManager` and `TaskPlanner`.
"""
