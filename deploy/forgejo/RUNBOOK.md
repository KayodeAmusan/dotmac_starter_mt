# Forgejo private registry — standup runbook (dotmac-s3)

Stands up Forgejo as Dotmac's authoritative private artifact registry on
**dotmac-s3 ([redacted 2026-10-05: dotmac-s3 address; see Fleet])**, co-located with the existing MinIO, serving
`https://registry.dotmac.io`. Supersedes the public-PyPI R0 decision (ADR-0005).

**Access:** dotmac-s3 is reached by jumping from seabone
(`ssh seabone 'ssh root@<dotmac-s3 address, from Fleet> …'`) — seabone holds the authorized key.
**Secrets:** every credential is generated on the host and stored in OpenBao;
NEVER printed to a terminal transcript, logged, or committed. `.env` on the host
is populated from OpenBao and is git-ignored.

Host facts (verified 2026-07-30): Ubuntu, Docker; MinIO container mounts
`/opt/minio/data` and publishes `:9000`/`:9001`; nominatim on `:8080`;
node-exporter on `:9100`; 261G free on `/`. Free ports for us: 80, 443, 3000.
UFW currently allows 22, 9000, 9001 (world), 9100 (observe).

---

## 0. Prerequisites / decisions to confirm before applying

- [ ] **OpenBao access** for the workflow: this uses GitHub OIDC → OpenBao JWT
      auth so the release workflow retrieves the Forgejo token at runtime with no
      standing GitHub secret. Requires an OpenBao JWT auth role bound to
      `repo:michaelayoade/dotmac_starter_mt`, workflow `release-kernel.yml`,
      environment `registry-release` (step 5). Confirm OpenBao address + that the
      agent/operator may configure this, OR fall back to a protected GitHub
      environment secret (documented as a deviation).
- [ ] **Firewall**: open 80/443 on dotmac-s3 (step 3). Decide whether to also
      restrict the world-open MinIO console `9001` (and `9000`) to internal/observe.
- [ ] **Pin images to digests**: resolve `codeberg.org/forgejo/forgejo:11`,
      `postgres:16-alpine`, `caddy:2-alpine` to `@sha256:…` before `up`.

---

## 1. MinIO artifact bucket + scoped service account (no new service)

On the host, using the MinIO client `mc` against the local MinIO (root creds from
OpenBao `secret/dotmac/minio/root`, referenced by path — never echoed):

```bash
# Alias to the local MinIO (root creds sourced from OpenBao into the shell env).
mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

# Immutable artifact bucket: versioning + object-lock (WORM retention) so a
# Forgejo admin deleting/republishing a version can NOT erase the prior bytes.
mc mb --with-lock local/dotmac-packages
mc version enable local/dotmac-packages
mc retention set --default GOVERNANCE 90d local/dotmac-packages   # tune period

# Least-privilege policy: read/write on ONLY this bucket.
cat > /tmp/forgejo-pkgs-policy.json <<'JSON'
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow",
    "Action": ["s3:PutObject","s3:GetObject","s3:DeleteObject","s3:ListBucket",
               "s3:GetBucketLocation","s3:ListBucketMultipartUploads",
               "s3:ListMultipartUploadParts","s3:AbortMultipartUpload"],
    "Resource": ["arn:aws:s3:::dotmac-packages","arn:aws:s3:::dotmac-packages/*"] } ] }
JSON
mc admin policy create local forgejo-packages-rw /tmp/forgejo-pkgs-policy.json
mc admin user svcacct add --policy forgejo-packages-rw local "$MINIO_ROOT_USER"
# -> capture the printed Access Key / Secret Key DIRECTLY into OpenBao:
#    bao kv put secret/dotmac/forgejo/minio-svc access_key=… secret_key=…
#    (do NOT echo them to the transcript). Then rm /tmp/forgejo-pkgs-policy.json.
```

## 2. Deploy Forgejo + its Postgres + Caddy

```bash
install -d -m 0755 /opt/forgejo
# Copy deploy/forgejo/{docker-compose.yml,Caddyfile} to /opt/forgejo/.
# Create /opt/forgejo/.env from .env.example, filling values FROM OpenBao:
#   FORGEJO_DB_PASSWORD           <- secret/dotmac/forgejo/db-password (generate)
#   FORGEJO_MINIO_ACCESS_KEY/SECRET_KEY <- secret/dotmac/forgejo/minio-svc (step 1)
cd /opt/forgejo && docker compose pull && docker compose up -d
docker compose ps          # forgejo + forgejo-db(healthy) + caddy up
```

## 3. Firewall + TLS

```bash
ufw allow 80/tcp comment 'Forgejo ACME/redirect'
ufw allow 443/tcp comment 'Forgejo TLS'
# Optional hardening (decision in step 0): scope MinIO off the public internet.
# ufw delete allow 9001/tcp ; ufw delete allow 9000/tcp   # then re-allow from observe/internal only
```

Caddy auto-issues the `registry.dotmac.io` cert on first HTTPS hit. Verify:

```bash
curl -sSI https://registry.dotmac.io/ | head -3         # 200/302 + valid TLS
```

## 4. Bootstrap admin + private org

- Create the initial admin (CLI, no open registration):
  ```bash
  docker compose exec forgejo forgejo admin user create \
    --admin --username dotmac-admin --email registry@dotmac.io \
    --random-password           # capture the password into OpenBao, do not echo
  ```
- In the UI (or CLI): create the **private org `dotmac`**.

## 5. CI publisher identity (scoped token, OpenBao-sourced)

- Create a non-human user `ci-publisher` and add it to org `dotmac` through a
  **packages-only team** — NEVER through `owners`. The team carries the
  packages unit at `write` and every other repository unit at `none`, with
  `can_create_org_repo=false` and `includes_all_repositories=false`. The
  starter's team is `starter-publishers`; `deployment-control-publishers` is
  the equivalent for that lane. Org **team** membership is what grants package
  access — a correctly scoped token with no team membership gets `401
  reqPackageAccess` on the package plane.

  > **Why this is called out.** As built, `ci-publisher` was placed in the
  > `owners` team, which satisfies "package read+write" but also confers full
  > organization ownership. Token scope hides this: a `write:package` token
  > refuses the repository/org APIs regardless of membership, so the excess
  > authority is invisible until someone mints a broader token on the account
  > or signs in with its password (`prohibit_login` is false). Measured
  > 2026-08-30 with an `all`-scoped token on `ci-publisher`: as an owner it
  > created an organization repository and an organization team (201/201);
  > from the packages-only team both are refused (403/403), as is adding
  > itself back to `owners`. Grant packages through a packages-only team and
  > verify with a credential that has only that grant.

  `restricted=true` is NOT a substitute: it was measured to break package index
  reads while changing no refusal.
- Generate a **scoped access token** (scope: `write:package`) and store it:
  `bao kv put secret/dotmac/forgejo/ci-publisher-token token=…` (never echoed).
- Configure OpenBao **JWT auth for GitHub OIDC**: a role bound to
  `sub = repo:michaelayoade/dotmac_starter_mt:environment:registry-release`,
  audience `https://github.com/michaelayoade`, granting read on
  `secret/dotmac/forgejo/ci-publisher-token`. (This is what lets
  `release-kernel.yml` fetch the token at runtime with no GitHub secret.)

## 6. Verify a real upload (manual pre-flight)

```bash
# From a machine with the ci-publisher token (sourced from OpenBao, not echoed):
python -m build     # or use the existing dist/
twine upload --repository-url https://registry.dotmac.io/api/packages/dotmac/pypi \
  -u ci-publisher -p "$FORGEJO_TOKEN" dist/*
pip install --index-url https://ci-publisher:$FORGEJO_TOKEN@registry.dotmac.io/api/packages/dotmac/pypi/simple \
  --pre "dotmac-kernel==0.1.0a1"   # installs; blob served from MinIO
```

## 7. Then: automated release + downstream pinning

- Rework is in `.github/workflows/release-kernel.yml` (this branch): dispatch
  `Release kernel` `version=0.1.0a1` → publishes to Forgejo via the OpenBao token
  → verify installs from the Forgejo index → tag `dotmac-kernel-v0.1.0a1`.
- Pin **Vendor CP** and **Sub** to `dotmac-kernel==0.1.0a1` with the Forgejo index
  as the explicit `--index-url` (no uncontrolled extra-index fallback).
- Lift the main feature freeze; merge WS4 (#23), the font fix (#24), then WS3
  relay into `0.1.0a2`.

## Immutability / operational controls (per the ruling)

- MinIO bucket **versioning + object-lock** retains prior bytes + digests even if
  a Forgejo admin deletes/republishes — the tamper-evident anchor.
- Restrict Forgejo admin accounts; treat delete/republish as an audited action.
- Off-host/versioned backups: MinIO bucket replication/backup + the Forgejo
  metadata Postgres dump (add to the fleet backup rota).
- All images pinned to digests; all publishing-workflow actions pinned to SHAs.
