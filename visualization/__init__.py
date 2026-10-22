"""
Visualization and reporting utilities for memory analysis.
"""

import json
import sys
import threading
import time
import tracemalloc
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from ..analysis import ComparisonResult, LeakCandidate
from ..core import MemorySnapshot, TracemallocSession

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


@dataclass
class FlameNode:
    """Node in a flame graph."""
    name: str
    value: int
    children: Dict[str, 'FlameNode'] = field(default_factory=dict)
    parent: Optional['FlameNode'] = None
    traceback: Tuple = ()

    def add_child(self, name: str, value: int, traceback: Tuple) -> 'FlameNode':
        if name not in self.children:
            self.children[name] = FlameNode(name=name, value=value, traceback=traceback, parent=self)
        else:
            self.children[name].value += value
        return self.children[name]

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "value": self.value,
            "value_mb": self.value / 1024 / 1024,
            "children": {k: v.to_dict() for k, v in self.children.items()},
            "traceback": [f"{f.filename}:{f.lineno} in {f.function}" for f in self.traceback] if self.traceback else [],
        }


class MemoryFlameGraph:
    """
    Generate flame graphs from memory snapshots.

    Flame graphs visualize memory allocation stacks, where
    width represents memory size.
    """

    def __init__(self, snapshot: tracemalloc.Snapshot, key_type: str = 'traceback'):
        self.snapshot = snapshot
        self.key_type = key_type
        self._root = FlameNode(name="root", value=0)
        self._build()

    def _build(self):
        stats = self.snapshot.statistics(self.key_type)
        for stat in stats:
            self._add_trace(stat)

    def _add_trace(self, stat: tracemalloc.Statistic):
        if not stat.traceback:
            return

        node = self._root
        node.value += stat.size

        # Build from bottom (oldest) to top (newest)
        for frame in reversed(stat.traceback):
            name = f"{frame.filename}:{frame.lineno} ({frame.function})"
            node = node.add_child(name, stat.size, stat.traceback)

    def to_dict(self) -> Dict:
        return self._root.to_dict()

    def to_json(self, filepath: Optional[Union[str, Path]] = None) -> str:
        """Export as JSON for visualization tools."""
        data = {
            "type": "flamegraph",
            "metadata": {
                "total_memory_mb": self._root.value / 1024 / 1024,
                "generated": time.time(),
            },
            "data": self.to_dict(),
        }
        json_str = json.dumps(data, indent=2)
        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)
        return json_str

    def to_speedscope(self, filepath: Union[str, Path]):
        """Export in Speedscope format."""
        # Speedscope uses a different format
        events = []
        def traverse(node: FlameNode, depth: int = 0):
            events.append({
                "type": "O",
                "name": node.name,
                "value": node.value,
                "depth": depth,
            })
            for child in node.children.values():
                traverse(child, depth + 1)
            events.append({"type": "C"})  # Close

        traverse(self._root)

        data = {
            "$schema": "https://www.speedscope.app/file-format-schema.json",
            "profiles": [{
                "type": "evented",
                "name": "Memory Flame Graph",
                "unit": "bytes",
                "startValue": 0,
                "endValue": 0,
                "events": events,
            }],
            "shared": {},
        }

        with open(filepath, 'w') as f:
            json.dump(data, f)

    def print_text(self, max_depth: int = 20, min_size_mb: float = 0.1):
        """Print text-based flame graph."""
        min_bytes = min_size_mb * 1024 * 1024

        def print_node(node: FlameNode, prefix: str = "", depth: int = 0):
            if depth > max_depth or node.value < min_bytes:
                return
            if node.name != "root":
                bar_len = int((node.value / self._root.value) * 50) if self._root.value > 0 else 0
                bar = "█" * bar_len
                print(f"{prefix}{bar} {node.name} ({node.value / 1024 / 1024:.2f} MB)")
            for child in sorted(node.children.values(), key=lambda x: x.value, reverse=True):
                print_node(child, prefix + "  ", depth + 1)

        print_node(self._root)


@dataclass
class TimelinePoint:
    timestamp: float
    current_mb: float
    peak_mb: float
    label: str = ""


class AllocationTimeline:
    """
    Track and visualize memory allocation over time.
    """

    def __init__(self):
        self._points: List[TimelinePoint] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 1.0
        self._session = None

    def start(self, session: 'TracemallocSession', interval: float = 1.0):
        """Start automatic timeline recording."""
        self._session = session
        self._interval = interval
        self._running = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop timeline recording."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _record_loop(self):
        while self._running and self._session and self._session.is_active:
            current, peak = self._session.get_traced_memory()
            self._points.append(self.TimelinePoint(
                timestamp=time.time(),
                current_mb=current / 1024 / 1024,
                peak_mb=peak / 1024 / 1024,
            ))
            time.sleep(self._interval)

    def add_point(self, label: str = ""):
        """Manually add a timeline point."""
        if self._session and self._session.is_active:
            current, peak = self._session.get_traced_memory()
            self._points.append(self.TimelinePoint(
                timestamp=time.time(),
                current_mb=current / 1024 / 1024,
                peak_mb=peak / 1024 / 1024,
                label=label,
            ))

    def get_data(self) -> List[Dict]:
        """Get timeline data as list of dicts."""
        if not self._points:
            return []
        start_time = self._points[0].timestamp
        return [
            {
                "time": p.timestamp - start_time,
                "current_mb": p.current_mb,
                "peak_mb": p.peak_mb,
                "label": p.label,
            }
            for p in self._points
        ]

    def plot(self, filepath: Optional[Union[str, Path]] = None, show: bool = False):
        """Plot timeline using matplotlib."""
        if not MATPLOTLIB_AVAILABLE:
            raise RuntimeError("matplotlib not available")

        data = self.get_data()
        if not data:
            return

        times = [d["time"] for d in data]
        current = [d["current_mb"] for d in data]
        peak = [d["peak_mb"] for d in data]

        plt.figure(figsize=(12, 6))
        plt.plot(times, current, label='Current', linewidth=2)
        plt.plot(times, peak, label='Peak', linewidth=1, alpha=0.7)
        plt.fill_between(times, current, alpha=0.1)

        # Mark labeled points
        labeled = [(i, d) for i, d in enumerate(data) if d["label"]]
        for i, d in labeled:
            plt.annotate(d["label"], (times[i], current[i]),
                        textcoords="offset points", xytext=(0, 10),
                        ha='center', fontsize=8, rotation=45)

        plt.xlabel('Time (seconds)')
        plt.ylabel('Memory (MB)')
        plt.title('Memory Allocation Timeline')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        if filepath:
            plt.savefig(filepath, dpi=150)
        if show:
            plt.show()
        plt.close()

    def export_json(self, filepath: Union[str, Path]):
        """Export timeline as JSON."""
        data = {
            "type": "timeline",
            "metadata": {
                "points": len(self._points),
                "duration": self._points[-1].timestamp - self._points[0].timestamp if len(self._points) > 1 else 0,
            },
            "data": self.get_data(),
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)


class TreemapVisualizer:
    """
    Generate treemap visualizations of memory allocations.

    Treemaps show hierarchical memory usage as nested rectangles.
    """

    def __init__(self, snapshot: tracemalloc.Snapshot, key_type: str = 'traceback'):
        self.snapshot = snapshot
        self.key_type = key_type
        self._data = self._build_treemap()

    def _build_treemap(self) -> Dict:
        stats = self.snapshot.statistics(self.key_type)
        root = {"name": "total", "value": 0, "children": []}

        # Group by top-level module/file
        groups: Dict[str, Dict] = defaultdict(lambda: {"name": "", "value": 0, "children": []})

        for stat in stats:
            if not stat.traceback:
                continue

            # Get top frame for grouping
            top_frame = stat.traceback[-1]
            group_key = top_frame.filename

            group = groups[group_key]
            group["name"] = group_key
            group["value"] += stat.size
            group["children"].append({
                "name": f"{top_frame.function}:{top_frame.lineno}",
                "value": stat.size,
                "traceback": [f"{f.filename}:{f.lineno} in {f.function}" for f in stat.traceback],
            })

        root["value"] = sum(g["value"] for g in groups.values())
        root["children"] = list(groups.values())

        # Sort children by value
        def sort_children(node):
            if "children" in node:
                node["children"].sort(key=lambda x: x["value"], reverse=True)
                for child in node["children"]:
                    sort_children(child)

        sort_children(root)
        return root

    def to_dict(self) -> Dict:
        return self._data

    def to_json(self, filepath: Optional[Union[str, Path]] = None) -> str:
        json_str = json.dumps(self._data, indent=2)
        if filepath:
            with open(filepath, 'w') as f:
                f.write(json_str)
        return json_str

    def plot(self, filepath: Optional[Union[str, Path]] = None, show: bool = False):
        """Plot treemap using matplotlib (requires squarify)."""
        if not MATPLOTLIB_AVAILABLE:
            raise RuntimeError("matplotlib not available")

        try:
            import squarify
        except ImportError as err:
            raise RuntimeError("squarify not available. Install with: pip install squarify") from err

        # Flatten data for squarify
        rects = []
        labels = []
        colors = []

        def collect_rects(node: Dict, prefix: str = ""):
            if "children" not in node or not node["children"]:
                return
            for child in node["children"]:
                if child["value"] > 0:
                    rects.append(child["value"])
                    name = child["name"]
                    if len(name) > 40:
                        name = name[:37] + "..."
                    labels.append(f"{name}\n{child['value']/1024/1024:.1f}MB")
                    colors.append(plt.cm.viridis(hash(name) % 256 / 256))

        collect_rects(self._data)

        if not rects:
            return

        # Normalize
        total = sum(rects)
        norm_rects = [r / total for r in rects]

        fig, ax = plt.subplots(figsize=(14, 10))
        squarify.plot(sizes=norm_rects, label=labels, color=colors, alpha=0.8, ax=ax)
        ax.set_title('Memory Allocation Treemap')
        ax.axis('off')
        plt.tight_layout()

        if filepath:
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
        if show:
            plt.show()
        plt.close()


class ConsoleReporter:
    """
    Rich console reporter for memory analysis.
    """

    def __init__(self, use_color: bool = True, width: int = 100):
        self.use_color = use_color and sys.stdout.isatty()
        self.width = width
        self._colors = {
            'red': '\033[91m',
            'green': '\033[92m',
            'yellow': '\033[93m',
            'blue': '\033[94m',
            'magenta': '\033[95m',
            'cyan': '\033[96m',
            'white': '\033[97m',
            'bold': '\033[1m',
            'reset': '\033[0m',
        } if self.use_color else dict.fromkeys(['red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white', 'bold', 'reset'], '')

    def _c(self, text: str, color: str) -> str:
        return f"{self._colors.get(color, '')}{text}{self._colors['reset']}"

    def report_snapshot(self, snapshot: 'MemorySnapshot', top_n: int = 20, key_type: str = 'lineno'):
        """Report a single snapshot."""
        print(self._c(f"\n{'='*self.width}", 'cyan'))
        print(self._c(f"MEMORY SNAPSHOT: {snapshot.label}", 'bold'))
        print(self._c(f"{'='*self.width}", 'cyan'))
        print(f"Time: {time.ctime(snapshot.timestamp)}")
        print(f"Domain: {snapshot.domain}")
        print(f"Process Memory: {snapshot.process_memory_mb:.2f} MB")

        current, peak = tracemalloc.get_traced_memory()
        print(f"Traced Current: {current/1024/1024:.2f} MB")
        print(f"Traced Peak: {peak/1024/1024:.2f} MB")

        stats = snapshot.top_allocations(top_n, key_type)
        print(self._c(f"\nTOP {top_n} ALLOCATIONS ({key_type}):", 'yellow'))
        print(self._c("-" * self.width, 'yellow'))

        for i, stat in enumerate(stats, 1):
            size_mb = stat.size / 1024 / 1024
            color = 'red' if size_mb > 10 else 'yellow' if size_mb > 1 else 'green'
            print(f"{i:3d}. {self._c(f'{size_mb:>8.2f} MB', color)} ({stat.count:>6d} allocs)")
            if stat.traceback:
                frame = stat.traceback[0]
                print(f"      {self._c(frame.filename, 'cyan')}:{frame.lineno} in {self._c(frame.function, 'magenta')}")
                for frame in stat.traceback[1:4]:
                    print(f"      {frame.filename}:{frame.lineno} in {frame.function}")
                if len(stat.traceback) > 4:
                    print(f"      ... and {len(stat.traceback) - 4} more frames")
            print()

    def report_comparison(self, diff: 'ComparisonResult', top_n: int = 20):
        """Report comparison between snapshots."""
        print(self._c(f"\n{'='*self.width}", 'cyan'))
        print(self._c("MEMORY COMPARISON", 'bold'))
        print(self._c(f"{'='*self.width}", 'cyan'))
        print(f"Total Size Change: {self._c(f'{diff.total_size_diff_mb:+.2f} MB', 'red' if diff.total_size_diff > 0 else 'green')}")
        print(f"Total Count Change: {self._c(f'{diff.total_count_diff:+d}', 'red' if diff.total_count_diff > 0 else 'green')}")

        print(self._c("\nTOP INCREASES:", 'red'))
        print(self._c("-" * self.width, 'red'))
        for d in diff.get_top_changes(top_n, 'size'):
            if d.size_diff > 0:
                print(f"  +{d.size_diff_mb:.2f} MB ({d.percent_change:+.1f}%)")
                if d.statistic.traceback:
                    frame = d.statistic.traceback[0]
                    print(f"    {frame.filename}:{frame.lineno} in {frame.function}")

        print(self._c("\nTOP DECREASES:", 'green'))
        print(self._c("-" * self.width, 'green'))
        for d in diff.get_top_changes(top_n, 'size'):
            if d.size_diff < 0:
                print(f"  {d.size_diff_mb:.2f} MB ({d.percent_change:+.1f}%)")
                if d.statistic.traceback:
                    frame = d.statistic.traceback[0]
                    print(f"    {frame.filename}:{frame.lineno} in {frame.function}")

    def report_leak_candidates(self, candidates: List['LeakCandidate']):
        """Report suspected memory leaks."""
        print(self._c(f"\n{'='*self.width}", 'red'))
        print(self._c("SUSPECTED MEMORY LEAKS", 'bold'))
        print(self._c(f"{'='*self.width}", 'red'))

        if not candidates:
            print(self._c("No leaks detected.", 'green'))
            return

        for i, c in enumerate(candidates, 1):
            conf_color = 'red' if c.confidence > 0.8 else 'yellow' if c.confidence > 0.5 else 'cyan'
            print(f"\n{i}. {self._c(c.description, 'bold')}")
            print(f"   Confidence: {self._c(f'{c.confidence:.0%}', conf_color)}")
            print(f"   Growth: {(c.size_history[-1] - c.size_history[0]) / 1024 / 1024:.2f} MB")
            if c.last_seen > c.first_seen:
                rate = (c.size_history[-1] - c.size_history[0]) / (c.last_seen - c.first_seen)
                print(f"   Rate: {rate/1024:.2f} KB/s")
            print(f"   First seen: {time.ctime(c.first_seen)}")
            print(f"   Last seen: {time.ctime(c.last_seen)}")
            if c.traceback:
                print("   Traceback:")
                for frame in c.traceback[:5]:
                    print(f"     {frame.filename}:{frame.lineno} in {frame.function}")


class HTMLReporter:
    """
    Generate interactive HTML reports.
    """

    HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Memory Report - {title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; }}
        .metric {{ display: inline-block; margin: 10px 20px; }}
        .metric-value {{ font-size: 2em; font-weight: bold; }}
        .metric-label {{ font-size: 0.9em; opacity: 0.8; }}
        .section {{ margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; }}
        .increase {{ color: #e74c3c; }}
        .decrease {{ color: #27ae60; }}
        .traceback {{ font-family: monospace; font-size: 0.85em; color: #666; }}
        .chart-container {{ width: 100%; height: 400px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Memory Analysis Report</h1>
        <p>{title}</p>
        <div class="metrics">
            <div class="metric"><div class="metric-value">{current_mb:.1f}</div><div class="metric-label">Current (MB)</div></div>
            <div class="metric"><div class="metric-value">{peak_mb:.1f}</div><div class="metric-label">Peak (MB)</div></div>
            <div class="metric"><div class="metric-value">{process_mb:.1f}</div><div class="metric-label">Process (MB)</div></div>
        </div>
    </div>

    <div class="section">
        <h2>Top Allocations</h2>
        <table>
            <thead><tr><th>Rank</th><th>Size (MB)</th><th>Count</th><th>Location</th></tr></thead>
            <tbody>{allocation_rows}</tbody>
        </table>
    </div>

    {comparison_section}

    <div class="section">
        <h2>Timeline</h2>
        <div class="chart-container"><canvas id="timelineChart"></canvas></div>
    </div>

    <script>
        const timelineData = {timeline_json};
        new Chart(document.getElementById('timelineChart'), {{
            type: 'line',
            data: {{
                labels: timelineData.map(d => d.time.toFixed(1)),
                datasets: [{{
                    label: 'Current (MB)',
                    data: timelineData.map(d => d.current_mb),
                    borderColor: '#3498db',
                    fill: true,
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                }}, {{
                    label: 'Peak (MB)',
                    data: timelineData.map(d => d.peak_mb),
                    borderColor: '#e74c3c',
                    fill: false,
                }}]
            }},
            options: {{ responsive: true, maintainAspectRatio: false }}
        }});
    </script>
</body>
</html>
"""

    def generate(
        self,
        snapshot: 'MemorySnapshot',
        comparison: Optional['ComparisonResult'] = None,
        timeline: Optional[AllocationTimeline] = None,
        title: str = "Memory Report",
    ) -> str:
        """Generate HTML report."""
        current, peak = tracemalloc.get_traced_memory()

        # Allocation rows
        rows = []
        for i, stat in enumerate(snapshot.top_allocations(20), 1):
            traceback_str = ""
            if stat.traceback:
                traceback_str = "<br>".join(
                    f"{f.filename}:{f.lineno} in {f.function}" for f in stat.traceback[:5]
                )
            rows.append(f"""
                <tr>
                    <td>{i}</td>
                    <td>{stat.size/1024/1024:.2f}</td>
                    <td>{stat.count}</td>
                    <td class="traceback">{traceback_str}</td>
                </tr>
            """)
        allocation_rows = "\n".join(rows)

        # Comparison section
        comparison_section = ""
        if comparison:
            comp_rows = []
            for d in comparison.get_top_changes(15, 'size'):
                cls = 'increase' if d.size_diff > 0 else 'decrease'
                traceback_str = ""
                if d.statistic.traceback:
                    traceback_str = "<br>".join(
                        f"{f.filename}:{f.lineno} in {f.function}" for f in d.statistic.traceback[:3]
                    )
                comp_rows.append(f"""
                    <tr>
                        <td class="{cls}">{d.size_diff_mb:+.2f}</td>
                        <td class="{cls}">{d.percent_change:+.1f}%</td>
                        <td class="traceback">{traceback_str}</td>
                    </tr>
                """)
            comparison_section = f"""
                <div class="section">
                    <h2>Comparison</h2>
                    <p>Total Change: <span class="{'increase' if comparison.total_size_diff > 0 else 'decrease'}">{comparison.total_size_diff_mb:+.2f} MB</span></p>
                    <table>
                        <thead><tr><th>Size Diff (MB)</th><th>% Change</th><th>Location</th></tr></thead>
                        <tbody>{"".join(comp_rows)}</tbody>
                    </table>
                </div>
            """

        # Timeline data
        timeline_json = "[]"
        if timeline:
            timeline_json = json.dumps(timeline.get_data())

        return self.HTML_TEMPLATE.format(
            title=title,
            current_mb=current/1024/1024,
            peak_mb=peak/1024/1024,
            process_mb=snapshot.process_memory_mb,
            allocation_rows=allocation_rows,
            comparison_section=comparison_section,
            timeline_json=timeline_json,
        )

    def save(self, html: str, filepath: Union[str, Path]):
        with open(filepath, 'w') as f:
            f.write(html)
