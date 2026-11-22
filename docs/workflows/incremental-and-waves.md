# Incremental Selection, `@recall`, Wave Scheduling & Mutation Proofs

> **Tier:** Pro (Selection, `--base` proof reuse, `impact`, `recall`, `plan`, `merge`, spec scaffolding, `review --base`) · Enterprise (`mutants`, `sweep --flow --simplify --promote`, `stats`)

As a repository grows from one slice to hundreds, DRIFT keeps feedback sub-second through causal graphs, symbolic context capsules, wave scheduling, and mutation campaigns.

---

## 1. Causal Test & Budget Selection (`Pro`)

`drift select` traces `bind.code`, `<path>#<symbol>` anchors, `policy.ignore` helper reverse-imports, coupled resources, and optional Cargo/Maven build graphs (`verifier/drift_build_graph.py`)—widening safely whenever ownership is uncertain:

```bash
# Emit affected test files, a structured drift.test-plan/1 JSON, or a ready-to-run shell command
drift select HEAD .drift/contracts --events .drift/events --changed src/items.js --files
drift select HEAD .drift/contracts --events .drift/events --changed src/items.js --plan --json
drift select HEAD .drift/contracts --events .drift/events --changed src/items.js --cmd

# Narrow across Cargo/Maven workspace manifests
python3 verifier/drift_build_graph.py --root . --out .drift-work/build-graph.json
drift select HEAD .drift/contracts --events .drift/events --changed crates/core/src/lib.rs --build-graph .drift-work/build-graph.json --plan

# Reuse passing proofs and security locks on untouched slices
drift gate .drift/contracts --events .drift/events --base HEAD --changed src/items.js
```

In Maven builds, `-Ddrift.changed=auto` snapshots the Git tree during `prepare` and reuses unchanged test shards automatically while enforcing the gate.

---

## 2. Blast Radius, `@recall` Capsules & Wave Planning (`Pro`)

```bash
# Transitive resource blast radius
drift impact .drift --writes items --transitive

# L0–L2 hierarchical domain tree and token-budgeted symbolic recall capsules
# (add --max-degraded-lenses N to fail closed if over-compressed @ lenses exceed N)
drift recall query "@tree" .drift
drift recall query "item lookup #getItem /800t" .drift --max-degraded-lenses 0

# Record standing or anchor-triggered negative analysis findings (surfaced as [due] on drift)
drift recall record item-get --dead-end "Keep lookup stateless" --revisit-if src/items/handler.js#getItem --shared

# Compute conflict-free parallel execution waves, compile-edge stages, and fenced worker packs
# (pass --pack-base <prior-pack.json> to emit a content-addressed backscatter delta)
drift plan .drift/contracts --events .drift/events --pack ready --active --compile-edges
```

---

## 3. Multi-Source Scaffolding, 3-Way Merge & Semantic Baseline Review (`Pro`)

```bash
# Scaffold profiles and contracts from OpenAPI 3.x (incl. 3.2 QUERY), AsyncAPI, or recorded traces
drift new .drift/profiles/items-api@1.toml --openapi openapi.json
drift new .drift/profiles/items-events@1.toml --asyncapi asyncapi.json
drift new .drift/contracts/item-legacy.toml --from-upstream .drift-work/observed.jsonl --profile http-json@1

# Semantic baseline diff: detects renames, moved cases, contravariant when.narrowed, then.widened,
# relaxation witnesses, budget referent shifts, and undiscriminated added cases
drift review .drift/contracts --brief --base HEAD --delta --as md

# Three-way structural and semantic TOML merge (usable as a Git merge driver)
drift merge base.toml ours.toml theirs.toml --out -
```

---

## 4. Mutation Proofs, Fleet Flow Audits & Churn Radar (`Enterprise`)

Upgrade `[policy]` in `.drift/config.toml` to `pack = "core@1"` and `proof = "killed"` for high-criticality areas:

```bash
# Audit ownership, cross-contract dataflow, L0–L3 causal coupling, FSM/Saga protocols,
# write duplicates, exact symbol clones, and AsyncAPI multi-epoch compatibility
drift sweep check .drift/contracts --root . --flow --simplify

# Generate contract and incoming-seam mutants prioritized by risk and [policy].priority_weights
# (add --pairs to append bounded 2nd-order compatible mutant pairs per case)
drift mutants .drift/contracts --out .drift-work/mutants.json --budget 50 --events .drift/events
DRIFT_MUTANTS=.drift-work/mutants.json DRIFT_MUTATION_EVENTS=.drift-work/mutation-events node --test

# Verify killed proof floor and emit JUnit XML + OpenSSH-signed attestation
drift gate .drift/contracts --events .drift/events \
  --mutants .drift-work/mutants.json --mutation-events .drift-work/mutation-events \
  --attest target/drift/attestation.json --ssh-sign ~/.ssh/id_ed25519 \
  --trust-root .drift/allowed_signers --verify-time 2026-11-10T09:00:00Z \
  --as junit > target/drift/junit.xml

# Rank uncontracted Git churn hotspots, co-change coupled contracts, and C/U obligation density (--density --ops)
drift stats .drift/contracts --root . --churn-list git-log.txt --top 10 --detail summary
```
