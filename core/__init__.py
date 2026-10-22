"""
Core tracemalloc fundamentals - The foundation of all memory tracking.
"""

import contextlib
import gc
import threading
import time
import tracemalloc
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

T = TypeVar('T')


@dataclass(frozen=True)
class AllocationRecord:
    """Immutable record of a single memory allocation."""
    size: int
    count: int
    traceback: Tuple[tracemalloc.Frame, ...]
    domain: str = "default"
    timestamp: float = field(default_factory=time.time)
    thread_id: int = field(default_factory=threading.get_ident)

    @property
    def total_bytes(self) -> int:
        return self.size * self.count

    def __lt__(self, other: 'AllocationRecord') -> bool:
        return self.total_bytes < other.total_bytes


@dataclass
class MemorySnapshot:
    """Enhanced snapshot with metadata and analysis helpers."""
    snapshot: tracemalloc.Snapshot
    timestamp: float
    label: str
    domain: str = "default"
    thread_id: int = field(default_factory=threading.get_ident)
    process_memory_mb: float = 0.0
    _stats_cache: Optional[List[tracemalloc.Statistic]] = None

    def __post_init__(self):
        self._update_process_memory()

    def _update_process_memory(self):
        import psutil
        try:
            self.process_memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
        except ImportError:
            self.process_memory_mb = 0.0

    def filter_traces(self, *filters: tracemalloc.Filter) -> 'MemorySnapshot':
        """Return a new snapshot with filters applied."""
        filtered = self.snapshot.filter_traces(filters)
        return MemorySnapshot(
            snapshot=filtered,
            timestamp=self.timestamp,
            label=f"{self.label} (filtered)",
            domain=self.domain,
            thread_id=self.thread_id,
        )

    def statistics(self, key_type: str = 'lineno') -> List[tracemalloc.Statistic]:
        """Get cached statistics."""
        if self._stats_cache is None or self._stats_cache[0].key_type != key_type:
            self._stats_cache = self.snapshot.statistics(key_type)
        return self._stats_cache

    def top_allocations(self, n: int = 10, key_type: str = 'lineno') -> List[tracemalloc.Statistic]:
        """Get top N allocations by size."""
        return self.statistics(key_type)[:n]

    def compare_to(self, other: 'MemorySnapshot', key_type: str = 'lineno') -> List[tracemalloc.StatisticDiff]:
        """Compare this snapshot to another."""
        return self.snapshot.compare_to(other.snapshot, key_type)


class TracemallocSession:
    """
    High-level session manager for tracemalloc.

    Provides a clean API for starting, stopping, and managing
    memory tracking sessions with automatic cleanup.
    """

    _default_session: Optional['TracemallocSession'] = None
    _lock = threading.Lock()

    def __init__(
        self,
        max_frames: int = 50,
        trace_python_allocators: bool = True,
        trace_c_allocators: bool = False,
    ):
        self.max_frames = max_frames
        self.trace_python_allocators = trace_python_allocators
        self.trace_c_allocators = trace_c_allocators
        self._started = False
        self._snapshots: List[MemorySnapshot] = []
        self._domain_filters: Dict[str, List[tracemalloc.Filter]] = defaultdict(list)
        self._callbacks: List[Callable[[MemorySnapshot], None]] = []
        self._thread_local = threading.local()

    @classmethod
    def get_default(cls) -> 'TracemallocSession':
        """Get or create the default global session."""
        with cls._lock:
            if cls._default_session is None:
                cls._default_session = cls()
            return cls._default_session

    @classmethod
    def set_default(cls, session: 'TracemallocSession'):
        """Set the default global session."""
        with cls._lock:
            cls._default_session = session

    def start(self) -> 'TracemallocSession':
        """Start the tracemalloc session."""
        if not self._started:
            tracemalloc.start(self.max_frames)
            self._started = True
        return self

    def stop(self) -> 'TracemallocSession':
        """Stop the tracemalloc session."""
        if self._started:
            tracemalloc.stop()
            self._started = False
        return self

    def __enter__(self) -> 'TracemallocSession':
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    @property
    def is_active(self) -> bool:
        return self._started and tracemalloc.is_tracing()

    def take_snapshot(self, label: str = "", domain: str = "default") -> MemorySnapshot:
        """Take a memory snapshot with metadata."""
        if not self.is_active:
            raise RuntimeError("Session not active. Call start() first.")

        snapshot = tracemalloc.take_snapshot()
        mem_snapshot = MemorySnapshot(
            snapshot=snapshot,
            timestamp=time.time(),
            label=label or f"snapshot_{len(self._snapshots)}",
            domain=domain,
        )
        self._snapshots.append(mem_snapshot)

        for callback in self._callbacks:
            with contextlib.suppress(Exception):
                callback(mem_snapshot)

        return mem_snapshot

    def get_snapshots(self, domain: Optional[str] = None) -> List[MemorySnapshot]:
        """Get all snapshots, optionally filtered by domain."""
        if domain is None:
            return list(self._snapshots)
        return [s for s in self._snapshots if s.domain == domain]

    def clear_snapshots(self, domain: Optional[str] = None):
        """Clear stored snapshots."""
        if domain is None:
            self._snapshots.clear()
        else:
            self._snapshots = [s for s in self._snapshots if s.domain != domain]

    def add_filter(self, filter_obj: tracemalloc.Filter, domain: str = "default"):
        """Add a filter for a specific domain."""
        self._domain_filters[domain].append(filter_obj)

    def remove_filter(self, filter_obj: tracemalloc.Filter, domain: str = "default"):
        """Remove a filter from a domain."""
        if filter_obj in self._domain_filters[domain]:
            self._domain_filters[domain].remove(filter_obj)

    def get_filters(self, domain: str = "default") -> List[tracemalloc.Filter]:
        """Get filters for a domain."""
        return list(self._domain_filters.get(domain, []))

    def apply_filters(self, snapshot: tracemalloc.Snapshot, domain: str = "default") -> tracemalloc.Snapshot:
        """Apply all domain filters to a snapshot."""
        filters = self._domain_filters.get(domain, [])
        return snapshot.filter_traces(filters)

    def register_callback(self, callback: Callable[[MemorySnapshot], None]):
        """Register a callback for new snapshots."""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[MemorySnapshot], None]):
        """Unregister a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def get_traced_memory(self) -> Tuple[int, int]:
        """Get current and peak traced memory in bytes."""
        return tracemalloc.get_traced_memory()

    def reset_peak(self):
        """Reset peak memory statistics."""
        tracemalloc.reset_peak()

    def clear_traces(self):
        """Clear all traces."""
        tracemalloc.clear_traces()
        self._snapshots.clear()


class MemoryTracker:
    """
    High-level memory tracking with automatic snapshot management.

    Designed for tracking memory usage across code sections,
    functions, or arbitrary blocks of code.
    """

    def __init__(self, session: Optional[TracemallocSession] = None):
        self.session = session or TracemallocSession.get_default()
        self._marks: Dict[str, MemorySnapshot] = {}
        self._tracking_stack: List[str] = []

    def mark(self, name: str, domain: str = "default") -> MemorySnapshot:
        """Mark a point in time with a named snapshot."""
        snapshot = self.session.take_snapshot(name, domain)
        self._marks[name] = snapshot
        return snapshot

    def get_mark(self, name: str) -> Optional[MemorySnapshot]:
        """Get a previously marked snapshot."""
        return self._marks.get(name)

    def compare_marks(self, name1: str, name2: str, key_type: str = 'lineno') -> List[tracemalloc.StatisticDiff]:
        """Compare two marked snapshots."""
        snap1 = self._marks.get(name1)
        snap2 = self._marks.get(name2)
        if not snap1 or not snap2:
            raise ValueError(f"Mark not found: {name1 if not snap1 else name2}")
        return snap1.compare_to(snap2, key_type)

    @contextmanager
    def track(self, name: str, domain: str = "default") -> Generator[MemorySnapshot, None, None]:
        """Context manager for tracking a code block."""
        start = self.mark(f"{name}_start", domain)
        try:
            yield start
        finally:
            end = self.mark(f"{name}_end", domain)
            diff = start.compare_to(end, 'lineno')
            if diff:
                print(f"[{name}] Memory change: {self._format_diff(diff)}")

    def _format_diff(self, diff: List[tracemalloc.StatisticDiff]) -> str:
        total = sum(d.size_diff for d in diff)
        return f"{total / 1024:.2f} KB" if total else "0 KB"

    def get_all_marks(self) -> Dict[str, MemorySnapshot]:
        return dict(self._marks)

    def clear_marks(self):
        self._marks.clear()


class SnapshotManager:
    """
    Advanced snapshot management with persistence and comparison.
    """

    def __init__(self, session: Optional[TracemallocSession] = None):
        self.session = session or TracemallocSession.get_default()
        self._snapshots: Dict[str, MemorySnapshot] = {}
        self._groups: Dict[str, List[str]] = defaultdict(list)

    def save(self, name: str, snapshot: Optional[MemorySnapshot] = None, group: str = "default"):
        """Save a snapshot by name."""
        if snapshot is None:
            snapshot = self.session.take_snapshot(name)
        self._snapshots[name] = snapshot
        self._groups[group].append(name)

    def load(self, name: str) -> Optional[MemorySnapshot]:
        """Load a saved snapshot."""
        return self._snapshots.get(name)

    def delete(self, name: str):
        """Delete a saved snapshot."""
        if name in self._snapshots:
            del self._snapshots[name]
            for group in self._groups.values():
                if name in group:
                    group.remove(name)

    def compare(self, name1: str, name2: str, key_type: str = 'lineno') -> List[tracemalloc.StatisticDiff]:
        """Compare two saved snapshots."""
        s1 = self._snapshots.get(name1)
        s2 = self._snapshots.get(name2)
        if not s1 or not s2:
            raise ValueError("Snapshot not found")
        return s1.compare_to(s2, key_type)

    def get_group(self, group: str) -> List[MemorySnapshot]:
        """Get all snapshots in a group."""
        return [self._snapshots[n] for n in self._groups.get(group, []) if n in self._snapshots]

    def list_snapshots(self) -> List[str]:
        return list(self._snapshots.keys())

    def list_groups(self) -> List[str]:
        return list(self._groups.keys())

    def export_to_file(self, name: str, filepath: Union[str, Path]):
        """Export snapshot to file (pickle)."""
        import pickle
        snapshot = self._snapshots.get(name)
        if not snapshot:
            raise ValueError(f"Snapshot {name} not found")
        with open(filepath, 'wb') as f:
            pickle.dump(snapshot, f)

    def import_from_file(self, name: str, filepath: Union[str, Path]) -> MemorySnapshot:
        """Import snapshot from file."""
        import pickle
        with open(filepath, 'rb') as f:
            snapshot = pickle.load(f)
        self.save(name, snapshot)
        return snapshot


class FilterBuilder:
    """
    Fluent builder for creating complex tracemalloc filters.
    """

    def __init__(self):
        self._filters: List[tracemalloc.Filter] = []

    def include(self, filename_pattern: str, domain: str = "default") -> 'FilterBuilder':
        """Include traces matching filename pattern."""
        self._filters.append(tracemalloc.Filter(True, filename_pattern, domain=domain))
        return self

    def exclude(self, filename_pattern: str, domain: str = "default") -> 'FilterBuilder':
        """Exclude traces matching filename pattern."""
        self._filters.append(tracemalloc.Filter(False, filename_pattern, domain=domain))
        return self

    def include_module(self, module_name: str) -> 'FilterBuilder':
        """Include traces from a specific module."""
        return self.include(f"*{module_name.replace('.', '/')}*")

    def exclude_module(self, module_name: str) -> 'FilterBuilder':
        """Exclude traces from a specific module."""
        return self.exclude(f"*{module_name.replace('.', '/')}*")

    def exclude_stdlib(self) -> 'FilterBuilder':
        """Exclude standard library traces."""
        return self.exclude("<*").exclude("*site-packages*").exclude("*dist-packages*")

    def exclude_test_files(self) -> 'FilterBuilder':
        """Exclude test file traces."""
        return self.exclude("*test*.py").exclude("*_test.py").exclude("test_*.py")

    def exclude_virtualenv(self) -> 'FilterBuilder':
        """Exclude virtual environment traces."""
        venv_paths = [
            "*venv*", "*virtualenv*", "*env*", "*conda*",
            "*site-packages*", "*dist-packages*"
        ]
        for path in venv_paths:
            self.exclude(path)
        return self

    def include_only_project(self, project_root: str) -> 'FilterBuilder':
        """Include only traces from project root."""
        return self.include(project_root).exclude_stdlib().exclude_virtualenv()

    def build(self) -> List[tracemalloc.Filter]:
        """Build the filter list."""
        return list(self._filters)

    def apply(self, snapshot: tracemalloc.Snapshot) -> tracemalloc.Snapshot:
        """Apply filters to a snapshot."""
        return snapshot.filter_traces(self._filters)


class DomainTracker:
    """
    Track memory allocations per domain (e.g., per module, component, or feature).
    """

    def __init__(self, session: Optional[TracemallocSession] = None):
        self.session = session or TracemallocSession.get_default()
        self._domains: Dict[str, DomainTracker.DomainData] = {}
        self._current_domain = "default"

    @dataclass
    class DomainData:
        filters: List[tracemalloc.Filter] = field(default_factory=list)
        snapshots: List[MemorySnapshot] = field(default_factory=list)
        total_allocations: int = 0
        total_bytes: int = 0

    def create_domain(self, name: str, *filters: tracemalloc.Filter) -> 'DomainTracker':
        """Create a new tracking domain."""
        self._domains[name] = self.DomainData(filters=list(filters))
        return self

    def set_domain(self, name: str) -> 'DomainTracker':
        """Set the current active domain."""
        if name not in self._domains:
            self.create_domain(name)
        self._current_domain = name
        return self

    def get_domain(self, name: Optional[str] = None) -> DomainData:
        """Get domain data."""
        name = name or self._current_domain
        return self._domains.get(name, self.DomainData())

    def add_filter(self, filter_obj: tracemalloc.Filter, domain: Optional[str] = None):
        """Add a filter to a domain."""
        domain = domain or self._current_domain
        self._domains.setdefault(domain, self.DomainData()).filters.append(filter_obj)

    def take_snapshot(self, label: str = "", domain: Optional[str] = None) -> MemorySnapshot:
        """Take a snapshot in a specific domain."""
        domain = domain or self._current_domain
        snapshot = self.session.take_snapshot(label, domain)
        self._domains.setdefault(domain, self.DomainData()).snapshots.append(snapshot)
        return snapshot

    def get_domain_stats(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for a domain."""
        data = self.get_domain(domain)
        if not data.snapshots:
            return {"snapshots": 0, "total_allocations": 0, "total_bytes": 0}

        latest = data.snapshots[-1]
        stats = latest.statistics('lineno')
        total_bytes = sum(s.size for s in stats)
        total_allocs = sum(s.count for s in stats)

        return {
            "snapshots": len(data.snapshots),
            "total_allocations": total_allocs,
            "total_bytes": total_bytes,
            "top_allocations": stats[:10],
        }

    def compare_domains(self, domain1: str, domain2: str, key_type: str = 'lineno') -> List[tracemalloc.StatisticDiff]:
        """Compare latest snapshots of two domains."""
        d1 = self.get_domain(domain1)
        d2 = self.get_domain(domain2)
        if not d1.snapshots or not d2.snapshots:
            raise ValueError("Both domains must have at least one snapshot")
        return d1.snapshots[-1].compare_to(d2.snapshots[-1], key_type)

    def list_domains(self) -> List[str]:
        return list(self._domains.keys())

    def clear_domain(self, domain: str):
        """Clear all data for a domain."""
        if domain in self._domains:
            del self._domains[domain]


def configure_tracemalloc(
    max_frames: int = 50,
    trace_python: bool = True,
    trace_c: bool = False,
) -> TracemallocSession:
    """
    Configure and start tracemalloc with common settings.

    Returns a configured TracemallocSession ready to use.
    """
    session = TracemallocSession(
        max_frames=max_frames,
        trace_python_allocators=trace_python,
        trace_c_allocators=trace_c,
    )
    session.start()
    return session


def get_current_memory_mb() -> float:
    """Get current process memory in MB."""
    import psutil
    return psutil.Process().memory_info().rss / 1024 / 1024


def get_traced_memory_mb() -> Tuple[float, float]:
    """Get current and peak traced memory in MB."""
    current, peak = tracemalloc.get_traced_memory()
    return current / 1024 / 1024, peak / 1024 / 1024


@contextmanager
def temporary_session(**kwargs) -> Generator[TracemallocSession, None, None]:
    """Create a temporary tracemalloc session."""
    session = TracemallocSession(**kwargs)
    session.start()
    try:
        yield session
    finally:
        session.stop()


def enable_gc_tracking():
    """Enable GC tracking for more accurate memory measurement."""
    gc.set_debug(gc.DEBUG_STATS | gc.DEBUG_LEAK)


def disable_gc_tracking():
    """Disable GC tracking."""
    gc.set_debug(0)


def collect_garbage() -> Tuple[int, int, int]:
    """Force garbage collection and return stats."""
    return gc.collect(), gc.get_count(), gc.get_threshold()
