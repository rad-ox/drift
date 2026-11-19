# Legacy Carve-Outs, Mainframe Copybooks & Cutover Governance

> **Tier:** Free (`[assurance.cutover]`, parity/migration receipts, JUnit 4 / PHP / COBOL bridges) · Pro (`--wsdl`, `--copybook`, `--from-signal`) · Enterprise (`sweep --flow` DB/CICS/ORM seam discovery)

When decomposing a monolith or migrating mainframe batch jobs into modern services, DRIFT governs both sides of the cutover with differential parity and multi-epoch database migration receipts.

---

## 1. Scaffold from WSDL 1.1 or COBOL Copybooks (`Pro`)

```bash
# Scaffold a SOAP/XML slice contract from WSDL 1.1 / XSD
drift new .drift/contracts/item-soap.toml --wsdl items.wsdl --profile http-json@1

# Scaffold a batch record contract from a COBOL PIC copybook
drift new .drift/contracts/order-batch.toml --copybook ORDREC.cpy --profile batch@1
```

For runtime bridges covering **Java 6–8 / JUnit 4 (`DriftJUnit4.java`)**, **PHP 8.2+ (`Drift.php`)**, and **COBOL 85 (`drift_cobol.py`)**, see **[Bridges](../bridges.md#legacy-php--mainframe-bridges)**.

---

## 2. Discover Hidden DB, CICS & ORM Seams (`Enterprise`)

Before carving out a slice, audit shared database tables, stored procedures, JDBC/MyBatis/Hibernate metadata, PHP PDO/ORM queries, and COBOL `EXEC SQL`/`CICS` seams:

```bash
drift sweep check .drift/contracts --root . --flow --wsdl items.wsdl --copybook ORDREC.cpy
```

`sweep --flow` surfaces `scope.undeclared_db_access`, `resource.shared_db_write`, and `db.unresolved_sql` without modifying approved contracts.

---

## 3. Differential Cutover Parity & Multi-Epoch DB Migrations (`Free`)

Declare `[assurance.cutover]` on the slice contract to require both differential parity (`*.parity.json`, `drift.parity-receipt/1`) between legacy and candidate targets and passing schema migration receipts (`*.migration.json`, `drift.migration-receipt/1`) before release:

```bash
# Evaluate cutover parity and migration receipts alongside normal proof shards
drift gate .drift/contracts --events target/drift/events --phase release --explain
python3 verifier/drift_verify.py .drift/contracts --config .drift/config.toml --events target/drift/events --phase release --json
```

Both `drift gate` and `verifier/drift_verify.py` fail closed (`parity.*`, `migration.*`) when required epochs or parity runs are missing, stale, or violated.

---

## 4. Post-Release Production Signal Triage (`Pro`)

Feed production anomalies (`drift.production-signal/1`) linked to a verified deployment receipt (`drift.deployment-receipt/1`) directly into draft regression cases:

```bash
drift case add .drift/contracts/order-batch.toml --from-signal prod-signal.json --deployment deploy-receipt.json
```
