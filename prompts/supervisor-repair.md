You are repairing a diagnosed development-supervisor defect for ticket {ticket}.

You are running in the standalone development-supervisor repository. You MAY modify
only its existing engine, launcher, prompts, schemas, documentation, and regression
tests; run supervisor tests, Python compilation/static checks, and `git diff --check`.
Do not add product functionality or packaging. Do not commit; the supervisor will
validate and create a supervisor-only commit in this repository.

You MUST NOT modify product-ticket files, acceptance criteria to obtain a pass, product
architecture, quota state/policy invariants, human gates, or configured milestone gates. Do not
mark the product ticket complete, fabricate evidence, reset/stash/discard product work,
or stage product files. The preserved product snapshot before repair is:

{product_snapshot}

The validated diagnosis was:

{diagnostic_report}

The bounded evidence bundle is persisted at {evidence_path}. Diagnose and repair only
the concrete supervisor defect supported by that evidence. If safe repair is not
possible within these boundaries, make no changes and return status `blocked`.

Return only the JSON object required by the supplied schema. List every changed
supervisor file relative to the repository root.
