"""The two prerequisites Lane 3 cannot start without: a lease, and a vantage.

Both encode a failure that actually happened on this fleet.

**The lease.** Measured on the rehearsal target 2026-08-30, `/var/lock` held
`lvm/` and `subsys/` and nothing else — there was no lease mechanism at all,
while eleven agents' worktrees shared the host. "Exclusive lease" was a sentence
in a plan, and a sentence is not a lock. The rule that shapes `lease.py` is that
a lease **cannot be self-granted**: it must reference the Platform CP
authorization run, because a holder who writes its own lease has proved only
that it can write a file.

**The vantage.** `198.51.100.155` was qualified as "outside every Dotmac
allowlist" on the strength of refusals, then found to hold a second NIC into a
private network. Re-measured 2026-08-30 that NIC is gone — which removed the
risk AND removed the discrimination control that depended on it. So
qualification is now a set of positive proofs, and the last one is measured from
the FAR END, because it is the only one a vantage cannot fake about itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from dotmac_deployment_foundation.controller_identity import (
    ControllerSshFingerprintV1,
)
from dotmac_deployment_foundation.errors import PreconditionFailed, SpecError
from dotmac_deployment_foundation.lease import HostLease, load_lease, write_lease
from dotmac_deployment_foundation.vantage import (
    VantageQualification,
    qualify_vantage,
)

RUN = "pcp-run-9182"
PRINCIPAL = "repo:michaelayoade/dotmac_starter_mt:ref:refs/heads/main"
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
#: A real OpenSSH fingerprint — `SHA256:` and 43 characters of unpadded base64,
#: which is what `ssh-keygen -lf` emits. This fixture read `"SHA256:abc"` while
#: `HostLease` only checked the field was non-empty; the field is now a
#: `ControllerSshFingerprintV1` and that value is refused by decoding.
CONTROLLER = ControllerSshFingerprintV1.parse(
    "SHA256:T1kdK/6QTzzwU1EienO6nUgk8wu9UpjqB8BatKbndSE", field="controller"
)


def _lease(**overrides: str) -> HostLease:
    fields = {
        "target": "203.0.113.10",
        "holder": "deployment-foundation-rehearsal",
        "authorization_run_id": RUN,
        "starts_at": "2026-08-30T11:00:00+00:00",
        "expires_at": "2026-08-30T15:00:00+00:00",
        "compose_project_prefix": "lane3-",
        "controller_identity_fingerprint": CONTROLLER,
        # REQUIRED on HostLease.v2 and deliberately not defaulted: a lease
        # names the authenticated workload that holds it, and a fixture
        # omitting it would be a lease this facility cannot issue.
        "workload_principal": PRINCIPAL,
    }
    fields.update(overrides)
    return HostLease(**fields)  # type: ignore[arg-type]


# ── the lease ───────────────────────────────────────────────────────────────


def test_a_live_lease_for_this_authorization_covers_the_run() -> None:
    """The accepting control for every lease refusal below."""
    _lease().covers(now=NOW, authorization_run_id=RUN)


def test_a_lease_naming_no_authorization_run_is_refused() -> None:
    """The rule, stated as a refusal: a lease is not self-granted."""
    with pytest.raises(SpecError, match="not self-granted"):
        _lease(authorization_run_id="  ")


def test_a_lease_taken_for_another_authorization_does_not_cover_this_run() -> None:
    """The substitution that would otherwise let a window granted for one piece
    of work shelter a different one."""
    with pytest.raises(PreconditionFailed, match="does not cover another"):
        _lease().covers(now=NOW, authorization_run_id="pcp-run-0001")


def test_an_expired_lease_is_refused_rather_than_treated_as_weak() -> None:
    """The host may already have been handed to someone else."""
    with pytest.raises(PreconditionFailed, match="expired"):
        _lease().covers(now=NOW + timedelta(hours=4), authorization_run_id=RUN)


def test_a_lease_that_has_not_begun_is_refused() -> None:
    with pytest.raises(PreconditionFailed, match="does not begin until"):
        _lease().covers(now=NOW - timedelta(hours=2), authorization_run_id=RUN)


def test_a_zero_length_lease_is_not_a_lease() -> None:
    with pytest.raises(SpecError, match="not after"):
        _lease(expires_at="2026-08-30T11:00:00+00:00")


def test_the_holder_is_a_fixed_token_not_free_text() -> None:
    with pytest.raises(SpecError, match="holder must be"):
        _lease(holder="some-other-agent")


def test_the_project_prefix_scopes_the_deletion_set(tmp_path) -> None:
    """What makes the post-rehearsal deletion set label-scoped by construction
    rather than by anyone remembering which objects were theirs."""
    lease = _lease()
    assert lease.owns_project("lane3-pcp-run-9182")
    assert not lease.owns_project("erp-fin-perms-0778")


def test_a_lease_round_trips_and_a_missing_one_refuses(tmp_path) -> None:
    write_lease(_lease(), directory=tmp_path)
    assert load_lease("203.0.113.10", directory=tmp_path) == _lease()
    with pytest.raises(PreconditionFailed, match="no lease record"):
        load_lease("198.51.100.1", directory=tmp_path)


def test_taking_a_host_already_leased_to_another_run_is_refused(tmp_path) -> None:
    """Two holders each believing they have exclusive use is worse than no
    lease, because both then skip the checks a shared host needs."""
    write_lease(_lease(), directory=tmp_path, now=NOW)
    with pytest.raises(PreconditionFailed, match="already leased"):
        write_lease(
            _lease(authorization_run_id="pcp-run-0002"),
            directory=tmp_path,
            now=NOW,
        )


def test_the_refusal_does_not_depend_on_the_wall_clock(tmp_path) -> None:
    """This assertion used to expire.

    `_lease()` holds until 15:00 UTC on 2026-08-30 and `write_lease` read
    `datetime.now(UTC)`, so from 15:00 that day the stored lease read expired,
    the host read free, and the refusal above silently stopped firing --
    turning green to red on a date rather than on a change. Pinning `now`
    fixes that case; this proves the dependency is gone rather than merely
    postponed, which pushing the fixture forward would not.
    """
    write_lease(_lease(), directory=tmp_path, now=NOW)
    long_after = datetime(2099, 1, 1, tzinfo=UTC)
    contender = _lease(authorization_run_id="pcp-run-0003")

    # Before expiry: refused, because a live lease is held for another run.
    with pytest.raises(PreconditionFailed, match="already leased"):
        write_lease(contender, directory=tmp_path, now=NOW)

    # After expiry: permitted, and this is the half that proves `now` is read
    # at all. If the parameter were ignored, both calls would refuse.
    write_lease(contender, directory=tmp_path, now=long_after)
    assert load_lease("203.0.113.10", directory=tmp_path).authorization_run_id == (
        "pcp-run-0003"
    )


# ── the vantage ─────────────────────────────────────────────────────────────


def _vantage(**overrides) -> VantageQualification:
    fields = {
        "address_v4": "198.51.100.7",
        "address_v6": "2001:db8::7",
        "public_interface": "eth0",
        "interfaces": {"eth0": ("198.51.100.7/20", "2001:db8::7/64")},
        "link_kinds": (),
        "routes_to_target": {"ipv4": "eth0", "ipv6": "eth0"},
        "private_paths_unreachable": {"10.0.0.2": True, "10.0.0.3": True},
        "credential_markers": {"openbao_dir": False, "bao_env": False},
        "observed_source_v4": "198.51.100.7",
        "observed_source_v6": "2001:db8::7",
    }
    fields.update(overrides)
    return VantageQualification(**fields)  # type: ignore[arg-type]


def test_a_clean_single_interface_vantage_qualifies() -> None:
    """The accepting control — and the shape `198.51.100.155` now has."""
    assert qualify_vantage(_vantage()).qualified


def test_a_second_interface_disqualifies_even_with_clean_routes() -> None:
    """The retracted 2026-08-29 shape. A second interface is a second path, and
    the interface list is what makes 'the route left via eth0' meaningful."""
    observed = _vantage(
        interfaces={"eth0": ("198.51.100.7/20",), "eth1": ("10.0.0.4/22",)}
    )
    problems = " ".join(observed.refusals)
    assert "exactly one" in problems
    assert "10.0.0.4/22" in problems
    with pytest.raises(SpecError):
        qualify_vantage(observed)


def test_a_tunnel_disqualifies() -> None:
    observed = _vantage(link_kinds=("wireguard",))
    assert any("tunnel" in problem for problem in observed.refusals)


def test_a_reachable_former_private_path_disqualifies() -> None:
    observed = _vantage(private_paths_unreachable={"10.0.0.2": False})
    assert any("still REACHABLE" in problem for problem in observed.refusals)


def test_unprobed_private_paths_are_refused_rather_than_assumed_absent() -> None:
    """An unprobed path is not an absent one — this is the check that the
    retracted NIC's reach is genuinely gone rather than merely unlisted."""
    observed = _vantage(private_paths_unreachable={})
    assert any(
        "unprobed" in p or "no former private path" in p for p in observed.refusals
    )


def test_assumed_credential_absence_is_refused() -> None:
    observed = _vantage(credential_markers={})
    assert any("assumed" in problem for problem in observed.refusals)


def test_holding_fleet_credentials_disqualifies() -> None:
    observed = _vantage(credential_markers={"openbao_dir": True})
    assert any("credential material" in problem for problem in observed.refusals)


def test_a_route_leaving_by_another_interface_disqualifies_that_family() -> None:
    observed = _vantage(routes_to_target={"ipv4": "eth0", "ipv6": "eth1"})
    problems = " ".join(observed.refusals)
    assert "ipv6 route" in problems


def test_the_far_end_disagreeing_about_the_source_disqualifies() -> None:
    """The one proof the vantage cannot fake about itself, and the replacement
    for the discrimination control lost when the second NIC was removed."""
    observed = _vantage(observed_source_v4="203.0.113.99")
    assert any("egressing from somewhere other" in p for p in observed.refusals)


def test_a_missing_far_end_observation_disqualifies() -> None:
    observed = _vantage(observed_source_v6="")
    assert any("never recorded" in problem for problem in observed.refusals)


def test_every_reason_is_reported_at_once() -> None:
    """A vantage with three defects should not take three rounds to fix, and a
    reader who sees only the first assumes it is the only one."""
    observed = _vantage(
        interfaces={"eth0": ("198.51.100.7/20",), "wg0": ("10.9.0.1/24",)},
        link_kinds=("wireguard",),
        credential_markers={"openbao_dir": True},
    )
    assert len(observed.refusals) >= 3
