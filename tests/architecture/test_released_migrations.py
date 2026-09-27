"""A migration that shipped in a published tag is history, and history is bytes.

## The enforceable premise (ADR-0018)

Every migration file present at any tag recorded below is inside a wheel on the
registry, and has therefore RUN, unmodified, in at least one database this
repository does not own and cannot inspect. The owner and tag counts are
derived by the guards; prose does not freeze a census that becomes false with
the next release.

Allocation is the sharper case, and the reason the guard grew a second
distribution rather than staying a one-module special. Its first four releases
hold ONE migration with ONE digest: a2 exposed `versions_dir()`, a3 made the ORM
relationships class-bound, a4 moved a manifest declaration between plane slots.
a6 then shipped the two prerequisite verifier revisions after deliberately
skipping a5. A quiet directory is not evidence its released bytes remain ours.

The integration a3 entry was added while #204 was open: a3 was tagged from `b14f66e`
after the branch was cut, which is exactly the event the map has to absorb
rather than be surprised by. The six files did not move — a3 is a Python fix —
so the entry repeats a2's digests, and
`test_two_tags_agree_unless_the_divergence_is_exactly_grandfathered` is what
proves that repetition is a fact rather than a paste.

Editing such a file does not migrate anything. It changes what a future
installation builds while every existing installation keeps whatever the old
bytes built — and `alembic_version` records only that the revision ran, never
which version of it. So the divergence is permanent, silent, and invisible to
every other gate here: the composed gate reads the CURRENT tree, the
live-catalog gate reads a database built from the CURRENT tree, and both agree
with each other while disagreeing with the field.

That premise is enforceable, which is what makes this a guard rather than a
convention. "Released" is not a judgement call: it is a tag on `origin`, and
every digest below is reproducible with

    git show <tag>:<path> | shasum -a 256

## Two halves, because either alone is defeatable

The **checked-in map** is what a reviewer reads: an edit to a released
migration shows up as a digest change in the diff, at the moment somebody could
still object. On its own it is defeatable in one commit — edit the file, update
the digest beside it, and the comparison agrees with itself.

So the map is also **cross-checked against the tags**: every recorded digest
must equal the SHA-256 of the blob git holds at that tag. Doctoring the map now
requires moving a tag on `origin`, which is a different and far more visible
act. Neither half is redundant; the first catches the honest mistake, the
second catches the map being brought into line with it.

The tag half follows the fail-closed oracle discipline #202 established for
`test_declared_publication.py`: a shallow or tagless checkout is a FAILURE, not
a skip, because "the oracle was unavailable" is never evidence that nothing is
wrong. It is runnable because that change gave the `unit` job `fetch-depth: 0`
— before it, this half would have been permanently skipped, which is why the
checked-in map is the primary and not merely a convenience.

## What this does NOT claim

It does not stop a released migration from being WRONG. A defect in shipped DDL
is repaired by a new revision that alters the result — the same discipline as
`ig_0007`, which verifies a prerequisite `ig_0001` should arguably have verified
and does not touch `ig_0001` to do it. This guard only insists the repair be
additive.

Approvals and ticketing are the measured exceptions to one-byte-history.
`ap_0001` shipped three byte sets across a1-a4 before enrolment; `tk_0001`
shipped two across a3-a4, and that second one was found by ENROLLING the
lineage on 2026-09-01 rather than by any gate — it is the same in-place edit
approvals made in the same week, invisible only because nothing was pointed at
it. `GRANDFATHERED_DIVERGENCES` records each closed historical set and the
canonical bytes retained by the tree; it is not permission for another edit.

The approvals census is paired with
`tests/test_approvals_released_migration_upgrades.py`, which reconstructs each
tagged meaning and proves its additive upgrade on PostgreSQL. Ticketing has no
such matrix, deliberately: it is sequenced AFTER the additive `tk_0002` repair
exists, because the matrix's job is to prove that repair. Its inventory says so
rather than implying evidence exists — and records that a straight port of the
approvals matrix would not do the job, because that matrix asserts tables and
rows and never asserts a grant.

## The kernel

``dotmac-kernel`` was the largest hole this file had, and the last one anybody
would have expected to find open: 61 published tags, 28 migrations, and a pin
in every product in the fleet. It stayed uncovered because the census below
read ``.github/release-modules.json`` alone, and the kernel is deliberately
absent from that allowlist — it has its own workflow with its own inspection
rules. "Not in the module allowlist" was therefore doing double duty: it meant
*unreleasable* for a package with no lane, and *released by a different lane*
for this one. ``_publishable_here`` separates them by reusing the sweep's own
``DEDICATED_WORKFLOWS``, and the dedicated-lane published-tag proof below
keeps that second door from becoming a way in for a name no tag supports.

## Scope

Every distribution named in ``DISTRIBUTIONS``. Each entry's digests were read
from its published tags when that lineage enrolled. That is the enrolment rule,
and it is the reason this is still not generalised to "every allowlisted
module": a distribution enters when the tag oracle has actually verified its
history, because a guard populated by guesswork is worse than an absent one.

Enrolment is therefore a data edit — a row in `DISTRIBUTIONS`, its tags in
`RELEASED_TAGS`, and its still-editable files in `UNRELEASED`. The
`test_every_migration_is_either_released_or_declared_unreleased` ratchet then
holds that distribution's whole versions directory, in both directions.

An unenrolled distribution is UNMONITORED here, not exempt (ADR-0018). The
difference is visible in `test_the_unmonitored_distributions_are_named`, which
lists exactly which allowlisted modules this file says nothing about.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"

#: The distributions this file monitors, and where each keeps its lineage.
#:
#: A distribution is here because somebody read its tags. Everything else is
#: unmonitored and named as such by
#: `test_the_unmonitored_distributions_are_named`.
DISTRIBUTIONS: dict[str, Path] = {
    "dotmac-numbering": (
        REPO_ROOT / "packages/dotmac-numbering/src/dotmac_numbering/migrations/versions"
    ),
    "dotmac-approvals": (
        REPO_ROOT / "packages/dotmac-approvals/src/dotmac_approvals/migrations/versions"
    ),
    "dotmac-integration": (
        REPO_ROOT
        / "packages/dotmac-integration/src/dotmac_integration/migrations/versions"
    ),
    "dotmac-entitlement-allocation": (
        REPO_ROOT
        / "packages/dotmac-entitlement-allocation/src/dotmac_entitlement_allocation"
        / "migrations/versions"
    ),
    "dotmac-files": (
        REPO_ROOT / "packages/dotmac-files/src/dotmac_files/migrations/versions"
    ),
    "dotmac-forms": (
        REPO_ROOT / "packages/dotmac-forms/src/dotmac_forms" / "migrations/versions"
    ),
    "dotmac-workflow-runtime": (
        REPO_ROOT
        / "packages/dotmac-workflow-runtime/src/dotmac_workflow_runtime"
        / "migrations/versions"
    ),
    "dotmac-platform-health": (
        REPO_ROOT
        / "packages/dotmac-platform-health/src/dotmac_platform_health"
        / "migrations/versions"
    ),
    "dotmac-support-access": (
        REPO_ROOT
        / "packages/dotmac-support-access/src/dotmac_support_access"
        / "migrations/versions"
    ),
    "dotmac-remote-access": (
        REPO_ROOT
        / "packages/dotmac-remote-access/src/dotmac_remote_access"
        / "migrations/versions"
    ),
    "dotmac-compliance-reporting": (
        REPO_ROOT
        / "packages/dotmac-compliance-reporting/src/dotmac_compliance_reporting"
        / "migrations/versions"
    ),
    "dotmac-ai-operations": (
        REPO_ROOT
        / "packages/dotmac-ai-operations/src/dotmac_ai_operations"
        / "migrations/versions"
    ),
    "dotmac-payments": (
        REPO_ROOT / "packages/dotmac-payments/src/dotmac_payments/migrations/versions"
    ),
    "dotmac-imports": (
        REPO_ROOT / "packages/dotmac-imports/src/dotmac_imports/migrations/versions"
    ),
    "dotmac-inbox-operations": (
        REPO_ROOT
        / "packages/dotmac-inbox-operations"
        / "src/dotmac_inbox_operations/migrations/versions"
    ),
    "dotmac-operational-escalations": (
        REPO_ROOT
        / "packages/dotmac-operational-escalations"
        / "src/dotmac_operational_escalations/migrations/versions"
    ),
    "dotmac-service-changes": (
        REPO_ROOT
        / "packages/dotmac-service-changes"
        / "src/dotmac_service_changes/migrations/versions"
    ),
    "dotmac-subscriptions": (
        REPO_ROOT
        / "packages/dotmac-subscriptions"
        / "src/dotmac_subscriptions/migrations/versions"
    ),
    "dotmac-billing": (
        REPO_ROOT / "packages/dotmac-billing" / "src/dotmac_billing/migrations/versions"
    ),
    "dotmac-collections": (
        REPO_ROOT
        / "packages/dotmac-collections"
        / "src/dotmac_collections/migrations/versions"
    ),
    "dotmac-fulfillment": (
        REPO_ROOT
        / "packages/dotmac-fulfillment"
        / "src/dotmac_fulfillment/migrations/versions"
    ),
    "dotmac-tax": (
        REPO_ROOT / "packages/dotmac-tax/src/dotmac_tax/migrations/versions"
    ),
    "dotmac-service-catalog": (
        REPO_ROOT
        / "packages/dotmac-service-catalog"
        / "src/dotmac_service_catalog/migrations/versions"
    ),
    "dotmac-customers": (
        REPO_ROOT
        / "packages/dotmac-customers"
        / "src/dotmac_customers/migrations/versions"
    ),
    "dotmac-fx-policy": (
        REPO_ROOT
        / "packages/dotmac-fx-policy"
        / "src/dotmac_fx_policy/migrations/versions"
    ),
    "dotmac-qualification": (
        REPO_ROOT
        / "packages/dotmac-qualification"
        / "src/dotmac_qualification/migrations/versions"
    ),
    "dotmac-response-obligations": (
        REPO_ROOT
        / "packages/dotmac-response-obligations"
        / "src/dotmac_response_obligations/migrations/versions"
    ),
    "dotmac-sales": (
        REPO_ROOT / "packages/dotmac-sales" / "src/dotmac_sales/migrations/versions"
    ),
    "dotmac-service-access-policy": (
        REPO_ROOT
        / "packages/dotmac-service-access-policy"
        / "src/dotmac_service_access_policy/migrations/versions"
    ),
    "dotmac-services": (
        REPO_ROOT
        / "packages/dotmac-services"
        / "src/dotmac_services/migrations/versions"
    ),
    "dotmac-template-studio": (
        REPO_ROOT
        / "packages/dotmac-template-studio"
        / "src/dotmac_template_studio/migrations/versions"
    ),
    "dotmac-commercial-agreements": (
        REPO_ROOT
        / "packages/dotmac-commercial-agreements"
        / "src/dotmac_commercial_agreements/migrations/versions"
    ),
    "dotmac-people": (
        REPO_ROOT / "packages/dotmac-people" / "src/dotmac_people/migrations/versions"
    ),
    "dotmac-inbox": (
        REPO_ROOT / "packages/dotmac-inbox" / "src/dotmac_inbox/migrations/versions"
    ),
    "dotmac-kernel": (
        REPO_ROOT / "packages/dotmac-kernel" / "src/dotmac_kernel/migrations/versions"
    ),
    "dotmac-accounting": (
        REPO_ROOT
        / "packages/dotmac-accounting"
        / "src/dotmac_accounting/migrations/versions"
    ),
    "dotmac-analytics": (
        REPO_ROOT
        / "packages/dotmac-analytics"
        / "src/dotmac_analytics/migrations/versions"
    ),
    "dotmac-application-directory": (
        REPO_ROOT
        / "packages/dotmac-application-directory"
        / "src/dotmac_application_directory/migrations/versions"
    ),
    "dotmac-assets": (
        REPO_ROOT / "packages/dotmac-assets" / "src/dotmac_assets/migrations/versions"
    ),
    "dotmac-banking": (
        REPO_ROOT / "packages/dotmac-banking" / "src/dotmac_banking/migrations/versions"
    ),
    "dotmac-brand-profiles": (
        REPO_ROOT
        / "packages/dotmac-brand-profiles"
        / "src/dotmac_brand_profiles/migrations/versions"
    ),
    "dotmac-campaigns": (
        REPO_ROOT
        / "packages/dotmac-campaigns"
        / "src/dotmac_campaigns/migrations/versions"
    ),
    "dotmac-content": (
        REPO_ROOT / "packages/dotmac-content" / "src/dotmac_content/migrations/versions"
    ),
    "dotmac-documents": (
        REPO_ROOT
        / "packages/dotmac-documents"
        / "src/dotmac_documents/migrations/versions"
    ),
    "dotmac-durable-timers": (
        REPO_ROOT
        / "packages/dotmac-durable-timers"
        / "src/dotmac_durable_timers/migrations/versions"
    ),
    "dotmac-expenses": (
        REPO_ROOT
        / "packages/dotmac-expenses"
        / "src/dotmac_expenses/migrations/versions"
    ),
    "dotmac-fiber-plant": (
        REPO_ROOT
        / "packages/dotmac-fiber-plant"
        / "src/dotmac_fiber_plant/migrations/versions"
    ),
    "dotmac-finance": (
        REPO_ROOT / "packages/dotmac-finance" / "src/dotmac_finance/migrations/versions"
    ),
    "dotmac-inventory": (
        REPO_ROOT
        / "packages/dotmac-inventory"
        / "src/dotmac_inventory/migrations/versions"
    ),
    "dotmac-ipam": (
        REPO_ROOT / "packages/dotmac-ipam" / "src/dotmac_ipam/migrations/versions"
    ),
    "dotmac-licensing": (
        REPO_ROOT
        / "packages/dotmac-licensing"
        / "src/dotmac_licensing/migrations/versions"
    ),
    "dotmac-media-observations": (
        REPO_ROOT
        / "packages/dotmac-media-observations"
        / "src/dotmac_media_observations/migrations/versions"
    ),
    "dotmac-network-access": (
        REPO_ROOT
        / "packages/dotmac-network-access"
        / "src/dotmac_network_access/migrations/versions"
    ),
    "dotmac-network-assurance": (
        REPO_ROOT
        / "packages/dotmac-network-assurance"
        / "src/dotmac_network_assurance/migrations/versions"
    ),
    "dotmac-network-control": (
        REPO_ROOT
        / "packages/dotmac-network-control"
        / "src/dotmac_network_control/migrations/versions"
    ),
    "dotmac-network-inventory": (
        REPO_ROOT
        / "packages/dotmac-network-inventory"
        / "src/dotmac_network_inventory/migrations/versions"
    ),
    "dotmac-network-observability": (
        REPO_ROOT
        / "packages/dotmac-network-observability"
        / "src/dotmac_network_observability/migrations/versions"
    ),
    "dotmac-network-topology": (
        REPO_ROOT
        / "packages/dotmac-network-topology"
        / "src/dotmac_network_topology/migrations/versions"
    ),
    "dotmac-party": (
        REPO_ROOT / "packages/dotmac-party" / "src/dotmac_party/migrations/versions"
    ),
    "dotmac-payables": (
        REPO_ROOT
        / "packages/dotmac-payables"
        / "src/dotmac_payables/migrations/versions"
    ),
    "dotmac-payroll": (
        REPO_ROOT / "packages/dotmac-payroll" / "src/dotmac_payroll/migrations/versions"
    ),
    "dotmac-pon-access": (
        REPO_ROOT
        / "packages/dotmac-pon-access"
        / "src/dotmac_pon_access/migrations/versions"
    ),
    "dotmac-positioning": (
        REPO_ROOT
        / "packages/dotmac-positioning"
        / "src/dotmac_positioning/migrations/versions"
    ),
    "dotmac-procurement": (
        REPO_ROOT
        / "packages/dotmac-procurement"
        / "src/dotmac_procurement/migrations/versions"
    ),
    "dotmac-projects": (
        REPO_ROOT
        / "packages/dotmac-projects"
        / "src/dotmac_projects/migrations/versions"
    ),
    "dotmac-publishing": (
        REPO_ROOT
        / "packages/dotmac-publishing"
        / "src/dotmac_publishing/migrations/versions"
    ),
    "dotmac-records": (
        REPO_ROOT / "packages/dotmac-records" / "src/dotmac_records/migrations/versions"
    ),
    "dotmac-referrals": (
        REPO_ROOT
        / "packages/dotmac-referrals"
        / "src/dotmac_referrals/migrations/versions"
    ),
    "dotmac-release-catalog": (
        REPO_ROOT
        / "packages/dotmac-release-catalog"
        / "src/dotmac_release_catalog/migrations/versions"
    ),
    "dotmac-reseller-management": (
        REPO_ROOT
        / "packages/dotmac-reseller-management"
        / "src/dotmac_reseller_management/migrations/versions"
    ),
    "dotmac-service-orders": (
        REPO_ROOT
        / "packages/dotmac-service-orders"
        / "src/dotmac_service_orders/migrations/versions"
    ),
    "dotmac-sites": (
        REPO_ROOT / "packages/dotmac-sites" / "src/dotmac_sites/migrations/versions"
    ),
    "dotmac-surveys": (
        REPO_ROOT / "packages/dotmac-surveys" / "src/dotmac_surveys/migrations/versions"
    ),
    "dotmac-web-analytics": (
        REPO_ROOT
        / "packages/dotmac-web-analytics"
        / "src/dotmac_web_analytics/migrations/versions"
    ),
    "dotmac-work-orders": (
        REPO_ROOT
        / "packages/dotmac-work-orders"
        / "src/dotmac_work_orders/migrations/versions"
    ),
    "dotmac-ticketing": (
        REPO_ROOT
        / "packages/dotmac-ticketing"
        / "src/dotmac_ticketing/migrations/versions"
    ),
    "dotmac-deployment-control": (
        REPO_ROOT
        / "packages/dotmac-deployment-control"
        / "src/dotmac_deployment_control/migrations/versions"
    ),
}

#: The glob that enumerates one distribution's lineage on disk. Derived from
#: the module's migration prefix, so the ratchet cannot be defeated by a file
#: the pattern happens not to match.
LINEAGE_GLOBS: dict[str, str] = {
    "dotmac-numbering": "nu_*.py",
    "dotmac-approvals": "ap_*.py",
    "dotmac-integration": "ig_*.py",
    "dotmac-entitlement-allocation": "ea_*.py",
    "dotmac-files": "fi_*.py",
    "dotmac-forms": "fm_*.py",
    "dotmac-workflow-runtime": "wr_*.py",
    "dotmac-platform-health": "ph_*.py",
    "dotmac-support-access": "sup_*.py",
    "dotmac-remote-access": "ra_*.py",
    "dotmac-compliance-reporting": "cr_*.py",
    "dotmac-ai-operations": "ao_*.py",
    "dotmac-payments": "pm_*.py",
    "dotmac-imports": "im_*.py",
    "dotmac-inbox-operations": "io_*.py",
    "dotmac-operational-escalations": "oe_*.py",
    "dotmac-service-changes": "sch_*.py",
    "dotmac-subscriptions": "su_*.py",
    "dotmac-billing": "bi_*.py",
    "dotmac-collections": "cl_*.py",
    "dotmac-fulfillment": "fu_*.py",
    "dotmac-tax": "tx_*.py",
    "dotmac-service-catalog": "sc_*.py",
    "dotmac-customers": "cu_*.py",
    "dotmac-fx-policy": "fx_*.py",
    "dotmac-qualification": "qu_*.py",
    "dotmac-response-obligations": "ro_*.py",
    "dotmac-sales": "sa_*.py",
    "dotmac-service-access-policy": "sap_*.py",
    "dotmac-services": "se_*.py",
    "dotmac-template-studio": "ts_*.py",
    "dotmac-commercial-agreements": "cg_*.py",
    "dotmac-people": "pe_*.py",
    "dotmac-inbox": "ib_*.py",
    "dotmac-kernel": "2*_[0-9][0-9][0-9][0-9]_*.py",
    "dotmac-accounting": "ac_*.py",
    "dotmac-analytics": "ay_*.py",
    "dotmac-application-directory": "ad_*.py",
    "dotmac-assets": "as_*.py",
    "dotmac-banking": "bk_*.py",
    "dotmac-brand-profiles": "bp_*.py",
    "dotmac-campaigns": "ca_*.py",
    "dotmac-content": "ct_*.py",
    "dotmac-documents": "do_*.py",
    "dotmac-durable-timers": "dt_*.py",
    "dotmac-expenses": "ex_*.py",
    "dotmac-fiber-plant": "fp_*.py",
    "dotmac-finance": "fn_*.py",
    "dotmac-inventory": "iv_*.py",
    "dotmac-ipam": "ip_*.py",
    "dotmac-licensing": "li_*.py",
    "dotmac-media-observations": "mo_*.py",
    "dotmac-network-access": "nac_*.py",
    "dotmac-network-assurance": "na_*.py",
    "dotmac-network-control": "nc_*.py",
    "dotmac-network-inventory": "ni_*.py",
    "dotmac-network-observability": "no_*.py",
    "dotmac-network-topology": "nt_*.py",
    "dotmac-party": "pt_*.py",
    "dotmac-payables": "pa_*.py",
    "dotmac-payroll": "py_*.py",
    "dotmac-pon-access": "pn_*.py",
    "dotmac-positioning": "po_*.py",
    "dotmac-procurement": "pc_*.py",
    "dotmac-projects": "pj_*.py",
    "dotmac-publishing": "pb_*.py",
    "dotmac-records": "re_*.py",
    "dotmac-referrals": "rf_*.py",
    "dotmac-release-catalog": "rl_*.py",
    "dotmac-reseller-management": "rm_*.py",
    "dotmac-service-orders": "so_*.py",
    "dotmac-sites": "si_*.py",
    "dotmac-surveys": "sv_*.py",
    "dotmac-web-analytics": "wa_*.py",
    "dotmac-work-orders": "wo_*.py",
    "dotmac-ticketing": "tk_*.py",
    "dotmac-deployment-control": "dc_*.py",
}

TAG_PREFIXES: dict[str, str] = {
    "dotmac-numbering": "dotmac-numbering-v",
    "dotmac-approvals": "dotmac-approvals-v",
    "dotmac-integration": "dotmac-integration-v",
    "dotmac-entitlement-allocation": "dotmac-entitlement-allocation-v",
    "dotmac-files": "dotmac-files-v",
    "dotmac-forms": "dotmac-forms-v",
    "dotmac-workflow-runtime": "dotmac-workflow-runtime-v",
    "dotmac-platform-health": "dotmac-platform-health-v",
    "dotmac-support-access": "dotmac-support-access-v",
    "dotmac-remote-access": "dotmac-remote-access-v",
    "dotmac-compliance-reporting": "dotmac-compliance-reporting-v",
    "dotmac-ai-operations": "dotmac-ai-operations-v",
    "dotmac-payments": "dotmac-payments-v",
    "dotmac-imports": "dotmac-imports-v",
    "dotmac-inbox-operations": "dotmac-inbox-operations-v",
    "dotmac-operational-escalations": "dotmac-operational-escalations-v",
    "dotmac-service-changes": "dotmac-service-changes-v",
    "dotmac-subscriptions": "dotmac-subscriptions-v",
    "dotmac-billing": "dotmac-billing-v",
    "dotmac-collections": "dotmac-collections-v",
    "dotmac-fulfillment": "dotmac-fulfillment-v",
    "dotmac-tax": "dotmac-tax-v",
    "dotmac-service-catalog": "dotmac-service-catalog-v",
    "dotmac-customers": "dotmac-customers-v",
    "dotmac-fx-policy": "dotmac-fx-policy-v",
    "dotmac-qualification": "dotmac-qualification-v",
    "dotmac-response-obligations": "dotmac-response-obligations-v",
    "dotmac-sales": "dotmac-sales-v",
    "dotmac-service-access-policy": "dotmac-service-access-policy-v",
    "dotmac-services": "dotmac-services-v",
    "dotmac-template-studio": "dotmac-template-studio-v",
    "dotmac-commercial-agreements": "dotmac-commercial-agreements-v",
    "dotmac-people": "dotmac-people-v",
    "dotmac-inbox": "dotmac-inbox-v",
    "dotmac-kernel": "dotmac-kernel-v",
    "dotmac-accounting": "dotmac-accounting-v",
    "dotmac-analytics": "dotmac-analytics-v",
    "dotmac-application-directory": "dotmac-application-directory-v",
    "dotmac-assets": "dotmac-assets-v",
    "dotmac-banking": "dotmac-banking-v",
    "dotmac-brand-profiles": "dotmac-brand-profiles-v",
    "dotmac-campaigns": "dotmac-campaigns-v",
    "dotmac-content": "dotmac-content-v",
    "dotmac-documents": "dotmac-documents-v",
    "dotmac-durable-timers": "dotmac-durable-timers-v",
    "dotmac-expenses": "dotmac-expenses-v",
    "dotmac-fiber-plant": "dotmac-fiber-plant-v",
    "dotmac-finance": "dotmac-finance-v",
    "dotmac-inventory": "dotmac-inventory-v",
    "dotmac-ipam": "dotmac-ipam-v",
    "dotmac-licensing": "dotmac-licensing-v",
    "dotmac-media-observations": "dotmac-media-observations-v",
    "dotmac-network-access": "dotmac-network-access-v",
    "dotmac-network-assurance": "dotmac-network-assurance-v",
    "dotmac-network-control": "dotmac-network-control-v",
    "dotmac-network-inventory": "dotmac-network-inventory-v",
    "dotmac-network-observability": "dotmac-network-observability-v",
    "dotmac-network-topology": "dotmac-network-topology-v",
    "dotmac-party": "dotmac-party-v",
    "dotmac-payables": "dotmac-payables-v",
    "dotmac-payroll": "dotmac-payroll-v",
    "dotmac-pon-access": "dotmac-pon-access-v",
    "dotmac-positioning": "dotmac-positioning-v",
    "dotmac-procurement": "dotmac-procurement-v",
    "dotmac-projects": "dotmac-projects-v",
    "dotmac-publishing": "dotmac-publishing-v",
    "dotmac-records": "dotmac-records-v",
    "dotmac-referrals": "dotmac-referrals-v",
    "dotmac-release-catalog": "dotmac-release-catalog-v",
    "dotmac-reseller-management": "dotmac-reseller-management-v",
    "dotmac-service-orders": "dotmac-service-orders-v",
    "dotmac-sites": "dotmac-sites-v",
    "dotmac-surveys": "dotmac-surveys-v",
    "dotmac-web-analytics": "dotmac-web-analytics-v",
    "dotmac-work-orders": "dotmac-work-orders-v",
    "dotmac-ticketing": "dotmac-ticketing-v",
    "dotmac-deployment-control": "dotmac-deployment-control-v",
}

#: Kept for the many call sites that only need integration's directory.
VERSIONS = DISTRIBUTIONS["dotmac-integration"]

#: `tag -> (distribution, exact peeled commit, {filename: sha256 at that tag})`.
#:
#: Every one is an annotated tag created by `release-module.yml` and present on
#: `origin`; the full peeled commit is recorded and cross-checked so the tag
#: object and unchanged migration bytes cannot hide a moved coordinate.
RELEASED_TAGS: dict[str, tuple[str, str, dict[str, str]]] = {
    # ── dotmac-numbering ─────────────────────────────────────────────────────
    # Enrolled after nu_0001 was edited in place AFTER this tag shipped: a
    # `_ALLOWED_FREEZE_ARGUMENTS` allowlist was added to appease bandit B608,
    # which scanned this lineage because it was not in the exclusion list. The
    # emitted DDL was byte-identical and both call sites passed, but the file
    # was not -- and `dotmac_erp` pins a2 AND composes this lineage, so one
    # revision id named two file contents in a database this repository cannot
    # inspect. The file is restored to these bytes in the same change.
    "dotmac-numbering-v0.1.0a2": (
        "dotmac-numbering",
        "4c282228b53405442effc4159f5db9d50446d335",
        {
            "nu_0001_numbering.py": (
                "9c3079774b0db615ea5d4c6ca121a9ed43688236bbc5f0a0166a2906513da561"
            ),
        },
    ),
    # ── dotmac-approvals ────────────────────────────────────────────────────
    # ap_0001 was edited in place twice before this guard enrolled the module.
    # The exact three historical byte sets are recorded here; the explicit
    # grandfathered-divergence ledger below decides which one the tree retains.
    "dotmac-approvals-v0.1.0a8": (
        "dotmac-approvals",
        "9e2d69f4913474d9504cfaeca81a9105919b8555",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
            "ap_0002_outbox_relay.py": (
                "6aace60a4925ad5f5c693b81a356807c1ad2b9ffe1664fdfcd1417429d127e2d"
            ),
            "ap_0003_withdrawals.py": (
                "6446e2301fbe4ca0401835a320cee8948fbc9912e7d8c3ddd294d90854e78c36"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a7": (
        "dotmac-approvals",
        "7cab65c56272c1d8e3a2784ce5b91ce601dd9b05",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
            "ap_0002_outbox_relay.py": (
                "6aace60a4925ad5f5c693b81a356807c1ad2b9ffe1664fdfcd1417429d127e2d"
            ),
            "ap_0003_withdrawals.py": (
                "6446e2301fbe4ca0401835a320cee8948fbc9912e7d8c3ddd294d90854e78c36"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a1": (
        "dotmac-approvals",
        "221f6868651426397e6e8443ca8b544234648247",
        {
            "ap_0001_approvals.py": (
                "ec5e1aa9e504de8143eebaafacb0615cf24b6ea930648f5b9cfd1a9afc2db70e"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a2": (
        "dotmac-approvals",
        "3e1f8012c4f45369b6801a709a270d71c5c95a8d",
        {
            "ap_0001_approvals.py": (
                "6c7b3263e05f860982dda125439171f62bba716d36d95b21e2c3a3224f19ad6a"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a3": (
        "dotmac-approvals",
        "16f11a9ef0df7697558904efa969294bafc3fab3",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a4": (
        "dotmac-approvals",
        "f013c7e0e0be9f704d3afbc13e233fde8950a1be",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a5": (
        "dotmac-approvals",
        "8d4ddfd9e285da06ce1fdd29b59f1b483d6ea38c",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
            "ap_0002_outbox_relay.py": (
                "6aace60a4925ad5f5c693b81a356807c1ad2b9ffe1664fdfcd1417429d127e2d"
            ),
        },
    ),
    "dotmac-approvals-v0.1.0a6": (
        # a6's migration bytes are identical to a5, but the recorded commit is
        # THIS tag's own peeled commit, per test_each_recorded_commit_is_the_
        # exact_peeled_tag — never a prior release's commit.
        "dotmac-approvals",
        "dc94adbb2469ce4b8f75b3e61d9b10cba0e65b77",
        {
            "ap_0001_approvals.py": (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
            ),
            "ap_0002_outbox_relay.py": (
                "6aace60a4925ad5f5c693b81a356807c1ad2b9ffe1664fdfcd1417429d127e2d"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a17": (
        "dotmac-integration",
        "2cab76b442e6cc6c8ed81a409d943ba250351c3d",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
            "ig_0012_delivery_evidence.py": (
                "61ef4e096dae74b7646608257614f4497af125edda63a6c270e402a63c2cfdd3"
            ),
            "ig_0013_delivery_result.py": (
                "28dfc210785c3c22a8d883239fe37727cbf14dc80e7e26058df4d32f387f14ea"
            ),
            "ig_0014_polling_evidence.py": (
                "07dea79c6650aefd205bb67500abf08cb9f0464766d470bb218ec181302549be"
            ),
            "ig_0015_descriptor_contract.py": (
                "ea7f03fcd60eee9688846f67934b9d56a5451020e46514ad8a379bd8e8b85503"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a16": (
        "dotmac-integration",
        "dcab4559b6dcc2c38737dd65ce6bb2f5ba59df0e",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
            "ig_0012_delivery_evidence.py": (
                "61ef4e096dae74b7646608257614f4497af125edda63a6c270e402a63c2cfdd3"
            ),
            "ig_0013_delivery_result.py": (
                "28dfc210785c3c22a8d883239fe37727cbf14dc80e7e26058df4d32f387f14ea"
            ),
            "ig_0014_polling_evidence.py": (
                "07dea79c6650aefd205bb67500abf08cb9f0464766d470bb218ec181302549be"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a15": (
        "dotmac-integration",
        "bd8d2262c26f62041cc22a813916066b9af85c7f",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
            "ig_0012_delivery_evidence.py": (
                "61ef4e096dae74b7646608257614f4497af125edda63a6c270e402a63c2cfdd3"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a14": (
        "dotmac-integration",
        "70459efd468dd2dcc9e31693b9910b04fec21447",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
            "ig_0012_delivery_evidence.py": (
                "61ef4e096dae74b7646608257614f4497af125edda63a6c270e402a63c2cfdd3"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a13": (
        "dotmac-integration",
        "46926fa4f4243f7cd0c00230684eef8ab25cf723",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a1": (
        "dotmac-integration",
        "1b1d62bebc4651273b2587fb607c49485fed123a",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a2": (
        "dotmac-integration",
        "aaa3b5435732f0b1bebdf894778d6615c05e3c12",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
        },
    ),
    # a3 is a Python-only fix (`ModeContractError` sanitisation, #201) shipped
    # with the same six migrations. Recorded anyway: "the lineage did not
    # change" is a claim, and an entry per tag is what checks it.
    "dotmac-integration-v0.1.0a3": (
        "dotmac-integration",
        "b14f66e65642ec636936ea649ad0e86249b6de5a",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
        },
    ),
    # a4 adds the DDL-free prerequisite verification revision. Its bytes are
    # now published history and may not remain in the editable set below.
    "dotmac-integration-v0.1.0a4": (
        "dotmac-integration",
        "306a40e29da8fa63a6ee9346f29665731b558cc5",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
        },
    ),
    # a5 is a Python/SPI release. It repeats a4's seven migration digests, which
    # is still a release-history fact rather than permission to omit the tag.
    "dotmac-integration-v0.1.0a5": (
        "dotmac-integration",
        "7828697ef11fb1ae765a5397dfa7dc221ae6207a",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
        },
    ),
    # a6 adds the DDL-free platform-audit prerequisite verifier. It was
    # published from main before the product-port branch merged, so ig_0009 is
    # deliberately absent from this immutable release record.
    "dotmac-integration-v0.1.0a6": (
        "dotmac-integration",
        "7e0543004864845f0035c9ec325e3f5064c281cc",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
        },
    ),
    # a7 adds immutable product-port descriptor provenance and receipt-owned
    # provider identity. It was published from main while the independent
    # shadow-evidence branch was being rebased, so only ig_0010 remains
    # editable after this release record is reconciled.
    "dotmac-integration-v0.1.0a7": (
        "dotmac-integration",
        "c669b24ee8be09677e92f85b11619f6626ad998d",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
        },
    ),
    # a8 adds the module-owned, indexed shadow-comparison evidence table. The
    # release workflow installed the exact published wheel from the private
    # index, registered its manifest and only then created this tag.
    "dotmac-integration-v0.1.0a8": (
        "dotmac-integration",
        "4b1e86753b010a60be38bb5346f89e493936d2f4",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
        },
    ),
    # a9 makes replay evidence finite and makes released legal-hold history
    # survive an eligible receipt delete. The release workflow installed the
    # exact wheel from the private index before creating this tag.
    "dotmac-integration-v0.1.0a9": (
        "dotmac-integration",
        "92ae7a6f9c8307797704deb615a24e59420a73c4",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
        },
    ),
    # a10 adds SPI 1.3 runtime declarations and changes no migration bytes.
    # The release workflow installed the exact wheel from the private index,
    # registered its manifest and only then created this tag.
    # a11 records the finite replay-evidence retention already on main; the
    # migration bytes are unchanged from a10 apart from ig_0011. The release
    # workflow installed the exact wheel from the private index, registered its
    # manifest and only then created this tag.
    "dotmac-integration-v0.1.0a12": (
        "dotmac-integration",
        "9f59d02b47ec9aa6a594705e12b2032a7168ae46",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a11": (
        "dotmac-integration",
        "f25df1adf7076634abc735546158c374eedd6c31",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
        },
    ),
    "dotmac-integration-v0.1.0a10": (
        "dotmac-integration",
        "7a5986420881e3e49945efc1dc51c653070e73b3",
        {
            "ig_0001_connector_control_plane.py": (
                "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            ),
            "ig_0002_execution.py": (
                "745f1b23ccaf45964099c41b6aa5ee7a63b2623a3cf9a1c3736000046ae33d42"
            ),
            "ig_0003_ingress_endpoint.py": (
                "feb1a66e2f0f1558bea00a221c02a9e1da5a4bc6536c35a93805d0681f670066"
            ),
            "ig_0004_destinations.py": (
                "80da09cbb492006a3cf6334466d4c79e3ee6cce676013edfb897845b09d38201"
            ),
            "ig_0005_receipt_delivery.py": (
                "b762d17591ccd877143c36a72269b083adab13ab3a57e326b20aa9dd3d99371d"
            ),
            "ig_0006_retention.py": (
                "51a40ae5290e71baa2879b9bb87ea7bb06f75d5372ebdfc378eed6e836a42aaa"
            ),
            "ig_0007_idempotency_ledger.py": (
                "9f6336e88e016c37d8c5a1b6d0548f8a5a91bde6e41a5093676709136c68e54b"
            ),
            "ig_0008_platform_audit_log.py": (
                "1e2cb215be0e71edf1af33b41cd53630ba9583168c2ff270c568483fdff15825"
            ),
            "ig_0009_product_port_descriptors.py": (
                "f95ec953d0ec9d561b5d7d438d1865e817fc4d15b2178c87e5f67350a07ab2d9"
            ),
            "ig_0010_shadow_evidence.py": (
                "eb897df97435c63ec4844753d8afa497391fa2eabfa0673312725995c231b4ed"
            ),
            "ig_0011_replay_retention.py": (
                "96336372ac879518ad46f6657b8c81cf60afd133d500c4bc6310017f94c59b42"
            ),
        },
    ),
    # ── dotmac-entitlement-allocation ───────────────────────────────────────
    #
    # Four tags, one migration, one digest. `ea_0001` has not moved a byte
    # since `0.1.0a1`: a2 exposed `versions_dir()`, a3 made the ORM
    # relationships class-bound, and a4 moved the tables from the `tables=`
    # slot to `platform_tables=` — all three are Python-only, and the fourth
    # changed a manifest declaration rather than any DDL.
    #
    # That is exactly the history that makes an in-place edit tempting: four
    # releases with nothing to show for them in this directory reads as "the
    # migration is still ours". It is not — those bytes have run in databases
    # this repository does not own, which is why `ea_0002` exists as its own
    # head instead of a `require_prerequisites` line appended to `ea_0001`.
    "dotmac-entitlement-allocation-v0.1.0a1": (
        "dotmac-entitlement-allocation",
        "847ce0b5ea89dabdc34c26029df86173da80a4ab",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
        },
    ),
    "dotmac-entitlement-allocation-v0.1.0a2": (
        "dotmac-entitlement-allocation",
        "5ded8808e376b2eeaf6150bf095077ba1ba3de5b",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
        },
    ),
    "dotmac-entitlement-allocation-v0.1.0a3": (
        "dotmac-entitlement-allocation",
        "c371b0fdbb22bd3d51fd34d36922b9bc1e9dae68",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
        },
    ),
    "dotmac-entitlement-allocation-v0.1.0a4": (
        "dotmac-entitlement-allocation",
        "67bdfb8b404a92fd455473806a256995bb507524",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
        },
    ),
    # a5 was never published. a6 is the next release and freezes both DDL-free
    # verifier revisions alongside the unchanged allocation table revision.
    "dotmac-entitlement-allocation-v0.1.0a6": (
        "dotmac-entitlement-allocation",
        "7e0543004864845f0035c9ec325e3f5064c281cc",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
            "ea_0002_idempotency_ledger.py": (
                "56076edb3f086b6e00b510df95d7af3b35153e8795f7b66754c89a2ad90032c2"
            ),
            "ea_0003_platform_audit_log.py": (
                "63027541404d7f9c824cade44c247098aa5f19bdb6d70cf321c1452974e0e072"
            ),
        },
    ),
    "dotmac-entitlement-allocation-v0.1.0a7": (
        # a7 adds only a database_catalog= manifest declaration; the migration
        # lineage is byte-identical to a6, so the same digests apply. Commit
        # is this tag's own peeled commit, per
        # test_each_recorded_commit_is_the_exact_peeled_tag.
        "dotmac-entitlement-allocation",
        "c9de0a1b65a816e38b13bb6cc892b2a05bd653eb",
        {
            "ea_0001_allocations.py": (
                "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            ),
            "ea_0002_idempotency_ledger.py": (
                "56076edb3f086b6e00b510df95d7af3b35153e8795f7b66754c89a2ad90032c2"
            ),
            "ea_0003_platform_audit_log.py": (
                "63027541404d7f9c824cade44c247098aa5f19bdb6d70cf321c1452974e0e072"
            ),
        },
    ),
    # ── dotmac-files ────────────────────────────────────────────────────────
    # a2's root is the published atomic catalogue. a3 adds fi_0002 rather than
    # changing this digest, so an existing a2 installation and a fresh a3
    # installation converge through an ordinary Alembic upgrade.
    "dotmac-files-v0.1.0a4": (
        "dotmac-files",
        "df85e47267cd9093d063f93725b0ef2d2c0c6fab",
        {
            "fi_0001_stored_files.py": (
                "58976eab44ccfaaa77af255c52f92ef333e650e89ee3f6808211820b3c3b4fd0"
            ),
            "fi_0002_selectable_planes.py": (
                "9cdaf0da282402777d6c2e694c60d29f8078a0d48c64211e9a6a67dc1ac05581"
            ),
        },
    ),
    "dotmac-files-v0.1.0a2": (
        "dotmac-files",
        "b3e47855f14433c626b4ac3e7723414f7834601a",
        {
            "fi_0001_stored_files.py": (
                "58976eab44ccfaaa77af255c52f92ef333e650e89ee3f6808211820b3c3b4fd0"
            ),
        },
    ),
    "dotmac-files-v0.1.0a3": (
        "dotmac-files",
        "c6ef6cd7b13105bd95c3faf354ffee9032077625",
        {
            "fi_0001_stored_files.py": (
                "58976eab44ccfaaa77af255c52f92ef333e650e89ee3f6808211820b3c3b4fd0"
            ),
            "fi_0002_selectable_planes.py": (
                "9cdaf0da282402777d6c2e694c60d29f8078a0d48c64211e9a6a67dc1ac05581"
            ),
        },
    ),
    # ── the ADR-0040 composable-unit cohort ─────────────────────────────────
    #
    # Seven modules published in one serial series on 2026-08-22, each from the
    # same protected-main revision, each composition-checked against every
    # sibling already published and kernel 0.1.0a88. Enrolled here at their
    # FIRST release rather than after an in-place edit forced the issue, which
    # is the only cheap moment to do it: one migration, one digest, no history
    # to reconstruct and no divergence to grandfather.
    "dotmac-forms-v0.1.0a1": (
        "dotmac-forms",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "fm_0001_forms.py": (
                "0778d4f950acf049851c6876dcd5d34bb6ef23f37a4dcc35c6af38af3e6b8267"
            ),
        },
    ),
    "dotmac-workflow-runtime-v0.1.0a1": (
        "dotmac-workflow-runtime",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "wr_0001_runtime.py": (
                "f959ef451f951e8c1bf314f8e1e4438731685f5aaf040c8a01bae4da3bb8311f"
            ),
        },
    ),
    "dotmac-platform-health-v0.1.0a1": (
        "dotmac-platform-health",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "ph_0001_platform_health.py": (
                "ed2be6b9a295f0e5a25f45c8d32e4168a33a25ecc4a59a69b0633606c1d52b9e"
            ),
        },
    ),
    "dotmac-support-access-v0.1.0a1": (
        "dotmac-support-access",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "sup_0001_support_access.py": (
                "22b75f92e04756cf05bffce76e303b06a7afbb3170b527f180477657351890a9"
            ),
        },
    ),
    "dotmac-remote-access-v0.1.0a1": (
        "dotmac-remote-access",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "ra_0001_remote_access.py": (
                "8958e4cb85ac62a1c923a62b7a4b4b25691e32a085dc81639f5f642b283f377a"
            ),
        },
    ),
    "dotmac-compliance-reporting-v0.1.0a1": (
        "dotmac-compliance-reporting",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "cr_0001_compliance_reporting.py": (
                "82e16095b9ae50f397010657755fb95b18444052aca9222490f0c2dd6a7fcf31"
            ),
        },
    ),
    "dotmac-ai-operations-v0.1.0a1": (
        "dotmac-ai-operations",
        "8f52abc4f903d001f9fbb5dfd9bfe87434e1f2ce",
        {
            "ao_0001_ai_operations.py": (
                "211d35dfd814d6c93a5e984053c60a1a2444c176b5aa8d08066261f9cfd96538"
            ),
        },
    ),
    # ── dotmac-payments ──
    "dotmac-payments-v0.1.0a1": (
        "dotmac-payments",
        "04b9771320b865b66d1322660fc6d3590605c973",
        {
            "pm_0001_payment_intents.py": (
                "d3f253970bfb6ef1e98289bff1dc2853bf4964a995d406a92529527d3bdb55db"
            ),
        },
    ),
    # ── dotmac-imports ──
    "dotmac-imports-v0.1.0a2": (
        "dotmac-imports",
        "5876ffd0bce17172fa2dc6ac6d09b48d877fadf8",
        {
            "im_0001_import_runs.py": (
                "c6d6caa3765bf133da66f1c6fe9decb179a3a2a7638ec404e3bcae7dc4f5109a"
            ),
        },
    ),
    # ── dotmac-inbox-operations ──
    "dotmac-inbox-operations-v0.1.0a3": (
        "dotmac-inbox-operations",
        "5b2798b80f6ac903fb132a0b1c205dd1dde3c528",
        {
            "io_0001_inbox_operations.py": (
                "180e422c920b43cadbd05a52ac2c72b423a952a9f70094f5372ff29f1b932aa0"
            ),
            "io_0002_queue_admission.py": (
                "0ff834e0cf7082c211e685d5e5ae292283a90e2d83da796e4dc2944a32948a32"
            ),
            "io_0003_operational_safety.py": (
                "26607110cf3001f0134ec9942a85ef0eb96866968b0502f978c8529352394ac3"
            ),
        },
    ),
    # ── dotmac-operational-escalations ──
    "dotmac-operational-escalations-v0.1.0a1": (
        "dotmac-operational-escalations",
        "c006da75d4c04eb6e5b2f9fec715edebcbcdea30",
        {
            "oe_0001_escalation_policy.py": (
                "05928af9f19dd89c98d082c79076510d6519c6d418f3e907f080f56e9a394d3a"
            ),
        },
    ),
    # ── dotmac-service-changes ──
    "dotmac-service-changes-v0.1.0a1": (
        "dotmac-service-changes",
        "c7571b9cbe3ddc9f5687f208a39930001ace8401",
        {
            "sch_0001_service_changes.py": (
                "a01c0e1056246ab39a7420e1364b644c7c2d56a4959fe5ac76298fd612cda20a"
            ),
        },
    ),
    # ── dotmac-subscriptions ──
    "dotmac-subscriptions-v0.1.0a3": (
        "dotmac-subscriptions",
        "ad6c5824086f6f550447caeabe820e860cdfe23c",
        {
            "su_0001_subscriptions.py": (
                "bbc6a1da801259a734988c976800c404ce30f4a3b8cf3f24a48410f557e3f252"
            ),
            "su_0002_offer_pricing.py": (
                "3b1a8524cfd585bac895f63bf7a8f3dc1d9521cfd997b80f379488e31fd21210"
            ),
            "su_0003_billing_treatments.py": (
                "ccdb960c3ed40f852d913a640d12903b86acad481e95c3a87f59ce7e69e129dc"
            ),
        },
    ),
    "dotmac-subscriptions-v0.1.0a2": (
        "dotmac-subscriptions",
        "f91253d5e193918507e9f2e0768a76aefe5bbce0",
        {
            "su_0001_subscriptions.py": (
                "bbc6a1da801259a734988c976800c404ce30f4a3b8cf3f24a48410f557e3f252"
            ),
            "su_0002_offer_pricing.py": (
                "3b1a8524cfd585bac895f63bf7a8f3dc1d9521cfd997b80f379488e31fd21210"
            ),
        },
    ),
    "dotmac-subscriptions-v0.1.0a1": (
        "dotmac-subscriptions",
        "ffe483fb53f12dd7aee400a39e0c85ecf308470f",
        {
            "su_0001_subscriptions.py": (
                "bbc6a1da801259a734988c976800c404ce30f4a3b8cf3f24a48410f557e3f252"
            ),
        },
    ),
    # ── dotmac-billing ──
    "dotmac-billing-v0.1.0a1": (
        "dotmac-billing",
        "92a1626b16d7e068f92536d8cfcb2ef9b6f270c2",
        {
            "bi_0001_billing.py": (
                "f82a962e7c0745cf11e2c8187042a5af412dd80a254be5b2e0975d0c7aa36373"
            ),
        },
    ),
    # ── dotmac-collections ──
    "dotmac-collections-v0.1.0a1": (
        "dotmac-collections",
        "6ecf518a6985b8bf4b163eccb3de2fef171ecccc",
        {
            "cl_0001_collections.py": (
                "f718c94d4044bb925da92aa9e186ee1c0765d4e5d67b1bbc6bc66ccf161d86f4"
            ),
        },
    ),
    # ── dotmac-fulfillment ──
    "dotmac-fulfillment-v0.1.0a1": (
        "dotmac-fulfillment",
        "be02e28d11a0ba849b4974273f5a2d4bd7806a4a",
        {
            "fu_0001_fulfillment.py": (
                "fa41945d34a08fc7f96d529f7ccc1f103a2b90b5c7095153dcc08f4283afe254"
            ),
        },
    ),
    # ── dotmac-tax ──
    "dotmac-tax-v0.1.0a4": (
        "dotmac-tax",
        "fb7fb252c6fba8e15d7c39ed18f8057057adfbab",
        {
            "tx_0001_tax.py": (
                "bf3091556eb5eac401e64cfe342a2d59c17b7d511c0c772aef034340b07012ab"
            ),
            "tx_0002_multi_tax.py": (
                "9b78094519fe8d0785735f3a4e3a37dacdb9901b88eda25c90cdb167474abde0"
            ),
            "tx_0003_result_fingerprint.py": (
                "dd9751218ce7e27922a6ae4a869f6b25061dfa4bb93e0db7e152ea834579d4b3"
            ),
        },
    ),
    "dotmac-tax-v0.1.0a3": (
        "dotmac-tax",
        "531f7f8c37ce2fdf41ecbf2f9a7a9940264a18f9",
        {
            "tx_0001_tax.py": (
                "bf3091556eb5eac401e64cfe342a2d59c17b7d511c0c772aef034340b07012ab"
            ),
            "tx_0002_multi_tax.py": (
                "9b78094519fe8d0785735f3a4e3a37dacdb9901b88eda25c90cdb167474abde0"
            ),
            "tx_0003_result_fingerprint.py": (
                "dd9751218ce7e27922a6ae4a869f6b25061dfa4bb93e0db7e152ea834579d4b3"
            ),
        },
    ),
    "dotmac-tax-v0.1.0a2": (
        "dotmac-tax",
        "bd8d2262c26f62041cc22a813916066b9af85c7f",
        {
            "tx_0001_tax.py": (
                "bf3091556eb5eac401e64cfe342a2d59c17b7d511c0c772aef034340b07012ab"
            ),
            "tx_0002_multi_tax.py": (
                "9b78094519fe8d0785735f3a4e3a37dacdb9901b88eda25c90cdb167474abde0"
            ),
        },
    ),
    "dotmac-tax-v0.1.0a1": (
        "dotmac-tax",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "tx_0001_tax.py": (
                "bf3091556eb5eac401e64cfe342a2d59c17b7d511c0c772aef034340b07012ab"
            ),
        },
    ),
    # ── dotmac-service-catalog ──
    "dotmac-service-catalog-v0.1.0a1": (
        "dotmac-service-catalog",
        "f91253d5e193918507e9f2e0768a76aefe5bbce0",
        {
            "sc_0001_technical_catalog.py": (
                "7fc940ad1ddb48adb2fec31201756b48b48fae90b466fc2aca1d0901eb0c6547"
            ),
        },
    ),
    # ── dotmac-customers ──
    "dotmac-customers-v0.1.0a1": (
        "dotmac-customers",
        "2e2e0eff49aafc54a84885007402cd6012073330",
        {
            "cu_0001_customer_accounts.py": (
                "0a6ba209d80c4dabf40e40dd4023b1d08803c92ed904fde95869ad9e480256c9"
            ),
        },
    ),
    # ── dotmac-fx-policy ──
    "dotmac-fx-policy-v0.1.0a1": (
        "dotmac-fx-policy",
        "a0901915c6dcc5cd0580cb86d942dd3e91507d76",
        {
            "fx_0001_fx_policy.py": (
                "e8e89ed213ff468efba088b20b4dce0e81940d7abbfeb2bff580330948d9b134"
            ),
        },
    ),
    # ── dotmac-qualification ──
    "dotmac-qualification-v0.1.0a1": (
        "dotmac-qualification",
        "3922235907ae83ab0d241d07793a7db2830c7366",
        {
            "qu_0001_qualification_evidence.py": (
                "85afb29ec41ab7dde076ddd3e6d64e1b959563ee8ea54ac776a5ff295e5ef930"
            ),
        },
    ),
    # ── dotmac-response-obligations ──
    "dotmac-response-obligations-v0.1.0a1": (
        "dotmac-response-obligations",
        "8afbd7db7a3c9cdf2b47a54355fd67da4c38f45d",
        {
            "ro_0001_response_obligations.py": (
                "24f9755152d8a688a96f4416173e64bc1ad337ee90cdf21c56f550a0260620a5"
            ),
        },
    ),
    # ── dotmac-sales ──
    "dotmac-sales-v0.1.0a1": (
        "dotmac-sales",
        "1eef66eddcde3cb051886e5a2a61bdb30dc972a5",
        {
            "sa_0001_sales.py": (
                "25d918ceda444edf244ca96096d02283682f8f46c014171138ae47900cfa2553"
            ),
        },
    ),
    # ── dotmac-service-access-policy ──
    "dotmac-service-access-policy-v0.1.0a1": (
        "dotmac-service-access-policy",
        "1029354b0619fa356cc43651c7f26a4ebaf0ac60",
        {
            "sap_0001_access_policy.py": (
                "7dc2cb8f39891bc2b963a77771cf33f8ce3f5c5d5010007a445af4ed7dccec54"
            ),
        },
    ),
    # ── dotmac-services ──
    "dotmac-services-v0.1.0a1": (
        "dotmac-services",
        "63169d01bff8a93503100464ca16aaa450fe0557",
        {
            "se_0001_service_lifecycle.py": (
                "6daef5fde446a943b5cbab8d2dd2948c75d432a177217ffef0ffe495dc0a00bb"
            ),
        },
    ),
    # ── dotmac-template-studio ──
    "dotmac-template-studio-v0.2.0a4": (
        "dotmac-template-studio",
        "ac5e439e622ec5adba94cf52f4f961f2c39a2d30",
        {
            "ts_0001_templates.py": (
                "511073d3225c8fa9be09c687500e0515efbb5d8fdc4859791e1e4f16ed7308f4"
            ),
            "ts_0002_notification_identity.py": (
                "b50c2387f54a877cf0f0ff772bcfc84083a973595c490d6facf6bf7a8f196088"
            ),
        },
    ),
    "dotmac-template-studio-v0.2.0a3": (
        "dotmac-template-studio",
        "5777ceb5b41414c389036342ed58262bbfb97f31",
        {
            "ts_0001_templates.py": (
                "511073d3225c8fa9be09c687500e0515efbb5d8fdc4859791e1e4f16ed7308f4"
            ),
            "ts_0002_notification_identity.py": (
                "b50c2387f54a877cf0f0ff772bcfc84083a973595c490d6facf6bf7a8f196088"
            ),
        },
    ),
    # ── dotmac-commercial-agreements ──
    "dotmac-commercial-agreements-v0.1.0a1": (
        "dotmac-commercial-agreements",
        "fead57bc93d6551450f5e6ae1c9de1296e27b0ae",
        {
            "cg_0001_agreements.py": (
                "ac9e5f698f1814381a5987274131b186e9b0c0237b03314164cd69aa3806ec38"
            ),
        },
    ),
    "dotmac-commercial-agreements-v0.1.0a2": (
        "dotmac-commercial-agreements",
        "42acc8b30f1bcaed1580d312fd33d7b5ef358817",
        {
            "cg_0001_agreements.py": (
                "ac9e5f698f1814381a5987274131b186e9b0c0237b03314164cd69aa3806ec38"
            ),
        },
    ),
    "dotmac-commercial-agreements-v0.1.0a3": (
        # a3's migration bytes are identical to a2, but the recorded commit is
        # THIS tag's own peeled commit, per test_each_recorded_commit_is_the_
        # exact_peeled_tag — never a prior release's commit.
        "dotmac-commercial-agreements",
        "5005e998a4cac9b4f7e3ba91f371967b0ee8b2a2",
        {
            "cg_0001_agreements.py": (
                "ac9e5f698f1814381a5987274131b186e9b0c0237b03314164cd69aa3806ec38"
            ),
        },
    ),
    # ── dotmac-people ──
    "dotmac-people-v0.1.0a2": (
        "dotmac-people",
        "636a97f95a2648e5f10a6e945578630a7499a989",
        {
            "pe_0001_people_directory.py": (
                "ce988433dc698af381ff8b9968ed127b9d3090d373c6b6c12115759113e6ec7f"
            ),
        },
    ),
    "dotmac-people-v0.1.0a1": (
        "dotmac-people",
        "459569afdc6df6b78357d10277cee15820142fc9",
        {
            "pe_0001_people_directory.py": (
                "ce988433dc698af381ff8b9968ed127b9d3090d373c6b6c12115759113e6ec7f"
            ),
        },
    ),
    # ── dotmac-inbox ──
    "dotmac-inbox-v0.1.0a2": (
        "dotmac-inbox",
        "c3e651cf3e220a64ab3dd51cdf7c98553c0997e8",
        {
            "ib_0001_conversations.py": (
                "cd9b7a6189ecf7fde8b2d55279b5a5feff68947b2639de6cdb566c4422349a53"
            ),
        },
    ),
    "dotmac-inbox-v0.1.0a1": (
        "dotmac-inbox",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "ib_0001_conversations.py": (
                "cd9b7a6189ecf7fde8b2d55279b5a5feff68947b2639de6cdb566c4422349a53"
            ),
        },
    ),
    # ── dotmac-kernel ────────────────────────────────────────────────────────
    # Enrolled 2026-09-01. The kernel is deliberately absent from
    # `.github/release-modules.json` -- it has its own lane
    # (`.github/workflows/release-kernel.yml`), which is why the census below
    # reads the sweep's `DEDICATED_WORKFLOWS` rather than the module allowlist
    # alone. Absence from that allowlist was never a statement that the kernel
    # has no released bytes: it has 61 published tags and every product in the
    # fleet pins one, so an in-place edit to any file here reaches more
    # databases this repository cannot inspect than every module lineage
    # combined.
    "dotmac-kernel-v0.1.0a104": (
        "dotmac-kernel",
        "bf16e30efc3321ca9a495de31570bb5f9a02e9e3",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a103": (
        "dotmac-kernel",
        "2e6613322c386e996565c8449b6c3672c9efd956",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a102": (
        "dotmac-kernel",
        "7a3c128b06eaba09784a9d8409d036169b3caa68",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a101": (
        "dotmac-kernel",
        "037ef065376c0ad4597cc59f86f4ef3eb7d5322b",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a100": (
        "dotmac-kernel",
        "917181b38dcc5954bac932b630909afdfb19012b",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a99": (
        "dotmac-kernel",
        "8c92943062dbfe7f17bfa35264243709ec3d92c3",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a98": (
        "dotmac-kernel",
        "ae7320876ad91d5bf4639d634d65a6e8fd36bb00",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a97": (
        "dotmac-kernel",
        "548084fd74779ccf1ad436e1201e03cb9239631a",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
            "20260824_0028_machine_attribution.py": (
                "baa27e0134ae97ac5b6f10c7d0f47e391187589fa8a7cb8ee70f81eaa8b3e01c"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a95": (
        "dotmac-kernel",
        "188f5eb907a43fb67978d193e7482a57896f84a3",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a94": (
        "dotmac-kernel",
        "9e717eb88603f6ef61bded23b2aa468fe4533a95",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a93": (
        "dotmac-kernel",
        "8537a9bcb45464af36811a603463c0cfa71f2e4f",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a92": (
        "dotmac-kernel",
        "720eeb0a2e5c623ba27837ff9183ffd7958ba5f7",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a91": (
        "dotmac-kernel",
        "6c6a38b06829cd7904c52d3a10bb429db2e8ba35",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a90": (
        "dotmac-kernel",
        "4999bc492f58a2af60dd87d8b4a25fbb76751918",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
            "20260822_0027_machine_credential.py": (
                "2b6511e955f947203a838c3a1b57c967da149b1f238a9aef4f17ccf900a636ea"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a89": (
        "dotmac-kernel",
        "17e395d3676bfc50d9cfbe79b5fd819859c0f528",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a88": (
        "dotmac-kernel",
        "8673a2d943c63ae90931b7be3603b8e66f35668b",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a86": (
        "dotmac-kernel",
        "8b8e3d26f4b344cf1ed7444e9a2e3836c7115f30",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a85": (
        "dotmac-kernel",
        "b0310103994618a078eb7a7a1b300c17504eeb49",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a83": (
        "dotmac-kernel",
        "4cfdcd76739c9ad6c6dc249c1093849db7c3b752",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a81": (
        "dotmac-kernel",
        "8f99413826e5adf3d35379ebc6deb79bcb5c8242",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a77": (
        "dotmac-kernel",
        "fead57bc93d6551450f5e6ae1c9de1296e27b0ae",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a73": (
        "dotmac-kernel",
        "cfa9df8ac8d4f6c2b4faa92d6724be7ae767bbe7",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a72": (
        "dotmac-kernel",
        "f7d69f7d3db6a36dcccaa847dff7a37e9c3cd685",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a71": (
        "dotmac-kernel",
        "459569afdc6df6b78357d10277cee15820142fc9",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a70": (
        "dotmac-kernel",
        "c37b40db9d21869f42c4b9acdcb4f7f1bb9a2233",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a69": (
        "dotmac-kernel",
        "7c93ebf9d5ac8805029fe2c978d7732c0bc4f694",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a68": (
        "dotmac-kernel",
        "7b20d1567850aa663bd887b70766efc8013db67d",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
            "20260816_0026_platform_audit_log.py": (
                "6d54d2f910509015481e9322abae2fa669a0fb260406d2845979ed8ea5218d18"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a67": (
        "dotmac-kernel",
        "ed3ac864b350d4556808a69496f999f764682442",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
            "20260816_0025_session_provenance.py": (
                "179d452235332892efb078fd14b2e84ab13709c797515b6681c41a25d7cd8083"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a66": (
        "dotmac-kernel",
        "4c282228b53405442effc4159f5db9d50446d335",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a65": (
        "dotmac-kernel",
        "1e9c4332dc1dbc2cc81fd18ba3401a079c81d839",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a64": (
        "dotmac-kernel",
        "c680621fd8bbf99f8f5a4749743191beb1894724",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a63": (
        "dotmac-kernel",
        "67bdfb8b404a92fd455473806a256995bb507524",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
            "20260814_0024_external_identity_bindings.py": (
                "fa7875d51524b3bd1a01b2e27b0f32a3521fdd1316b96b08f3cea09c738d3bef"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a62": (
        "dotmac-kernel",
        "7556b96e8751d46a8bf3cb014b95a9a64eb03b0c",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a61": (
        "dotmac-kernel",
        "16f11a9ef0df7697558904efa969294bafc3fab3",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a60": (
        "dotmac-kernel",
        "3e1f8012c4f45369b6801a709a270d71c5c95a8d",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a59": (
        "dotmac-kernel",
        "49f9ccf6738a01a524ccbb450b27f92eb3b2565c",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a58": (
        "dotmac-kernel",
        "02006c382a85d68329e3a68a365037ed2c2a4a4b",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a56": (
        "dotmac-kernel",
        "2699b2b50091921c498bf16e7819c2736ba2572f",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a50": (
        "dotmac-kernel",
        "461aff83d32d73166625be13e5214718f2ade9cf",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a45": (
        "dotmac-kernel",
        "3e54d3c71bad4a53568101b7f383d2e8e455199f",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a42": (
        "dotmac-kernel",
        "048662dbd944aca95b2e89f133b0c864c3fd5a59",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
            "20260812_0022_party_role_grants.py": (
                "69b525286e71ea76d2a51a5f5482d29cd511448a0ea939be0955c3f2b89b3fc6"
            ),
            "20260812_0023_audit_actor_and_forensics.py": (
                "2b72e48ebeec9cce92b4d8d96b0da6052a99301d247db40b617e370379eb8444"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a40": (
        "dotmac-kernel",
        "b37d25b6ab9f94ad5592c717d7b04af11800db15",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
            "20260811_0021_setting_scope_alignment.py": (
                "36d223b100554c2b485281fb2cae7ee54af07b582af08618d84a964ec1710a15"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a38": (
        "dotmac-kernel",
        "58bb1945bdefb93688bece87044151e29e2a2fe8",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
            "20260810_0019_communication_consent.py": (
                "d88619f7cd4f7cf464113e25a05354b317a15aa06f9823c016ec97cae30cd687"
            ),
            "20260810_0020_delivery_receipts.py": (
                "e4b497623a50c733e8a0b3c97b2aa539c0b3a07a29f0f441d3cb2a43985b4ae0"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a33": (
        "dotmac-kernel",
        "21b735c0ded23e6aec5aae55ec3a060a2b84d6d6",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
            "20260810_0018_idempotency_one_owner.py": (
                "8e4776b6a1528a4ddf7fde07d6af2c9a3adf44ba5e8d52795f9715fbe108779e"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a32": (
        "dotmac-kernel",
        "56865b66cda554057fe99ed0f551198a759f24b6",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a31": (
        "dotmac-kernel",
        "047759b49a9bd26ed5137e4efd27bfc34a38c38e",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a30": (
        "dotmac-kernel",
        "4497e0b4641c6e35f7c1209b045ddde21ae60783",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a27": (
        "dotmac-kernel",
        "58ccaab619e4f162175fc7dfcc4e73f6559b8e92",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a25": (
        "dotmac-kernel",
        "e663fb57efd33a0aeb30def347012b40d0d6050e",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a24": (
        "dotmac-kernel",
        "1717f8dd8f8ea0a6e83effcfaee0c319eaa66097",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a23": (
        "dotmac-kernel",
        "f2460f91b5eed507ab8c8525e1396bd31d809b0f",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a21": (
        "dotmac-kernel",
        "7fb72df5a34590cd97b74e25975e53c22a5a94f6",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
            "20260808_0017_history_actor.py": (
                "cad05a8a96df3999c3acd6f7bc259745e1b8ce0070f358a46f9bf0e4f849da17"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a18": (
        "dotmac-kernel",
        "7b8596c240031f7284b5ffefcc440ca3897b06bd",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
            "20260808_0015_open_value_types.py": (
                "d866b7c09050e45cb153071bde951e1988c8d73c42dff4c398c7ca947ead4627"
            ),
            "20260808_0016_setting_scope_depth.py": (
                "fc4ac2f104b12a2d7e08d49530379a2fd4071b41968aadf83436373f294d2599"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a14": (
        "dotmac-kernel",
        "8472b9ee1b4f11d8388fcf08a558cd975d2450df",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
            "20260807_0014_open_setting_domains.py": (
                "e410b0b05e71768498cb65c83ed44fe4a93aba59e4325391cf6da7f9cf3d09fb"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a13": (
        "dotmac-kernel",
        "a83d6865565aae597dfbcdd7c80134394c6dc168",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
            "20260807_0013_feature_flag_overrides.py": (
                "0b0e3602ee1bf363d34e93925bbceee6783c3966dbb2f08b996880bfb9aad4c2"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a12": (
        "dotmac-kernel",
        "7995c66f6c5093de22f79ffb0d51dd1bf76e13a1",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a9": (
        "dotmac-kernel",
        "07b9d36040b5048b49a676795f3148d9a0cf29c2",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a8": (
        "dotmac-kernel",
        "1df5f4af1bf2e5479ebb5237592bc5ecca1d5414",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a7": (
        "dotmac-kernel",
        "fc546a05d1258d2b9ca0a2859c08c436d4e1455b",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a6": (
        "dotmac-kernel",
        "53a1b714cdf7bb5ad47a6e6baf9f367e8e465871",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
            "20260731_0012_platform_outbox.py": (
                "00a54b8c94a9b297b502c32af6562d9eeba56ab9dfeb8cc11663b011d7fcf085"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a5": (
        "dotmac-kernel",
        "322e662dd0e4c2898218d9e993c1d3c42baf41ba",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
            "20260731_0011_outbox_relay_leasing.py": (
                "b1ac5cd7aab8cd80ad96fb2c98d319c85f027cf519230bfe6409082bce2006f6"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a4": (
        "dotmac-kernel",
        "be4b6b4ca54bb3f06d2c610e824a176b98345744",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
            "20260731_0010_tenant_entitlements.py": (
                "41ab63a8a765811f08fdcc68a87ce7df0b9f4c58eebb3aaa50cddd42b5761fcd"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a3": (
        "dotmac-kernel",
        "9878033b16d591b71dfdc32bb0ae134e9764cf40",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a2": (
        "dotmac-kernel",
        "a8db2d0a5389f54128b8e631b0d7698452516c4d",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
            "20260730_0009_platform_audit_inbox.py": (
                "b68ed88472f4e5b44478b51a25ed87a9ba93e0915233f81935bc6afbff22984a"
            ),
        },
    ),
    "dotmac-kernel-v0.1.0a1": (
        "dotmac-kernel",
        "3267a3ba8a4bb22b5fe90b6e2b0b82e01c2e2e56",
        {
            "20260504_0001_initial_tenant_schema.py": (
                "f7dbbf89ea2c4fe0526b77c390dc72942ea04b39e68aff62c635069ecb00746b"
            ),
            "20260717_0002_settings_table.py": (
                "19bde6949e5b227278de6d0b32c83fce9b0fb9d492097ec354bc76cfaf0b08db"
            ),
            "20260717_0003_party_identity.py": (
                "5c7774f57391c7cc86e934e1ebcb48ff95169ae0681e6c3f1e5ffa30746ae2b2"
            ),
            "20260717_0004_custom_fields.py": (
                "79750341f1ddd65c86a1e51896154857d4e2add726c220e97c17dd5c8bd1a27f"
            ),
            "20260718_0005_single_email_authority.py": (
                "4515c454bff012df792be0deb00df3a96d90220e8a97c672eaf46d55746260e0"
            ),
            "20260718_0006_display_setting_domain.py": (
                "99fa5abcb2bbf48f0a808ab7e3c321ffad36c47550b5e57f7205228e45815c5c"
            ),
            "20260730_0007_platform_identity.py": (
                "b70d3cb83f40420f2b269df133d082fcfc8496c88041799a902edf12352001be"
            ),
            "20260730_0008_outbox_inbox.py": (
                "86722eca15bc1a44a0e2bca5da2fc7198989603f595557405d65354872328043"
            ),
        },
    ),
    # ── dotmac-accounting ──
    "dotmac-accounting-v0.1.0a1": (
        "dotmac-accounting",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "ac_0001_accounting.py": (
                "ed2aedd04df0c7446ae7a7b90d6e97d40c2f352f806b9c8eba26558521ef686e"
            ),
        },
    ),
    # ── dotmac-analytics ──
    "dotmac-analytics-v0.1.0a1": (
        "dotmac-analytics",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "ay_0001_analytics.py": (
                "dd528b1b083e11df7bd47dd590d7440111406d53c21447763ec2bb12c7d60344"
            ),
        },
    ),
    # ── dotmac-application-directory ──
    "dotmac-application-directory-v0.1.0a3": (
        "dotmac-application-directory",
        "bbc53bac361a1199e4f32738883d59bd27845253",
        {
            "ad_0001_application_bindings.py": (
                "6efcdc37e8c06e2fc436d8db75c8e3813321b7eeb245e35db2b39ad7ced8baac"
            ),
        },
    ),
    # ── dotmac-assets ──
    "dotmac-assets-v0.1.0a1": (
        "dotmac-assets",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "as_0001_assets.py": (
                "717a44ac90b001f90659a0646d425b86b9f7943b9e89df1b314ce93242023236"
            ),
        },
    ),
    # ── dotmac-banking ──
    "dotmac-banking-v0.1.0a1": (
        "dotmac-banking",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "bk_0001_banking.py": (
                "1b2118eeeacd18eabb907382d84bdeb1dda1c86427cc627c62acbb96b6f5b261"
            ),
        },
    ),
    # ── dotmac-brand-profiles ──
    "dotmac-brand-profiles-v0.1.0a1": (
        "dotmac-brand-profiles",
        "ed69f9dfdeea493dab7d7ba25c04e940f0870545",
        {
            "bp_0001_brand_profiles.py": (
                "b6d569955954d6610d06300c0e60a18c02eeaa06cf0758c7f1a85dc8faeb8961"
            ),
        },
    ),
    # ── dotmac-campaigns ──
    "dotmac-campaigns-v0.1.0a1": (
        "dotmac-campaigns",
        "ae5369c0dcc63b9a9daeba9f522f8906b78a997d",
        {
            "ca_0001_campaigns.py": (
                "ed31a5d91eedf15f182e055fe786f1e7ee3eb364cec561f8ad147343ba125926"
            ),
        },
    ),
    # ── dotmac-content ──
    "dotmac-content-v0.1.0a1": (
        "dotmac-content",
        "8f99413826e5adf3d35379ebc6deb79bcb5c8242",
        {
            "ct_0001_content.py": (
                "e6f36ce5a0cb83f90d97f67dc6cf7cd463cb9b585387150c5ffbbca9f0118d84"
            ),
        },
    ),
    # ── dotmac-documents ──
    "dotmac-documents-v0.1.0a1": (
        "dotmac-documents",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "do_0001_documents.py": (
                "54d15a08a950170677846e344c0b7debaa429dddd87b8e091a1ecb947caaa184"
            ),
        },
    ),
    # ── dotmac-durable-timers ──
    "dotmac-durable-timers-v0.1.0a1": (
        "dotmac-durable-timers",
        "f7d69f7d3db6a36dcccaa847dff7a37e9c3cd685",
        {
            "dt_0001_durable_timers.py": (
                "12bdaad16e18a2dca53b989adb80b9c6c2873e2971ab4a8713ccbc1a2b8d4370"
            ),
        },
    ),
    # ── dotmac-expenses ──
    "dotmac-expenses-v0.1.0a1": (
        "dotmac-expenses",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "ex_0001_expenses.py": (
                "985234f5b245372655f33c49f91b00369f6ecc8cf7e1b2ed328f70a8745a6687"
            ),
        },
    ),
    # ── dotmac-fiber-plant ──
    "dotmac-fiber-plant-v0.1.0a1": (
        "dotmac-fiber-plant",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "fp_0001_fiber_plant.py": (
                "7749f27a97b01c438613639dbc35cc971cab427821920619b6d434ea8b6a821b"
            ),
        },
    ),
    # ── dotmac-finance ──
    "dotmac-finance-v0.1.0a1": (
        "dotmac-finance",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "fn_0001_asset_accounting.py": (
                "1f503d5056eabbcde45954152f250b631ee43b488d7f4d29056b69042f4c1c79"
            ),
        },
    ),
    # ── dotmac-inventory ──
    "dotmac-inventory-v0.1.0a1": (
        "dotmac-inventory",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "iv_0001_inventory.py": (
                "625aadcdce6c0b6f92ceecdb5c3f9606407aa720b326286c9c318582243b4114"
            ),
        },
    ),
    # ── dotmac-ipam ──
    "dotmac-ipam-v0.1.0a1": (
        "dotmac-ipam",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "ip_0001_ipam.py": (
                "ac7292ca9cf580d5a9d00f56160e15482dc57ce3491940559f76056c987e5198"
            ),
        },
    ),
    # ── dotmac-licensing ──
    "dotmac-licensing-v0.1.0a2": (
        "dotmac-licensing",
        "e88df7915efc3acc27541856f111902b5af6fafb",
        {
            "li_0001_licensing.py": (
                "3c6e610e75016fd652b678674bca4d50c01beb7d9f9c15450a4b1bebf43b2e4d"
            ),
        },
    ),
    "dotmac-licensing-v0.1.0a1": (
        "dotmac-licensing",
        "fead57bc93d6551450f5e6ae1c9de1296e27b0ae",
        {
            "li_0001_licensing.py": (
                "3c6e610e75016fd652b678674bca4d50c01beb7d9f9c15450a4b1bebf43b2e4d"
            ),
        },
    ),
    # ── dotmac-media-observations ──
    "dotmac-media-observations-v0.1.0a1": (
        "dotmac-media-observations",
        "8f99413826e5adf3d35379ebc6deb79bcb5c8242",
        {
            "mo_0001_media_observations.py": (
                "b274cb73037d314a275e7c23193229b139dd3d536cf5269b2ebc91b61b035bbf"
            ),
        },
    ),
    # ── dotmac-network-access ──
    "dotmac-network-access-v0.1.0a1": (
        "dotmac-network-access",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "nac_0001_network_access.py": (
                "1540a2a8ce67bde692865514314f4f50b391b2a0339868e4c27ea839bf0dc198"
            ),
        },
    ),
    # ── dotmac-network-assurance ──
    "dotmac-network-assurance-v0.1.0a1": (
        "dotmac-network-assurance",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "na_0001_network_assurance.py": (
                "718b4d076ca8bfb71f3e22a2422ac107bba731983e37e522e651ed356416e6e4"
            ),
        },
    ),
    # ── dotmac-network-control ──
    "dotmac-network-control-v0.1.0a1": (
        "dotmac-network-control",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "nc_0001_network_control.py": (
                "2467b95b53d09fdcfc275fbc995e10393121e86826fa18f0c3b5f18290e67603"
            ),
        },
    ),
    # ── dotmac-network-inventory ──
    "dotmac-network-inventory-v0.1.0a1": (
        "dotmac-network-inventory",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "ni_0001_network_inventory.py": (
                "6936e411a5fd364113c11d9552d9b190c351b3d187399bfd64982a883713b5f1"
            ),
        },
    ),
    # ── dotmac-network-observability ──
    "dotmac-network-observability-v0.1.0a1": (
        "dotmac-network-observability",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "no_0001_net_observability.py": (
                "1e992888be2a813d13ff485f28b5af05435995a9bc1013ab81cfd120eaa465f6"
            ),
        },
    ),
    # ── dotmac-network-topology ──
    "dotmac-network-topology-v0.1.0a1": (
        "dotmac-network-topology",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "nt_0001_network_topology.py": (
                "b47d4600830b07a8d3c1034c397a4e347446e15d84260c4ee473c7a3e9d5632e"
            ),
        },
    ),
    # ── dotmac-party ──
    "dotmac-party-v0.1.0a1": (
        "dotmac-party",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "pt_0001_party_context.py": (
                "fd84e1bbe1fe9ee97d2a0d26def9e7ca561aaf527fcc24d94faa80afa7d50750"
            ),
        },
    ),
    # ── dotmac-payables ──
    "dotmac-payables-v0.1.0a1": (
        "dotmac-payables",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "pa_0001_payables.py": (
                "ea7e28ec2fe9d424b629f2435cfbf8741afa92e8a139227ad8432bf66ba66c05"
            ),
        },
    ),
    # ── dotmac-payroll ──
    "dotmac-payroll-v0.1.0a1": (
        "dotmac-payroll",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "py_0001_payroll.py": (
                "7778ff65a7ede98bf4aa8d8659a0d8bddf66f703355c5f4e3878c78473f5c8fd"
            ),
        },
    ),
    # ── dotmac-pon-access ──
    "dotmac-pon-access-v0.1.0a1": (
        "dotmac-pon-access",
        "bfc112fc8eac58e5ce279c1d0a5868c1f156c0e3",
        {
            "pn_0001_pon_access.py": (
                "241685bf0ccc01bc6e797622c787e2d27c7652b577e645ff9592dcfd463dee3b"
            ),
        },
    ),
    # ── dotmac-positioning ──
    "dotmac-positioning-v0.1.0a1": (
        "dotmac-positioning",
        "75a26abd3f866ebe24c4881a3958439d423034c7",
        {
            "po_0001_positioning.py": (
                "153136b3f1441e03f26626502808b5081ac3a39678bf7d40be5712c49e70d16f"
            ),
        },
    ),
    # ── dotmac-procurement ──
    "dotmac-procurement-v0.1.0a1": (
        "dotmac-procurement",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "pc_0001_procurement.py": (
                "d2b5b7b30e72337ecf6ed49833debe58882f6928bab5174d236e2e8a97943101"
            ),
        },
    ),
    # ── dotmac-projects ──
    "dotmac-projects-v0.1.0a1": (
        "dotmac-projects",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "pj_0001_projects.py": (
                "0342699ea131a1128ab1b112743a56d53e3e37dd9ed4086607c31c8ad4bf19aa"
            ),
        },
    ),
    # ── dotmac-publishing ──
    "dotmac-publishing-v0.1.0a1": (
        "dotmac-publishing",
        "8f99413826e5adf3d35379ebc6deb79bcb5c8242",
        {
            "pb_0001_publishing.py": (
                "ee75c055bbefac8117f94967705c6d6e5764baa0d21a579085684af0582b216e"
            ),
        },
    ),
    # ── dotmac-records ──
    "dotmac-records-v0.1.0a1": (
        "dotmac-records",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "re_0001_records.py": (
                "392a43f8eddaa7e6bb011c8e870ede77d064097e5670f9c186c020ac7ce30598"
            ),
        },
    ),
    # ── dotmac-referrals ──
    "dotmac-referrals-v0.1.0a1": (
        "dotmac-referrals",
        "401f000626fb74898d0d6bda4244fee69849bcf2",
        {
            "rf_0001_referrals.py": (
                "3af67102534e75737ca5a9f58cd9435bab842c8843be8f02e13053382467ffaf"
            ),
        },
    ),
    # ── dotmac-release-catalog ──
    "dotmac-release-catalog-v0.1.0a4": (
        "dotmac-release-catalog",
        "7556b96e8751d46a8bf3cb014b95a9a64eb03b0c",
        {
            "rl_0001_release_artifacts.py": (
                "f8a8d7167e2e37aeb5878cd12c8afeb023cee86355aefae8933f60c35a91a70e"
            ),
        },
    ),
    "dotmac-release-catalog-v0.1.0a5": (
        # a5 adds rl_0002_db_catalog_attestations.py (new migration, #716) plus
        # a database_catalog= manifest declaration; rl_0001 is byte-identical
        # to a4. Commit is this tag's own peeled commit, per
        # test_each_recorded_commit_is_the_exact_peeled_tag.
        "dotmac-release-catalog",
        "9a9403624a8c21571053e36043f3eeab7ec34480",
        {
            "rl_0001_release_artifacts.py": (
                "f8a8d7167e2e37aeb5878cd12c8afeb023cee86355aefae8933f60c35a91a70e"
            ),
            "rl_0002_db_catalog_attestations.py": (
                "e05f9ec0f7cced74f184b0fdbdc30997f0f9aa83b7384856c6250db2f1ca46ce"
            ),
        },
    ),
    "dotmac-release-catalog-v0.1.0a3": (
        "dotmac-release-catalog",
        "461aff83d32d73166625be13e5214718f2ade9cf",
        {
            "rl_0001_release_artifacts.py": (
                "f8a8d7167e2e37aeb5878cd12c8afeb023cee86355aefae8933f60c35a91a70e"
            ),
        },
    ),
    "dotmac-release-catalog-v0.1.0a2": (
        "dotmac-release-catalog",
        "5a911802e4423d72bb6576fe514d5d4efb23801a",
        {
            "rl_0001_release_artifacts.py": (
                "f8a8d7167e2e37aeb5878cd12c8afeb023cee86355aefae8933f60c35a91a70e"
            ),
        },
    ),
    "dotmac-release-catalog-v0.1.0a1": (
        "dotmac-release-catalog",
        "fb38ee0fd008f26fd7fd56bb65a6ef076328c2ea",
        {
            "rl_0001_release_artifacts.py": (
                "f8a8d7167e2e37aeb5878cd12c8afeb023cee86355aefae8933f60c35a91a70e"
            ),
        },
    ),
    # ── dotmac-reseller-management ──
    "dotmac-reseller-management-v0.1.0a1": (
        "dotmac-reseller-management",
        "401f000626fb74898d0d6bda4244fee69849bcf2",
        {
            "rm_0001_reseller_management.py": (
                "948a28e5adeb297d12e8d03599ed2f56a5ba2e45867ca03600821ddc74c7ec2e"
            ),
        },
    ),
    # ── dotmac-service-orders ──
    "dotmac-service-orders-v0.1.0a1": (
        "dotmac-service-orders",
        "909164420b5a3e14b289af923ddbb13f70ec4020",
        {
            "so_0001_service_delivery_orders.py": (
                "3065f107cfda5914dee7319ae0aacfc5eb2ebfd849d4b558e8dcd2850e97dff9"
            ),
        },
    ),
    # ── dotmac-sites ──
    "dotmac-sites-v0.1.0a1": (
        "dotmac-sites",
        "8f99413826e5adf3d35379ebc6deb79bcb5c8242",
        {
            "si_0001_sites.py": (
                "1dd7d1f95343001574630c6cd252ed1d7cbe5070654d6aa8a8cd8d4809117de2"
            ),
        },
    ),
    # ── dotmac-surveys ──
    "dotmac-surveys-v0.1.0a1": (
        "dotmac-surveys",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "sv_0001_surveys.py": (
                "8c86d1b7d756d81bf0aad746b8d222c434bdb2526ba353f3b3d231ce92fda7fe"
            ),
        },
    ),
    # ── dotmac-web-analytics ──
    "dotmac-web-analytics-v0.1.0a1": (
        "dotmac-web-analytics",
        "8b8e3d26f4b344cf1ed7444e9a2e3836c7115f30",
        {
            "wa_0001_web_analytics.py": (
                "febb356d3e8a280049226803286ea4076150e39af3ad6a65e09d611ec9fe4b71"
            ),
        },
    ),
    # ── dotmac-work-orders ──
    "dotmac-work-orders-v0.1.0a1": (
        "dotmac-work-orders",
        "20d24703e70e4d361de2f406165df4b36cbee507",
        {
            "wo_0001_work_orders.py": (
                "b34f8f60964b45ffc4bb96b2bc93d089d462c293ded9cf17986a00b874d0580c"
            ),
        },
    ),
    # ── dotmac-ticketing ──
    "dotmac-ticketing-v0.1.0a4": (
        "dotmac-ticketing",
        "16f11a9ef0df7697558904efa969294bafc3fab3",
        {
            "tk_0001_tickets.py": (
                "0e27d341b9b0a26577a55b2a973dcab7335b381c1dc4d5c936ed57a119993727"
            ),
        },
    ),
    "dotmac-ticketing-v0.1.0a3": (
        "dotmac-ticketing",
        "3e1f8012c4f45369b6801a709a270d71c5c95a8d",
        {
            "tk_0001_tickets.py": (
                "4719bb00030931b9c18697ee66e6e183067728582040a90f5189e1fcef0ed7bb"
            ),
        },
    ),
    # ── dotmac-deployment-control ──
    "dotmac-deployment-control-v0.1.0a2": (
        "dotmac-deployment-control",
        "5c87272a632096850a80e5e9dc1f625a97c3e5d6",
        {
            "dc_0001_deployment_control.py": (
                "378ebc8d149d5c187b4339eac9126b9ae75ddf88c6728dc1acc656d6ffb684fa"
            ),
        },
    ),
    "dotmac-deployment-control-v0.1.0a1": (
        "dotmac-deployment-control",
        "fead57bc93d6551450f5e6ae1c9de1296e27b0ae",
        {
            "dc_0001_deployment_control.py": (
                "378ebc8d149d5c187b4339eac9126b9ae75ddf88c6728dc1acc656d6ffb684fa"
            ),
        },
    ),
}


@dataclass(frozen=True)
class GrandfatheredDivergence:
    """A released filename whose historical tags do not contain one byte set."""

    canonical_digest: str
    variants: tuple[tuple[str, frozenset[str]], ...]
    reason: str


#: The accepted released-byte divergences. Each records damage already in the
#: registry; none authorizes another in-place edit. The canonical digest is the
#: latest shipped shape and is the only byte set the current tree may retain.
#:
#: Two rows, and the second is the reason the first was never enough. Approvals
#: and ticketing made the SAME edit to their lineage roots in the same week --
#: implicit plane inference rewritten into ADR-0028 explicit selection, in
#: place, on a published revision. Approvals was enrolled here, so it was
#: caught, written up and given a PostgreSQL upgrade matrix
#: (`tests/test_approvals_released_migration_upgrades.py`). Ticketing was not
#: enrolled, so the identical edit passed every gate and was found only when
#: this lineage was enrolled on 2026-09-01. That asymmetry is the argument for
#: closing the coverage baseline; it is not an argument that one edit was worse.
#:
#: Every row must be written up under `docs/inventories/`, which
#: `test_every_grandfathered_divergence_is_written_up` enforces -- a divergence
#: nobody documented is one the next reader has to reconstruct from digests.
GRANDFATHERED_DIVERGENCES: dict[tuple[str, str], GrandfatheredDivergence] = {
    ("dotmac-approvals", "ap_0001_approvals.py"): GrandfatheredDivergence(
        canonical_digest=(
            "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb"
        ),
        variants=(
            (
                "ec5e1aa9e504de8143eebaafacb0615cf24b6ea930648f5b9cfd1a9afc2db70e",
                frozenset({"dotmac-approvals-v0.1.0a1"}),
            ),
            (
                "6c7b3263e05f860982dda125439171f62bba716d36d95b21e2c3a3224f19ad6a",
                frozenset({"dotmac-approvals-v0.1.0a2"}),
            ),
            (
                "102110e3e50c2ebfe0e73c5eb5e77bafe014e4835edad45a41a91a9ae0c144cb",
                frozenset(
                    {
                        "dotmac-approvals-v0.1.0a3",
                        "dotmac-approvals-v0.1.0a4",
                        "dotmac-approvals-v0.1.0a5",
                        "dotmac-approvals-v0.1.0a6",
                        "dotmac-approvals-v0.1.0a7",
                        "dotmac-approvals-v0.1.0a8",
                    }
                ),
            ),
        ),
        reason=(
            "a1 built both planes; a2 inferred tenant installation from a "
            "binding; a3/a4/a5 require explicit plane selection. These releases "
            "already exist, so the divergence is preserved as evidence and "
            "each variant must upgrade to the canonical current lineage."
        ),
    ),
    ("dotmac-ticketing", "tk_0001_tickets.py"): GrandfatheredDivergence(
        canonical_digest=(
            "0e27d341b9b0a26577a55b2a973dcab7335b381c1dc4d5c936ed57a119993727"
        ),
        variants=(
            (
                "4719bb00030931b9c18697ee66e6e183067728582040a90f5189e1fcef0ed7bb",
                frozenset({"dotmac-ticketing-v0.1.0a3"}),
            ),
            (
                "0e27d341b9b0a26577a55b2a973dcab7335b381c1dc4d5c936ed57a119993727",
                frozenset({"dotmac-ticketing-v0.1.0a4"}),
            ),
        ),
        reason=(
            "P1 migration-lineage incident, found by THIS enrolment on "
            "2026-09-01. The difference is conditional EXECUTION, not a grant "
            "list: exactly one textual grant differs and the rest of the DDL "
            "is byte-identical, but a3 runs `_upgrade_platform_plane()` "
            "unconditionally while a4 guards it on explicit selection "
            "(ADR-0028). On a tenant-only assembly a3 therefore additionally "
            "leaves `mod_tkt.platform_tickets` and "
            "`mod_tkt.platform_ticket_comments` existing, with `platform_api` "
            "holding DML on them. Both are published, so revision "
            "`tk_0001_tickets` names two schema results and `alembic_version` "
            "records only that it ran. Recorded as damage already in the "
            "registry: it freezes the census at two byte sets and does not "
            "authorize a third. a3 AND a4 are both refused for new production "
            "adoption -- a4 still grants `platform_api` DML on the tenant "
            "tables while withholding schema USAGE -- until an additive "
            "`tk_0002` repairs both and is independently verified. The known "
            "installation set is EMPTY (no product composes it, no "
            "non-pipeline registry fetch occurred), which bounds who was "
            "affected and does not lift the refusal. This repository's own "
            "reference assembly does compose tenant+platform, so the platform "
            "plane's RETIREMENT is a change here and not only elsewhere: the "
            "supported composition going forward is tenant-only. See "
            "docs/inventories/ticketing-released-migration-divergence.md."
        ),
    ),
}


#: Migration files that exist in the tree and have NOT shipped in any tag, so
#: are still editable. This is the second direction of the ratchet: a new
#: migration must be named here, and a file may only move from here into
#: `RELEASED_TAGS` — never the other way, and never out of both.
#:
#: An empty set means every current migration shipped. A non-empty set names
#: the exact files that remain editable; Integration's ig_0015 is one current
#: example. The release lane does not wait for an open branch, which is why
#: "released" is read from tags rather than from an intended version number.
UNRELEASED: dict[str, frozenset[str]] = {
    "dotmac-numbering": frozenset(),
    # `ap_0003` records approved-decision withdrawals; still editable until
    # `dotmac-approvals` 0.1.0a7 is tagged.
    "dotmac-approvals": frozenset(),
    "dotmac-integration": frozenset(),
    "dotmac-entitlement-allocation": frozenset(),
    "dotmac-files": frozenset(),
    "dotmac-forms": frozenset(),
    "dotmac-workflow-runtime": frozenset(),
    # `ph_0002` snapshots each observation's freshness policy at acceptance,
    # so a later policy change cannot reclassify an unchanged observation.
    # Still editable: `dotmac-platform-health` has no released tag carrying it.
    "dotmac-platform-health": frozenset({"ph_0002_observation_freshness_snapshot.py"}),
    "dotmac-support-access": frozenset(),
    "dotmac-remote-access": frozenset(),
    "dotmac-compliance-reporting": frozenset(),
    # `ao_0002` expands `ai_insights` with a typed evidence binding
    # (additive columns only, legacy `action_evidence_ref` untouched).
    # `ao_0003` gives acknowledgement attribution the identical shadowing
    # treatment (additive columns only, legacy `acknowledged_by_ref`/
    # `acknowledged_at` untouched). Still editable: no released tag
    # carries either yet.
    "dotmac-ai-operations": frozenset(
        {
            "ao_0002_insight_evidence_binding.py",
            "ao_0003_ack_attribution.py",
        }
    ),
    "dotmac-payments": frozenset(),
    "dotmac-imports": frozenset(),
    # a5's availability/transfer lineage: still editable until the
    # protected release tags it and its digest is recorded above.
    "dotmac-inbox-operations": frozenset({"io_0004_availability_transfers.py"}),
    "dotmac-operational-escalations": frozenset(),
    "dotmac-service-changes": frozenset(),
    "dotmac-subscriptions": frozenset(),
    "dotmac-billing": frozenset(),
    "dotmac-collections": frozenset(),
    "dotmac-fulfillment": frozenset(),
    "dotmac-tax": frozenset(),
    "dotmac-service-catalog": frozenset(),
    "dotmac-customers": frozenset(),
    "dotmac-fx-policy": frozenset(),
    "dotmac-qualification": frozenset(),
    "dotmac-response-obligations": frozenset(),
    "dotmac-sales": frozenset(),
    "dotmac-service-access-policy": frozenset(),
    "dotmac-services": frozenset(),
    "dotmac-template-studio": frozenset(),
    # `cg_0002` records approval withdrawals as standing; still editable until
    # `dotmac-commercial-agreements` 0.1.0a4 is tagged.
    "dotmac-commercial-agreements": frozenset({"cg_0002_approval_withdrawals.py"}),
    "dotmac-people": frozenset(),
    "dotmac-inbox": frozenset(
        {"ib_0002_supplied_identity.py", "ib_0003_transport_refs.py"}
    ),
    "dotmac-kernel": frozenset(),
    "dotmac-accounting": frozenset(),
    "dotmac-analytics": frozenset(),
    "dotmac-application-directory": frozenset(),
    "dotmac-assets": frozenset(),
    "dotmac-banking": frozenset(),
    "dotmac-brand-profiles": frozenset(),
    "dotmac-campaigns": frozenset(),
    "dotmac-content": frozenset(),
    "dotmac-documents": frozenset(),
    "dotmac-durable-timers": frozenset(),
    "dotmac-expenses": frozenset(),
    "dotmac-fiber-plant": frozenset(),
    "dotmac-finance": frozenset(),
    "dotmac-inventory": frozenset(),
    "dotmac-ipam": frozenset(),
    "dotmac-licensing": frozenset(),
    "dotmac-media-observations": frozenset(),
    "dotmac-network-access": frozenset(),
    "dotmac-network-assurance": frozenset(),
    "dotmac-network-control": frozenset(),
    "dotmac-network-inventory": frozenset(),
    "dotmac-network-observability": frozenset(),
    "dotmac-network-topology": frozenset(),
    "dotmac-party": frozenset(),
    "dotmac-payables": frozenset(),
    "dotmac-payroll": frozenset(),
    "dotmac-pon-access": frozenset(),
    "dotmac-positioning": frozenset(),
    "dotmac-procurement": frozenset(),
    "dotmac-projects": frozenset(),
    "dotmac-publishing": frozenset(),
    "dotmac-records": frozenset(),
    "dotmac-referrals": frozenset(),
    "dotmac-release-catalog": frozenset(),
    "dotmac-reseller-management": frozenset(),
    "dotmac-service-orders": frozenset(),
    "dotmac-sites": frozenset(),
    "dotmac-surveys": frozenset(),
    "dotmac-web-analytics": frozenset(),
    "dotmac-work-orders": frozenset(),
    "dotmac-ticketing": frozenset(),
    "dotmac-deployment-control": frozenset(),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _drift(versions: Path, distribution: str = "dotmac-integration") -> list[str]:
    """Every released file of `distribution` in `versions` whose bytes moved.

    Takes the directory as an argument rather than reading the module constant,
    which is the whole reason the sensitivity proofs below can run: they point
    it at a deliberately damaged copy of the tree. `distribution` selects which
    tags apply, because one directory holds one lineage and the map now holds
    several.
    """
    problems: list[str] = []
    checked_divergences: set[tuple[str, str]] = set()
    for tag, (owner, commit, files) in sorted(RELEASED_TAGS.items()):
        if owner != distribution:
            continue
        for name, expected in sorted(files.items()):
            key = (owner, name)
            divergence = GRANDFATHERED_DIVERGENCES.get(key)
            if divergence is not None:
                if key in checked_divergences:
                    continue
                checked_divergences.add(key)
                path = versions / name
                if not path.is_file():
                    shipping_tags = sorted(
                        tag_name for _, tags in divergence.variants for tag_name in tags
                    )
                    problems.append(
                        f"{name} shipped with grandfathered variants in "
                        f"{shipping_tags} and is now MISSING — released history "
                        "cannot be withdrawn"
                    )
                    continue
                actual = _digest(path)
                if actual != divergence.canonical_digest:
                    problems.append(
                        f"{name} has grandfathered released variants but the "
                        "current tree must retain canonical sha256 "
                        f"{divergence.canonical_digest}; found {actual}"
                    )
                continue
            path = versions / name
            if not path.is_file():
                problems.append(
                    f"{name} shipped in {tag} ({commit}) and is now MISSING — a "
                    "released revision cannot be withdrawn; adopters have "
                    "already run it"
                )
                continue
            actual = _digest(path)
            if actual != expected:
                problems.append(
                    f"{name} shipped in {tag} ({commit}) as sha256 {expected} "
                    f"and is now {actual}"
                )
    return problems


def _shipping_tags(name: str) -> list[str]:
    """Every tag whose entry records `name`.

    Derived, never counted by hand: `ig_0001` was in two tags when this file
    was written and three by the time it merged, and a hardcoded expectation
    turns a released migration appearing in one more release into a red suite
    for no reason.
    """
    return sorted(tag for tag, (_, _, files) in RELEASED_TAGS.items() if name in files)


# ── The guard ───────────────────────────────────────────────────────────────


def test_the_map_records_something_to_check() -> None:
    """A digest map that emptied would make every test below pass having
    compared nothing — the exact failure ADR-0018 calls a guard with no
    sensitivity."""
    assert RELEASED_TAGS, "no released tags recorded; this file proves nothing"
    for tag, (owner, _, files) in RELEASED_TAGS.items():
        assert files, f"{tag} records no files"
        assert owner in DISTRIBUTIONS, (
            f"{tag} names distribution {owner!r}, which has no versions "
            "directory in DISTRIBUTIONS — the map would then check nothing"
        )
    # Every monitored distribution must actually be monitored. A row in
    # DISTRIBUTIONS with no tag would look enrolled and check nothing.
    covered = {owner for owner, _, _ in RELEASED_TAGS.values()}
    assert covered == set(DISTRIBUTIONS), sorted(set(DISTRIBUTIONS) - covered)
    missing_prefixes = sorted(set(DISTRIBUTIONS) - set(TAG_PREFIXES))
    assert set(TAG_PREFIXES) == set(DISTRIBUTIONS), (
        "every monitored distribution needs a tag prefix, or a later release "
        f"can evade the external tag oracle: {missing_prefixes}"
    )


@pytest.mark.parametrize("distribution", sorted(DISTRIBUTIONS))
def test_no_released_migration_has_been_edited(distribution: str) -> None:
    """The guard itself. Adopters ran these bytes; the tree must still hold
    them, or a repair was made in place instead of in a new revision."""
    problems = _drift(DISTRIBUTIONS[distribution], distribution)
    assert not problems, (
        f"{distribution}: released migrations were modified:\n" + "\n".join(problems)
    )


def test_two_tags_agree_unless_the_divergence_is_exactly_grandfathered() -> None:
    """No second byte history can hide behind the approvals exception."""
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    divergent: dict[tuple[str, str], dict[str, set[str]]] = {}
    for tag, (owner, _, files) in sorted(RELEASED_TAGS.items()):
        for name, digest in sorted(files.items()):
            key = (owner, name)
            divergent.setdefault(key, {}).setdefault(digest, set()).add(tag)
            seen.setdefault(key, (tag, digest))
    assert seen, "no shared files to compare"

    actual_divergences = {
        key: variants for key, variants in divergent.items() if len(variants) > 1
    }
    assert set(actual_divergences) == set(GRANDFATHERED_DIVERGENCES), (
        "released-byte divergence is either undeclared or its exception is stale: "
        f"actual={sorted(actual_divergences)}, "
        f"declared={sorted(GRANDFATHERED_DIVERGENCES)}"
    )
    for key, actual in actual_divergences.items():
        declaration = GRANDFATHERED_DIVERGENCES[key]
        declared = {digest: set(tags) for digest, tags in declaration.variants}
        assert actual == declared, f"{key}: variant/tag census drifted"
        assert declaration.canonical_digest in actual
        assert declaration.reason.strip()
        assert _digest(DISTRIBUTIONS[key[0]] / key[1]) == (
            declaration.canonical_digest
        ), f"{key}: current tree no longer retains the canonical released bytes"


#: Where a grandfathered divergence is written up for a human, keyed by
#: distribution. A digest census proves WHAT diverged; only prose says what the
#: two byte sets each meant, what was measured, and what is still owed.
DIVERGENCE_INVENTORIES: dict[str, Path] = {
    "dotmac-approvals": (
        REPO_ROOT / "docs/inventories/approvals-released-migration-divergence.md"
    ),
    "dotmac-ticketing": (
        REPO_ROOT / "docs/inventories/ticketing-released-migration-divergence.md"
    ),
}


def test_every_grandfathered_divergence_is_written_up() -> None:
    """A second byte history may not enter as a digest literal and nothing else.

    The census in `GRANDFATHERED_DIVERGENCES` is machine-checkable and says
    nothing a reader can act on: it proves two tags disagree, not what the
    disagreement did to a database, how far it reached, or what is owed.
    Requiring the write-up -- and requiring it to quote every digest, so it
    cannot go stale silently while the map moves -- is what keeps
    "grandfathered" from becoming a place to put things.
    """
    keys = {distribution for distribution, _ in GRANDFATHERED_DIVERGENCES}
    assert keys == set(DIVERGENCE_INVENTORIES), (
        "every grandfathered divergence needs an inventory document, and every "
        f"document a live divergence: {sorted(keys ^ set(DIVERGENCE_INVENTORIES))}"
    )
    for distribution in sorted(keys):
        document = DIVERGENCE_INVENTORIES[distribution]
        assert document.is_file(), f"{distribution}: {document} does not exist"
        prose = document.read_text(encoding="utf-8")
        for key, declaration in GRANDFATHERED_DIVERGENCES.items():
            if key[0] != distribution:
                continue
            assert declaration.canonical_digest in prose, (
                f"{distribution}: {document.name} does not record the canonical "
                f"digest {declaration.canonical_digest} the tree must retain"
            )
            for digest, _ in declaration.variants:
                assert digest in prose, (
                    f"{distribution}: {document.name} does not record released "
                    f"variant {digest}"
                )


@pytest.mark.parametrize("distribution", sorted(DISTRIBUTIONS))
def test_every_migration_is_either_released_or_declared_unreleased(
    distribution: str,
) -> None:
    """The two-directional ratchet.

    Without this, the guard is trivially defeated in both directions: a new
    migration simply never enters the map, and a released one can be dropped
    from it in the same commit that edits it. Neither is possible if the union
    must equal the directory exactly.
    """
    versions = DISTRIBUTIONS[distribution]
    on_disk = {path.name for path in versions.glob(LINEAGE_GLOBS[distribution])}
    assert on_disk, f"{distribution}: no migration matched its lineage glob"
    released = {
        name
        for owner, _, files in RELEASED_TAGS.values()
        if owner == distribution
        for name in files
    }
    unreleased = UNRELEASED[distribution]

    assert not (released & unreleased), (
        f"{distribution}: {sorted(released & unreleased)} claimed as both "
        "released and unreleased — a file is one or the other"
    )
    missing = sorted(on_disk - released - unreleased)
    assert not missing, (
        f"{distribution}: migration(s) {missing} are in neither map. A new "
        "migration goes in UNRELEASED; record its digest under its tag when it "
        "ships"
    )
    stale = sorted((released | unreleased) - on_disk)
    assert not stale, (
        f"{distribution}: {stale} are recorded but not on disk — see the "
        "deletion message in `_drift` before removing anything"
    )


@dataclass(frozen=True)
class FrozenReleaseCoordinate:
    """One published release this repository can no longer reproduce."""

    distribution: str
    version: str
    tag: str
    commit: str
    #: migration filename -> sha256 AS PUBLISHED under this exact tag.
    artifacts: dict[str, str]
    reason: str


#: EXACT released coordinates, and deliberately nothing wider.
#:
#: The obvious shape for this exception is a publisher: "deployment-control is
#: released from another repository now, so stop expecting a lane here." That
#: shape is wrong, and wrong in the direction that matters — it would exempt
#: EVERY FUTURE release from that publisher, including versions this repository
#: never saw, cannot read and has no basis to vouch for. An exemption keyed by
#: publisher grows silently; an exemption keyed by coordinate cannot.
#:
#: What is actually true is narrow and checkable. Two versions were built HERE,
#: from two named commits, producing two named artifact digests. On 2026-08-29
#: `dotmac-deployment-control` was removed from `.github/release-modules.json`,
#: and that absence IS the freeze: `release-module.yml` resolves its target
#: there and fails closed, so a comment saying "do not publish this here" would
#: only have been a request. `michaelayoade/dotmac_deployment_control` owns the
#: name now, and `git filter-repo` rewrote every commit during the extraction —
#: a tag recreated over there would name a different tree. So these two
#: releases cannot be reconstructed by any repository, including that one, and
#: their bytes remain this repository's history to freeze.
#:
#: That argument covers a1 and a2. It says nothing about a3, which is the
#: point: a later release from the new owner is not grandfathered by this row,
#: it is simply not this repository's to monitor, and adding a coordinate for
#: it would require the amendment below.
#:
#: A coordinate here is NOT excused from the byte census. It is excused only
#: from the module-release allowlist, and every claim it makes is re-derived
#: from the tag rather than trusted.
FROZEN_RELEASE_COORDINATES: tuple[FrozenReleaseCoordinate, ...] = (
    FrozenReleaseCoordinate(
        distribution="dotmac-deployment-control",
        version="0.1.0a1",
        tag="dotmac-deployment-control-v0.1.0a1",
        commit="fead57bc93d6551450f5e6ae1c9de1296e27b0ae",
        artifacts={
            "dc_0001_deployment_control.py": (
                "378ebc8d149d5c187b4339eac9126b9ae75ddf88c6728dc1acc656d6ffb684fa"
            ),
        },
        reason=(
            "built in this repository on 2026-08-20 and published from here; "
            "the distribution moved to "
            "michaelayoade/dotmac_deployment_control on 2026-08-29 and "
            "git filter-repo rewrote the commit during the extraction, so no "
            "repository can reproduce this coordinate"
        ),
    ),
    FrozenReleaseCoordinate(
        distribution="dotmac-deployment-control",
        version="0.1.0a2",
        tag="dotmac-deployment-control-v0.1.0a2",
        commit="5c87272a632096850a80e5e9dc1f625a97c3e5d6",
        artifacts={
            "dc_0001_deployment_control.py": (
                "378ebc8d149d5c187b4339eac9126b9ae75ddf88c6728dc1acc656d6ffb684fa"
            ),
        },
        reason=(
            "built in this repository on 2026-08-21 and published from here; "
            "same extraction as a1 — the commit no longer exists in the "
            "repository that owns the name"
        ),
    ),
)

#: How many frozen coordinates a human has reviewed and accepted.
#:
#: Two-directional, per ADR-0018. A NEW coordinate fails until this number is
#: raised in the same change that adds it, which is what makes the exception
#: cost a review rather than a paste. A REMOVED coordinate fails too, until the
#: number is lowered — a quietly shrinking exception list stops describing what
#: is actually exempt, and the next reader cannot tell "repaired" from
#: "deleted".
REVIEWED_FROZEN_COORDINATES = 2


def test_a_frozen_coordinate_is_exact_and_still_frozen() -> None:
    """Every claim a coordinate makes is re-derived, never trusted.

    The row asserts four things a checkout can verify: the tag names the
    version, the tag peels to the recorded commit, the tag holds the recorded
    artifact bytes, and the distribution is absent from the live module
    allowlist. The last one is what stops the row outliving the freeze — if the
    name comes back into `.github/release-modules.json`, this repository
    publishes it again and the exemption is stale, not narrow.
    """
    allowlist = set(
        json.loads(
            (REPO_ROOT / ".github/release-modules.json").read_text(encoding="utf-8")
        )["modules"]
    )
    assert FROZEN_RELEASE_COORDINATES, "the frozen-coordinate exception records nothing"
    for coordinate in FROZEN_RELEASE_COORDINATES:
        assert coordinate.reason.strip(), f"{coordinate.tag}: a freeze without a reason"
        assert coordinate.tag == f"{coordinate.distribution}-v{coordinate.version}", (
            f"{coordinate.tag}: tag and version disagree, so the row names two "
            "different releases"
        )
        assert coordinate.distribution not in allowlist, (
            f"{coordinate.distribution} is back in the module release "
            "allowlist, so it is no longer frozen — drop the row rather than "
            "keeping two answers"
        )
        assert (
            coordinate.artifacts
        ), f"{coordinate.tag}: a coordinate with no artifact digest freezes nothing"
        argv = ["git", "rev-parse", f"{coordinate.tag}^{{commit}}"]
        peeled = subprocess.run(  # noqa: S603 # nosec B603 B607
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert peeled.returncode == 0, (
            f"{coordinate.tag} does not resolve in this checkout; a frozen "
            "coordinate must name a tag that exists"
        )
        assert peeled.stdout.strip() == coordinate.commit, (
            f"{coordinate.tag}: recorded commit {coordinate.commit} is not the "
            f"peeled tag {peeled.stdout.strip()}"
        )
        directory = DISTRIBUTIONS[coordinate.distribution].relative_to(REPO_ROOT)
        for name, digest in sorted(coordinate.artifacts.items()):
            argv = ["git", "show", f"{coordinate.tag}:{(directory / name).as_posix()}"]
            blob = subprocess.run(  # noqa: S603 # nosec B603 B607
                argv,
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            )
            assert (
                blob.returncode == 0
            ), f"{coordinate.tag}: {name} is not in the tagged tree"
            assert hashlib.sha256(blob.stdout).hexdigest() == digest, (
                f"{coordinate.tag}: {name} does not hash to the recorded "
                f"{digest} — the coordinate describes bytes the tag never held"
            )


def test_a_new_frozen_coordinate_needs_an_explicit_amendment() -> None:
    """Two-directional ratchet: the exception costs a review, not a paste.

    ADR-0018. A list of exemptions that anyone can extend in the same breath as
    the change needing the exemption is not an exception mechanism, it is a
    habit. Raising `REVIEWED_FROZEN_COORDINATES` is the amendment, and it is a
    one-line diff a reviewer cannot miss.

    It fails downward too. A row silently disappearing would quietly re-arm a
    guard over history nobody re-derived, and would leave the next reader
    unable to tell a repair from a deletion.
    """
    actual = len(FROZEN_RELEASE_COORDINATES)
    assert actual == REVIEWED_FROZEN_COORDINATES, (
        f"{actual} frozen release coordinate(s) are declared but "
        f"{REVIEWED_FROZEN_COORDINATES} have been reviewed. A new coordinate "
        "is an explicit amendment: add the row AND raise the count, with the "
        "reason it cannot be reconstructed. Removing one lowers the count."
    )
    coordinates = {(c.distribution, c.version) for c in FROZEN_RELEASE_COORDINATES}
    assert (
        len(coordinates) == actual
    ), "two frozen coordinates name the same distribution and version"


def test_the_frozen_coordinate_exception_is_narrower_than_its_publisher() -> None:
    """Sensitivity: the row must not answer for a version it does not name.

    This is the whole reason the map is keyed by coordinate rather than by
    publisher. A publisher-keyed exemption would say yes to any tag carrying
    that name; a coordinate-keyed one says yes only to the two releases a human
    read. Proved by asking about a version deliberately absent from the map.
    """
    frozen_versions = {(c.distribution, c.version) for c in FROZEN_RELEASE_COORDINATES}
    assert ("dotmac-deployment-control", "0.1.0a1") in frozen_versions
    assert ("dotmac-deployment-control", "0.1.0a99") not in frozen_versions, (
        "an unreviewed version of a frozen distribution is answered by the "
        "map, which means the exception is publisher-shaped after all"
    )
    frozen_names = {c.distribution for c in FROZEN_RELEASE_COORDINATES}
    publishable, _ = _publishable_here()
    assert frozen_names <= publishable, (
        "a frozen coordinate's distribution must reach `_publishable_here`, or "
        "enrolling it fails for a reason the row was meant to answer"
    )


def _publishable_here() -> tuple[set[str], set[str]]:
    """Every distribution THIS repository can publish, and the module lane's share.

    Three sources, kept apart on purpose. The module allowlist is the closed
    set `release-module.yml` resolves against. The dedicated-workflow set is the
    sweep's own enumeration of packages released by a workflow of their own,
    and it is deliberately enumerated there rather than inferred from "absent
    from every lane", because absence is also what an unreleasable package
    looks like. Reusing it keeps one answer to "may this repository publish
    that name?" instead of two that can drift apart.

    `FROZEN_RELEASE_COORDINATES` is the third and narrowest, and it answers a
    different question from the other two: not "may this repository publish
    that name?" but "did it, at this exact coordinate?" Past tense is the whole
    point — released bytes do not stop being history when the publisher moves,
    and a name that may never be published here again still has releases that
    were.
    """
    allowlist = set(
        json.loads(
            (REPO_ROOT / ".github/release-modules.json").read_text(encoding="utf-8")
        )["modules"]
    )
    sweep = _tag_oracle()
    dedicated = set(sweep.DEDICATED_WORKFLOWS)  # type: ignore[attr-defined]
    frozen = {coordinate.distribution for coordinate in FROZEN_RELEASE_COORDINATES}
    return allowlist | dedicated | frozen, allowlist


def test_a_dedicated_lane_still_has_to_prove_a_published_tag() -> None:
    """The union above must not become a way in for an unpublished name.

    A distribution reaching `DISTRIBUTIONS` through the dedicated-workflow lane
    carries the identical premise as one reaching it through the module
    allowlist: its bytes are inside a wheel because a TAG says so. A workflow
    file proves a lane exists, never that it ran.
    """
    sweep = _tag_oracle()
    tags = set(sweep.git_tags(REPO_ROOT))  # type: ignore[attr-defined]
    dedicated = set(sweep.DEDICATED_WORKFLOWS) & set(DISTRIBUTIONS)  # type: ignore[attr-defined]
    assert dedicated, (
        "no dedicated-lane distribution is monitored, so the union in "
        "`_publishable_here` is currently checking nothing"
    )
    for distribution in sorted(dedicated):
        prefix = TAG_PREFIXES[distribution]
        assert any(tag.startswith(prefix) for tag in tags), (
            f"{distribution} is monitored via its dedicated release workflow "
            f"but this checkout holds no {prefix}* tag — a lane is not a release"
        )


def test_the_unmonitored_distributions_are_named() -> None:
    """ADR-0018: unmonitored and exempt are different labels, and the
    difference has to be visible.

    A releasable module absent from `DISTRIBUTIONS` is not excused from the
    rule that released bytes are history — nothing here checks it, which is a
    weaker statement and a different one. Naming the set turns "this file
    covers two modules" from a fact a reader has to reconstruct into one the
    suite reports, and makes enrolling the next module a visible diff rather
    than a silent absence.

    Deliberately NOT an assertion that the set is empty. It will not be for a
    long time, and a failing gate nobody can fix is one somebody deletes.

    The module allowlist is not the whole census of what this repository has
    published. `dotmac-kernel` is deliberately absent from it — it has its own
    workflow with its own inspection rules — and reading only that file made
    "not in the release allowlist" mean two different things: unreleasable, and
    released by a different lane. The sweep already distinguishes them in
    `DEDICATED_WORKFLOWS`, so that ONE definition is reused here rather than a
    second one being written. `_publishable_here` is the union, and every name
    in it still has to prove a published tag below.
    """
    monitored = set(DISTRIBUTIONS)
    publishable, allowlist = _publishable_here()
    assert monitored <= publishable, (
        f"{sorted(monitored - publishable)} is monitored here but this "
        "repository publishes no such distribution — an unreleasable "
        "distribution has no released bytes"
    )
    unmonitored = sorted(allowlist - monitored)
    print(
        "released-migration guard — UNMONITORED (not exempt): "
        + (", ".join(unmonitored) or "none")
    )
    assert monitored, "no distribution is monitored; this file proves nothing"


# ── Sensitivity proofs ──────────────────────────────────────────────────────
#
# A guard nobody has watched fail is a guard nobody has tested. Both proofs
# damage a COPY of the tree, so they establish that `_drift` reports the change
# without any chance of leaving the real one modified.


def test_the_guard_catches_a_one_byte_edit_to_a_released_migration(
    tmp_path: Path,
) -> None:
    """The proof that matters: a whitespace-only change is still a change.

    The realistic way a released migration gets edited is not a rewrite — it is
    a formatter run, a typo fix in a docstring, or a comment added while reading
    it. If the guard only noticed semantic edits it would miss every one of
    those, and they are equally capable of making the checked-in lineage
    disagree with what shipped.
    """
    copy = tmp_path / "versions"
    shutil.copytree(VERSIONS, copy)
    assert not _drift(copy), "the copy must start clean or this proves nothing"

    victim = copy / "ig_0001_connector_control_plane.py"
    victim.write_bytes(victim.read_bytes() + b"\n")

    shipped_in = _shipping_tags("ig_0001_connector_control_plane.py")
    assert len(shipped_in) >= 2, "this proof wants a file that shipped more than once"
    problems = _drift(copy)
    assert len(problems) == len(shipped_in), problems
    for problem, tag in zip(problems, shipped_in, strict=True):
        assert tag in problem, "each release that shipped the file must be named"
        assert "ig_0001_connector_control_plane.py" in problem
        assert (
            "dd9d566c4708980fa4d5c5c9c13301b9d9b558ed622a15712dd98c2148d745f1"
            in problem
        ), "the message must name the digest that shipped, not just 'differs'"


def test_the_guard_catches_a_deleted_released_migration(tmp_path: Path) -> None:
    """Deletion is the other half, and `_digest` alone would raise
    `FileNotFoundError` here — an error, not a finding, and one a reader would
    take for a broken test rather than a withdrawn revision."""
    copy = tmp_path / "versions"
    shutil.copytree(VERSIONS, copy)
    (copy / "ig_0006_retention.py").unlink()

    problems = _drift(copy)
    assert len(problems) == len(_shipping_tags("ig_0006_retention.py")), problems
    for problem in problems:
        assert "ig_0006_retention.py" in problem
        assert "MISSING" in problem


def test_an_unreleased_migration_is_free_to_change(tmp_path: Path) -> None:
    """Specificity for the two above: `_drift` must fire on RELEASED bytes, not
    on any change at all. A guard that refused every edit to the directory would
    pass both proofs above and block all future work."""
    distribution = "dotmac-integration"
    copy = tmp_path / "versions"
    shutil.copytree(DISTRIBUTIONS[distribution], copy)
    victim = copy / "ig_9999_still_being_written.py"
    victim.write_text("revision = 'ig_9999_still_being_written'\n", encoding="utf-8")
    assert all(
        victim.name not in files for _, _, files in RELEASED_TAGS.values()
    ), "the sensitivity file must not be classified as released"
    assert not _drift(copy, distribution)


def test_the_guard_catches_an_edit_to_the_second_distributions_bytes(
    tmp_path: Path,
) -> None:
    """Enrolment is only real if the new rows are actually compared.

    `ea_0001` shipped in five tags with one digest, and every proof above walks
    integration's directory — so all of them would pass with the allocation
    rows present and never read. This damages the file `ea_0002` exists to
    avoid editing, and requires all five releases to be named.
    """
    distribution = "dotmac-entitlement-allocation"
    copy = tmp_path / "versions"
    shutil.copytree(DISTRIBUTIONS[distribution], copy)
    assert not _drift(copy, distribution), "the copy must start clean"

    victim = copy / "ea_0001_allocations.py"
    victim.write_bytes(victim.read_bytes() + b"\n# a formatter ran\n")

    shipped_in = _shipping_tags("ea_0001_allocations.py")
    assert len(shipped_in) == 6, shipped_in
    problems = _drift(copy, distribution)
    assert len(problems) == len(shipped_in), problems
    for problem, tag in zip(problems, shipped_in, strict=True):
        assert tag in problem
        assert "ea_0001_allocations.py" in problem
        assert (
            "a06682b221ac454a4e6df778c3184be59b63bde4bb527eacb27977c940425e22"
            in problem
        ), "the message must name the digest that shipped, not just 'differs'"


@pytest.mark.parametrize("key", sorted(GRANDFATHERED_DIVERGENCES))
def test_the_grandfathered_divergence_refuses_one_more_byte_set(
    key: tuple[str, str],
    tmp_path: Path,
) -> None:
    """Sensitivity: grandfathering history is not permission to edit again.

    Parametrized over every declared divergence rather than written once
    against approvals. A hardcoded proof would have covered the approvals row
    and said nothing about the ticketing row added beside it -- and an
    exception nobody has watched refuse anything is the shape ADR-0018 calls a
    guard with no sensitivity.
    """
    distribution, filename = key
    copy = tmp_path / "versions"
    shutil.copytree(DISTRIBUTIONS[distribution], copy)
    assert not _drift(copy, distribution), "the canonical copy must start clean"

    victim = copy / filename
    victim.write_bytes(victim.read_bytes() + b"\n# one more byte set\n")

    problems = _drift(copy, distribution)
    assert len(problems) == 1, problems
    assert "grandfathered released variants" in problems[0]
    assert "canonical sha256" in problems[0]
    assert GRANDFATHERED_DIVERGENCES[key].canonical_digest in problems[0], (
        "the message must name the canonical digest the tree must retain, not "
        "just report that the bytes differ"
    )


def test_one_distributions_damage_is_not_attributed_to_the_other(
    tmp_path: Path,
) -> None:
    """The scoping proof the second distribution makes necessary.

    `_drift` filters by owner. Without that filter it would hunt every recorded
    filename in whichever directory it was handed — so an intact allocation
    lineage would be reported as four MISSING files every time integration's
    directory was checked, and a guard that fails loudly for the wrong module
    is one whose next real failure gets waved through.

    Damage integration; require the allocation lineage, on disk and untouched,
    to stay silent.
    """
    damaged = tmp_path / "integration"
    shutil.copytree(DISTRIBUTIONS["dotmac-integration"], damaged)
    victim = damaged / "ig_0002_execution.py"
    victim.write_bytes(victim.read_bytes() + b"\n")
    assert _drift(damaged, "dotmac-integration"), "the damage must be reported"

    intact = tmp_path / "allocation"
    shutil.copytree(DISTRIBUTIONS["dotmac-entitlement-allocation"], intact)
    assert not _drift(intact, "dotmac-entitlement-allocation")


# ── The map is cross-checked against the tags it claims to quote ────────────


def _tag_oracle() -> object:
    """The repository's ONE definition of a usable tag oracle.

    Reusing `declared_publication_sweep` rather than re-implementing `git tag`
    here: two answers to "can this checkout be trusted about tags?" is how one
    of them ends up lenient. Its refusals are `SweepRefused`, and they are
    propagated, never converted to a skip.
    """
    import importlib.util

    path = REPO_ROOT / "scripts/declared_publication_sweep.py"
    spec = importlib.util.spec_from_file_location("declared_publication_sweep", path)
    assert spec is not None and spec.loader is not None
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    return sweep


def _blob_digest(tag: str, name: str) -> str:
    """SHA-256 of the migration file as git holds it at `tag`.

    The directory comes from the tag's own recorded distribution, not from a
    module constant — with two lineages in the map, a fixed path would compare
    one distribution's tags against the other's files and fail on every one.
    """
    distribution, _, _ = RELEASED_TAGS[tag]
    relative = DISTRIBUTIONS[distribution].relative_to(REPO_ROOT) / name
    # Fixed argv, no shell. The only interpolated values are this file's own
    # literals — a tag and a path from `RELEASED_TAGS`. `git` from PATH is the
    # same trust assumption every other subprocess guard here makes.
    argv = ["git", "show", f"{tag}:{relative.as_posix()}"]
    result = subprocess.run(  # noqa: S603 # nosec B603 B607
        argv, cwd=REPO_ROOT, capture_output=True, check=False
    )
    assert result.returncode == 0, (
        f"`git show {tag}:{relative}` failed: {result.stderr.decode().strip()} "
        "— the map names a tag or a path this checkout does not have"
    )
    return hashlib.sha256(result.stdout).hexdigest()


def _tag_inventory_problems(tags: set[str]) -> list[str]:
    """Recorded and published tags must agree in both directions."""
    problems: list[str] = []
    recorded = set(RELEASED_TAGS)
    missing = sorted(recorded - tags)
    if missing:
        problems.append(f"recorded tags absent from checkout: {missing}")
    for distribution, prefix in sorted(TAG_PREFIXES.items()):
        published = {tag for tag in tags if tag.startswith(prefix)}
        recorded_for_distribution = {
            tag for tag, (owner, _, _) in RELEASED_TAGS.items() if owner == distribution
        }
        unrecorded = sorted(published - recorded_for_distribution)
        if unrecorded:
            problems.append(
                f"{distribution}: published tags missing from RELEASED_TAGS: "
                f"{unrecorded}"
            )
    return problems


def test_the_tag_oracle_is_usable_and_complete() -> None:
    """Fail closed, exactly as `test_declared_publication.py` now does.

    A shallow or tagless checkout cannot answer what a release contained. The
    previous version of that module treated an unusable oracle as a skip and
    ran green while checking nothing on every PR for weeks (#202). This asserts
    the oracle up front so the cross-check below cannot inherit that shape.
    """
    sweep = _tag_oracle()
    assert not sweep.is_shallow(REPO_ROOT), (  # type: ignore[attr-defined]
        "shallow checkout: the released-migration cross-check needs full "
        "history and tags — every CI job that reads release history must set "
        "fetch-depth: 0"
    )
    tags = set(sweep.git_tags(REPO_ROOT))  # type: ignore[attr-defined]
    problems = _tag_inventory_problems(tags)
    assert not problems, "released-tag inventory:\n" + "\n".join(problems)


def _job_fetches_full_history(workflow: dict[str, object], job_name: str) -> bool:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return False
    job = jobs.get(job_name)
    if not isinstance(job, dict):
        return False
    steps = job.get("steps")
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict) or not str(step.get("uses", "")).startswith(
            "actions/checkout@"
        ):
            continue
        checkout_with = step.get("with")
        return isinstance(checkout_with, dict) and checkout_with.get("fetch-depth") == 0
    return False


def test_every_ci_job_that_reads_release_history_fetches_tags() -> None:
    """The unit oracle and PostgreSQL upgrade proofs both execute git show."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    missing = [
        job_name
        for job_name in ("unit", "integration")
        if not _job_fetches_full_history(workflow, job_name)
    ]
    assert not missing, (
        f"CI jobs {missing} execute release-history proofs without a full checkout; "
        "set actions/checkout fetch-depth: 0 so published tags are evidence"
    )


def test_the_ci_tag_checkout_guard_detects_a_missing_fetch_depth() -> None:
    """Sensitivity: the detector must fail when a checkout loses its tag oracle."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    checkout = next(
        step
        for step in workflow["jobs"]["integration"]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    checkout.pop("with", None)
    assert not _job_fetches_full_history(workflow, "integration")


@pytest.mark.parametrize("distribution", sorted(TAG_PREFIXES))
def test_the_tag_inventory_rejects_an_unrecorded_future_release(
    distribution: str,
) -> None:
    """Sensitivity: every enrolled lineage refuses an unrecorded future tag."""
    fake = f"{TAG_PREFIXES[distribution]}99.0.0"
    problems = _tag_inventory_problems(set(RELEASED_TAGS) | {fake})
    assert problems == [
        f"{distribution}: published tags missing from RELEASED_TAGS: ['{fake}']"
    ]


@pytest.mark.parametrize("tag", sorted(RELEASED_TAGS))
def test_each_recorded_commit_is_the_exact_peeled_tag(tag: str) -> None:
    """A digest match cannot substitute for the tag's immutable coordinate."""
    recorded = RELEASED_TAGS[tag][1]
    argv = ["git", "rev-parse", f"{tag}^{{commit}}"]
    peeled = subprocess.run(  # noqa: S603 # nosec B603 B607
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert peeled.returncode == 0, peeled.stderr
    assert (
        len(recorded) == 40 and recorded == peeled.stdout.strip()
    ), f"{tag}: map records {recorded!r}, peeled tag is {peeled.stdout.strip()!r}"


@pytest.mark.parametrize("tag", sorted(RELEASED_TAGS))
def test_the_recorded_digests_are_what_the_tag_actually_holds(tag: str) -> None:
    """The half that makes the map hard to doctor.

    Editing a released migration and updating its digest here would satisfy
    every test above — the tree and the map would simply agree with each other
    about the wrong bytes. This compares the map to git, so the two can only be
    reconciled by moving a tag.

    It also proves the file SET: a released file quietly dropped from the map
    would go unnoticed by a digest comparison that only walks the map, so the
    tag's own file list is the expected set.
    """
    distribution, commit, files = RELEASED_TAGS[tag]
    relative = DISTRIBUTIONS[distribution].relative_to(REPO_ROOT).as_posix()
    argv = ["git", "ls-tree", "-r", "--name-only", tag, "--", relative]
    listing = subprocess.run(  # noqa: S603 # nosec B603 B607
        argv, cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert listing.returncode == 0, listing.stderr
    at_tag = {
        line.rsplit("/", 1)[-1]
        for line in listing.stdout.splitlines()
        if line.strip() and not line.endswith("/__init__.py")
    }
    assert at_tag == set(files), (
        f"{tag} ({commit}) contains {sorted(at_tag)} but the map records "
        f"{sorted(files)} — a released file is missing from, or invented in, "
        "this entry"
    )
    for name, expected in sorted(files.items()):
        assert _blob_digest(tag, name) == expected, (
            f"{tag}/{name}: the map records {expected} but git holds "
            f"{_blob_digest(tag, name)} at that tag — the map was edited to "
            "match a changed file instead of the change being reverted"
        )


def test_the_cross_check_would_catch_a_doctored_map() -> None:
    """Sensitivity for the two above, without touching a real tag.

    `_blob_digest` reads git; the assertion compares it to the map. Point it at
    a file whose recorded digest is deliberately wrong and it must disagree —
    otherwise the comparison is not reading git at all, which is exactly how a
    cross-check degrades into a second copy of the thing it checks.
    """
    # One derived example per enrolled distribution. A hardcoded spot-check
    # stopped at four owners while the registry grew past thirty, so its claim
    # of covering every path silently became false.
    examples: dict[str, tuple[str, str]] = {}
    for tag, (owner, _, files) in sorted(RELEASED_TAGS.items()):
        if files:
            examples.setdefault(owner, (tag, sorted(files)[0]))
    assert set(examples) == set(DISTRIBUTIONS)

    for tag, name in examples.values():
        actual = _blob_digest(tag, name)
        assert actual == RELEASED_TAGS[tag][2][name]
        assert actual != "0" * 64


@pytest.mark.parametrize("tag", sorted(RELEASED_TAGS))
def test_each_recorded_digest_is_a_sha256(tag: str) -> None:
    """A truncated or mistyped digest would compare unequal to everything and
    turn the guard into a permanent failure — or, pasted from the wrong column,
    into a permanent pass against a value nothing produces."""
    _, _, files = RELEASED_TAGS[tag]
    for name, digest in files.items():
        assert len(digest) == 64, f"{tag}/{name}: {digest!r} is not a sha256"
        assert set(digest) <= set("0123456789abcdef"), f"{tag}/{name}: {digest!r}"
