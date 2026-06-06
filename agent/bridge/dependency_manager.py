"""
Dependency Manager — DAG-based task dependency resolution.

Manages work order dependencies, detects cycles, calculates critical paths,
and auto-unblocks tasks when their dependencies complete.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from collections import deque


@dataclass
class DependencyNode:
    """Represents a task in the dependency graph."""
    task_id: str
    in_degree: int = 0  # Number of unresolved dependencies
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)  # Tasks that depend on this
    critical_path_length: int = 0


class DependencyManager:
    """
    Manages task dependencies using a directed acyclic graph (DAG).

    Supports:
    - Adding tasks with dependencies
    - Cycle detection
    - Critical path calculation
    - Auto-unblocking on completion
    - Topological sorting
    """

    def __init__(self):
        """Initialize the dependency manager."""
        self.nodes: Dict[str, DependencyNode] = {}
        self.completed: Set[str] = set()

    def add_task(self, task_id: str, dependencies: Optional[List[str]] = None) -> bool:
        """
        Add a task with optional dependencies.

        Args:
            task_id: Unique task identifier
            dependencies: List of task IDs this task depends on

        Returns:
            True if task was added, False if it already exists
        """
        if task_id in self.nodes:
            return False

        deps = dependencies or []

        # Create or update nodes
        if task_id not in self.nodes:
            self.nodes[task_id] = DependencyNode(task_id=task_id)

        # Add dependency edges
        for dep in deps:
            if dep not in self.nodes:
                self.nodes[dep] = DependencyNode(task_id=dep)

            # Only add if not already present
            if dep not in self.nodes[task_id].dependencies:
                self.nodes[task_id].dependencies.append(dep)
                self.nodes[dep].dependents.append(task_id)

        # Update in-degree
        self.nodes[task_id].in_degree = len([d for d in deps if d not in self.completed])

        return True

    def has_cycle(self) -> bool:
        """
        Detect cycles in the dependency graph using DFS.

        Returns:
            True if a cycle exists, False otherwise
        """
        # Color-based cycle detection (white=0, gray=1, black=2)
        color = {task_id: 0 for task_id in self.nodes}

        def has_cycle_dfs(node_id: str) -> bool:
            color[node_id] = 1  # Mark as being processed
            for dep in self.nodes[node_id].dependencies:
                if color[dep] == 1:
                    return True  # Back edge found
                if color[dep] == 0 and has_cycle_dfs(dep):
                    return True
            color[node_id] = 2  # Mark as done
            return False

        for task_id in self.nodes:
            if color[task_id] == 0:
                if has_cycle_dfs(task_id):
                    return True

        return False

    def get_ready_tasks(self) -> List[str]:
        """
        Get all tasks that have no unresolved dependencies.

        Returns:
            List of task IDs ready to execute
        """
        return [
            task_id
            for task_id, node in self.nodes.items()
            if task_id not in self.completed and node.in_degree == 0
        ]

    def complete_task(self, task_id: str) -> List[str]:
        """
        Mark a task as complete and auto-unblock dependents.

        Args:
            task_id: Task ID to mark as complete

        Returns:
            List of newly unblocked task IDs
        """
        if task_id not in self.nodes or task_id in self.completed:
            return []

        self.completed.add(task_id)
        newly_ready = []

        # Unblock dependent tasks
        for dependent_id in self.nodes[task_id].dependents:
            self.nodes[dependent_id].in_degree -= 1
            if self.nodes[dependent_id].in_degree == 0:
                newly_ready.append(dependent_id)

        return newly_ready

    def calculate_critical_path(self) -> int:
        """
        Calculate the length of the critical path (longest path in DAG).

        Uses dynamic programming: for each node, CP = max(CP of dependencies) + 1

        Returns:
            Length of the critical path
        """
        if self.has_cycle():
            return -1  # Invalid for cyclic graphs

        # Topological sort with memo
        memo: Dict[str, int] = {}

        def longest_path(task_id: str) -> int:
            if task_id in memo:
                return memo[task_id]

            deps = self.nodes[task_id].dependencies
            if not deps:
                memo[task_id] = 1
            else:
                memo[task_id] = 1 + max(longest_path(dep) for dep in deps)

            return memo[task_id]

        # Calculate for all nodes and return the maximum
        max_path = 0
        for task_id in self.nodes:
            path_len = longest_path(task_id)
            self.nodes[task_id].critical_path_length = path_len
            max_path = max(max_path, path_len)

        return max_path

    def get_critical_path_tasks(self) -> List[str]:
        """
        Get the task IDs that form the critical path.

        Returns:
            List of task IDs on the critical path
        """
        if not self.nodes:
            return []

        cp_length = self.calculate_critical_path()
        critical_tasks = []

        # Find tasks that are on a path of length cp_length
        for task_id, node in self.nodes.items():
            if node.critical_path_length == cp_length:
                critical_tasks.append(task_id)

        return critical_tasks

    def topological_sort(self) -> List[str]:
        """
        Return tasks in topological order using Kahn's algorithm.

        Returns:
            List of task IDs in topological order, or empty list if cycle exists
        """
        if self.has_cycle():
            return []

        # Copy in-degrees
        in_degree = {
            task_id: node.in_degree
            for task_id, node in self.nodes.items()
            if task_id not in self.completed
        }

        # Initialize queue with tasks that have no dependencies
        queue = deque(task_id for task_id in in_degree if in_degree[task_id] == 0)
        result = []

        while queue:
            current = queue.popleft()
            result.append(current)

            # Reduce in-degree of dependents
            for dependent in self.nodes[current].dependents:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return result

    def get_blocking_tasks(self, task_id: str) -> List[str]:
        """
        Get all tasks that are blocking the specified task.

        Args:
            task_id: Target task ID

        Returns:
            List of unresolved dependency task IDs
        """
        if task_id not in self.nodes:
            return []

        blocking = []
        for dep in self.nodes[task_id].dependencies:
            if dep not in self.completed:
                blocking.append(dep)

        return blocking

    def get_blocked_by(self, task_id: str) -> List[str]:
        """
        Get all tasks that are blocked by the specified task.

        Args:
            task_id: Task ID to check

        Returns:
            List of task IDs that depend on this task
        """
        if task_id not in self.nodes:
            return []

        blocked = []
        for dependent in self.nodes[task_id].dependents:
            if dependent not in self.completed and self.nodes[dependent].in_degree > 0:
                blocked.append(dependent)

        return blocked

    def get_task_info(self, task_id: str) -> Optional[Dict]:
        """
        Get detailed information about a task.

        Args:
            task_id: Task ID

        Returns:
            Dictionary with task info, or None if not found
        """
        if task_id not in self.nodes:
            return None

        node = self.nodes[task_id]
        return {
            "taskId": task_id,
            "completed": task_id in self.completed,
            "dependencies": node.dependencies,
            "dependents": node.dependents,
            "unresolvedDependencies": [d for d in node.dependencies if d not in self.completed],
            "inDegree": node.in_degree,
            "criticalPathLength": node.critical_path_length,
            "isReady": task_id not in self.completed and node.in_degree == 0,
        }

    def to_dict(self) -> Dict:
        """
        Serialize the dependency graph to a dictionary.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "nodes": {
                task_id: {
                    "taskId": task_id,
                    "dependencies": node.dependencies,
                    "dependents": node.dependents,
                    "inDegree": node.in_degree,
                    "completed": task_id in self.completed,
                }
                for task_id, node in self.nodes.items()
            },
            "completed": list(self.completed),
            "readyTasks": self.get_ready_tasks(),
            "hasCycle": self.has_cycle(),
            "criticalPathLength": self.calculate_critical_path() if not self.has_cycle() else -1,
        }

    def reset(self) -> None:
        """Reset the manager to initial state."""
        self.nodes.clear()
        self.completed.clear()
