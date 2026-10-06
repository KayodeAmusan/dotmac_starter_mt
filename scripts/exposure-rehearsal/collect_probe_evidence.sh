#!/usr/bin/env bash
# Collect the external half of Lane 3, from a vantage that is enumerated first.
#
# Two rules this script exists to enforce mechanically, both learned expensively
# on 2026-08-29:
#
#   1. ENUMERATE THE VANTAGE BEFORE BELIEVING ITS REFUSALS. A host qualified as
#      "outside every allowlist" on the strength of refusals turned out to hold
#      a second NIC into a Dotmac private network. Refusals over one transport
#      were read as refusals over all. So the interface list, the routes and the
#      private-path probes are collected as DATA and handed to
#      `vantage.qualify_vantage`, which refuses rather than assuming.
#
#   2. NEVER PROBE A NEGATIVE AFTER TEARDOWN. A refusal against a port where
#      nothing is listening measures an absent service, not an enforced
#      exposure. Every negative here carries `service_running`, and the runner
#      refuses the item if it is false.
#
# The far-end source addresses are MEASURED as of 2026-09-04 and are no longer
# sentinels. `observe_far_end.sh` reads them from the target itself over a
# ProxyJump through this vantage — see that file for why a listener would have
# been a mutation dressed as a read, and why only field ONE of
# `SSH_CONNECTION` is comparable across families.
#
# TWO fields here are still NOT measurable from this vantage, and are emitted as
# fail-closed placeholders rather than omitted:
#
# The two fields this vantage could never measure — `private_inside` and
# `privileged_vantage_refused` — are gone from here as of 2026-09-04 rather than
# emitted as fail-closed literals. Both are now MEASURED, by
# `probe_inside_vantage.sh` through a vantage that genuinely sits inside the
# accepted source set. A literal that fails closed is honest and is still not a
# measurement; this host is outside the set by construction and no value it
# writes about the inside can be one.
#
# `nc` throughout, never bash /dev/tcp: that builtin is absent in this shell and
# reads EVERY port closed, which is a silent all-green — the worst possible
# failure mode for a security probe.
set -euo pipefail

# TWO PHASES, and the split is the whole point of item 13.
#
#   qualify  — BEFORE the controller applies anything. Enumerates the vantage
#              and reads the far end. Collected first so the vantage is
#              qualified against its own interfaces and routes rather than
#              trusted, and so nothing the controller does can contaminate it.
#   probe    — AFTER the apply and BEFORE teardown, which is the only moment a
#              negative means anything. A refusal against a port where nothing
#              is listening measures an absent service, not an enforced
#              exposure, and evidence collected before the stack was applied is
#              an accurate measurement of the wrong instant.
#
# The ordering guarantee the single-phase version had is preserved rather than
# traded away: qualification still happens before any mutation. What moved is
# only the half that has to happen while the service is up.
PHASE="${1:?usage: collect_probe_evidence.sh <qualify|probe> <probe-host> <target>}"
PROBE="${2:?usage: collect_probe_evidence.sh <qualify|probe> <probe-host> <target>}"
TARGET="${3:?usage: collect_probe_evidence.sh <qualify|probe> <probe-host> <target>}"
case "${PHASE}" in
  qualify|probe) ;;
  *) echo "REFUSED: unknown phase '${PHASE}'" >&2; exit 2 ;;
esac
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes)

# The private paths the retracted NIC used to reach. Probed explicitly, because
# an unprobed path is not an absent one. REQUIRED, with no default: the values
# are topology, they come from the private topology record
# (docs/LANE3_EXECUTION_TOPOLOGY.md § 4), and this public file names none. An
# unset value refuses, because probing nothing would read as "no former path".
: "${LANE3_FORMER_PRIVATE_PATHS:?unset: the former private paths to probe, from the private topology record}"
FORMER_PRIVATE="${LANE3_FORMER_PRIVATE_PATHS}"

on_probe() { ssh "${SSH_OPTS[@]}" "${PROBE}" "$@"; }

# The far end's own report of this vantage's source address, per family. Read
# BEFORE the remote block so a failure to obtain it surfaces here rather than as
# an empty field somebody has to trace. Every value is configured, never
# hardcoded: an unset identity is a refusal, because falling back to an agent
# key would prove a credential works that was never meant to be used.
: "${LANE3_OBSERVER_USER:?unset: the restricted target-side observation identity}"
: "${LANE3_OBSERVER_KEY:?unset: the private key for that identity}"
observed_v4=""; observed_v6=""; listening=""
if [ "${PHASE}" = qualify ]; then
  far_end="$(
    "$(dirname "$0")/observe_far_end.sh" \
      "${PROBE}" "${TARGET}" "${LANE3_OBSERVER_USER}" "${LANE3_OBSERVER_KEY}"
  )"
  extract() { printf '%s' "${far_end}" | sed -n "s/.*\"$1\": \"\\([^\"]*\\)\".*/\\1/p"; }
  observed_v4="$(extract observed_source_v4)"
  observed_v6="$(extract observed_source_v6)"
else
  # MEASURED, at the moment the probes are taken. Not a literal, and not a
  # value carried over from another phase: a service state observed once and
  # reused for probes taken at other times is the same defect as asserting it.
  listening="$(
    "$(dirname "$0")/observe_service_state.sh" \
      "${TARGET}" "${LANE3_OBSERVER_USER}" "${LANE3_OBSERVER_KEY}"
  )"
  test -n "${listening}" || {
    echo "REFUSED: could not read the target's listening ports, so no negative" \
         "probe in this phase can be distinguished from one taken against a" \
         "stopped service" >&2
    exit 1; }
fi

target_v6="$(on_probe "getent ahostsv6 ${TARGET} | awk 'NR==1{print \$1}'" || true)"
: "${target_v6:=}"

on_probe "
set -eu
TARGET='${TARGET}'; TARGET6='${target_v6}'; FORMER='${FORMER_PRIVATE}'
OBSERVED4='${observed_v4}'; OBSERVED6='${observed_v6}'
PHASE='${PHASE}'; LISTENING='${listening}'
# `service_running` for one port, MEASURED from the target's own socket
# table. Absent from the list is FALSE, never a default: the runner refuses
# an absent key too, so neither end can turn silence into a pass.
running() { case \" \$LISTENING \" in *\" \$1 \"*) printf true;; *) printf false;; esac; }

emit_bool() { if \"\$@\" >/dev/null 2>&1; then printf true; else printf false; fi; }
probe4() { nc -4 -z -w 5 \"\$1\" \"\$2\"; }
probe6() { [ -n \"\$TARGET6\" ] && nc -6 -z -w 5 \"\$1\" \"\$2\"; }

printf '{\n'

if [ \"\$PHASE\" = qualify ]; then
printf '  \"vantage\": {\n'
printf '    \"address_v4\": \"%s\",\n' \"\$(ip -4 -br addr show scope global | awk 'NR==1{split(\$3,a,\"/\"); print a[1]}')\"
printf '    \"address_v6\": \"%s\",\n' \"\$(ip -6 -br addr show scope global | awk 'NR==1{split(\$3,a,\"/\"); print a[1]}')\"
printf '    \"public_interface\": \"%s\",\n' \"\$(ip route show default | awk '{print \$5; exit}')\"

printf '    \"interfaces\": {'
first=1
ip -br addr show | while read -r name _state addrs; do
  [ \"\$name\" = lo ] && continue
  [ \"\$first\" = 1 ] || printf ','
  first=0
  printf '\"%s\": [' \"\$name\"
  sep=''
  for a in \$addrs; do printf '%s\"%s\"' \"\$sep\" \"\$a\"; sep=','; done
  printf ']'
done
printf '},\n'

printf '    \"link_kinds\": ['
sep=''
for k in \$(ip -d link show | grep -oE '(wireguard|tun|tap|gre|vti|ipip|sit|geneve|vxlan)' | sort -u); do
  printf '%s\"%s\"' \"\$sep\" \"\$k\"; sep=','
done
printf '],\n'

printf '    \"routes\": {\"ipv4\": \"%s\"' \"\$(ip route get \$TARGET 2>/dev/null | grep -oE 'dev [^ ]+' | awk '{print \$2; exit}')\"
if [ -n \"\$TARGET6\" ]; then
  printf ', \"ipv6\": \"%s\"' \"\$(ip -6 route get \$TARGET6 2>/dev/null | grep -oE 'dev [^ ]+' | awk '{print \$2; exit}')\"
fi
printf '},\n'

printf '    \"private_paths_unreachable\": {'
sep=''
for host in \$FORMER; do
  if nc -4 -z -w 3 \"\$host\" 22 >/dev/null 2>&1; then u=false; else u=true; fi
  printf '%s\"%s\": %s' \"\$sep\" \"\$host\" \"\$u\"; sep=','
done
printf '},\n'

printf '    \"credential_markers\": {\"openbao_dir\": %s, \"bao_env\": %s},\n' \\
  \"\$(if [ -d /opt/openbao ]; then printf true; else printf false; fi)\" \\
  \"\$(if env | grep -qE '^(BAO|VAULT)'; then printf true; else printf false; fi)\"

printf '    \"observed_source_v4\": \"%s\",\n' \"\$OBSERVED4\"
printf '    \"observed_source_v6\": \"%s\"\n' \"\$OBSERVED6\"
printf '  }\n'
printf '}\n'
exit 0
fi

printf '  \"probes\": {\n'
printf '    \"positive_v6\": {\"reachable\": %s, \"positive_control_fired\": true, \"service_running\": %s},\n' \\
  \"\$(emit_bool probe6 \"\$TARGET6\" 22)\" \"\$(running 22)\"
printf '    \"negative_v6\": {\"reachable\": %s, \"positive_control_fired\": %s, \"service_running\": %s},\n' \\
  \"\$(emit_bool probe6 \"\$TARGET6\" 18443)\" \"\$(emit_bool probe6 \"\$TARGET6\" 22)\" \"\$(running 18443)\"
printf '    \"v4_pair\": {\"reachable\": %s, \"positive_control_fired\": %s, \"service_running\": %s}\n' \\
  \"\$(emit_bool probe4 \"\$TARGET\" 18443)\" \"\$(emit_bool probe4 \"\$TARGET\" 22)\" \"\$(running 18443)\"
printf '  },\n'

printf '  \"closed_port_behaviour\": \"%s\"\n' \"\$(s=\$(date +%s%N); nc -4 -z -w 5 \$TARGET 18444 >/dev/null 2>&1 || true; e=\$(date +%s%N); if [ \$(( (e-s)/1000000 )) -lt 2000 ]; then printf reset; else printf drop; fi)\"
printf '}\n'
"
