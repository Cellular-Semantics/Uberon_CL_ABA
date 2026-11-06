---
name: reasoner-check
description: Check how a CL, Uberon or MBA edit (or a patch) changes classification, using the workbench's Owlery KBs. Use before and after editing cl-edit.owl / uberon-edit.obo / MBA templates, when asked where a class classifies, or to compare branches.
---

# Reasoner check

1. `uv run wb status` shows which KBs are built and served. If the KB you need is
   missing, `uv run wb build KB` and then `uv run wb serve KB`.
2. Pick the KB:
   - anything that involves both ontologies → `cl-<branch>__uberon-<branch>`
   - anything involving MBA atlas structures → `mba-<branch>__cl-<branch>__uberon-<branch>`
     (or `mba-…__uberon-…` if CL is not involved)
   - baseline → the same recipe built from master checkouts
3. Write the query in Manchester syntax with CURIEs or quoted labels:
   - `uv run wb q KB "'GABAergic neuron' and (RO:0002100 some UBERON:0002037)" --direct`
   - `--super` for where a class or expression classifies, `--equiv` for equivalents
4. Before/after: `uv run wb compare KB_BASE KB_NEW EXPR [--super] [--direct]`.
5. Always finish with `uv run wb unsat KB`. Report unsatisfiable classes with their
   labels, and say whether they are new compared with the baseline KB.

Useful relations: RO:0002100 has soma location, BFO:0000050 part of, RO:0002215
capable of, RO:0002162 in taxon. MBA classes are `MBA:<Allen structure id>`; use the CURIE, since
MBA labels are often shared with Uberon or other atlases. For a CL release problem
involving MBA, check `mbao-release__cl-…__uberon-…` (the published MBAO, as CL imports it).

Report the exact queries and the KBs they ran on (with `build/kbs/<kb>.json` commits
if provenance matters), so the result can be reproduced.
