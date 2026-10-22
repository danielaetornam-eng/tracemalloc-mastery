"""
Advanced patterns: decorators, context managers, and utilities for memory tracking.
"""

import functools
import sys
import threading
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    TypeVar,
)

from ..analysis import SnapshotComparator
from ..core import TracemallocSession

T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


@dataclass
class ProfileResult:
    """Result of a profiled function execution."""
    function_name: str
    args: Tuple
    kwargs: Dict
    return_value: Any
    execution_time: float
    memory_before: Tuple[int, int]  # (current, peak)
    memory_after: Tuple[int, int]
    memory_diff: Tuple[int, int]
    snapshot_before: Optional[tracemalloc.Snapshot] = None
    snapshot_after: Optional[tracemalloc.Snapshot] = None
    top_diffs: List = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def memory_increase_mb(self) -> float:
        return self.memory_diff[0] / 1024 / 1024

    @property
    def peak_increase_mb(self) -> float:
        return self.memory_diff[1] / 1024 / 1024


class MemoryGuard:
    """
    Context manager and decorator for guarding memory usage.

    Ensures memory stays within limits and alerts on violations.
    """

    def __init__(
        self,
        max_memory_mb: float = 100,
        max_increase_mb: float = 50,
        action: str = 'warn',  # 'warn', 'raise', 'log'
        session: Optional['TracemallocSession'] = None,
    ):
        from tracemalloc_mastery.core import TracemallocSession
        self.max_memory_mb = max_memory_mb
        self.max_increase_mb = max_increase_mb
        self.action = action
        self.session = session or TracemallocSession.get_default()
        self._initial_memory: Optional[Tuple[int, int]] = None
        self._snapshots: List[tracemalloc.Snapshot] = []

    def __enter__(self):
        if not self.session.is_active:
            self.session.start()
        self._initial_memory = self.session.get_traced_memory()
        self._snapshots.append(tracemalloc.take_snapshot())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.session.is_active:
            return

        current, peak = self.session.get_traced_memory()
        initial_current, initial_peak = self._initial_memory

        increase = current - initial_current
        increase_mb = increase / 1024 / 1024
        current_mb = current / 1024 / 1024

        violations = []
        if current_mb > self.max_memory_mb:
            violations.append(f"Memory {current_mb:.2f}MB exceeds limit {self.max_memory_mb}MB")
        if increase_mb > self.max_increase_mb:
            violations.append(f"Memory increase {increase_mb:.2f}MB exceeds limit {self.max_increase_mb}MB")

        if violations:
            msg = "; ".join(violations)
            if self.action == 'raise':
                raise MemoryError(msg)
            elif self.action == 'warn':
                import warnings
                warnings.warn(msg, RuntimeWarning, stacklevel=2)
            elif self.action == 'log':
                import logging
                logging.warning(msg)

        self._snapshots.append(tracemalloc.take_snapshot())
        return False

    def __call__(self, func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return wrapper  # type: ignore


def track_memory(
    session: Optional['TracemallocSession'] = None,
    label: str = "",
    top_n: int = 10,
    log_result: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to track memory usage of a function.

    Usage:
        @track_memory(label="my_function")
        def my_function():
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            sess = session or TracemallocSession.get_default()
            if not sess.is_active:
                sess.start()

            label_used = label or f"{func.__module__}.{func.__qualname__}"
            snap_before = sess.take_snapshot(f"{label_used}_start")

            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                end_time = time.perf_counter()
                snap_after = sess.take_snapshot(f"{label_used}_end")

                comparator = SnapshotComparator()
                diff = comparator.compare(snap_before.snapshot, snap_after.snapshot)

                exec_time = end_time - start_time

                if log_result:
                    print(f"\n[{label_used}] Memory Profile:")
                    print(f"  Execution time: {exec_time*1000:.2f} ms")
                    print(f"  Memory change: {diff.total_size_diff_mb:.2f} MB")
                    print(f"  Allocation count change: {diff.total_count_diff}")
                    if diff.added:
                        print("  Top allocations:")
                        for d in diff.get_top_changes(top_n, 'size'):
                            print(f"    +{d.size_diff_mb:.2f} MB: {d.statistic.traceback[0] if d.statistic.traceback else 'unknown'}")

        return wrapper  # type: ignore
    return decorator


@contextmanager
def memory_context(
    session: Optional['TracemallocSession'] = None,
    label: str = "",
    auto_compare: bool = True,
    top_n: int = 10,
) -> Generator['ProfileContext', None, None]:
    """
    Context manager for memory tracking a code block.

    Usage:
        with memory_context(label="data_processing") as ctx:
            process_large_data()
        print(ctx.result)
    """
    sess = session or TracemallocSession.get_default()
    if not sess.is_active:
        sess.start()

    label_used = label or f"block_{id(threading.current_thread())}"
    snap_before = sess.take_snapshot(f"{label_used}_start")

    start_time = time.perf_counter()
    result = ProfileContext()
    result.label = label_used
    result.snapshot_before = snap_before
    result.start_time = start_time

    try:
        yield result
    finally:
        end_time = time.perf_counter()
        snap_after = sess.take_snapshot(f"{label_used}_end")

        result.snapshot_after = snap_after
        result.end_time = end_time
        result.execution_time = end_time - start_time

        if auto_compare:
            comparator = SnapshotComparator()
            diff = comparator.compare(snap_before.snapshot, snap_after.snapshot)
            result.comparison = diff
            result.memory_diff_mb = diff.total_size_diff_mb
            result.count_diff = diff.total_count_diff
            result.top_changes = diff.get_top_changes(top_n, 'size')

            if result.memory_diff_mb > 0:
                print(f"\n[{label_used}] Memory: {result.memory_diff_mb:.2f} MB increase in {result.execution_time*1000:.2f} ms")


def allocate_guard(
    max_allocations: int = 10000,
    max_bytes: int = 100 * 1024 * 1024,
    action: str = 'raise',
) -> Callable[[F], F]:
    """
    Decorator to guard against excessive allocations.

    Usage:
        @allocate_guard(max_allocations=1000, max_bytes=10*1024*1024)
        def my_function():
            ...
    """
    from tracemalloc_mastery.core import TracemallocSession

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            sess = TracemallocSession.get_default()
            if not sess.is_active:
                sess.start()

            before = sess.get_traced_memory()
            result = func(*args, **kwargs)
            after = sess.get_traced_memory()

            alloc_count = after[0] - before[0]
            alloc_bytes = after[0] - before[0]

            violations = []
            if alloc_count > max_allocations:
                violations.append(f"Allocation count {alloc_count} exceeds {max_allocations}")
            if alloc_bytes > max_bytes:
                violations.append(f"Allocation bytes {alloc_bytes/1024/1024:.2f}MB exceeds {max_bytes/1024/1024:.2f}MB")

            if violations:
                msg = f"[{func.__name__}] " + "; ".join(violations)
                if action == 'raise':
                    raise MemoryError(msg)
                elif action == 'warn':
                    import warnings
                    warnings.warn(msg, RuntimeWarning, stacklevel=2)

            return result
        return wrapper  # type: ignore
    return decorator


def profile_function(
    session: Optional['TracemallocSession'] = None,
    include_snapshots: bool = False,
    top_n: int = 10,
) -> Callable[[F], F]:
    """
    Decorator that returns a ProfileResult with detailed memory info.

    Usage:
        @profile_function()
        def my_function():
            ...

        result = my_function()
        print(result.memory_increase_mb)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            sess = session or TracemallocSession.get_default()
            if not sess.is_active:
                sess.start()

            mem_before = sess.get_traced_memory()
            snap_before = tracemalloc.take_snapshot() if include_snapshots else None

            start_time = time.perf_counter()
            return_value = func(*args, **kwargs)
            end_time = time.perf_counter()

            mem_after = sess.get_traced_memory()
            snap_after = tracemalloc.take_snapshot() if include_snapshots else None

            mem_diff = (mem_after[0] - mem_before[0], mem_after[1] - mem_before[1])

            top_diffs = []
            if include_snapshots and snap_before and snap_after:
                comparator = SnapshotComparator()
                diff = comparator.compare(snap_before, snap_after)
                top_diffs = diff.get_top_changes(top_n, 'size')

            return ProfileResult(
                function_name=f"{func.__module__}.{func.__qualname__}",
                args=args,
                kwargs=kwargs,
                return_value=return_value,
                execution_time=end_time - start_time,
                memory_before=mem_before,
                memory_after=mem_after,
                memory_diff=mem_diff,
                snapshot_before=snap_before,
                snapshot_after=snap_after,
                top_diffs=top_diffs,
            )
        return wrapper  # type: ignore
    return decorator


class ProfileContext:
    """
    Advanced profiling context with nested support.

    Usage:
        profiler = ProfileContext()
        with profiler.profile("operation_name"):
            do_work()
        print(profiler.get_summary())
"""

    def __init__(self, session: Optional['TracemallocSession'] = None):
        from tracemalloc_mastery.core import TracemallocSession
        self.session = session or TracemallocSession.get_default()
        self._stack: List[ProfileContext.Frame] = []
        self._results: List[ProfileContext.Frame] = []
        self._enabled = True

    @dataclass
    class Frame:
        name: str
        parent: Optional['ProfileContext.Frame']
        start_time: float
        memory_start: Tuple[int, int]
        snapshot_start: Optional[tracemalloc.Snapshot]
        children: List['ProfileContext.Frame'] = field(default_factory=list)
        end_time: float = 0
        memory_end: Tuple[int, int] = (0, 0)
        snapshot_end: Optional[tracemalloc.Snapshot] = None

    @contextmanager
    def profile(self, name: str, take_snapshot: bool = True) -> Generator['ProfileContext.Frame', None, None]:
        if not self._enabled:
            yield None
            return

        if not self.session.is_active:
            self.session.start()

        parent = self._stack[-1] if self._stack else None
        frame = self.Frame(
            name=name,
            parent=parent,
            start_time=time.perf_counter(),
            memory_start=self.session.get_traced_memory(),
            snapshot_start=tracemalloc.take_snapshot() if take_snapshot else None,
        )

        if parent:
            parent.children.append(frame)

        self._stack.append(frame)

        try:
            yield frame
        finally:
            frame.end_time = time.perf_counter()
            frame.memory_end = self.session.get_traced_memory()
            frame.snapshot_end = tracemalloc.take_snapshot() if take_snapshot else None
            self._stack.pop()
            self._results.append(frame)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all profiled frames."""
        if not self._results:
            return {}

        from tracemalloc_mastery.analysis import SnapshotComparator
        comparator = SnapshotComparator()

        def frame_to_dict(frame: 'ProfileContext.Frame') -> Dict:
            mem_diff = frame.memory_end[0] - frame.memory_start[0]
            result = {
                "name": frame.name,
                "execution_time_ms": (frame.end_time - frame.start_time) * 1000,
                "memory_increase_mb": mem_diff / 1024 / 1024,
                "memory_start_mb": frame.memory_start[0] / 1024 / 1024,
                "memory_end_mb": frame.memory_end[0] / 1024 / 1024,
                "children": [frame_to_dict(c) for c in frame.children],
            }

            if frame.snapshot_start and frame.snapshot_end:
                diff = comparator.compare(frame.snapshot_start, frame.snapshot_end)
                result["top_allocations"] = [
                    {"size_mb": d.size_diff_mb, "traceback": str(d.statistic.traceback[0]) if d.statistic.traceback else "unknown"}
                    for d in diff.get_top_changes(5, 'size')
                ]
            return result

        return {
            "total_frames": len(self._results),
            "frames": [frame_to_dict(f) for f in self._results if f.parent is None],
        }

    def clear(self):
        self._results.clear()
        self._stack.clear()

    def disable(self):
        self._enabled = False

    def enable(self):
        self._enabled = True


class AsyncMemoryTracker:
    """
    Track memory across async operations.

    Usage:
        tracker = AsyncMemoryTracker()
        async with tracker.track("async_operation"):
            await async_operation()
    """

    def __init__(self, session: Optional['TracemallocSession'] = None):
        from tracemalloc_mastery.core import TracemallocSession
        self.session = session or TracemallocSession.get_default()
        self._tasks: Dict[int, AsyncMemoryTracker.TaskData] = {}

    @dataclass
    class TaskData:
        name: str
        start_time: float
        memory_start: Tuple[int, int]
        snapshot_start: tracemalloc.Snapshot
        memory_end: Tuple[int, int] = (0, 0)
        snapshot_end: Optional[tracemalloc.Snapshot] = None
        end_time: float = 0

    @contextmanager
    def track(self, name: str) -> Generator[None, None, None]:
        if not self.session.is_active:
            self.session.start()

        task_id = id(asyncio.current_task() if 'asyncio' in sys.modules else threading.current_thread())

        task_data = self.TaskData(
            name=name,
            start_time=time.perf_counter(),
            memory_start=self.session.get_traced_memory(),
            snapshot_start=tracemalloc.take_snapshot(),
        )
        self._tasks[task_id] = task_data

        try:
            yield
        finally:
            task_data.end_time = time.perf_counter()
            task_data.memory_end = self.session.get_traced_memory()
            task_data.snapshot_end = tracemalloc.take_snapshot()

    def get_task_result(self, task_id: int) -> Optional[Dict]:
        """Get result for a specific task."""
        task = self._tasks.get(task_id)
        if not task or not task.snapshot_end:
            return None

        from tracemalloc_mastery.analysis import SnapshotComparator
        comparator = SnapshotComparator()
        diff = comparator.compare(task.snapshot_start, task.snapshot_end)

        return {
            "name": task.name,
            "execution_time": task.end_time - task.start_time,
            "memory_increase_mb": (task.memory_end[0] - task.memory_start[0]) / 1024 / 1024,
            "top_changes": [
                {"size_mb": d.size_diff_mb, "traceback": str(d.statistic.traceback[0]) if d.statistic.traceback else "unknown"}
                for d in diff.get_top_changes(5, 'size')
            ],
        }

    def get_all_results(self) -> List[Dict]:
        return [self.get_task_result(tid) for tid in self._tasks if self.get_task_result(tid)]


# Import for type hints
try:
    import asyncio
except ImportError:
    asyncio = None
