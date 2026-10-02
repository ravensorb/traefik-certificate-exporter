# Story acceptance-criteria dimensions

This is the one canonical statement of the dimensions a story's acceptance criteria must
cover. Story elaboration and the story technical-AC gate both read it; neither restates it.

Infrastructure and configuration stories use the **same** dimensions as code stories, in
different vocabulary. A Terraform module, a pipeline or a policy is held to the same eight
questions; only the words change. Each dimension below gives a CODE line and a CONFIG
line; some add an ALL line that applies to every work type.

## Required shape

A story carries two sections, business above technical, each dimension an `###` heading in
the order listed here:

```
## Business acceptance criteria
### Outcome
### Non-goals

## Technical acceptance criteria
### Interface contracts
### Error and edge case handling
### Observability requirements
### Security considerations
### Testability approach
### Existing-library check
```

## Rules

- **Provenance.** Every applicable dimension, business `Outcome` included and all six
  technical ones, ends with a resolving `Spec: <path>#<anchor>` line, or
  `Spec: none — <reason>`.
- **Exception: `Non-goals`, the single exemption.** It takes no `Spec:` pointer. A negative scope statement has
  nothing to resolve against.
- **`N/A — <reason>`.** A dimension that does not apply is marked `N/A — <reason>`, never
  omitted. An absent dimension and an inapplicable one look identical otherwise, so an
  omitted heading is treated as unfilled and blocks advancement.

## Business acceptance criteria

### Outcome

- CODE: the observable result for the user or caller, stated so a reviewer can tell whether it happened.
- CONFIG: the operational result, stated as who benefits and what they can now do.
  Example: "support can trace a failed deploy to its triggering change without reading raw logs", not "the pipeline is restructured".

### Non-goals

- CODE: behaviour a reader might assume is in scope that this story deliberately does not deliver.
- CONFIG: adjacent work a reader would reasonably assume is included but is left out.
  Example: "does not migrate the legacy Jenkins jobs" or "no production rollout in this story".

## Technical acceptance criteria

### Interface contracts

- CODE: function, API and data-model signatures, with types, required fields and versioning.
- CONFIG: module inputs and outputs, variable types and defaults, and the contract other stacks consume.
- ALL: inspect the siblings of every path the story adds or changes and state the conventions they set — companion files, index/barrel or enumeration registration, any per-directory pattern.
  Example: a new `.mjs` module where every module has a `.d.mts` sibling needs its own; a new Terraform module where every module has `variables.tf` and `outputs.tf` needs both.

### Error and edge case handling

- CODE: invalid input, timeouts, empty and boundary values, and what the caller sees on failure.
- CONFIG: partial apply, rollback and re-run safety, drift, and what state a half-finished deployment leaves.

### Observability requirements

- CODE: structured logs, metrics and traces, with a correlation ID carried across calls.
- CONFIG: pipeline correlation IDs, deployment and audit logs, and alerts on the resources created.

### Security considerations

- CODE: input validation, authentication and authorisation, secrets handling and data exposure.
- CONFIG: IAM and role assignments, secrets and key storage, and network exposure and segmentation.

### Testability approach

- CODE: unit, integration and contract tests, and how dependencies are isolated.
- CONFIG: plan or what-if output reviewed before apply, policy checks, and a post-deploy validation.
- ALL: state where the new tests or checks live and how they are named, as the neighbouring ones establish.
  Example (shape only; read the real siblings, do not copy): a suite named for its module, or a policy check wired in beside the others.

### Existing-library check

- CODE: which library or platform capability already covers this, or why custom code is warranted.
- CONFIG: which published module, action or built-in resource already covers this, or why a bespoke one is warranted.
  Example: use the published `azure/login` action rather than scripting `az login` by hand, or state why its version pin is unacceptable here.
