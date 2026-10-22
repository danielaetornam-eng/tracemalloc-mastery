"""
Tests for tracemalloc_mastery package.
"""

import os
import sys
import tempfile
import tracemalloc
import unittest

# Add parent to path - MUST be before any tracemalloc_mastery imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracemalloc_mastery.analysis import (
    AllocationProfiler,
    ComparisonResult,
    GrowthAnalyzer,
    LeakDetector,
    MemoryReportGenerator,
    SnapshotComparator,
)
from tracemalloc_mastery.core import (
    DomainTracker,
    FilterBuilder,
    MemorySnapshot,
    MemoryTracker,
    SnapshotManager,
    TracemallocSession,
    configure_tracemalloc,
)
from tracemalloc_mastery.patterns import (
    MemoryGuard,
    ProfileContext,
    allocate_guard,
    memory_context,
    profile_function,
    track_memory,
)
from tracemalloc_mastery.testing import (
    LeakRegressionTest,
    MemoryBenchmark,
    MemoryBenchmarkResult,
    MemoryProfiler,
    MemoryTestCase,
    assert_memory_stable,
)
from tracemalloc_mastery.visualization import (
    AllocationTimeline,
    ConsoleReporter,
    HTMLReporter,
    MemoryFlameGraph,
    TreemapVisualizer,
)


class TestCore(unittest.TestCase):
    """Test core functionality."""

    def setUp(self):
        self.session = TracemallocSession(max_frames=20)
        self.session.start()

    def tearDown(self):
        if self.session.is_active:
            self.session.stop()

    def test_session_lifecycle(self):
        self.assertTrue(self.session.is_active)
        self.session.stop()
        self.assertFalse(self.session.is_active)

    def test_context_manager(self):
        with TracemallocSession() as session:
            self.assertTrue(session.is_active)
        self.assertFalse(session.is_active)

    def test_take_snapshot(self):
        snap = self.session.take_snapshot("test")
        self.assertIsInstance(snap, MemorySnapshot)
        self.assertEqual(snap.label, "test")

    def test_get_traced_memory(self):
        current, peak = self.session.get_traced_memory()
        self.assertIsInstance(current, int)
        self.assertIsInstance(peak, int)
        self.assertGreaterEqual(peak, current)

    def test_memory_tracker(self):
        tracker = MemoryTracker(self.session)
        tracker.mark("start")
        [list(range(100)) for _ in range(10)]
        tracker.mark("end")

        diff = tracker.compare_marks("start", "end")
        self.assertIsInstance(diff, list)

    def test_snapshot_manager(self):
        mgr = SnapshotManager(self.session)
        snap = self.session.take_snapshot("test")
        mgr.save("test_snap", snap)

        loaded = mgr.load("test_snap")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.label, "test")

    def test_filter_builder(self):
        filters = (FilterBuilder()
            .include("*mycode*")
            .exclude("*test*")
            .exclude_stdlib()
            .build())

        self.assertEqual(len(filters), 3)

    def test_domain_tracker(self):
        tracker = DomainTracker(self.session)
        tracker.create_domain("db",
            tracemalloc.Filter(True, "*db*"),
        )
        tracker.set_domain("db")
        tracker.take_snapshot("query")

        stats = tracker.get_domain_stats("db")
        self.assertEqual(stats["snapshots"], 1)

    def test_configure_tracemalloc(self):
        session = configure_tracemalloc(max_frames=30, trace_c=True)
        self.assertTrue(session.is_active)
        session.stop()


class TestAnalysis(unittest.TestCase):
    """Test analysis functionality."""

    def setUp(self):
        self.session = TracemallocSession()
        self.session.start()

    def tearDown(self):
        if self.session.is_active:
            self.session.stop()

    def test_snapshot_comparator(self):
        snap1 = self.session.take_snapshot("before")
        [list(range(1000)) for _ in range(10)]
        snap2 = self.session.take_snapshot("after")

        comparator = SnapshotComparator()
        result = comparator.compare(snap1.snapshot, snap2.snapshot)

        self.assertIsInstance(result, ComparisonResult)
        self.assertGreaterEqual(result.total_size_diff, 0)

    def test_growth_analyzer(self):
        analyzer = GrowthAnalyzer(min_growth_bytes=1000, window_size=2)

        snap1 = self.session.take_snapshot("s1")
        analyzer.add_snapshot(snap1)

        [list(range(1000)) for _ in range(50)]
        snap2 = self.session.take_snapshot("s2")
        analyzer.add_snapshot(snap2)

        summary = analyzer.get_growth_summary()
        self.assertIn("total_tracked", summary)
        self.assertIn("suspected_leaks", summary)

    def test_leak_detector(self):
        detector = LeakDetector(self.session, comparison_interval=1)

        leaks = []
        def callback(candidate):
            leaks.append(candidate)

        detector.register_callback(callback)
        detector.start_detection()

        # Create some allocations
        for i in range(3):
            _ = [list(range(1000)) for _ in range(10)]
            detector.take_snapshot(f"iter_{i}")

        detector.stop_detection()

        # Should not crash
        report = detector.get_report()
        self.assertIn("total_candidates", report)

    def test_allocation_profiler(self):
        profiler = AllocationProfiler(self.session)

        import traceback
        tb = tuple(traceback.extract_stack())
        profiler.profile_allocation(1000, tb)
        profiler.profile_allocation(2000, tb)

        stats = profiler.get_allocation_stats()
        self.assertEqual(stats["total_allocations"], 2)
        self.assertEqual(stats["total_bytes"], 3000)

        top = profiler.get_top_allocations(1)
        self.assertEqual(len(top), 1)

    def test_report_generator(self):
        snap = self.session.take_snapshot("test")
        [list(range(100)) for _ in range(10)]

        generator = MemoryReportGenerator(self.session)
        report = generator.generate_report(snap)

        self.assertIn("top_allocations", report)
        self.assertIn("statistics", report)

        text = generator.generate_text_report(snap)
        self.assertIn("MEMORY REPORT", text)

        json_report = generator.generate_json_report(snap)
        self.assertIn("top_allocations", json_report)


class TestPatterns(unittest.TestCase):
    """Test pattern utilities."""

    def setUp(self):
        self.session = TracemallocSession()
        self.session.start()

    def tearDown(self):
        if self.session.is_active:
            self.session.stop()

    def test_track_memory_decorator(self):
        @track_memory(label="test_func", log_result=False)
        def test_func():
            return [list(range(100)) for _ in range(10)]

        result = test_func()
        self.assertIsInstance(result, list)

    def test_memory_context(self):
        with memory_context(label="test_block") as ctx:
            [list(range(100)) for _ in range(10)]

        self.assertIsInstance(ctx.execution_time, float)
        self.assertGreaterEqual(ctx.execution_time, 0)
        self.assertIsInstance(ctx.memory_diff_mb, float)

    def test_memory_guard(self):
        guard = MemoryGuard(max_increase_mb=100, action='warn')
        with guard:
            [list(range(100)) for _ in range(10)]

    def test_allocate_guard(self):
        @allocate_guard(max_allocations=100000, max_bytes=10*1024*1024, action='warn')
        def test_func():
            return [list(range(100)) for _ in range(10)]

        result = test_func()
        self.assertIsInstance(result, list)

    def test_profile_function(self):
        @profile_function(include_snapshots=True, top_n=3)
        def test_func():
            return [list(range(100)) for _ in range(10)]

        result = test_func()
        self.assertIsInstance(result, ProfileContext)
        # Actually returns ProfileResult
        # Check it has the right attributes
        self.assertTrue(hasattr(result, 'memory_increase_mb'))

    def test_profile_context_nested(self):
        profiler = ProfileContext(self.session)

        with profiler.profile("outer"), profiler.profile("inner"):
            [list(range(100)) for _ in range(10)]

        summary = profiler.get_summary()
        self.assertIn("frames", summary)
        self.assertEqual(len(summary["frames"]), 1)


class TestVisualization(unittest.TestCase):
    """Test visualization utilities."""

    def setUp(self):
        self.session = TracemallocSession()
        self.session.start()
        self.snap = self.session.take_snapshot("test")
        # Add some data
        _ = [list(range(1000)) for _ in range(50)]

    def tearDown(self):
        if self.session.is_active:
            self.session.stop()

    def test_flame_graph(self):
        flame = MemoryFlameGraph(self.snap.snapshot)
        data = flame.to_dict()
        self.assertIn("name", data)
        self.assertIn("children", data)

        json_str = flame.to_json()
        self.assertIn("flamegraph", json_str)

    def test_allocation_timeline(self):
        timeline = AllocationTimeline()
        timeline.add_point("start")
        timeline.add_point("middle")
        timeline.add_point("end")

        data = timeline.get_data()
        self.assertEqual(len(data), 3)

    def test_treemap(self):
        treemap = TreemapVisualizer(self.snap.snapshot)
        data = treemap.to_dict()
        self.assertIn("name", data)

    def test_console_reporter(self):
        reporter = ConsoleReporter(use_color=False)
        # Should not crash
        reporter.report_snapshot(self.snap, top_n=5)

    def test_html_reporter(self):
        html_reporter = HTMLReporter()
        html = html_reporter.generate(self.snap, title="Test")
        self.assertIn("Memory Analysis Report", html)
        self.assertIn("text/html", html_reporter.HTML_TEMPLATE)


class TestTesting(unittest.TestCase):
    """Test testing utilities."""

    def test_memory_benchmark(self):
        def simple_func():
            return sum(range(1000))

        benchmark = MemoryBenchmark(warmup=1, gc_between=True)
        result = benchmark.run("test", simple_func, iterations=5)

        self.assertEqual(result.iterations, 5)
        self.assertGreater(result.avg_time, 0)

    def test_assert_memory_stable(self):
        def stable_func():
            return sum(range(100))

        result = assert_memory_stable(stable_func, max_increase_mb=10, iterations=10)
        self.assertEqual(result, 4950)  # sum(range(100))

    def test_memory_test_case(self):
        class DummyTest(MemoryTestCase):
            def test_something(self):
                with self.assert_memory_stable(max_increase_mb=10):
                    _ = [list(range(100)) for _ in range(10)]

        test = DummyTest()
        test.setUp()
        try:
            test.test_something()
        finally:
            test.tearDown()

    def test_memory_profiler(self):
        profiler = MemoryProfiler()

        def test_func():
            return sum(range(100))

        result = profiler.profile_test("test", test_func)
        self.assertIsInstance(result, MemoryBenchmarkResult)

        summary = profiler.get_summary()
        self.assertEqual(summary["total_tests"], 1)

    def test_leak_regression(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_file = os.path.join(tmpdir, "baseline.json")
            regression = LeakRegressionTest(baseline_file)

            def test_func():
                return sum(range(100))

            # Record baseline
            regression.record_baseline("test", test_func, iterations=5)

            # Check regression
            ok = regression.check_regression("test", test_func, iterations=5)
            self.assertTrue(ok)


class TestIntegration(unittest.TestCase):
    """Test integration utilities."""

    def test_unified_profiler(self):
        from tracemalloc_mastery.integration import UnifiedProfiler

        profiler = UnifiedProfiler()
        tools = profiler.get_available_tools()

        self.assertIn("tracemalloc", tools)
        self.assertIsInstance(tools, list)

    def test_profiler_orchestrator(self):
        from tracemalloc_mastery.integration import ProfilerOrchestrator

        orchestrator = ProfilerOrchestrator()
        orchestrator.start_all()

        snap = orchestrator.take_snapshot("test")
        self.assertIsNotNone(snap)

        results = orchestrator.stop_all()
        self.assertIn("timestamp", results)


class TestExamples(unittest.TestCase):
    """Test examples can run."""

    def test_example_runner(self):
        from tracemalloc_mastery.examples import ExampleRunner

        # Should have examples
        self.assertGreater(len(ExampleRunner.EXAMPLES), 0)

        # Check structure
        for name, func in ExampleRunner.EXAMPLES:
            self.assertIsInstance(name, str)
            self.assertTrue(callable(func))


if __name__ == "__main__":
    unittest.main()
