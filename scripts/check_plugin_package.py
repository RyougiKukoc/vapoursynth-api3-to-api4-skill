#!/usr/bin/env python3
"""Check a packaged VapourSynth plugin directory or zip artifact."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PackageView:
    source: Path
    names: list[str]
    reader: object
    original_names: dict[str, str]

    def read_text(self, name: str) -> str:
        name = normalize_name(name)
        if isinstance(self.reader, zipfile.ZipFile):
            return self.reader.read(self.original_names[name]).decode("utf-8-sig", errors="replace")
        return (self.source / name).read_text(encoding="utf-8-sig", errors="replace")

    def close(self) -> None:
        if isinstance(self.reader, zipfile.ZipFile):
            self.reader.close()


def normalize_name(name: str) -> str:
    name = name.replace("\\", "/").strip()
    while name.startswith("./"):
        name = name[2:]
    while name.startswith("/"):
        name = name[1:]
    return "/".join(part for part in name.split("/") if part and part != ".")


def open_package(path: Path) -> PackageView:
    if path.is_dir():
        names = sorted(normalize_name(p.relative_to(path).as_posix()) for p in path.rglob("*") if p.is_file())
        return PackageView(path.resolve(), names, None, {name: name for name in names})
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        original_names: dict[str, str] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            normalized = normalize_name(info.filename)
            if normalized and normalized not in original_names:
                original_names[normalized] = info.filename
        return PackageView(path.resolve(), sorted(original_names), zf, original_names)
    raise FileNotFoundError(f"not a directory or zip file: {path}")


def parent_dir_for(names: list[str], filename: str) -> set[str]:
    filename = normalize_name(filename).strip("/")
    parents: set[str] = set()
    for name in names:
        if name == filename:
            parents.add("")
        elif name.endswith(f"/{filename}"):
            parents.add(name[: -(len(filename) + 1)])
    return parents


def infer_package_dir(names: list[str], plugin_dll: str, manifest: str) -> str:
    plugin_dirs = parent_dir_for(names, plugin_dll)
    manifest_dirs = parent_dir_for(names, manifest)
    common_dirs = plugin_dirs & manifest_dirs
    if len(common_dirs) == 1:
        return next(iter(common_dirs))
    if len(plugin_dirs) == 1 and not manifest_dirs:
        return next(iter(plugin_dirs))

    top_files = [name for name in names if "/" not in name]
    top_dirs = sorted({name.split("/", 1)[0] for name in names if "/" in name})
    if len(top_dirs) == 1 and not top_files:
        return top_dirs[0]
    if plugin_dll in names or manifest in names:
        return ""
    raise RuntimeError("could not infer package directory; pass --package-dir")


def package_prefix(package_dir: str) -> str:
    package_dir = normalize_name(package_dir).strip("/")
    return f"{package_dir}/" if package_dir else ""


def rel_path(prefix: str, name: str) -> str:
    return name[len(prefix) :] if prefix else name


def manifest_plugins(text: str) -> list[str]:
    plugins = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        plugins.append(line)
    return plugins


def validate_package(view: PackageView, args: argparse.Namespace) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    names = view.names
    if not names:
        errors.append("package is empty")
        package_dir = normalize_name(args.package_dir or "").strip("/")
        prefix = package_prefix(package_dir)
        package_files: list[str] = []
    else:
        package_dir = normalize_name(args.package_dir).strip("/") if args.package_dir else infer_package_dir(names, args.plugin_dll, args.manifest)
        prefix = package_prefix(package_dir)
        package_files = [name for name in names if name.startswith(prefix)]

    if args.require_top_level_dir and not package_dir:
        errors.append("artifact does not preserve a top-level package directory")

    if args.forbid_vapoursynth_prefix and package_dir.lower().startswith("vapoursynth/"):
        errors.append(f"artifact has redundant VapourSynth install prefix: {package_dir}")

    if args.require_top_level_dir and package_dir:
        outside = [name for name in names if not name.startswith(prefix)]
        if outside:
            errors.append("files outside package directory: " + ", ".join(outside[:10]))

    rel_files = {rel_path(prefix, name) for name in package_files}
    plugin_dll = normalize_name(args.plugin_dll).strip("/")
    manifest = normalize_name(args.manifest).strip("/")
    required = [normalize_name(item).strip("/") for item in args.required]

    if plugin_dll not in rel_files:
        errors.append(f"missing plugin DLL: {prefix}{plugin_dll}")
    for item in required:
        if item not in rel_files:
            errors.append(f"missing required file: {prefix}{item}")

    dlls = sorted(name for name in rel_files if name.lower().endswith(".dll"))
    manifest_plugins_found: list[str] = []
    if len(dlls) > 1 and manifest not in rel_files and not args.require_manifest:
        warnings.append("package contains multiple DLLs but no manifest.vs")

    if args.require_manifest or manifest in rel_files:
        if manifest not in rel_files:
            errors.append(f"missing manifest: {prefix}{manifest}")
        else:
            manifest_name = prefix + manifest
            text = view.read_text(manifest_name)
            if "[VapourSynth Manifest V1]" not in text:
                errors.append(f"manifest missing VapourSynth Manifest V1 header: {manifest_name}")
            plugin_base = Path(plugin_dll).stem
            manifest_plugins_found = manifest_plugins(text)
            if plugin_base not in manifest_plugins_found:
                errors.append(f"manifest does not list plugin base name {plugin_base!r}: {manifest_name}")

    return {
        "source": str(view.source),
        "package_dir": package_dir or ".",
        "files": sorted(package_files),
        "file_count": len(package_files),
        "plugin_dll": plugin_dll,
        "required": required,
        "manifest": manifest,
        "manifest_plugins": manifest_plugins_found,
        "warnings": warnings,
        "errors": errors,
        "ok": not errors,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate a VapourSynth plugin package directory or zip.")
    parser.add_argument("path", help="Extracted artifact directory, plugin package directory, or zip file.")
    parser.add_argument("--package-dir", help="Top-level plugin directory name inside the artifact, such as nnedi3cl.")
    parser.add_argument("--plugin-dll", required=True, help="Plugin DLL filename relative to the package directory.")
    parser.add_argument("--required", action="append", default=[], help="Required file relative to the package directory. May be repeated.")
    parser.add_argument("--manifest", default="manifest.vs", help="Manifest filename relative to the package directory.")
    parser.add_argument("--require-manifest", action="store_true", help="Require and validate manifest.vs.")
    parser.add_argument("--require-top-level-dir", action="store_true", help="Require every file to live under the package directory.")
    parser.add_argument("--forbid-vapoursynth-prefix", action="store_true", help="Reject artifacts rooted at vapoursynth/plugins/...")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON result.")
    args = parser.parse_args(argv)

    view = open_package(Path(args.path))
    try:
        result = validate_package(view, args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"source={result['source']}")
            print(f"package_dir={result['package_dir']}")
            print(f"files={result['file_count']}")
            for name in result["files"]:
                print(name)

        if not args.json:
            for warning in result["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
            for error in result["errors"]:
                print(f"error: {error}", file=sys.stderr)
        return 0 if result["ok"] else 1
    finally:
        view.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
