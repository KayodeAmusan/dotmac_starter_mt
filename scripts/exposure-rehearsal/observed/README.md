# Observed bytes from the Lane 3 run, 2026-08-29

Real output from `[redacted 2026-10-05: shared rehearsal host IPv4]` while `scripts/exposure-rehearsal/product.toml`
was applied, kept as parser and verifier fixtures so the next change is tested
against measured bytes rather than invented ones.

**The address above is historical and is deliberately not updated.** These are
recorded bytes: they came from that host, on that date, and rewriting the
provenance line to name the current Role A
(`lane3-rehearsal-target`, `[redacted 2026-10-05: rehearsal target public IPv4]`) would make the file claim a
measurement nobody took. `[redacted 2026-10-05: shared rehearsal host IPv4]` is no longer an authorized rehearsal
target — see `docs/inventories/deployment-exposure-rehearsal.md` — and nothing
here should be read as authorizing it. When a run against the new target
produces bytes, they arrive as new fixtures beside these, not as an edit to
them.

Reproduce the verdict with no host present:

```
dotmac-deploy -f scripts/exposure-rehearsal/product.toml exposure-verify \
  --sockets scripts/exposure-rehearsal/observed/ss-tlnp.txt \
  --processes scripts/exposure-rehearsal/observed/docker-proxy.txt \
  --closed-port-behaviour reset
```

## What each file shows

`ss-tlnp.txt` — the three declared publications behaving exactly as declared:

| port | declared | observed |
|---|---|---|
| 18443 | `loopback` / `dual_stack` | `127.0.0.1` **and** `[::1]` |
| 18445 | `loopback` / `ipv4` | `127.0.0.1` only, no IPv6 |
| 18444 | `none` | **absent** |

No `0.0.0.0:` and no `[::]:` for any of them. 18445 is the control for 18443:
without a single-family publication in the same run, a host that simply had no
IPv6 would produce the same "no wildcard v6 socket" reading as a host where the
contract worked, and the run would pass for the wrong reason.

The two extra sockets — `127.0.0.1:55439` and `127.0.0.1:5434` — are **not**
part of the fixture's product. They belong to other work on the shared host,
and they are kept in the file deliberately: they are what makes
`undeclared_socket` fire, which is the other-direction sweep doing its job. A
verifier that only walks the descriptor cannot see the port the descriptor does
not mention, and that is the port that stays open.

`docker-proxy.txt` — one process per published family, with distinct PIDs. A
surviving PID would mean the container was never recreated and the apply proved
nothing.
