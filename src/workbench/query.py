"""DL queries against served KBs with CURIEs and 'labels' instead of full IRIs."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .build import kb_dir
from .config import OBO, Config

SPECIAL = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
}
ENDPOINT = {"sub": "subclasses", "super": "superclasses", "equiv": "equivalent",
            "inst": "instances"}

_labels_cache: dict[str, dict] = {}


def labels(cfg: Config, kb: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    if kb not in _labels_cache:
        iri2l, l2iri = {}, {}
        f = kb_dir(cfg) / f"{kb}.labels.tsv"
        if f.exists():
            for line in f.read_text().splitlines():
                iri, _, lab = line.partition("\t")
                iri2l[iri] = lab
                l2iri.setdefault(lab.lower(), []).append(iri)
        _labels_cache[kb] = (iri2l, l2iri)
    return _labels_cache[kb]


def curie_to_iri(prefix: str, local: str, extra: dict[str, str] | None = None) -> str:
    ns = {**(extra or {}), **SPECIAL}.get(prefix)
    return ns + local if ns else f"{OBO}{prefix}_{local}"


def iri_to_curie(iri: str, extra: dict[str, str] | None = None) -> str:
    for p, ns in {**SPECIAL, **(extra or {})}.items():
        if iri.startswith(ns):
            return f"{p}:{iri[len(ns):]}"
    if iri.startswith(OBO):
        local = iri[len(OBO):]
        if "_" in local:
            p, _, rest = local.partition("_")
            return f"{p}:{rest}"
    return f"<{iri}>"


_CURIE = re.compile(r"(?<![\w/#.:])([A-Za-z][A-Za-z0-9]*):([A-Za-z0-9_]+)")


def expand(cfg: Config, kb: str, expr: str) -> str:
    """Manchester expression with 'quoted labels' and CURIEs -> full IRIs."""
    _, l2iri = labels(cfg, kb)

    def lab(m):
        hits = l2iri.get(m.group(1).lower())
        if not hits:
            raise SystemExit(f"no class labelled {m.group(1)!r} in {kb}")
        if len(set(hits)) > 1:  # e.g. Uberon vs Allen atlas classes: prefer the OBO one
            obo = sorted({h for h in hits if h.startswith(OBO)})
            if len(obo) == 1:
                return f"<{obo[0]}>"
            raise SystemExit(f"label {m.group(1)!r} is ambiguous in {kb}: "
                             + ", ".join(iri_to_curie(h, cfg.prefixes) for h in hits))
        return f"<{hits[0]}>"

    out = []
    for seg in re.split(r"(<[^>]*>|'[^']*')", expr):
        if seg.startswith("<"):
            out.append(seg)
        elif seg.startswith("'"):
            out.append(lab(re.match(r"'([^']*)'", seg)))
        else:
            out.append(_CURIE.sub(lambda m: f"<{curie_to_iri(*m.groups(), cfg.prefixes)}>", seg))
    return "".join(out)


def base_url(cfg: Config) -> str:
    return f"http://localhost:{cfg.serve.get('port', 8090)}"


def ask(cfg: Config, kb: str, kind: str, expr: str, direct: bool = False) -> list[str]:
    q = urllib.parse.urlencode({"object": expand(cfg, kb, expr),
                                "direct": str(direct).lower()})
    url = f"{base_url(cfg)}/kbs/{urllib.parse.quote(kb)}/{ENDPOINT[kind]}?{q}"
    try:
        with urllib.request.urlopen(url, timeout=None) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{e.code} from {kb}: {e.read().decode(errors='replace')[:500]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {base_url(cfg)} ({e.reason}); is `wb serve` running?")
    # Owlery answers with JSON-LD: {"@id": expr, "<relation>": [iris]}.
    res = []
    for k, v in data.items():
        if k.startswith("@"):
            continue
        res.extend(v if isinstance(v, list) else [v])
    return sorted(set(res))


def render(cfg: Config, kb: str, iris: list[str]) -> list[str]:
    iri2l, _ = labels(cfg, kb)
    return [f"{iri_to_curie(i, cfg.prefixes)}\t{iri2l.get(i, '')}" for i in iris]
