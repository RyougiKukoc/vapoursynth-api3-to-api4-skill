# Verification Protocol for API3 to API4 Migrations

Use this reference before calling a migration complete. Compile success is a
necessary gate, but the final question is whether the API4 plugin behaves like
the API3 plugin under equivalent inputs.

The durable validation sequence is: build/load the original API3 baseline,
build/load the API4 candidate, run paired behavior reports in separate Python
processes, then validate packaging/release artifacts. A successful API4 compile
is only the middle of this sequence, not the end.

## User Intake

When behavior verification is possible, ask the user for these concrete items:

- R73/API3 Python executable path, such as
  `C:\vs-r73\python.exe`.
- R74+ or newer API4 Python executable path, such as
  `C:\vs-r77\python.exe`.
- API3 plugin binary path built from the original source.
- API4 plugin binary path built from the migrated source.
- The build commands used for both binaries, or confirmation that the provided
  binaries were built from the intended revisions.
- If binaries come from GitHub Actions, the workflow name, run URL, commit SHA,
  artifact name, and exact artifact path used for verification.
- A deterministic source set. Prefer generated sources in a case file; use
  real clips only when the filter needs file-specific behavior.
- Representative filter calls: defaults, boundary values, plane selections,
  odd dimensions, variable formats, temporal windows, audio inputs, or any
  special mode the plugin supports.
- Invalid calls that should raise clean errors.

Record these answers in the forward-test doc for the repository. If any item is
missing, say exactly which verification layer is blocked.

Important isolation rule: a plugin loaded with `core.std.LoadPlugin(...)` cannot
be unloaded from that VapourSynth core. Never load the API3 and API4 candidate
plugins in the same Python process. Run one fresh Python process per candidate
plugin and compare the JSON reports after both processes exit.

## Verification Gates

Gate 1: static scan.

```bash
python scripts/scan_api3.py /path/to/plugin --summary-only
python scripts/migration_report.py /path/to/plugin
```

Expected result: no API3 markers in migrated plugin source. Any intentional
compatibility code must be documented.

Gate 2: compile or full build.

```bash
cc_or_cxx -I /path/to/vapoursynth-r77/include -c source.c_or_cpp
```

Prefer the repository's own build command. A single translation-unit compile
against R77 headers is only a minimum API surface check for small plugins.

When the repository already has GitHub Actions, a successful workflow run on the
migrated branch is the preferred full-build gate. Record the run URL, commit
SHA, matrix entry, and downloaded artifact name. Use the downloaded artifact as
the binary for Gate 3 and Gate 4.

Gate 3: explicit load in a clean API4 environment.

```python
import vapoursynth as vs
core = vs.core
core.std.LoadPlugin(r"C:\path\to\migrated-plugin.dll")
print(core.namespace.Filter)
```

Expected result: no load error, no API3 deprecation warning, expected namespace,
and API4 media types such as `vnode` in the signature.

Important: Gate 3 is not behavior verification. A successful explicit load or
single-sided API4 runtime smoke must not be summarized as "the migration works"
unless Gate 4 is also complete or explicitly blocked.

Gate 4: R73/API3 versus R74+/API4 behavior comparison.

This is the real correctness check. Use the same case file in both
environments, render the same frames, and compare JSON reports.

If both plugin binaries and both VapourSynth environments are already present,
run at least one deterministic paired case immediately before close-out. For a
normal filter this minimum paired case should usually be a generated-source
default invocation plus one representative rendered frame. Report the exact
hash and `PlaneStats` outcome explicitly, not just "smoke passed".

Gate 5: packaged artifact and release asset checks, when packaging changed.

Download the exact CI artifact or release asset that users will install. Inspect
the extracted path list and confirm it preserves the intended plugin package
directory, required data files, and runtime DLLs. Run the same API4 explicit
load test from the packaged path. If the package is meant for autoload
installation, also test a clean environment with `VAPOURSYNTH_EXTRA_PLUGIN_PATH`
pointing at the package parent directory or with the package installed under the
environment's `vapoursynth/plugins` directory.

For release automation, a normal branch push may build and pack the zip while
skipping the release-upload step. That is expected when upload is gated on tag
or release events. Verify release upload by checking the workflow condition and,
when a release is created, by downloading the release asset and repeating the
package path inspection.

If the repository is meant to support
`pip install "package-name @ git+https://...git"`, Gate 5 also includes
verifying that install path itself. A direct wheel upload is not enough
evidence for the VCS-install strategy. Test whether the repository build
actually reuses the intended Release asset by default or silently falls back to
local compilation.

Use the package checker for directory or zip layout validation:

```bash
python scripts/check_plugin_package.py artifact.zip \
  --plugin-dll plugin.dll \
  --required support-runtime.dll \
  --require-manifest \
  --require-top-level-dir \
  --forbid-vapoursynth-prefix
```

Repeat `--required` for required data files and support DLLs. A normal
R77-style release zip should usually infer `package_dir=plugin-name`; a zip
rooted at `vapoursynth/plugins/plugin-name` should fail when
`--forbid-vapoursynth-prefix` is used.
Pass `--json` when a wrapper script needs structured `ok`, `errors`, `warnings`,
`files`, and `manifest_plugins` fields.

When VCS install is part of the design, run a real install attempt such as:

```bash
pip install "plugin-name @ git+https://github.com/owner/repo.git"
```

or a local repository equivalent:

```bash
pip install --force-reinstall --no-deps --no-build-isolation .
```

Then report one of:

- package name was confirmed and matches the documented install command
- build log confirmed use of the intended Release asset
- build log showed fallback to local build
- install path is blocked, with the exact reason

## Reusable Runner

Prefer Python scripts for verification setup, report generation, and report
comparison. Shell commands should only launch Python, compilers, or the
repository build tool; avoid PowerShell- or Bash-specific data generation in
the durable workflow.

Create a plugin-specific case file from
`references/compare_case_template.py`. The case file must define:

```python
def make_cases(core, plugin_path):
    return {
        "clips": [
            {"name": "default", "clip": core.namespace.Filter(src), "frames": [0, 1, 2]},
        ],
        "errors": [
            {"name": "invalid", "call": lambda: core.namespace.Filter(src, bad=-1)},
        ],
    }
```

Run the case in both environments:

```bash
C:\vs-r73\python.exe scripts\run_vs_compare_case.py ^
  --case cases\plugin_case.py ^
  --plugin C:\path\to\api3-plugin.dll ^
  --label api3-r73 ^
  --out reports\old.json

C:\vs-r77\python.exe scripts\run_vs_compare_case.py ^
  --case cases\plugin_case.py ^
  --plugin C:\path\to\api4-plugin.dll ^
  --label api4-r77 ^
  --out reports\new.json
```

The runner is intentionally a single-plugin process: it loads at most the one
`--plugin` path, renders reports, and exits. By default it creates the
VapourSynth core with `DISABLE_AUTO_LOADING` before accessing `vs.core`, so the
explicit plugin path is the only plugin-under-test variable. Use
`--allow-autoload` only for a case that intentionally validates installed
autoload behavior.

On Windows, the runner automatically adds the plugin's containing directory to
the DLL search path before loading it. Use repeated `--dll-dir PATH` arguments
when support DLLs live outside the plugin directory.

Compare reports outside the VapourSynth environments:

```bash
python scripts\compare_vs_reports.py reports\old.json reports\new.json
python scripts\compare_vs_reports.py reports\old.json reports\new.json --json
```

Expected result for pure migrations: `Reports match.`
Use `--json` when a wrapper or CI step needs structured `ok`, `diff_count`,
`diffs`, and `omitted_diff_count` fields.

For filters where byte-exact output is not expected but normalized plane
statistics should stay close, run an additional approximate comparison:

```bash
python scripts\compare_vs_reports.py reports\old.json reports\new.json --plane-stats-eps 0.000001
python scripts\compare_vs_reports.py reports\old.json reports\new.json --plane-stats-eps 0.000001 --json
```

This tolerance only applies to `PlaneStats` min/max/average values. Frame
hashes, dimensions, formats, properties, and error behavior still compare
strictly.

## What the Reports Compare

The runner records:

- VapourSynth environment metadata.
- Plugin path and label.
- Clip width, height, frame count, and format.
- Per-frame width, height, format details, SHA-256 hash of all planes, and
  frame properties.
- Per-frame `core.std.PlaneStats` min, max, and average for each plane. These
  are normalized values between 0 and 1 and are useful as a quick approximate
  signal or for tolerance-based checks.
- Error-path result: whether an exception was raised, exception type, and
  message.

The comparer ignores environment metadata and compares rendered behavior
strictly unless `--plane-stats-eps` is explicitly provided.

## Choosing Cases

For each plugin, include at least:

- A default call.
- One call for each optional argument that changes processing.
- Boundary values near min/max validation.
- Plane selection or channel selection if supported.
- Odd dimensions or subsampled formats when the filter pads/crops or touches
  chroma.
- Multiple formats: 8-bit, 10/16-bit integer, float, RGB/YUV/Gray as
  applicable.
- Several frames for temporal filters, including edge frames near 0 and near
  the end.
- Deterministic generated clips whose values change across frames for temporal
  filters. A flat all-zero source may pass load/render checks without exercising
  the filter's temporal decision logic.
- Error cases for invalid ranges, duplicate planes, unsupported formats, and
  missing required dependencies.

Minimum expectation when a quick confirmation is needed:

- One deterministic generated default case must be run in both API3 and API4
  environments when both binaries are available.
- The close-out must say whether frame hashes matched exactly.
- The close-out must also report the paired `PlaneStats` min/max/average result
  or explicitly say that only hash comparison was performed.

Do not compare random noise unless it is generated with a fixed seed and stable
across both environments.

## Interpreting Failures

- Static scan failure: stale API3 names or manual migration points remain.
- Compile failure: wrong headers, stale signatures, missing return type string,
  `VSVideoInfo.format` pointer semantics, changed API call shape, or build
  system still finding old SDK headers.
- Load failure: wrong exported entry point, symbol visibility, install path,
  dependency DLL, namespace, or plugin id.
- Hash mismatch with matching PlaneStats: the output is not byte-identical, but
  broad normalized min/max/average are close. Inspect rounding, dithering, SIMD
  order, and frame properties before accepting it.
- Hash mismatch with PlaneStats mismatch: algorithm, requested frames, format
  negotiation, padding/cropping, metadata handling, rounding, integer scaling,
  or SIMD path changed.
- Property mismatch: frame property copying or reserved property behavior
  changed.
- Error mismatch: validation, exception conversion, `mapSetError`, or reference
  ownership changed.

When a difference is intentional, record it in the forward-test doc with the
exact case name and reason. Do not silently accept differences just because an
upstream API4 release also differs; upstream releases may combine API migration
with independent bug fixes, optimizations, C++ modernization, or packaging.

## Packaging Is Separate

PyPI wheels, Meson install paths, GitHub Actions, and autoload layouts are
separate from API correctness. Validate the API4 plugin behavior first, then
test packaging by installing into a clean environment and running the same
explicit load and behavior comparison reports against the installed artifact.

For the newer Release-backed VCS-install pattern, treat the `pyproject.toml`
and build-hook behavior as part of packaging verification, not as proof of API
correctness.

When using R77-style plugin folders, keep support DLLs beside the plugin binary
and add a `manifest.vs` so the loader intentionally loads only plugin DLLs from
that folder. Do not infer correctness from a green upload step alone; inspect
the artifact/release zip layout and load from the extracted package.
