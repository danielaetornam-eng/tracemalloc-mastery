# tracemalloc_mastery

**God-tier tracemalloc memory analysis toolkit** - Covers 99.99% of tracemalloc concepts from basics to advanced patterns.

## Features

- **Core Fundamentals**: Session management, snapshot handling, filter building, domain tracking
- **Advanced Analysis**: Snapshot comparison, growth analysis, leak detection, allocation profiling
- **Patterns & Decorators**: Context managers, function decorators, memory guards, nested profiling
- **Visualizations**: Flame graphs, timelines, treemaps, console/HTML reports
- **Tool Integration**: py-spy, memray, objgraph, pympler unified interface
- **Testing Utilities**: Memory benchmarks, leak regression tests, pytest fixtures
- **CLI**: Full command-line interface for all operations

## Installation

```bash
# Basic installation
pip install tracemalloc-mastery

# With visualization support
pip install tracemalloc-mastery[visualization]

# With external profiling tools
pip install tracemalloc-mastery[profiling]

# Everything
pip install tracemalloc-mastery[all]
```

## Quick Start

### Python API

```python
from tracemalloc_mastery import (
    configure_tracemalloc, track_memory, memory_context,
    MemoryGuard, LeakDetector, ConsoleReporter
)

# Basic tracking
session = configure_tracemalloc()
snapshot = session.take_snapshot("baseline")
# ... do work ...
session.take_snapshot("after")
session.stop()

# Decorator-based profiling
@track_memory(label="my_function")
def my_function():
    data = [list(range(1000)) for _ in range(100)]
    return sum(len(d) for d in data)

# Context manager
with memory_context(label="data_processing") as ctx:
    process_data()
print(f"Memory: {ctx.memory_diff_mb:.2f} MB")

# Memory guard
with MemoryGuard(max_increase_mb=10, action='raise'):
    risky_operation()

# Leak detection
detector = LeakDetector(session)
detector.start_detection()
# ... run code ...
detector.stop_detection()
for leak in detector.get_leak_candidates():
    print(f"Leak: {leak.description}")

# Reporting
reporter = ConsoleReporter()
reporter.report_snapshot(snapshot)
```

### Command Line

```bash
# Run script with memory tracking
tracemalloc-mastery run --script my_script.py --output reports/

# Profile running process
tracemalloc-mastery profile --pid 1234 --duration 30 --tools py-spy memray

# Analyze snapshot
tracemalloc-mastery analyze --snapshot snapshot.pkl --format html --output report.html

# Detect leaks
tracemalloc-mastery leak-detect --script my_app.py --duration 60 --threshold 1MB

# Generate visualizations
tracemalloc-mastery visualize --snapshot snapshot.pkl --flamegraph --treemap --html

# Benchmark function
tracemalloc-mastery benchmark --func my_module:my_function --iterations 100

# Run examples
tracemalloc-mastery examples --list
tracemalloc-mastery examples --run basic_tracking
tracemalloc-mastery examples --all
```

## Architecture

```
tracemalloc_mastery/
├── core/              # Fundamental tracemalloc wrappers
│   ├── TracemallocSession    # High-level session management
│   ├── MemoryTracker         # Mark-based tracking
│   ├── SnapshotManager       # Persistent snapshots
│   ├── FilterBuilder         # Fluent filter construction
│   └── DomainTracker         # Per-component tracking
├── analysis/          # Deep analysis tools
│   ├── SnapshotComparator    # Rich comparison
│   ├── GrowthAnalyzer        # Growth pattern detection
│   ├── LeakDetector          # Automated leak detection
│   ├── AllocationProfiler    # Allocation pattern analysis
│   └── MemoryReportGenerator # Multi-format reports
├── patterns/          # Decorators & context managers
│   ├── track_memory          # Function decorator
│   ├── memory_context        # Block context manager
│   ├── MemoryGuard           # Limit enforcement
│   ├── allocate_guard        # Allocation limits
│   ├── profile_function      # Detailed profiling
│   └── ProfileContext        # Nested profiling
├── visualization/     # Visual output
│   ├── MemoryFlameGraph      # Flame graphs (speedscope)
│   ├── AllocationTimeline    # Time-series plots
│   ├── TreemapVisualizer     # Treemaps
│   ├── ConsoleReporter       # Rich console output
│   └── HTMLReporter          # Interactive HTML
├── integration/       # External tool bridges
│   ├── PySpyIntegration
│   ├── MemrayIntegration
│   ├── ObjgraphIntegration
│   ├── PymplerIntegration
│   └── UnifiedProfiler
├── examples/          # Real-world examples
├── testing/           # Test utilities
│   ├── MemoryBenchmark
│   ├── MemoryTestCase
│   ├── LeakRegressionTest
│   └── pytest fixtures
└── cli/               # Command-line interface
```

## Examples

Run the built-in examples:

```bash
# List all examples
tracemalloc-mastery examples --list

# Run specific example
tracemalloc-mastery examples --run leak_detection

# Run all examples
tracemalloc-mastery examples --all
```

Available examples:
- `basic_tracking` - Fundamental snapshot comparison
- `context_manager` - Block-level tracking
- `decorators` - Function decorators
- `memory_guard` - Limit enforcement
- `leak_detection` - Automated leak detection
- `growth_analysis` - Growth pattern analysis
- `domain_tracking` - Per-component tracking
- `filter_builder` - Advanced filtering
- `allocation_profiling` - Allocation hotspots
- `visualization` - Flame graphs, timelines, HTML
- `nested_profiling` - Hierarchical profiling
- `cache_analysis` - Real-world cache memory
- `data_pipeline` - Pipeline stage analysis
- `comprehensive_report` - Full report generation

## Testing

```python
from tracemalloc_mastery import MemoryTestCase, assert_memory_stable, assert_no_leaks

class MyTests(MemoryTestCase):
    def test_no_leak(self):
        with self.assert_memory_stable(max_increase_mb=1.0):
            do_operation()
    
    def test_strict_no_leak(self):
        with self.assert_no_leaks(max_growth_mb=0.1):
            do_operation()

# Or as decorators
@assert_memory_stable(max_increase_mb=0.5)
def test_my_function():
    ...

@no_leaks(max_growth_mb=0.1)
def test_strict():
    ...
```

## Benchmarking

```python
from tracemalloc_mastery import MemoryBenchmark

benchmark = MemoryBenchmark(warmup=3, gc_between=True)
result = benchmark.run("my_function", my_func, iterations=100)
print(result)
# my_function: 100 iters, 12.34ms avg, 45.67MB avg, 52.10MB peak, 0.12MB growth

# Compare two implementations
result1, result2 = benchmark.compare("sort", quicksort, mergesort, data)
benchmark.print_comparison(result1, result2)
```

## Leak Regression Testing

```python
from tracemalloc_mastery import LeakRegressionTest

regression = LeakRegressionTest("baseline.json")

# Record baseline (run once)
regression.record_baseline("process_data", process_data, iterations=50)

# Check for regressions (run in CI)
if not regression.check_regression("process_data", process_data):
    print("REGRESSION DETECTED!")
    exit(1)
```

## Visualization

### Flame Graphs
```python
from tracemalloc_mastery import MemoryFlameGraph

flame = MemoryFlameGraph(snapshot.snapshot)
flame.print_text(max_depth=15, min_size_mb=0.1)
flame.to_speedscope("flamegraph.speedscope.json")  # Open in https://speedscope.app
```

### Timeline
```python
from tracemalloc_mastery import AllocationTimeline

timeline = AllocationTimeline()
timeline.start(session, interval=0.5)
# ... run code ...
timeline.stop()
timeline.plot("timeline.png")
timeline.export_json("timeline.json")
```

### HTML Report
```python
from tracemalloc_mastery import HTMLReporter

html_reporter = HTMLReporter()
html = html_reporter.generate(snapshot, comparison=diff, timeline=timeline)
with open("report.html", "w") as f:
    f.write(html)
```

## Integration with External Tools

```python
from tracemalloc_mastery import UnifiedProfiler, PySpyIntegration, MemrayIntegration

profiler = UnifiedProfiler()
print("Available tools:", profiler.get_available_tools())

# Profile running process with all tools
results = profiler.profile_running_process(pid=1234, output_dir="profiles/", duration=30)

# Or use specific tools
py_spy = PySpyIntegration()
if py_spy.available:
    py_spy.flamegraph(1234, "profile.svg", duration=10)

memray = MemrayIntegration()
if memray.available:
    memray.run("my_script.py", "profile.bin")
    memray.flamegraph("profile.bin", "flame.svg")
```

## Configuration

```python
from tracemalloc_mastery import configure_tracemalloc, FilterBuilder

# Configure tracemalloc
session = configure_tracemalloc(
    max_frames=100,           # Stack depth
    trace_python=True,        # Python allocations
    trace_c=False,            # C allocations (experimental)
)

# Build custom filters
filters = (FilterBuilder()
    .include_only_project("/my/project")
    .exclude_test_files()
    .exclude_virtualenv()
    .build())

# Apply to snapshot
filtered = snapshot.filter_traces(filters)
```

## Requirements

- Python 3.8+
- psutil (required)
- matplotlib + squarify (for visualization)
- py-spy, memray, objgraph, pympler (optional, for integration)

## License

MIT License - see LICENSE file for details.