# Linux Docker Validation

Use this reference for Linux plugin validation after a VapourSynth API4 port
or a Release-backed packaging change. The baseline image is deliberately ready
for validation but contains no target plugin.

## Baseline image

Build the image from `assets/linux-validation/Dockerfile`. When the host needs
an HTTP proxy, pass it as build arguments rather than attempting a direct
image/dependency download first:

```powershell
docker build `
  --build-arg HTTP_PROXY=http://host.docker.internal:7890 `
  --build-arg HTTPS_PROXY=http://host.docker.internal:7890 `
  -t vpy-api4-vs79-validation `
  -f skills/vapoursynth-api3-to-api4-skill/assets/linux-validation/Dockerfile .
```

The image contains Debian Bookworm, Python 3.13, VapourSynth R79, a native
compiler, CMake, pkg-config, Meson/Ninja, Hatchling, curl, git, and unzip. It does not
contain a target plugin. Rebuild it only when the declared baseline changes;
reuse it for each plugin test.

The examples deliberately mount a repository read-only. Copy the source into a
container work directory before running a build or a command that can create
`__pycache__`; alternatively set `PYTHONDONTWRITEBYTECODE=1` for a read-only
static check. Do not make the source mount writable merely to accommodate
generated build output.

The baseline explicitly includes Autotools (`autoconf`, `automake`, and
`libtool`) in addition to CMake and Meson. An Autotools plugin should still
copy its checkout to the container work directory before invoking `autogen.sh`.
On a Windows host, normalize that copied shell script to LF if the checkout has
CRLF endings: a Linux shell otherwise passes a literal carriage return to tools
such as `autoreconf`. Do this only in the temporary build copy, not by changing
the repository's Windows working-tree settings.

VapourSynth R79's Linux wheel is tagged `manylinux_2_27_x86_64`, so a release
plugin intended for that runtime must not claim a lower end-to-end runtime
floor. A plugin may have lower GLIBC symbol requirements, but that does not
make an incompatible VapourSynth runtime usable.

When a native build obtains headers and `vapoursynth.pc` from the installed
wheel, prepend `vapoursynth/pkgconfig` to `PKG_CONFIG_PATH` while retaining any
caller-provided entries. Do not treat a pre-existing path as proof that it
contains `vapoursynth.pc`; hosted CI environments commonly set it for Python
or unrelated libraries.

Some Linux VapourSynth wheels keep `VapourSynth4.h` and `VSHelper4.h` directly
under `vapoursynth/include`, while legacy cross-platform plugin source uses
`#include <vapoursynth/VapourSynth4.h>`. Confirm the actual header layout as
well as the pkg-config include flag. If these forms differ, create a temporary
build-only include root containing `vapoursynth/` with the wheel headers (or
add an equivalent compatible include directory). Do not mutate the installed
wheel and do not change Windows-only SDK shims merely to make a Linux fallback
compile.

Some R79 wheels ship only a versioned native library such as
`libvapoursynth.so.4`, while their pkg-config metadata requests
`-lvapoursynth`. If the unversioned linker name is absent, create a temporary
SDK shim inside the build directory: copy the wheel library, add a
`libvapoursynth.so` linker-name symlink (or copy on filesystems without
symlink support), and write a replacement `vapoursynth.pc` pointing to that
shim and the wheel headers. Prepend the shim and the wheel metadata to
`PKG_CONFIG_PATH`, retaining caller entries. Never alter the installed wheel,
and do not bundle `libvapoursynth` into the plugin payload: the installed
VapourSynth runtime supplies it.

An R79 wheel may be too new to install into a conservative manylinux builder
even though its extracted headers and `vapoursynth.pc` are sufficient to build
a plugin. In that CI-only situation, download and extract the selected wheel,
point `PKG_CONFIG_PATH` at the extracted metadata, and invoke the frontend's
explicit no-isolation dependency-check bypass (PyPA build currently spells
this `--no-isolation --skip-dependency-check`). Keep `VapourSynth` in
`build-system.requires` and separately test an ordinary isolated PEP 517
install on an R79-capable runtime; the CI bypass is not evidence that users'
isolated source builds can omit the SDK requirement.

If a hook normally imports `vapoursynth` to find its SDK, make that location
overrideable for the conservative builder, for example with a
`<PLUGIN>_VAPOURSYNTH_ROOT` environment variable pointing directly at the
extracted wheel's `vapoursynth/` directory. Use that root before attempting an
import; ordinary isolated PEP 517 builds should continue to discover the SDK
from the imported wheel. Test both paths, since an extracted R79 wheel cannot
be imported in an older glibc container.

For Hatchling custom build hooks, do not assume the `initialize(version, ...)`
argument is the project version: the standard wheel target supplies `standard`.
When a Release URL needs the distribution version, read the authoritative
`[project].version` metadata (or an explicit environment override) and test the
default URL in an isolated build before publishing. A target-name-derived URL
such as `releases/download/vstandard/...` must fall back cleanly, but is not the
intended Release mapping.

VapourSynth wheel pkg-config metadata is sufficient for compilation but need
not define every optional variable a plugin's install rule expects. In
particular, do not make wheel packaging depend on `vapoursynth.pc` supplying a
`libdir` variable merely to choose an install destination that the wheel hook
does not use. Keep the dependency declaration for headers and compiler flags,
and choose an ordinary build-system install root for any unused install rule.

Manylinux images can expose a versioned Python interpreter while omitting that
interpreter's `bin` directory from `PATH`. After installing Meson with
`$PYTHON -m pip install meson`, invoke it as
`$PYTHON -m mesonbuild.mesonmain` (or explicitly prepend the scripts
directory) instead of assuming a bare `meson` command is available. Prepend
that same interpreter directory before Meson configures so its `ninja` entry
point is discoverable. When enabling `devtoolset`, source its `enable` script
before `set -u`: it reads otherwise-optional variables such as `MANPATH`.
Test this inside the selected builder image before making it the release path.

Before committing to a conservative builder, run its Meson configure step
against the project's declared `cpp_std` or `c_std`. An older builder compiler
can reject a newly named language mode (for example, GCC 10 rejects Meson's
`c++23` option even when the source only needs C++20). Use the oldest standard
that the project actually requires, keep the version change reviewable, and
repeat the ABI inspection after the adjustment.

For a plugin with optional OpenMP, regard `libgomp` as a runtime dependency,
not merely a build detail. Smoke the uploaded payload in fresh processes with
more than one OpenMP thread before bundling a libgomp copy. If that combination
is unstable across the conservative builder and modern runtime, explicitly
disable the optional OpenMP path for the Linux release and Linux fallback,
document the serial-performance tradeoff, and verify its frame output rather
than shipping a runtime library that only passes a loader check.

## Release payload gate

For a Linux Release zip, validate the actual uploaded asset, not a local build
directory. Run the target repository's explicit package smoke script in the
baseline image. The script must disable plugin autoloading before calling
`core.std.LoadPlugin` on the extracted `.so`.

```powershell
$repo = (Resolve-Path repos/vapoursynth-tcomb-api4).Path
docker run --rm `
  -e http_proxy=http://host.docker.internal:7890 `
  -e https_proxy=http://host.docker.internal:7890 `
  -v "${repo}:/workspace:ro" `
  vpy-api4-vs79-validation bash -lc `
  'mkdir /release && curl -fsSL https://github.com/RyougiKukoc/vapoursynth-tcomb-api4/releases/download/v4.2/tcomb-linux-x86_64.zip -o /release/tcomb.zip && python tools/ci_smoke_package.py --artifact-zip /release/tcomb.zip --json'
```

The direct package smoke should prove all of the following:

- the zip has one top-level plugin directory, a manifest, and the expected
  native `.so`;
- explicit `LoadPlugin` succeeds with autoload disabled;
- a deterministic valid clip renders representative frames, recording hashes,
  dimensions, format, and PlaneStats;
- an unsupported input follows the documented error path.

For a Release-backed VCS package, run a second clean-container install using
the documented `git+https` ref. Inspect pip output to confirm the hook selected
the platform Release asset rather than silently compiling from source, then
run the installed-wheel autoload smoke.

## OpenCL payloads

An OpenCL plugin needs two separate checks. Package the OpenCL loader and every
non-system library identified by the payload's dynamic-dependency closure, with
an `$ORIGIN` runtime search path when those libraries sit beside the plugin.
The vendor ICD remains a host requirement and must not be copied from a build
machine into a generic payload.

Require an explicit accelerator-mode filter call followed by `get_frame()` to
claim OpenCL validation. A successful `LoadPlugin`, an installed loader, or a
CUDA-visible GPU is not evidence of an OpenCL backend: Linux GPU containers
often lack both `libOpenCL.so` and `/etc/OpenCL/vendors/*.icd`. Smoke scripts
should support a strict mode that fails without a real frame and otherwise
record the exact unavailable-platform error. Report that condition as an
unvalidated GPU gate, never as a CPU fallback or GPU success.

## CUDA RTC payloads

Validate each CUDA dependency line in a separate environment. Do not install
or merge payloads built for two CUDA lines into one plugin directory. A Linux
CUDA Release payload should record its toolkit version, `readelf` GLIBC and
GLIBCXX requirements, `ldd` dependencies, NVIDIA driver, GPU name, and compute
capability. A loader-only smoke is insufficient: invoke the RTC filter and
request frames so NVRTC actually compiles the generated kernel on the target
driver and GPU.

When a CUDA plugin statically links `libstdc++` or `libgcc` to keep a portable
ABI, hide archive symbols from the dynamic export table, for example with
`-Wl,--exclude-libs,ALL` on ELF. Otherwise those symbols can interpose with the
host C++ runtime already loaded by VapourSynth or Python and corrupt seemingly
unrelated operations such as generated NVRTC source construction. Recheck both
the ABI inspection and the real RTC compile-and-frame smoke after changing
link options.

## TComb evidence

TComb v4.2 established this procedure with the uploaded
`tcomb-linux-x86_64.zip`: explicit loading of `tcomb.so` succeeded under R79,
frames 0, 3, and 11 from a static YUV420P8 case had the same SHA-256,
dimensions were 64x48, and an RGB input was rejected. Its CI repeats the same
asset smoke after manylinux build and before tag publication.

This is a Linux runtime/package behavior gate. It is not an API3/API4
equivalence claim. When an API3 binary/environment is available, run the
separate-process comparison described in `verification.md` and retain both
reports.
