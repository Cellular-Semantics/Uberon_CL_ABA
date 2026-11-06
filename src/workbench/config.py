"""Load workbench.yaml (+ workbench.local.yaml) and expand it into checkouts and KBs."""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import itertools
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

OBO = "http://purl.obolibrary.org/obo/"


def find_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        if (d / "workbench.yaml").exists():
            return d
    raise SystemExit("workbench.yaml not found in this directory or any parent")


def deep_merge(base, over, path=()):
    """Merge workbench.local.yaml (`over`) onto workbench.yaml (`base`).

    Dicts merge recursively. Two lists extend rather than replace, so local branches
    and KBs add to the shared set-up: `sources.<src>.checkouts` (keyed by checkout
    name) and `kbs` (keyed by `name`; a same-name entry is merged over the shared one).
    Every other list, and a non-list on either side (`checkouts: auto`), replaces.
    """
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base.get(k), v, path + (k,)) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list):
        if path == ("kbs",):
            return merge_keyed(base, over, lambda r: r.get("name"), path)
        if len(path) == 3 and path[0] == "sources" and path[2] == "checkouts":
            return merge_keyed(base, over, checkout_key, path)
    return copy.deepcopy(over)


def merge_keyed(base: list, over: list, key, path) -> list:
    out = copy.deepcopy(base)
    index = {key(x): i for i, x in enumerate(out)}
    for x in over:
        k = key(x)
        if k in index:
            i = index[k]
            both_dicts = isinstance(out[i], dict) and isinstance(x, dict)
            out[i] = deep_merge(out[i], x, path + ("*",)) if both_dicts else copy.deepcopy(x)
        else:
            index[k] = len(out)
            out.append(copy.deepcopy(x))
    return out


def checkout_key(spec) -> str:
    """The checkout name a `checkouts:` entry produces (see Source.resolve_checkouts)."""
    if isinstance(spec, dict):
        pr = spec.get("pr")
        return safe_name(str(spec.get("name") or (f"pr-{pr}" if pr is not None else spec.get("branch"))))
    return safe_name(str(spec))


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


@dataclass
class Checkout:
    source: str
    name: str            # used in KB names and as the worktree folder name
    path: Path
    branch: str | None = None
    pr: int | None = None
    managed: bool = True  # False: an existing worktree we only read


@dataclass
class Source:
    name: str
    repo: str | None
    edit: str
    catalog: str
    sync: str
    path: Path | None          # existing clone (unmanaged)
    checkout_specs: list | str
    filter_dirs: list[str]
    root: Path
    checkouts: list[Checkout] = field(default_factory=list)

    @property
    def managed(self) -> bool:
        return self.path is None

    @property
    def clone_dir(self) -> Path:
        return self.path if self.path else self.root / "sources" / self.name / ".repo"

    def resolve_checkouts(self) -> list[Checkout]:
        specs = self.checkout_specs
        if self.managed:
            out = []
            for spec in specs or []:
                if isinstance(spec, (str, int)):
                    spec = {"branch": str(spec)}
                branch = spec.get("branch")
                pr = spec.get("pr")
                if not branch and pr is None:
                    raise SystemExit(f"sources.{self.name}: checkout needs branch or pr: {spec}")
                name = safe_name(spec.get("name") or (f"pr-{pr}" if pr is not None else branch))
                out.append(Checkout(self.name, name, self.root / "sources" / self.name / name,
                                    branch=branch, pr=pr))
            return out
        # Existing clone: use its worktrees.
        found = list_worktrees(self.path)
        if specs in (None, "auto"):
            return found
        wanted = [str(s if not isinstance(s, dict) else s.get("name") or s.get("branch")) for s in specs]
        by_name = {c.name: c for c in found}
        missing = [w for w in wanted if safe_name(w) not in by_name]
        if missing:
            raise SystemExit(f"sources.{self.name}: no worktree of {self.path} on {missing}; "
                             f"have {sorted(by_name)}")
        return [by_name[safe_name(w)] for w in wanted]


def list_worktrees(repo: Path) -> list[Checkout]:
    try:
        out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"{repo}: not a git checkout ({e.stderr.strip()})")
    res, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur.get("worktree") and "bare" not in cur:
                p = Path(cur["worktree"])
                br = cur.get("branch", "").removeprefix("refs/heads/") or None
                res.append(Checkout("", safe_name(br or p.name), p, branch=br, managed=False))
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    return res


@dataclass
class Part:
    source: str | None = None
    checkout: Checkout | None = None
    file: Path | None = None
    url: str | None = None
    drop_import_subjects: list[str] = field(default_factory=list)

    def label(self) -> str:
        if self.checkout:
            return f"{self.source}@{self.checkout.name}"
        return str(self.file or self.url)


@dataclass
class KB:
    name: str
    parts: list[Part]
    heap: str
    recipe: dict   # the raw recipe, for the build fingerprint


@dataclass
class Config:
    root: Path
    raw: dict
    sources: dict[str, Source]
    kbs: list[KB]

    @property
    def tools(self) -> dict:
        return self.raw.get("tools", {})

    @property
    def serve(self) -> dict:
        return self.raw.get("serve", {})

    @property
    def prefixes(self) -> dict[str, str]:
        """Non-OBO CURIE prefixes, e.g. MBA -> https://purl.brain-bican.org/ontology/mbao/MBA_"""
        return self.raw.get("prefixes") or {}

    def kb(self, name: str) -> KB:
        for k in self.kbs:
            if k.name == name:
                return k
        raise SystemExit(f"no KB {name!r}; `wb kbs` lists them")

    def select_kbs(self, patterns: list[str] | str | None) -> list[KB]:
        if not patterns or patterns == "*":
            return list(self.kbs)
        if isinstance(patterns, str):
            patterns = [patterns]
        sel = [k for k in self.kbs if any(fnmatch.fnmatchcase(k.name, p) for p in patterns)]
        if not sel:
            raise SystemExit(f"no KB matches {patterns}; `wb kbs` lists them")
        return sel


def prefix_iri(p: str, prefixes: dict[str, str] | None = None) -> str:
    if "://" in p:
        return p
    p = p.rstrip("_:")
    return (prefixes or {}).get(p) or f"{OBO}{p}_"


def load(root: Path | None = None) -> Config:
    root = root or find_root()
    raw = yaml.safe_load((root / "workbench.yaml").read_text()) or {}
    local = root / "workbench.local.yaml"
    if local.exists():
        raw = deep_merge(raw, yaml.safe_load(local.read_text()) or {})

    sources = {}
    for name, s in (raw.get("sources") or {}).items():
        path = Path(s["path"]).expanduser().resolve() if s.get("path") else None
        src = Source(
            name=name, repo=s.get("repo"), edit=s["edit"], catalog=s.get("catalog", ""),
            sync=s.get("sync", "none" if path else "ff"), path=path,
            checkout_specs=s.get("checkouts", "auto" if path else ["master"]),
            filter_dirs=s.get("filter_dirs", ["imports"]), root=root)
        if not path and not src.repo:
            raise SystemExit(f"sources.{name}: needs `repo` or `path`")
        src.checkouts = src.resolve_checkouts()
        for c in src.checkouts:
            c.source = name
        sources[name] = src

    serve = raw.get("serve", {})
    kbs = []
    for recipe in raw.get("kbs") or []:
        if recipe.get("enabled", True) is False:
            continue
        kbs.extend(expand_kb(recipe, sources, root, serve.get("heap", "6G"),
                             raw.get("prefixes") or {}))
    names = [k.name for k in kbs]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise SystemExit(f"duplicate KB names after expansion: {sorted(dup)}")
    return Config(root, raw, sources, kbs)


def expand_kb(recipe: dict, sources: dict[str, Source], root: Path, default_heap: str,
              prefixes: dict[str, str] | None = None) -> list[KB]:
    part_specs = recipe["parts"]
    used = []
    for p in part_specs:
        if "source" in p:
            if p["source"] not in sources:
                raise SystemExit(f"KB {recipe['name']}: unknown source {p['source']!r}")
            if p["source"] not in used:
                used.append(p["source"])
    matrix = recipe.get("matrix") or {}
    axes = []
    for s in used:
        sel = matrix.get(s, "*")
        cos = sources[s].checkouts
        if sel != "*":
            sel = [safe_name(str(x)) for x in ([sel] if isinstance(sel, str) else sel)]
            cos = [c for c in cos if any(fnmatch.fnmatchcase(c.name, x) for x in sel)]
        axes.append(cos)
    out = []
    for combo in itertools.product(*axes):
        chosen = dict(zip(used, combo))
        name = recipe["name"].format(**{s: c.name for s, c in chosen.items()})
        parts = []
        for p in part_specs:
            drop = [prefix_iri(x, prefixes) for x in p.get("drop_import_subjects", [])]
            if "source" in p:
                parts.append(Part(source=p["source"], checkout=chosen[p["source"]],
                                  drop_import_subjects=drop))
            elif "file" in p:
                parts.append(Part(file=(root / p["file"]).resolve()))
            elif "url" in p:
                parts.append(Part(url=p["url"]))
            else:
                raise SystemExit(f"KB {recipe['name']}: part needs source, file or url: {p}")
        out.append(KB(safe_name(name), parts, recipe.get("heap", default_heap), recipe))
    return out


def digest(*items) -> str:
    h = hashlib.sha256()
    for it in items:
        h.update(json.dumps(it, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]
