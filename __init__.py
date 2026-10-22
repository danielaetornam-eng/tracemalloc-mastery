"""
tracemalloc_mastery - The God-Tier Tracemalloc Mastery Codebase

Covers 99.99% of tracemalloc concepts from basics to advanced patterns.
"""

__version__ = "1.0.0"
__author__ = "tracemalloc_mastery"
__all__ = [
    "core",
    "analysis",
    "patterns",
    "visualization",
    "integration",
    "examples",
    "testing",
    "cli",
]

from .analysis import (
    AllocationProfiler,
    GrowthAnalyzer,
    LeakDetector,
    MemoryReportGenerator,
    SnapshotComparator,
)
from .core import (
    DomainTracker,
    FilterBuilder,
    MemoryTracker,
    SnapshotManager,
    TracemallocSession,
)
from .examples import (
    ExampleRunner,
    run_all_examples,
)
from .integration import (
    MemrayIntegration,
    ObjgraphIntegration,
    PymplerIntegration,
    PySpyIntegration,
)
from .patterns import (
    MemoryGuard,
    ProfileContext,
    allocate_guard,
    memory_context,
    profile_function,
    track_memory,
)
from .testing import (
    MemoryBenchmark,
    MemoryTestCase,
    assert_memory_stable,
    assert_no_leaks,
)
from .visualization import (
    AllocationTimeline,
    ConsoleReporter,
    HTMLReporter,
    MemoryFlameGraph,
    TreemapVisualizer,
)

__all__ = [
    "TracemallocSession",
    "MemoryTracker",
    "SnapshotManager",
    "FilterBuilder",
    "DomainTracker",
    "SnapshotComparator",
    "LeakDetector",
    "GrowthAnalyzer",
    "AllocationProfiler",
    "MemoryReportGenerator",
    "track_memory",
    "memory_context",
    "MemoryGuard",
    "allocate_guard",
    "profile_function",
    "ProfileContext",
    "MemoryFlameGraph",
    "AllocationTimeline",
    "TreemapVisualizer",
    "ConsoleReporter",
    "HTMLReporter",
    "PySpyIntegration",
    "MemrayIntegration",
    "ObjgraphIntegration",
    "PymplerIntegration",
    "MemoryTestCase",
    "assert_memory_stable",
    "assert_no_leaks",
    "MemoryBenchmark",
    "run_all_examples",
    "ExampleRunner",
]
