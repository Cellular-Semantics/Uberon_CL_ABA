# CL + Uberon + Allen brain atlas (ABA) workbench

For developing related terms in the Cell Ontology (CL), Uberon and the Allen brain atlas
ontologies together, with a reasoner checking the result as you go:

- [Mouse Brain Atlas Ontology](https://github.com/brain-bican/mouse_brain_atlas_ontology)
  (MBA, the Allen CCF structure graph mapped to Uberon)
- [Developing Human Brain Atlas Ontology](https://github.com/brain-bican/developing_human_brain_atlas_ontology)
  (DHBA)
- [Harmonized Ontology of Mammalian Brain Anatomy](https://github.com/Cellular-Semantics/harmonized_ontology_of_mammalian_brain_anatomy_ontology)
  (HOMBA)

Built from the
[cl-uberon-workbench](https://github.com/Cellular-Semantics/cl-uberon-workbench)
template, with the atlas ontologies added as further sources (see [MBA](#mba) and
[DHBA and HOMBA](#dhba-and-homba) below). It gives you:

- **Branch checkouts** of CL and Uberon (or any ODK-style ontology repo) as git
  worktrees, declared in one config file and kept in sync with GitHub.
- **Merged knowledgebases**: CL with its Uberon import slice replaced by the full
  `uberon-edit` closure of a chosen Uberon branch, and the reverse. So a new Uberon
  term and the CL class defined from it can be reasoned over together before either
  PR is merged.
- **Owlery** (ELK) serving every KB at one URL, one process per KB, so a rebuilt KB
  reloads without restarting the others. `wb watch` rebuilds and reloads when a
  checkout or patch changes.
- **`wb q` / `wb compare` / `wb unsat`**: DL queries written with CURIEs and
  `'labels'`, before/after comparison between KBs, and an unsatisfiable-class check.
- **`oq`** (onto-query): OLS4 / Ubergraph lookups against *published* ontologies, for
  comparing with what's on your branches.

## Quick start

Requirements: Java 11+, [uv](https://docs.astral.sh/uv/), git, about 16 GB RAM.
Or open the repo in a GitHub Codespace / dev container (`.devcontainer/`), which sets
everything up.

```sh
# "Use this template" on GitHub, then clone your copy, or clone this repo directly
uv sync                 # Python env with wb and oq
uv run wb setup         # ROBOT + Owlery into .tools/
uv run wb up            # clone CL, Uberon (master) + MBA (main), build KBs, serve on :8090
uv run wb q mba-main__cl-master__uberon-master "'GABAergic neuron' and (RO:0002100 some 'cerebellum')" --direct
uv run wb q mba-main__cl-master__uberon-master "BFO:0000050 some MBA:549" --direct   # parts of MBA 'Thalamus'
```

The first `wb sync` makes blob-less partial clones (file contents are fetched on
demand), so it takes a few minutes, not the time of a full clone.

## Configuration

`workbench.yaml` is the only thing to edit. It is committed, so a team working from
one copy of the template shares the same set-up. `workbench.local.yaml` (git-ignored;
see `workbench.local.yaml.example`) is deep-merged on top for machine-specific
settings.

### Sources and checkouts

```yaml
sources:
  cl:
    repo: https://github.com/obophenotype/cell-ontology.git   # or your fork
    edit: src/ontology/cl-edit.owl
    catalog: src/ontology/catalog-v001.xml
    checkouts:
      - master
      - my-new-neuron-types          # a branch
      - pr: 3788                     # someone's PR, to reason over it with your Uberon branch
    sync: ff
```

Each checkout is a worktree at `sources/<source>/<name>/`. Edit `cl-edit.owl` there
(Protégé, a text editor, an agent), commit and push as usual: these are ordinary git
checkouts.

Already have clones? Point at them in `workbench.local.yaml` instead:

```yaml
sources:
  cl:
    path: ~/GitHub/cell-ontology
    checkouts: auto        # every worktree of that clone, named by branch
```

### Sync policy

| `sync` | `wb sync` does |
|---|---|
| `ff` (default for managed sources) | fetch, then fast-forward each clean checkout to its upstream (PR checkouts to the PR head). Checkouts with uncommitted changes or local commits are left alone and reported. |
| `fetch` | fetch only; `wb status` shows ahead/behind |
| `none` (default for `path:` sources) | nothing; you manage the checkout |

`wb sync --prune` removes clean managed worktrees that you've taken out of the config.

### KBs

A KB is a merge of **parts**: a source's edit-file import closure, a local `file:`
(see `patches/`), or a `url:`. `{source}` in the name expands over that source's
checkouts (all of them, unless `matrix` restricts it):

```yaml
kbs:
  - name: cl-{cl}__uberon-{uberon}
    parts:
      - {source: cl, drop_import_subjects: [UBERON]}
      - {source: uberon, drop_import_subjects: [CL]}
    matrix: {cl: "*", uberon: [master, my-uberon-branch]}
    heap: 10G
```

`drop_import_subjects` handles the overlap. CL imports a slice of Uberon and Uberon
imports a slice of CL, and each slice is from the last release, not your branch. For
each file the edit file imports from `imports/`, the build drops every axiom whose
*subject* is a term with one of the given prefixes. Uberon's own axioms then come only
from `uberon-edit`, and CL's only from `cl-edit`. Axioms that only *mention* those
terms (e.g. a GO class `occurs in` some Uberon term, a CL GCI) are kept.

`wb kbs` shows what the config expands to and whether each KB is current.

### Serving

```yaml
serve:
  port: 8090            # http://localhost:8090/kbs/<kb>/{subclasses,superclasses,equivalent,instances}
  backend_port_base: 9100
  reasoner: elk
  heap: 6G
  kbs: "*"              # which KBs `wb serve` starts by default; globs allowed
```

## MBA

MBA classes (`MBA:<Allen structure id>`, i.e.
`https://purl.brain-bican.org/ontology/mbao/MBA_<id>`) are each defined as an Uberon
class and `part_of` some `Mus musculus`, and arranged by the Allen structure graph.
`workbench.yaml` adds:

- source `mba` (`main`), edit file `src/ontology/mbao-edit.owl`. The MBA terms are not
  in the edit file but in `components/all_templates.owl`, generated from
  `src/templates/*.tsv` by the ODK Makefile. After editing a template (e.g. the
  CCF→Uberon mapping in `mba_CCF_to_UBERON.tsv`), regenerate the component in the
  checkout before `wb build`; the workbench builds from what's committed or on disk.
- `filter_dirs: [imports, components]` and `drop_import_subjects: [UBERON, CL]` on the
  MBA part. The component carries labels etc. for every CL/Uberon class it references,
  taken from the release it was built against; these are dropped so CL and Uberon
  axioms come only from their checkouts. MBA's own Uberon import
  (`imports/merged_import.owl`) is an empty placeholder in the repo; the build treats
  0-byte imports as empty ontologies.
- a top-level `prefixes:` map so `MBA:549` / `ABA:…` work as CURIEs in `wb q` and
  results print as CURIEs.
- KBs `mba-{mba}__uberon-{uberon}` and `mba-{mba}__cl-{cl}__uberon-{uberon}`. Use the
  three-way KB to check, for example, a new Uberon brain-region class, the MBA
  structures mapped to it, and CL classes with that soma location, together. It is
  also the one `wb serve` starts by default.

- KB `mbao-release__cl-{cl}__uberon-{uberon}`: the *published* `mbao-base.owl` (what
  CL mirrors for its MBA import) instead of an MBA checkout. It reproduces what CL's
  release sees, so an unsat there is one the CL release will hit.

Labels: many MBA labels are shared with Uberon or other atlases (e.g. 'thalamus' is
both MBA:549 and a DHBA class). A quoted label resolves only if it is unique, or if
exactly one match is an OBO class; otherwise use the CURIE (`MBA:549`).

## DHBA and HOMBA

Both are set up like MBA (`drop_import_subjects: [UBERON, CL]` on the atlas part,
`DHBA:` / `HOMBA:` in `prefixes:`), with two differences:

- **DHBA**: the committed `components/all_templates.owl` is an empty placeholder; the
  content only exists in the built `dhbao-base.owl` at the repo root, which is the edit
  file the KBs read. After changing the structure graph (`src/ontology/sources/16.ofn`)
  or the Uberon→DHBA bridge, rebuild `dhbao-base.owl` in the checkout (ODK
  `make prepare_release`) before `wb build`. KBs: `dhba-{dhba}__cl-{cl}__uberon-{uberon}`
  and `dhbao-release__cl-{cl}__uberon-{uberon}` (the published `dhbao-base.owl`, which CL
  mirrors for its DHBA import).
- **HOMBA**: the Allen HOMBA_v1 structure graph plus the Uberon→HOMBA bridge, compiled
  into the committed `components/all_templates.owl`. KB:
  `homba-{homba}__cl-{cl}__uberon-{uberon}`.

## Commands

| | |
|---|---|
| `wb sync [SOURCE…] [--prune]` | create/update checkouts per config and `sync` policy |
| `wb status` | checkouts (branch, commit, ahead/behind, uncommitted) and KBs (built, served, needs reload) |
| `wb build [KB…] [--force]` | build KBs (globs ok). Per-checkout closures are cached and keyed by commit plus uncommitted changes, so only what changed is rebuilt |
| `wb serve [KB…]` / `wb restart [KB…]` / `wb stop [KB…]` | manage Owlery backends and the proxy |
| `wb up` | sync + build + serve |
| `wb watch [KB…] [--interval 20] [--sync-every 600]` | rebuild and reload served KBs whose checkouts or patches change; optionally pull remote changes too |
| `wb q KB EXPR [--super\|--equiv\|--inst] [--direct]` | DL query (Manchester syntax with CURIEs, `'labels'` or `<IRIs>`) |
| `wb compare KB_A KB_B EXPR …` | results that differ between two KBs, e.g. a branch vs master, or patched vs not |
| `wb unsat KB` | unsatisfiable classes |
| `oq …` | OLS4 / Ubergraph lookups (`uv run oq --help`) |

Results print as `CURIE<TAB>label`. When a label is ambiguous, the OBO term is used if
there is exactly one; otherwise use the CURIE.

## A typical loop

1. Add your Uberon branch and CL branch as checkouts, then run `wb sync`.
2. `wb serve 'cl-*__uberon-*'`, then `wb watch` in another terminal.
3. Try the idea as a patch first (`patches/`, a `file:` part), and use `wb compare`
   to see what it changes.
4. Move the axioms into `uberon-edit.obo` / `cl-edit.owl` on the branches and commit.
   `watch` rebuilds the KB, and `wb compare cl-master__uberon-master
   cl-mybranch__uberon-mybranch EXPR` shows the effect of both PRs together.
5. Run `wb unsat` before opening PRs: the merged KB also catches cross-ontology
   clashes (e.g. taxon constraints in Uberon against a CL class's soma location).

## Layout

```
workbench.yaml            shared config (commit it): sources cl, uberon, mba
workbench.local.yaml      your overrides (ignored)
patches/                  experimental OWL axioms (file: parts)
src/workbench/            the wb CLI
sources/<src>/.repo       partial bare clone        (ignored)
sources/<src>/<checkout>  worktrees                 (ignored)
build/parts/              cached per-checkout closures (ignored)
build/kbs/<kb>.ofn        KBs; <kb>.json records the commits they were built from
run/                      Owlery configs, logs, PIDs  (ignored)
```

All reasoner inputs are OWL functional syntax written by OWLAPI. Nothing goes through
an OWL → RDF → OWL round trip.

See `docs/design.md` for the reasons behind these choices and the alternatives.
