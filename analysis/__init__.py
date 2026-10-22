"""
Advanced snapshot comparison and analysis module.
"""

import threading
import time
import tracemalloc
from contextlib import suppress
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

from ..core import MemorySnapshot, TracemallocSession


@dataclass
class StatisticDiff:
    """Enhanced statistic difference with additional computed fields."""
    statistic: tracemalloc.Statistic
    size_diff: int
    count_diff: int
    size_diff_mb: float = 0.0
    percent_change: float = 0.0

    def __post_init__(self):
        self.size_diff_mb = self.size_diff / 1024 / 1024
        if self.statistic.size != 0:
            self.percent_change = (self.size_diff / self.statistic.size) * 100


@dataclass
class LeakCandidate:
    """Represents a potential memory leak candidate."""
    traceback: Tuple[tracemalloc.Frame, ...]
    first_seen: float
    last_seen: float
    size_history: List[int]
    count_history: List[int]
    confidence: float = 0.0
    description: str = ""

    def update(self, size: int, count: int, timestamp: float):
        self.size_history.append(size)
        self.count_history.append(count)
        self.last_seen = timestamp
        self._calculate_confidence()

    def _calculate_confidence(self):
        if len(self.size_history) < 3:
            self.confidence = 0.0
            return

        # Check for consistent growth
        growths = [
            self.size_history[i+1] - self.size_history[i]
            for i in range(len(self.size_history)-1)
        ]
        positive_growths = [g for g in growths if g > 0]

        if len(positive_growths) / len(growths) > 0.7:
            # Consistent growth pattern
            total_growth = self.size_history[-1] - self.size_history[0]
            time_span = self.last_seen - self.first_seen
            if time_span > 0:
                rate = total_growth / time_span
                self.confidence = min(1.0, rate / (self.size_history[0] / time_span + 1))
        else:
            self.confidence = 0.0


@dataclass
class ComparisonResult:
    """Complete comparison result between two snapshots."""
    added: List[StatisticDiff]
    removed: List[StatisticDiff]
    changed: List[StatisticDiff]
    unchanged: List[tracemalloc.Statistic]
    total_size_diff: int
    total_count_diff: int
    timestamp: float = field(default_factory=time.time)

    @property
    def total_size_diff_mb(self) -> float:
        return self.total_size_diff / 1024 / 1024

    def get_top_changes(self, n: int = 10, by: str = 'size') -> List[StatisticDiff]:
        """Get top N changes by size or count."""
        all_changes = self.added + self.changed + self.removed
        if by == 'size':
            return sorted(all_changes, key=lambda x: abs(x.size_diff), reverse=True)[:n]
        elif by == 'count':
            return sorted(all_changes, key=lambda x: abs(x.count_diff), reverse=True)[:n]
        return all_changes[:n]


class SnapshotComparator:
    """
    Advanced snapshot comparison with detailed analysis.

    Provides rich comparison capabilities beyond basic tracemalloc.
    """

    def __init__(self):
        self._comparison_history: List[ComparisonResult] = []

    def compare(
        self,
        snapshot1: tracemalloc.Snapshot,
        snapshot2: tracemalloc.Snapshot,
        key_type: str = 'lineno',
        filters: Optional[List[tracemalloc.Filter]] = None,
    ) -> ComparisonResult:
        """Compare two snapshots with detailed analysis."""
        if filters:
            snapshot1 = snapshot1.filter_traces(filters)
            snapshot2 = snapshot2.filter_traces(filters)

        raw_diff = snapshot1.compare_to(snapshot2, key_type)

        added = []
        removed = []
        changed = []

        for diff in raw_diff:
            stat_diff = StatisticDiff(
                statistic=diff,
                size_diff=diff.size_diff,
                count_diff=diff.count_diff,
            )
            if diff.size_diff > 0 and diff.count_diff > 0:
                added.append(stat_diff)
            elif diff.size_diff < 0 and diff.count_diff < 0:
                removed.append(stat_diff)
            else:
                changed.append(stat_diff)

        # Get unchanged (present in both with no size change)
        stats1 = {s.traceback: s for s in snapshot1.statistics(key_type)}
        stats2 = {s.traceback: s for s in snapshot2.statistics(key_type)}
        unchanged = [s for tb, s in stats1.items() if tb in stats2 and stats2[tb].size == s.size]

        result = ComparisonResult(
            added=added,
            removed=removed,
            changed=changed,
            unchanged=unchanged,
            total_size_diff=sum(d.size_diff for d in added) + sum(d.size_diff for d in changed),
            total_count_diff=sum(d.count_diff for d in added) + sum(d.count_diff for d in changed),
        )

        self._comparison_history.append(result)
        return result

    def compare_snapshots(
        self,
        snap1: 'MemorySnapshot',
        snap2: 'MemorySnapshot',
        key_type: str = 'lineno',
    ) -> ComparisonResult:
        """Compare two MemorySnapshot objects."""
        return self.compare(snap1.snapshot, snap2.snapshot, key_type)

    def get_history(self) -> List[ComparisonResult]:
        return list(self._comparison_history)

    def clear_history(self):
        self._comparison_history.clear()


@dataclass
class GrowthRecord:
    """Record of memory growth for a specific traceback."""
    traceback: Tuple[tracemalloc.Frame, ...]
    size_history: List[int]
    count_history: List[int]
    timestamps: List[float]
    growth_rate_bps: float = 0.0  # bytes per second
    is_suspected_leak: bool = False

    def update(self, size: int, count: int, timestamp: float):
        self.size_history.append(size)
        self.count_history.append(count)
        self.timestamps.append(timestamp)
        if len(self.size_history) > 2:
            time_diff = self.timestamps[-1] - self.timestamps[0]
            if time_diff > 0:
                self.growth_rate_bps = (self.size_history[-1] - self.size_history[0]) / time_diff


class GrowthAnalyzer:
    """
    Analyze memory growth patterns over time.

    Tracks allocations across multiple snapshots to identify
    growing memory regions and potential leaks.
    """

    def __init__(
        self,
        min_growth_bytes: int = 1024,
        min_growth_percent: float = 10.0,
        window_size: int = 10,
    ):
        self.min_growth_bytes = min_growth_bytes
        self.min_growth_percent = min_growth_percent
        self.window_size = window_size
        self._snapshots: List[MemorySnapshot] = []
        self._growth_records: List[GrowthRecord] = []

    def add_snapshot(self, snapshot: 'MemorySnapshot'):
        """Add a snapshot for growth analysis."""
        self._snapshots.append(snapshot)
        self._analyze_growth(snapshot)

    def _analyze_growth(self, snapshot: 'MemorySnapshot'):
        stats = snapshot.statistics('traceback')

        for stat in stats:
            tb = stat.traceback
            existing = next((r for r in self._growth_records if r.traceback == tb), None)

            if existing:
                existing.update(stat.size, stat.count, snapshot.timestamp)
            else:
                record = self.GrowthRecord(
                    traceback=tb,
                    size_history=[stat.size],
                    count_history=[stat.count],
                    timestamps=[snapshot.timestamp],
                )
                self._growth_records.append(record)

        # Check for suspected leaks
        for record in self._growth_records:
            if len(record.size_history) >= self.window_size:
                recent = record.size_history[-self.window_size:]
                if all(recent[i] <= recent[i+1] for i in range(len(recent)-1)):
                    total_growth = recent[-1] - recent[0]
                    if total_growth >= self.min_growth_bytes:
                        percent = (total_growth / recent[0]) * 100 if recent[0] > 0 else 0
                        if percent >= self.min_growth_percent:
                            record.is_suspected_leak = True

    def get_suspected_leaks(self) -> List[GrowthRecord]:
        """Get all suspected memory leaks."""
        return [r for r in self._growth_records if r.is_suspected_leak]

    def get_growth_summary(self) -> Dict[str, Any]:
        """Get summary of growth analysis."""
        leaks = self.get_suspected_leaks()
        return {
            "total_tracked": len(self._growth_records),
            "suspected_leaks": len(leaks),
            "total_growth_bytes": sum(r.size_history[-1] - r.size_history[0] for r in leaks if len(r.size_history) > 1),
            "top_growing": sorted(
                [r for r in self._growth_records if len(r.size_history) > 1],
                key=lambda x: x.growth_rate_bps,
                reverse=True
            )[:10],
        }

    def clear(self):
        self._snapshots.clear()
        self._growth_records.clear()


class LeakDetector:
    """
    Advanced memory leak detection with multiple strategies.

    Combines snapshot comparison, growth analysis, and
    allocation pattern recognition to detect leaks.
    """

    def __init__(
        self,
        session: Optional['TracemallocSession'] = None,
        comparison_interval: int = 5,
        min_leak_size: int = 1024 * 1024,  # 1MB
        max_snapshots: int = 100,
    ):
        from tracemalloc_mastery.core import MemorySnapshot, TracemallocSession
        self.session = session or TracemallocSession.get_default()
        self.comparison_interval = comparison_interval
        self.min_leak_size = min_leak_size
        self.max_snapshots = max_snapshots
        self._snapshots: List[MemorySnapshot] = []
        self._leak_candidates: List[LeakCandidate] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[LeakCandidate], None]] = []

    def start_detection(self):
        """Start automatic leak detection."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()

    def stop_detection(self):
        """Stop automatic leak detection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _detection_loop(self):
        while self._running:
            time.sleep(self.comparison_interval)
            if self._running:
                self._analyze()

    def _analyze(self):
        with self._lock:
            if len(self._snapshots) < 2:
                return

            comparator = SnapshotComparator()
            latest = self._snapshots[-1]
            previous = self._snapshots[-2]

            result = comparator.compare(latest.snapshot, previous.snapshot)

            for diff in result.added:
                if diff.size_diff >= self.min_leak_size:
                    self._register_candidate(diff, latest.timestamp)

            for candidate in self._leak_candidates:
                stat = self._find_stat(latest, candidate.traceback)
                if stat:
                    candidate.update(stat.size, stat.count, latest.timestamp)
                    if candidate.confidence > 0.7:
                        for callback in self._callbacks:
                            with suppress(Exception):
                                callback(candidate)

            # Cleanup old snapshots
            if len(self._snapshots) > self.max_snapshots:
                self._snapshots = self._snapshots[-self.max_snapshots:]

    def _register_candidate(self, diff: StatisticDiff, timestamp: float):
        existing = next(
            (c for c in self._leak_candidates if c.traceback == diff.statistic.traceback),
            None
        )
        if existing:
            existing.update(diff.statistic.size, diff.statistic.count, timestamp)
        else:
            candidate = self.LeakCandidate(
                traceback=diff.statistic.traceback,
                first_seen=timestamp,
                last_seen=timestamp,
                size_history=[diff.statistic.size],
                count_history=[diff.statistic.count],
            )
            candidate.description = self._generate_description(candidate)
            self._leak_candidates.append(candidate)

    def _find_stat(self, snapshot: 'MemorySnapshot', traceback) -> Optional[tracemalloc.Statistic]:
        for stat in snapshot.statistics('traceback'):
            if stat.traceback == traceback:
                return stat
        return None

    def _generate_description(self, candidate: LeakCandidate) -> str:
        frames = list(candidate.traceback)
        if frames:
            frame = frames[0]
            return f"Potential leak at {frame.filename}:{frame.lineno} in {frame.function}"
        return "Unknown location"

    def register_callback(self, callback: Callable[['LeakCandidate'], None]):
        """Register callback for detected leaks."""
        self._callbacks.append(callback)

    def take_snapshot(self, label: str = "") -> 'MemorySnapshot':
        """Take a snapshot and add to analysis."""
        snapshot = self.session.take_snapshot(label)
        with self._lock:
            self._snapshots.append(snapshot)
        return snapshot

    def get_leak_candidates(self, min_confidence: float = 0.5) -> List[LeakCandidate]:
        """Get current leak candidates above confidence threshold."""
        return [c for c in self._leak_candidates if c.confidence >= min_confidence]

    def get_report(self) -> Dict[str, Any]:
        """Get comprehensive leak detection report."""
        candidates = self.get_leak_candidates()
        return {
            "total_candidates": len(self._leak_candidates),
            "high_confidence": len(candidates),
            "candidates": [
                {
                    "description": c.description,
                    "confidence": c.confidence,
                    "growth_bytes": c.size_history[-1] - c.size_history[0] if len(c.size_history) > 1 else 0,
                    "growth_rate_bps": (c.size_history[-1] - c.size_history[0]) / (c.last_seen - c.first_seen) if c.last_seen > c.first_seen else 0,
                    "first_seen": c.first_seen,
                    "last_seen": c.last_seen,
                    "traceback": self._format_traceback(c.traceback),
                }
                for c in candidates
            ],
        }

    def _format_traceback(self, traceback) -> List[str]:
        return [f"{f.filename}:{f.lineno} in {f.function}" for f in traceback]


@dataclass
class AllocationStats:
    """Statistics for a specific allocation pattern."""
    count: int = 0
    total_size: int = 0
    min_size: int = 0
    max_size: int = 0
    sizes: List[int] = field(default_factory=list)
    timestamps: List[float] = field(default_factory=list)
    traceback: Tuple = ()

    def add(self, size: int, timestamp: float):
        self.count += 1
        self.total_size += size
        self.min_size = min(self.min_size, size) if self.min_size else size
        self.max_size = max(self.max_size, size)
        self.sizes.append(size)
        self.timestamps.append(timestamp)


class AllocationProfiler:
    """
    Profile memory allocations with detailed statistics.

    Tracks allocation patterns, frequency, and sizes
    to identify optimization opportunities.
    """

    def __init__(self, session: Optional['TracemallocSession'] = None):
        from tracemalloc_mastery.core import TracemallocSession
        self.session = session or TracemallocSession.get_default()
        self._allocations: Dict[Tuple, AllocationStats] = {}
        self._total_allocations = 0
        self._total_bytes = 0

    def profile_allocation(self, size: int, traceback: Tuple):
        """Record an allocation."""
        key = traceback
        if key not in self._allocations:
            self._allocations[key] = self.AllocationStats(traceback=traceback)
        self._allocations[key].add(size, time.time())
        self._total_allocations += 1
        self._total_bytes += size

    def get_top_allocations(self, n: int = 20, by: str = 'total_size') -> List[AllocationStats]:
        """Get top allocations by various criteria."""
        allocs = list(self._allocations.values())
        if by == 'total_size':
            allocs.sort(key=lambda x: x.total_size, reverse=True)
        elif by == 'count':
            allocs.sort(key=lambda x: x.count, reverse=True)
        elif by == 'avg_size':
            allocs.sort(key=lambda x: x.avg_size, reverse=True)
        elif by == 'rate':
            allocs.sort(key=lambda x: x.allocation_rate, reverse=True)
        return allocs[:n]

    def get_allocation_stats(self) -> Dict[str, Any]:
        """Get overall allocation statistics."""
        return {
            "total_allocations": self._total_allocations,
            "total_bytes": self._total_bytes,
            "unique_traces": len(self._allocations),
            "avg_allocation_size": self._total_bytes / self._total_allocations if self._total_allocations else 0,
        }

    def find_hotspots(self, threshold_percent: float = 5.0) -> List[AllocationStats]:
        """Find allocation hotspots (top contributors)."""
        allocs = self.get_top_allocations(by='total_size')
        total = self._total_bytes
        hotspots = []
        for alloc in allocs:
            percent = (alloc.total_size / total * 100) if total else 0
            if percent >= threshold_percent:
                hotspots.append(alloc)
            else:
                break
        return hotspots

    def clear(self):
        self._allocations.clear()
        self._total_allocations = 0
        self._total_bytes = 0


class MemoryReportGenerator:
    """
    Generate comprehensive memory reports in multiple formats.
    """

    def __init__(self, session: Optional['TracemallocSession'] = None):
        from tracemalloc_mastery.core import TracemallocSession
        self.session = session or TracemallocSession.get_default()

    def generate_report(
        self,
        snapshot: 'MemorySnapshot',
        include_top: int = 20,
        include_comparison: Optional['MemorySnapshot'] = None,
        key_type: str = 'lineno',
    ) -> Dict[str, Any]:
        """Generate a comprehensive memory report."""
        report = {
            "timestamp": snapshot.timestamp,
            "label": snapshot.label,
            "domain": snapshot.domain,
            "process_memory_mb": snapshot.process_memory_mb,
            "traced_memory": self.session.get_traced_memory(),
            "top_allocations": [],
            "statistics": {},
        }

        # Top allocations
        top_stats = snapshot.top_allocations(include_top, key_type)
        report["top_allocations"] = [
            {
                "size_mb": s.size / 1024 / 1024,
                "size_kb": s.size / 1024,
                "count": s.count,
                "traceback": self._format_traceback(s.traceback),
            }
            for s in top_stats
        ]

        # Statistics by key type
        for kt in ['lineno', 'filename', 'traceback']:
            stats = snapshot.statistics(kt)
            report["statistics"][kt] = {
                "total_allocations": sum(s.count for s in stats),
                "total_bytes": sum(s.size for s in stats),
                "unique_locations": len(stats),
            }

        # Comparison if provided
        if include_comparison:
            comparator = SnapshotComparator()
            diff = comparator.compare(snapshot.snapshot, include_comparison.snapshot, key_type)
            report["comparison"] = {
                "total_size_diff_mb": diff.total_size_diff_mb,
                "total_count_diff": diff.total_count_diff,
                "top_increases": [
                    {
                        "size_diff_mb": d.size_diff_mb,
                        "percent_change": d.percent_change,
                        "traceback": self._format_traceback(d.statistic.traceback),
                    }
                    for d in diff.get_top_changes(10, 'size')
                ],
            }

        return report

    def _format_traceback(self, traceback) -> List[str]:
        if not traceback:
            return []
        return [f"{f.filename}:{f.lineno} in {f.function}" for f in traceback]

    def generate_text_report(self, snapshot: 'MemorySnapshot', **kwargs) -> str:
        """Generate human-readable text report."""
        report = self.generate_report(snapshot, **kwargs)
        lines = [
            "=" * 60,
            f"MEMORY REPORT: {report['label']}",
            "=" * 60,
            f"Timestamp: {time.ctime(report['timestamp'])}",
            f"Domain: {report['domain']}",
            f"Process Memory: {report['process_memory_mb']:.2f} MB",
            f"Traced Current: {report['traced_memory'][0] / 1024 / 1024:.2f} MB",
            f"Traced Peak: {report['traced_memory'][1] / 1024 / 1024:.2f} MB",
            "",
            "TOP ALLOCATIONS:",
            "-" * 60,
        ]

        for i, alloc in enumerate(report['top_allocations'], 1):
            lines.append(f"{i:2d}. {alloc['size_mb']:.2f} MB ({alloc['count']} allocations)")
            for tb in alloc['traceback'][:5]:
                lines.append(f"      {tb}")
            if len(alloc['traceback']) > 5:
                lines.append(f"      ... and {len(alloc['traceback']) - 5} more frames")
            lines.append("")

        if 'comparison' in report:
            comp = report['comparison']
            lines.extend([
                "COMPARISON:",
                "-" * 60,
                f"Total Size Change: {comp['total_size_diff_mb']:.2f} MB",
                f"Total Count Change: {comp['total_count_diff']}",
                "",
                "TOP INCREASES:",
            ])
            for inc in comp['top_increases']:
                lines.append(f"  +{inc['size_diff_mb']:.2f} MB ({inc['percent_change']:.1f}%)")
                for tb in inc['traceback'][:3]:
                    lines.append(f"      {tb}")

        return "\n".join(lines)

    def generate_json_report(self, snapshot: 'MemorySnapshot', **kwargs) -> str:
        """Generate JSON report."""
        import json
        report = self.generate_report(snapshot, **kwargs)
        # Convert non-serializable objects
        def serialize(obj):
            if isinstance(obj, (tuple, list)):
                return [serialize(x) for x in obj]
            elif hasattr(obj, '__dict__'):
                return serialize(obj.__dict__)
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            return str(obj)
        return json.dumps(serialize(report), indent=2)
