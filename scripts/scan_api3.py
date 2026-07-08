#!/usr/bin/env python3
"""Scan a VapourSynth plugin tree for API3 migration markers.

This script is intentionally read-only. It reports likely API3 surface area and
manual-review hazards before Codex edits source files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inl",
    ".ipp",
    ".txt",
    ".md",
    ".rst",
    ".cmake",
    ".meson",
    ".build",
    ".props",
    ".targets",
    ".vcxproj",
    ".filters",
}

DEFAULT_FILENAMES = {
    "CMakeLists.txt",
    "meson.build",
    "Makefile",
    "makefile",
    "GNUmakefile",
    "configure.ac",
}

C_LIKE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".inl",
    ".ipp",
}

HASH_COMMENT_EXTENSIONS = {
    ".cmake",
    ".meson",
    ".build",
}

HASH_COMMENT_FILENAMES = {
    "CMakeLists.txt",
    "meson.build",
    "Makefile",
    "makefile",
    "GNUmakefile",
    "configure.ac",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".vs",
    ".vscode",
    "build",
    "dist",
    "out",
    "external",
    "third_party",
    "node_modules",
    "__pycache__",
    "_deps",
    ".mypy_cache",
    ".pytest_cache",
}


def should_skip_dir(name: str) -> bool:
    lower = name.lower()
    return (
        name in SKIP_DIRS
        or name == "verification"
        or name.startswith("verification-")
        or lower.startswith("build-")
        or lower.startswith("cmake-build-")
        or lower.startswith(".venv")
    )


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    severity: str
    hint: str


RULES = [
    Rule("api3-header", re.compile(r'#\s*include\s*[<"]VapourSynth\.h[>"]'), "high", "Use VapourSynth4.h."),
    Rule("api3-helper", re.compile(r'#\s*include\s*[<"]VSHelper\.h[>"]'), "high", "Use VSHelper4.h."),
    Rule("api3-entry-point", re.compile(r"\bVapourSynthPluginInit\s*\("), "high", "Use VapourSynthPluginInit2(VSPlugin *, const VSPLUGINAPI *)."),
    Rule("api3-config-callback", re.compile(r"\bVSConfigPlugin\b|\bconfigFunc\s*\("), "high", "Use vspapi->configPlugin with plugin version and flags."),
    Rule("api3-register-callback", re.compile(r"\bVSRegisterFunction\b|\bregisterFunc\s*\("), "high", "Use vspapi->registerFunction and add return type strings."),
    Rule("api3-filter-init", re.compile(r"\bVSFilterInit\b|\bsetVideoInfo\s*\("), "high", "Inline init work into the create function and pass VSVideoInfo to createVideoFilter."),
    Rule("api3-instance-data-indirection", re.compile(r"void\s*\*\s*\*\s*instanceData|[)=,(]\s*\*\s*instanceData"), "high", "API4 removes ordinary VSFilterInit and getFrame receives void *instanceData; remove obsolete indirection."),
    Rule("api3-create-filter", re.compile(r"->\s*createFilter\s*\("), "high", "Use createVideoFilter/createAudioFilter with VSFilterDependency."),
    Rule("api3-frame-ref", re.compile(r"\bVSFrameRef\b"), "high", "Use VSFrame."),
    Rule("api3-node-ref", re.compile(r"\bVSNodeRef\b"), "high", "Use VSNode."),
    Rule("api3-func-ref", re.compile(r"\bVSFuncRef\b"), "high", "Use VSFunction."),
    Rule("api3-format", re.compile(r"\bVSFormat\b"), "medium", "Use VSVideoFormat; VSVideoInfo.format is a value in API4."),
    Rule("api3-prop-api", re.compile(r"->\s*prop(?:Get|Set|Num|Delete)[A-Za-z0-9_]*\s*\("), "high", "Use map* API names; mapSetData needs a data type hint."),
    Rule("api3-map-error", re.compile(r"->\s*(?:setError|getError)\s*\("), "high", "Use mapSetError/mapGetError."),
    Rule("api3-clone-ref", re.compile(r"->\s*clone(?:FrameRef|NodeRef|FuncRef)\s*\("), "medium", "Use addFrameRef/addNodeRef/addFunctionRef."),
    Rule("api3-function-object", re.compile(r"->\s*(?:createFunc|callFunc|freeFunc)\s*\("), "medium", "Use createFunction/callFunction/freeFunction."),
    Rule("api3-frame-props", re.compile(r"->\s*getFrameProps(?:RO|RW)\s*\("), "medium", "Use getFramePropertiesRO/getFramePropertiesRW."),
    Rule("api3-frame-format", re.compile(r"->\s*getFrameFormat\s*\("), "medium", "Use getVideoFrameFormat."),
    Rule("api3-format-registry", re.compile(r"->\s*(?:getFormatPreset|registerFormat)\s*\("), "medium", "Use getVideoFormatByID/queryVideoFormat/queryVideoFormatID."),
    Rule("api3-plugin-lookup", re.compile(r"->\s*(?:getPluginById|getPluginByNs)\s*\("), "medium", "Use getPluginByID/getPluginByNamespace."),
    Rule("api3-video-info-format-pointer", re.compile(r"(?:\b(?:vi|d->vi|data\.vi|data->vi)->format|\.format)\s*->"), "medium", "VSVideoInfo.format is a value in API4; update member access deliberately."),
    Rule("api3-video-info-format-null-check", re.compile(r"(?:!\s*(?:\b(?:vi|d->vi|d\.vi|data\.vi|data->vi)->format\b|\b[A-Za-z_][A-Za-z0-9_]*\.format\b)|(?:\b(?:vi|d->vi|d\.vi|data\.vi|data->vi)->format\b|\b[A-Za-z_][A-Za-z0-9_]*\.format\b)\s*(?:!=|==)\s*(?:NULL|nullptr|0)\b)"), "medium", "Use colorFamily != cfUndefined for VSVideoInfo format availability checks."),
    Rule("api3-append-mode", re.compile(r"\bpa(?:Replace|Append|Touch)\b"), "medium", "Use maReplace/maAppend; review paTouch manually."),
    Rule("api3-activation", re.compile(r"\barFrameReady\b|\bqueryCompletedFrame\s*\("), "manual", "API4 normal filters use arInitial/arAllFramesReady; redesign request flow."),
    Rule("api3-color-family", re.compile(r"\bcm(?:Gray|RGB|YUV|YCoCg|Compat)\b"), "medium", "Use cfGray/cfRGB/cfYUV; review YCoCg/compat formats manually."),
    Rule("api3-compatible-format", re.compile(r"\bpfCompat[A-Za-z0-9_]*\b"), "manual", "Packed compatibility formats should not be migrated mechanically."),
    Rule("api3-helper-functions", re.compile(r"(?<!::)\b(?:isConstantFormat|isSameFormat|vs_normalizeRational|vs_addRational|int64ToIntS|vs_bitblt|areValidDimensions)\s*\("), "medium", "Use VSHelper4 C names with vsh_ prefix or C++ vsh:: namespace."),
    Rule("api3-saturating-helper", re.compile(r"\bint64ToIntS\s*\(\s*[^;]*propGetInt|(?:float|double)\s*\([^;]*propGetFloat"), "medium", "Consider mapGetIntSaturated/mapGetFloatSaturated."),
    Rule("api3-helper-alloc", re.compile(r"\bVS_ALIGNED_(?:MALLOC|FREE)\b"), "medium", "Use VSH_ALIGNED_MALLOC/VSH_ALIGNED_FREE."),
    Rule("api3-arg-string", re.compile(r'"[^"\n]*:(?:clip|frame)(?:\[\])?(?=[:;])[^"\n]*"'), "medium", "API4 registration strings use vnode/vframe or anode/aframe."),
    Rule("range-property", re.compile(r"_ColorRange"), "manual", "Review manually before changing to _Range; values are inverted in API4.2."),
    Rule("api3-log-handler", re.compile(r"\b(?:VSMessageHandler|setMessageHandler|addMessageHandler|removeMessageHandler)\b"), "medium", "Use VSLogHandler/addLogHandler/removeLogHandler."),
    Rule("api3-create-core", re.compile(r"->\s*createCore\s*\("), "manual", "API4 createCore takes creation flags, not thread count."),
]


def should_scan(path: Path) -> bool:
    if path.name in DEFAULT_FILENAMES:
        return True
    return path.suffix in DEFAULT_EXTENSIONS


def iter_files(root: Path):
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not should_skip_dir(d)]
        for filename in files:
            path = Path(current_root, filename)
            if should_scan(path):
                yield path


def strip_c_like_comments(text: str) -> list[str]:
    lines: list[str] = []
    in_block = False
    for line in text.splitlines():
        out: list[str] = []
        i = 0
        in_string: str | None = None
        escaped = False
        while i < len(line):
            ch = line[i]
            nxt = line[i + 1] if i + 1 < len(line) else ""
            if in_block:
                if ch == "*" and nxt == "/":
                    in_block = False
                    i += 2
                else:
                    i += 1
                continue
            if in_string:
                out.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_string:
                    in_string = None
                i += 1
                continue
            if ch in {'"', "'"}:
                in_string = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                i += 2
                continue
            if ch == "/" and nxt == "/":
                break
            out.append(ch)
            i += 1
        lines.append("".join(out))
    return lines


def strip_hash_comment(line: str) -> str:
    in_string: str | None = None
    escaped = False
    for i, ch in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in {'"', "'"}:
            in_string = ch
            continue
        if ch == "#":
            return line[:i]
    return line


def effective_lines(path: Path, text: str) -> list[str]:
    if path.suffix in C_LIKE_EXTENSIONS:
        return strip_c_like_comments(text)
    if path.suffix in HASH_COMMENT_EXTENSIONS or path.name in HASH_COMMENT_FILENAMES:
        return [strip_hash_comment(line) for line in text.splitlines()]
    return text.splitlines()


def scan_file(path: Path, display_root: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return []
    except OSError:
        return []

    hits = []
    rel = path.relative_to(display_root)
    for lineno, line in enumerate(effective_lines(path, text), 1):
        for rule in RULES:
            if rule.pattern.search(line):
                hits.append((rule.severity, rel, lineno, rule.name, line.strip(), rule.hint))
    return hits


def severity_key(severity: str) -> int:
    order = {"high": 0, "medium": 1, "manual": 2}
    return order.get(severity, 99)


def hit_to_dict(hit) -> dict[str, object]:
    severity, rel, lineno, name, line, hint = hit
    return {
        "severity": severity,
        "path": rel.as_posix(),
        "line": lineno,
        "rule": name,
        "text": line,
        "hint": hint,
    }


def summary_to_dict(counts: dict[tuple[str, str, str], int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (severity, name, hint), count in sorted(counts.items(), key=lambda item: (severity_key(item[0][0]), item[0][1])):
        rows.append({"severity": severity, "rule": name, "hint": hint, "count": count})
    return rows


def report_to_dict(root: Path, paths: list[Path], hits: list[tuple]) -> dict[str, object]:
    counts: dict[tuple[str, str, str], int] = {}
    for severity, _rel, _lineno, name, _line, hint in hits:
        key = (severity, name, hint)
        counts[key] = counts.get(key, 0) + 1
    return {
        "path": str(root),
        "scanned_files": len(paths),
        "hits": len(hits),
        "summary": summary_to_dict(counts),
        "locations": [hit_to_dict(hit) for hit in hits],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scan for VapourSynth API3 migration markers.")
    parser.add_argument("path", nargs="?", default=".", help="Plugin project root to scan.")
    parser.add_argument("--summary-only", action="store_true", help="Only print counts by rule.")
    parser.add_argument("--fail-on-hits", action="store_true", help="Exit with code 1 when markers are found.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report.")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2

    hits = []
    if root.is_file():
        display_root = root.parent
        paths = [root] if should_scan(root) else []
    else:
        display_root = root
        paths = list(iter_files(root))

    for path in paths:
        hits.extend(scan_file(path, display_root))

    hits.sort(key=lambda h: (severity_key(h[0]), str(h[1]).lower(), h[2], h[3]))

    if args.json:
        print(json.dumps(report_to_dict(root, paths, hits), indent=2, sort_keys=True))
        return 1 if hits and args.fail_on_hits else 0

    counts: dict[tuple[str, str, str], int] = {}
    for severity, _rel, _lineno, name, _line, hint in hits:
        key = (severity, name, hint)
        counts[key] = counts.get(key, 0) + 1

    print(f"Scanned: {root}")
    print(f"Hits: {len(hits)}")
    if counts:
        print("\nSummary:")
        for (severity, name, hint), count in sorted(counts.items(), key=lambda item: (severity_key(item[0][0]), item[0][1])):
            print(f"  {severity:6} {count:4} {name}: {hint}")

    if hits and not args.summary_only:
        print("\nLocations:")
        for severity, rel, lineno, name, line, hint in hits:
            print(f"{rel}:{lineno}: [{severity}] {name}: {line}")
            print(f"    hint: {hint}")

    return 1 if hits and args.fail_on_hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
