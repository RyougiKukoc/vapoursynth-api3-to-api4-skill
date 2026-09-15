#!/usr/bin/env python3
"""Summarize VapourSynth API3-to-API4 migration work for a plugin tree.

This script is read-only. It reuses scan_api3.py rules and turns raw markers
into a project-level migration plan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import scan_api3


SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx"}
HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp"}
BUILD_FILENAMES = {"CMakeLists.txt", "meson.build", "Makefile", "makefile", "GNUmakefile", "configure.ac"}
BUILD_EXTENSIONS = {".cmake", ".meson", ".build", ".props", ".targets", ".vcxproj", ".filters"}
AUXILIARY_FILENAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "meson_options.txt",
    "README.md",
    "README.rst",
}
AUXILIARY_EXTENSIONS = {".yml", ".yaml", ".toml"}


@dataclass(frozen=True)
class Hit:
    severity: str
    rel: Path
    lineno: int
    rule: str
    line: str
    hint: str


@dataclass(frozen=True)
class Stage:
    name: str
    rules: frozenset[str]
    action: str


@dataclass(frozen=True)
class RiskGate:
    name: str
    level: str
    reason: str
    action: str


STAGES = [
    Stage(
        "Mechanical surface",
        frozenset(
            {
                "api3-header",
                "api3-helper",
                "api3-frame-ref",
                "api3-node-ref",
                "api3-func-ref",
                "api3-format",
                "api3-prop-api",
                "api3-map-error",
                "api3-clone-ref",
                "api3-function-object",
                "api3-frame-props",
                "api3-frame-format",
                "api3-append-mode",
                "api3-color-family",
                "api3-helper-functions",
                "api3-helper-alloc",
                "api3-arg-string",
            }
        ),
        "Run rewrite_api3_mechanical.py in dry-run mode, then apply the safe changes.",
    ),
    Stage(
        "Entry point and registration",
        frozenset({"api3-entry-point", "api3-config-callback", "api3-register-callback", "api3-arg-string"}),
        "Convert to VapourSynthPluginInit2, VSPLUGINAPI, explicit return types, and vnode/vframe signatures.",
    ),
    Stage(
        "Filter lifecycle",
        frozenset({"api3-filter-init", "api3-instance-data-indirection", "api3-create-filter", "api3-activation"}),
        "Move init work into create, use void *instanceData, and createVideoFilter/createAudioFilter with dependencies.",
    ),
    Stage(
        "Format and media semantics",
        frozenset(
            {
                "api3-format",
                "api3-video-info-format-pointer",
                "api3-video-info-format-null-check",
                "api3-format-registry",
                "api3-color-family",
                "api3-compatible-format",
                "range-property",
            }
        ),
        "Review value-style VSVideoInfo.format, format IDs, color/range properties, and compat formats.",
    ),
    Stage(
        "Host/core/logging",
        frozenset({"api3-create-core", "api3-log-handler"}),
        "Review host-application APIs: createCore flags and per-core log handlers.",
    ),
]

ADVANCED_RULES = {
    "api3-activation",
    "api3-compatible-format",
    "range-property",
    "api3-create-core",
    "api3-format-registry",
}

MANUAL_LINE_PATTERNS = {
    "propSetData": re.compile(r"\bpropSetData\s*\("),
    "paTouch": re.compile(r"\bpaTouch\b"),
    "cache flags": re.compile(r"\bnf(?:MakeLinear|NoCache|IsCache)\b|\bcacheFrame\s*\("),
    "message handlers": re.compile(r"\b(?:VSMessageHandler|setMessageHandler|addMessageHandler|removeMessageHandler)\b"),
    "range property": re.compile(r"_ColorRange"),
    "compat formats": re.compile(r"\b(?:cmCompat|pfCompat[A-Za-z0-9_]*)\b"),
}


def should_scan(path: Path) -> bool:
    return scan_api3.should_scan(path)


def iter_files(root: Path):
    return scan_api3.iter_files(root)


def collect_paths(root: Path, include_external: bool) -> tuple[Path, list[Path]]:
    if include_external:
        scan_api3.SKIP_DIRS.discard("external")
        scan_api3.SKIP_DIRS.discard("third_party")

    if root.is_file():
        display_root = root.parent
        paths = [root] if should_scan(root) else []
    else:
        display_root = root
        paths = list(iter_files(root))
    return display_root, paths


def collect_auxiliary_paths(root: Path) -> list[Path]:
    if root.is_file():
        return []

    paths: list[Path] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not scan_api3.should_skip_dir(d)]
        current = Path(current_root)
        in_workflow_dir = current.match("**/.github/workflows") or current.as_posix().endswith("/.github/workflows")
        for filename in files:
            path = current / filename
            if in_workflow_dir and path.suffix in {".yml", ".yaml"}:
                paths.append(path)
            elif path.name in AUXILIARY_FILENAMES or path.suffix in AUXILIARY_EXTENSIONS:
                paths.append(path)
    return sorted(set(paths))


def collect_hits(paths: list[Path], display_root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for path in paths:
        for raw in scan_api3.scan_file(path, display_root):
            hits.append(Hit(*raw))
    hits.sort(key=lambda h: (scan_api3.severity_key(h.severity), str(h.rel).lower(), h.lineno, h.rule))
    return hits


def file_kind(path: Path) -> str:
    if path.name in BUILD_FILENAMES or path.suffix in BUILD_EXTENSIONS:
        return "build"
    if path.suffix in SOURCE_EXTENSIONS:
        return "source"
    if path.suffix in HEADER_EXTENSIONS:
        return "header"
    return "other"


def detect_build_system(paths: list[Path]) -> list[str]:
    names = {path.name for path in paths}
    suffixes = {path.suffix for path in paths}
    systems: list[str] = []
    if "meson.build" in names:
        systems.append("Meson")
    if "CMakeLists.txt" in names or ".cmake" in suffixes:
        systems.append("CMake")
    if {"Makefile", "makefile", "GNUmakefile"} & names:
        systems.append("Make")
    if ".vcxproj" in suffixes:
        systems.append("Visual Studio")
    if "configure.ac" in names:
        systems.append("Autotools")
    return systems


def read_project_text(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            try:
                chunks.append(path.read_text(encoding="utf-8-sig"))
            except UnicodeDecodeError:
                continue
        except OSError:
            continue
    return "\n".join(chunks)


def contains_node_input(text: str) -> bool:
    return bool(re.search(r':(?:clip|vnode)(?:\[\])?[:;]|\bpropGetNode\s*\(|\bmapGetNode\s*\(', text))


def detect_plugin_shape(hits: list[Hit], project_text: str) -> list[str]:
    joined = "\n".join(hit.line for hit in hits) + "\n" + project_text
    shape: list[str] = []
    if re.search(r"\b(?:anode|aframe|VSAudio|createAudioFilter)\b", joined):
        shape.append("audio-aware")
    if re.search(r':(?:clip|vnode)(?:\[\])?[:;]|\b(?:VSNodeRef|VSNode)\b|propGetNode|mapGetNode', joined):
        shape.append("video node input")
    if re.search(r"\bcreateFilter\s*\(|\bcreateVideoFilter\s*\(", joined) and not contains_node_input(joined):
        shape.append("possible source filter")
    if has_temporal_request_pattern(joined):
        shape.append("temporal/multi-frame access")
    if re.search(r"\barFrameReady\b|\bqueryCompletedFrame\s*\(", joined):
        shape.append("custom/old async request flow")
    if re.search(r"\bnf(?:MakeLinear|NoCache|IsCache)\b|\bcacheFrame\s*\(", joined):
        shape.append("custom cache behavior")
    return shape or ["unknown from API3 markers"]


def detect_risk_gates(paths: list[Path], hits: list[Hit], project_text: str) -> list[RiskGate]:
    joined = "\n".join(hit.line for hit in hits) + "\n" + project_text
    rules = {hit.rule for hit in hits}
    gates: list[RiskGate] = []

    def add(name: str, level: str, reason: str, action: str) -> None:
        if not any(gate.name == name for gate in gates):
            gates.append(RiskGate(name, level, reason, action))

    if re.search(r"\bcreateFilter\s*\(|\bcreateVideoFilter\s*\(", joined) and not contains_node_input(joined):
        add(
            "source-filter-design",
            "high",
            "filter creation is present but no obvious input clip argument was found",
            "Treat this as a possible source filter; review dependencies, source lifetime, and createVideoFilter/createVideoFilter2 output publication.",
        )

    if re.search(
        r"\bgetOutputIndex\s*\(|\bVSVideoInfo\s+[A-Za-z_][A-Za-z0-9_]*\s*\[|_Alpha\b|AV_PIX_FMT_FLAG_ALPHA|background_frame\s*\[\s*1\s*\]",
        joined,
    ):
        add(
            "multi-output-or-alpha",
            "high",
            "multi-output or alpha-side-output markers were found",
            "Do an API design review; API4 often wants explicit returned nodes or an _Alpha frame property instead of API3 output indexes.",
        )

    if has_temporal_request_pattern(joined):
        add(
            "temporal-requests",
            "high",
            "the filter appears to request frames other than the current output index",
            "Use a conservative VSFilterDependency request pattern such as rpGeneral and verify with multi-frame generated cases.",
        )

    if "api3-activation" in rules or re.search(r"\barFrameReady\b|\bqueryCompletedFrame\s*\(", joined):
        add(
            "old-async-activation",
            "high",
            "API3 arFrameReady/queryCompletedFrame flow is present",
            "Redesign around API4 arInitial/arAllFramesReady and normal requestFrameFilter/getFrameFilter flow.",
        )

    if re.search(r"\bnf(?:MakeLinear|NoCache|IsCache)\b|\bcacheFrame\s*\(", joined):
        add(
            "cache-or-linear-filter",
            "medium",
            "old cache flags or explicit cacheFrame calls were found",
            "Review cache behavior manually; convert nfMakeLinear to setLinearFilter only when linear source behavior is intended.",
        )

    if "range-property" in rules or "_ColorRange" in joined:
        add(
            "range-property-semantics",
            "medium",
            "_ColorRange markers were found",
            "Review manually; API4.2 _Range uses inverted full/limited values compared with old _ColorRange.",
        )

    if rules & {"api3-format-registry", "api3-compatible-format"}:
        add(
            "format-registry",
            "medium",
            "format registry or compat packed-format markers were found",
            "Review format IDs and reject or redesign packed compat formats; do not migrate these mechanically.",
        )

    if re.search(r"\b(?:OpenCL|CUDA|Vulkan|boost::compute|clCreate|clGet|cu[A-Z][A-Za-z0-9_]*)\b", joined):
        add(
            "accelerator-runtime",
            "medium",
            "GPU/accelerator runtime markers were found",
            "Build validation must include dependency DLL packaging and at least one real frame execution on a host with the runtime available.",
        )

    if re.search(r"\b(?:libav|ffmpeg|avformat|avcodec|AVFrame|AVPacket|L-SMASH|lsmash)\b", joined, re.IGNORECASE):
        add(
            "external-media-runtime",
            "medium",
            "external media library markers were found",
            "Prefer the existing CI/dependency workflow and verify behavior with deterministic real media, not only generated clips.",
        )

    workflow_paths = [path for path in paths if ".github" in path.parts and path.suffix in {".yml", ".yaml"}]
    if workflow_paths or re.search(r"\b(?:actions/upload-artifact|gh release|release upload|cibuildwheel|meson-python)\b", joined):
        add(
            "ci-or-packaging",
            "medium",
            "CI or packaging metadata was found",
            "Inspect existing workflows before inventing a build; use their artifacts for load and behavior verification.",
        )

    return gates


def estimate_complexity(hits: list[Hit], source_files_with_hits: int) -> tuple[str, list[str]]:
    if not hits:
        return "none", ["No API3 markers were found by the scanner."]

    rules = {hit.rule for hit in hits}
    severities = Counter(hit.severity for hit in hits)
    advanced = rules & ADVANCED_RULES
    lifecycle = rules & {"api3-filter-init", "api3-instance-data-indirection", "api3-create-filter", "api3-activation"}
    entry = rules & {"api3-entry-point", "api3-config-callback", "api3-register-callback"}
    manual_line_hits = manual_line_hits_by_name(hits)

    score = severities["high"] * 3 + severities["medium"] * 2 + severities["manual"] * 5
    if source_files_with_hits > 4:
        score += 8
    if advanced:
        score += 10
    if manual_line_hits:
        score += 5

    reasons: list[str] = []
    if entry:
        reasons.append("plugin entry/registration must be rewritten")
    if lifecycle:
        reasons.append("filter lifecycle must be migrated")
    if advanced:
        reasons.append("advanced/manual hazards present: " + ", ".join(sorted(advanced)))
    if manual_line_hits:
        reasons.append("manual line patterns present: " + ", ".join(sorted(manual_line_hits)))
    if source_files_with_hits > 4:
        reasons.append(f"API3 markers span {source_files_with_hits} source files")

    if score >= 45:
        return "high", reasons
    if score >= 18:
        return "medium", reasons
    return "low", reasons or ["mostly mechanical API3 surface markers"]


def manual_line_hits_by_name(hits: list[Hit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        for name, pattern in MANUAL_LINE_PATTERNS.items():
            if pattern.search(hit.line):
                counts[name] = counts.get(name, 0) + 1
    return counts


def has_temporal_request_pattern(text: str) -> bool:
    if re.search(r"requestFrameFilter\s*\(\s*(?:n\s*[-+]|[^,\n]*[-+]\s*n\b)", text):
        return True
    return bool(
        re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*n\s*[-+]", text)
        and re.search(r"requestFrameFilter\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*,", text)
    )


def recommended_steps(hits: list[Hit], project_text: str, risk_gates: list[RiskGate]) -> list[str]:
    if not hits:
        steps = [
            "If this is expected to be an API3 plugin, broaden the scan to source/build files that may be generated or vendored.",
            "Otherwise treat the project as already API4-shaped and build it against the target VapourSynth SDK.",
        ]
        steps.extend(risk_followup_steps(risk_gates))
        return steps

    rules = {hit.rule for hit in hits}
    steps: list[str] = []
    mechanical_rules = STAGES[0].rules
    if rules & mechanical_rules:
        steps.append("Run rewrite_api3_mechanical.py --diff, review the patch, then apply the safe mechanical rewrites.")
    if rules & {"api3-entry-point", "api3-config-callback", "api3-register-callback", "api3-arg-string"}:
        steps.append("Convert VapourSynthPluginInit to VapourSynthPluginInit2 and add API4 config/register return type strings.")
    if rules & {"api3-filter-init", "api3-create-filter", "api3-instance-data-indirection", "api3-activation"}:
        steps.append("Refactor filter creation: inline VSFilterInit work, fix getFrame instanceData, and add VSFilterDependency.")
        if has_temporal_request_pattern(project_text):
            steps.append("Use rpGeneral rather than rpStrictSpatial for temporal filters that request neighboring frames.")
    if rules & {"api3-video-info-format-pointer", "api3-video-info-format-null-check", "api3-format", "api3-format-registry"}:
        steps.append("Update VSVideoInfo.format value semantics and any format registry calls before compiling.")
    manual_lines = manual_line_hits_by_name(hits)
    if "propSetData" in manual_lines:
        steps.append("Convert propSetData by choosing dtUtf8, dtBinary, or dtUnknown explicitly.")
    if rules & {"api3-activation"}:
        steps.append("Redesign arFrameReady/queryCompletedFrame users around API4 request/consume activation phases.")
    if rules & {"range-property"} or "range property" in manual_lines:
        steps.append("Review _ColorRange manually; do not rename to _Range without flipping full/limited values.")
    steps.extend(risk_followup_steps(risk_gates))
    steps.append("Build against the target R74+ API4 headers and rerun scan_api3.py until no API3 markers remain.")
    return steps


def risk_followup_steps(risk_gates: list[RiskGate]) -> list[str]:
    risk_names = {gate.name for gate in risk_gates}
    steps: list[str] = []
    if "temporal-requests" in risk_names:
        steps.append("Verify temporal behavior with deterministic multi-frame cases, including edge frames near the start and end.")
    if "accelerator-runtime" in risk_names:
        steps.append("Add a runtime smoke case that actually renders a frame on the GPU/accelerator path and package required support DLLs.")
    if "external-media-runtime" in risk_names:
        steps.append("Use deterministic real media samples for behavior verification because generated clips may not exercise source-reader paths.")
    if "ci-or-packaging" in risk_names:
        steps.append("Reuse the existing CI workflow for the full build and validate downloaded artifacts with check_plugin_package.py when packaging changes.")
    if "multi-output-or-alpha" in risk_names:
        steps.append("Write down the API4 output contract before editing multi-output or alpha-producing source filters.")
    return steps


def hit_to_dict(hit: Hit) -> dict[str, object]:
    return {
        "severity": hit.severity,
        "path": hit.rel.as_posix(),
        "line": hit.lineno,
        "rule": hit.rule,
        "text": hit.line,
        "hint": hit.hint,
    }


def build_report_data(root: Path, paths: list[Path], report_paths: list[Path], hits: list[Hit], top: int) -> dict[str, object]:
    project_text = read_project_text(report_paths)
    files_with_hits = {hit.rel for hit in hits}
    source_files_with_hits = sum(1 for path in files_with_hits if file_kind(path) == "source")
    severity_counts = Counter(hit.severity for hit in hits)
    rule_counts = Counter(hit.rule for hit in hits)
    kind_counts = Counter(file_kind(path) for path in paths)
    build_systems = detect_build_system(report_paths)
    complexity, reasons = estimate_complexity(hits, source_files_with_hits)
    risk_gates = detect_risk_gates(report_paths, hits, project_text)

    stage_rows: list[dict[str, object]] = []
    for stage in STAGES:
        stage_hits = sum(count for rule, count in rule_counts.items() if rule in stage.rules)
        if stage_hits:
            stage_rows.append({"name": stage.name, "markers": stage_hits, "action": stage.action})

    manual_lines = manual_line_hits_by_name(hits)
    manual_rows: list[dict[str, object]] = []
    for name, count in sorted(manual_lines.items()):
        manual_rows.append({"name": name, "markers": count, "hint": ""})
    for rule, count in sorted(rule_counts.items()):
        if any(hit.rule == rule and hit.severity == "manual" for hit in hits):
            hint = next(hit.hint for hit in hits if hit.rule == rule)
            manual_rows.append({"name": rule, "markers": count, "hint": hint})

    by_file: dict[Path, list[Hit]] = defaultdict(list)
    for hit in hits:
        by_file[hit.rel].append(hit)
    hot_files: list[dict[str, object]] = []
    for rel, file_hits in sorted(by_file.items(), key=lambda item: (-len(item[1]), str(item[0]).lower()))[:top]:
        severities = Counter(hit.severity for hit in file_hits)
        hot_files.append(
            {
                "path": rel.as_posix(),
                "markers": len(file_hits),
                "severity": {key: severities[key] for key in sorted(severities) if severities[key]},
            }
        )

    top_rules: list[dict[str, object]] = []
    for rule, count in rule_counts.most_common(10):
        hint = next(hit.hint for hit in hits if hit.rule == rule)
        severity = next(hit.severity for hit in hits if hit.rule == rule)
        top_rules.append({"rule": rule, "markers": count, "severity": severity, "hint": hint})

    return {
        "target": str(root),
        "scanned_files": len(paths),
        "files_with_api3_markers": len(files_with_hits),
        "total_markers": len(hits),
        "complexity": complexity,
        "build_systems": build_systems,
        "file_mix": {key: kind_counts[key] for key in sorted(kind_counts) if kind_counts[key]},
        "likely_shape": detect_plugin_shape(hits, project_text),
        "risk_gates": [
            {"name": gate.name, "level": gate.level, "reason": gate.reason, "action": gate.action}
            for gate in risk_gates
        ],
        "complexity_reasons": reasons,
        "severity": {severity: severity_counts[severity] for severity in ("high", "medium", "manual") if severity_counts[severity]},
        "migration_stages": stage_rows,
        "manual_review_gates": manual_rows,
        "hot_files": hot_files,
        "top_rules": top_rules,
        "recommended_next_steps": recommended_steps(hits, project_text, risk_gates),
        "hits": [hit_to_dict(hit) for hit in hits],
    }


def print_report(root: Path, paths: list[Path], report_paths: list[Path], hits: list[Hit], top: int) -> None:
    data = build_report_data(root, paths, report_paths, hits, top)

    print("# VapourSynth API3 to API4 Migration Report")
    print()
    print(f"Target: {root}")
    print(f"Scanned files: {data['scanned_files']}")
    print(f"Files with API3 markers: {data['files_with_api3_markers']}")
    print(f"Total markers: {data['total_markers']}")
    print(f"Complexity: {data['complexity']}")
    build_systems = data["build_systems"]
    print(f"Build systems: {', '.join(build_systems) if build_systems else 'not detected'}")
    print(f"File mix: {format_mapping(data['file_mix'])}")
    print(f"Likely shape: {', '.join(data['likely_shape'])}")

    print()
    print("## Risk Gates")
    if data["risk_gates"]:
        for gate in data["risk_gates"]:
            print(f"- {gate['level']} {gate['name']}: {gate['reason']}")
            print(f"  action: {gate['action']}")
    else:
        print("- none detected")

    if data["complexity_reasons"]:
        print()
        print("## Complexity Reasons")
        for reason in data["complexity_reasons"]:
            print(f"- {reason}")

    print()
    print("## Severity")
    if data["severity"]:
        for severity in ("high", "medium", "manual"):
            count = data["severity"].get(severity)
            if count:
                print(f"- {severity}: {count}")
    else:
        print("- none")

    print()
    print("## Migration Stages")
    if data["migration_stages"]:
        for stage in data["migration_stages"]:
            print(f"- {stage['name']}: {stage['markers']} marker(s). {stage['action']}")
    else:
        print("- No API3 migration stages were detected.")

    if data["manual_review_gates"]:
        print()
        print("## Manual Review Gates")
        for gate in data["manual_review_gates"]:
            if gate["hint"]:
                print(f"- {gate['name']}: {gate['markers']} marker(s). {gate['hint']}")
            else:
                print(f"- {gate['name']}: {gate['markers']} occurrence(s)")

    if hits:
        print()
        print("## Hot Files")
        for hot_file in data["hot_files"]:
            print(f"- {hot_file['path']}: {hot_file['markers']} marker(s), {format_mapping(hot_file['severity'])}")

        print()
        print("## Top Rules")
        for rule in data["top_rules"]:
            print(f"- {rule['rule']}: {rule['markers']}. {rule['hint']}")

    print()
    print("## Recommended Next Steps")
    for index, step in enumerate(data["recommended_next_steps"], 1):
        print(f"{index}. {step}")


def format_counter(counter: Counter[str]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter) if counter[key])


def format_mapping(mapping: dict[str, object]) -> str:
    if not mapping:
        return "none"
    return ", ".join(f"{key}={mapping[key]}" for key in sorted(mapping) if mapping[key])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a project-level VapourSynth API3-to-API4 migration report.")
    parser.add_argument("path", nargs="?", default=".", help="Plugin project root or source/build file to report on.")
    parser.add_argument("--top", type=int, default=8, help="Number of hot files to show.")
    parser.add_argument("--fail-on-hits", action="store_true", help="Exit with code 1 when API3 markers are found.")
    parser.add_argument("--include-external", action="store_true", help="Do not skip directories named external or third_party.")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report.")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2

    display_root, paths = collect_paths(root, args.include_external)
    auxiliary_paths = collect_auxiliary_paths(root)
    report_paths = sorted(set(paths) | set(auxiliary_paths))
    hits = collect_hits(paths, display_root)
    if args.json:
        print(json.dumps(build_report_data(root, paths, report_paths, hits, max(1, args.top)), indent=2, sort_keys=True))
    else:
        print_report(root, paths, report_paths, hits, max(1, args.top))
    return 1 if hits and args.fail_on_hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
