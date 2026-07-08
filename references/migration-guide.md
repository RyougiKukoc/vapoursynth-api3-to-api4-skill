# VapourSynth API3 to API4 Migration Guide

Use this reference when converting C or C++ VapourSynth plugins from API3 to
API4. Prefer current project source and compiler errors over this guide when
they conflict.

## Baseline Before Editing

For non-trivial projects, first reproduce or document the API3 baseline. Record
the original revision, API3 SDK/header source, VapourSynth runtime, dependency
versions, build command, plugin binary, and explicit-load result. If the
baseline cannot be built locally, document the exact blocker and prefer an
existing CI artifact or user-provided binary for later comparison.

Do not mix the pure API port with unrelated bug fixes, optimization work, or
packaging modernization until the API3/API4 behavior question is understood.

## Required Shape of an API4 Plugin

API4 plugin files normally include:

```c
#include "VapourSynth4.h"
#include "VSHelper4.h"
```

The exported entry point must be:

```c
VS_EXTERNAL_API(void) VapourSynthPluginInit2(VSPlugin *plugin, const VSPLUGINAPI *vspapi) {
    vspapi->configPlugin("com.example.plugin", "plugin", "Plugin Name",
                         VS_MAKE_VERSION(1, 0), VAPOURSYNTH_API_VERSION, 0, plugin);
    vspapi->registerFunction("Filter", "clip:vnode;", "clip:vnode;",
                             filterCreate, NULL, plugin);
}
```

Normal video filters should create nodes from the public create function:

```c
VSFilterDependency deps[] = {{d.node, rpStrictSpatial}};
vsapi->createVideoFilter(out, "Filter", &vi, filterGetFrame, filterFree,
                         fmParallel, deps, 1, data, core);
```

Keep `rpGeneral` when the access pattern is unclear.
Use `rpGeneral` for temporal/window filters that request neighboring frames
such as `n - radius` through `n + radius`; `rpStrictSpatial` is only for output
frame `n` requesting input frame `n`.

## High-Level Design Changes

- API4 is explicitly media-typed. Video and audio nodes/frames have distinct
  argument/property types.
- `VSVideoInfo.format` is a `VSVideoFormat` value, not a nullable `VSFormat *`.
- There is no ordinary API4 `VSFilterInit` step. Do validation and construct
  output `VSVideoInfo` before `createVideoFilter` or `createAudioFilter`.
- `VSFilterDependency` communicates upstream nodes and request patterns to the
  cache.
- `prop*` map functions were renamed to `map*` and expanded with typed
  media-aware node/frame values.

## Entry Point and Function Registration

| API3 | API4 |
| --- | --- |
| `VapourSynthPluginInit(configFunc, registerFunc, plugin)` | `VapourSynthPluginInit2(plugin, vspapi)` |
| `configFunc(id, ns, name, apiVersion, readonly, plugin)` | `vspapi->configPlugin(id, ns, name, pluginVersion, apiVersion, flags, plugin)` |
| `registerFunc(name, args, func, data, plugin)` | `vspapi->registerFunction(name, args, returnType, func, data, plugin)` |

Registration string changes:

- `clip` input usually becomes `vnode`.
- `frame` input usually becomes `vframe`.
- Add an explicit return type string, usually `"clip:vnode;"`.
- Use `anode` / `aframe` only for actual audio plugins.
- Use `"any"` only for genuinely unpredictable return types; ordinary filters
  should expose concrete return types for editor completion.
- `configPlugin` now has a flags field. `0` means read-only. Use
  `pcModifiable` only for plugin loaders or special cases that need API3-style
  post-load function registration.

## Type Renames

| API3 | API4 |
| --- | --- |
| `VSFrameRef` | `VSFrame` |
| `VSNodeRef` | `VSNode` |
| `VSFuncRef` | `VSFunction` |
| `VSFormat` | `VSVideoFormat` |
| `VSFreeFuncData` | `VSFreeFunctionData` |
| `VSMessageHandler` | `VSLogHandler` |
| `VSMessageHandlerFree` | `VSLogHandlerFree` |

Reference-counting and function object renames:

| API3 | API4 |
| --- | --- |
| `cloneFrameRef` | `addFrameRef` |
| `cloneNodeRef` | `addNodeRef` |
| `cloneFuncRef` | `addFunctionRef` |
| `freeFunc` | `freeFunction` |
| `createFunc` | `createFunction` |
| `callFunc` | `callFunction` |

The bundled `scripts/rewrite_api3_mechanical.py` can apply these stable
renames, API3 header replacements, most `prop*` to `map*` member-call renames,
`paReplace`/`paAppend`, basic color-family names, and registration string
`clip`/`frame` to `vnode`/`vframe`. Run it in dry-run mode first with `--diff`.
It does not complete lifecycle, entry-point, `VSVideoInfo.format`, or
`mapSetData` migration.

For a project-level triage before editing, run
`scripts/migration_report.py /path/to/plugin`. It groups scanner markers into
mechanical, entry-point, lifecycle, format/media, and host/core stages, then
lists hot files and recommended next steps.
Pass `--json` when the result needs to be consumed by a CI job or a wrapper
script.

The conservative rewriter also supports `--json` for dry-run automation:
`scripts/rewrite_api3_mechanical.py /path/to/plugin --json`. Use it to count
available mechanical rewrites and remaining manual markers without parsing the
human diff output.

The report's `Risk Gates` section is intentionally broader than API3 marker
scanning. It may flag already-migrated code that still needs special design or
verification, such as temporal frame requests, source-reader media
dependencies, accelerator runtimes, CI/release packaging, or alpha side output.
Use those gates to choose verification cases and build strategy; do not treat
them as proof that API3 names remain.

## Filter Lifecycle Conversion

API3 `getFrame` commonly starts with:

```c
static const VSFrameRef *VS_CC filterGetFrame(
    int n, int activationReason, void **instanceData, void **frameData,
    VSFrameContext *frameCtx, VSCore *core, const VSAPI *vsapi
) {
    FilterData *d = (FilterData *)*instanceData;
}
```

API4 should be:

```c
static const VSFrame *VS_CC filterGetFrame(
    int n, int activationReason, void *instanceData, void **frameData,
    VSFrameContext *frameCtx, VSCore *core, const VSAPI *vsapi
) {
    FilterData *d = (FilterData *)instanceData;
}
```

Rules:

- Remove `arFrameReady` handling. API4 normal filters request on `arInitial`
  and process on `arAllFramesReady`.
- `frameData` now points to scratch storage for `void *[4]`, not just one
  pointer. Use it for temporary per-frame state when it avoids allocations.
- Remove `VSFilterInit` when it only calls `setVideoInfo` and assigns data.
- Replace `createFilter(..., init, getFrame, free, filterMode, flags, data, core)`
  with `createVideoFilter(..., vi, getFrame, free, filterMode, deps, numDeps,
  data, core)`.
- Convert `nfMakeLinear` to `setLinearFilter(node)` only when the filter uses
  linear caching or `cacheFrame`.
- Convert `nfNoCache` / `nfIsCache` only after reviewing intent. API4 cache
  control is `setCacheMode` and `setCacheOptions`.

Source filters and old multi-output filters need an API design review:

- API3 filters could expose multiple clip outputs from one filter instance via
  `setVideoInfo(vi, numOutputs, node)` and `getOutputIndex(frameCtx)`. API4
  normal plugin functions have explicit return types, so do not blindly emulate
  the old multi-output model.
- If the old second output was alpha, return one `vnode` and attach a generated
  alpha frame to the main frame's `_Alpha` property. Create the alpha frame with
  a gray `VSVideoFormat` resolved by `queryVideoFormat`, set its range property
  deliberately, and use `mapConsumeFrame` when transferring ownership.
- Use `createVideoFilter2` when you need the returned `VSNode *` to call
  `setLinearFilter`, then publish it with `mapConsumeNode(out, "clip", node,
  maAppend)`.
- For pure source filters with no upstream clips, pass zero dependencies. A
  dummy `{NULL, rpGeneral}` entry with `numDeps = 0` is common in migrated C
  code but should not be counted as a real dependency.
- Review error paths after creating auxiliary frames. If alpha frame creation
  fails after the main output frame was allocated, release the main frame before
  returning `NULL`.

## Video Format Conversion

| API3 | API4 |
| --- | --- |
| `vi->format != NULL` | `vi->format.colorFamily != cfUndefined` |
| `vi->format->bitsPerSample` | `vi->format.bitsPerSample` |
| `vi->format->numPlanes` | `vi->format.numPlanes` |
| `getFrameFormat(frame)` | `getVideoFrameFormat(frame)` |
| `getFormatPreset(id, core)` | `getVideoFormatByID(&format, id, core)` |
| `registerFormat(...)` | `queryVideoFormat(...)` or `queryVideoFormatID(...)` |

Color family renames:

| API3 | API4 |
| --- | --- |
| `cmGray` | `cfGray` |
| `cmRGB` | `cfRGB` |
| `cmYUV` | `cfYUV` |
| `cmYCoCg` | no direct API4 equivalent |
| `cmCompat` | do not migrate as a normal planar format |

Do not rely on numeric equality of `pf*` preset values between API3 and API4.

## Frame Access

| API3 | API4 |
| --- | --- |
| `getFramePropsRO` | `getFramePropertiesRO` |
| `getFramePropsRW` | `getFramePropertiesRW` |
| `newVideoFrame(const VSFormat *, ...)` | `newVideoFrame(const VSVideoFormat *, ...)` |
| `newVideoFrame2(const VSFormat *, ...)` | `newVideoFrame2(const VSVideoFormat *, ...)` |
| `getPluginById` | `getPluginByID` |
| `getPluginByNs` | `getPluginByNamespace` |

Update local stride variables from `int` to `ptrdiff_t` when they receive
`vsapi->getStride(...)`.
Also review helper/processing function parameters that receive those stride
values; update them to `ptrdiff_t` when practical instead of silently narrowing
back to `int`.

`getWritePtr` invalidates read pointers to the same frame in API4. Avoid
reordering pointer acquisition unless you have checked the frame usage.

## Map and Property API

| API3 | API4 |
| --- | --- |
| `setError` | `mapSetError` |
| `getError` | `mapGetError` |
| `propNumKeys` | `mapNumKeys` |
| `propGetKey` | `mapGetKey` |
| `propNumElements` | `mapNumElements` |
| `propGetType` | `mapGetType` |
| `propDeleteKey` | `mapDeleteKey` |
| `propGetInt` | `mapGetInt` |
| `propGetFloat` | `mapGetFloat` |
| `propGetData` | `mapGetData` |
| `propGetDataSize` | `mapGetDataSize` |
| `propGetNode` | `mapGetNode` |
| `propGetFrame` | `mapGetFrame` |
| `propGetFunc` | `mapGetFunction` |
| `propSetInt` | `mapSetInt` |
| `propSetFloat` | `mapSetFloat` |
| `propSetData` | `mapSetData` |
| `propSetNode` | `mapSetNode` |
| `propSetFrame` | `mapSetFrame` |
| `propSetFunc` | `mapSetFunction` |
| `propGetIntArray` | `mapGetIntArray` |
| `propGetFloatArray` | `mapGetFloatArray` |
| `propSetIntArray` | `mapSetIntArray` |
| `propSetFloatArray` | `mapSetFloatArray` |

Append mode conversion:

| API3 | API4 |
| --- | --- |
| `paReplace` | `maReplace` |
| `paAppend` | `maAppend` |
| `paTouch` | no direct equivalent; consider `mapSetEmpty` |

A single `VSMap` key can hold video nodes or audio nodes, but not a mixture of
both. The same applies to video and audio frames.

`mapSetData` has an extra `VSDataTypeHint` argument:

```c
vsapi->mapSetData(map, key, data, size, dtUtf8, append);
vsapi->mapSetData(map, key, data, size, dtBinary, append);
```

Use `dtUnknown` only when the original intent cannot be inferred.

Ownership:

- `mapGetNode`, `mapGetFrame`, and `mapGetFunction` return new references.
- `mapSetNode`, `mapSetFrame`, and `mapSetFunction` do not consume references.
- `mapConsumeNode`, `mapConsumeFrame`, and `mapConsumeFunction` consume
  references even on error.
- Data returned by `mapGetData` is tied to the map/key lifetime. Copy it into
  instance data if it is needed after the create function returns.

`mapGetIntSaturated` and `mapGetFloatSaturated` can replace helper-wrapped
`mapGetInt` / `mapGetFloat` in API4 code when the old code only used helpers
to avoid narrowing warnings. This is a style and robustness improvement, not a
required migration step.

Use `mapConsumeNode` / `mapConsumeFrame` / `mapConsumeFunction` when a temporary
reference is only being inserted into a map and should always be released. This
usually shortens error paths, but it is not required if the original
`mapSetNode` plus `freeNode` ownership is preserved correctly.

## Helper Header Conversion

| API3 helper | C API4 helper |
| --- | --- |
| `VS_ALIGNED_MALLOC` | `VSH_ALIGNED_MALLOC` |
| `VS_ALIGNED_FREE` | `VSH_ALIGNED_FREE` |
| `isConstantFormat` | `vsh_isConstantVideoFormat` |
| `isSameFormat` | `vsh_isSameVideoInfo` or `vsh_isSameVideoFormat` |
| `vs_normalizeRational` | `vsh_reduceRational` |
| `vs_addRational` | `vsh_addRational` |
| `int64ToIntS` | `vsh_int64ToIntS` |
| `vs_bitblt` | `vsh_bitblt` |
| `areValidDimensions` | `vsh_areValidDimensions` |

In C++, helper names live in the `vsh::` namespace without the C `vsh_`
prefix.

## Logging and Core Changes

| API3 | API4 |
| --- | --- |
| `logMessage(type, msg)` | `logMessage(type, msg, core)` |
| `addMessageHandler` | `addLogHandler` |
| `removeMessageHandler(int id)` | `removeLogHandler(VSLogHandle *handle, core)` |
| `createCore(int threads)` | `createCore(int flags)` |

Do not migrate numeric message severity constants by value. API4 adds
`mtInformation`, shifting warning and higher numeric values.

Message handlers are per-core in API4, not global. Direct core/VSScript users
may need to install a handler because there is no default stderr handler when no
handler is installed.

## Frame Property Range Change

API 4.2 introduced `_Range` and deprecated `_ColorRange`.

- `_ColorRange`: full = `0`, limited = `1`.
- `_Range`: full = `1`, limited = `0`.

Do not mechanically rename `_ColorRange` to `_Range` without flipping values.
Base API4 migrations can defer this unless the project opts into API 4.2 or
uses `VS_USE_LATEST_API`.

## Manual Review Triggers

Stop and reason carefully when these appear:

- `arFrameReady` or `queryCompletedFrame`
- `paTouch`
- `propSetData`
- `_ColorRange`
- `cmYCoCg`, `cmCompat`, `pfCompat*`
- numeric `pf*` or `VSFormat.id` comparisons
- custom cache flags or `nfMakeLinear`
- plugins that create their own `VSCore`
- source filters, stateful filters, file readers, or non-video filters
- C++ wrappers around the C API
- plugin loaders that add functions after initialization
- map keys that may mix audio and video node/frame values
- old core plugin lookups such as `getPluginById` and `getPluginByNs`
- integer scaling, rounding, or SIMD changes mixed into an upstream API4
  migration commit

## Evidence From R73/R77 Research

- R73 still says general API3 plugin support remains "for now", while API R3
  headers are no longer distributed with Windows binaries.
- R73 includes `APIV4 changes.txt`, an official migration note covering header
  renames, value-style video formats, `VapourSynthPluginInit2`, `map*`
  property APIs, `createVideoFilter`, `frameData` scratch space, audio support,
  per-core message handlers, and helper renames.
- R77 source still contains an API3 compatibility path, but it logs a
  deprecation warning when loading API3 plugins.
- R77 SDK examples use `VapourSynth4.h`, `VSHelper4.h`,
  `VapourSynthPluginInit2`, `VSPLUGINAPI`, `map*`, and `createVideoFilter`.
