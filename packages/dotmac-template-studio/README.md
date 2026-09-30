# dotmac-template-studio

Tenant-authored **notification templates** for DotMac products — and the
reference for what an installable, stateful DotMac module looks like.

ADR-0006 names this the first stateful module: *"dotmac-template-studio a MODULE
— the first stateful one, not a kernel facility."* It owns a database namespace
and a migration lineage of its own, is optional, and is installed by an assembly
rather than imported by the kernel.

## Its one decision: what the message SAYS

ADR-0006 § 5b narrowed this module to a single owned decision. It renders and
returns `(subject, body)`. It does **not** decide whether a message may be sent
(consent), over what (channel policy), how it is actually sent (delivery), or
produce documents — four separate foundation owners, each with its own dossier.

Documents are explicitly **not** served here. ERP's document templates need Jinja
control flow, filters and page geometry; this module substitutes rather than
evaluates, on purpose. The 2026-08-10 source audit
(`docs/inventories/template-studio-source-audit.md`) has the evidence.

## What it does

- **Templates** are addressed by a stable `(slug, channel)` within a tenant.
  Channel is part of the identity, not an attribute of it: the same message
  routinely exists as an `email` and an `sms` with different wording, and both
  are the "same" template to the code that sends it.
- **A render context** fixes which placeholders a template may use. The product
  registers one per real send path; this module owns the checking and knows none
  of the names.
- **Versions** are immutable revisions. Publishing points the template at one of
  them; the superseded revision is kept, which is the whole point of a studio.
  A published revision cannot be edited — "what was sent" must not change after
  the fact.
- **Rendering** substitutes `{variable}` placeholders in the PUBLISHED revision.
  Deliberately **not** a Jinja environment: a tenant-authored body is untrusted
  input, and handing it to a template engine would give an operator arbitrary
  expression evaluation inside the server process. Products that only need
  substitution can import `dotmac_template_studio.rendering.render` without
  assembling Template Studio's web surface or database models.
- **Email composition** joins already-rendered bodies in caller-declared order
  and uses the caller-named primary part's rendered subject. `service.compose_email`
  returns the exact ordered parts as provenance. The product still decides which
  events belong together, whether and when to send, and which channels to use.
  Full templates may repeat greetings; composition does not rewrite copy.

## The placeholder contract (ported, not invented)

Single-brace `{variable}`, validated **at save time** against the template's
registered context. This is Sub's production contract, ported with its seven
behaviour tests as parity proof.

Two rules do the work:

1. **`{{double}}` braces are rejected when you save.** They are not substituted
   at send time, so they would reach the recipient literally — which is exactly
   what happened before Sub added this check.
2. **A placeholder the context cannot supply is rejected when you save.** This is
   the load-bearing rule: a template that saves cannot later produce a
   half-substituted message, because every name it uses is known to exist before
   anyone can publish it.

Validating against the *union* of every context would pass both and reproduce the
original bug, which is why a template names one context and is held to it.

## Installing it in an assembly

Four edits, and no more:

```python
# app/assembly.py
import dotmac_template_studio

# Declare the send paths this product actually implements. A context must never
# name a variable its sender cannot produce — that guarantee is the whole point.
dotmac_template_studio.register_contexts(
    dotmac_template_studio.RenderContext(
        name="billing",
        variables=("customer_name", "invoice_number", "amount", "due_date"),
        description="Values the billing send path supplies.",
    )
)

assembly = ProductAssemblySpec(
    modules=[*load_manifests(FEATURE_MODULES), dotmac_template_studio.module],
    packaged_template_dirs=(dotmac_template_studio.template_dir(),),
    ...
)
```

```ini
; alembic.ini — append the module's lineage
version_locations = ... .../dotmac_template_studio/migrations/versions
```

plus the dependency itself. The module's namespace allocation
(`mod_tstudio`, prefix `ts`) is **not** one of the edits: it ships in the kernel's
`MIGRATION_OWNER_LEDGER`, which is what makes "one module, one immutable schema"
enforceable across repositories rather than a convention each product re-states.

## Its public surface

`module`, `RenderContext`, `register_contexts()`, `registered_contexts()`,
`service` (including `RenderedEmailPart`, `ComposedEmail`, `compose_email`),
`template_dir()`, `migrations_dir()`, `__version__`.

Do **not** import `dotmac_template_studio.models` and query it. The tables are an
implementation detail behind `service`; reaching past it re-creates the
parallel-writer problem the source-of-truth standard exists to prevent.

## Two things worth knowing if you are writing the next module

1. **Its admin screens style themselves with `var(--dmui-*)` tokens, not utility
   classes.** A consuming assembly's Tailwind build cannot see inside an
   installed package, so any utility class used only in a module's templates is
   purged from the compiled CSS — the screen renders unstyled in production while
   looking fine in a dev build that scanned more. Tokens are a published
   contract; the host's utility classes are its private build output.
2. **It is held to the assembly's governance, not a weaker one.** The
   thin-wrapper, route-guard, web-import, template-convention, timestamp-filter
   and service-typing checks all walk this package. A module is the
   less-reviewed code of the two; exempting it would put the weaker standard
   exactly where the stronger one is needed.

## Versioning

`dotmac-template-studio`'s version is its own. It is independent of both the
kernel's release version and `KERNEL_MODULE_CONTRACT_VERSION` — the manifest
generation it is built against, which is what actually gates loading.
