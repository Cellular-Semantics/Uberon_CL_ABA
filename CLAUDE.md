# CL + Uberon + Allen brain atlas (ABA) workbench

Reasoner-informed co-development of CL, Uberon and the Allen brain atlas ontologies:
Mouse Brain Atlas (MBA), Developing Human Brain Atlas (DHBA) and Harmonized Ontology of
Mammalian Brain Anatomy (HOMBA). README.md has the user guide; this file is for agents
working in the repo.

## Where things are

- `workbench.yaml` (+ `workbench.local.yaml`) declares sources, checkouts, KBs and
  serving. Run `uv run wb kbs` and `uv run wb status` to see the current state; don't
  guess paths.
- Add branch and PR checkouts, and KBs specific to them, to `workbench.local.yaml`
  (git-ignored), not `workbench.yaml`, which holds only the shared baseline (main
  branches, standard KBs). Local `checkouts:` and `kbs:` add to the shared lists
  (same name = override; `enabled: false` disables a shared KB); other lists replace.
  Templated KBs expand over local checkouts automatically, so a new KB is rarely needed.
- Ontology edits happen in the checkouts that `wb status` lists (under
  `sources/<src>/<name>/`, or wherever `path:` points). Edit only the edit files
  (`src/ontology/cl-edit.owl`, `src/ontology/uberon-edit.obo`) and follow each repo's
  own CLAUDE.md / contributing rules. Never edit `imports/` or `components/` by hand.
- MBA terms come from `src/templates/*.tsv` in the MBA checkout, compiled by the ODK
  Makefile into `components/all_templates.owl`. Edit the templates, then regenerate the
  component (in the ODK docker image, from `src/ontology/`) before building a KB;
  otherwise the KB still has the old MBA terms. MBA IRIs are not OBO:
  `MBA:549` = `https://purl.brain-bican.org/ontology/mbao/MBA_549` (`prefixes:` in
  workbench.yaml). A quoted label shared with another class only resolves if exactly one match is OBO;
  prefer `MBA:<id>`. `mbao-release__…` KBs use the published mbao-base.owl, i.e. what
  CL's release imports.
- DHBA's committed component is an empty placeholder: its terms are only in the built
  `dhbao-base.owl` at the checkout root, which is what the KBs read. Rebuild it (ODK
  `make prepare_release`) after changing the structure graph or bridge. HOMBA terms are
  in its committed `components/all_templates.owl`. `dhbao-release__…` KBs use the
  published dhbao-base.owl that CL imports.
- `patches/*.ofn` hold experimental axioms not yet in either repo (placeholder IDs
  `obo:EX_…`).

## Checking a change with the reasoner

1. Before editing: query the relevant KB (`uv run wb q KB EXPR`) and keep the output.
2. Edit, then `uv run wb build KB && uv run wb restart KB`. If `wb watch` is running,
   it does this for you; check `wb status` until the KB is served again.
3. Re-run the query, and `uv run wb compare` against a KB built from master.
4. `uv run wb unsat KB` must not report anything new.

Use the merged `cl-*__uberon-*` KBs for anything that crosses the two ontologies
(soma location, part_of chains, taxon constraints), and `mba-*__cl-*__uberon-*` when
MBA atlas structures are involved
(`dhba-*__…` / `homba-*__…` likewise for DHBA and HOMBA). The single-ontology KBs see only the other
ontology's last-release import slice; MBA has no usable Uberon of its own, so it is
only built merged with an Uberon checkout.

`oq` (`uv run oq …`) queries the *published* ontologies (OLS4, Ubergraph). Use it for
the released state and for ontologies not in the workbench, not as a check of a
branch.

## Rules

- Commit or push in the ontology checkouts only when asked. `wb sync` never
  overwrites uncommitted work (ff-only, clean checkouts only).
- Don't round-trip reasoner inputs through RDF; keep `.ofn`.
- Uberon partonomy in CL's import can differ from uberon-edit. When they disagree,
  the merged KB is the one to trust for a branch.
