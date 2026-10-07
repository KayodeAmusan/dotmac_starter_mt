# dotmac-connector-traccar

Provider transport for bounded, read-only Fleet tracking requests through the
Dotmac Integrator. It implements the `REQUEST` SPI and is never installed in a
product runtime.

The connector exposes four fixed capabilities:

- `integration.provider.health.v1`
- `fleet.tracking.device.read.v1`
- `fleet.tracking.position.latest.v1`
- `fleet.tracking.position.history.v1`

There is no arbitrary method, URL, path, query or raw-response operation. The
only provider origin is `http://traccar:8082`; redirects are disabled. Position
history is limited to seven days and 5,000 normalized positions. Raw Traccar
attributes do not cross the connector boundary.

## Authentication and material

The manifest declares two logical material names:

- `service_email`
- `service_password`

Integrator materializes them from its deployment-owned secret mount. The
connector knows no OpenBao path and persists neither value.

Authentication is lazy. A successful `POST /api/session` establishes the
provider cookie, isolated by the opaque Integrator `installation_id`. Later reads
reuse it. A read rejected with 401/403 clears that one connection's cookie,
authenticates once and replays the same GET once. A second rejection is final.
The connector contains no general retry or backoff engine.

## Configuration

The connection revision must carry exactly:

```json
{
  "base_url": "http://traccar:8082",
  "connect_timeout_seconds": 5,
  "read_timeout_seconds": 15
}
```

Both timeouts must be between 0.1 and 60 seconds. Configuration cannot widen
the manifest-declared host, port or origin.
