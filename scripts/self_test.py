#!/usr/bin/env python3
"""Run lightweight regression tests for the VapourSynth API3-to-API4 skill scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def run(script: str, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT_DIR / script), *args]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"{' '.join(cmd)} failed with {result.returncode}\n{result.stdout}")
    return result


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def make_api3_fixture(root: Path) -> Path:
    project = root / "api3-project"
    write_text(
        project / "src" / "filter.c",
        r'''
        #include "VapourSynth.h"
        #include "VSHelper.h"

        typedef struct {
            VSNodeRef *node;
            int radius;
        } FilterData;

        static const VSFrameRef *VS_CC filterGetFrame(int n, int activationReason, void **instanceData,
                                                      void **frameData, VSFrameContext *frameCtx,
                                                      VSCore *core, const VSAPI *vsapi) {
            FilterData *d = (FilterData *)*instanceData;
            const char *runtime = "OpenCL";
            (void)runtime;
            if (activationReason == arInitial)
                vsapi->requestFrameFilter(n - d->radius, d->node, frameCtx);
            else if (activationReason == arFrameReady)
                vsapi->queryCompletedFrame(NULL, frameCtx);
            return NULL;
        }

        static void filterCreate(const VSMap *in, VSMap *out, void *userData,
                                 VSCore *core, const VSAPI *vsapi) {
            VSNodeRef *node = vsapi->propGetNode(in, "clip", 0, NULL);
            (void)node;
            vsapi->propSetData(out, "note", "x", -1, paReplace);
            vsapi->createFilter(in, out, "Filter", NULL, filterGetFrame, NULL,
                                fmParallel, nfMakeLinear, NULL, core);
        }

        VS_EXTERNAL_API(void) VapourSynthPluginInit(VSConfigPlugin configFunc,
                                                    VSRegisterFunction registerFunc,
                                                    VSPlugin *plugin) {
            configFunc("com.example.filter", "example", "Example", VAPOURSYNTH_API_VERSION, 1, plugin);
            registerFunc("Filter", "clip:clip;", filterCreate, NULL, plugin);
        }
        ''',
    )
    write_text(
        project / "build-api3-r73" / "old.c",
        r'''
        #include "VapourSynth.h"
        VSFrameRef *stale_build_output;
        ''',
    )
    write_text(
        project / ".venv-test" / "generated.c",
        r'''
        #include "VapourSynth.h"
        VSNodeRef *generated_node;
        ''',
    )
    write_text(
        project / ".github" / "workflows" / "build.yml",
        r'''
        name: build
        on: [push]
        jobs:
          build:
            runs-on: windows-latest
            steps:
              - uses: actions/upload-artifact@v7
        ''',
    )
    write_text(
        project / "meson.build",
        r'''
        project('example', 'c')
        dependency('vapoursynth')
        ''',
    )
    return project


def test_scan_report_and_rewrite(root: Path) -> None:
    project = make_api3_fixture(root)

    scan = run("scan_api3.py", str(project))
    assert "Hits:" in scan.stdout
    assert "src\\filter.c" in scan.stdout or "src/filter.c" in scan.stdout
    assert "build-api3-r73" not in scan.stdout
    assert ".venv-test" not in scan.stdout

    scan_json = json.loads(run("scan_api3.py", str(project), "--json").stdout)
    assert scan_json["hits"] > 0
    assert scan_json["scanned_files"] >= 2
    assert any(hit["rule"] == "api3-header" for hit in scan_json["locations"])
    assert not any("build-api3-r73" in hit["path"] for hit in scan_json["locations"])
    assert not any(".venv-test" in hit["path"] for hit in scan_json["locations"])

    report = run("migration_report.py", str(project), "--top", "2")
    for expected in [
        "## Risk Gates",
        "temporal-requests",
        "old-async-activation",
        "cache-or-linear-filter",
        "accelerator-runtime",
        "ci-or-packaging",
    ]:
        assert expected in report.stdout, report.stdout
    assert "build-api3-r73" not in report.stdout

    report_json = json.loads(run("migration_report.py", str(project), "--top", "2", "--json").stdout)
    assert report_json["total_markers"] > 0
    assert report_json["build_systems"] == ["Meson"]
    risk_names = {gate["name"] for gate in report_json["risk_gates"]}
    for expected in {"temporal-requests", "old-async-activation", "cache-or-linear-filter", "accelerator-runtime", "ci-or-packaging"}:
        assert expected in risk_names, report_json
    assert not any("build-api3-r73" in hit["path"] for hit in report_json["hits"])

    rewrite = run("rewrite_api3_mechanical.py", str(project), "--diff")
    for expected in ["VapourSynth4.h", "VSFrame", "mapGetNode", "propSetData"]:
        assert expected in rewrite.stdout, rewrite.stdout
    assert "build-api3-r73" not in rewrite.stdout
    assert ".venv-test" not in rewrite.stdout

    rewrite_json = json.loads(run("rewrite_api3_mechanical.py", str(project), "--json").stdout)
    assert rewrite_json["mode"] == "dry-run"
    assert rewrite_json["changed_files"] == 1
    assert "header-vapoursynth" in rewrite_json["replacements"]
    assert "propSetData" in rewrite_json["manual_markers"]
    assert not any("build-api3-r73" in row["path"] for row in rewrite_json["files"])
    assert not any(".venv-test" in row["path"] for row in rewrite_json["files"])


def manifest() -> str:
    return "[VapourSynth Manifest V1]\n\nexample\n"


def make_package_zip(path: Path, prefix: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{prefix}/manifest.vs", manifest())
        zf.writestr(f"{prefix}/example.dll", "plugin")
        zf.writestr(f"{prefix}/support.dll", "runtime")


def test_package_checker(root: Path) -> None:
    good = root / "good.zip"
    bad = root / "bad.zip"
    make_package_zip(good, "./example")
    make_package_zip(bad, "vapoursynth/plugins/example")

    common = [
        "--plugin-dll",
        "example.dll",
        "--required",
        "support.dll",
        "--require-manifest",
        "--require-top-level-dir",
        "--forbid-vapoursynth-prefix",
    ]
    good_result = run("check_plugin_package.py", str(good), *common)
    assert "package_dir=example" in good_result.stdout

    good_json = json.loads(run("check_plugin_package.py", str(good), *common, "--json").stdout)
    assert good_json["ok"] is True
    assert good_json["package_dir"] == "example"
    assert good_json["manifest_plugins"] == ["example"]

    bad_result = run("check_plugin_package.py", str(bad), *common, check=False)
    assert bad_result.returncode == 1
    assert "redundant VapourSynth install prefix" in bad_result.stdout

    bad_json_result = run("check_plugin_package.py", str(bad), *common, "--json", check=False)
    assert bad_json_result.returncode == 1
    bad_json = json.loads(bad_json_result.stdout)
    assert bad_json["ok"] is False
    assert bad_json["package_dir"] == "vapoursynth/plugins/example"
    assert any("redundant VapourSynth install prefix" in error for error in bad_json["errors"])


def write_report(path: Path, average: float, label: str) -> None:
    report = {
        "label": label,
        "plugin": f"{label}.dll",
        "vapoursynth_version": "ignored",
        "clips": [
            {
                "name": "case",
                "frames": [
                    {
                        "n": 0,
                        "sha256": "abc",
                        "plane_stats": [{"plane": 0, "min": 0.0, "max": 1.0, "average": average}],
                    }
                ],
            }
        ],
        "errors": [],
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def test_report_compare(root: Path) -> None:
    old = root / "old.json"
    new = root / "new.json"
    write_report(old, 0.5, "api3")
    write_report(new, 0.5000001, "api4")

    strict = run("compare_vs_reports.py", str(old), str(new), check=False)
    assert strict.returncode == 1
    assert "Reports differ" in strict.stdout

    strict_json_result = run("compare_vs_reports.py", str(old), str(new), "--json", check=False)
    assert strict_json_result.returncode == 1
    strict_json = json.loads(strict_json_result.stdout)
    assert strict_json["ok"] is False
    assert strict_json["diff_count"] == 1
    assert strict_json["omitted_diff_count"] == 0

    tolerant = run("compare_vs_reports.py", str(old), str(new), "--plane-stats-eps", "0.000001")
    assert "Reports match." in tolerant.stdout

    tolerant_json = json.loads(
        run("compare_vs_reports.py", str(old), str(new), "--plane-stats-eps", "0.000001", "--json").stdout
    )
    assert tolerant_json["ok"] is True
    assert tolerant_json["diff_count"] == 0


def test_compare_runner_help() -> None:
    help_result = run("run_vs_compare_case.py", "--help")
    assert "--case-id" in help_result.stdout
    assert "--arrays-out" in help_result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vpy-api4-self-test-") as temp:
        root = Path(temp)
        test_scan_report_and_rewrite(root)
        test_package_checker(root)
        test_report_compare(root)
        test_compare_runner_help()
    print("self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
