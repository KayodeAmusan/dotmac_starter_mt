# Lane 3 B5 scheduling evidence — 2026-10-06

Status: scheduling evidence recorded; full topology admission remains blocked.
`.github/lane3-execution.json` keeps `admission_evidence: null`.
This record does not authorize privileged attachment, provision credentials,
allocate Foundation 0.4.0a2, or certify a rehearsal receipt.

## Scope and verification

The execution repository is `dotmac-tech/lane3-exposure-execution`, repository
ID 1406738001 and owner ID 335992433. Launcher revision:
`67eb180022340eaea4a249cd49b06de5417b30c4`.

GitHub API read-backs verified the terminal job states below, P1's approval,
its runner assignment and individual step outcomes, and current empty group
membership. The private execution packet records contemporaneous 11–15 minute
queued/unassigned observations with the canary online and idle. Terminal API
state independently confirms no assignment; it does not reconstruct those
historical observations or prove the runner was idle throughout that interval.
No private topology values, credentials, or private evidence bundle are copied
into this public record.

## Negative probes

| Probe | Canonical run / job | Terminal API result |
| --- | --- | --- |
| N1 same-repository PR #2 | [run 37451022513](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451022513) / [job 112227350215](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451022513/job/112227350215) | cancelled; runner_id 0 |
| N2 fork PR #3 | [run 37451068062](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451068062) / [job 112227489146](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451068062/job/112227489146) | cancelled; runner_id 0 |
| N4 branch dispatch | [run 37450714534](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450714534) / [job 112226342145](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450714534/job/112226342145) | failed before assignment; packet attributes refusal to Environment branch policy |
| N4b branch without main guard/Environment | [run 37450971831](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450971831) / [job 112227184807](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450971831/job/112227184807) | cancelled; runner_id 0 |
| N4b repeat | [run 37451020042](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451020042) / [job 112227339105](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37451020042/job/112227339105) | cancelled; runner_id 0 |
| N5 different workflow | [run 37450637488](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450637488) / [job 112226076464](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450637488/job/112226076464) | cancelled; runner_id 0 |
| N5 repeat | [run 37450970003](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450970003) / [job 112227172334](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450970003/job/112227172334) | cancelled; runner_id 0 |
| N6 reusable call | [run 37450637888](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450637888) / [job 112226077783](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450637888/job/112226077783) | cancelled; runner_id 0 |
| N6 repeat | [run 37450970305](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450970305) / [job 112227173581](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37450970305/job/112227173581) | cancelled; runner_id 0 |

**N3 (`pull_request_target`) was not executed.** Its default-branch execution
semantics and the protected workflow's absence of a PR-target trigger are
structural observations, not a passed live negative. Starter topology § 7
explicitly requires PR-target probes; CP's runner-isolation contract also says
absence of that trigger is not a substitute for isolation. Complete the required
same-repository/fork PR-target evidence on an authorized disposable canary, or
obtain a checked-in contract amendment accepting a precisely defined substitute.
Topology § 12 now proposes a narrowly scoped structural substitution. It is
not adopted, and this scheduling record does not supply the full structural
evidence dossier or accept the substitution.

## Positive scheduling probe

[P1 run 37452430048](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37452430048),
[job 112231922192](https://github.com/dotmac-tech/lane3-exposure-execution/actions/runs/37452430048/job/112231922192):

- Event `workflow_dispatch`, attempt 1, admitted launcher SHA above, workflow
  `.github/workflows/lane3-exposure-rehearsal.yml`.
- Run title binds Starter `25f9157d9c2d72a31131c985db11c6c51242d021` and
  candidate label `0.4.0a2`; that label does not allocate a candidate.
- GitHub approval record: `michaelayoade`, state `approved`, Environment
  `lane3-rehearsal-protected`.
- Runner ID 9, `lane3-b5-canary-1791282685`, runner group ID 4.
- Dispatch grammar step succeeded. `Refuse until Lane 3 execution is admitted`
  failed as designed. Overall conclusion `failure` is expected for this
  refusal-only launcher; it proves scheduling, not authorized execution.

## Post-run controls and teardown

GitHub group read-back: group 4 `lane3-exposure-protected`, selected visibility,
`restricted_to_workflows: true`, selected coordinate
`dotmac-tech/lane3-exposure-execution/.github/workflows/lane3-exposure-rehearsal.yml@refs/heads/main`,
zero runners.

Read-only host checks independently verified: no canary VM, bridge, IPv4/IPv6
canary firewall table or management-key file; IPv4 forwarding is off and all
21 original VMs are running. Observe lists only its pre-existing WireGuard
interface and no canary-interface rule in the OpenBao chain. File absence does
not independently prove secure erasure, and the limited rule check does not
prove byte-for-byte restoration of all firewall rules.

Disposable fork deletion and removal of elevated GitHub OAuth scopes remain
separate cleanup items until verified.

## Remaining admission requirements

B5 scheduling and A2 transport evidence are programme substeps, not all of
Starter topology § 7. In addition to N3, the section requires role-bound OIDC
claims and live credential refusals, no-grant OpenBao audit evidence,
private-side disclosure/state cleanup checks, and oracle reachability with
intended and wrong credentials. These remain unproved by P1 and this record.

Only after the applicable contract evidence is complete and reviewed may a
follow-up set `admission_evidence` to an accepted evidence record. CP Q2/D19,
unseal custody remediation, Gate-0 and candidate allocation gates remain open.
