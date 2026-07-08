#!/usr/bin/env python3
"""Apply conservative mechanical VapourSynth API3-to-API4 rewrites.

The script is intentionally narrow. It rewrites names that are stable across
the API3/API4 boundary and reports hazards that still need human design work.
It defaults to dry-run mode; pass --write to modify files.
"""

from __future__ import annotations

import argparse
import difflib
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
class Replacement:
    name: str
    pattern: re.Pattern[str]
    replacement: str
    note: str


@dataclass(frozen=True)
class ManualMarker:
    name: str
    pattern: re.Pattern[str]
    note: str


def word(name: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(name)}\b")


def unqualified_word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!::)\b{re.escape(name)}\b")


def member(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?P<prefix>(?:->|\.)\s*){re.escape(name)}\b")


def member_replacement(name: str) -> str:
    return rf"\g<prefix>{name}"


COMMON_REPLACEMENTS = [
    Replacement("header-vapoursynth", re.compile(r"\bVapourSynth\.h\b"), "VapourSynth4.h", "Use API4 public header."),
    Replacement("header-helper", re.compile(r"\bVSHelper\.h\b"), "VSHelper4.h", "Use API4 helper header."),
    Replacement("type-frame", word("VSFrameRef"), "VSFrame", "Rename frame type."),
    Replacement("type-node", word("VSNodeRef"), "VSNode", "Rename node type."),
    Replacement("type-function", word("VSFuncRef"), "VSFunction", "Rename function type."),
    Replacement("type-format", word("VSFormat"), "VSVideoFormat", "Rename video format type."),
    Replacement("type-free-function-data", word("VSFreeFuncData"), "VSFreeFunctionData", "Rename function-data free callback type."),
    Replacement("type-log-handler", word("VSMessageHandler"), "VSLogHandler", "Rename log handler type."),
    Replacement("type-log-handler-free", word("VSMessageHandlerFree"), "VSLogHandlerFree", "Rename log handler free type."),
    Replacement("api-prop-num-keys", member("propNumKeys"), member_replacement("mapNumKeys"), "Rename map API."),
    Replacement("api-prop-get-key", member("propGetKey"), member_replacement("mapGetKey"), "Rename map API."),
    Replacement("api-prop-num-elements", member("propNumElements"), member_replacement("mapNumElements"), "Rename map API."),
    Replacement("api-prop-get-type", member("propGetType"), member_replacement("mapGetType"), "Rename map API."),
    Replacement("api-prop-delete-key", member("propDeleteKey"), member_replacement("mapDeleteKey"), "Rename map API."),
    Replacement("api-prop-get-int-array", member("propGetIntArray"), member_replacement("mapGetIntArray"), "Rename map API."),
    Replacement("api-prop-get-float-array", member("propGetFloatArray"), member_replacement("mapGetFloatArray"), "Rename map API."),
    Replacement("api-prop-set-int-array", member("propSetIntArray"), member_replacement("mapSetIntArray"), "Rename map API."),
    Replacement("api-prop-set-float-array", member("propSetFloatArray"), member_replacement("mapSetFloatArray"), "Rename map API."),
    Replacement("api-prop-get-int", member("propGetInt"), member_replacement("mapGetInt"), "Rename map API."),
    Replacement("api-prop-get-float", member("propGetFloat"), member_replacement("mapGetFloat"), "Rename map API."),
    Replacement("api-prop-get-data-size", member("propGetDataSize"), member_replacement("mapGetDataSize"), "Rename map API."),
    Replacement("api-prop-get-data", member("propGetData"), member_replacement("mapGetData"), "Rename map API."),
    Replacement("api-prop-get-node", member("propGetNode"), member_replacement("mapGetNode"), "Rename map API."),
    Replacement("api-prop-get-frame", member("propGetFrame"), member_replacement("mapGetFrame"), "Rename map API."),
    Replacement("api-prop-get-function", member("propGetFunc"), member_replacement("mapGetFunction"), "Rename map API."),
    Replacement("api-prop-set-int", member("propSetInt"), member_replacement("mapSetInt"), "Rename map API."),
    Replacement("api-prop-set-float", member("propSetFloat"), member_replacement("mapSetFloat"), "Rename map API."),
    Replacement("api-prop-set-node", member("propSetNode"), member_replacement("mapSetNode"), "Rename map API."),
    Replacement("api-prop-set-frame", member("propSetFrame"), member_replacement("mapSetFrame"), "Rename map API."),
    Replacement("api-prop-set-function", member("propSetFunc"), member_replacement("mapSetFunction"), "Rename map API."),
    Replacement("api-set-error", member("setError"), member_replacement("mapSetError"), "Rename map error API."),
    Replacement("api-get-error", member("getError"), member_replacement("mapGetError"), "Rename map error API."),
    Replacement("api-clone-frame", member("cloneFrameRef"), member_replacement("addFrameRef"), "Rename reference increment API."),
    Replacement("api-clone-node", member("cloneNodeRef"), member_replacement("addNodeRef"), "Rename reference increment API."),
    Replacement("api-clone-function", member("cloneFuncRef"), member_replacement("addFunctionRef"), "Rename reference increment API."),
    Replacement("api-create-function", member("createFunc"), member_replacement("createFunction"), "Rename function object API."),
    Replacement("api-call-function", member("callFunc"), member_replacement("callFunction"), "Rename function object API."),
    Replacement("api-free-function", member("freeFunc"), member_replacement("freeFunction"), "Rename function object API."),
    Replacement("api-frame-props-ro", member("getFramePropsRO"), member_replacement("getFramePropertiesRO"), "Rename frame property API."),
    Replacement("api-frame-props-rw", member("getFramePropsRW"), member_replacement("getFramePropertiesRW"), "Rename frame property API."),
    Replacement("api-frame-format", member("getFrameFormat"), member_replacement("getVideoFrameFormat"), "Rename frame format API."),
    Replacement("api-get-plugin-by-id", member("getPluginById"), member_replacement("getPluginByID"), "Rename plugin lookup API."),
    Replacement("api-get-plugin-by-ns", member("getPluginByNs"), member_replacement("getPluginByNamespace"), "Rename plugin lookup API."),
    Replacement("append-replace", word("paReplace"), "maReplace", "Rename append mode."),
    Replacement("append-append", word("paAppend"), "maAppend", "Rename append mode."),
    Replacement("color-gray", word("cmGray"), "cfGray", "Rename color family."),
    Replacement("color-rgb", word("cmRGB"), "cfRGB", "Rename color family."),
    Replacement("color-yuv", word("cmYUV"), "cfYUV", "Rename color family."),
    Replacement("helper-aligned-malloc", word("VS_ALIGNED_MALLOC"), "VSH_ALIGNED_MALLOC", "Rename helper macro."),
    Replacement("helper-aligned-free", word("VS_ALIGNED_FREE"), "VSH_ALIGNED_FREE", "Rename helper macro."),
    Replacement("arg-clip", re.compile(r"(?<=:)clip(?=(?:\[\])?[:;])"), "vnode", "Registration strings use vnode."),
    Replacement("arg-frame", re.compile(r"(?<=:)frame(?=(?:\[\])?[:;])"), "vframe", "Registration strings use vframe."),
]

C_HELPER_REPLACEMENTS = [
    Replacement("helper-constant-format", word("isConstantFormat"), "vsh_isConstantVideoFormat", "Rename C helper."),
    Replacement("helper-normalize-rational", word("vs_normalizeRational"), "vsh_reduceRational", "Rename C helper."),
    Replacement("helper-add-rational", word("vs_addRational"), "vsh_addRational", "Rename C helper."),
    Replacement("helper-int64-to-int", word("int64ToIntS"), "vsh_int64ToIntS", "Rename C helper."),
    Replacement("helper-bitblt", word("vs_bitblt"), "vsh_bitblt", "Rename C helper; update stride types to ptrdiff_t."),
    Replacement("helper-valid-dimensions", word("areValidDimensions"), "vsh_areValidDimensions", "Rename C helper."),
]

CPP_HELPER_REPLACEMENTS = [
    Replacement("helper-cpp-aligned-malloc", word("vs_aligned_malloc"), "vsh::vsh_aligned_malloc", "Rename C++ helper."),
    Replacement("helper-cpp-aligned-free", word("vs_aligned_free"), "vsh::vsh_aligned_free", "Rename C++ helper."),
    Replacement("helper-constant-format", word("isConstantFormat"), "vsh::isConstantVideoFormat", "Rename C++ helper."),
    Replacement("helper-normalize-rational", word("vs_normalizeRational"), "vsh::reduceRational", "Rename C++ helper."),
    Replacement("helper-add-rational", word("vs_addRational"), "vsh::addRational", "Rename C++ helper."),
    Replacement("helper-int64-to-int", unqualified_word("int64ToIntS"), "vsh::int64ToIntS", "Rename C++ helper."),
    Replacement("helper-bitblt", word("vs_bitblt"), "vsh::bitblt", "Rename C++ helper; update stride types to ptrdiff_t."),
    Replacement("helper-valid-dimensions", unqualified_word("areValidDimensions"), "vsh::areValidDimensions", "Rename C++ helper."),
]

MANUAL_MARKERS = [
    ManualMarker("propSetData", word("propSetData"), "Rename to mapSetData and add dtUtf8/dtBinary/dtUnknown before the append argument."),
    ManualMarker("entry-point", word("VapourSynthPluginInit"), "Convert to VapourSynthPluginInit2(VSPlugin *, const VSPLUGINAPI *) and use vspapi."),
    ManualMarker("config-callback", re.compile(r"\bVSConfigPlugin\b|\bconfigFunc\s*\("), "Use vspapi->configPlugin with plugin version and flags."),
    ManualMarker("register-callback", re.compile(r"\bVSRegisterFunction\b|\bregisterFunc\s*\("), "Use vspapi->registerFunction with an explicit return type string."),
    ManualMarker("filter-init", re.compile(r"\bVSFilterInit\b|\bsetVideoInfo\s*\("), "Inline output-info setup into the create function."),
    ManualMarker("create-filter", re.compile(r"->\s*createFilter\s*\("), "Replace with createVideoFilter/createAudioFilter and VSFilterDependency."),
    ManualMarker("instance-data", re.compile(r"void\s*\*\s*\*\s*instanceData|[)=,(]\s*\*\s*instanceData"), "API4 getFrame receives void *instanceData; remove obsolete indirection."),
    ManualMarker("arFrameReady", word("arFrameReady"), "API4 removed arFrameReady; redesign request flow around arInitial/arAllFramesReady."),
    ManualMarker("queryCompletedFrame", word("queryCompletedFrame"), "API4 normal filters should use requestFrameFilter/getFrameFilter."),
    ManualMarker("paTouch", word("paTouch"), "No direct equivalent; use mapSetEmpty when creating typed empty arrays."),
    ManualMarker("color-ycocg", word("cmYCoCg"), "No direct API4 color family."),
    ManualMarker("color-compat", word("cmCompat"), "Compatibility formats should not be migrated mechanically."),
    ManualMarker("compat-format", re.compile(r"\bpfCompat[A-Za-z0-9_]*\b"), "Packed compatibility formats need manual redesign."),
    ManualMarker("range-property", word("_ColorRange"), "Do not mechanically rename to _Range; full/limited values are inverted in API 4.2."),
    ManualMarker("video-info-format-pointer", re.compile(r"(?:\b(?:vi|d->vi|data\.vi|data->vi)->format|\.format)\s*->"), "VSVideoInfo.format is a value in API4; update member access deliberately."),
    ManualMarker("video-info-format-null-check", re.compile(r"(?:!\s*(?:\b(?:vi|d->vi|d\.vi|data\.vi|data->vi)->format\b|\b[A-Za-z_][A-Za-z0-9_]*\.format\b)|(?:\b(?:vi|d->vi|d\.vi|data\.vi|data->vi)->format\b|\b[A-Za-z_][A-Za-z0-9_]*\.format\b)\s*(?:!=|==)\s*(?:NULL|nullptr|0)\b)"), "Replace nullable VSVideoInfo format checks with colorFamily != cfUndefined."),
    ManualMarker("format-preset", word("getFormatPreset"), "Use getVideoFormatByID; API4 changes this to an output-argument call."),
    ManualMarker("format-register", word("registerFormat"), "Use queryVideoFormat/queryVideoFormatID; API4 changes the call shape."),
    ManualMarker("log-message", word("logMessage"), "API4 logMessage takes VSCore * as an additional argument."),
    ManualMarker("message-handler", re.compile(r"\b(?:addMessageHandler|removeMessageHandler|setMessageHandler)\b"), "Use addLogHandler/removeLogHandler; handlers are per-core."),
    ManualMarker("create-core", word("createCore"), "API4 createCore takes creation flags, not thread count."),
    ManualMarker("helper-cpp-aligned-malloc", word("vs_aligned_malloc"), "In C++, use vsh::vsh_aligned_malloc; review manually in headers."),
    ManualMarker("helper-cpp-aligned-free", word("vs_aligned_free"), "In C++, use vsh::vsh_aligned_free; review manually in headers."),
    ManualMarker("helper-is-constant-format", word("isConstantFormat"), "Use vsh_isConstantVideoFormat in C or vsh::isConstantVideoFormat in C++."),
    ManualMarker("helper-is-same-format", word("isSameFormat"), "Choose vsh_isSameVideoInfo or vsh_isSameVideoFormat based on the arguments."),
    ManualMarker("helper-normalize-rational", word("vs_normalizeRational"), "Use vsh_reduceRational in C or vsh::reduceRational in C++."),
    ManualMarker("helper-add-rational", word("vs_addRational"), "Use vsh_addRational in C or vsh::addRational in C++."),
    ManualMarker("helper-int64-to-int", unqualified_word("int64ToIntS"), "Use vsh_int64ToIntS in C or vsh::int64ToIntS in C++."),
    ManualMarker("helper-bitblt", word("vs_bitblt"), "Use vsh_bitblt in C or vsh::bitblt in C++; update stride types to ptrdiff_t."),
    ManualMarker("helper-valid-dimensions", unqualified_word("areValidDimensions"), "Use vsh_areValidDimensions in C or vsh::areValidDimensions in C++."),
]

CPP_SUFFIXES = {".cc", ".cpp", ".cxx", ".c++", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}


def replacements_for_path(path: Path) -> list[Replacement]:
    replacements = list(COMMON_REPLACEMENTS)
    suffix = path.suffix.lower()
    if suffix == ".c":
        replacements.extend(C_HELPER_REPLACEMENTS)
    elif suffix in CPP_SUFFIXES:
        replacements.extend(CPP_HELPER_REPLACEMENTS)
    return replacements


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


def read_text(path: Path) -> tuple[str, str] | None:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return handle.read(), encoding
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def apply_replacements(text: str, replacements: list[Replacement]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for replacement in replacements:
        text, count = replacement.pattern.subn(replacement.replacement, text)
        if count:
            counts[replacement.name] = counts.get(replacement.name, 0) + count
    return text, counts


def find_manual_markers(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for marker in MANUAL_MARKERS:
        count = len(marker.pattern.findall(text))
        if count:
            counts[marker.name] = count
    return counts


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def print_diff(path: Path, old: str, new: str, root: Path) -> None:
    rel = display_path(path, root)
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    for line in difflib.unified_diff(old_lines, new_lines, fromfile=f"{rel} (old)", tofile=f"{rel} (new)", n=3):
        print(line, end="")
    if old_lines and (not old_lines[-1].endswith(("\n", "\r"))):
        print()


def make_backup(path: Path) -> Path:
    backup = path.with_name(path.name + ".api3bak")
    index = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.api3bak{index}")
        index += 1
    backup.write_bytes(path.read_bytes())
    return backup


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Conservatively rewrite mechanical VapourSynth API3 names to API4 names.")
    parser.add_argument("path", nargs="?", default=".", help="Plugin project root or source/build file to rewrite.")
    parser.add_argument("--write", action="store_true", help="Modify files in place. Default is dry-run.")
    parser.add_argument("--backup", action="store_true", help="When used with --write, create .api3bak backup files.")
    parser.add_argument("--diff", action="store_true", help="Print unified diffs for files that would change.")
    parser.add_argument("--fail-on-changes", action="store_true", help="Exit with code 1 when rewrites are available or manual markers remain.")
    parser.add_argument("--include-external", action="store_true", help="Do not skip directories named external or third_party.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON result. Suppresses unified diff output.")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2

    if args.include_external:
        SKIP_DIRS.discard("external")
        SKIP_DIRS.discard("third_party")

    if root.is_file():
        display_root = root.parent
        paths = [root] if should_scan(root) else []
    else:
        display_root = root
        paths = list(iter_files(root))

    changed_files = 0
    total_replacements: dict[str, int] = {}
    total_manual: dict[str, int] = {}
    backups: list[Path] = []
    file_results: list[dict[str, object]] = []

    for path in paths:
        read_result = read_text(path)
        if read_result is None:
            continue
        original, encoding = read_result
        replacements = replacements_for_path(path)
        rewritten, replacement_counts = apply_replacements(original, replacements)
        manual_counts = find_manual_markers(rewritten)
        for name, count in manual_counts.items():
            total_manual[name] = total_manual.get(name, 0) + count
        backup: Path | None = None
        if replacement_counts:
            changed_files += 1
            for name, count in replacement_counts.items():
                total_replacements[name] = total_replacements.get(name, 0) + count

            if args.diff and not args.json:
                print_diff(path, original, rewritten, display_root)

            if args.write:
                if args.backup:
                    backup = make_backup(path)
                    backups.append(backup)
                with path.open("w", encoding=encoding, newline="") as handle:
                    handle.write(rewritten)

        if replacement_counts or manual_counts:
            file_results.append(
                {
                    "path": display_path(path, display_root).replace("\\", "/"),
                    "changed": bool(replacement_counts),
                    "written": bool(args.write and replacement_counts),
                    "backup": str(backup) if backup else None,
                    "replacements": dict(sorted(replacement_counts.items())),
                    "manual_markers": dict(sorted(manual_counts.items())),
                }
            )

    if args.json:
        result = {
            "path": str(root),
            "mode": "write" if args.write else "dry-run",
            "scanned_files": len(paths),
            "changed_files": changed_files,
            "replacements": dict(sorted(total_replacements.items())),
            "manual_markers": dict(sorted(total_manual.items())),
            "files": file_results,
            "backups": [str(backup) for backup in backups],
            "ok": not (changed_files or total_manual),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.fail_on_changes and (changed_files or total_manual):
            return 1
        return 0

    mode = "write" if args.write else "dry-run"
    print(f"Mode: {mode}")
    print(f"Scanned files: {len(paths)}")
    print(f"Files with mechanical rewrites: {changed_files}")

    if total_replacements:
        print("\nMechanical rewrites:")
        replacement_order = COMMON_REPLACEMENTS + C_HELPER_REPLACEMENTS + CPP_HELPER_REPLACEMENTS
        seen_replacements: set[str] = set()
        for replacement in replacement_order:
            if replacement.name in seen_replacements:
                continue
            seen_replacements.add(replacement.name)
            count = total_replacements.get(replacement.name)
            if count:
                print(f"  {count:4} {replacement.name}: {replacement.note}")

    if total_manual:
        print("\nManual review markers:")
        manual_by_name = {marker.name: marker for marker in MANUAL_MARKERS}
        for name in sorted(total_manual):
            marker = manual_by_name[name]
            print(f"  {total_manual[name]:4} {name}: {marker.note}")

    if backups:
        print("\nBackups:")
        for backup in backups:
            print(f"  {backup}")

    if not args.write and changed_files:
        print("\nDry run only. Re-run with --write to modify files.")

    if args.fail_on_changes and (changed_files or total_manual):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
