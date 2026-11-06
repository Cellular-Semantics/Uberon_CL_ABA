# Design notes

## Goals

1. Anyone can start from the GitHub template and get a working set-up with three
   commands, on a laptop or in a Codespace.
2. Users control **what** is loaded (which repos, branches, PRs, patches, which
   combinations) and **when** it is refreshed, without editing scripts.
3. Reasoning reflects the *branches being edited*, not last month's import slices.

## What gets loaded: a declarative config

Users don't edit build scripts; they edit `workbench.yaml`.

- **Sources** are generic: any ODK-style repo with an edit file and a catalog. CL and
  Uberon are the defaults, but an application ontology (WMBO, BGO, HRA…) is just
  another source.
- **Checkouts** are branches or PR numbers. A PR checkout lets you reason over a
  collaborator's open CL PR alongside your Uberon branch without checking it out by
  hand.
- **KB recipes** are lists of parts with a name template and an optional matrix. That
  covers every combination we've needed so far (CL alone, Uberon alone, CL×Uberon,
  CL×Uberon+patch, CL×Uberon×application ontology) without special cases in the code.
- **Two config layers.** The committed file is the team's shared set-up; the
  git-ignored local file holds paths to existing clones, heap sizes and ports. This
  lets one template serve both "clone everything fresh" users and people with existing
  checkouts and worktrees (like `cell-ontology-wt/` in the WMB collection).

Alternatives considered:

- *Makefile / shell scripts* (as in `../owlery/build.sh`): fine for one user. But
  every new combination means editing the script, and incremental rebuilds keyed on
  "commit + uncommitted diff" are awkward in make.
- *Git submodules* for CL/Uberon: they pin one commit per repo, can't express "these
  three branches", and are painful with large repos. Worktrees off one partial clone
  give any number of branches for the cost of one object store.
- *Pulling release artefacts (PURLs) instead of building from edit files*: fast, but
  defeats the point, since you want the branch you are editing.

## How it is synced: three layers, all optional

| Layer | Mechanism | Who uses it |
|---|---|---|
| Remote → checkout | `wb sync` (`ff` / `fetch` / `none` per source), or `wb watch --sync-every N` | following a collaborator's PR or master as it moves |
| Checkout → KB | content fingerprint (HEAD + uncommitted diff + untracked files in the ontology folder) compared with the KB manifest; `wb build` rebuilds only stale parts | everyone |
| KB → Owlery | one process per KB; `wb restart KB`, or automatic in `wb watch` | everyone |

The sync rules are conservative: fast-forward only, clean checkouts only. Local work
is never overwritten, and the workbench never commits or pushes.

Polling (`wb watch`) was chosen over file-system events: it needs no dependencies,
works on network file systems and in containers, and builds take tens of seconds
anyway. Hooks are another option and can sit on top: a git `post-commit` /
`post-merge` hook or a Claude Code `PostToolUse` hook on edits to `*-edit.*` can
simply run `wb build KB && wb restart KB`.

## Why one Owlery per KB

Owlery loads its KBs at start-up and has no reload endpoint. With all KBs in one
process (as in `../owlery/start.sh`), changing one branch means re-loading and
re-classifying every KB. With a process per KB:

- a rebuild reloads one KB and leaves the others answering queries;
- each KB gets its own heap (merged CL+Uberon needs more than CL alone);
- a failing KB doesn't take the others down.

The cost is one JVM (a few hundred MB) per KB. A ~100-line stdlib proxy keeps a single
base URL, so existing Owlery clients only see `/kbs/<name>/…`.

## The CL ↔ Uberon merge

CL's `imports/merged_import.owl` contains a Uberon slice; Uberon's contains a CL
slice. Merging the two edit closures naively gives a KB with two versions of every
shared term: the release slice and the branch. Axioms removed on the branch survive
from the slice, and stale definitions can make the merge inconsistent (we've seen
exactly this with WMBO's stale CL slice and `CL_0010011`).

The workbench filters each side's import files by **axiom subject**, so the other
ontology is the only source of axioms *about* its own terms. Axioms that only
reference the other ontology's terms are kept (GO, GCIs, restrictions). This is
`drop_axioms_about.py` from `../owlery/`, generalised to ID prefixes.

What it doesn't do (yet):

- Other shared imports (RO, GO, PATO, NCBITaxon) are taken from *both* sides, so the
  merge contains two release versions of each. That has been harmless so far; if it
  isn't, add `drop_import_subjects: [RO, GO, …]` to one side.
- `robot unmerge` of a product file (as in the WMBO build, which removes the CL
  product from WMBO). If an application-ontology source needs it, add an `unmerge:`
  option to parts.

## Distribution

- **GitHub template repo**: users get the config, CLI, docs and Claude Code set-up
  (`CLAUDE.md`, `.claude/skills/`), and their copy's `workbench.yaml` becomes their
  team's config.
- **`uv`** pins the Python side, including `oq` from its tagged release.
- **ROBOT and Owlery** are downloaded by version from GitHub releases into `.tools/`
  (or an existing `robot` on PATH is used). No Docker: the Owlery image is amd64-only
  and slow under emulation on Apple silicon.
- **Dev container** for Codespaces: Java 21, uv, port 8090 forwarded. 16 GB machines
  are enough for one merged KB plus the single-ontology KBs.

Possible next steps: a GitHub Action that builds the merged KB for a pair of PR
branches and posts `wb unsat` plus a classification diff as a PR comment; a
`wb diff` that runs `robot diff` on the inferred hierarchy between two KBs.
