"""The executor: turn a :class:`~.plan.DeploymentPlan` into effects.

The whole design rests on one seam. Every effect this package can have on the
world goes through :class:`Effects` — a Protocol with fourteen methods and no
implementation here. That is what makes the required failure-injection matrix
— a wrong digest, missing migration credentials, a failed backup, a corrupt
backup, a candidate that never becomes ready, a primary that fails after
handoff, an unhealthy worker, a stale scheduler, an invalid ingress config, an
unavailable collector, a source bind mount, a maintenance-required migration
attempted online — an ordinary unit test rather than a disposable-VM exercise.

`dotmac_sub`'s 880-line script is the extraction source and cannot do this. Its
gates are `if`-statements interleaved with `docker` invocations, so the only
way to observe a gate firing is to arrange the failure on a real host. Two of
its gates were in fact found to be wrong only in production
(`seabone-staging-dotmac-sub-deploy-landmines`): the 180-second health budget
that caused a false rollback, and the profile filter that prevented Beat from
being CREATED but not from CONTINUING TO RUN.

## What the executor is responsible for, and what it is not

It owns **order, refusal and evidence**. It does not own *how* to talk to
Docker, Postgres or Nginx — that is the `Effects` implementation, which lives
in a provider and can be swapped for a Kubernetes one without touching the
sequence.

## The rule about failure

Every step failure raises. Nothing is caught and continued, with exactly one
exception, which is stated rather than silent: `PRUNE_IMAGES` is housekeeping,
and failing an otherwise-healthy deployment because a retention sweep hit a
permission error would be worse than the debt it leaves. The original had the
same fail-open behaviour at `deploy.sh:831-836`; the difference is that here it
becomes a recorded note rather than an undocumented `|| true`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from ..authorization import ExecutionGrant
from ..authorization_v3 import (
    require_committed_consumption_v3,
    require_current_subject_v3,
)
from ..backup import BackupRecord
from ..canonical_plan import EXECUTION_PLAN_WRONG_TYPE
from ..deployment_evidence import (
    DeploymentEvidenceV1,
    DeploymentEvidenceV2,
    RunStanding,
    StepEvidenceV1,
    StepStanding,
)
from ..errors import DeploymentError, PreconditionFailed, StepFailed
from ..evidence import (
    SignatureVerifier,
    SignedEvidenceEnvelope,
    TrustPolicy,
    accept_release_evidence,
)
from ..execution_plan import (
    HostPrestateV1,
)
from ..execution_plan_v2 import (
    ExposureReconciliationV1,
    PostgresPrincipalCredentialBootstrapV1,
)
from ..execution_plan_v3 import (
    FoundationExecutionPlanV3,
    require_execution_plan_v3_digest,
)
from ..exposure import (
    ExposureEffects,
    HostObservation,
    managed_ports,
    ownership_comment,
    require_preserved_foreign_rules,
    verify_exposure,
)
from ..external_recovery import (
    EXTERNAL_BACKUP_PATH_PREFIX,
    accept_external_recovery_receipt,
    backup_record_from_receipt,
    require_restore_proof,
)
from ..host_source import HostSource
from ..host_source_admission import (
    HostSourceAdmissionProvider,
    HostSourceAdmissionTrace,
)
from ..policy import build_firewall_plan
from ..spec import ProductDeploymentSpec
from ..telemetry import Annotation
from .lock import DeploymentLockHeld
from .plan import (
    DeploymentPlan,
    Step,
    StepKind,
    steps_for_rollback,
)
from .plan import (
    _ingress_roles as _plan_ingress_roles,
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class RoleObservation:
    """What a role actually looks like right now.

    ``restarts`` is separate from ``running`` because a container that is
    running having restarted four times is a failed deployment that looks
    healthy at the instant you check it — Sub verifies `RestartCount == 0` for
    exactly this reason (`deploy.sh:232-272`).
    """

    code: str
    running: bool
    image_digest: str
    restarts: int
    source_mounted: bool = False


@dataclass(frozen=True, slots=True)
class BackupResult:
    dataset: str
    path: str
    size_bytes: int
    checksum: str
    checksum_algorithm: str


@runtime_checkable
class Effects(Protocol):
    """Everything the executor can do to the world.

    Every method either returns a fact or raises. None of them decide anything:
    the decision to fail is the executor's, from the fact returned, so the
    policy lives in one readable place instead of being distributed across
    fourteen implementations that might each interpret a failure differently.
    """

    # ── gates ──
    def image_present(self, reference: str) -> bool: ...

    def image_labels(self, reference: str) -> Mapping[str, str]: ...

    def release_evidence(self, revision: str) -> SignedEvidenceEnvelope | None:
        """The signed envelope for `revision`, parsed and TYPED — or None.

        Typed at the SEAM, deliberately. This was ``Mapping[str, str]``, and
        that type did not merely permit the corruption that made a4
        inadmissible — it required it: the envelope's `document` is a nested
        object, so every conforming provider had to stringify it, and the
        signature was then judged over a Python repr. `SignedEvidenceEnvelope`
        refuses a stringified document at construction, so a conforming
        implementation CANNOT corrupt it. None means "no evidence for this
        revision" and is refused downstream; an empty mapping used to mean
        that, and an empty mapping is also what a half-broken reader returns.
        """
        ...

    def manifest_digest(self, manifest_path: str) -> str: ...

    def observe_roles(self) -> Sequence[RoleObservation]: ...

    def working_tree_dirty(self) -> bool: ...

    def untracked_compose_overrides(self) -> Sequence[str]: ...

    def resolved_materials(self) -> Sequence[str]: ...

    # ── mutation ──
    def run_command(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        materials: Sequence[str] = (),
    ) -> CommandResult: ...

    def backup(self, dataset_code: str, *, timeout_seconds: int) -> BackupResult: ...

    def verify_backup(self, result: BackupResult) -> bool: ...

    def run_support_job(
        self, code: str, *, timeout_seconds: int, image: str
    ) -> CommandResult:
        """Run and verify the descriptor's profile-gated support job."""
        ...

    # ── candidate-image injected work (item 7 of the a5 audit) ──
    #
    # Every method below takes the image the ENGINE says this deployment is
    # about, because each one used to run against whatever happened to be
    # lying around instead: `migration_preflight` and `migrate` were bare
    # host-shell commands with no image concept at all — `alembic` from the
    # host PATH migrating a schema the CANDIDATE image's code owns — and
    # `verify_heads`/`start_candidate` used the on-disk compose file, which
    # still pins the PREVIOUS image until `switch` re-renders it at step
    # sixteen. A migration run by the old code against the new release's
    # schema expectations is the exact drift `require_prerequisites` exists
    # to catch one layer down, reintroduced by the executor itself.
    def run_migration_command(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        materials: Sequence[str] = (),
        image: str,
    ) -> CommandResult: ...

    def migration_heads(self, *, image: str) -> Sequence[str]: ...

    def stop_roles(self, roles: Sequence[str], *, timeout_seconds: int) -> None: ...

    def start_candidate(
        self, role: str, *, timeout_seconds: int, image: str
    ) -> str: ...

    def role_ready(self, role: str) -> bool: ...

    def candidate_ready(self, role: str) -> bool: ...

    def switch(self, *, timeout_seconds: int, image: str) -> None: ...

    def worker_responds(self, role: str) -> bool: ...

    def scheduler_last_tick_age_seconds(self, role: str) -> int | None: ...

    def write_evidence(self, evidence: Mapping[str, object]) -> str: ...

    def read_evidence(self, path: str) -> Mapping[str, object]: ...

    def bootstrap_principal_credential(
        self, bootstrap: PostgresPrincipalCredentialBootstrapV1
    ) -> StepStanding:
        """Install a database principal's credential from the named reference.

        THE ONLY WIDENING THIS PROTOCOL HAS TAKEN FOR THE BOOTSTRAP, and it is
        deliberately shaped so the Foundation cannot do the work:

        * it receives the TYPED plan member, not a command, a DSN or a
          statement — there is no parameter SQL could arrive through;
        * it resolves nothing. The implementation reads the OpenBao reference on
          the target and performs the compare-and-set; this facility neither
          holds the material nor sees it;
        * it RETURNS A STANDING rather than a boolean, and the executor refuses
          any standing other than `installed` or `reconciled_after_commit`. A
          provider that answers "true" has not said which history happened, and
          those two are the pair that must never collapse: one run installed the
          credential, another found it already present because an earlier
          attempt died after its commit point.

        Raise `PreconditionFailed` when the store refuses the compare-and-set —
        that is the expected answer for a record that already exists, and it is
        a refusal rather than a failure because nothing was mutated.
        """
        ...

    def prune_images(self, *, retain: int) -> None: ...

    def emit_annotation(self, annotation: Mapping[str, str]) -> None: ...


@dataclass(slots=True)
class StepRecord:
    """One step, in memory.

    ``detail`` is OPERATOR OUTPUT and is deliberately not the same thing as
    ``standing``. The sentence is what a human reads on the terminal; the
    standing is what the evidence document records. Keeping both is what lets
    the persisted record be closed without making the CLI less useful — see
    `deployment_evidence`, which has no field this string could be written to.
    """

    kind: StepKind
    target: str
    ok: bool
    detail: str
    duration_seconds: float
    standing: StepStanding = StepStanding.OK


@dataclass(slots=True)
class DeploymentOutcome:
    """What happened, in enough detail to be the evidence artefact."""

    plan: DeploymentPlan
    records: list[StepRecord] = field(default_factory=list)
    succeeded: bool = False
    failed_step: StepKind | None = None
    failure: str = ""
    mutated: bool = False
    notes: list[str] = field(default_factory=list)
    evidence_path: str = ""
    #: `ExecutionPlanDigestV1` and the operation, carried onto the report so the
    #: thing that ran is recognisable as the thing Control froze. Empty when the
    #: run was not bound to an authorized execution plan -- and empty is REPORTED
    #: rather than defaulted to something plausible, because a report that
    #: invents a digest is worse evidence than one that says it has none.
    execution_plan_digest: str = ""
    #: The other two terms, persisted under their OWN names. The outcome used to
    #: carry the execution-plan digest alone (always empty, see `Executor`), no
    #: descriptor digest at all, and no name for Control's plan digest — so the
    #: evidence could not distinguish three measurements that must never be
    #: conflated. `provenance.py` explains why they are separate.
    descriptor_digest: str = ""
    control_plan_digest: str = ""
    #: Control's replay coordinate, echoed onto the report so Control can place
    #: this execution against its target's high-water mark. Zero means "not
    #: carried", which `authorize_v3()` makes unreachable on a real run.
    execution_sequence: int = 0
    attempt_no: int = 0
    #: Deterministic Control ledger coordinate, set only after consume returns.
    control_consumption_ref: str = ""
    operation: str = ""
    #: The run's outcome as ONE CLOSED WORD, replacing the free-text `failure`
    #: field in the persisted record. `failure` still exists here, still holds
    #: `str(exc)`, and is still what the CLI prints — it simply no longer
    #: travels. See `deployment_evidence` for why that split is the whole point.
    standing: RunStanding = RunStanding.FAILED

    def as_evidence(self) -> dict[str, object]:
        """The persisted record, through the CLOSED type.

        This used to build a free-form mapping with three open text channels —
        ``failure`` (assigned from ``str(exc)``), ``steps[].detail`` (prose,
        twelve handlers building it with an f-string over live values) and
        ``notes`` (including ``f"evidence could not be written: {exc}"``). Raw
        exception text reached all three, and a guard placed before each write
        would not have caught it: `require_no_secrets` is a SHAPE detector and
        stderr is not secret-shaped.

        `DeploymentEvidenceV1` has no field any of them could be written to.
        """
        evidence = DeploymentEvidenceV1(
            product=self.plan.product,
            image_reference=self.plan.image,
            image_digest=self.plan.image_digest,
            source_revision=self.plan.source_revision,
            manifest_digest=self.plan.manifest_digest,
            execution_plan_digest=self.execution_plan_digest,
            descriptor_digest=self.descriptor_digest,
            control_plan_digest=self.control_plan_digest,
            execution_sequence=int(self.execution_sequence),
            attempt_no=int(self.attempt_no),
            operation=self.operation,
            strategy=self.plan.strategy.value,
            standing=self.standing,
            succeeded=self.succeeded,
            mutated=self.mutated,
            failed_step=self.failed_step.value if self.failed_step else "",
            steps=tuple(
                StepEvidenceV1(
                    kind=record.kind.value,
                    target=record.target,
                    standing=record.standing,
                    duration_seconds=record.duration_seconds,
                )
                for record in self.records
            ),
        )
        if self.control_consumption_ref:
            return DeploymentEvidenceV2(
                base=evidence, control_consumption_ref=self.control_consumption_ref
            ).as_document()
        return evidence.as_document()


#: Refused: the provider cannot be moved into stage two.
STAGE_TWO_ABSENT: Final = "execution_plan.stage_two_absent"

#: Refused: the provider rejected the authorized facts.
STAGE_TWO_REFUSED: Final = "execution_plan.stage_two_refused"


def bind_authorized_effects(
    effects: Effects,
    plan: FoundationExecutionPlanV3,
) -> None:
    """Move effects into stage two, from the AUTHORIZED plan. Foundation owns this.

    Call it after `render_execution_plan` and before `Executor`. That is the only
    window in which the two facts exist: the plan carries them and the plan
    cannot exist until the effects do, because rendering it reads
    ``observe_roles()`` on those same effects.

    ## Why this is a second call and not four constructor arguments

    The circularity is real. An assembly's provider needs the target identity and
    the frozen prestate; both live on the plan; the plan is rendered from the
    provider. Nothing can break that by ordering alone, so the seam is two
    stages: `build_effects(spec, deploy_dir)` satisfies the published binding
    contract, and this supplies what only the authorized plan knows.

    ## THE PROHIBITIONS ARE STRUCTURAL, NOT REMEMBERED

    * **No re-observation after authorization.** There is no `observe_roles()`
      call in this function. That is not a rule to keep — it is an absent call,
      and `test_the_stage_two_caller_never_reobserves` derives it from the AST
      rather than trusting the reading. A prestate read here would be a second
      authority over a fact the plan already fixed.
    * **No caller-supplied attempt number.** This function has no such
      parameter, so nothing here can assert what the envelope should carry. The
      coordinate reaches the report from the receipt, through the grant.
    * **No raw mapping.** The plan is type-checked before anything is read off
      it, so a mapping with the right keys cannot stand in for the document that
      was frozen.

    ## Unbound is not empty, and the projection is the identity

    `HostPrestateV1.roles` is already sorted ``(role_code, image_digest)`` pairs
    with each role named once, and the provider's own validator applies the same
    rules and REFUSES an unsorted sequence rather than repairing it. So this
    passes the frozen tuple through unchanged: there is no sort, no rebuild and
    no mapping step, because any of those would be a second opinion about a fact
    the plan froze.

    An EMPTY prestate is a positive claim — "no role containers, a first
    deployment" — and `plan.host_prestate` is a required field with no default,
    so this can never pass ``None``. The provider keeps unbound as its own type
    for the same reason: collapsing them would label the previous release's own
    bytes a first deployment, and that is visible only during a restore.
    """
    if not isinstance(plan, FoundationExecutionPlanV3):
        raise PreconditionFailed(
            f"stage two takes the typed execution plan, not a "
            f"{type(plan).__name__}. A mapping with the right keys is not the "
            "document that was frozen",
            code=EXECUTION_PLAN_WRONG_TYPE,
        )
    bind = getattr(effects, "bind_authorized_execution", None)
    if not callable(bind):
        raise PreconditionFailed(
            f"{type(effects).__name__} cannot be moved into stage two: it "
            "declares no `bind_authorized_execution(target=, incumbent_roles=)`. "
            "A provider that needs the authorized target and the frozen prestate "
            "must accept them through this seam — building them into the factory "
            "is impossible, because the plan that carries them is rendered from "
            "the provider itself",
            code=STAGE_TWO_ABSENT,
        )
    try:
        bind(target=plan.target, incumbent_roles=plan.host_prestate.roles)
    except (ValueError, TypeError) as exc:
        raise PreconditionFailed(
            f"the provider refused the authorized execution facts: {exc}. "
            "Stage two passes what the plan FROZE — a refusal here means the "
            "provider was already bound to different facts, which is the drift "
            "the frozen prestate exists to catch, arriving from inside the "
            "process rather than from the host",
            code=STAGE_TWO_REFUSED,
        ) from exc


class Executor:
    """Runs a plan against an :class:`Effects` implementation.

    ``sleep`` is injected so the stability window is instantaneous in a test.
    A test that genuinely waits 120 seconds is a test nobody runs.
    """

    def __init__(
        self,
        spec: ProductDeploymentSpec,
        effects: Effects,
        grant: ExecutionGrant,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        deployment_id: str = "",
        evidence_policy: TrustPolicy | None = None,
        evidence_verifier: SignatureVerifier | None = None,
        admission_provider: HostSourceAdmissionProvider,
        recovery_receipts: Mapping[str, object] | None = None,
        recovery_verifier: SignatureVerifier | None = None,
        recovery_records: Mapping[str, Sequence[BackupRecord]] | None = None,
        now_epoch: int = 0,
        exposure_effects: ExposureEffects | None = None,
        execution_plan: FoundationExecutionPlanV3,
    ) -> None:
        """`grant` is positional and required — that is the whole point.

        An `Executor` is the only thing in this facility that mutates a host,
        so it is where authorization has to be unavoidable. Making the grant a
        required POSITIONAL parameter means a caller cannot forget it, cannot
        default it, and cannot be given one by a helper that quietly passes
        `None`. A caller with no grant has nothing to construct this with, and
        `ExecutionGrant` cannot be built outside `authorize_v3()` — so "execute on
        a flag" stops being expressible rather than merely being discouraged.
        """
        self._spec = spec
        self._effects = effects
        self._grant = grant
        # Both default to None and BOTH refuse at the point of use rather than
        # at construction. A missing policy must not be discovered only on the
        # host that had one — but it also must not stop a `plan` or a dry run,
        # neither of which verifies anything.
        self._evidence_policy = evidence_policy
        self._evidence_verifier = evidence_verifier
        # HANDED OVER, never discovered — the same rule as `recovery_receipts`
        # just below, applied to the host-source admission seam. REQUIRED, no
        # default: a caller that wants today's unconditional refusal passes
        # `RefusingHostSourceAdmissionProvider()` explicitly, so "no real
        # admission was wired in" is a visible decision at every call site
        # rather than a silent fallback. See `host_source_admission.py` for why
        # this is a constructor parameter and never an ambient registry.
        self._admission_provider: HostSourceAdmissionProvider = admission_provider
        # HANDED OVER, never discovered. There is no directory scan and no
        # `Effects.find_receipt()`: the caller passes the exact envelope for
        # each dataset, exactly as `--authorization` passes an
        # `AuthorizationReceipt`. Ambient discovery is how a stale receipt from
        # a previous quarter comes to satisfy today's gate, and a facility that
        # goes looking cannot tell "no proof exists" from "no proof was offered".
        self._recovery_receipts: Mapping[str, object] = recovery_receipts or {}
        self._recovery_verifier = recovery_verifier
        # Records the deployment already holds for this dataset. The accepted
        # receipt is APPENDED to them rather than replacing them, so a fresh
        # receipt cannot make an otherwise-overdue history look current by being
        # the only thing in the list.
        self._recovery_records: Mapping[str, Sequence[BackupRecord]] = (
            recovery_records or {}
        )
        self._now_epoch = now_epoch
        # THE MIDDLE TERM, and it is now unavoidable in both halves.
        #
        # `execution_plan` used to default to None and the authorized digest to
        # "", with `_require_execution_plan` PERMITTING "absent on both sides"
        # and returning "". `cmd_deploy` passed neither and there was no flag to
        # supply one, so every real deployment took that branch, mutated a host,
        # and wrote `deploy-evidence.json` with an empty digest. The entire
        # `ExecutionPlanDigestV1` mechanism was built, tested, and unreachable
        # from the only path that touches a host.
        #
        # The plan is now a REQUIRED keyword argument with no default, and the
        # authorized digest is not a parameter at all — it is read from the
        # grant, which carries it from the receipt. So there is no way to
        # construct an executor bound to a plan nobody froze, and no way to
        # supply an authorized digest that did not come through attestation.
        # TYPE-CHECKED AT CONSTRUCTION, not at first attribute access.
        # `RecoveryExecutionPlanV1` exists and carries no `operation` field, so
        # a swapped plan would previously have travelled all the way to
        # `_require_execution_plan` and died on `AttributeError: 'Recovery...'
        # object has no attribute 'operation'` — after the executor had been
        # built and while an operator reads a traceback rather than a refusal.
        # The two plan kinds are not interchangeable at any acceptance point,
        # and this is one of the three.
        #
        # `None` is deliberately NOT refused here, and the exclusion is the
        # opposite of a loophole. Absent-plan is an EXISTING, separately proven
        # refusal that `_require_execution_plan` makes with its own precise
        # sentence — "this executor has no execution plan, so nothing can be
        # recomputed and nothing was frozen" — and
        # `test_absent_execution_plan_produces_zero_effects` is the regression
        # test for the branch that used to let exactly that state mutate a host.
        # Swallowing `None` here would answer that case with "you passed a
        # NoneType, not a FoundationExecutionPlanV1", which is true, useless,
        # and replaces a diagnosis with a type name. Two different faults, two
        # different sentences, and the wrong-type one must not eat the other.
        if execution_plan is not None and not isinstance(
            execution_plan, FoundationExecutionPlanV3
        ):
            raise PreconditionFailed(
                f"Executor was given a {type(execution_plan).__name__} as its "
                f"execution plan, not a {FoundationExecutionPlanV3.__name__}. "
                "This executor mutates a product host under a deployment "
                "authorization, and a plan of another kind describes another "
                "act that nothing this class holds authorizes",
                code=EXECUTION_PLAN_WRONG_TYPE,
            )
        self._execution_plan = execution_plan
        # AUTHORIZED bootstraps, read off the plan and nowhere else. They are
        # inside `ExecutionPlanDigestV1`, so Control froze them; a set taken
        # from anywhere but the plan would be a set nobody approved.
        self._bootstraps: tuple[PostgresPrincipalCredentialBootstrapV1, ...] = tuple(
            getattr(execution_plan, "principal_bootstraps", ()) or ()
        )
        # AUTHORIZED exposure, read off the plan and nowhere else — same rule,
        # same `getattr` shape, and for the same reason: a V1 plan carries none,
        # so an old authorization cannot acquire a new act by being run through
        # a newer executor. The RULES are not here and never will be: they are
        # derived from the descriptor, whose digest is inside this plan and
        # inside the grant, so what gets written to a shared chain is frozen
        # transitively rather than restated somewhere it could disagree.
        self._exposure: tuple[ExposureReconciliationV1, ...] = tuple(
            getattr(execution_plan, "exposure_reconciliations", ()) or ()
        )
        # HANDED OVER, never constructed here. `exposure.py` owns the seam and
        # the measurement; `providers/exposure_host.py` owns one implementation
        # of it; this class owns the ORDER, which until now was owned by a
        # second class in a third place. Defaults to None and refuses at the
        # point of use, like the evidence policy above: a plan that authorizes
        # no exposure must not require a provider to be installed.
        self._exposure_effects = exposure_effects
        self._sleep = sleep
        self._clock = clock
        self._rolling_back = False
        # Identifies this RUN, not this release: two deployments of one digest
        # to one host are two deployments, and an operator asking whether the
        # second one fixed it needs them apart.
        self._deployment_id = deployment_id or "unset"
        self._notes_sink: list[str] = []
        # A step that succeeded by a DELIBERATE fail-open records `non_fatal`
        # rather than `ok`. "It worked" and "it did not work and we decided that
        # was acceptable" are different facts, and the free-text `detail` was the
        # only thing carrying the difference before the record was closed. Image
        # retention is the live case and currently the only one.
        self._non_fatal: dict[StepKind, StepStanding] = {}
        # The real BackupResult per dataset, kept as a value rather than
        # reconstructed from a formatted note. See `_do_verify_backup`.
        self._backups: dict[str, BackupResult] = {}
        # Set by `run`/`rollback` from the caller's proven hold. Empty here
        # rather than Optional-with-a-default-path: a value invented at
        # construction would be a lock path for a lock nobody took.
        self._lock_path: Path | str = ""
        # NO HOST SOURCE PARSING INGREDIENTS ARE ACCEPTED HERE, DELIBERATELY,
        # and this is the THIRD time this comment has had to say so.
        #
        # The first repair (`host_source_receipt`/`host_source_metadata` as
        # the only accepted parameters, `host_source_installed`/
        # `host_source_probe` removed) was itself a live bypass respelled: a
        # caller supplying BOTH a `CandidateReceipt` (a plain frozen
        # dataclass, constructible by anyone who imports it, carrying
        # `artifact_digest` directly) AND an `InstalledMetadata` whose
        # `read_text("direct_url.json")` returns a caller-chosen JSON string
        # could still state the SAME digest on both sides of the comparison
        # `require_host_source` makes — byte-for-byte the admission
        # `host_source_installed=` produced, with a `json.dumps` in between.
        # `valid_host_source_kwargs()` (`tests/unit/host_source_stance.py`)
        # WAS this exploit, shipped as a convenience fixture every "admitted
        # executor" test used. `CandidateReceipt` and `InstalledMetadata` are
        # PARSING interfaces — either half, alone or together, is
        # caller-authored data, and no combination of "verify the receipt's
        # shape" and "verify the metadata's shape" turns it into proof of
        # what a trusted third party attested.
        #
        # The seam this class DOES accept now is `admission_provider`: one
        # argument-free method returning a HostSource and trace. This type is
        # NOT proof of provenance. An arbitrary in-process constructor caller
        # can supply a method returning invented values; the executor does not
        # authenticate the provider or its result. A real provider therefore
        # requires a trusted, non-request-selectable assembly binding and
        # fresh Control-backed verification before it can be used in a
        # mutating deployment. The shipped CLI passes
        # `RefusingHostSourceAdmissionProvider()` explicitly, and an
        # architecture test guards that refusal-only call-site premise. This
        # parameter is REQUIRED, with no default: a caller that wants today's
        # unconditional refusal constructs `RefusingHostSourceAdmissionProvider()`
        # itself — which calls exactly `require_host_source(receipt=None)` and
        # always refuses, with the exact typed refusal (`NO_RECEIPT`, or
        # `ABSENT`/`WRONG_KIND` if the interpreter itself has nothing
        # installed) `require_host_source` already produces today. `run` and
        # `rollback` call `_verify_host_source` themselves, which calls the
        # provider; a caller explicitly supplying the refusing provider
        # observes no behavior change from before this seam existed.
        #
        # The provider's reported identity and trace. Both remain `None`
        # until `_verify_host_source` runs, but their types alone do not prove
        # verification: only a trusted composition can establish that the
        # provider actually invoked the authenticated admission function.
        # Neither is branched on or persisted by this class.
        self._host_source: HostSource | None = None
        self._host_source_admission_trace: HostSourceAdmissionTrace | None = None

    # ── entry point ─────────────────────────────────────────────────────────

    def _descriptor_digest(self) -> str:
        """This run's descriptor digest, in the canonical spelling.

        Derived from the spec rather than taken from the caller: a digest the
        caller supplies alongside the descriptor it is asking us to run proves
        only that the caller can compute a digest.
        """
        return self._spec.to_canonical_document().sha256_digest()

    def _verify_host_source(self) -> None:
        """THE MANDATORY PREREQUISITE every mutating entry point calls.

        Delegates to `self._admission_provider.admit_host_source()` — a
        FRESH call every time, never cached across `run`/`rollback`
        invocations on the same instance. `admission_provider` is a required
        constructor argument with no default; a caller that wants today's
        unconditional refusal constructs `RefusingHostSourceAdmissionProvider`
        explicitly, which itself calls exactly `require_host_source(receipt=None)`
        and always refuses —
        `NO_RECEIPT` if the interpreter has a genuine installed artifact and
        no receipt behind it, `ABSENT`/`WRONG_KIND` if it does not even have
        that. Both are typed refusals with zero effects: nothing between the
        caller's lock and this call has mutated anything.

        This changes Boundary 4's earlier call-shape ruling: the executor
        invokes a handed-over provider rather than `require_host_source`
        directly. The protocol alone cannot enforce that the provider used
        the verifier; only trusted assembly composition can make a positive
        result admissible. A supplied provider's own
        `PreconditionFailed`/`SpecError` propagates
        unchanged: this method catches nothing, retries nothing, and never
        falls back to the refusing default once a real provider has been
        supplied. Ordering is the other half, unchanged from before this
        seam existed: called after the lock is proven held (so there is
        something to serialise against) and before EVERYTHING else — grant
        revalidation, plan-digest recomputation, annotations, principal
        bootstrap, every step.
        """
        self._host_source, self._host_source_admission_trace = (
            self._admission_provider.admit_host_source()
        )

    def run(
        self, plan: DeploymentPlan, *, lock: DeploymentLockHeld
    ) -> DeploymentOutcome:
        # THE LOCK, PROVEN RATHER THAN ASSUMED, and FIRST — before the grant,
        # before the plan digest, before `_bootstrap_principals`, before any
        # step. `_do_acquire_lock` used to return the sentence "held by the
        # caller for the duration of the run" without asking anybody, and the
        # executor named no lock, took no lock and checked no lock. The rule
        # lived in two comments in `cli.py` and held only for the two callers
        # who had read them.
        #
        # Required and keyword-only with no default, the same construction the
        # grant uses one line below: a caller holding no lock has nothing to
        # pass, so "deploy without serialising" stops being expressible rather
        # than merely being discouraged. The 2026-07-12 incident (`lock.py`)
        # was two concurrent deployments; this is the first thing in this
        # facility that would actually have refused the second one.
        self._lock_path = lock.require_held(product=self._spec.product)
        # Which Foundation is asking, verified before anything else this
        # method does. See `_verify_host_source`'s docstring for why the
        # position — right after the lock, ahead of the grant — is the ruling
        # rather than a preference.
        self._verify_host_source()
        # Re-checked here, not merely at construction: the grant names a
        # descriptor, and this asserts the plan in hand is that descriptor's.
        # A grant built early and used late is exactly where "nothing changed
        # in between" stops being safe to assume.
        self._grant.require(
            operation="deploy", descriptor_digest=self._descriptor_digest()
        )
        outcome = DeploymentOutcome(
            plan=plan,
            notes=list(plan.notes),
            # Each from the side that OWNS it: the descriptor digest re-derived
            # from the spec in hand, Control's plan digest copied verbatim off
            # the receipt and never recomputed here.
            descriptor_digest=self._descriptor_digest(),
            control_plan_digest=str(self._grant.receipt.control_plan_digest),
            execution_sequence=int(self._grant.execution_sequence),
            attempt_no=int(self._grant.attempt_no),
            operation="deploy",
        )
        digest, consumption_ref = self._require_execution_plan("deploy")
        outcome.execution_plan_digest = digest
        outcome.control_consumption_ref = consumption_ref
        # The first question about any graph that turned bad at 14:32 is what
        # changed at 14:32. No product in the fleet emits this today, and the
        # annotation is worth almost nothing after the fact — it has to be sent
        # BEFORE the work, or a deployment that dies mid-migration is the one
        # case with no marker at all.
        self._annotate("deployment.start", plan)
        try:
            self._bootstrap_principals(outcome)
            self._run_steps(plan.steps, plan, outcome)
            # AFTER the steps, and the ordering is the act's rather than a
            # preference: the rules published here point at containers that
            # `_do_switch` has already recreated, so reconciling before the
            # switch would open ports onto the outgoing image.
            self._reconcile_exposure(outcome)
            outcome.succeeded = True
            outcome.standing = RunStanding.SUCCEEDED
        except DeploymentError:
            # The failure is RETURNED on the outcome, not raised. A caller needs
            # the whole record — which steps ran, what mutated, where the gate
            # boundary was — and an exception carries only the last line of it.
            # `_run_steps` re-raises so that `rollback()` gets the same shape.
            pass
        finally:
            self._annotate(
                "deployment.success" if outcome.succeeded else "deployment.failure",
                plan,
                # The STANDING, never `outcome.failure`. That field is
                # `str(exc)`, and sending it here put raw exception text — a DSN
                # from a connection error, a fragment of SQL, whatever a driver
                # wrote — on the wire to the observability platform, on the
                # failure path, which is the one least exercised.
                detail=outcome.standing.value,
            )
            outcome.notes.extend(self._notes_sink)
            self._notes_sink.clear()
            # Evidence is written on EVERY path, including the failing ones.
            # An earlier version made `record_evidence` an ordinary step near the
            # end of the plan, so a deployment that died at `migrate` — the case
            # where an operator most needs to know what ran — left no record at
            # all. Evidence that exists only on success is evidence that is
            # absent exactly when it is wanted.
            self._persist_evidence(outcome)
        return outcome

    def _require_execution_plan(self, operation: str) -> tuple[str, str]:
        """Step 4: recompute the plan digest and consume the Control dispatch.

        Nothing here reconstructs Control's document and nothing normalizes it.
        Control froze a digest the Foundation produced; this re-derives that
        same digest from the plan actually in hand, so a mismatch means the plan
        CHANGED rather than that two canonicalizers disagreed. That distinction
        is the whole repair: while Control hashed the spec wrapped in six
        sibling keys and the Foundation hashed the descriptor alone, a mismatch
        was unavoidable and told nobody anything.

        ABSENT IS NO LONGER PERMITTED. This used to return "" when neither a
        plan nor an authorized digest was present, on the reasoning that a run
        never bound to one must not have a digest invented for its report. The
        reasoning was sound and the consequence was not: the only production
        caller supplied neither, so "unbound" was not an unusual case being
        reported honestly, it was every deployment this facility has ever run.
        A branch that is only ever taken by the path it was meant to describe as
        exceptional is not a fallback, it is the behaviour.
        """
        if self._execution_plan is None:
            raise PreconditionFailed(
                "this executor has no execution plan, so nothing can be "
                "recomputed and nothing was frozen. An unbound executor is "
                "refused BEFORE any effect: the plan is what says what will be "
                "DONE to this target under this operation, and a descriptor "
                "approval alone does not say that"
            )
        authorized = self._grant.execution_plan_digest
        if not authorized:
            raise PreconditionFailed(
                "the grant carries no authorized execution plan digest, so "
                "nothing froze this plan. Rendering a plan is not the same as "
                "having it authorized, and running the unfrozen one is the gap "
                "this contract closes"
            )
        # THE HOST IS RE-OBSERVED, not remembered. The plan's prestate is what
        # the host looked like when the plan was rendered and authorized; this
        # is what it looks like NOW, at the moment before mutation. Between the
        # two, another deployment, a manual compose invocation or a rollback
        # can have moved the base state — and an authorized change applied to
        # an unreviewed starting point is not the change that was reviewed.
        # A read, deliberately BEFORE any effect, so the refusal leaves the
        # host byte-identical.
        observed = HostPrestateV1.from_observations(self._effects.observe_roles())
        if observed != self._execution_plan.host_prestate:
            authorized_state = self._execution_plan.host_prestate.as_document()
            raise PreconditionFailed(
                "the host is not the host that was authorized: the plan was "
                f"rendered against prestate {authorized_state} "
                f"and the target now observes {observed.as_document()}. "
                "Something deployed, rolled back or hand-mutated this target "
                "after authorization. Re-render the plan against the current "
                "state and have it re-authorized; executing anyway would apply "
                "a reviewed change to an unreviewed starting point"
            )
        if self._execution_plan.operation != operation:
            raise PreconditionFailed(
                f"the execution plan authorizes {self._execution_plan.operation!r} "
                f"and this is a {operation!r}. Deploy and rollback are frozen "
                "separately, for the same reason they are authorized separately: "
                "one decision must not both make a change and erase it"
            )
        # Re-read interpreter wheel provenance and Control/Fleet-resolved host
        # identity at the last pre-effect boundary.  A matching signed digest
        # alone cannot admit a changed wheel or re-enrolled host.
        facts = require_current_subject_v3(
            plan=self._execution_plan, provider=self._grant.v3_provider
        )
        # F2's authenticated installed-host subject is a separate reading from
        # the V3 provider's Control/Fleet subject. ADR-0073 defines its
        # host_identity as the same Fleet host_id, its installed signer as the
        # host-key incarnation, and its root version as the enrolment UUID.
        # Compare exact strings; neither Foundation nor Effects translates a
        # host grammar. This follows F2's first-after-lock admission and still
        # precedes every annotation or mutation for deploy and rollback.
        trace = self._host_source_admission_trace
        if not isinstance(trace, HostSourceAdmissionTrace):
            raise PreconditionFailed("F2 supplied no typed installed-host trace")
        for name, admitted, planned, current in (
            (
                "host_id",
                trace.host_identity,
                self._execution_plan.host_id,
                facts.host_id,
            ),
            (
                "host_incarnation",
                trace.installed_signer_fingerprint,
                self._execution_plan.host_incarnation,
                facts.host_incarnation,
            ),
            (
                "host_enrolment_ref",
                trace.installed_trust_root_version,
                self._execution_plan.host_enrolment_ref,
                facts.host_enrolment_ref,
            ),
        ):
            if admitted != planned or admitted != current:
                raise PreconditionFailed(
                    f"F2 admitted {name} disagrees with the V3 execution subject"
                )
        if facts.operation != operation or facts.target_ref != self._grant.target:
            raise PreconditionFailed("execution subject moved after authorization")
        if (
            facts.execution_sequence != self._grant.execution_sequence
            or facts.attempt_no != self._grant.attempt_no
        ):
            raise PreconditionFailed(
                "Control dispatch coordinate moved after authorization"
            )
        self._grant.receipt._require_live(now=self._grant.v3_provider.now())
        digest = require_execution_plan_v3_digest(
            self._execution_plan, authorized=authorized
        )
        # The startup-fixed CP provider owns current-standing validation and
        # atomic dispatch consumption in its external transaction. It refuses
        # before COMMIT or returns normally after it. Every Foundation check
        # has already run; no fallible check follows before the first effect.
        consumption_ref = require_committed_consumption_v3(
            grant=self._grant,
            plan=self._execution_plan,
            facts=facts,
            trace=trace,
        )
        return digest, consumption_ref

    def _bootstrap_principals(self, outcome: DeploymentOutcome) -> None:
        """Install the credentials this plan was authorized to install.

        BEFORE the step loop, and the ordering is the act's rather than a
        preference: a migration may need the role to exist and be able to
        authenticate, so a bootstrap after `migrate` would be a bootstrap for
        the run after this one. It adds a credential and destroys nothing, so it
        does not sit behind the backup gate.

        NOT a member of `plan.steps`, and that is a constraint rather than a
        shortcut. A step emitted by `build_plan` lands in
        `FoundationExecutionPlanV1.steps`, which is inside the V1 digest — so
        adding one would move every existing V1 digest, including ones Control
        has already frozen, for deployments that perform no bootstrap at all.
        The act is driven from `principal_bootstraps` on the authorized V2 plan,
        which is itself inside the digest, and the ordering above is a constant
        of this facility version. That is the same argument
        `RecoveryExecutionPlanV1` makes for not listing `RESTORE_PROCEDURE`'s
        ten steps in a document.

        A V1 plan carries no bootstraps, so this is a no-op and no record is
        written — a step that always appears and usually does nothing is noise
        in every deployment that never asked for one.
        """
        for bootstrap in self._bootstraps:
            started = self._clock()
            # Claimed BEFORE the call, like every other mutating step: an
            # install that failed partway has still touched the store.
            outcome.mutated = True
            try:
                standing = self._effects.bootstrap_principal_credential(bootstrap)
                if standing not in (
                    StepStanding.INSTALLED,
                    StepStanding.RECONCILED_AFTER_COMMIT,
                ):
                    # Raised INSIDE the try so it is recorded by the same handler
                    # as a provider failure. An earlier version raised after it,
                    # which left `failed_step` and the run standing unset — the
                    # run failed and the record could not say where. A refusal
                    # the evidence cannot locate is barely a refusal.
                    raise StepFailed(
                        StepKind.BOOTSTRAP_PRINCIPALS.value,
                        f"the provider reported {standing!r} for principal "
                        f"{bootstrap.principal!r}. A bootstrap must report "
                        f"{StepStanding.INSTALLED.value!r} or "
                        f"{StepStanding.RECONCILED_AFTER_COMMIT.value!r}: same "
                        "end state, different histories, and the crash path is "
                        "exactly when someone needs to tell them apart",
                    )
            except DeploymentError as exc:
                refused = isinstance(exc, PreconditionFailed)
                outcome.records.append(
                    StepRecord(
                        StepKind.BOOTSTRAP_PRINCIPALS,
                        bootstrap.principal,
                        False,
                        str(exc),
                        self._clock() - started,
                        StepStanding.REFUSED if refused else StepStanding.FAILED,
                    )
                )
                outcome.failed_step = StepKind.BOOTSTRAP_PRINCIPALS
                outcome.failure = str(exc)
                outcome.succeeded = False
                outcome.standing = (
                    RunStanding.REFUSED if refused else RunStanding.FAILED
                )
                raise
            outcome.records.append(
                StepRecord(
                    StepKind.BOOTSTRAP_PRINCIPALS,
                    bootstrap.principal,
                    True,
                    f"credential {standing.value} for {bootstrap.principal}",
                    self._clock() - started,
                    standing,
                )
            )

    def _reconcile_exposure(self, outcome: DeploymentOutcome) -> None:
        """Apply the exposure this plan was authorized to apply, or put it back.

        ## Why this is here and not in `exposure.py`

        Because it is an ORDER of effects against a host, and this facility has
        exactly one of those. `ExposureTransaction` used to own this sequence —
        take a lock, snapshot, apply, re-observe, verify, compensate — which
        made it a second executor: no `ExecutionGrant` reached it, no frozen
        plan bound it, no receipt named it, and the CLI subcommand that drove
        it had no `--authorization` flag to offer. Every guarantee the rest of
        this package spends a thousand lines establishing simply did not apply
        on that path.

        It also took its OWN lock, which is worse than it sounds. `flock` is
        per open file description, so a caller already holding the product's
        deployment lock could not call it at all — the inner acquisition
        refuses with `EAGAIN` against its own process. Exposure and deployment
        were not merely ungoverned together; they were structurally unable to
        be sequenced. That is why boundary 1 and boundary 3 are one change.

        ## What it does NOT do

        It does not recreate containers. `_do_switch` already does that, and
        the old transaction's `apply_compose` was a SECOND mutation on top of
        the first irreversible one. Here the compose half belongs to the step
        that owns it and this reconciles the firewall half only, which is the
        half nothing else in the executor performs. `verify_exposure` then
        checks BOTH against the descriptor, so the division of labour is not a
        division of verification.

        ## Compensation, and its limit

        On any refusal this restores the snapshot's chains and re-measures. The
        limit is stated rather than hidden: `restore_chains` is the provider's
        promise, and `require_preserved_foreign_rules` is how that promise is
        MEASURED rather than believed — in both directions, apply and restore,
        because a compensation that eats a bystander's rule is the same bug as
        an apply that does.
        """
        if not self._exposure:
            return
        effects = self._exposure_effects
        if effects is None:
            raise PreconditionFailed(
                "this plan authorizes exposure reconciliation for "
                f"{[item.family for item in self._exposure]} and no exposure "
                "provider is installed. The authorization is real and the "
                "capability is absent, which is a deployment environment that "
                "was built wrong — not a step to skip. Declare one through the "
                "assembly's execution bindings"
            )
        owner = ownership_comment(self._spec.product)
        managed = managed_ports(self._spec)
        started = self._clock()
        # Read BEFORE the flag: observing mutates nothing, and a snapshot is
        # what a rollback restores TO. A full observation rather than a diff,
        # because a compensation that restores only what it thinks it changed
        # cannot repair what it did not notice changing.
        snapshot = effects.observe()
        # Claimed BEFORE the first write, like every other mutating act here: a
        # reconciliation that failed partway has already touched a shared chain.
        outcome.mutated = True
        try:
            for item in self._exposure:
                rules = tuple(
                    rule
                    for rule in build_firewall_plan(self._spec)
                    if rule.family == item.family
                )
                effects.replace_rules(item.family, item.chain, rules)
            observed = effects.observe()
            require_preserved_foreign_rules(
                snapshot, observed, owner=owner, managed=managed, phase="apply"
            )
            report = verify_exposure(self._spec, observed)
            if not report.ok:
                raise PreconditionFailed(
                    "the applied exposure did not verify: "
                    + "; ".join(finding.detail for finding in report.refusals)
                )
        except DeploymentError as exc:
            compensated = self._restore_exposure(snapshot, outcome, owner, managed)
            refused = isinstance(exc, PreconditionFailed)
            # BOTH facts, in one sentence, and neither one displacing the other.
            #
            # The original diagnosis is what the operator came for: a
            # compensation that raises its own error instead sends them looking
            # for the wrong cause. But a compensation that DELETED a bystander's
            # firewall rule is a data-loss event, and burying that in a step
            # record while the exception talks about a port binding would rank
            # the two exactly backwards. So the raised message leads with what
            # went wrong and ends with what putting it back did.
            detail = f"{exc} ({compensated})"
            outcome.records.append(
                StepRecord(
                    StepKind.APPLY_EXPOSURE,
                    self._spec.product,
                    False,
                    detail,
                    self._clock() - started,
                    StepStanding.REFUSED if refused else StepStanding.FAILED,
                )
            )
            outcome.failed_step = StepKind.APPLY_EXPOSURE
            outcome.failure = detail
            outcome.succeeded = False
            outcome.standing = RunStanding.REFUSED if refused else RunStanding.FAILED
            raise type(exc)(detail) from exc
        outcome.records.append(
            StepRecord(
                StepKind.APPLY_EXPOSURE,
                self._spec.product,
                True,
                f"reconciled {[item.family for item in self._exposure]} against "
                f"descriptor {report.descriptor_digest}",
                self._clock() - started,
                StepStanding.OK,
            )
        )

    def _restore_exposure(
        self,
        snapshot: HostObservation,
        outcome: DeploymentOutcome,
        owner: str,
        managed: Sequence[int],
    ) -> str:
        """Put back this product's rules, and MEASURE that nothing else moved.

        Returns a sentence for the failing record rather than raising, because
        the caller is already carrying a failure and a compensation that
        replaces the original diagnosis with its own has lost the thing the
        operator needed. A compensation that itself failed is recorded as its
        own step, so both facts survive.
        """
        effects = self._exposure_effects
        if effects is None:  # pragma: no cover - guarded by the caller
            return "no provider to compensate with"
        started = self._clock()
        try:
            effects.restore_chains(snapshot.chains)
            require_preserved_foreign_rules(
                snapshot,
                effects.observe(),
                owner=owner,
                managed=managed,
                phase="restore",
            )
        except DeploymentError as exc:
            outcome.records.append(
                StepRecord(
                    StepKind.RESTORE_EXPOSURE,
                    self._spec.product,
                    False,
                    str(exc),
                    self._clock() - started,
                    StepStanding.FAILED,
                )
            )
            return f"NOT rolled back: {exc}"
        outcome.records.append(
            StepRecord(
                StepKind.RESTORE_EXPOSURE,
                self._spec.product,
                True,
                "this product's rules restored; no foreign rule moved",
                self._clock() - started,
                StepStanding.OK,
            )
        )
        return "rolled back"

    def _run_steps(
        self,
        steps: Sequence[Step],
        plan: DeploymentPlan,
        outcome: DeploymentOutcome,
    ) -> None:
        for step in steps:
            started = self._clock()
            if step.mutates:
                # Claimed BEFORE the call, not after it. A step that fails
                # PARTWAY — a migration that applied three revisions of five, a
                # switch that recreated half the roles — has mutated the world,
                # and setting the flag only on success reported `mutated=False`
                # for precisely the failures where the answer decides whether an
                # operator may re-run the identical command.
                outcome.mutated = True
            try:
                detail = self._dispatch(step, plan, outcome)
            except DeploymentError as exc:
                # REFUSED and FAILED are different facts and the exception type
                # already knows which: `PreconditionFailed` is a gate refusing
                # before anything was mutated — the caller may fix the stated
                # cause and re-run the identical command — while `StepFailed`
                # means a step ran and state may have changed. Collapsing them
                # into "not ok" throws away the one distinction an operator
                # needs before deciding whether to re-run.
                refused = isinstance(exc, PreconditionFailed)
                outcome.records.append(
                    StepRecord(
                        step.kind,
                        step.target,
                        False,
                        str(exc),
                        self._clock() - started,
                        StepStanding.REFUSED if refused else StepStanding.FAILED,
                    )
                )
                outcome.failed_step = step.kind
                outcome.failure = str(exc)
                outcome.succeeded = False
                outcome.standing = (
                    RunStanding.REFUSED if refused else RunStanding.FAILED
                )
                raise
            outcome.records.append(
                StepRecord(
                    step.kind,
                    step.target,
                    True,
                    detail,
                    self._clock() - started,
                    self._non_fatal.pop(step.kind, StepStanding.OK),
                )
            )

    def _annotate(self, event: str, plan: DeploymentPlan, *, detail: str = "") -> None:
        """Send one deployment annotation, and never let it fail a deployment.

        A telemetry sink being unreachable is not a reason to refuse to deploy —
        ADR-0003 says failure or disabling of telemetry never blocks the
        product's request path, and the same reasoning applies to the deployment
        path. The failure is recorded as a note so it is visible without being
        fatal.
        """
        annotation = Annotation(
            event=event,
            product=self._spec.product,
            environment=self._spec.environment or "unknown",
            deployment_id=self._deployment_id,
            image_digest=plan.image_digest,
            git_sha=plan.source_revision,
            strategy=plan.strategy.value,
            detail=detail,
        )
        try:
            self._effects.emit_annotation(annotation.as_mapping())
        except Exception as exc:
            self._notes_sink.append(f"annotation {event!r} could not be sent: {exc}")

    def _persist_evidence(self, outcome: DeploymentOutcome) -> None:
        """Write the evidence artefact, and never let that failure mask another.

        A write failure here is recorded as a note rather than raised: losing the
        record of a deployment is bad, and replacing the reason it failed with
        "could not write the evidence file" is worse.
        """
        try:
            outcome.evidence_path = self._effects.write_evidence(outcome.as_evidence())
        except Exception as exc:
            outcome.notes.append(f"evidence could not be written: {exc}")

    def rollback(
        self, plan: DeploymentPlan, *, lock: DeploymentLockHeld
    ) -> DeploymentOutcome:
        """Execute the rollback, or refuse it.

        `steps_for_rollback` returns the steps and nothing ran them, so
        `dotmac-deploy rollback` could only ever PRINT a plan. Here the steps
        actually execute, and `_rolling_back` makes `switch` target the previous
        digest rather than the deploying one — which the shared handler would
        otherwise have done, restoring the image that had just failed.

        ``lock`` is required here for the same reason it is required by
        :meth:`run`, and the rollback half is if anything the sharper one: a
        rollback races the deployment it is undoing, and the two must not
        interleave. Boundary 3 names failure and rollback handling explicitly
        because that is the half a "wrap the happy path" reading omits.
        """
        self._lock_path = lock.require_held(product=self._spec.product)
        # Same gate, same position, same reason as `run`: rollback mutates a
        # host exactly like a deploy does, and the ruling names it explicitly
        # so this is not left to a "wrap the happy path" reading.
        self._verify_host_source()
        self._grant.require(
            operation="rollback", descriptor_digest=self._descriptor_digest()
        )
        steps = steps_for_rollback(plan)
        outcome = DeploymentOutcome(
            plan=plan,
            notes=list(plan.notes),
            descriptor_digest=self._descriptor_digest(),
            control_plan_digest=str(self._grant.receipt.control_plan_digest),
            execution_sequence=int(self._grant.execution_sequence),
            attempt_no=int(self._grant.attempt_no),
            operation="rollback",
        )
        if not steps:
            outcome.failure = plan.rollback_reason
            outcome.notes.append(f"ROLLBACK REFUSED — {plan.rollback_reason}")
            self._persist_evidence(outcome)
            raise PreconditionFailed(f"rollback refused: {plan.rollback_reason}")
        digest, consumption_ref = self._require_execution_plan("rollback")
        outcome.execution_plan_digest = digest
        outcome.control_consumption_ref = consumption_ref
        self._rolling_back = True
        # `plan.rollback_reason` is descriptor-derived prose, not an exception
        # — but it is still free text crossing the same seam, and the type now
        # refuses it. The event name already says a rollback started.
        self._annotate("deployment.rollback", plan)
        try:
            self._run_steps(steps, plan, outcome)
            outcome.succeeded = True
            outcome.standing = RunStanding.SUCCEEDED
        except DeploymentError:
            pass
        finally:
            self._rolling_back = False
            outcome.notes.extend(self._notes_sink)
            self._notes_sink.clear()
            self._persist_evidence(outcome)
        return outcome

    # ── dispatch ────────────────────────────────────────────────────────────

    def _dispatch(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        handler = getattr(self, f"_do_{step.kind.value}", None)
        if handler is None:
            # Not a silent skip. A step in the plan with no handler is a bug in
            # this file, and a deployment that quietly omits a gate is the worst
            # possible way to find out.
            raise StepFailed(step.kind.value, "no handler is implemented for this step")
        result: str = handler(step, plan, outcome)
        return result

    # ── gates: nothing below mutates ────────────────────────────────────────

    def _do_acquire_lock(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        # The lock is held by the CALLER around the whole run (`lock.py`), not
        # here: a lock taken inside the executor would be released the moment
        # this method returns, which is the beginning of the deployment rather
        # than the end of it.
        #
        # This step no longer ASSERTS that. `run`/`rollback` refuse without a
        # live `DeploymentLockHeld` before reaching any step, so by the time
        # this executes the hold is established and this reports the actual
        # inode rather than restating a convention. A step that narrated a
        # property nobody checked is how the property came to be unchecked.
        if not self._lock_path:  # pragma: no cover - run()/rollback() set it
            raise PreconditionFailed(
                "no deployment lock is recorded for this run. Reaching this "
                "step without one means an entry point mutated a host without "
                "passing through the lock requirement"
            )
        return f"held by the caller at {self._lock_path} for the whole run"

    def _do_verify_image(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        if not self._effects.image_present(plan.image):
            raise PreconditionFailed(
                f"the exact image {plan.image} is not present. Nothing is built "
                "here: build once, promote the digest. A missing digest means "
                "the release was never published or the reference is wrong"
            )
        return f"digest {plan.image_digest} present"

    def _do_verify_revision(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        labels = self._effects.image_labels(plan.image)
        recorded = labels.get("org.opencontainers.image.revision", "")
        if not recorded:
            raise PreconditionFailed(
                f"{plan.image} carries no org.opencontainers.image.revision "
                "label, so nothing connects the running bytes to a reviewable "
                "commit"
            )
        if recorded != plan.source_revision:
            raise PreconditionFailed(
                f"{plan.image} was built from {recorded}, but the descriptor "
                f"declares {plan.source_revision}. One of the two is stale, and "
                "guessing which would deploy an unreviewed tree"
            )
        return f"built from {recorded}"

    def _do_verify_manifest(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        observed = self._effects.manifest_digest(step.target)
        if not observed:
            raise PreconditionFailed(
                f"the product manifest {step.target!r} could not be read, so "
                "nothing establishes which module set this deployment runs. The "
                "image digest cannot see it: the same image composes whatever "
                "manifest it is given"
            )
        if observed != plan.manifest_digest:
            raise PreconditionFailed(
                f"the product manifest hashes to {observed}, the descriptor "
                f"declares {plan.manifest_digest}. Either the manifest was "
                "regenerated without updating the descriptor, or this "
                "deployment is about to run an approved image against a module "
                "set nobody approved"
            )
        return f"manifest {observed}"

    def _do_verify_release_evidence(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        """Evidence must be signed, current, and from a protected ref HERE.

        The previous version of this step checked that the evidence mapping was
        non-empty. That made "CI is the acceptance owner" satisfiable by any
        writable file: nothing established who wrote it, whether the run it
        describes happened, or whether it happened in this repository.
        """
        raw = self._effects.release_evidence(plan.source_revision)
        if raw is None:
            raise PreconditionFailed(
                f"no release evidence exists for revision {plan.source_revision}. "
                "CI is the acceptance owner; a deployment of a revision CI never "
                "accepted is a deployment of an unreviewed tree"
            )
        if not isinstance(raw, SignedEvidenceEnvelope):
            raise PreconditionFailed(
                "the Effects implementation returned release evidence as "
                f"{type(raw).__name__}, not as a SignedEvidenceEnvelope. The "
                "typed envelope is the contract that keeps the signed document "
                "un-restated between the file and the verifier; a loose "
                "mapping here is exactly the seam that stringified a4's "
                "envelopes"
            )
        if self._evidence_policy is None:
            raise PreconditionFailed(
                "release evidence was found but no TrustPolicy is configured, "
                "so there is nothing to judge it against. Refusing rather than "
                "falling back to 'a file exists': that fallback is what let an "
                "unsigned, unattributed file stand for CI acceptance"
            )
        evidence = accept_release_evidence(
            raw,
            revision=plan.source_revision,
            policy=self._evidence_policy,
            verifier=self._evidence_verifier,
        )
        return (
            f"run {evidence.run_id} of {evidence.workflow} on {evidence.ref} "
            f"({evidence.repository}), signed and not from a fork"
        )

    def _do_refuse_dirty_state(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        problems: list[str] = []
        if self._effects.working_tree_dirty():
            problems.append(
                "the deployment checkout has uncommitted changes, so what runs "
                "is not what any commit describes"
            )
        overrides = list(self._effects.untracked_compose_overrides())
        if overrides:
            problems.append(
                f"untracked compose override(s) {overrides} carry configuration "
                "nothing tracks. A host-only override is an undocumented manual "
                "step, and the first re-render reverts it"
            )
        mounted = [
            observation.code
            for observation in self._effects.observe_roles()
            if observation.source_mounted
        ]
        if mounted:
            problems.append(
                f"role(s) {mounted} bind-mount source into the container, so the "
                "running behaviour is the host checkout rather than the image "
                "digest that was reviewed"
            )
        if problems:
            raise PreconditionFailed("; ".join(problems))
        return "clean checkout, no untracked override, no source mount"

    def _do_verify_materials(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        resolved = set(self._effects.resolved_materials())
        required = set(self._spec.runtime_materials) | {
            self._spec.migration.owner_material
        }
        missing = sorted(required - resolved)
        if missing:
            raise PreconditionFailed(
                f"material(s) {missing} do not resolve. A container started with "
                "an empty credential fails later, further from the cause, and "
                "sometimes only under load"
            )
        # The second half is a static property of the descriptor and `spec.py`
        # already refuses it at parse time. It is re-checked here because the
        # descriptor on the host may not be the descriptor that was reviewed,
        # and this is the last moment before DDL at which that is cheap to see.
        for role in self._spec.roles:
            if self._spec.migration.owner_material in role.materials:
                raise PreconditionFailed(
                    f"role {role.code!r} holds the migration owner material "
                    f"{self._spec.migration.owner_material!r}"
                )
        return (
            f"{len(required)} material(s) resolve; "
            "owner material absent from every role"
        )

    def _do_verify_external_recovery_receipt(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        """Somebody else restored it. Prove it, bind it, and enforce the window.

        Three things had to be true before this step could exist and each was
        missing. The descriptor could not name the privilege verifications, so a
        receipt could only ever claim `schema` and `row_counts`. Nothing turned
        an external proof into a `BackupRecord`, so `restore_proved_at_epoch` was
        written by nothing in the package. And `backup.assess()` -- which
        computes the `restore_proof_max_age_days` window correctly -- had zero
        callers, so the window was inert. This is the caller.
        """
        dataset = next(
            (item for item in self._spec.backup_datasets if item.code == step.target),
            None,
        )
        if dataset is None or dataset.external_executor is None:
            raise StepFailed(
                step.kind.value,
                f"the plan asks for an external recovery receipt for "
                f"{step.target!r} and the descriptor declares no external "
                "executor for it. A plan and a descriptor that disagree about "
                "who performs recovery must not be resolved by guessing",
            )
        envelope = self._recovery_receipts.get(step.target)
        if envelope is None:
            raise PreconditionFailed(
                f"no recovery receipt was supplied for {step.target!r}. It is "
                "passed in, never discovered: this facility does not go looking, "
                "because a search cannot tell 'no proof exists' from 'no proof "
                "was offered' and will happily find last quarter's"
            )
        receipt = accept_external_recovery_receipt(
            envelope,
            identity=dataset.identity(self._spec.product),
            descriptor_digest=str(self._spec.to_canonical_document().sha256_digest()),
            executor=dataset.external_executor,
            required_verifications=dataset.verify,
            verifier=self._recovery_verifier,
        )
        records = [
            *self._recovery_records.get(step.target, ()),
            backup_record_from_receipt(
                receipt,
                path=f"{EXTERNAL_BACKUP_PATH_PREFIX}{receipt.executor.identifier}",
                size_bytes=max(1, receipt.restore_duration_seconds),
            ),
        ]
        detail = require_restore_proof(
            self._spec,
            step.target,
            records,
            now_epoch=self._now_epoch or receipt.proved_at_epoch,
        )
        outcome.notes.append(
            f"recovery receipt {receipt.sha256_digest()} for {step.target}: {detail}"
        )
        return (
            f"{receipt.executor.kind}:{receipt.executor.identifier}"
            f"@{receipt.executor.version} proved {list(receipt.verifications)} "
            f"on snapshot {receipt.snapshot_checksum_algorithm}="
            f"{receipt.snapshot_checksum}; {detail}"
        )

    def _do_product_preflight(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        return self._run_hook(step, "preflight")

    # ── mutation ────────────────────────────────────────────────────────────

    def _do_backup(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        result = self._effects.backup(step.target, timeout_seconds=step.timeout_seconds)
        if not result.checksum:
            raise StepFailed(
                step.kind.value,
                f"backup {step.target!r} returned no checksum. The checksum is "
                "recorded at WRITE time on purpose: computed later it proves only "
                "that the file has not changed since the verifier read it",
            )
        if result.size_bytes <= 0:
            raise StepFailed(
                step.kind.value,
                f"backup {step.target!r} reported {result.size_bytes} bytes",
            )
        self._backups[step.target] = result
        outcome.notes.append(
            f"backup {step.target}: {result.path} "
            f"({result.size_bytes} bytes, "
            f"{result.checksum_algorithm}={result.checksum})"
        )
        return f"{result.path} ({result.size_bytes} bytes)"

    def _do_verify_backup(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        result = self._backups.get(step.target)
        if result is None:
            raise StepFailed(
                step.kind.value,
                f"no backup was recorded for {step.target!r}, so there is nothing "
                "to verify. Verification of a backup that did not run must fail, "
                "not pass vacuously",
            )
        # The REAL result, carried as a value. An earlier version re-parsed it
        # out of a formatted note and rebuilt it with `size_bytes=0` and an
        # empty checksum — so the verifier was handed the two fields it exists
        # to check, blanked, and could only ever confirm the path.
        if not self._effects.verify_backup(result):
            raise StepFailed(
                step.kind.value,
                f"backup {step.target!r} did not verify. A clean exit is "
                "COMPLETION, not integrity: it cannot see corruption during the "
                "write, during transfer, or on disk since. Verification is a "
                "full decompression plus the checksum recorded at write time",
            )
        return f"{step.target} verified"

    def _do_migration_preflight(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        if not step.command:
            return "no preflight command is declared"
        # IN THE CANDIDATE IMAGE. This was `run_command` — the bare host
        # shell — so the preflight proved the HOST's alembic and the host's
        # code could talk to the database, about a release whose code it was
        # not running. The image is the plan's: the one the grant authorized.
        result = self._effects.run_migration_command(
            step.command,
            timeout_seconds=step.timeout_seconds,
            materials=[self._spec.migration.owner_material],
            image=plan.image,
        )
        if not result.ok:
            raise StepFailed(
                step.kind.value,
                "the migration identity, role posture or database ownership "
                f"contract is unsatisfied (exit {result.exit_code}): "
                f"{result.stderr.strip() or result.stdout.strip()}",
                exit_code=result.exit_code,
            )
        return "migration role verified"

    def _do_support_job(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        topology = self._spec.compose_topology
        if topology is None:
            raise StepFailed(step.kind.value, "support job has no v3 topology")
        job = next((item for item in topology.jobs if item.code == step.target), None)
        if job is None or not job.run_during_deploy:
            raise StepFailed(step.kind.value, "support job is not deploy-authorized")
        result = self._effects.run_support_job(
            job.code, timeout_seconds=step.timeout_seconds, image=plan.image
        )
        if not result.ok:
            raise StepFailed(
                step.kind.value,
                f"support job {job.code!r} or its postcondition failed; "
                "command output withheld",
                exit_code=result.exit_code,
            )
        return f"{job.code} postcondition verified"

    def _do_stop_for_maintenance(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        roles = list(self._spec.role_codes)
        self._effects.stop_roles(roles, timeout_seconds=step.timeout_seconds)
        return f"stopped {len(roles)} role(s) before DDL"

    def _do_migrate(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        last = ""
        for attempt in range(1, step.retries + 1):
            # IN THE CANDIDATE IMAGE — the migration is the candidate's code
            # changing the schema to what the candidate expects. Run by the
            # previous release's code (or the host's PATH), it is the drift
            # `require_prerequisites` exists to catch, reintroduced here.
            result = self._effects.run_migration_command(
                step.command,
                timeout_seconds=step.timeout_seconds,
                materials=[self._spec.migration.owner_material],
                image=plan.image,
            )
            if result.ok:
                return f"migrated on attempt {attempt}"
            last = (result.stderr or result.stdout).strip()
            if not _is_lock_contention(last):
                # Narrow on purpose, ported from `deploy.sh:378-400`. A blanket
                # retry runs a genuinely failing migration `retries` times, and
                # a migration that fails halfway and is retried is the shape
                # that leaves a schema nobody can describe.
                raise StepFailed(
                    step.kind.value,
                    f"migration failed and the failure is not lock contention, "
                    f"so retrying would re-run a failing migration: {last}",
                    exit_code=result.exit_code,
                )
            if attempt < step.retries:
                self._sleep(min(10 * attempt, 60))
        raise StepFailed(
            step.kind.value,
            f"migration lock contention persisted across {step.retries} attempts: "
            f"{last}",
        )

    def _do_verify_heads(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        # The heads READ also runs in the candidate image: the previous
        # image's alembic may not even know the new lineage's branch labels.
        observed = set(self._effects.migration_heads(image=plan.image))
        expected = set(self._spec.migration.expected_heads)
        if observed != expected:
            raise StepFailed(
                step.kind.value,
                f"migration heads are {sorted(observed)}, the descriptor expects "
                f"{sorted(expected)}. `upgrade heads` is plural because a "
                "composition has several lineages, and a lineage that silently "
                "did not advance is invisible to an exit code of 0",
            )
        return f"heads {sorted(observed)}"

    def _do_start_candidate(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        # The image is INJECTED into the start, not hoped for: before this,
        # the candidate started from the on-disk compose file — which still
        # pins the PREVIOUS image until `switch` re-renders it — and only a
        # post-hoc digest comparison stood between that and gating traffic
        # onto the old release. The comparison stays, as a canary.
        digest = self._effects.start_candidate(
            step.target, timeout_seconds=step.timeout_seconds, image=plan.image
        )
        if digest and digest != plan.image_digest:
            raise StepFailed(
                step.kind.value,
                f"the {step.target!r} candidate started on digest {digest}, not "
                f"the deploying digest {plan.image_digest}",
            )
        return f"{step.target} candidate started"

    def _do_gate_candidate(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        role = self._spec.role(step.target)
        probe = role.ready
        if probe is None:
            raise StepFailed(
                step.kind.value,
                f"role {step.target!r} has no readiness probe, so the only "
                "available gate is a timer",
            )
        deadline = self._clock() + step.timeout_seconds
        attempts = 0
        while self._clock() < deadline:
            attempts += 1
            if self._effects.candidate_ready(step.target):
                return f"{step.target} ready after {attempts} probe(s)"
            self._sleep(probe.interval_seconds)
        raise StepFailed(
            step.kind.value,
            f"the {step.target!r} candidate never became ready within "
            f"{step.timeout_seconds}s across {attempts} probes. It is NOT handed "
            "traffic. Note that a budget too small for a host that starts every "
            "role at once produces this same message, and has caused a false "
            "rollback before — check the budget before assuming the image",
        )

    def _do_switch(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        target = plan.previous_image if self._rolling_back else plan.image
        self._effects.switch(timeout_seconds=step.timeout_seconds, image=target)
        if self._rolling_back:
            return f"every role restored to the previous digest {target}"
        return "traffic switched and every role recreated on the deploying digest"

    def _do_verify_roles(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        expected = (
            _digest_of(plan.previous_image) if self._rolling_back else plan.image_digest
        )
        if not step.target:
            # A whole-deployment verification, which is the shape the rollback
            # plan uses: there is no per-role step list to walk because every
            # role moved together.
            checked = [role.code for role in self._spec.roles if role.replicas > 0]
            for code in checked:
                self._verify_one_role(
                    code, expected, plan, step_timeout=step.timeout_seconds
                )
            return f"{len(checked)} role(s) verified on {expected}"
        self._verify_one_role(
            step.target, expected, plan, step_timeout=step.timeout_seconds
        )
        return f"{step.target} verified on {expected}"

    def _verify_one_role(
        self, code: str, expected: str, plan: DeploymentPlan, *, step_timeout: int = 60
    ) -> None:
        step_kind = StepKind.VERIFY_ROLES.value
        role = self._spec.role(code)
        if role.replicas == 0:
            return
        observations = {item.code: item for item in self._effects.observe_roles()}
        observation = observations.get(code)
        if observation is None or not observation.running:
            raise StepFailed(step_kind, f"role {code!r} is not running")
        if observation.image_digest != expected:
            raise StepFailed(
                step_kind,
                f"role {code!r} runs digest {observation.image_digest}, not "
                f"{expected}. One deployment, one digest, every role — a "
                "surviving container from a previous release is how a stale "
                "scheduler kept firing failing tasks for hours with every "
                "container-level check green",
            )
        if observation.restarts:
            raise StepFailed(
                step_kind,
                f"role {code!r} has restarted {observation.restarts} time(s). "
                "A running container that has restarted is a crash loop observed "
                "between crashes",
            )
        if observation.source_mounted:
            raise StepFailed(
                step_kind, f"role {code!r} bind-mounts source into the container"
            )
        if role.ready is not None and code in set(_plan_ingress_roles(self._spec)):
            # REAL readiness, every strategy. `GATE_CANDIDATE` polls the
            # candidate's probe before traffic — but only the warm-candidate
            # strategy ever creates that step, so a maintenance or recreate
            # deployment used to declare victory on docker-inspect facts plus
            # a sleep: running, right digest, zero restarts — and an app that
            # binds its port then hangs on a dead dependency passes all three.
            # The role's own declared probe is polled here, bounded by the
            # step's budget, for every strategy including warm-candidate
            # (whose candidate is gone by now; the REAL role must be ready
            # too).
            deadline = self._clock() + step_timeout
            attempts = 0
            while True:
                attempts += 1
                if self._effects.role_ready(code):
                    break
                if self._clock() >= deadline:
                    raise StepFailed(
                        step_kind,
                        f"role {code!r} is running the right digest and never "
                        f"answered its readiness probe within {step_timeout}s "
                        f"across {attempts} attempt(s). Running is not ready: "
                        "a process that bound its port and hangs on a dead "
                        "dependency looks exactly like this",
                    )
                self._sleep(role.ready.interval_seconds)
        if role.worker is not None and not self._effects.worker_responds(code):
            raise StepFailed(
                step_kind,
                f"worker role {code!r} does not answer its ping. A worker "
                "whose process is up and whose queue is not being drained is "
                "indistinguishable from a healthy one at the container level",
            )
        if role.scheduler_tick_max_age_seconds is not None:
            age = self._effects.scheduler_last_tick_age_seconds(code)
            if age is None:
                raise StepFailed(
                    step_kind, f"scheduler role {code!r} reports no tick at all"
                )
            if age > role.scheduler_tick_max_age_seconds:
                raise StepFailed(
                    step_kind,
                    f"scheduler role {code!r} last ticked {age}s ago, "
                    f"budget {role.scheduler_tick_max_age_seconds}s",
                )

    def _do_stabilise(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        window = self._spec.stability_window_seconds
        self._sleep(window)
        for observation in self._effects.observe_roles():
            if observation.code not in self._spec.role_codes:
                continue
            if self._spec.role(observation.code).replicas == 0:
                continue
            if not observation.running or observation.restarts:
                raise StepFailed(
                    step.kind.value,
                    f"role {observation.code!r} did not survive the {window}s "
                    f"stability window (running={observation.running}, "
                    f"restarts={observation.restarts})",
                )
        return f"stable for {window}s"

    def _do_product_postflight(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        return self._run_hook(step, "postflight")

    def _do_record_evidence(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        # An interim write, so the record exists before the last two steps run.
        # It is NOT the only write: `run()` persists in a `finally`, so a
        # deployment that dies at `migrate` still leaves evidence. This step
        # remains in the plan because a reader of the plan should see that
        # evidence is written, and because the interim copy captures the state
        # before pruning touches anything.
        #
        # MANDATORY here, best-effort in the `finally` — deliberately split.
        # On the SUCCESS path, evidence that failed to persist or does not
        # read back must fail the deployment before success is declared: an
        # unrecorded deployment is indistinguishable from an unauthorized one
        # a week later. On the FAILURE path (`_persist_evidence` from
        # `finally`), a write failure stays a note, because replacing the real
        # failure with "could not write the evidence file" is worse — that
        # rule has its own test and it is not weakened here.
        self._persist_evidence(outcome)
        if not outcome.evidence_path:
            raise StepFailed(
                step.kind.value,
                "the evidence artefact could not be written, and this is the "
                "success path: a deployment whose only account of itself "
                "failed to persist must not be declared successful. "
                f"{'; '.join(outcome.notes[-1:]) or ''}",
            )
        # `default=str` is GONE from both sides. It is a stringify-anything
        # escape hatch, and it defeats a closed document by turning an
        # unexpected object into text rather than refusing it — the exact
        # mechanism by which an exception instance becomes an exception message
        # inside a persisted record. With the closed type upstream there is
        # nothing left that legitimately needs it, so an unserialisable value
        # here is a defect and must raise.
        document = json.loads(json.dumps(outcome.as_evidence(), sort_keys=True))
        read_back = json.loads(
            json.dumps(
                dict(self._effects.read_evidence(outcome.evidence_path)),
                sort_keys=True,
            )
        )
        if read_back != document:
            raise StepFailed(
                step.kind.value,
                f"the evidence record at {outcome.evidence_path} does not read "
                "back as the outcome this run produced. A record that cannot "
                "be read back identical is a hope, not evidence",
            )
        return outcome.evidence_path

    def _do_prune_images(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        try:
            self._effects.prune_images(retain=self._spec.rollback_images_retained)
        except DeploymentError as exc:
            # The one deliberate fail-open, stated rather than silent. Retention
            # is housekeeping; failing a verified-healthy deployment over a disk
            # permission is worse than the debt it leaves behind.
            outcome.notes.append(f"image retention failed and was not fatal: {exc}")
            self._non_fatal[step.kind] = StepStanding.NON_FATAL
            return "retention failed (non-fatal, recorded)"
        return f"retained {self._spec.rollback_images_retained} rollback image(s)"

    def _do_release_lock(
        self, step: Step, plan: DeploymentPlan, outcome: DeploymentOutcome
    ) -> str:
        return "released by the caller when the run exits"

    # ── shared ──────────────────────────────────────────────────────────────

    def _run_hook(self, step: Step, phase: str) -> str:
        result = self._effects.run_command(
            step.command,
            timeout_seconds=step.timeout_seconds,
            materials=self._spec.runtime_materials,
        )
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            message = f"product {phase} hook {step.target!r} failed: {detail}"
            if phase == "preflight":
                raise PreconditionFailed(message)
            raise StepFailed(step.kind.value, message, exit_code=result.exit_code)
        return f"{step.target} ok"


_LOCK_MARKERS: tuple[str, ...] = (
    "lock timeout",
    "canceling statement due to lock",
    "could not obtain lock",
    "deadlock detected",
)


def _is_lock_contention(message: str) -> bool:
    """Whether a migration failure is worth retrying.

    Deliberately a closed list of markers rather than "does the word lock
    appear": a migration whose own SQL creates a table called `locks` would
    otherwise be retried four times on every real failure.
    """
    lowered = message.lower()
    return any(marker in lowered for marker in _LOCK_MARKERS)


def _digest_of(reference: str) -> str:
    """The `sha256:…` part of an image reference, or the reference itself.

    A recorded previous image may be stored either as a full reference or as a
    bare digest depending on what the host reported, and a rollback that
    compared the two forms directly would fail on a correct restoration.
    """
    return reference.rsplit("@", 1)[1] if "@" in reference else reference
