# Working in this repository

- Do all work on a clearly named branch other than `main`. If the current branch
  is `main`, create a feature branch before editing. Choose a broad name that
  describes the full scope of work different from `main`, including earlier
  commits and uncommitted changes, rather than just the latest task. Keep that
  name stable through individual tasks and refinements; rename it only when the
  user asks.
- Do not push unless the user explicitly asks.
- Do not create new documentation files without the user's explicit approval.
  Update existing documentation instead, keeping the number of files manageable.
- When work is finished, clearly state what comes next. Identify any manual work
  required from the user and give the concrete next steps.
- Read `ROADMAP.md` and `docs/implementation-plan.md` before implementing features.
  `ROADMAP.md` owns direction and delivery order; older research backlogs are
  historical. Work on the agreed milestone only. Update its status when work
  changes milestone progress.
- Use simple language in documentation and explanations. Prefer "file index" to
  "manifest", "model version record" to "release manifest", "fetch data" to
  "research acquisition", "shared" or "main" to "canonical", and "save public
  forecasts" to "public-forecast capture". Keep real filenames, commands and code
  identifiers unchanged unless a code change is intended.
- Preserve original evaluation results, code versions and required data before
  moving or removing components. Existing code need not be kept when it no longer
  serves the forecast product. Frozen model version records include source paths
  and checksums; do not rewrite them to disguise code moves or changes.
- After completing a unit of work, proactively commit using Conventional Commits.

## Setup and checks

- Use `uv sync --frozen --group research` for the full development environment.
- Run relevant tests with `uv run pytest <paths>`. CI runs `uv run pytest`,
  `uv run ruff check .` and `uv run ruff format --check .`.
  Tests use local fixtures and a temporary Prefect server; image checks require Docker.
- Run `bash scripts/check.sh` before pushing for the same locked lint, formatting,
  full test suite and offline web/runner image checks as CI. Use `lint`, `test`, `demo` or `runner`
  as an argument to run just one group; see `README.md` for prerequisites.
- See `README.md` for quick start and checks, `docs/operations.md` for forecast
  commands and deployment, and `research/README.md` for evaluation evidence.
  The daily producer uses one package/CLI; follow the implementation plan when changing it.

## Documentation

- Keep the root README short: purpose, demo, quick start and task-based links.
- Put maintained guides in `docs/`, evidence in `research/reports/`, supporting
  literature in `research/literature.md` and superseded plans in `docs/archive/`.
- Give each topic one main home: status/order in `ROADMAP.md`, architecture in
  `docs/implementation-plan.md`, procedures in `docs/operations.md`, models in
  `docs/dataflow.md`, evaluation definitions in `docs/metrics.md` and publication
  rules in `docs/integration_contract.md`. Link instead of repeating details.
- Write procedures as prerequisites, commands and expected results. Keep history
  out of the main task sequence. Update the owning guide when behaviour changes.
- Keep frozen reports and model identities unchanged. Original report commands
  and literal paths describe the preserved checkout; explain them in the evidence index.
- Check relative links and safe CLI examples after moving or editing guides.
