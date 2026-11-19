#!/usr/bin/env python3
"""Deterministic Cargo workspace and Maven reactor adapter for drift.build-graph/1 (D412)."""

from __future__ import annotations

import sys
if sys.version_info < (3, 11):
    sys.stderr.write(f"drift_build_graph: Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})\n")
    sys.exit(2)

import argparse
import hashlib
import json
import os
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from typing import Any

SCHEMA = "drift.build-graph/1"
_CARGO_META_ONLY_PKG_KEYS = frozenset((
    "version",
    "description",
    "authors",
    "readme",
    "homepage",
    "repository",
    "documentation",
    "keywords",
    "categories",
    "license",
    "license-file",
    "publish",
    "metadata",
    "default-run",
))
_MAVEN_META_ONLY_TAGS = frozenset((
    "name",
    "description",
    "url",
    "inceptionYear",
    "organization",
    "licenses",
    "developers",
    "contributors",
    "mailingLists",
    "scm",
    "issueManagement",
    "ciManagement",
    "distributionManagement",
))
_PROP_RE = re.compile(r"\$\{([^}]+)\}")


def _sha256_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rel_posix(target: Path, root: Path) -> str:
    return target.resolve().relative_to(root.resolve()).as_posix()


def _cargo_manifest_build_fingerprint(manifest_path: Path) -> tuple[str, bool]:
    raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    pkg = raw.get("package") if isinstance(raw.get("package"), dict) else {}
    pkg_build = {k: v for k, v in pkg.items() if k not in _CARGO_META_ONLY_PKG_KEYS}
    has_links = bool(pkg.get("links"))
    relevant = {
        "package": pkg_build,
        "features": raw.get("features", {}),
        "dependencies": raw.get("dependencies", {}),
        "dev-dependencies": raw.get("dev-dependencies", {}),
        "build-dependencies": raw.get("build-dependencies", {}),
        "target": raw.get("target", {}),
        "lib": raw.get("lib", {}),
        "bin": raw.get("bin", []),
        "test": raw.get("test", []),
        "lints": raw.get("lints", {}),
    }
    return _sha256_json(relevant), has_links


def build_cargo_graph(ws_root: Path, metadata_json: dict[str, Any] | None = None) -> dict[str, Any]:
    ws_root = ws_root.resolve()
    if metadata_json is None:
        cmd = ["cargo", "metadata", "--format-version", "1", "--manifest-path", str(ws_root / "Cargo.toml")]
        res = subprocess.run(cmd, cwd=ws_root, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"cargo metadata failed: {res.stderr.strip()}")
        metadata_json = json.loads(res.stdout)

    pkgs_by_id: dict[str, dict[str, Any]] = {p["id"]: p for p in metadata_json.get("packages", [])}
    ws_members = set(metadata_json.get("workspace_members", []))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    resolve = metadata_json.get("resolve") or {}
    for node in resolve.get("nodes", []):
        nodes_by_id[node["id"]] = node

    manifests: set[str] = set()
    if (ws_root / "Cargo.toml").is_file():
        manifests.add("Cargo.toml")
    if (ws_root / "Cargo.lock").is_file():
        manifests.add("Cargo.lock")

    modules: dict[str, Any] = {}
    for member_id in sorted(ws_members):
        pkg = pkgs_by_id.get(member_id)
        if not pkg:
            continue
        m_path = Path(pkg["manifest_path"]).resolve()
        if not m_path.is_relative_to(ws_root):
            continue
        rel_m = _rel_posix(m_path, ws_root)
        manifests.add(rel_m)
        pkg_dir = m_path.parent
        rel_dir = _rel_posix(pkg_dir, ws_root)
        code_globs = ["**"] if rel_dir in ("", ".") else [f"{rel_dir}/**"]

        m_ref, self_links = _cargo_manifest_build_fingerprint(m_path)
        pkg_name = str(pkg["name"])
        deps_by_key: dict[tuple[str, str], dict[str, Any]] = {
            (f"{pkg_name}#manifest", "manifest"): {
                "id": f"{pkg_name}#manifest",
                "kind": "manifest",
                "opaque": self_links,
                "version_ref": m_ref,
            }
        }

        direct_ws_deps: set[str] = set()
        direct_node = nodes_by_id.get(member_id, {})
        for d0 in direct_node.get("deps", []):
            d0_id = d0.get("pkg")
            if d0_id and d0_id in ws_members and d0_id != member_id:
                d0_name = str(pkgs_by_id.get(d0_id, {}).get("name") or d0.get("name") or "")
                if d0_name and d0_name != pkg_name:
                    direct_ws_deps.add(d0_name)

        q: deque[str] = deque([member_id])
        visited: set[str] = {member_id}
        while q:
            cur = q.popleft()
            node = nodes_by_id.get(cur)
            if not node:
                continue
            for dep in node.get("deps", []):
                dep_id = dep.get("pkg")
                if not dep_id or dep_id in ws_members:
                    if dep_id and dep_id not in visited:
                        visited.add(dep_id)
                        q.append(dep_id)
                    continue
                dep_pkg = pkgs_by_id.get(dep_id, {})
                dep_name = str(dep_pkg.get("name") or dep.get("name") or dep_id)
                dep_node = nodes_by_id.get(dep_id, {})
                feats = sorted(set(str(f) for f in dep_node.get("features", [])))
                targets = dep_pkg.get("targets", [])
                is_proc = any("proc-macro" in (t.get("kind") or []) for t in targets if isinstance(t, dict))
                kind = "proc-macro" if is_proc else "library"
                is_opaque = bool(dep_pkg.get("links") or dep_name.endswith("-sys"))
                v_ref = _sha256_json({
                    "id": dep_id,
                    "version": dep_pkg.get("version", ""),
                    "source": dep_pkg.get("source"),
                    "features": feats,
                })
                key = (dep_name, kind)
                prev = deps_by_key.get(key)
                if prev is None:
                    deps_by_key[key] = {
                        "id": dep_name,
                        "kind": kind,
                        "opaque": is_opaque,
                        "version_ref": v_ref,
                    }
                else:
                    prev["opaque"] = bool(prev["opaque"] or is_opaque)
                    if v_ref != prev["version_ref"]:
                        prev["version_ref"] = _sha256_json([prev["version_ref"], v_ref])
                if dep_id not in visited:
                    visited.add(dep_id)
                    q.append(dep_id)

        mod_entry: dict[str, Any] = {
            "code": code_globs,
            "deps": [deps_by_key[k] for k in sorted(deps_by_key)],
        }
        if direct_ws_deps:
            mod_entry["module_deps"] = sorted(direct_ws_deps)
        modules[pkg_name] = mod_entry

    return {
        "manifests": sorted(manifests),
        "modules": dict(sorted(modules.items())),
        "schema": SCHEMA,
    }


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _xml_to_data(elem: ET.Element, skip_tags: frozenset[str] = frozenset()) -> Any:
    children = [c for c in elem if _strip_ns(c.tag) not in skip_tags]
    if not children:
        return (elem.text or "").strip()
    grouped: dict[str, list[Any]] = {}
    for ch in children:
        t = _strip_ns(ch.tag)
        grouped.setdefault(t, []).append(_xml_to_data(ch))
    return {k: (v[0] if len(v) == 1 else v) for k, v in sorted(grouped.items())}


def _sub_props(val: str, props: dict[str, str]) -> str:
    return _PROP_RE.sub(lambda m: props.get(m.group(1), m.group(0)), val)


def _parse_pom(pom_path: Path) -> dict[str, Any]:
    root = ET.fromstring(pom_path.read_text(encoding="utf-8"))
    props: dict[str, str] = {}
    mods: list[str] = []
    dep_mgmt: dict[tuple[str, str], str] = {}
    deps: list[dict[str, str]] = []
    group_id = ""
    artifact_id = ""
    parent_group = ""
    parent_ver = ""
    for ch in root:
        t = _strip_ns(ch.tag)
        if t == "groupId":
            group_id = (ch.text or "").strip()
        elif t == "artifactId":
            artifact_id = (ch.text or "").strip()
        elif t == "parent":
            for pc in ch:
                pt = _strip_ns(pc.tag)
                if pt == "groupId":
                    parent_group = (pc.text or "").strip()
                elif pt == "version":
                    parent_ver = (pc.text or "").strip()
        elif t == "properties":
            for pc in ch:
                props[_strip_ns(pc.tag)] = (pc.text or "").strip()
        elif t == "modules":
            for mc in ch:
                if _strip_ns(mc.tag) == "module" and (mc.text or "").strip():
                    mods.append((mc.text or "").strip())
        elif t == "dependencyManagement":
            for dlist in ch:
                if _strip_ns(dlist.tag) == "dependencies":
                    for d in dlist:
                        if _strip_ns(d.tag) == "dependency":
                            dm = {_strip_ns(x.tag): (x.text or "").strip() for x in d}
                            if dm.get("groupId") and dm.get("artifactId") and dm.get("version"):
                                dep_mgmt[(dm["groupId"], dm["artifactId"])] = dm["version"]
        elif t == "dependencies":
            for d in ch:
                if _strip_ns(d.tag) == "dependency":
                    deps.append({_strip_ns(x.tag): (x.text or "").strip() for x in d})
    stripped_build = _xml_to_data(root, _MAVEN_META_ONLY_TAGS | {"version", "modules"})
    return {
        "group_id": group_id or parent_group,
        "artifact_id": artifact_id,
        "parent_version": parent_ver,
        "props": props,
        "modules": mods,
        "dep_mgmt": dep_mgmt,
        "deps": deps,
        "build_fp": _sha256_json(stripped_build),
    }


def build_maven_graph(reactor_root: Path) -> dict[str, Any]:
    reactor_root = reactor_root.resolve()
    root_pom = reactor_root / "pom.xml"
    if not root_pom.is_file():
        raise RuntimeError(f"missing {root_pom}")

    manifests: set[str] = set()
    parsed_poms: list[tuple[Path, dict[str, Any]]] = []
    merged_props: dict[str, str] = {}
    merged_mgmt: dict[tuple[str, str], str] = {}

    def _walk(pom_file: Path) -> None:
        info = _parse_pom(pom_file)
        manifests.add(_rel_posix(pom_file, reactor_root))
        merged_props.update(info["props"])
        merged_mgmt.update(info["dep_mgmt"])
        if not info["modules"]:
            parsed_poms.append((pom_file, info))
        for sub in info["modules"]:
            sub_pom = (pom_file.parent / sub / "pom.xml").resolve()
            if sub_pom.is_file():
                _walk(sub_pom)

    _walk(root_pom)
    reactor_coords = {(info["group_id"], info["artifact_id"]) for _, info in parsed_poms}
    modules_out: dict[str, Any] = {}
    for pom_file, info in parsed_poms:
        mod_id = info["artifact_id"] or pom_file.parent.name
        rel_dir = _rel_posix(pom_file.parent, reactor_root)
        code_globs = ["**"] if rel_dir in ("", ".") else [f"{rel_dir}/**"]
        dep_entries: list[dict[str, Any]] = [{
            "id": f"{mod_id}#pom",
            "kind": "manifest",
            "opaque": False,
            "version_ref": info["build_fp"],
        }]
        mod_deps: set[str] = set()
        for d in info["deps"]:
            g = _sub_props(d.get("groupId", ""), merged_props)
            a = _sub_props(d.get("artifactId", ""), merged_props)
            if not g or not a or (g, a) in reactor_coords:
                if (g, a) in reactor_coords and a != mod_id:
                    mod_deps.add(a)
                continue
            raw_v = d.get("version") or merged_mgmt.get((g, a), "")
            v = _sub_props(raw_v, merged_props)
            scope = d.get("scope", "compile") or "compile"
            coord = f"{g}:{a}"
            opaque = any(tok in a.lower() for tok in ("jni", "native", "-sys"))
            dep_entries.append({
                "id": coord,
                "kind": scope,
                "opaque": opaque,
                "version_ref": _sha256_json({"coord": coord, "version": v, "scope": scope, "classifier": d.get("classifier", "")}),
            })
        dep_entries.sort(key=lambda x: (x["id"], x["kind"]))
        mod_entry: dict[str, Any] = {"code": code_globs, "deps": dep_entries}
        if mod_deps:
            mod_entry["module_deps"] = sorted(mod_deps)
        modules_out[mod_id] = mod_entry

    return {
        "manifests": sorted(manifests),
        "modules": dict(sorted(modules_out.items())),
        "schema": SCHEMA,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift_build_graph.py")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--cargo", help="Cargo workspace root directory")
    grp.add_argument("--maven", help="Maven reactor root directory")
    ap.add_argument("--cargo-metadata", help="Optional precomputed cargo metadata JSON file")
    ap.add_argument("--out", help="Output file path (default: stdout)")
    args = ap.parse_args(argv)

    try:
        if args.cargo:
            meta = json.loads(Path(args.cargo_metadata).read_text(encoding="utf-8")) if args.cargo_metadata else None
            graph = build_cargo_graph(Path(args.cargo), meta)
        else:
            graph = build_maven_graph(Path(args.maven))
    except Exception as exc:
        print(f"drift_build_graph: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(graph, indent=2, sort_keys=True) + "\n"
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
