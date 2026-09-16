# Build-System Migration Notes

Use this reference when a VapourSynth API3 plugin migration touches CMake,
Meson, Makefiles, Visual Studio projects, pkg-config files, or install scripts.

Treat build-system modernization as a later phase unless a build edit is
strictly required to compile the API4 source. First preserve or reproduce the
original API3 build well enough to create a baseline binary; then retarget the
minimum API-specific include/header/link pieces for the API4 candidate. After
behavior verification, clean up CI, package-manager dependency setup, and
release artifact layout as separate work.

## General Checks

- Before trying to build locally, do a narrow environment probe and record the
  actual compiler, build tool, SDK/header roots, import libraries, pkg-config
  executables, and third-party library paths visible on the machine.
- If the probe shows missing dependencies, do not immediately download,
  substitute, or workaround them. First give the user a concrete configuration
  checklist for the intended build path and wait for feedback that the machine
  has been prepared.
- Ensure source files include `VapourSynth4.h` and `VSHelper4.h`.
- Ensure the compiler include path points at a VapourSynth SDK that contains
  API4 headers.
- Before inventing a local build recipe, inspect `.github/workflows/`. Most
  maintained VapourSynth plugins already encode their compiler, dependency, SDK,
  and packaging setup in GitHub Actions.
- For API3 baseline reproduction, prefer the repository's original toolchain
  and dependency shape. Only switch toolchains after the baseline status is
  documented and the user has explicitly prepared or approved the alternative.
- The mechanical rewrite script may update API3 header names in source/build
  files, but still inspect dependency checks and include directories by hand.
- Do not add a dependency on legacy API3 headers just because `VapourSynth.h`
  still exists in some source releases.
- Check whether the project builds bundled SDK headers or uses system headers.
  Prefer the target VapourSynth SDK consistently across all build variants.
- Keep plugin output naming and install location unchanged unless the old build
  hard-codes a legacy VapourSynth layout.

## pkg-config

Modern VapourSynth source still ships `vapoursynth.pc.in`, but project-specific
pkg-config names may vary by distribution. Check the target environment before
changing package names.

Look for:

- `vapoursynth`
- `vapoursynth-script`
- hard-coded include paths to old SDK folders
- hard-coded `VAPOURSYNTH_API_MAJOR=3` or equivalent defines

Current Windows wheels/portable installs can provide API4 headers and
pkg-config metadata. When using an installed or extracted R74+ wheel as the SDK
source, verify that the `.pc` file resolves to the actual `include` and library
directories in that layout. If an extracted wheel's `prefix`, `includedir`, or
`libdir` does not match its temporary location, generate a temporary normalized
`.pc` file for CI instead of hard-coding many include/link paths in build
scripts.

## CMake

Common places to update:

- `find_path` searches for `VapourSynth.h` or `VSHelper.h`
- source-level checks that include API3 headers
- custom variables such as `VAPOURSYNTH_INCLUDE_DIR`
- generated config headers with API major/minor constants

Prefer checking for `VapourSynth4.h` when the project is plugin-only.

When a `MODULE` or `SHARED` plugin target links CMake `OBJECT` libraries,
explicitly set `POSITION_INDEPENDENT_CODE ON` on every object target. PIC on
the final plugin does not reliably propagate to separately-defined object
targets. This can pass on a modern linker and then fail in a conservative
manylinux build with relocations such as `R_X86_64_32` against pthread symbols.

## Meson

Common places to update:

- `cc.has_header('VapourSynth.h')`
- `cc.find_library` or dependency wrappers that assume old SDK layouts
- generated configuration data with API3 constants

Prefer `cc.has_header('VapourSynth4.h')` for plugin code. Keep `VSScript4.h`
separate; VSScript is for host applications, not ordinary plugins.

For new Windows CI, MSYS2/UCRT64 plus Meson/pkg-config is often cleaner than
MSVC when the plugin's non-VapourSynth dependencies are available through
pacman. A typical workflow installs GCC, Meson, Ninja, pkgconf, Boost/OpenCL
packages as needed, extracts or installs a current VapourSynth wheel for API4
headers, points `PKG_CONFIG_PATH` at the wheel's normalized `vapoursynth.pc`,
then builds and smoke-loads the packaged artifact. Keep an old MSVC workflow as
manual compatibility coverage only when it is slower, harder to reproduce, or
uses legacy SDK setup that should not be the primary path.

When invoking MSYS2 compilers from PowerShell, `cmd`, or another non-MSYS shell,
prepend the active MSYS2 environment's `bin` directory and `usr/bin` to `PATH`
before compiling. Otherwise GCC may find `gcc.exe` but fail when launching
`cc1.exe` because dependent runtime DLLs are not discoverable. For UCRT64 this
usually means adding `<msys2>/ucrt64/bin` and `<msys2>/usr/bin`.

If Boost.Compute is used with current Khronos OpenCL headers, check the
project's intended OpenCL target. Older plugins may need an explicit
`CL_TARGET_OPENCL_VERSION` such as `120` to compile without inheriting OpenCL
3.0 defaults.

Do not assume a distribution's Boost development package exposes Meson or
pkg-config metadata. For a default path that uses only Boost.Compute headers,
probe the needed header and use an explicit header-only dependency fallback.
Keep a strict `dependency('boost', modules: ...)` requirement for modes such as
an offline cache that actually link Boost libraries.

Conservative manylinux images can also ship a Boost version that lacks
Boost.Compute entirely. When building a Boost.Compute plugin there, download a
fixed modern Boost source archive, use its headers only, and pass that root
through the project's existing `boost_root` or equivalent Meson option. Do not
silently build a Release payload against an arbitrary newer runner-host Boost.

## Makefiles

Common places to update:

- hard-coded `-I` SDK paths
- copied SDK headers in repository-local include folders
- install rules that place files in old autoload directories
- variables named for API3 or `VS_INCLUDE`

Do not remove platform-specific compiler/linker flags unless they are directly
API3-specific.

## GitHub Actions Reuse

For existing plugin projects, prefer reusing the repository's CI workflow over
reconstructing the full build environment locally.

Checklist:

- Read every `.github/workflows/*.yml` or `.yaml` file before editing build
  scripts.
- Identify the OS matrix, compiler/toolchain setup, dependency installation,
  VapourSynth SDK/header source, build command, test command, and artifact
  upload step.
- Preserve the dependency setup and compiler flags unless they directly select
  API3 headers or APIs.
- Update only the API-specific parts: included SDK headers, VapourSynth include
  paths, API version checks, generated package metadata, and post-build smoke
  tests.
- If the workflow downloads a VapourSynth SDK or wheel, retarget it to R74+ or
  the intended current release. Do not silently keep an R73/API3 SDK for an API4
  migration build.
- If the workflow uploads artifacts, use those artifacts as the preferred
  binaries for later explicit-load and behavior-comparison gates.
- If benchmarking or dependency availability identifies one build as the
  preferred user-facing build, make that workflow the automatic push/PR path
  and keep slower or legacy workflows manual-only.
- For release publishing, generate the release zip from the same packaged
  directory that passed smoke tests. Trigger release upload on tag/release
  events, not on every branch push.
- When the user wants
  `pip install "package-name @ git+https://...git"` instead of manual DLL
  copying, treat `pyproject.toml`, the chosen Python package name, and the
  wheel build hook as part of the release design. A direct wheel asset alone is
  not enough for that install path because pip builds from repository metadata
  when installing from VCS.
- For that VCS-install pattern, publish the tested native plugin package
  directory as a Release zip asset and make the wheel build hook try that asset
  first, falling back to local compilation only if necessary.
- Prefer the explicit named VCS install form in docs and testing. If the user
  has not chosen a package name yet, ask for one or define it before finishing
  the packaging work.
- Keep the package version to Release-tag mapping deterministic. The simplest
  rule is `project.version = 1.0` and Release tag `v1.0`, but a custom template
  is acceptable only if the build hook, workflow, docs, and smoke tests all
  use the same mapping.
- Before publishing the remote Release, prefer one loopback smoke test where
  the source-install path consumes a locally produced Release zip via the
  hook's explicit prebuilt-URL override. This catches mismatches between the
  packaged artifact and the VCS-install hook before tag publication.

For mutable variant refs, force-updating a tag can generate both deletion and
creation push events. Put ref-scoped workflow concurrency around the full
build/publish workflow and cancel superseded runs, otherwise duplicate jobs can
race to overwrite the same Release assets. Still validate each variant ref one
at a time, and remove a failed tag/Release before retrying it.

This is often cleaner than a local build because the CI already knows the
project's non-VapourSynth dependencies. The local machine can stay focused on
static migration, source comparison, and report comparison, while GitHub-hosted
builds provide the compiled DLLs/so/dylibs.

Do not treat CI success as final correctness. CI build artifacts still need an
explicit API4 load test and, when an API3 baseline is available, frame output
comparison using the verification runner.

## Windows Plugin Package Layout

For API4-compatible Windows packaging, prefer a top-level plugin directory in artifacts
and release zips:

```text
plugin-name/
  manifest.vs
  plugin.dll
  support-runtime.dll
```

The zip/artifact root should usually be `plugin-name/`, not
`vapoursynth/plugins/plugin-name/`, unless a package manager specifically
expects the full install prefix. Users can copy that directory under
`<site-packages>/vapoursynth/plugins/`.

Use `manifest.vs` when the directory contains support DLLs. A manifest tells the
VapourSynth plugin loader which plugin base names to load from that directory,
so runtime DLLs can live next to the plugin without being scanned as plugins.
This is also the safer layout when a plugin ships multiple DLLs or optimized
variants.

In GitHub Actions, upload the parent directory if the artifact system would
otherwise flatten the package folder. After upload, download the artifact and
inspect the extracted path list; verify the top-level package directory is
preserved.

For repeatable checks, run `scripts/check_plugin_package.py` against the
downloaded artifact or release zip. Use `--require-top-level-dir` for zips that
should preserve `plugin-name/`, and `--forbid-vapoursynth-prefix` when the zip
should not include an install-root prefix such as `vapoursynth/plugins/`.

If the repository also publishes a wheel, remember that the Release zip and the
wheel serve different purposes:

- the wheel is the most direct user install artifact
- the top-level package zip is the reusable binary payload for
  `pip install "package-name @ git+https://...git"` when the repository build
  hook consumes Release assets

## Visual Studio Projects

Common places to update:

- Additional Include Directories pointing at old SDKs
- project filters listing `VapourSynth.h` or `VSHelper.h`
- preprocessor definitions that force API3 behavior
- copied header files in the project tree

Update `.vcxproj.filters` only when the actual project file or source list
requires it.

## Verification

After source migration, run the project's normal build. If the project has no
configured build, compile at least one migrated plugin source file against the
target API4 SDK `include` directory with warnings enabled to catch stale API3 signatures.
