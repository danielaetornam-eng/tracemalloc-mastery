"""
Integration with other profiling and memory analysis tools.
"""

import json
import subprocess
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Tuple,
    Union,
)


@dataclass
class ToolResult:
    """Result from an external profiling tool."""
    tool: str
    success: bool
    output: str
    error: str = ""
    data: Any = None
    duration: float = 0.0


class PySpyIntegration:
    """
    Integration with py-spy for sampling profiling.

    Requires: pip install py-spy
    """

    def __init__(self, py_spy_path: str = "py-spy"):
        self.py_spy_path = py_spy_path
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            subprocess.run([self.py_spy_path, "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @property
    def available(self) -> bool:
        return self._available

    def record(
        self,
        pid: int,
        output: Union[str, Path],
        duration: float = 10,
        rate: int = 100,
        native: bool = False,
    ) -> ToolResult:
        """Record a profile using py-spy."""
        if not self._available:
            return ToolResult("py-spy", False, "", "py-spy not available")

        start = time.time()
        cmd = [
            self.py_spy_path, "record",
            "-p", str(pid),
            "-o", str(output),
            "-d", str(duration),
            "-r", str(rate),
        ]
        if native:
            cmd.append("--native")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
            return ToolResult(
                "py-spy",
                result.returncode == 0,
                result.stdout,
                result.stderr,
                duration=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return ToolResult("py-spy", False, "", "Timeout", duration=time.time() - start)

    def top(self, pid: int, duration: float = 5) -> ToolResult:
        """Show top functions using py-spy top."""
        if not self._available:
            return ToolResult("py-spy", False, "", "py-spy not available")

        start = time.time()
        try:
            result = subprocess.run(
                [self.py_spy_path, "top", "-p", str(pid), "-d", str(duration)],
                capture_output=True, text=True, timeout=duration + 5
            )
            return ToolResult("py-spy", result.returncode == 0, result.stdout, result.stderr, duration=time.time() - start)
        except subprocess.TimeoutExpired:
            return ToolResult("py-spy", False, "", "Timeout", duration=time.time() - start)

    def flamegraph(self, pid: int, output: Union[str, Path], duration: float = 10) -> ToolResult:
        """Generate flamegraph using py-spy."""
        return self.record(pid, output, duration, native=True)


class MemrayIntegration:
    """
    Integration with memray for memory profiling.

    Requires: pip install memray
    """

    def __init__(self, memray_path: str = "memray"):
        self.memray_path = memray_path
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            subprocess.run([self.memray_path, "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @property
    def available(self) -> bool:
        return self._available

    def run(
        self,
        script: Union[str, Path],
        output: Union[str, Path],
        args: List[str] = None,
    ) -> ToolResult:
        """Run a script with memray tracking."""
        if not self._available:
            return ToolResult("memray", False, "", "memray not available")

        args = args or []
        start = time.time()
        cmd = [self.memray_path, "run", "-o", str(output), str(script)] + args

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            return ToolResult("memray", result.returncode == 0, result.stdout, result.stderr, duration=time.time() - start)
        except subprocess.TimeoutExpired:
            return ToolResult("memray", False, "", "Timeout", duration=time.time() - start)

    def attach(self, pid: int, output: Union[str, Path]) -> ToolResult:
        """Attach to running process."""
        if not self._available:
            return ToolResult("memray", False, "", "memray not available")

        start = time.time()
        try:
            result = subprocess.run(
                [self.memray_path, "attach", str(pid), "-o", str(output)],
                capture_output=True, text=True, timeout=60
            )
            return ToolResult("memray", result.returncode == 0, result.stdout, result.stderr, duration=time.time() - start)
        except subprocess.TimeoutExpired:
            return ToolResult("memray", False, "", "Timeout", duration=time.time() - start)

    def summary(self, input_file: Union[str, Path]) -> ToolResult:
        """Get summary from memray output."""
        if not self._available:
            return ToolResult("memray", False, "", "memray not available")

        start = time.time()
        try:
            result = subprocess.run(
                [self.memray_path, "summary", str(input_file)],
                capture_output=True, text=True, timeout=30
            )
            return ToolResult("memray", result.returncode == 0, result.stdout, result.stderr, duration=time.time() - start)
        except subprocess.TimeoutExpired:
            return ToolResult("memray", False, "", "Timeout", duration=time.time() - start)

    def flamegraph(self, input_file: Union[str, Path], output: Union[str, Path]) -> ToolResult:
        """Generate flamegraph from memray data."""
        if not self._available:
            return ToolResult("memray", False, "", "memray not available")

        start = time.time()
        try:
            result = subprocess.run(
                [self.memray_path, "flamegraph", str(input_file), "-o", str(output)],
                capture_output=True, text=True, timeout=60
            )
            return ToolResult("memray", result.returncode == 0, result.stdout, result.stderr, duration=time.time() - start)
        except subprocess.TimeoutExpired:
            return ToolResult("memray", False, "", "Timeout", duration=time.time() - start)


class ObjgraphIntegration:
    """
    Integration with objgraph for object graph analysis.

    Requires: pip install objgraph
    """

    def __init__(self):
        self._objgraph = None
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            import objgraph
            self._objgraph = objgraph
            return True
        except ImportError:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def count_types(self, limit: int = 20) -> List[Tuple[str, int]]:
        """Count objects by type."""
        if not self._available:
            return []
        return self._objgraph.typestats()[:limit]

    def find_leaking_objects(self, limit: int = 10) -> List[Dict]:
        """Find potentially leaking objects."""
        if not self._available:
            return []

        # Get growth between two points
        counts1 = self._objgraph.typestats()
        time.sleep(0.1)
        counts2 = self._objgraph.typestats()

        growth = {}
        for name, count in counts2:
            prev = next((c for n, c in counts1 if n == name), 0)
            if count > prev:
                growth[name] = count - prev

        return [
            {"type": name, "growth": growth}
            for name, growth in sorted(growth.items(), key=lambda x: x[1], reverse=True)[:limit]
        ]

    def get_referrers(self, obj: Any, max_depth: int = 3) -> List[List[Any]]:
        """Get referrer chain for an object."""
        if not self._available:
            return []
        return self._objgraph.find_backref_chain(obj, max_depth=max_depth)

    def show_growth(self, limit: int = 10) -> str:
        """Show object growth as text."""
        if not self._available:
            return "objgraph not available"

        import io
        output = io.StringIO()
        self._objgraph.show_growth(limit=limit, file=output)
        return output.getvalue()

    def export_dot(self, obj: Any, filepath: Union[str, Path], max_depth: int = 2):
        """Export object graph as DOT file."""
        if not self._available:
            return
        self._objgraph.export_dot(obj, str(filepath), max_depth=max_depth)


class PymplerIntegration:
    """
    Integration with pympler for memory profiling.

    Requires: pip install pympler
    """

    def __init__(self):
        self._muppy = None
        self._summary = None
        self._classtracker = None
        self._available = self._check_available()

    def _check_available(self) -> bool:
        try:
            from pympler import classtracker, muppy, summary
            self._muppy = muppy
            self._summary = summary
            self._classtracker = classtracker
            return True
        except ImportError:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def get_all_objects(self) -> List:
        """Get all tracked objects."""
        if not self._available:
            return []
        return self._muppy.get_objects()

    def get_summary(self, objects: List = None) -> List[Tuple]:
        """Get memory summary."""
        if not self._available:
            return []
        objects = objects or self.get_all_objects()
        return self._summary.summarize(objects)

    def print_summary(self, objects: List = None, limit: int = 20):
        """Print memory summary."""
        if not self._available:
            print("pympler not available")
            return
        objects = objects or self.get_all_objects()
        summ = self.get_summary(objects)
        self._summary.print_(summ[:limit])

    def create_tracker(self) -> 'ClassTracker':
        """Create a class tracker."""
        if not self._available:
            return None
        return ClassTracker(self._classtracker.ClassTracker())

    def diff_summaries(self, before: List, after: List) -> List[Tuple]:
        """Diff two summaries."""
        if not self._available:
            return []
        return self._summary.diff(before, after)


class ClassTracker:
    """Wrapper for pympler's ClassTracker."""

    def __init__(self, tracker):
        self._tracker = tracker

    def track_class(self, cls: type):
        self._tracker.track_class(cls)

    def create_snapshot(self):
        self._tracker.create_snapshot()

    def stats(self) -> str:
        import io
        output = io.StringIO()
        self._tracker.stats(file=output)
        return output.getvalue()

    def diff(self, index1: int = -2, index2: int = -1) -> str:
        import io
        output = io.StringIO()
        self._tracker.diff(index1, index2, file=output)
        return output.getvalue()


class UnifiedProfiler:
    """
    Unified interface for multiple profiling tools.

    Automatically detects available tools and provides
    a consistent API.
    """

    def __init__(self):
        self.py_spy = PySpyIntegration()
        self.memray = MemrayIntegration()
        self.objgraph = ObjgraphIntegration()
        self.pympler = PymplerIntegration()
        self.tracemalloc_session = None

    def get_available_tools(self) -> List[str]:
        """Get list of available profiling tools."""
        tools = ["tracemalloc"]
        if self.py_spy.available:
            tools.append("py-spy")
        if self.memray.available:
            tools.append("memray")
        if self.objgraph.available:
            tools.append("objgraph")
        if self.pympler.available:
            tools.append("pympler")
        return tools

    def profile_script(
        self,
        script: Union[str, Path],
        output_dir: Union[str, Path],
        tools: List[str] = None,
    ) -> Dict[str, ToolResult]:
        """Profile a script with multiple tools."""
        tools = tools or self.get_available_tools()
        results = {}
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if "memray" in tools and self.memray.available:
            results["memray"] = self.memray.run(script, output_dir / "memray.bin")

        if "py-spy" in tools and self.py_spy.available:
            # py-spy needs a running process, so we'd need to run script in background
            pass

        return results

    def profile_running_process(
        self,
        pid: int,
        output_dir: Union[str, Path],
        duration: float = 30,
        tools: List[str] = None,
    ) -> Dict[str, ToolResult]:
        """Profile a running process."""
        tools = tools or self.get_available_tools()
        results = {}
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if "py-spy" in tools and self.py_spy.available:
            results["py-spy-flamegraph"] = self.py_spy.flamegraph(pid, output_dir / "py-spy.svg", duration)
            results["py-spy-top"] = self.py_spy.top(pid, min(5, duration))

        if "memray" in tools and self.memray.available:
            results["memray"] = self.memray.attach(pid, output_dir / "memray.bin")

        return results

    def get_comprehensive_report(self) -> Dict[str, Any]:
        """Get comprehensive memory report from all available tools."""
        report = {
            "timestamp": time.time(),
            "tools": self.get_available_tools(),
            "tracemalloc": {},
        }

        # Tracemalloc info
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            report["tracemalloc"] = {
                "current_mb": current / 1024 / 1024,
                "peak_mb": peak / 1024 / 1024,
                "tracing": True,
            }
        else:
            report["tracemalloc"] = {"tracing": False}

        # Objgraph info
        if self.objgraph.available:
            report["objgraph"] = {
                "type_counts": dict(self.objgraph.count_types(10)),
                "growth": self.objgraph.find_leaking_objects(10),
            }

        # Pympler info
        if self.pympler.available:
            objects = self.pympler.get_all_objects()
            report["pympler"] = {
                "total_objects": len(objects),
                "summary": [
                    {"type": str(t), "count": c, "size": s}
                    for t, c, s in self.pympler.get_summary(objects)[:10]
                ],
            }

        return report


class ProfilerOrchestrator:
    """
    Orchestrate multiple profilers for comprehensive analysis.
    """

    def __init__(self):
        self.unified = UnifiedProfiler()
        self._running = False
        self._results: Dict[str, Any] = {}

    def start_all(self):
        """Start all available profilers."""
        import tracemalloc
        tracemalloc.start()

        # Start tracemalloc session
        from ..core import TracemallocSession
        self.tracemalloc_session = TracemallocSession.get_default()
        self.tracemalloc_session.start()

        self._running = True

    def stop_all(self, output_dir: Union[str, Path] = None):
        """Stop all profilers and collect results."""
        self._running = False

        if self.tracemalloc_session:
            self.tracemalloc_session.stop()

        self._results = self.unified.get_comprehensive_report()

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_dir / "unified_report.json", 'w') as f:
                json.dump(self._results, f, indent=2, default=str)

        return self._results

    def take_snapshot(self, label: str = ""):
        """Take a snapshot with all profilers."""
        if not self._running:
            self.start_all()

        result = {"label": label, "timestamp": time.time()}

        if self.tracemalloc_session:
            result["tracemalloc"] = self.tracemalloc_session.take_snapshot(label)

        if self.objgraph.available:
            result["objgraph_growth"] = self.objgraph.find_leaking_objects()

        if self.pympler.available:
            objects = self.pympler.get_all_objects()
            result["pympler_summary"] = self.pympler.get_summary(objects)[:10]

        return result
