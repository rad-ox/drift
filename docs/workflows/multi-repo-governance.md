# Multi-Repo Governance: Clean-Room Grants, Bilateral Pacts & Federation

> **Tier:** Free (Grantee onboarding & `--grant-lock`, Pact onboarding & `--pact-lock`, federated `drift.composition-manifest/1` gating, MIT verifier parity) · Pro (`export grant`, `drift pact`, `export boundary`) · Enterprise (`sweep --flow --pacts`, AsyncAPI `--epoch-manifest`)

When multiple repositories, teams, or external suppliers collaborate across service boundaries, DRIFT coordinates integration seams **without exposing internal code paths or private slices**.

---

## 1. Clean-Room Specification Grants (`drift.grant-lock/1`)

Package approved `0.3` contracts for an external implementer or supplier under an explicit `grant-policy.toml` (redacting `[bind]`, unpicked options, notes, and forbidden egress tokens while preserving exact `dr2b:` behaviour digests and `dr2r:` obligations):

```bash
# Grantor (Pro): preview exact egress strings, then export and sign the grant
drift export grant .drift/contracts --policy grant-policy.toml --dry-run
drift export grant .drift/contracts --policy grant-policy.toml --out dist/orders-grant --ssh-sign ~/.ssh/grantor_ed25519

# Grantee (Free): onboard the grant into a clean repository
drift init supplier-team ./supplier-repo --grant dist/orders-grant

# Grantor acceptance CI (Free or MIT verifier): verify against Grantor's external lock
drift gate ./supplier-repo/.drift/contracts --events ./supplier-repo/events \
  --grant-lock dist/orders-grant/.drift/grant.lock.json --trust-root .drift/allowed_signers
python3 verifier/drift_verify.py ./supplier-repo/.drift/contracts --config ./supplier-repo/.drift/config.toml \
  --events ./supplier-repo/events --grant-lock dist/orders-grant/.drift/grant.lock.json --json
```

---

## 2. Bilateral Integration Pacts (`drift.pact-lock/1`)

Negotiate a balanced integration seam between two peer repositories across 6 axes (surface, domain slack, failure duties, retry deadlines, evolution, and assurance trust) using blind redacted offers:

```bash
# 1. Each side exports a blind redacted offer (Pro)
drift pact offer .drift/contracts --policy equalizer-policy.toml \
  --pact-id orders-pact --counterparty checkout --role producer --area orders --out dist/orders.offer.json

# 2. Equalize both offers and seal the bilateral lock (Pro)
drift pact equalize --left dist/orders.offer.json --right dist/checkout.offer.json --policy equalizer-policy.toml --as md
drift pact seal --left dist/orders.offer.json --right dist/checkout.offer.json --policy equalizer-policy.toml --out dist/orders-pact.lock.json

# 3. Onboard and enforce directional conformance on each side (Free)
drift init checkout-team ./checkout-repo --pact dist/orders-pact.lock.json
drift gate ./checkout-repo/.drift/contracts --events ./checkout-repo/events --pact-lock dist/orders-pact.lock.json
```

Local tightenings and internal refactors remain green without renegotiating the lock; envelope widenings, missing bilateral OpenSSH quorums, or unacknowledged revision retirements (`drift pact ack`) fail closed.

In **Enterprise**, verify multi-hop fleet conservation (deadline squeeze, idempotency breaks, posture inversion, unmapped errors, revision hazards, and non-injective boundary projections `pact.boundary_non_injective`) across all pacts:

```bash
drift sweep check .drift/contracts --root . --flow --pacts dist/pacts
```

---

## 3. Federated Composition & Boundary Bundles (`drift.boundary-bundle/1`)

Export bidirectional boundary bundles (`offers` / `requires`) and verify multi-service canary rollout matrices and retained AsyncAPI event epochs:

```bash
# Export boundary bundle (Pro)
drift export boundary .drift/contracts --out target/drift/boundary.json

# Audit directional AsyncAPI compatibility across retained epochs (Enterprise)
drift sweep check .drift/contracts --root . --flow --asyncapi asyncapi.json --epoch-manifest epochs.json
```
