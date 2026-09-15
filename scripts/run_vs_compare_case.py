#!/usr/bin/env python3
"""Run a VapourSynth migration comparison case and emit a JSON report.

The same case file should be run in the R73/API3 environment and the
R74+/API4 environment. The case file defines clips and error-path tests; this
runner handles plugin loading, frame hashing, metadata capture, and JSON
serialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path
from typing import Any


class IsolatedEnvironmentPolicy:
    """Single-environment policy that can set core creation flags before core use."""

    def __init__(self, vs_module: Any, flags: int) -> None:
        self._vs = vs_module
        self._flags = flags
        self._api = None
        self._environment = None

    def on_policy_registered(self, api: Any) -> None:
        self._api = api
        self._environment = api.create_environment(self._flags)

    def on_policy_cleared(self) -> None:
        self._api = None
        self._environment = None

    def get_current_environment(self) -> Any:
        return self._environment

    def set_environment(self, environment: Any) -> Any:
        previous = self._environment
        if environment is not None:
            self._environment = environment
        return previous

    def is_alive(self, environment: Any) -> bool:
        return environment is self._environment

    def close(self) -> None:
        if self._api is not None and self._environment is not None:
            self._api.destroy_environment(self._environment)
            self._environment = None


def install_isolated_policy(vs_module: Any, disable_autoload: bool) -> IsolatedEnvironmentPolicy | None:
    if vs_module.has_policy():
        return None
    flags = 0
    if disable_autoload:
        flags |= int(vs_module.DISABLE_AUTO_LOADING)
    policy = IsolatedEnvironmentPolicy(vs_module, flags)
    vs_module.register_policy(policy)
    return policy


def stable_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [stable_value(item) for item in value]
    return repr(value)


def frame_hash(frame: Any) -> str:
    digest = hashlib.sha256()
    for plane in range(frame.format.num_planes):
        digest.update(memoryview(frame[plane]).tobytes())
    return digest.hexdigest()


def frame_report(frame: Any, n: int) -> dict[str, Any]:
    props = {str(key): stable_value(frame.props[key]) for key in sorted(frame.props.keys())}
    return {
        "n": n,
        "width": frame.width,
        "height": frame.height,
        "format": {
            "id": getattr(frame.format, "id", None),
            "name": getattr(frame.format, "name", None),
            "color_family": repr(getattr(frame.format, "color_family", None)),
            "sample_type": repr(getattr(frame.format, "sample_type", None)),
            "bits_per_sample": getattr(frame.format, "bits_per_sample", None),
            "bytes_per_sample": getattr(frame.format, "bytes_per_sample", None),
            "num_planes": getattr(frame.format, "num_planes", None),
            "subsampling_w": getattr(frame.format, "subsampling_w", None),
            "subsampling_h": getattr(frame.format, "subsampling_h", None),
        },
        "hash": frame_hash(frame),
        "props": props,
    }


def plane_stats_report(core: Any, clip: Any, n: int) -> list[dict[str, Any]]:
    stats = []
    num_planes = clip.format.num_planes
    for plane in range(num_planes):
        prop = f"PlaneStats{plane}"
        stats_clip = core.std.PlaneStats(clip, plane=plane, prop=prop)
        frame = stats_clip.get_frame(n)
        try:
            stats.append(
                {
                    "plane": plane,
                    "min": stable_value(frame.props[f"{prop}Min"]),
                    "max": stable_value(frame.props[f"{prop}Max"]),
                    "average": stable_value(frame.props[f"{prop}Average"]),
                }
            )
        finally:
            close = getattr(frame, "close", None)
            if close:
                close()
    return stats


def clip_report(core: Any, name: str, clip: Any, frames: list[int]) -> dict[str, Any]:
    info = {
        "name": name,
        "node": {
            "width": getattr(clip, "width", None),
            "height": getattr(clip, "height", None),
            "num_frames": getattr(clip, "num_frames", None),
            "format": getattr(getattr(clip, "format", None), "name", None),
        },
        "frames": [],
    }
    for n in frames:
        frame = clip.get_frame(n)
        try:
            frame_info = frame_report(frame, n)
            frame_info["plane_stats"] = plane_stats_report(core, clip, n)
            info["frames"].append(frame_info)
        finally:
            close = getattr(frame, "close", None)
            if close:
                close()
    return info


def error_report(name: str, callback: Any) -> dict[str, Any]:
    try:
        result = callback()
        get_frame = getattr(result, "get_frame", None)
        if get_frame:
            frame = get_frame(0)
            close = getattr(frame, "close", None)
            if close:
                close()
    except Exception as exc:  # noqa: BLE001 - report exact environment behavior.
        return {
            "name": name,
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
        }
    return {
        "name": name,
        "raised": False,
        "type": None,
        "message": None,
    }


def load_case(case_path: Path, plugin_path: str, label: str) -> dict[str, Any]:
    namespace = runpy.run_path(str(case_path), init_globals={"PLUGIN_PATH": plugin_path, "LABEL": label})
    if "make_cases" not in namespace:
        raise RuntimeError("case file must define make_cases(core, plugin_path)")
    return namespace


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run a VapourSynth API migration comparison case.")
    parser.add_argument("--case", required=True, help="Python case file defining make_cases(core, plugin_path).")
    plugin_group = parser.add_mutually_exclusive_group(required=True)
    plugin_group.add_argument("--plugin", help="Plugin path to load with core.std.LoadPlugin.")
    plugin_group.add_argument("--no-plugin", action="store_true", help="Do not load a plugin; useful for runner smoke tests.")
    parser.add_argument("--out", required=True, help="JSON report path to write.")
    parser.add_argument("--label", default="", help="Environment label such as api3-r73 or api4-current.")
    parser.add_argument(
        "--dll-dir",
        action="append",
        default=[],
        help="Extra directory to add to the Windows DLL search path before loading the plugin. May be repeated.",
    )
    parser.add_argument(
        "--allow-autoload",
        action="store_true",
        help="Do not create the VapourSynth core with DISABLE_AUTO_LOADING.",
    )
    args = parser.parse_args(argv)

    dll_handles = []
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        dll_dirs = [Path(p).resolve() for p in args.dll_dir]
        if args.plugin:
            dll_dirs.insert(0, Path(args.plugin).resolve().parent)
        for dll_dir in dll_dirs:
            if dll_dir.exists():
                dll_handles.append(add_dll_directory(str(dll_dir)))

    import vapoursynth as vs  # pylint: disable=import-outside-toplevel

    policy = install_isolated_policy(vs, not args.allow_autoload)
    try:
        core = vs.core
        if args.plugin:
            core.std.LoadPlugin(args.plugin)

        plugin_path = args.plugin or ""
        namespace = load_case(Path(args.case).resolve(), plugin_path, args.label)
        case_data = namespace["make_cases"](core, plugin_path)
        clip_cases = case_data.get("clips", [])
        error_cases = case_data.get("errors", [])

        report = {
            "label": args.label,
            "plugin": str(Path(args.plugin).resolve()) if args.plugin else "",
            "autoload_disabled": not args.allow_autoload,
            "single_plugin_process": True,
            "vapoursynth_version": getattr(vs, "__version__", None),
            "api_version": getattr(vs, "API_VERSION", None),
            "clips": [],
            "errors": [],
        }

        for case in clip_cases:
            name = case["name"]
            clip = case["clip"]
            frames = list(case.get("frames", [0]))
            report["clips"].append(clip_report(core, name, clip, frames))

        for case in error_cases:
            report["errors"].append(error_report(case["name"], case["call"]))

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    finally:
        if policy is not None:
            policy.close()
        for handle in dll_handles:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
