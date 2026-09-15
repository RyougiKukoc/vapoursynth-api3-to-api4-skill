---
name: vapoursynth-api3-to-api4
description: Convert legacy VapourSynth API3 C/C++ plugin projects to the API4 plugin interface. Use when working on VapourSynth plugins that include VapourSynth.h/VSHelper.h, export VapourSynthPluginInit, use VSFrameRef/VSNodeRef/VSFormat, prop* map functions, createFilter/VSFilterInit, or need migration to an R74+ or current API4 SDK. Also use when the migration task includes modern Windows CI, API4-compatible plugin packaging, GitHub Release assets, wheel/pyproject packaging, or pip-installable release-backed plugin delivery.
---

# VapourSynth API3 to API4

## Four-Phase Migration Model

Use this model for real plugin projects. Keep API migration, behavior
verification, and packaging modernization separate unless the user explicitly
asks to combine them.

1. **Reproduce the API3 baseline.** Identify the intended API3 revision,
   original build workflow, dependencies, VapourSynth SDK/header source, Python
   runtime, and plugin binary path. Build and explicitly load the unmodified
   plugin in an R73/API3-capable environment when possible. Record exact
   commands and blockers before editing source. If the local machine is missing
   toolchain or third-party dependencies, first do a simple environment probe,
   then write down the exact missing pieces and give the user concrete
   configuration steps to satisfy them. Stop there and wait for the user's
   feedback instead of silently downloading dependencies, inventing a different
   local build path, or continuing past the blocked baseline phase.
2. **Port the VapourSynth interface.** Run the report/scanner, apply safe
   mechanical rewrites, then manually migrate entry/registration, filter
   lifecycle, map/property calls, `VSVideoInfo.format`, ownership, request
   patterns, and source-filter or multi-output design. Keep bug fixes,
   optimizations, and packaging changes out of the pure API patch unless they
   are required to compile or preserve behavior.
3. **Compare behavior.** Build the API4 candidate, explicitly load it in a
   clean R74+ environment, and compare against the API3 baseline in
   separate Python processes. Use deterministic generated clips for normal
   filters and deterministic real media for source readers. Compare hashes,
   frame properties, dimensions, formats, error paths, and `PlaneStats`. When
   both environments and both plugin binaries are already available locally, do
   not defer this step: run at least one deterministic paired case immediately
   and report the exact match result side by side.
4. **Modernize build and packaging.** Only after API behavior is understood,
   clean up CI/build/release flows. Reuse existing GitHub Actions where
   possible, retarget VapourSynth SDK/header discovery to an R74+ API4 SDK, prefer
   package-manager dependencies over hand-built ones when practical, and verify
   released artifacts with package layout and load tests.

## Workflow

1. Inspect the project before editing. Identify the build system, GitHub Actions
   workflows, plugin entry points, source files, and whether the plugin is
   video-only, audio-capable, a source filter, or stateful.
   For baseline reproduction, also identify the expected compiler, external
   libraries, header roots, import libraries, runtime DLLs, and whether the
   repository expects pkg-config, Meson, CMake, or a Visual Studio project.
2. Run the project-level migration report:

```bash
python scripts/migration_report.py /path/to/plugin
python scripts/migration_report.py /path/to/plugin --json
```

Use this first for non-trivial projects. It summarizes likely plugin shape,
build system, hot files, complexity, migration stages, risk gates, and
recommended next steps. Treat risk gates as verification/design requirements,
not as mechanical rewrite targets. Use `--json` when another script or CI job
needs to consume the report.

3. Run the read-only scanner from this skill when you need exact locations:

```bash
python scripts/scan_api3.py /path/to/plugin
python scripts/scan_api3.py /path/to/plugin --json
```

If `python` is not available, use the local Python launcher/interpreter that is
available in the environment. The scanner accepts either a project directory or
a single source/build file. Use `--fail-on-hits` only when you want CI-style
failure if API3 markers remain. It skips common generated/output directories,
including `verification*`, so stored API3 baselines do not pollute source scans.
Run it on the target plugin tree, not on this skill directory, because the
references intentionally contain API3 names.

4. Optionally run the conservative mechanical rewriter:

```bash
python scripts/rewrite_api3_mechanical.py /path/to/plugin --diff
python scripts/rewrite_api3_mechanical.py /path/to/plugin --write
python scripts/rewrite_api3_mechanical.py /path/to/plugin --json
```

It defaults to dry-run mode and only rewrites stable name/header/string
changes. Use it as a first pass, then re-run the scanner. It deliberately leaves
entry points, `createFilter` lifecycle, `VSVideoInfo.format` semantics,
`propSetData`, `paTouch`, `_ColorRange`, and activation-flow changes for manual
review.

5. Read `references/migration-guide.md` when the scanner finds API3 markers or
   when you need exact API mappings.
   Read `references/build-systems.md` when the migration touches CMake, Meson,
   Makefiles, Visual Studio projects, pkg-config, CI workflows, release
   artifacts, install paths, or bundled SDK headers.
   Read `references/verification.md` before calling a migration complete or
   when the user can provide R73/R74+ comparison environments.
   Read `references/release-packaging-example.md` when the user wants a
   pip-installable plugin repository, a GitHub Release backed
   `pip install "package-name @ git+https://...git"` path, or a Windows-first
   example that avoids manual DLL copying.
6. Migrate in this order:
   includes and types, map/property calls, entry point and registration strings,
   filter creation/lifecycle, format handling, helper functions, build files.
7. Treat scanner findings marked `manual` as design-review points. Do not
   blindly rewrite `_ColorRange`, `paTouch`, `arFrameReady`,
   `queryCompletedFrame`, compat formats, or custom cache behavior.
8. Build or run the repository's normal verification command. If the repository
   has GitHub Actions, prefer reusing that workflow or a local reproduction of
   its exact commands before inventing a new build recipe. Use compiler errors
   to catch remaining API3 names and update the code until the API4 build is
   clean.
   During the API3 baseline phase, do not auto-install missing dependencies or
   pivot to an unrelated toolchain just to keep moving. Probe the local machine,
   summarize what is present and what is missing, give the user explicit setup
   guidance, and wait for confirmation before attempting the blocked build
   again.
   If packaging is being modernized for pip/VCS install, confirm the intended
   Python package name early and keep it stable across `pyproject.toml`, wheel
   metadata, documentation, and install examples. Also confirm the default
   mapping from `project.version` to the expected Release tag and asset URL.
   Prefer a simple `v<version>` rule, but if the repository uses a custom tag
   template, document and test that exact template in the build hook, workflow,
   and install examples.
9. Fill the verification gates from `references/verification.md`: scan, build,
   API4 load test, R73/API3 versus R74+/API4 behavior comparison, and package
   artifact checks when CI/release packaging changed. When the user has not
   provided both environments or plugin binaries, record exactly which gate is
   blocked. Compile success is necessary but not sufficient. Do not present a
   one-sided API4 runtime smoke as behavior verification; if only Gate 3 is
   done, say Gate 4 is still pending. If Gate 4 is possible, run it before
   summarizing verification.
   If the repository now supports
   `pip install "package-name @ git+https://...git"`, verify whether that path
   actually reuses the intended Release asset by default or still falls back to
   local compilation. If `project.version`, the default prebuilt URL, or the
   Release-tag template changed during this round, rerun the documented named
   VCS install against the default branch or target ref before calling the
   packaging flow complete.
10. When reporting progress after a successful API4 load or runtime smoke,
    explicitly state one of these outcomes:
    - paired API3/API4 check was run, including the case name and whether exact
      hashes and `PlaneStats` matched
    - paired API3/API4 check is blocked or still pending, including the exact
      missing environment, binary, or case input

For packaged Windows plugin directories or release zips, use:

```bash
python scripts/check_plugin_package.py artifact.zip \
  --plugin-dll plugin.dll --required support.dll \
  --require-manifest --require-top-level-dir --forbid-vapoursynth-prefix
python scripts/check_plugin_package.py artifact.zip \
  --plugin-dll plugin.dll --required support.dll \
  --require-manifest --require-top-level-dir --forbid-vapoursynth-prefix --json
```

Adjust `--required` for the plugin's data/runtime DLLs. This checks the package
directory shape before load-testing the extracted artifact.

When editing this skill's bundled scripts, run the lightweight regression test:

```bash
python scripts/self_test.py
```

It uses temporary synthetic fixtures and does not require a VapourSynth runtime.

## Migration Defaults

- Target base API4 unless the project explicitly needs API 4.1/4.2 functions.
- Use `VapourSynth4.h` and `VSHelper4.h`.
- Use `VapourSynthPluginInit2(VSPlugin *, const VSPLUGINAPI *)`.
- Register normal video filters with `vnode` arguments and `"clip:vnode;"`
  return types.
- Prefer `createVideoFilter` with `VSFilterDependency`. Use `rpStrictSpatial`
  only when output frame `n` requests input frame `n`; otherwise use a more
  conservative request pattern such as `rpGeneral`. Temporal/window filters
  that request neighboring frames should normally use `rpGeneral`.
- For API3 source filters that used multiple video outputs, redesign the API4
  surface as explicit returned nodes or frame properties. Alpha side outputs
  are usually represented with the `_Alpha` frame property on the main clip.
- Keep reference ownership explicit. `mapGetNode`, `mapGetFrame`, and
  `mapGetFunction` return references that must be released.
- Copy strings/data from input maps into instance data if they are needed after
  the create function returns.
- Preserve old filter behavior unless the user explicitly asks to incorporate
  upstream bug fixes or packaging changes found in newer releases.

## Common API Shape

API4 getframe signature:

```c
static const VSFrame *VS_CC filterGetFrame(
    int n, int activationReason, void *instanceData, void **frameData,
    VSFrameContext *frameCtx, VSCore *core, const VSAPI *vsapi
) {
    FilterData *d = (FilterData *)instanceData;
    if (activationReason == arInitial) {
        vsapi->requestFrameFilter(n, d->node, frameCtx);
    } else if (activationReason == arAllFramesReady) {
        const VSFrame *src = vsapi->getFrameFilter(n, d->node, frameCtx);
        /* process */
        return src;
    }
    return NULL;
}
```

API4 entry point:

```c
VS_EXTERNAL_API(void) VapourSynthPluginInit2(VSPlugin *plugin, const VSPLUGINAPI *vspapi) {
    vspapi->configPlugin("com.example.plugin", "plugin", "Plugin Name",
                         VS_MAKE_VERSION(1, 0), VAPOURSYNTH_API_VERSION, 0, plugin);
    vspapi->registerFunction("Filter", "clip:vnode;", "clip:vnode;",
                             filterCreate, NULL, plugin);
}
```

## Completion Checklist

- No project source includes API3 public headers for migrated plugin code.
- No migrated plugin exports `VapourSynthPluginInit`; it exports
  `VapourSynthPluginInit2`.
- No ordinary migrated code still uses `VSFrameRef`, `VSNodeRef`, `VSFuncRef`,
  `VSFormat`, `prop*`, or `createFilter`.
- `mapSetData` calls include `dtUtf8`, `dtBinary`, or an explicitly justified
  `dtUnknown`.
- `VSVideoInfo.format` member access uses API4 value semantics.
- Stride variables receiving `getStride` are `ptrdiff_t`.
- Manual review points from the scanner have been resolved or documented.
- The plugin builds against the intended VapourSynth API4 SDK.
- The plugin can be loaded explicitly with `core.std.LoadPlugin(...)` in a
  clean R74+ environment.
- If both API3 and API4 binaries/environments are available, at least one
  deterministic paired case has already been run and reported explicitly before
  calling runtime verification successful.
- If an R73/API3 baseline is available, representative output hashes/properties
  match or every intentional difference is documented.
- If packaging or CI artifacts changed, the downloaded artifact/release zip has
  the intended plugin directory layout and the packaged plugin load test passes.
- If packaging was modernized around `pyproject.toml` or wheels, the notes say
  what Python package name was chosen and whether users should install the
  direct wheel, use `pip install "package-name @ git+https://...git"`, or
  expect a local build fallback.
- If packaging was modernized around Release-backed VCS install, the notes also
  state the default `project.version` -> Release-tag mapping and whether the
  final documented named VCS install reused the Release asset or fell back to a
  local build.
- The forward-test doc or migration notes list the exact verification gates
  passed, blocked, and still untested.
