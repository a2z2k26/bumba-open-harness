"""Tests for DAG-based dependency manager."""

from bridge.dependency_manager import DependencyManager


class TestDependencyManagerBasics:
    """Test basic dependency manager operations."""

    def test_create_manager(self):
        """Can create a dependency manager."""
        manager = DependencyManager()
        assert manager is not None
        assert len(manager.nodes) == 0

    def test_add_task_no_dependencies(self):
        """Can add a task with no dependencies."""
        manager = DependencyManager()
        result = manager.add_task("task-1")
        assert result is True
        assert "task-1" in manager.nodes

    def test_add_task_with_dependencies(self):
        """Can add a task with dependencies."""
        manager = DependencyManager()
        manager.add_task("task-1")
        result = manager.add_task("task-2", dependencies=["task-1"])
        assert result is True
        assert "task-2" in manager.nodes
        assert "task-1" in manager.nodes["task-2"].dependencies

    def test_cannot_add_duplicate_task(self):
        """Cannot add the same task twice."""
        manager = DependencyManager()
        manager.add_task("task-1")
        result = manager.add_task("task-1")
        assert result is False

    def test_add_task_auto_creates_dependencies(self):
        """Adding a task with dependencies auto-creates those tasks."""
        manager = DependencyManager()
        manager.add_task("task-2", dependencies=["task-1", "task-3"])
        assert "task-1" in manager.nodes
        assert "task-3" in manager.nodes
        assert "task-2" in manager.nodes


class TestDependencyGraph:
    """Test dependency graph structure."""

    def test_dependency_edges(self):
        """Dependencies create correct edges."""
        manager = DependencyManager()
        manager.add_task("task-1")
        manager.add_task("task-2", dependencies=["task-1"])

        # task-2 depends on task-1
        assert "task-1" in manager.nodes["task-2"].dependencies
        # task-1 is depended on by task-2
        assert "task-2" in manager.nodes["task-1"].dependents

    def test_in_degree_calculation(self):
        """In-degree is correctly calculated."""
        manager = DependencyManager()
        manager.add_task("task-1")
        manager.add_task("task-2", dependencies=["task-1"])
        manager.add_task("task-3", dependencies=["task-1", "task-2"])

        assert manager.nodes["task-1"].in_degree == 0
        assert manager.nodes["task-2"].in_degree == 1
        assert manager.nodes["task-3"].in_degree == 2

    def test_complex_dependency_graph(self):
        """Can build a complex dependency graph."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])
        manager.add_task("d", dependencies=["b", "c"])
        manager.add_task("e", dependencies=["d"])

        assert len(manager.nodes) == 5
        assert manager.nodes["d"].in_degree == 2


class TestCycleDetection:
    """Test cycle detection."""

    def test_no_cycle_simple(self):
        """Simple linear graph has no cycle."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["b"])
        assert manager.has_cycle() is False

    def test_no_cycle_diamond(self):
        """Diamond dependency has no cycle."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])
        manager.add_task("d", dependencies=["b", "c"])
        assert manager.has_cycle() is False

    def test_detects_self_cycle(self):
        """Detects self-dependency cycle."""
        manager = DependencyManager()
        manager.add_task("a", dependencies=["a"])
        assert manager.has_cycle() is True

    def test_detects_two_node_cycle(self):
        """Detects two-node cycle."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        # Manually add the cycle (normally prevented)
        manager.nodes["a"].dependencies.append("b")
        manager.nodes["b"].dependents.append("a")
        assert manager.has_cycle() is True

    def test_detects_longer_cycle(self):
        """Detects cycles in longer paths."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["b"])
        # Create cycle manually
        manager.nodes["a"].dependencies.append("c")
        manager.nodes["c"].dependents.append("a")
        assert manager.has_cycle() is True


class TestReadyTasks:
    """Test ready task identification."""

    def test_no_dependencies_is_ready(self):
        """Tasks with no dependencies are ready."""
        manager = DependencyManager()
        manager.add_task("task-1")
        ready = manager.get_ready_tasks()
        assert "task-1" in ready

    def test_blocked_task_not_ready(self):
        """Tasks with unresolved dependencies are not ready."""
        manager = DependencyManager()
        manager.add_task("task-1")
        manager.add_task("task-2", dependencies=["task-1"])
        ready = manager.get_ready_tasks()
        assert "task-1" in ready
        assert "task-2" not in ready

    def test_unblock_on_completion(self):
        """Completing a task unblocks dependents."""
        manager = DependencyManager()
        manager.add_task("task-1")
        manager.add_task("task-2", dependencies=["task-1"])
        manager.add_task("task-3", dependencies=["task-2"])

        assert "task-2" not in manager.get_ready_tasks()

        unblocked = manager.complete_task("task-1")
        assert "task-2" in unblocked
        assert "task-2" in manager.get_ready_tasks()

    def test_cascading_unblock(self):
        """Completing a task can cascade unblocking."""
        manager = DependencyManager()
        manager.add_task("task-1")
        manager.add_task("task-2", dependencies=["task-1"])
        manager.add_task("task-3", dependencies=["task-2"])

        manager.complete_task("task-1")
        unblocked = manager.complete_task("task-2")

        assert "task-3" in unblocked
        assert "task-3" in manager.get_ready_tasks()


class TestCriticalPath:
    """Test critical path calculation."""

    def test_single_task_critical_path(self):
        """Single task has critical path of 1."""
        manager = DependencyManager()
        manager.add_task("task-1")
        cp = manager.calculate_critical_path()
        assert cp == 1

    def test_linear_critical_path(self):
        """Linear chain has path length equal to number of tasks."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["b"])
        manager.add_task("d", dependencies=["c"])
        cp = manager.calculate_critical_path()
        assert cp == 4

    def test_diamond_critical_path(self):
        """Diamond path selects longest path."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])
        manager.add_task("d", dependencies=["b", "c"])
        cp = manager.calculate_critical_path()
        assert cp == 3

    def test_complex_critical_path(self):
        """Complex DAG critical path calculation."""
        manager = DependencyManager()
        manager.add_task("1")
        manager.add_task("2", dependencies=["1"])
        manager.add_task("3", dependencies=["1"])
        manager.add_task("4", dependencies=["2", "3"])
        manager.add_task("5", dependencies=["4"])
        manager.add_task("6", dependencies=["3"])
        cp = manager.calculate_critical_path()
        # Path 1->2->4->5 = 4, or 1->3->4->5 = 4
        assert cp == 4

    def test_critical_path_with_cycle_returns_minus_one(self):
        """Critical path returns -1 for cyclic graphs."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.nodes["a"].dependencies.append("b")
        manager.nodes["b"].dependents.append("a")
        cp = manager.calculate_critical_path()
        assert cp == -1

    def test_critical_path_tasks(self):
        """Can identify tasks on the critical path."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["b"])
        manager.calculate_critical_path()
        critical = manager.get_critical_path_tasks()
        assert len(critical) > 0


class TestTopologicalSort:
    """Test topological sorting."""

    def test_topological_sort_simple(self):
        """Can sort simple DAG."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["b"])

        topo = manager.topological_sort()
        assert topo == ["a", "b", "c"]

    def test_topological_sort_diamond(self):
        """Can sort diamond dependency."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])
        manager.add_task("d", dependencies=["b", "c"])

        topo = manager.topological_sort()
        assert topo.index("a") < topo.index("b")
        assert topo.index("a") < topo.index("c")
        assert topo.index("b") < topo.index("d")
        assert topo.index("c") < topo.index("d")

    def test_topological_sort_with_cycle_returns_empty(self):
        """Returns empty list for cyclic graph."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.nodes["a"].dependencies.append("b")
        manager.nodes["b"].dependents.append("a")

        topo = manager.topological_sort()
        assert topo == []


class TestBlockingRelationships:
    """Test blocking task queries."""

    def test_get_blocking_tasks(self):
        """Can identify blocking tasks."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a", "b"])

        blocking = manager.get_blocking_tasks("c")
        assert "a" in blocking
        assert "b" in blocking

    def test_blocking_tasks_exclude_completed(self):
        """Blocking tasks exclude completed dependencies."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a", "b"])

        manager.complete_task("a")
        blocking = manager.get_blocking_tasks("c")
        assert "a" not in blocking
        assert "b" in blocking

    def test_get_blocked_by(self):
        """Can identify tasks blocked by a task."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])

        blocked = manager.get_blocked_by("a")
        assert "b" in blocked
        assert "c" in blocked

    def test_blocked_by_excludes_completed(self):
        """Blocked tasks exclude already completed tasks."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.add_task("c", dependencies=["a"])

        manager.complete_task("b")
        blocked = manager.get_blocked_by("a")
        assert "b" not in blocked
        assert "c" in blocked


class TestTaskInfo:
    """Test task information retrieval."""

    def test_get_task_info(self):
        """Can retrieve detailed task info."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])

        info = manager.get_task_info("b")
        assert info["taskId"] == "b"
        assert info["completed"] is False
        assert "task-1" not in info["dependencies"]
        assert info["inDegree"] == 1
        assert info["isReady"] is False

    def test_task_info_nonexistent(self):
        """Returns None for nonexistent task."""
        manager = DependencyManager()
        assert manager.get_task_info("nonexistent") is None

    def test_task_info_after_completion(self):
        """Task info reflects completion state."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])

        manager.complete_task("a")
        info = manager.get_task_info("a")
        assert info["completed"] is True


class TestSerialization:
    """Test serialization to dictionary."""

    def test_to_dict(self):
        """Can serialize to dict."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])

        data = manager.to_dict()
        assert "nodes" in data
        assert "completed" in data
        assert "readyTasks" in data
        assert "hasCycle" in data

    def test_to_dict_reflects_state(self):
        """Serialization reflects current state."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.complete_task("a")

        data = manager.to_dict()
        assert "a" in data["completed"]
        assert "b" in data["readyTasks"]


class TestReset:
    """Test manager reset."""

    def test_reset_clears_state(self):
        """Reset clears all nodes and completed tasks."""
        manager = DependencyManager()
        manager.add_task("a")
        manager.add_task("b", dependencies=["a"])
        manager.complete_task("a")

        assert len(manager.nodes) > 0
        assert len(manager.completed) > 0

        manager.reset()
        assert len(manager.nodes) == 0
        assert len(manager.completed) == 0
