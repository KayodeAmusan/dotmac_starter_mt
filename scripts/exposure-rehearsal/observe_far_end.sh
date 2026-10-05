#!/usr/bin/env bash
# What the TARGET saw as this vantage's source address — read from the far end.
#
# `vantage.qualify_vantage` refuses when this value is empty OR when it
# disagrees with the address the vantage claims. It is the one check measured
# from the far end, and it replaces the discrimination control lost when the
# second NIC was removed: a vantage cannot certify where it egresses from, so
# only the target can say what it saw. Until 2026-09-04 this was the sentinel
# `__TARGET_OBSERVED_V4__`, which is non-empty, so qualification refused through
# the MISMATCH branch and the whole run died before recording a single item.
#
# ## Why ProxyJump and not a listener
#
# The obvious implementation is a listener on the target that prints its peer.
# It is the wrong one: **a listener is a mutation dressed as a read.** It needs a
# port, it collides with the descriptor's declared ports, and it changes the
# target's state in order to measure it.
#
# `-J <vantage>` makes the TCP connection to the target ORIGINATE from the
# vantage while the key stays on the control runner, and `$SSH_CONNECTION` on the
# target is the far end's own report of that connection. Nothing is bound,
# nothing is written, and the observation identity needs no privilege at all.
#
# ## Field ONE, never field four
#
# `SSH_CONNECTION` is `<client-ip> <client-port> <server-ip> <server-port>`.
# The shape measured 2026-09-04 against the rehearsal target, with the real
# addresses replaced by documentation ranges (RFC 5737 / RFC 3849). This is a
# public repository, and topology does not belong in its source; the measured
# IPv4 server field was an RFC 1918 address:
#
#   IPv4: 198.51.100.7 48292 192.0.2.54 22
#   IPv6: 2001:db8:1::1 36088 2001:db8:2::102 22
#
# The CLIENT field is comparable across families and is what this emits. The
# SERVER field is not: on IPv4 it is the target's PRIVATE address because dstnat
# rewrote the destination before it arrived, while on IPv6 it is the public
# address because IPv6 is routed rather than translated. A check written against
# field four would read the private address on v4 and look like a v6-only bug.
#
# ## Two identities, and this one may not change anything
#
# `OBS_USER` is the restricted observation identity: no sudo, no docker group,
# and it cannot read another user's material. The controller identity that
# applies the plan is a DIFFERENT account, deliberately, so a target-side read
# never carries the ability to change the target.
set -euo pipefail

VANTAGE="${1:?usage: observe_far_end.sh <vantage> <target> <obs-user> <obs-key> [jump-key]}"
TARGET="${2:?usage: observe_far_end.sh <vantage> <target> <obs-user> <obs-key> [jump-key]}"
OBS_USER="${3:?usage: observe_far_end.sh <vantage> <target> <obs-user> <obs-key> [jump-key]}"
OBS_KEY="${4:?usage: observe_far_end.sh <vantage> <target> <obs-user> <obs-key> [jump-key]}"
# Optional. The OUTSIDE vantage is reached with ordinary access, but the INSIDE
# one is a restricted jump whose key differs from the target-side observation
# key — so the hop and the destination need different identities and `-J` alone
# cannot express that.
JUMP_KEY="${5:-}"

# `IdentitiesOnly=yes` is not tidiness. Without it ssh offers every agent key,
# and a run that succeeded on an operator's forwarded credential would prove the
# restricted identity works when it had never been used.
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o IdentitiesOnly=yes
  -i "${OBS_KEY}"
)

# `[%h]:%p` MUST be quoted inside the ProxyCommand. Unquoted, zsh globs the
# brackets and the command dies with `no matches found`, which reads like a
# connectivity failure and is not one.
if [ -n "${JUMP_KEY}" ]; then
  HOP=(-o "ProxyCommand=ssh -o BatchMode=yes -o IdentitiesOnly=yes -i ${JUMP_KEY} -W '[%h]:%p' ${VANTAGE}")
else
  HOP=(-J "${VANTAGE}")
fi

peer() {
  local family="$1"
  # The hop makes the connection ORIGINATE at the vantage; the family flag
  # applies to the leg the TARGET sees.
  ssh "${family}" "${SSH_OPTS[@]}" "${HOP[@]}" "${OBS_USER}@${TARGET}" \
    'printf %s "${SSH_CONNECTION}"' 2>/dev/null | awk '{print $1}'
}

v4="$(peer -4 || true)"
v6="$(peer -6 || true)"

# Emitted even when empty, and empty is a REFUSAL rather than an omission:
# `qualify_vantage` treats an absent far-end value as unqualified. An omitted key
# would instead read as "not applicable", which is the one thing it must not.
printf '{"observed_source_v4": "%s", "observed_source_v6": "%s"}\n' \
  "${v4}" "${v6}"
