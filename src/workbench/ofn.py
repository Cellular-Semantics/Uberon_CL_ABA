"""Line-level operations on OWLAPI-written OWL functional syntax (one axiom per line)."""
from __future__ import annotations

import re
from pathlib import Path

_PREFIX = re.compile(r"^Prefix\((\w*):=<(.*)>\)$")
_AXIOM = re.compile(r"^(\w+)\((.*)\)$")
_SKIP = ("Prefix", "Ontology", "Declaration", "Import")


def _strip_annotations(body: str) -> str:
    while body.startswith("Annotation("):
        depth, in_str, i = 0, False, 0
        for i, c in enumerate(body):
            if c == '"' and body[i - 1] != "\\":
                in_str = not in_str
            elif not in_str and c == "(":
                depth += 1
            elif not in_str and c == ")":
                depth -= 1
                if depth == 0:
                    break
        body = body[i + 1:].lstrip()
    return body


def _expand(tok: str, prefixes: dict) -> str:
    if tok.startswith("<"):
        return tok[1:-1]
    if ":" in tok:
        p, local = tok.split(":", 1)
        return prefixes.get(p, p + ":") + local
    return tok


def axiom_subject(line: str, prefixes: dict) -> str | None:
    """Subject IRI of an axiom line: first operand of a class/property axiom, or the
    annotated entity of an AnnotationAssertion. None for non-axiom lines."""
    m = _AXIOM.match(line.rstrip("\n"))
    if not m or m.group(1) in _SKIP:
        return None
    kind, body = m.groups()
    toks = _strip_annotations(body).split(" ")
    subj = toks[1] if kind == "AnnotationAssertion" and len(toks) > 1 else toks[0]
    return _expand(subj, prefixes)


def drop_subjects(in_path: Path, out_path: Path, iri_prefixes: list[str]) -> tuple[int, int]:
    """Copy an .ofn, dropping axioms whose subject IRI starts with any of the prefixes.
    Axioms that merely mention such terms (e.g. GO 'occurs in' some UBERON_x, or a GCI)
    are kept, as are declarations."""
    prefixes, dropped, kept = {}, 0, 0
    pfx = tuple(iri_prefixes)
    with open(in_path) as f, open(out_path, "w") as out:
        for line in f:
            m = _PREFIX.match(line)
            if m:
                prefixes[m.group(1)] = m.group(2)
            subj = axiom_subject(line, prefixes)
            if subj is not None:
                if subj.startswith(pfx):
                    dropped += 1
                    continue
                kept += 1
            out.write(line)
    return dropped, kept


_LABEL = re.compile(r'^AnnotationAssertion\((?:Annotation\(.*?\) )*rdfs:label (\S+) "((?:[^"\\]|\\.)*)"')


def labels(path: Path) -> dict[str, str]:
    """IRI -> rdfs:label (first one seen) from an .ofn."""
    prefixes, out = {}, {}
    with open(path) as f:
        for line in f:
            m = _PREFIX.match(line)
            if m:
                prefixes[m.group(1)] = m.group(2)
                continue
            if not line.startswith("AnnotationAssertion("):
                continue
            m = _LABEL.match(line)
            if m:
                iri = _expand(m.group(1), prefixes)
                out.setdefault(iri, m.group(2).replace('\\"', '"'))
    return out
