"""Shared helpers: percentiles, run metadata, result files."""
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (no interpolation): the smallest value with at least q% of the data <= it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def pct(part: int, total: int) -> str:
    return f"{part}/{total} ({100 * part / total:.1f}%)" if total else "0/0"


def run_metadata(**extra) -> dict:
    def version(pkg: str) -> str | None:
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None

    return {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "packages": {p: version(p) for p in ("ortools", "langgraph", "langchain-google-genai", "pydantic")},
        **extra,
    }


def write_results(name: str, payload: dict, markdown: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nWritten to {RESULTS_DIR / name}.json and .md")
