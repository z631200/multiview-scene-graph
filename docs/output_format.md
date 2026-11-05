# Text output contract

For the implemented Visible GT JSON format and rules, see
[ground-truth relations](ground_truth_relations.md). Its parent-type classification,
strict comparisons without gap thresholds, and accepted-only final edges are separate
from the model output contract below. Each GT run saves its rules in `definitions.json`.

See [README](../README.md) for quick start, [architecture](architecture.md) for module
interactions, [Ollama guide](ollama_guide.md) for retry/recovery usage, and
[research design](research_design.md) for the complete prompts.

All model answers are English Markdown bullets, not JSON. Each section uses an exact
level-two heading. Records have one line each and use ` | ` as the field separator.
Use `- None` for an empty section. Do not use pipes within prose fields.
The research design's English prompts are preserved in `scene_prompts.py`; the contract below
is appended to them. All examples here are illustrative, not observations of the input scene.

## Stage 1: local observation

Required headings: `Observation conditions`, `Objects`, `Relations`, `Uncertainties`.
Conditions must include the view ID. Conditions and uncertainties are free prose bullets.

Objects have five fields: ID, name, visible features, image location, occlusion.
Relations have seven fields: ID, subject, relation wording, object, reference type,
certainty, visible evidence.

```text
- v1_o1 | cup | white, round handle | center | base partly hidden
- v1_o2 | table | brown surface | bottom | extends beyond frame
- v1_r1 | v1_o1 | appears to rest on | v1_o2 | physical | tentative | base is partly hidden
```

Reference types: `image`, `camera depth`, `physical`.
Certainty: `clear`, `tentative`.
The parser also accepts subject, object, relation wording in that order when IDs
unambiguously identify the two endpoints. Raw model text is always retained.
Local IDs are scoped to their view, e.g. `v2_o1`, `v2_r1`.

## Stage 2: object correspondence

Required headings: `Global objects`, `Mapping`, `Ambiguities`.
Global objects have five fields: ID, description, local sources, status, rationale.
Mapping has three fields: local ID, global candidate IDs or `unknown`, status.
Ambiguities are free prose bullets with IDs such as `a1`.

```text
- g1 | white cup | v1_o1, v2_o3 | unresolved | distinctive markings are obscured
- v1_o1 | g1 | unresolved
- v2_o3 | g1, g2 | unresolved
- v3_o4 | unknown | unresolved
```

Statuses: `provisional`, `unresolved`. Provisional means provisionally accepted by
the model, not ground truth. Every local object must have exactly one mapping record.
Each global object's sources must exactly match its candidate memberships. Two separate
objects in one view cannot be provisionally merged. Unknown objects remain unassigned.

## Stage 3: initial graph

Required headings: `Nodes`, `Edges`, `Unresolved issues`, `Verification requests`.
Nodes have four fields: ID, description, local sources, correspondence status.
All stage-2 global IDs, sources and statuses must be preserved.
The stage-3 prompt includes a copyable node roster and a local-relation endpoint lookup,
computed exclusively from validated model outputs. These helpers neither use simulator
ground truth nor decide which relations belong in the graph.

Edges have eight fields: ID, triple, frame, status, basis, sources, premises, explanation.

```text
- e1 | (g1, on, g2) | physical | unresolved | observed | v1_r1 | none | cup base is partly hidden
```

Allowed relations:

| Relation | Frame | Condition |
| --- | --- | --- |
| `image_left_of` | `view_1`–`view_4` | Subject is left of object in that image. |
| `closer_to_camera` | `view_1`–`view_4` | Depth evidence places subject closer to that camera. |
| `on` | `physical` | Object supports subject on its surface. |
| `inside` | `physical` | Full containment; partial/unclear containment remains unresolved. |

Edge statuses: `provisional`, `unresolved`, `conflicting`. Basis is `observed`,
premises is `none`: no transitive, inverse, metric or world-direction inference is
enabled. Referenced local relations must support endpoint mappings in the same order
and the appropriate reference frame. Tentative evidence or unresolved identities
cannot produce provisional edges. Opposing image/depth claims within the same view
must both be conflicting. The validator cannot judge visual truth or semantic equivalence.

Issues are prose bullets with IDs such as `u1`. Requests have four fields:
request ID, target view, local object IDs in that view, neutral question.

```text
- q1 | view_1 | v1_o1, v1_o2 | Can the contact between the cup and table be seen?
```

Requests are bounded by `--verification-budget`; they are saved but not executed.
Each question must be answerable from the target view alone; it cannot ask the observer
to compare identities across images that observer cannot see. Explicit foreign view/ID
references are rejected; semantic neutrality still requires review.
All source ID lists use commas. An empty observation or graph is allowed when explicitly
reported; format validation does not imply useful coverage or scene accuracy.

## Audited normalization and recovery

The raw answer always stays in `responses/*.md` and `*.json`. Before strict validation:

- A predicate or reference-type label in the frame field can be replaced by `view_N`
  only when all cited local relations belong to that one view, have the matching
  reference type, and their endpoints agree with the global mapping.
- An explicit `view_N` is never silently changed. Unknown sources, mixed views and
  reversed endpoints remain errors. No objects or spatial claims are inferred.
- Identical directed triples within the same frame are consolidated, keeping the
  first edge ID, all sources and both explanations. Conflicting/unresolved status is
  retained conservatively. References to merged edge IDs are redirected and logged.

Changes and hashes are recorded in `normalizations/`; normalized drafts are saved as
`responses/*.normalized.md`. The result must still pass the full validator. Requests
without existing local target IDs must be corrected or omitted, not guessed.

`--fork-from OLD_RUN` creates a separate run after a code fix. Inputs, model/settings
and saved artifact hashes must match; stages 1–2 are revalidated and copied. The most
recent complete graph response is retried under the new validator/normalizer; if it
passes, no new inference is needed, otherwise only the graph is sent for correction.
The source run and its historical failure record are preserved.
