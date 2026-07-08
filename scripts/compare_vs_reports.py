#!/usr/bin/env python3
"""Compare two VapourSynth migration JSON reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


IGNORED_TOP_LEVEL = {"label", "plugin", "vapoursynth_version", "api_version"}


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def is_plane_stat_value(path: str) -> bool:
    return ".plane_stats[" in path and path.rsplit(".", 1)[-1] in {"min", "max", "average"}


def compare_values(path: str, old: Any, new: Any, diffs: list[str], plane_stats_eps: float | None) -> None:
    if type(old) is not type(new):
        diffs.append(f"{path}: type differs: {type(old).__name__} != {type(new).__name__}")
        return
    if isinstance(old, dict):
        old_keys = set(old)
        new_keys = set(new)
        for key in sorted(old_keys - new_keys):
            diffs.append(f"{path}.{key}: missing in new report")
        for key in sorted(new_keys - old_keys):
            diffs.append(f"{path}.{key}: extra in new report")
        for key in sorted(old_keys & new_keys):
            compare_values(f"{path}.{key}", old[key], new[key], diffs, plane_stats_eps)
        return
    if isinstance(old, list):
        if len(old) != len(new):
            diffs.append(f"{path}: length differs: {len(old)} != {len(new)}")
            return
        for index, (old_item, new_item) in enumerate(zip(old, new)):
            compare_values(f"{path}[{index}]", old_item, new_item, diffs, plane_stats_eps)
        return
    if plane_stats_eps is not None and is_plane_stat_value(path) and isinstance(old, (int, float)):
        if abs(float(old) - float(new)) > plane_stats_eps:
            diffs.append(f"{path}: abs({old!r} - {new!r}) > {plane_stats_eps}")
        return
    if old != new:
        diffs.append(f"{path}: {old!r} != {new!r}")


def comparable(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key not in IGNORED_TOP_LEVEL}


def build_result(old_path: Path, new_path: Path, plane_stats_eps: float | None, max_diffs: int) -> dict[str, Any]:
    old_report = load_report(old_path)
    new_report = load_report(new_path)

    diffs: list[str] = []
    compare_values("$", comparable(old_report), comparable(new_report), diffs, plane_stats_eps)
    return {
        "old": str(old_path),
        "new": str(new_path),
        "ok": not diffs,
        "diff_count": len(diffs),
        "diffs": diffs[:max_diffs],
        "omitted_diff_count": max(0, len(diffs) - max_diffs),
        "plane_stats_eps": plane_stats_eps,
        "ignored_top_level": sorted(IGNORED_TOP_LEVEL),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compare two VapourSynth migration reports.")
    parser.add_argument("old", help="JSON report from the R73/API3 baseline.")
    parser.add_argument("new", help="JSON report from the R74+/API4 migration.")
    parser.add_argument("--max-diffs", type=int, default=80, help="Maximum differences to print.")
    parser.add_argument(
        "--plane-stats-eps",
        type=float,
        default=None,
        help="Allow this absolute tolerance for PlaneStats min/max/average values.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON comparison result.")
    args = parser.parse_args(argv)

    result = build_result(Path(args.old), Path(args.new), args.plane_stats_eps, args.max_diffs)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1

    if result["ok"]:
        print("Reports match.")
        return 0

    print(f"Reports differ: {result['diff_count']} difference(s).")
    for diff in result["diffs"]:
        print(f"- {diff}")
    if result["omitted_diff_count"]:
        print(f"... {result['omitted_diff_count']} more difference(s) omitted.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
