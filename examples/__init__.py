"""
Real-world examples and use cases for tracemalloc mastery.
"""

import asyncio
import json
import random
import time
import tracemalloc
from typing import (
    Any,
    List,
)

from tracemalloc_mastery.analysis import (
    AllocationProfiler,
    GrowthAnalyzer,
    LeakDetector,
    MemoryReportGenerator,
    SnapshotComparator,
)

# Import from our modules
from tracemalloc_mastery.core import (
    DomainTracker,
    FilterBuilder,
    MemoryTracker,
    configure_tracemalloc,
)
from tracemalloc_mastery.patterns import (
    MemoryGuard,
    ProfileContext,
    memory_context,
    profile_function,
    track_memory,
)
from tracemalloc_mastery.visualization import (
    AllocationTimeline,
    ConsoleReporter,
    HTMLReporter,
    MemoryFlameGraph,
)

# ============================================================================
# Example 1: Basic Memory Tracking
# ============================================================================

def example_basic_tracking():
    """Basic memory tracking with tracemalloc."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic Memory Tracking")
    print("="*60)

    session = configure_tracemalloc(max_frames=20)

    # Track memory for a simple operation
    data = []
    snapshot1 = session.take_snapshot("before_allocation")

    # Allocate some memory
    for i in range(10000):
        data.append({"id": i, "data": "x" * 100})

    snapshot2 = session.take_snapshot("after_allocation")

    # Compare
    comparator = SnapshotComparator()
    diff = comparator.compare(snapshot1.snapshot, snapshot2.snapshot)

    print(f"Memory increase: {diff.total_size_diff_mb:.2f} MB")
    print(f"Allocation count increase: {diff.total_count_diff}")

    # Show top allocations
    for d in diff.get_top_changes(5, 'size'):
        print(f"  +{d.size_diff_mb:.2f} MB: {d.statistic.traceback[0] if d.statistic.traceback else 'unknown'}")

    session.stop()


# ============================================================================
# Example 2: Context Manager Tracking
# ============================================================================

def example_context_manager():
    """Using context manager for memory tracking."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Context Manager Tracking")
    print("="*60)

    session = configure_tracemalloc()

    with memory_context(label="data_processing") as ctx:
        # Simulate data processing
        data = [list(range(1000)) for _ in range(100)]
        [sum(x) for x in data]
        time.sleep(0.1)

    print(f"Execution time: {ctx.execution_time*1000:.2f} ms")
    print(f"Memory increase: {ctx.memory_diff_mb:.2f} MB")
    print(f"Allocations: {ctx.count_diff}")

    session.stop()


# ============================================================================
# Example 3: Decorator-based Profiling
# ============================================================================

@track_memory(label="process_data", top_n=5)
def process_data(items: List[int]) -> List[int]:
    """Process data with automatic memory tracking."""
    result = []
    for item in items:
        # Simulate some processing
        temp = [item * i for i in range(100)]
        result.append(sum(temp))
    return result


@profile_function(include_snapshots=True, top_n=3)
def complex_computation(n: int) -> list:
    """Function that returns detailed profile result."""
    data = []
    for i in range(n):
        data.append({"id": i, "matrix": [[j*k for k in range(10)] for j in range(10)]})
    return data


def example_decorators():
    """Demonstrate decorator-based memory profiling."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Decorator-based Profiling")
    print("="*60)

    configure_tracemalloc()

    # Track memory decorator
    process_data(list(range(100)))

    # Profile function decorator
    profile_result = complex_computation(50)
    print(f"\nFunction: {profile_result.function_name}")
    print(f"Time: {profile_result.execution_time*1000:.2f} ms")
    print(f"Memory increase: {profile_result.memory_increase_mb:.2f} MB")
    print(f"Peak increase: {profile_result.peak_increase_mb:.2f} MB")
    print("Top diffs:")
    for d in profile_result.top_diffs:
        print(f"  {d.size_diff_mb:.2f} MB: {d.statistic.traceback[0] if d.statistic.traceback else 'unknown'}")


# ============================================================================
# Example 4: Memory Guard
# ============================================================================

def example_memory_guard():
    """Using MemoryGuard to enforce memory limits."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Memory Guard")
    print("="*60)

    configure_tracemalloc()

    # Guard with warning
    guard = MemoryGuard(max_memory_mb=50, max_increase_mb=10, action='warn')

    with guard:
        data = []
        for _i in range(10000):
            data.append("x" * 1000)  # ~1KB each

    print("Completed within memory limits")

    # Guard that raises
    try:
        with MemoryGuard(max_increase_mb=1, action='raise'):
            ["x" * 100000 for _ in range(100)]  # This should exceed 1MB
    except MemoryError as e:
        print(f"Memory guard triggered: {e}")


# ============================================================================
# Example 5: Leak Detection
# ============================================================================

def example_leak_detection():
    """Demonstrate memory leak detection."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Leak Detection")
    print("="*60)

    session = configure_tracemalloc()
    detector = LeakDetector(session, comparison_interval=1, min_leak_size=10000)

    # Register callback for detected leaks
    leaks_found = []
    def on_leak(candidate):
        leaks_found.append(candidate)
        print(f"LEAK DETECTED: {candidate.description} (confidence: {candidate.confidence:.0%})")

    detector.register_callback(on_leak)
    detector.start_detection()

    # Simulate a leak
    leaked_data = []
    for i in range(5):
        detector.take_snapshot(f"iteration_{i}")
        # This simulates a leak - data accumulates
        leaked_data.extend([{"id": j, "data": "x" * 1000} for j in range(100)])
        time.sleep(1.5)

    detector.stop_detection()

    # Get report
    report = detector.get_report()
    print(f"\nLeak report: {report['high_confidence']} high-confidence candidates")

    session.stop()


# ============================================================================
# Example 6: Growth Analysis
# ============================================================================

def example_growth_analysis():
    """Analyze memory growth patterns."""
    print("\n" + "="*60)
    print("EXAMPLE 6: Growth Analysis")
    print("="*60)

    session = configure_tracemalloc()
    analyzer = GrowthAnalyzer(min_growth_bytes=5000, min_growth_percent=5.0, window_size=3)

    # Simulate growing allocations
    data_store = {}
    for i in range(10):
        snapshot = session.take_snapshot(f"step_{i}")
        analyzer.add_snapshot(snapshot)

        # Add growing data
        data_store[f"key_{i}"] = ["x" * 1000 for _ in range(i * 10 + 10)]
        time.sleep(0.2)

    summary = analyzer.get_growth_summary()
    print(f"Tracked allocations: {summary['total_tracked']}")
    print(f"Suspected leaks: {summary['suspected_leaks']}")
    print(f"Total growth: {summary['total_growth_bytes']/1024:.1f} KB")

    print("\nTop growing allocations:")
    for record in summary['top_growing'][:5]:
        print(f"  Rate: {record.growth_rate_bps/1024:.1f} KB/s - {record.traceback[0] if record.traceback else 'unknown'}")

    session.stop()


# ============================================================================
# Example 7: Domain Tracking
# ============================================================================

def example_domain_tracking():
    """Track memory per domain/component."""
    print("\n" + "="*60)
    print("EXAMPLE 7: Domain Tracking")
    print("="*60)

    session = configure_tracemalloc()
    tracker = DomainTracker(session)

    # Create domains
    tracker.create_domain("database",
        tracemalloc.Filter(True, "*database*"),
        tracemalloc.Filter(True, "*sql*"),
    )
    tracker.create_domain("cache",
        tracemalloc.Filter(True, "*cache*"),
    )
    tracker.create_domain("api",
        tracemalloc.Filter(True, "*api*"),
        tracemalloc.Filter(True, "*http*"),
    )

    # Simulate work in different domains
    for domain_name in ["database", "cache", "api"]:
        tracker.set_domain(domain_name)
        for i in range(5):
            tracker.take_snapshot(f"{domain_name}_op_{i}")
            # Simulate domain-specific allocations
            if domain_name == "database":
                _ = [{"query": f"SELECT * FROM t{i}", "rows": list(range(100))} for _ in range(10)]
            elif domain_name == "cache":
                _ = {f"key_{j}": "x" * 1000 for j in range(50)}
            elif domain_name == "api":
                _ = [{"endpoint": f"/api/{i}", "payload": "x" * 500} for _ in range(20)]

    # Compare domains
    print("Domain statistics:")
    for domain in tracker.list_domains():
        stats = tracker.get_domain_stats(domain)
        print(f"  {domain}: {stats['total_bytes']/1024:.1f} KB, {stats['total_allocations']} allocs, {stats['snapshots']} snapshots")

    # Compare database vs cache
    diff = tracker.compare_domains("database", "cache")
    print(f"\nDatabase vs Cache: {sum(d.size_diff for d in diff)/1024:.1f} KB difference")

    session.stop()


# ============================================================================
# Example 8: Filter Builder
# ============================================================================

def example_filter_builder():
    """Advanced filtering with FilterBuilder."""
    print("\n" + "="*60)
    print("EXAMPLE 8: Filter Builder")
    print("="*60)

    session = configure_tracemalloc()

    # Build custom filters
    filters = (FilterBuilder()
        .include_only_project("/path/to/project")
        .exclude_test_files()
        .build())

    # Take snapshot and apply filters
    snapshot = session.take_snapshot("raw")
    filtered = snapshot.filter_traces(filters)

    print(f"Raw allocations: {len(snapshot.statistics('lineno'))}")
    print(f"Filtered allocations: {len(filtered.statistics('lineno'))}")

    # Show top filtered
    print("\nTop filtered allocations:")
    for stat in filtered.top_allocations(5):
        print(f"  {stat.size/1024:.1f} KB: {stat.traceback[0] if stat.traceback else 'unknown'}")

    session.stop()


# ============================================================================
# Example 9: Allocation Profiling
# ============================================================================

def example_allocation_profiling():
    """Profile allocation patterns."""
    print("\n" + "="*60)
    print("EXAMPLE 9: Allocation Profiling")
    print("="*60)

    session = configure_tracemalloc()
    profiler = AllocationProfiler(session)

    # Simulate various allocations
    def allocate_small():
        return [1, 2, 3]

    def allocate_medium():
        return list(range(1000))

    def allocate_large():
        return ["x" * 1000 for _ in range(100)]

    # Profile allocations manually (in real use, hook into allocator)
    import traceback
    for _ in range(100):
        profiler.profile_allocation(100, tuple(traceback.extract_stack()))
    for _ in range(50):
        profiler.profile_allocation(10000, tuple(traceback.extract_stack()))
    for _ in range(10):
        profiler.profile_allocation(100000, tuple(traceback.extract_stack()))

    stats = profiler.get_allocation_stats()
    print(f"Total allocations: {stats['total_allocations']}")
    print(f"Total bytes: {stats['total_bytes']/1024:.1f} KB")
    print(f"Unique traces: {stats['unique_traces']}")

    print("\nTop by total size:")
    for alloc in profiler.get_top_allocations(5, 'total_size'):
        print(f"  {alloc.total_size/1024:.1f} KB ({alloc.count} allocs, avg {alloc.avg_size:.0f}B)")

    print("\nHotspots (>5%):")
    for hotspot in profiler.find_hotspots(5.0):
        print(f"  {hotspot.total_size/1024:.1f} KB ({hotspot.count} allocs)")

    session.stop()


# ============================================================================
# Example 10: Visualization
# ============================================================================

def example_visualization():
    """Generate visualizations."""
    print("\n" + "="*60)
    print("EXAMPLE 10: Visualization")
    print("="*60)

    session = configure_tracemalloc()

    # Create some allocations
    [{"id": i, "data": "x" * 1000} for i in range(1000)]
    snapshot = session.take_snapshot("visualization_demo")

    # Console reporter
    reporter = ConsoleReporter(use_color=True)
    reporter.report_snapshot(snapshot, top_n=10)

    # Flame graph
    flame = MemoryFlameGraph(snapshot.snapshot)
    print("\nFlame Graph (text):")
    flame.print_text(max_depth=10, min_size_mb=0.01)

    # Export for Speedscope
    try:
        flame.to_speedscope("flamegraph.speedscope.json")
        print("\nExported flamegraph.speedscope.json (open in https://speedscope.app)")
    except Exception as e:
        print(f"Flamegraph export failed: {e}")

    # Timeline
    timeline = AllocationTimeline()
    timeline.add_point("start")
    for i in range(5):
        _ = [list(range(1000)) for _ in range(10)]
        timeline.add_point(f"iteration_{i}")
        time.sleep(0.1)
    timeline.add_point("end")

    try:
        timeline.plot("timeline.png")
        print("Exported timeline.png")
    except Exception as e:
        print(f"Timeline plot failed: {e} (matplotlib/squarify may not be installed)")

    # HTML Report
    html_reporter = HTMLReporter()
    html = html_reporter.generate(snapshot, title="Memory Analysis Report")
    with open("report.html", 'w') as f:
        f.write(html)
    print("Exported report.html")

    session.stop()


# ============================================================================
# Example 11: Async Memory Tracking
# ============================================================================

async def async_operation(name: str, delay: float):
    """Simulate async operation with allocations."""
    data = [f"{name}_{i}" * 100 for i in range(100)]
    await asyncio.sleep(delay)
    return len(data)


async def example_async_tracking():
    """Track memory in async code."""
    print("\n" + "="*60)
    print("EXAMPLE 11: Async Memory Tracking")
    print("="*60)

    session = configure_tracemalloc()

    from .patterns import AsyncMemoryTracker
    tracker = AsyncMemoryTracker(session)

    # Track multiple concurrent operations
    async def run_tracked():
        tasks = []
        for i in range(5):
            task = asyncio.create_task(async_operation(f"task_{i}", 0.1))
            tasks.append(task)

        # Track each task
        for i, task in enumerate(tasks):
            with tracker.track(f"task_{i}"):
                await task

        return tasks

    await run_tracked()

    # Get results
    for _task_id, result in tracker._tasks.items():
        if result.snapshot_end:
            from .analysis import SnapshotComparator
            comparator = SnapshotComparator()
            diff = comparator.compare(result.snapshot_start, result.snapshot_end)
            print(f"Task {result.name}: {diff.total_size_diff_mb:.2f} MB increase")

    session.stop()


# ============================================================================
# Example 12: Profile Context (Nested)
# ============================================================================

def example_nested_profiling():
    """Nested profiling with ProfileContext."""
    print("\n" + "="*60)
    print("EXAMPLE 12: Nested Profiling")
    print("="*60)

    session = configure_tracemalloc()
    profiler = ProfileContext(session)

    with profiler.profile("main_operation"):
        with profiler.profile("step_1_data_loading"):
            data = [list(range(1000)) for _ in range(10)]

        with profiler.profile("step_2_processing"):
            processed = [sum(x) for x in data]

        with profiler.profile("step_3_aggregation"):
            {"sum": sum(processed), "avg": sum(processed)/len(processed)}

    summary = profiler.get_summary()
    print(json.dumps(summary, indent=2, default=str))

    session.stop()


# ============================================================================
# Example 13: Real-world - Cache Memory Analysis
# ============================================================================

class LRUCache:
    """Simple LRU cache for demonstration."""

    def __init__(self, maxsize: int = 100):
        self.maxsize = maxsize
        self._cache = {}
        self._access_times = {}
        self._counter = 0

    def get(self, key: str) -> Any:
        self._counter += 1
        if key in self._cache:
            self._access_times[key] = self._counter
            return self._cache[key]
        return None

    def set(self, key: str, value: Any):
        self._counter += 1
        if len(self._cache) >= self.maxsize:
            # Evict LRU
            lru = min(self._access_times, key=self._access_times.get)
            del self._cache[lru]
            del self._access_times[lru]
        self._cache[key] = value
        self._access_times[key] = self._counter


@track_memory(label="cache_operations")
def simulate_cache_workload(cache: LRUCache, operations: int = 1000):
    """Simulate cache workload."""
    for _i in range(operations):
        key = f"key_{random.randint(0, 200)}"
        if random.random() < 0.7:
            cache.get(key)
        else:
            cache.set(key, {"data": "x" * 1000, "meta": {"created": time.time()}})


def example_cache_analysis():
    """Analyze cache memory usage."""
    print("\n" + "="*60)
    print("EXAMPLE 13: Cache Memory Analysis")
    print("="*60)

    session = configure_tracemalloc()
    cache = LRUCache(maxsize=500)

    # Baseline
    snapshot1 = session.take_snapshot("cache_empty")

    # Fill cache
    simulate_cache_workload(cache, 2000)
    snapshot2 = session.take_snapshot("cache_filled")

    # More operations
    simulate_cache_workload(cache, 5000)
    snapshot3 = session.take_snapshot("cache_heavy_use")

    # Compare
    comparator = SnapshotComparator()
    diff1 = comparator.compare(snapshot1.snapshot, snapshot2.snapshot)
    diff2 = comparator.compare(snapshot2.snapshot, snapshot3.snapshot)

    print(f"Initial fill: {diff1.total_size_diff_mb:.2f} MB")
    print(f"Heavy usage: {diff2.total_size_diff_mb:.2f} MB")

    # Analyze growth
    analyzer = GrowthAnalyzer()
    analyzer.add_snapshot(snapshot1)
    analyzer.add_snapshot(snapshot2)
    analyzer.add_snapshot(snapshot3)

    summary = analyzer.get_growth_summary()
    print(f"Suspected leaks in cache: {summary['suspected_leaks']}")

    session.stop()


# ============================================================================
# Example 14: Data Pipeline Memory Analysis
# ============================================================================

def example_data_pipeline():
    """Analyze memory in data processing pipeline."""
    print("\n" + "="*60)
    print("EXAMPLE 14: Data Pipeline Analysis")
    print("="*60)

    session = configure_tracemalloc()
    tracker = MemoryTracker(session)

    def load_data():
        return [{"id": i, "values": [random.random() for _ in range(100)]} for i in range(1000)]

    def transform(data):
        return [{**d, "processed": sum(d["values"])} for d in data]

    def aggregate(data):
        return {
            "total": sum(d["processed"] for d in data),
            "count": len(data),
            "avg": sum(d["processed"] for d in data) / len(data),
        }

    with tracker.track("load"):
        raw_data = load_data()

    with tracker.track("transform"):
        transformed = transform(raw_data)

    with tracker.track("aggregate"):
        aggregate(transformed)

    # Compare all stages
    marks = tracker.get_all_marks()
    SnapshotComparator()

    stages = ["load_start", "load_end", "transform_start", "transform_end", "aggregate_start", "aggregate_end"]
    for i in range(0, len(stages), 2):
        if stages[i] in marks and stages[i+1] in marks:
            diff = marks[stages[i]].compare_to(marks[stages[i+1]], 'lineno')
            print(f"{stages[i].replace('_start', '')}: {sum(d.size_diff for d in diff)/1024/1024:.2f} MB")

    session.stop()


# ============================================================================
# Example 15: Comprehensive Report Generation
# ============================================================================

def example_comprehensive_report():
    """Generate comprehensive memory report."""
    print("\n" + "="*60)
    print("EXAMPLE 15: Comprehensive Report")
    print("="*60)

    session = configure_tracemalloc()
    reporter = MemoryReportGenerator(session)

    # Create various allocations
    {
        "users": [{"id": i, "name": f"user_{i}", "data": "x" * 500} for i in range(1000)],
        "orders": [{"id": i, "items": list(range(10))} for i in range(500)],
        "logs": ["log entry " + "x" * 200 for _ in range(2000)],
    }

    snapshot = session.take_snapshot("comprehensive_demo")

    # Generate reports
    text_report = reporter.generate_text_report(snapshot)
    print(text_report[:2000] + "..." if len(text_report) > 2000 else text_report)

    json_report = reporter.generate_json_report(snapshot)
    with open("memory_report.json", 'w') as f:
        f.write(json_report)
    print("\nSaved memory_report.json")

    # HTML report
    html_reporter = HTMLReporter()
    html = html_reporter.generate(snapshot, title="Comprehensive Memory Report")
    with open("memory_report.html", 'w') as f:
        f.write(html)
    print("Saved memory_report.html")

    session.stop()


# ============================================================================
# Example Runner
# ============================================================================

class ExampleRunner:
    """Run all examples."""

    EXAMPLES = [
        ("Basic Tracking", example_basic_tracking),
        ("Context Manager", example_context_manager),
        ("Decorators", example_decorators),
        ("Memory Guard", example_memory_guard),
        ("Leak Detection", example_leak_detection),
        ("Growth Analysis", example_growth_analysis),
        ("Domain Tracking", example_domain_tracking),
        ("Filter Builder", example_filter_builder),
        ("Allocation Profiling", example_allocation_profiling),
        ("Visualization", example_visualization),
        ("Nested Profiling", example_nested_profiling),
        ("Cache Analysis", example_cache_analysis),
        ("Data Pipeline", example_data_pipeline),
        ("Comprehensive Report", example_comprehensive_report),
    ]

    @classmethod
    def run_all(cls, skip: List[str] = None):
        """Run all examples."""
        skip = skip or []
        for name, func in cls.EXAMPLES:
            if name in skip:
                print(f"\nSkipping: {name}")
                continue
            try:
                print(f"\n{'='*60}")
                print(f"Running: {name}")
                print(f"{'='*60}")
                func()
            except Exception as e:
                print(f"Error in {name}: {e}")
                import traceback
                traceback.print_exc()

    @classmethod
    def run(cls, name: str):
        """Run a specific example by name."""
        for n, func in cls.EXAMPLES:
            if n.lower() == name.lower():
                func()
                return
        print(f"Example not found: {name}")
        print("Available:", ", ".join(n for n, _ in cls.EXAMPLES))


# ============================================================================
# Main entry point
# ============================================================================

def run_all_examples():
    """Run all examples."""
    ExampleRunner.run_all()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ExampleRunner.run(sys.argv[1])
    else:
        run_all_examples()
