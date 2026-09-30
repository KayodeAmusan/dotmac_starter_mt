# Contributing

Human developer rules. Agents follow the same canon via `AGENTS.md`
(the canonical hard-rules list — read it first; nothing here overrides it).

## Validation and merge gates

Tests run only on Git-hosted CI; do not run test commands or install
test/development dependencies on a workstation or any named test host.
Local static checks are allowed. Git-hosted PR CI is the merge owner
(`AGENTS.md`, "Validation before any commit").

```bash
# Local: pinned static checks only, without installing test dependencies.
# Git-hosted PR CI runs make check and make test-unit.
# For models, migrations, guards, or tenancy, CI also runs:
# make test-db-up && make test-integration && make test-db-down
```

All relevant Git-hosted CI gates must be green before merge.

## Test-first expectations

- Write the test before the behavior. For anything tenancy-affecting, the
  cross-tenant isolation canary comes FIRST (two tenants; B must get
  404/empty for A's rows even with the exact UUID) — copy the pattern in
  `tests/test_cross_tenant_isolation.py`.
- A new governance/architecture test needs a sensitivity proof: temporarily
  introduce the violation, watch the test go RED, revert.
- Unit tests (SQLite) never prove tenancy. RLS correctness only counts on
  Postgres (`make test-integration`).

## Migration discipline

- The SAME migration that creates a table creates its RLS
  (`ENABLE` + `FORCE` + policy) and its grants. No "add tenant_id later".
- Platform catalog tables (no `tenant_id`): GRANT `platform_api`/`app_admin`
  only, REVOKE from `app_user` — the catalog audit
  (`tests/test_rls_catalog.py`) fails otherwise.
- Migrations run as `app_admin` (`MIGRATION_DATABASE_URL`), never on
  container boot; `scripts/deploy.sh` is the only production migration path.
  New revisions stay backward-compatible with the previous release
  (deploy rolls the app back, not the schema).

## Adding things (pointers, not duplicates)

- **A feature package** — README § "Starting a project from this template"
  and `CLAUDE.md` § Extension points: package + `feature.py`, register in
  `FEATURE_MODULES`, add to the import-linter independence contract,
  isolation test first.
- **A setting** — declare a `SettingSpec` in your feature's spec module and
  wire a real `resolve_value(...)` reader before shipping
  (`tests/architecture/test_no_orphan_settings.py` fails otherwise).
- **A custom-fields entity** — register the model in
  `app/features/custom_fields/registry.py::ENTITY_MODELS` and give it a
  `custom_fields` JSONB column (see `Party.custom_fields`).
- **A model** — placement rule and provenance table:
  `CLAUDE.md` § Model placement rule and `docs/ARCHITECTURE.md`'s model
  provenance + ownership tables (every model/resource names its owner).
- **A config knob** — overridable with a documented default
  (`Settings` + `.env.example`); prod-unsafe defaults go in
  `validate_settings`'s prod-fatal list. Never hardcode ports, hosts,
  image names, or paths.

## Pull requests

- Small and reviewable — one coherent slice per PR, not a grab-bag.
- CI must be green before merge (quality matrix, unit, Postgres
  integration, docker-build health gate — `.github/workflows/ci.yml`).
- Breaking changes are called out in the PR body and CHANGELOG entry.
- Docs move with the code: update `docs/ARCHITECTURE.md`'s tables and any
  affected ADR (dated amendment, never rewritten history) in the same PR.
