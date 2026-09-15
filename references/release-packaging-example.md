# Release-Backed pip Install Example

Use this reference when the user wants a modern Windows-first release strategy
after the API4 migration, especially when they want users to install through
`pip` instead of manually copying plugin DLLs.

## Pattern

Preferred current pattern for suitable plugins:

1. Build the native plugin in GitHub Actions.
2. Smoke-load the packaged plugin directory in CI.
3. Publish that tested package directory as a GitHub Release asset.
4. Add `pyproject.toml` plus a custom wheel build hook.
5. Choose and document a stable Python package name.
6. Make `pip install "package-name @ git+https://github.com/...git"` try the
   Release asset first, then fall back to local compilation only if needed.

This is a packaging pattern, not an API migration requirement. Keep it in phase
4 of the migration model unless the user explicitly asks to combine work.

## When this pattern fits

This works best when the plugin repository is more than "just one DLL", for
example:

- a plugin DLL plus a Python helper module
- a plugin DLL plus data files
- a plugin DLL plus support runtime DLLs

It is especially good for current API4 installs where plugin files live under:

```text
site-packages/vapoursynth/plugins/plugin-name/
```

## smoothuv example

The current reference example is `RyougiKukoc/vapoursynth-smoothuv-api4`.

Chosen package name:

- `vapoursynth-smoothuv`

It publishes:

- a Release zip containing a tested top-level plugin package directory:

  ```text
  smoothuv/
    manifest.vs
    smoothuv.dll
  ```

- a direct-install wheel:
  `vapoursynth_smoothuv-3-py3-none-win_amd64.whl`

Its repository build hook reads `project.version` from `pyproject.toml` and
constructs the default Release-asset lookup:

```text
https://github.com/RyougiKukoc/vapoursynth-smoothuv-api4/releases/download/v<version>/smoothuv-msys2-ucrt64.zip
```

Recommended user-facing VCS install form:

```powershell
pip install "vapoursynth-smoothuv @ git+https://github.com/RyougiKukoc/vapoursynth-smoothuv-api4.git"
```

During that install on Windows x86_64:

1. `pip` builds from repository metadata.
2. Hatchling invokes the custom build hook.
3. The hook first attempts to fetch the matching Release zip.
4. If found, the build repackages that tested plugin payload into the wheel.
5. If missing, the hook falls back to a local Meson build.

This lets users stay on `pip install` without manually placing DLLs.

If the user only says "make it pip installable from GitHub", prefer this
explicit named form over bare `pip install git+https://...git`. If the package
name has not been decided yet, decide it first and then update:

- `project.name` in `pyproject.toml`
- wheel documentation
- VCS install examples
- release notes

## Design rules

- Keep the tested native package zip as a Release asset even if you also
  publish a direct wheel. The zip is the reusable payload for the VCS install
  path.
- When updating a mutable variant Release, delete every old wheel matching the
  distribution before uploading the current platform wheels. Then list the
  Release assets and assert the exact expected set: current native zip(s) plus
  current wheel(s). `gh release upload --clobber` only replaces equal names; it
  leaves older versioned wheel filenames behind, where users can accidentally
  select stale payloads.
- Keep the mapping from package version to Release tag deterministic and
  documented. The simplest rule is `1.0` -> `v1.0`, but a custom template is
  acceptable only if the build hook, workflow, release naming, and install
  examples all use the same mapping.
- Prefer a top-level plugin directory in zips, not
  `vapoursynth/plugins/plugin-name/`.
- Use `manifest.vs` when support DLLs live beside the plugin DLL.
- Reuse the exact package directory that passed smoke tests when creating the
  Release zip.
- Prefer the explicit named VCS install form in docs:
  `pip install "package-name @ git+https://github.com/owner/repo.git"`.
- Before publishing a tag or release, run one loopback test where the build
  hook reads a locally produced Release zip through its explicit prebuilt-URL
  override. This catches broken asset lookup and package-shape problems before
  the remote Release exists.
- If the package name is still undecided, stop and choose one before finishing
  the packaging design.
- Document the install modes clearly:
  - direct wheel install
  - `pip install "package-name @ git+https://...git"`
  - forced local build fallback when needed

## Windows CI lessons from the example

The `smoothuv` forward test found two practical GitHub Windows issues that are
worth encoding in the skill:

- Do not replace step-level `PATH` in workflow `env:` blocks if that risks
  dropping the runner's system path. Prepend within the shell step instead.
- If using MSYS2/UCRT64 from PowerShell, bias Meson toward GCC explicitly or
  make the helper do so, otherwise mixed-toolchain runners may silently select
  `cl`.

The example also found that helper scripts should wire the normalized
VapourSynth wheel metadata into both `PKG_CONFIG` and `PKG_CONFIG_PATH`
automatically when possible, instead of requiring every caller to remember both
variables manually.

## Linux local-build fallback

A Windows Release-backed package must not assume its fallback is Windows-only.
On Linux, prefer compiling a native ``.so`` from the same VCS source when the
plugin's upstream build system supports it. A current Linux VapourSynth pip
wheel places API4 headers, ``libvapoursynth``, and ``vapoursynth.pc`` below its
Python package directory, so the ``.pc`` file is not normally on the system
pkg-config search path. A Hatch build hook can discover it without hard-coding
a Python installation prefix:

```python
try:
    import vapoursynth
except ImportError:
    pass
else:
    pkgconfig_dir = Path(vapoursynth.__file__).resolve().parent / "pkgconfig"
    if pkgconfig_dir.is_dir() and "PKG_CONFIG_PATH" not in env:
        env["PKG_CONFIG_PATH"] = str(pkgconfig_dir)
```

The hook must then locate platform-native artifacts (for example
``libplugin.so`` from Meson on Linux and ``plugin.dll`` on Windows), package
the Linux file as ``plugin.so``, and declare all three native suffixes in the
wheel artifacts list. Do not run a Windows/MSYS2 preparation script from a
non-Windows fallback.

Release assets are optional accelerators, not the implementation of source
installation. Dispatch the asset lookup by the running platform and
architecture. A Linux/macOS install must never look for a Windows ``.dll``;
a Windows install must never accept a Linux ``.so``. When no current-platform
asset exists, including a deliberately unsupported macOS Release line, run the
repository's native Meson/CMake/Autotools/Cargo build and stage the actual
output suffix (``.so`` or ``.dylib``) with its manifest and runtime files.
Test this branch with the force-build option on a platform that has a Release
asset, and test the ordinary no-asset branch on every platform that is not
published. Record a missing host SDK/toolchain as a blocked gate; do not fall
back to another platform's binary.

Validate this path in a clean Linux container with ``build-essential`` and
``pkg-config`` installed: build the wheel, inspect it for
``vapoursynth/plugins/plugin/plugin.so`` and ``manifest.vs``, install the
wheel, call ``core.std.LoadPlugin`` with that installed ``.so``, and request a
deterministic frame. This is a packaging/runtime smoke test, not an API3/API4
behavior comparison.

### Release-backed Linux ABI policy

When a project publishes Linux payloads, make Linux mirror Windows: publish a
top-level plugin-directory zip for the VCS hook and a direct-install wheel on
the same Git tag. Build the native plugin in a conservative manylinux
container, then run the VapourSynth runtime smoke in a separate modern Linux
job that can install the target VapourSynth wheel.

The build job may download and extract a target-platform VapourSynth wheel
solely for API4 headers and ``vapoursynth.pc``; it need not execute that wheel
inside the older build container. Explicitly set ``PKG_CONFIG_PATH`` to the
extracted package's ``vapoursynth/pkgconfig`` directory.

Do not rely on Hatchling's host platform-tag inference for a payload-only
plugin wheel. Let CI supply a project-specific platform-tag override after
testing the binary, for example ``manylinux_2_27_x86_64`` when that is the
published VapourSynth runtime baseline. Extract the final wheel and inspect
the packaged ``.so`` with ``readelf --version-info``; fail if its highest
``GLIBC_X.Y`` symbol exceeds the documented build policy. This avoids both an
incorrect generic ``linux_x86_64`` tag and claiming a newer ABI than the
plugin requires.

Keep the force-build environment variable functional on Linux. It is the
escape hatch for users who provide a compatible local VapourSynth SDK/runtime
or need a platform not covered by the Release asset. Tag publication should
wait for Windows and Linux package/runtime smoke jobs, then use one publish
job to upload all platform assets to avoid release creation races.

## Verification requirements

Do not call this packaging pattern complete unless all of these are checked:

1. CI native build passed.
2. CI packaged-path smoke load passed.
3. CI wheel install smoke passed.
4. Release zip layout was checked.
5. Tag/release workflow actually uploaded the Release assets.
6. The chosen Python package name was documented consistently.
7. `pip install "package-name @ git+https://...git"` was tested or the exact
   blocker was documented.
8. If package version, default asset URL, or tag naming changed, the documented
   named VCS install was re-tested against the target default branch or ref,
   not only against an older tag or a local wheel.

If the VCS install path is part of the design goal, explicitly report whether
it used the Release asset by default or fell back to a local build.
