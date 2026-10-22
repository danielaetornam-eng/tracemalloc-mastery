"""
Command-line interface for tracemalloc_mastery.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog="tracemalloc-mastery",
        description="God-tier tracemalloc memory analysis toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tracemalloc-mastery run --script my_script.py
  tracemalloc-mastery profile --pid 1234 --duration 30
  tracemalloc-mastery analyze --snapshot snapshot.pkl --top 20
  tracemalloc-mastery leak-detect --interval 5 --threshold 1MB
  tracemalloc-mastery visualize --flamegraph snapshot.pkl --output flame.svg
  tracemalloc-mastery benchmark --func my_module:my_func --iterations 100
  tracemalloc-mastery examples --list
  tracemalloc-mastery examples --run basic_tracking
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a script with memory tracking")
    run_parser.add_argument("--script", required=True, help="Python script to run")
    run_parser.add_argument("--args", nargs=argparse.REMAINDER, help="Arguments to pass to script")
    run_parser.add_argument("--output", "-o", help="Output directory for reports")
    run_parser.add_argument("--max-frames", type=int, default=50, help="Max stack frames to track")
    run_parser.add_argument("--trace-c", action="store_true", help="Trace C allocations")

    # Profile command
    profile_parser = subparsers.add_parser("profile", help="Profile a running process")
    profile_parser.add_argument("--pid", type=int, required=True, help="Process ID to profile")
    profile_parser.add_argument("--duration", type=float, default=30, help="Profile duration in seconds")
    profile_parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval")
    profile_parser.add_argument("--output", "-o", help="Output directory")
    profile_parser.add_argument("--tools", nargs="+", choices=["py-spy", "memray", "tracemalloc"],
                               default=["tracemalloc"], help="Profiling tools to use")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze a snapshot")
    analyze_parser.add_argument("--snapshot", required=True, help="Snapshot file to analyze")
    analyze_parser.add_argument("--compare", help="Compare with another snapshot")
    analyze_parser.add_argument("--top", type=int, default=20, help="Show top N allocations")
    analyze_parser.add_argument("--key-type", choices=["lineno", "filename", "traceback"], default="lineno")
    analyze_parser.add_argument("--format", choices=["text", "json", "html"], default="text")
    analyze_parser.add_argument("--output", "-o", help="Output file")

    # Leak detection command
    leak_parser = subparsers.add_parser("leak-detect", help="Detect memory leaks")
    leak_parser.add_argument("--pid", type=int, help="Process ID to monitor (or current)")
    leak_parser.add_argument("--script", help="Script to run and monitor")
    leak_parser.add_argument("--interval", type=float, default=5.0, help="Check interval")
    leak_parser.add_argument("--threshold", default="1MB", help="Minimum leak size (e.g., 1MB, 500KB)")
    leak_parser.add_argument("--duration", type=float, default=60, help="Monitor duration")
    leak_parser.add_argument("--output", "-o", help="Output report file")

    # Visualize command
    viz_parser = subparsers.add_parser("visualize", help="Generate visualizations")
    viz_parser.add_argument("--snapshot", required=True, help="Snapshot file")
    viz_parser.add_argument("--flamegraph", action="store_true", help="Generate flame graph")
    viz_parser.add_argument("--timeline", action="store_true", help="Generate timeline")
    viz_parser.add_argument("--treemap", action="store_true", help="Generate treemap")
    viz_parser.add_argument("--html", action="store_true", help="Generate HTML report")
    viz_parser.add_argument("--output", "-o", help="Output file/directory")

    # Benchmark command
    bench_parser = subparsers.add_parser("benchmark", help="Benchmark memory usage")
    bench_parser.add_argument("--func", required=True, help="Function to benchmark (module:function)")
    bench_parser.add_argument("--iterations", type=int, default=10, help="Number of iterations")
    bench_parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations")
    bench_parser.add_argument("--compare", help="Compare with another function (module:function)")
    bench_parser.add_argument("--output", "-o", help="Output file")

    # Examples command
    examples_parser = subparsers.add_parser("examples", help="Run examples")
    examples_parser.add_argument("--list", action="store_true", help="List available examples")
    examples_parser.add_argument("--run", help="Run specific example by name")
    examples_parser.add_argument("--all", action="store_true", help="Run all examples")
    examples_parser.add_argument("--skip", nargs="+", help="Examples to skip")

    # Doctor command
    subparsers.add_parser("doctor", help="Check environment and dependencies")

    # Global options
    parser.add_argument("--verbose", "-v", action="count", default=0, help="Increase verbosity")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")

    return parser


def parse_size(size_str: str) -> int:
    """Parse size string like '1MB', '500KB', '1GB'."""
    size_str = size_str.upper().strip()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            return int(float(size_str[:-len(suffix)]) * mult)
    return int(size_str)


def cmd_run(args: argparse.Namespace) -> int:
    """Run a script with memory tracking."""
    from ..analysis import SnapshotComparator
    from ..core import configure_tracemalloc
    from ..visualization import ConsoleReporter, HTMLReporter, MemoryFlameGraph

    session = configure_tracemalloc(max_frames=args.max_frames, trace_c=args.trace_c)

    output_dir = Path(args.output) if args.output else Path.cwd() / "tracemalloc_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {args.script} with memory tracking...")
    print(f"Output directory: {output_dir}")

    # Take initial snapshot
    snap_start = session.take_snapshot("start")

    # Run script
    script_path = Path(args.script)
    cmd = [sys.executable, str(script_path)] + (args.args or [])

    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        duration = time.time() - start_time

        if result.stdout:
            print("STDOUT:")
            print(result.stdout)
        if result.stderr:
            print("STDERR:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)

        print(f"Script exited with code {result.returncode} in {duration:.2f}s")

    except subprocess.TimeoutExpired:
        print("Script timed out after 5 minutes")
        return 1
    except Exception as e:
        print(f"Error running script: {e}")
        return 1

    # Take final snapshot
    snap_end = session.take_snapshot("end")

    # Generate reports
    comparator = SnapshotComparator()
    diff = comparator.compare(snap_start.snapshot, snap_end.snapshot)

    reporter = ConsoleReporter()
    reporter.report_snapshot(snap_end, top_n=args.top if hasattr(args, 'top') else 20)
    reporter.report_comparison(diff, top_n=20)

    # Save snapshots
    import pickle
    with open(output_dir / "snapshot_start.pkl", 'wb') as f:
        pickle.dump(snap_start, f)
    with open(output_dir / "snapshot_end.pkl", 'wb') as f:
        pickle.dump(snap_end, f)

    # HTML report
    html_reporter = HTMLReporter()
    html = html_reporter.generate(snap_end, comparison=diff)
    with open(output_dir / "report.html", 'w') as f:
        f.write(html)

    # Flame graph
    flame = MemoryFlameGraph(snap_end.snapshot)
    flame.to_speedscope(output_dir / "flamegraph.speedscope.json")

    print(f"\nReports saved to {output_dir}")
    return result.returncode


def cmd_profile(args: argparse.Namespace) -> int:
    """Profile a running process."""
    from ..integration import UnifiedProfiler

    profiler = UnifiedProfiler()
    output_dir = Path(args.output) if args.output else Path.cwd() / "profile_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Profiling PID {args.pid} for {args.duration}s using {args.tools}")

    results = profiler.profile_running_process(args.pid, output_dir, args.duration, args.tools)

    for tool, result in results.items():
        status = "SUCCESS" if result.success else "FAILED"
        print(f"  {tool}: {status}")
        if result.error:
            print(f"    Error: {result.error}")

    # Generate unified report
    report = profiler.get_comprehensive_report()
    with open(output_dir / "unified_report.json", 'w') as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nReports saved to {output_dir}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze a snapshot file."""
    import pickle

    from ..analysis import MemoryReportGenerator, SnapshotComparator
    from ..core import MemorySnapshot
    from ..visualization import ConsoleReporter, HTMLReporter

    # Load snapshot
    with open(args.snapshot, 'rb') as f:
        snapshot = pickle.load(f)

    if not isinstance(snapshot, MemorySnapshot):
        print("Error: File is not a valid MemorySnapshot")
        return 1

    print(f"Analyzing snapshot: {snapshot.label}")
    print(f"Timestamp: {time.ctime(snapshot.timestamp)}")
    print(f"Domain: {snapshot.domain}")

    # Compare if requested
    comparison = None
    if args.compare:
        with open(args.compare, 'rb') as f:
            other = pickle.load(f)
        comparator = SnapshotComparator()
        comparison = comparator.compare(snapshot.snapshot, other.snapshot, args.key_type)

    # Generate output
    if args.format == "json":
        reporter = MemoryReportGenerator()
        report = reporter.generate_report(snapshot, include_comparison=comparison and other, key_type=args.key_type)
        output = json.dumps(report, indent=2, default=str)
    elif args.format == "html":
        html_reporter = HTMLReporter()
        output = html_reporter.generate(snapshot, comparison=comparison, title=f"Analysis: {snapshot.label}")
    else:
        reporter = ConsoleReporter()
        import io
        buf = io.StringIO()
        # Capture console output
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        reporter.report_snapshot(snapshot, top_n=args.top, key_type=args.key_type)
        if comparison:
            reporter.report_comparison(comparison, top_n=args.top)
        sys.stdout = old_stdout
        output = buf.getvalue()

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Output saved to {args.output}")
    else:
        print(output)

    return 0


def cmd_leak_detect(args: argparse.Namespace) -> int:
    """Detect memory leaks."""
    from ..analysis import LeakDetector
    from ..core import configure_tracemalloc
    from ..visualization import ConsoleReporter

    session = configure_tracemalloc()
    detector = LeakDetector(session, comparison_interval=args.interval)

    threshold_bytes = parse_size(args.threshold)
    detector.min_leak_size = threshold_bytes

    leaks_found = []
    def on_leak(candidate):
        leaks_found.append(candidate)
        print(f"LEAK: {candidate.description} (confidence: {candidate.confidence:.0%})")

    detector.register_callback(on_leak)
    detector.start_detection()

    if args.script:
        # Run script and monitor
        cmd = [sys.executable, args.script]
        proc = subprocess.Popen(cmd)

        try:
            for i in range(int(args.duration / args.interval)):
                time.sleep(args.interval)
                detector.take_snapshot(f"interval_{i}")
        finally:
            proc.terminate()
            proc.wait()
    else:
        # Monitor current process
        print(f"Monitoring current process for {args.duration}s...")
        for i in range(int(args.duration / args.interval)):
            time.sleep(args.interval)
            detector.take_snapshot(f"interval_{i}")

    detector.stop_detection()

    # Generate report
    report = detector.get_report()

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {args.output}")

    reporter = ConsoleReporter()
    reporter.report_leak_candidates(detector.get_leak_candidates())

    return 0


def cmd_visualize(args: argparse.Namespace) -> int:
    """Generate visualizations from snapshot."""
    import pickle

    from ..visualization import (
        HTMLReporter,
        MemoryFlameGraph,
        TreemapVisualizer,
    )

    with open(args.snapshot, 'rb') as f:
        snapshot = pickle.load(f)

    output_dir = Path(args.output) if args.output else Path.cwd() / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.flamegraph:
        flame = MemoryFlameGraph(snapshot.snapshot)
        flame.to_speedscope(output_dir / "flamegraph.speedscope.json")
        print(f"Flame graph saved to {output_dir / 'flamegraph.speedscope.json'}")

    if args.treemap:
        treemap = TreemapVisualizer(snapshot.snapshot)
        treemap.to_json(output_dir / "treemap.json")
        try:
            treemap.plot(output_dir / "treemap.png")
            print(f"Treemap saved to {output_dir / 'treemap.png'}")
        except Exception as e:
            print(f"Treemap plot failed: {e}")

    if args.html:
        html_reporter = HTMLReporter()
        html = html_reporter.generate(snapshot, title=f"Memory Report: {snapshot.label}")
        with open(output_dir / "report.html", 'w') as f:
            f.write(html)
        print(f"HTML report saved to {output_dir / 'report.html'}")

    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Benchmark a function."""
    from ..testing import MemoryBenchmark

    # Import function
    module_name, func_name = args.func.rsplit(":", 1)
    module = __import__(module_name, fromlist=[func_name])
    func = getattr(module, func_name)

    compare_func = None
    if args.compare:
        module_name2, func_name2 = args.compare.rsplit(":", 1)
        module2 = __import__(module_name2, fromlist=[func_name2])
        compare_func = getattr(module2, func_name2)

    benchmark = MemoryBenchmark(warmup=args.warmup)

    result1 = benchmark.run(args.func, func, iterations=args.iterations)
    print(result1)

    if compare_func:
        result2 = benchmark.run(args.compare, compare_func, iterations=args.iterations)
        print(result2)
        benchmark.print_comparison(result1, result2)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump({
                "result1": str(result1),
                "result2": str(result2) if compare_func else None,
            }, f, indent=2)

    return 0


def cmd_examples(args: argparse.Namespace) -> int:
    """Run examples."""
    from ..examples import ExampleRunner

    if args.list:
        print("Available examples:")
        for name, _ in ExampleRunner.EXAMPLES:
            print(f"  {name}")
        return 0

    if args.run:
        ExampleRunner.run(args.run)
        return 0

    if args.all:
        skip = args.skip or []
        ExampleRunner.run_all(skip=skip)
        return 0

    print("Use --list, --run NAME, or --all")
    return 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check environment."""
    from ..integration import (
        MemrayIntegration,
        ObjgraphIntegration,
        PymplerIntegration,
        PySpyIntegration,
    )

    print("=" * 50)
    print("TRACEMALLOC MASTERY - ENVIRONMENT CHECK")
    print("=" * 50)

    # Python version
    print(f"\nPython: {sys.version}")

    # Tracemalloc
    import tracemalloc
    print("Tracemalloc: Available (stdlib)")

    # Optional tools
    tools = [
        ("py-spy", PySpyIntegration()),
        ("memray", MemrayIntegration()),
        ("objgraph", ObjgraphIntegration()),
        ("pympler", PymplerIntegration()),
    ]

    print("\nOptional profiling tools:")
    for name, tool in tools:
        status = "✓ Available" if tool.available else "✗ Not installed"
        print(f"  {name}: {status}")

    # Visualization deps
    print("\nVisualization dependencies:")
    try:
        import matplotlib
        print(f"  matplotlib: ✓ {matplotlib.__version__}")
    except ImportError:
        print("  matplotlib: ✗ Not installed")

    try:
        import importlib.util
        if importlib.util.find_spec("squarify"):
            print("  squarify: ✓ Available")
        else:
            print("  squarify: ✗ Not installed (needed for treemaps)")
    except ImportError:
        print("  squarify: ✗ Not installed (needed for treemaps)")

    # Test basic functionality
    print("\nBasic functionality test:")
    tracemalloc.start()
    _ = [1, 2, 3]
    snap = tracemalloc.take_snapshot()
    tracemalloc.stop()
    print(f"  Snapshot capture: ✓ ({len(snap.statistics('lineno'))} entries)")

    print("\n" + "=" * 50)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # Set verbosity
    if args.quiet:
        import logging
        logging.disable(logging.CRITICAL)
    elif args.verbose > 1:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    elif args.verbose > 0:
        import logging
        logging.basicConfig(level=logging.INFO)

    # Dispatch
    commands = {
        "run": cmd_run,
        "profile": cmd_profile,
        "analyze": cmd_analyze,
        "leak-detect": cmd_leak_detect,
        "visualize": cmd_visualize,
        "benchmark": cmd_benchmark,
        "examples": cmd_examples,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args)
        except KeyboardInterrupt:
            print("\nInterrupted")
            return 130
        except Exception as e:
            if args.verbose:
                import traceback
                traceback.print_exc()
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
