# Patches

OWL files with axioms that live in neither CL nor Uberon yet: a proposed new term,
an alternative definition, a GCI. Add one to a KB as a `file:` part and compare that
KB with the unpatched one (`wb compare`) to see what the change does to
classification before you open a PR in either repo.

- Use OWL functional syntax (`.ofn`). Placeholder IDs: `obo:EX_nnnnnnn` (they are
  written as `EX:nnnnnnn` in `wb q`). Never use an ID range that a real ontology
  might hand out.
- `wb watch` rebuilds a KB when one of its patch files changes.
- When the change is ready, move the axioms into `cl-edit.owl` or `uberon-edit.obo`
  on a branch, add that branch as a checkout, and drop the patch.

`example-cerebellum-like.ofn` proposes an Uberon term `cerebellum-like structure`
(cerebellum + dorsal cochlear nucleus) and a CL class defined from it. In the patched
KB its direct subclasses are `cerebellum GABAergic neuron` and `cartwheel cell`. These
are the same members as CL's existing GCI-based `CL:0020088`. The reasoner doesn't
make the two equivalent, because CL's class is populated by GCIs and not defined.
