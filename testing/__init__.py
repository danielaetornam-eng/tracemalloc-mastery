"""
Testing and benchmarking utilities for memory analysis.
"""

import gc
import statistics
import time
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Tuple,
    TypeVar,
    Union,
)

from ..core import TracemallocSession

T = TypeVar('T')


@dataclass
class MemoryBenchmarkResult:
    """Result of a memory benchmark."""
    name: str
    iterations: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    memory_samples: List[Tuple[float, float]]  # (current_mb, peak_mb)
    avg_memory_mb: float
    peak_memory_mb: float
    memory_growth_mb: float
    allocations_per_iteration: float

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.iterations} iters, "
            f"{self.avg_time*1000:.2f}ms avg, "
            f"{self.avg_memory_mb:.2f}MB avg, "
            f"{self.peak_memory_mb:.2f}MB peak, "
            f"{self.memory_growth_mb:.2f}MB growth"
        )


class MemoryBenchmark:
    """
    Benchmark memory usage of functions.

    Usage:
        benchmark = MemoryBenchmark()
        result = benchmark.run("my_function", my_func, iterations=100)
        print(result)
    """

    def __init__(
        self,
        warmup: int = 3,
        gc_between: bool = True,
        track_allocations: bool = True,
    ):
        self.warmup = warmup
        self.gc_between = gc_between
        self.track_allocations = track_allocations
        self._session = None

    def run(
        self,
        name: str,
        func: Callable[..., T],
        *args,
        iterations: int = 10,
        **kwargs,
    ) -> MemoryBenchmarkResult:
        """Run benchmark."""
        from tracemalloc_mastery.core import TracemallocSession

        # Warmup
        for _ in range(self.warmup):
            func(*args, **kwargs)
            if self.gc_between:
                gc.collect()

        # Start tracking
        self._session = TracemallocSession(max_frames=20)
        self._session.start()

        times = []
        memory_samples = []

        initial_memory = self._session.get_traced_memory()

        for _i in range(iterations):
            if self.gc_between:
                gc.collect()

            self._session.get_traced_memory()
            start_time = time.perf_counter()

            func(*args, **kwargs)

            end_time = time.perf_counter()
            end_mem = self._session.get_traced_memory()

            times.append(end_time - start_time)
            memory_samples.append((end_mem[0] / 1024 / 1024, end_mem[1] / 1024 / 1024))

        final_memory = self._session.get_traced_memory()
        self._session.stop()

        # Calculate stats
        current_samples = [s[0] for s in memory_samples]
        peak_samples = [s[1] for s in memory_samples]

        return MemoryBenchmarkResult(
            name=name,
            iterations=iterations,
            total_time=sum(times),
            avg_time=statistics.mean(times),
            min_time=min(times),
            max_time=max(times),
            memory_samples=memory_samples,
            avg_memory_mb=statistics.mean(current_samples),
            peak_memory_mb=max(peak_samples),
            memory_growth_mb=(final_memory[0] - initial_memory[0]) / 1024 / 1024,
            allocations_per_iteration=(final_memory[0] - initial_memory[0]) / iterations if iterations else 0,
        )

    def compare(
        self,
        name: str,
        func1: Callable[..., T],
        func2: Callable[..., T],
        *args,
        iterations: int = 10,
        **kwargs,
    ) -> Tuple[MemoryBenchmarkResult, MemoryBenchmarkResult]:
        """Compare two functions."""
        result1 = self.run(f"{name}_v1", func1, *args, iterations=iterations, **kwargs)
        result2 = self.run(f"{name}_v2", func2, *args, iterations=iterations, **kwargs)
        return result1, result2

    def print_comparison(self, result1: MemoryBenchmarkResult, result2: MemoryBenchmarkResult):
        """Print comparison of two benchmarks."""
        print(f"\n{'='*60}")
        print(f"COMPARISON: {result1.name} vs {result2.name}")
        print(f"{'='*60}")
        print(f"{'Metric':<30} {result1.name:<20} {result2.name:<20} Diff")
        print(f"{'-'*60}")
        print(f"{'Avg Time (ms)':<30} {result1.avg_time*1000:<20.2f} {result2.avg_time*1000:<20.2f} {(result2.avg_time-result1.avg_time)*1000:+.2f}")
        print(f"{'Avg Memory (MB)':<30} {result1.avg_memory_mb:<20.2f} {result2.avg_memory_mb:<20.2f} {result2.avg_memory_mb-result1.avg_memory_mb:+.2f}")
        print(f"{'Peak Memory (MB)':<30} {result1.peak_memory_mb:<20.2f} {result2.peak_memory_mb:<20.2f} {result2.peak_memory_mb-result1.peak_memory_mb:+.2f}")
        print(f"{'Growth (MB)':<30} {result1.memory_growth_mb:<20.2f} {result2.memory_growth_mb:<20.2f} {result2.memory_growth_mb-result1.memory_growth_mb:+.2f}")


class MemoryTestCase(unittest.TestCase):
    """
    Base test case with memory assertions.

    Usage:
        class MyTests(MemoryTestCase):
            def test_no_leak(self):
                with self.assert_memory_stable():
                    do_operation()
    """

    def setUp(self):
        from tracemalloc_mastery.core import TracemallocSession
        self._session = TracemallocSession(max_frames=20)
        self._session.start()
        self._initial_memory = self._session.get_traced_memory()

    def tearDown(self):
        if self._session and self._session.is_active:
            self._session.stop()

    @contextmanager
    def assert_memory_stable(self, max_increase_mb: float = 1.0, max_allocations: int = 1000):
        """Assert memory doesn't grow significantly."""
        initial = self._session.get_traced_memory()
        try:
            yield
        finally:
            final = self._session.get_traced_memory()
            increase_mb = (final[0] - initial[0]) / 1024 / 1024
            alloc_count = final[0] - initial[0]  # Approximate

            self.assertLessEqual(
                increase_mb, max_increase_mb,
                f"Memory increased by {increase_mb:.2f} MB (max {max_increase_mb} MB)"
            )
            self.assertLessEqual(
                alloc_count, max_allocations,
                f"Allocation count increased by {alloc_count} (max {max_allocations})"
            )

    @contextmanager
    def assert_no_leaks(self, max_growth_mb: float = 0.5):
        """Assert no memory leaks (stricter check)."""
        initial = self._session.get_traced_memory()
        try:
            yield
        finally:
            # Force GC
            gc.collect()
            gc.collect()
            gc.collect()

            final = self._session.get_traced_memory()
            growth_mb = (final[0] - initial[0]) / 1024 / 1024

            self.assertLessEqual(
                growth_mb, max_growth_mb,
                f"Possible memory leak: {growth_mb:.2f} MB growth (max {max_growth_mb} MB)"
            )

    def assert_memory_less_than(self, max_mb: float):
        """Assert current memory is below threshold."""
        current, _ = self._session.get_traced_memory()
        current_mb = current / 1024 / 1024
        self.assertLessEqual(current_mb, max_mb, f"Memory {current_mb:.2f} MB exceeds {max_mb} MB")

    def get_memory_usage(self) -> Tuple[float, float]:
        """Get current and peak memory in MB."""
        current, peak = self._session.get_traced_memory()
        return current / 1024 / 1024, peak / 1024 / 1024


def assert_memory_stable(
    func: Callable[..., T],
    max_increase_mb: float = 1.0,
    iterations: int = 10,
    *args,
    **kwargs,
) -> T:
    """
    Assert a function doesn't leak memory.

    Usage:
        result = assert_memory_stable(my_function, max_increase_mb=0.5, iterations=100)
    """
    from tracemalloc_mastery.core import TracemallocSession

    session = TracemallocSession(max_frames=20)
    session.start()

    # Warmup
    for _ in range(3):
        func(*args, **kwargs)
    gc.collect()

    initial = session.get_traced_memory()

    for _ in range(iterations):
        result = func(*args, **kwargs)

    gc.collect()
    final = session.get_traced_memory()
    session.stop()

    increase_mb = (final[0] - initial[0]) / 1024 / 1024

    if increase_mb > max_increase_mb:
        raise AssertionError(
            f"Memory increased by {increase_mb:.2f} MB over {iterations} iterations "
            f"(max allowed: {max_increase_mb} MB)"
        )

    return result


def assert_no_leaks(
    func: Callable[..., T],
    max_growth_mb: float = 0.1,
    iterations: int = 50,
    *args,
    **kwargs,
) -> T:
    """
    Stricter leak detection.

    Usage:
        result = assert_no_leaks(my_function, max_growth_mb=0.1)
    """
    return assert_memory_stable(func, *args, max_increase_mb=max_growth_mb, iterations=iterations, **kwargs)


class MemoryProfiler:
    """
    Profile memory usage across test suite.
    """

    def __init__(self):
        self._results: Dict[str, MemoryBenchmarkResult] = {}
        self._session = None

    def profile_test(self, test_name: str, test_func: Callable):
        """Profile a single test."""
        benchmark = MemoryBenchmark(warmup=1, gc_between=True)
        result = benchmark.run(test_name, test_func, iterations=1)
        self._results[test_name] = result
        return result

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all profiled tests."""
        if not self._results:
            return {}

        total_time = sum(r.total_time for r in self._results.values())
        total_memory = sum(r.avg_memory_mb for r in self._results.values())

        return {
            "total_tests": len(self._results),
            "total_time": total_time,
            "avg_memory_mb": total_memory / len(self._results),
            "max_memory_mb": max(r.peak_memory_mb for r in self._results.values()),
            "tests": {name: str(result) for name, result in self._results.items()},
        }

    def print_summary(self):
        """Print summary."""
        summary = self.get_summary()
        print(f"\n{'='*60}")
        print("MEMORY PROFILE SUMMARY")
        print(f"{'='*60}")
        print(f"Tests profiled: {summary['total_tests']}")
        print(f"Total time: {summary['total_time']:.2f}s")
        print(f"Avg memory: {summary['avg_memory_mb']:.2f} MB")
        print(f"Max memory: {summary['max_memory_mb']:.2f} MB")
        print()
        for _name, result_str in summary['tests'].items():
            print(f"  {result_str}")


class LeakRegressionTest:
    """
    Regression test for memory leaks.

    Captures baseline memory profile and compares against future runs.
    """

    def __init__(self, baseline_file: Union[str, Path] = "memory_baseline.json"):
        self.baseline_file = Path(baseline_file)
        self.baseline: Dict[str, Any] = {}
        self._load_baseline()

    def _load_baseline(self):
        if self.baseline_file.exists():
            import json
            with open(self.baseline_file) as f:
                self.baseline = json.load(f)

    def _save_baseline(self):
        import json
        with open(self.baseline_file, 'w') as f:
            json.dump(self.baseline, f, indent=2)

    def record_baseline(self, name: str, func: Callable, iterations: int = 10):
        """Record baseline for a function."""
        benchmark = MemoryBenchmark()
        result = benchmark.run(name, func, iterations=iterations)

        self.baseline[name] = {
            "avg_time": result.avg_time,
            "avg_memory_mb": result.avg_memory_mb,
            "peak_memory_mb": result.peak_memory_mb,
            "memory_growth_mb": result.memory_growth_mb,
            "iterations": iterations,
            "timestamp": time.time(),
        }
        self._save_baseline()

    def check_regression(self, name: str, func: Callable, iterations: int = 10,
                         time_threshold: float = 1.5, memory_threshold: float = 1.5) -> bool:
        """Check for regression against baseline."""
        if name not in self.baseline:
            print(f"No baseline for {name}, recording new baseline")
            self.record_baseline(name, func, iterations)
            return True

        benchmark = MemoryBenchmark()
        result = benchmark.run(name, func, iterations=iterations)

        base = self.baseline[name]

        time_ratio = result.avg_time / base["avg_time"]
        memory_ratio = result.avg_memory_mb / base["avg_memory_mb"]
        growth_ratio = result.memory_growth_mb / max(base["memory_growth_mb"], 0.001)

        regressed = False
        if time_ratio > time_threshold:
            print(f"TIME REGRESSION: {name} - {time_ratio:.2f}x slower")
            regressed = True
        if memory_ratio > memory_threshold:
            print(f"MEMORY REGRESSION: {name} - {memory_ratio:.2f}x more memory")
            regressed = True
        if growth_ratio > memory_threshold:
            print(f"GROWTH REGRESSION: {name} - {growth_ratio:.2f}x more growth")
            regressed = True

        if not regressed:
            print(f"OK: {name} - no regression detected")

        return not regressed


# Pytest fixtures
def pytest_memory_session():
    """Pytest fixture for memory tracking."""
    session = TracemallocSession()
    session.start()
    yield session
    session.stop()


def pytest_memory_tracker():
    """Pytest fixture for memory tracking."""
    from ..core import MemoryTracker
    tracker = MemoryTracker()
    yield tracker


# Decorators for pytest
def memory_test(max_increase_mb: float = 1.0):
    """Decorator to mark a test as memory-checked."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return assert_memory_stable(func, *args, max_increase_mb=max_increase_mb, **kwargs)
        return wrapper
    return decorator


def no_leaks(max_growth_mb: float = 0.1):
    """Decorator to assert no memory leaks."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return assert_no_leaks(func, *args, max_growth_mb=max_growth_mb, **kwargs)
        return wrapper
    return decorator
