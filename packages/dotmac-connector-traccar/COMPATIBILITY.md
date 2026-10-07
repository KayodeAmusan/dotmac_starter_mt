# Compatibility — dotmac-connector-traccar

| Surface | Contract |
|---|---|
| Distribution | `dotmac-connector-traccar` |
| Connector key | `traccar` |
| Version | `0.1.0a1` (unreleased) |
| Integration floor | first published `dotmac-integration` release carrying SPI 1.6 |
| SPI | `>=1.6,<2.0` |
| Mode | `REQUEST` |
| Egress | exact host `traccar`; connector additionally fixes HTTP port 8082 |
| Provider | Traccar 6.15.3 API contract |

The declared dependency currently names `dotmac-integration >=0.1.0a18`, the
repository version allocated for the next integration release. Publication is
blocked until that exact version is published with SPI 1.6; otherwise the floor
must move to the first version that is.
