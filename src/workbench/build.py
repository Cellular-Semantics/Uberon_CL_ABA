"""Build KBs: one merged .ofn per KB from cached per-checkout import closures.

Everything fed to the reasoner is OWL functional syntax written by OWLAPI; nothing
goes through an OWL -> RDF -> OWL round trip.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import ofn
from .config import KB, Config, Part, digest
from .sources import fingerprint
from .tools import robot

CAT_NS = "urn:oasis:names:tc:entity:xmlns:xml:catalog"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


def kb_dir(cfg: Config) -> Path:
    return cfg.root / "build" / "kbs"


def direct_imports(edit: Path) -> list[str]:
    text = edit.read_text(errors="replace")
    if edit.suffix == ".obo":
        return re.findall(r"^import:\s*(\S+)", text, re.M)
    return (re.findall(r"^Import\(<([^>]+)>\)", text, re.M)
            or re.findall(r'owl:imports rdf:resource="([^"]+)"', text))


def read_catalog(path: Path) -> dict[str, Path]:
    """Catalog name -> absolute file path."""
    out = {}

    def walk(el, base: Path):
        base = base / el.get(XML_BASE) if el.get(XML_BASE) else base
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == "uri" and child.get("name") and child.get("uri"):
                u = child.get("uri").removeprefix("file:")
                out[child.get("name")] = (base / u).resolve()
            elif tag == "group":
                walk(child, base)

    walk(ET.parse(path).getroot(), path.parent)
    return out


def write_catalog(entries: dict[str, Path], path: Path) -> None:
    ET.register_namespace("", CAT_NS)
    root = ET.Element(f"{{{CAT_NS}}}catalog", {"prefer": "public"})
    for name, p in sorted(entries.items()):
        ET.SubElement(root, f"{{{CAT_NS}}}uri", {"name": name, "uri": str(p)})
    ET.ElementTree(root).write(path, xml_declaration=True, encoding="UTF-8")


def part_stamp(cfg: Config, part: Part) -> dict:
    if part.checkout:
        src = cfg.sources[part.source]
        return {"source": part.source, "checkout": part.checkout.name, "edit": src.edit,
                "filter_dirs": src.filter_dirs, "drop": part.drop_import_subjects,
                **fingerprint(src, part.checkout)}
    if part.file:
        return {"file": str(part.file), "sha": hashlib.sha256(part.file.read_bytes()).hexdigest()[:16]}
    return {"url": part.url}  # fetched once; `wb build --force` refetches


def part_path(cfg: Config, part: Part) -> Path:
    d = cfg.root / "build" / "parts"
    if part.checkout:
        tag = digest(part.drop_import_subjects)[:8]
        return d / f"{part.source}__{part.checkout.name}__{tag}.ofn"
    if part.file:
        return d / f"file__{part.file.stem}__{digest(str(part.file))[:8]}.ofn"
    return d / f"url__{digest(part.url)[:8]}.ofn"


def build_part(cfg: Config, part: Part, log, force=False) -> tuple[Path, dict]:
    out = part_path(cfg, part)
    stamp_file = out.with_suffix(".stamp.json")
    stamp = part_stamp(cfg, part)
    if (not force and out.exists() and stamp_file.exists()
            and json.loads(stamp_file.read_text()) == stamp):
        print(f"   part {part.label()}: up to date")
        return out, stamp
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.mkdir(exist_ok=True)
    t0 = time.time()
    if part.checkout:
        _build_checkout_part(cfg, part, tmp, log)
    elif part.file:
        robot(cfg, "convert", "-i", part.file, "-o", tmp / "part.ofn", log=log)
    else:
        robot(cfg, "convert", "-I", part.url, "-o", tmp / "part.ofn", log=log)
    (tmp / "part.ofn").replace(out)
    shutil.rmtree(tmp)
    stamp_file.write_text(json.dumps(stamp, indent=1))
    print(f"   part {part.label()}: built in {time.time() - t0:.0f}s")
    return out, stamp


def _build_checkout_part(cfg: Config, part: Part, tmp: Path, log) -> None:
    src = cfg.sources[part.source]
    co = part.checkout
    edit = co.path / src.edit
    ont_dir = edit.parent
    if not edit.exists():
        raise RuntimeError(f"{edit} missing")
    catalog = co.path / src.catalog if src.catalog else None
    entries = read_catalog(catalog) if catalog and catalog.exists() else {}
    # ODK placeholders can be committed as 0-byte files (e.g. MBA's merged_import.owl),
    # which OWLAPI can't parse: stand in an empty ontology with the expected IRI.
    for i, (iri, p) in enumerate(list(entries.items())):
        if p.exists() and p.stat().st_size == 0:
            stub = tmp / f"empty-{i}.ofn"
            stub.write_text(f"Ontology(<{iri}>\n)\n")
            entries[iri] = stub
    if part.drop_import_subjects:
        filter_roots = [(ont_dir / d).resolve() for d in src.filter_dirs]
        for iri in direct_imports(edit):
            p = entries.get(iri)
            if not p or not p.exists() or not any(p.is_relative_to(r) for r in filter_roots):
                continue
            conv = tmp / (p.stem + ".ofn")
            filt = tmp / (p.stem + ".filtered.ofn")
            robot(cfg, "convert", "-i", p, "-o", conv, log=log)
            dropped, kept = ofn.drop_subjects(conv, filt, part.drop_import_subjects)
            conv.unlink()
            msg = (f"   {part.label()}: {p.relative_to(ont_dir)}: dropped {dropped} axioms about "
                   f"{', '.join(x.rsplit('/', 1)[-1] for x in part.drop_import_subjects)}*; "
                   f"kept {kept}")
            print(msg)
            log.write(msg + "\n")
            entries[iri] = filt
    cat = tmp / "catalog.xml"
    write_catalog(entries, cat)
    robot(cfg, "merge", "--catalog", cat, "-i", edit, "-o", tmp / "part.ofn", log=log)


def kb_stamp(kb: KB, part_stamps: list[dict]) -> str:
    return digest(kb.name, part_stamps)


def build_kb(cfg: Config, kb: KB, force=False) -> bool:
    """Returns True if the KB file changed."""
    out_dir = kb_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs = cfg.root / "build" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{kb.name}.ofn"
    manifest = out_dir / f"{kb.name}.json"
    print(f"== KB {kb.name}: " + " + ".join(p.label() for p in kb.parts))
    with open(logs / f"{kb.name}.log", "a") as log:
        log.write(f"\n==== {time.ctime()} build {kb.name}\n")
        log.flush()
        built = [build_part(cfg, p, log, force) for p in kb.parts]
        stamps = [s for _, s in built]
        key = kb_stamp(kb, stamps)
        if not force and out.exists() and manifest.exists() and \
                json.loads(manifest.read_text()).get("key") == key:
            print("   up to date")
            return False
        t0 = time.time()
        tmp = out.with_suffix(".tmp.ofn")
        args = []
        for p, _ in built:
            args += ["-i", p]
        robot(cfg, "merge", *args, "annotate", "--ontology-iri",
              f"http://example.org/workbench/{kb.name}.owl", "-o", tmp, log=log)
        tmp.replace(out)
    lab = ofn.labels(out)
    with open(out_dir / f"{kb.name}.labels.tsv", "w") as f:
        for iri, l in sorted(lab.items()):
            f.write(f"{iri}\t{l}\n")
    manifest.write_text(json.dumps({"kb": kb.name, "key": key, "built": time.ctime(),
                                    "parts": stamps}, indent=1))
    print(f"   merged in {time.time() - t0:.0f}s -> {out} ({out.stat().st_size >> 20} MB)")
    return True


def stale(cfg: Config, kb: KB) -> bool:
    """Cheap check (no ROBOT) whether a KB's inputs have changed since it was built."""
    manifest = kb_dir(cfg) / f"{kb.name}.json"
    if not manifest.exists():
        return True
    try:
        stamps = [part_stamp(cfg, p) for p in kb.parts]
    except Exception:
        return True
    return json.loads(manifest.read_text()).get("key") != kb_stamp(kb, stamps)


def clean_orphans(cfg: Config) -> list[str]:
    names = {k.name for k in cfg.kbs}
    removed = []
    for f in kb_dir(cfg).glob("*.json") if kb_dir(cfg).exists() else []:
        n = f.name.removesuffix(".json")
        if n not in names:
            for ext in (".ofn", ".json", ".labels.tsv"):
                (kb_dir(cfg) / f"{n}{ext}").unlink(missing_ok=True)
            removed.append(n)
    return removed
