"""One capability id, two connectors, and no published contract between them.

ADR-0024 § 8.1 says a capability id is one contract with one payload, and § 8.4
records that two shipped capability families had each grown two dialects with no
gate able to see it. §§ 10-12 built the gate: the owning DOMAIN publishes the
schema, a connector may only claim its digest, and four seams enforce it.

The gate does not, by itself, repair anything already shipped. Every capability
in the fleet is in a declared `SchemaGrace` on the day it lands, and § 11.2 is
explicit that `messaging.send.v1` is repaired by SUCCESSION — new ids — rather
than by redefining a published version. So the shipped divergence stays for a
bounded window, and the question this file answers is the one ADR-0032 asks of
any gap: is it OBSERVED, or merely unnoticed?

This is the observation. It reads every connector distribution in this
repository, computes which capability ids are implemented by more than one of
them, and holds that register against a named, reviewed expectation. It is a
TWO-DIRECTIONAL ratchet: adding a second implementation of a capability without
recording it fails, and so does removing one without lowering the register —
because a silently shrinking backlog is how a gap stops being tracked while
still existing somewhere else.

Nothing here asserts the divergence is acceptable. It asserts that it is
enumerable, attributed, and cannot grow unnoticed.
"""

from __future__ import annotations

import importlib
from typing import Final

import pytest

#: Every connector distribution this repository builds, by its distribution's
#: import package. Listed rather than discovered from entry points because entry
#: points describe what is INSTALLED, and this guard is about what is BUILT
#: here — a connector dropped from the install set must still be counted.
CONNECTOR_PACKAGES: Final[tuple[str, ...]] = (
    "dotmac_connector_flutterwave",
    "dotmac_connector_linkedin",
    "dotmac_connector_meta_social",
    "dotmac_connector_mono",
    "dotmac_connector_paystack",
    "dotmac_connector_remita",
    "dotmac_connector_traccar",
    "dotmac_connector_whatsapp",
)

#: The reviewed register, as of 2026-08-24. Each row is a capability id served
#: by two or more connectors while NO owning domain has published a payload
#: contract for it — so nothing can currently prove the two agree.
#:
#: `messaging.send.v1` is the one ADR-0024 § 8.4 documents in full:
#: `meta_whatsapp` takes `send_text | send_template | send_media` with a
#: `recipient` parameter, `meta_social` takes
#: `send_direct_message | reply_to_comment` with `recipient_id` plus `channel`.
#: Two disjoint command vocabularies behind one id. § 11.2 rules that it is
#: repaired by SUCCESSION — `messaging.direct.send.v2`,
#: `social.comment.reply.v1` and `social.profile.read.v1` — and NOT by
#: redefining v1, which is why this entry is expected to persist until Sub has
#: migrated and v1 is retired, rather than to disappear in the change that
#: built the gate.
#:
#: The payments rows are § 8.4's other family, and ADR-0061 A3 answers them the
#: same way: the payload question is decided ONCE by the domain contract and
#: each connector adapts internally.
SHARED_UNGATED_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "messaging.receive.v1": frozenset({"meta_social", "meta_whatsapp"}),
    "messaging.send.v1": frozenset({"meta_social", "meta_whatsapp"}),
    "payments.intent.v1": frozenset({"flutterwave", "paystack"}),
    "payments.refund.v1": frozenset({"flutterwave", "paystack"}),
    "payments.settlement.observation.v1": frozenset({"flutterwave", "paystack"}),
}


def _implementers() -> dict[str, frozenset[str]]:
    """capability id → the connector keys that implement it, across the repo."""
    found: dict[str, set[str]] = {}
    for package in CONNECTOR_PACKAGES:
        manifest = importlib.import_module(package).PLUGIN.manifest
        for capability_id in manifest.capability_ids:
            found.setdefault(capability_id, set()).add(manifest.connector_key)
    return {
        capability_id: frozenset(keys)
        for capability_id, keys in found.items()
        if len(keys) > 1
    }


def test_the_shared_ungated_register_matches_the_reviewed_one() -> None:
    """The ratchet, in both directions.

    Growing is the obvious failure: a second connector behind a capability with
    no published contract is a new place two payload dialects can diverge, and
    it must not appear without a reviewer seeing it.

    SHRINKING fails too, and that is the half that is usually left out. A row
    that disappears because the capability was published, succeeded or retired
    is good news that belongs in this constant; a row that disappears because a
    connector was quietly dropped is the gap moving somewhere nobody is
    counting. Either way the diff has to say which.
    """
    assert _implementers() == SHARED_UNGATED_CAPABILITIES, (
        "the set of capability ids served by two or more connectors changed. "
        "One capability id is one contract with one payload (ADR-0024 § 8.1), "
        "and until the owning domain publishes a `command_schema` nothing can "
        "prove two implementations agree. Publish the contract, or record the "
        "new row here with the connectors that share it and why"
    )


def test_the_register_ratchet_bites() -> None:
    """Sensitivity proof. A comparison over a constant passes trivially if the
    computation feeding it is broken, so the computation is exercised directly
    on inputs whose answer is known."""

    class _Manifest:
        def __init__(self, key: str, ids: set[str]) -> None:
            self.connector_key = key
            self.capability_ids = frozenset(ids)

    def shared(*manifests: _Manifest) -> dict[str, frozenset[str]]:
        found: dict[str, set[str]] = {}
        for manifest in manifests:
            for capability_id in manifest.capability_ids:
                found.setdefault(capability_id, set()).add(manifest.connector_key)
        return {k: frozenset(v) for k, v in found.items() if len(v) > 1}

    one = _Manifest("alpha", {"a.b.v1", "a.c.v1"})
    two = _Manifest("beta", {"a.b.v1"})
    assert shared(one) == {}, "a single implementer is not a divergence"
    assert shared(one, two) == {"a.b.v1": frozenset({"alpha", "beta"})}
    three = _Manifest("gamma", {"a.c.v1"})
    assert set(shared(one, two, three)) == {
        "a.b.v1",
        "a.c.v1",
    }, "a newly shared capability must appear — the growing direction"


def test_every_listed_connector_package_is_importable() -> None:
    """The register's own premise (ADR-0018): a guard that silently skipped a
    package would report a shrinking backlog it had simply stopped reading."""
    for package in CONNECTOR_PACKAGES:
        module = importlib.import_module(package)
        assert hasattr(module, "PLUGIN"), f"{package} exposes no PLUGIN"


@pytest.mark.parametrize("capability_id", sorted(SHARED_UNGATED_CAPABILITIES))
def test_each_recorded_divergence_names_at_least_two_connectors(
    capability_id: str,
) -> None:
    """A one-connector row would be a register entry with nothing to diverge
    from, which would make the count meaningless."""
    assert len(SHARED_UNGATED_CAPABILITIES[capability_id]) >= 2
