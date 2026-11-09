# Guida Pratica a DRIFT

[English](GUIDE.md) · **Italiano**

<p align="center">
  <img src="assets/workflow.svg" alt="DRIFT Verification Loop" width="100%" />
</p>

DRIFT mantiene un contratto di comportamento per ogni slice in
`.drift/contracts/<id>.toml`. L'owner umano approva una versione specifica del
contratto (`dr1:<hash>`), e il gate di rilascio è **verde** (`green`) solo
quando i test eseguiti esattamente contro quella versione passano. Qualsiasi
modifica alle regole o agli esiti attesi del contratto rende l'approvazione
obsoleta (`stale`; spostare i percorsi `scope.code` o `owners` non invalida il
digest comportamentale durante i refactoring interni, pertanto proteggi
`.drift/**` con `CODEOWNERS` e commit firmati su GitHub così ogni modifica a
`[approval]` o `scope.code` richiede revisione autenticata in PR), e
un'esecuzione di test precedente non può mai dimostrare un contratto più
recente.

Prima di iniziare, installa DRIFT seguendo **[INSTALL.it.md](INSTALL.it.md)** ([English](INSTALL.md)).

---

## Concetti Chiave in 2 Minuti

| Concetto | File / Artefatto | Ruolo |
|---|---|---|
| **Area** | `.drift/config.toml` | Configurazione radice dell'area: nome, policy opzionale ed elenco degli approvatori autorizzati. |
| **Profilo** | `.drift/profiles/<name>@<ver>.toml` | Dichiara il vocabolario di predicati ammessi in `when` (precondizioni/input) e `then` (esiti attesi). |
| **Contratto** | `.drift/contracts/<slice>.toml` | Descrive il comportamento atteso di una slice: `[scope]`, `[cases.<id>]` e `[decisions.<id>]`. |
| **Approvazione** | `[approval]` (`ref = "dr1:..."`) | Sigillo registrato da `drift approve --by <owner>`. Diventa `stale` (`DR-E601`) se il comportamento cambia. |
| **Vista Risolta** | `<slice>.json` | JSON canonico esportato da `drift show --as json` e letto a runtime dai bridge di test. |
| **Evento di Prova** | `events.jsonl` + `.meta.json` | Emesso dai test runner (JUnit / Scala MUnit, Node.js, Python, Rust o V) quando i test vincolati vengono eseguiti. |
| **Gate** | `drift gate` | Verifica che configurazione e contratti siano approvati e che ogni caso, budget, ricevuta di sicurezza e prova formale abbia una prova valida e corrente. |

---

## Adottare DRIFT per Livelli Progressivi

Ogni livello porta valore immediato da solo: puoi fermarti al livello adatto al
tuo progetto o arrivare fino alla mutation analysis e alle attestazioni di
rilascio.

| Livello | Cosa aggiungi | Cosa ottieni | Edizione |
|---|---|---|---|
| **Livello 0** | `.drift/config.toml` + `.drift/contracts/*.toml` | Contratti per slice approvati dall'owner (inclusi vincoli relazionali `then`, `[invariants]`, frame `writes`, `[budgets.<id>]`, `[requires].security` e `[formal.<id>]`) che diventano `stale` ad ogni modifica non approvata | **Free** |
| **Livello 1** | Test vincolati (`@DriftCase` / `Drift.expect`, `runDriftCase`, `run_drift_case`) | Un gate **verde** solo quando test reali (Java, Scala, JS/TS, Python, Rust o V) passano contro la versione approvata | **Free** |
| **Livello 2** | Selezione incrementale (`drift select`), `@recall`, scaffolding OpenAPI/AsyncAPI e da tracce | Esecuzione dei soli test e budget impattati, riuso sicuro delle prove tramite snapshot e generazione di contratti da specifiche o tracce runtime | **Pro** |
| **Livello 3** | `[policy]` (`core@1`) + `drift mutants` + `sweep --flow` + `gate --attest` (`--ssh-sign`) | Approvatori certificati, soglia minima `verified` o `killed`, audit architetturali FSM/Saga/sicurezza e bundle di attestazione CI firmati OpenSSH | **Enterprise** |

---

## Livello 0: Contratti, Decision Card e Approvazione dell'Owner

### 1. Inizializza un'Area

Crea una nuova area `.drift` nella radice del progetto:

```bash
drift init catalog-service .
drift approve .drift/config.toml --by alice
```

### 2. Crea lo Scaffold di una Slice

```bash
drift new .drift/contracts/item-get.toml --profile http-json@1 --intent "Restituisce un articolo per id."
```

Per costruzione, uno scaffold appena generato **non può essere approvato subito**:
`indirect = "unknown"`, i valori `todo` e le domande aperte `[open.<id>]`
bloccano l'approvazione (`DR-E602`) finché non vengono risolti.

### 3. Compila Scope, Casi e Decision Card

Sostituisci i segnaposto con il comportamento reale della slice:

```toml
drift = "0.2"
id = "item-get"
intent = "Restituisce un articolo per id."

[use]
profile = "http-json@1"

[scope]
surface = "GET /items/{id}"
writes = []
reads = ["items"]
indirect = "none"
code = ["src/main/java/example/items/**"]

[cases.found]
at = ["http"]
when.request = "GET /items/1"
then.status = 200
then.name = "lamp"

[cases.missing]
at = ["http"]
when.request = "GET /items/99"
then.status = 404
then.error = "not_found"

[decisions.cache-lookup]
kind = "choice"
ask = "Leggere direttamente dallo store primario o introdurre una cache in memoria?"
pick = "primary-store"
cases = ["found", "missing"]
note = "La latenza su nodo singolo è <2ms; una cache aggiunge complessità di invalidazione."
evidence = "observed"
why = "La lettura diretta mantiene la consistenza immediata senza stato aggiuntivo."
options.primary-store = { does = "Interroga lo store primario a ogni GET.", complexity = "1/4", effort_h = 1, risk = "1/4", undo = "easy", leverage = "3/4" }
options.read-through-cache = { does = "Mantiene gli articoli in cache per id con TTL.", complexity = "3/4", effort_h = 4, risk = "2/4", undo = "easy", leverage = "2/4" }
```

> **Nota sui commenti TOML:** DRIFT rifiuta i commenti `#` nei file `.toml` (`DR-E004`) affinché nessuna motivazione resti nascosta fuori dai pacchetti di revisione o dal digest. Inserisci il testo descrittivo in `intent`, `ask`, `note`, `why` o `because`.

### 4. Formatta, Controlla, Revisiona e Approva

```bash
drift fmt .drift                                      # Layout TOML canonico
drift check .drift                                    # Tutte le regole statiche in un solo passaggio
drift review .drift/contracts/item-get.toml --brief   # Pacchetto di revisione per l'owner (exit 1 finché non approvato)
drift approve .drift/contracts/item-get.toml --by alice
```

Per un handoff vincolato alla versione, esegui `drift review <file|dir> --detail guided --as json` e conserva il JSON nella sessione dell'host. Approvalo con `drift approve --reviewed FILE --expect-review REF --by OWNER`, dove `REF` è esattamente il valore `review_snapshot.review_ref` mostrato nel JSON. Lo snapshot vincola area, selettori, target, policy e contesto decisionale; non è una firma e non prova chi ha acconsentito. Il comando `approve` legacy resta disponibile per approvazioni esplicite senza protezione dello snapshot.

Se `drift check` segnala un errore, esegui `drift explain <codice>` (ad esempio `drift explain DR-E601`) per vedere causa e correzione.

### 5. Vincoli Relazionali `then`, `[invariants]`, Frame `writes`, Budget, Sicurezza e Prove Formali

Oltre ai valori scalari puntuali, i contratti di **DRIFT Free** esprimono vincoli di dominio ed evidenze direttamente in `.toml`:

```toml
drift = "0.2"
id = "item-get"
intent = "Restituisce un articolo per id con latenza limitata e sicurezza formale sul totale."

[use]
profile = "http-json@1"

[scope]
surface = "GET /items/{id}"
writes = []
reads = ["items"]
indirect = "none"
code = ["src/main/java/example/items/**"]

[invariants]
status = { in = [200, 400, 404] }
body = { forbid_keys = ["password_hash", "internal_token"] }

[cases.found]
at = ["http"]
writes = []
when.request = "GET /items/1"
then.status = 200
then.name = { non_empty = true }
then.body = { allowed_keys = ["id", "name", "price", "tax", "total"] }
then.price = 10.0
then.tax = 2.0
then.total = { min = 0.0, max = 10000.0, sum_fields = ["price", "tax"] }
then.currency = { not_in = ["UNKNOWN"] }

[budgets.p99-latency]
case = "found"
metric = "request_latency"
unit = "ns"
aggregation = "p99"
op = "le"
limit = 15000000
evidence = "statistical"
min_confidence = 0.95
enforce = "release"
workload_ref = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
protocol_ref = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
environment_ref = "sha256:3333333333333333333333333333333333333333333333333333333333333333"
warn_ratio = 0.85

[formal.no-negative-total]
cases = ["found"]
verifier = "cbmc"
property = "no_negative_total"
property_kind = "safety"
min_evidence = "bounded_exhaustive"
linkage = "in_code_harness"
harness = "src/items.c#proof_no_negative_total"
enforce = "release"
```

- **Tabelle relazionali `then`**: vincolano intervalli numerici (`min`, `max`), tolleranze in virgola mobile (`approx`, `abs_tol`, `rel_tol`), invarianti di traiettoria tolleranti al tuning (`monotonic`, `sum_total`, `step_max_delta`), lunghezze (`min_len`, `max_len`, `non_empty`), insiemi finiti (`in`, `not_in`), affissi stringa (`prefix`, `suffix`, `contains`), chiavi consentite/vietate ricorsive nel payload grezzo prima della proiezione (`allowed_keys`, `forbid_keys`), confronti tra campi (`le_field`, `ge_field`, `eq_field`), somme affini (`sum_fields`) e bilanci lineari a partita doppia (`balance_fields`).
- **`[invariants]`, `[assurance.guards]` e frame condition `cases.<id>.writes`**: `[invariants]` vale su tutti i casi; `cases.<id>.writes` restringe quali risorse di `scope.writes` uno specifico caso può mutare (verificato a runtime con `checkFrame` / `checks.frame`, `checkLogSink` e collector frame non osservati `{ "observed": false }`); i contratti schema `0.3` (`drift fmt --upgrade 0.3`) introducono identità `dr2` a 256 bit separate per dominio (`dr2b`, `dr2a`, `dr2r`, `dr2x`) e `[assurance.guards]` tipizzati.
- **Evidenze di Performance (`[budgets.<id>]`), Sicurezza (`[requires].security`), Regolamentate (`[risks]`/`[controls]`), Simulazione (`drift.sim-receipt/1`) e Prove Formali (`[formal.<id>]`)**: passa `--measurements bench.jsonl` (`request_latency`, `successful_throughput`, `process_rss`, `frame_time`, `cold_start`, `artifact_bytes`, `work_units`), le ricevute `*.security.json` (con riuso selettivo `--security-lock`), le ricevute `*.study.json` e `*.evaluation.json` con firme multi-party detached `.sig.json`, le ricevute di replay/rollback deterministico `drift.sim-receipt/1` e le ricevute formali `*.formal.json` / `*.model.json` (`tlc`, `cbmc`, `alloy`, `spin`, Kani, `gappa` `arithmetic_model`, `stochastic_experiment`, `equivalence` QCEC, `observed_convergence`, `trajectory_stability`) a `drift prove`, `drift gate` e `verifier/drift_verify.py`.
- **Concetti di Dominio (`[concepts]`), Cutover Legacy (`[cutover]`) e Sequenze UI**: definisci i `[concepts]` di dominio qualificati per contesto in `.drift/config.toml` (`[use].concepts`, `drift new --concept`, recall `@concept`), vincola il cutover con ricevute di parità e migrazione DB (`[cutover]`, `*.parity.json` `drift.parity-receipt/1` e `*.migration.json` `drift.migration-receipt/1`) o segnali di produzione (`drift case add --from-signal`), e verifica superfici e sequenze UI multi-step (`drift.ui-observation/1` tramite `collectPlaywrightSequence` / `observeUiSequence`, profili riusabili `async-action-feedback@1` e `wizard-form@1`, `evaluateScenarioMatrix` e adapter Web, Compose o Windows UIA).
- **Protocollo di Osservazione Canonico (`drift.observation/1`), Sessioni Supervisor (`drift.bridge-session/1`), Seam Perimetrali, Shadow Mode e Composizione Federata**: valuta osservazioni lossless `ObsValue` (`int64`, `decimal`, `bytes` e decodifica copybook COBOL nativa nel kernel) e sessioni supervisor (`drift.bridge-session/1`) direttamente nel kernel, applica il coupling causale `L0–L3` (`sweep --flow`) e i controlli world-frame (`_frame` con `allowed_keys` e `checkFrame`), traccia la provenienza degli stub `.drift/seam-stub/` in `.meta.json` (`oracle.unverified_seam`, `oracle.stale_seam_stub`), sonda gli estremi 2-skeleton dei seam (`checkSeamBounds` / `check_seam_bounds`), le sonde comportamentali (idempotenza, retry/query sui seam, rollback, BOLA) e l'iniezione di guasti sui seam in ingresso (`prove.seam_mutants`), esegui DRIFT in **Shadow Mode** esterno (`--state-dir` / `DRIFT_STATE_DIR`, `shadow.toml`, albero soggetto in sola lettura con `GIT_OPTIONAL_LOCKS=0` e adapter JUnit XML a 2 fasi `verifier/drift_shadow_junit.py`), e governa il rollout multi-repository con `drift.composition-manifest/1` e bundle bidirezionali `drift.boundary-bundle/1` (`offers`/`requires`).

---

## Livello 1: Collegare i Test e Superare il Gate

Prima di eseguire i test, ogni caso del contratto risulta `missing`:

```text
item-get dr1:5922b40e14d7: not green (proof.not_green); 2 missing
```

### Opzione A: Java, Scala 3 / MUnit, Maven e sbt (`drift-junit` + `drift-maven-plugin`)

Aggiungi la dipendenza di test e il plugin al `pom.xml`:

```xml
<dependencies>
  <dependency>
    <groupId>drift</groupId>
    <artifactId>drift-junit</artifactId>
    <version>0.5.0</version>
    <scope>test</scope>
  </dependency>
</dependencies>

<build>
  <plugins>
    <plugin>
      <groupId>drift</groupId>
      <artifactId>drift-maven-plugin</artifactId>
      <version>0.5.0</version>
      <executions>
        <execution>
          <goals>
            <goal>prepare</goal>
            <goal>gate</goal>
          </goals>
        </execution>
      </executions>
    </plugin>
  </plugins>
</build>
```

Annota i test JUnit 5 con `@DriftCase` e leggi i valori attesi dal contratto tramite `Drift.expect`:

```java
@Test
@DriftCase(contract = "item-get", cases = "found", level = "http")
void returnsAnExistingItem() throws Exception {
    Drift.Case c = Drift.expect("item-get", "found");
    HttpResponse<String> r = send(c.whenString("request"));
    assertEquals(c.thenInt("status"), r.statusCode());
    assertEquals(c.thenString("name"), parseName(r.body()));
}
```

Poi esegui:

```bash
mvn verify
```

In **Scala 3 / sbt** (ad esempio **MUnit** `FunSuite`), risolvi `drift-junit` dal repository Maven locale in `build.sbt` e chiama `Drift.expect(contract, caseId, level)` + `c.verify(...)` direttamente nel corpo del test (senza annotazioni):

```scala
// build.sbt
scalaVersion := "3.9.0"
resolvers += Resolver.mavenLocal
libraryDependencies += "drift" % "drift-junit" % "0.5.0" % Test
Test / fork := true
Test / javaOptions ++= Seq(
  s"-Ddrift.resolved=${baseDirectory.value}/target/drift/resolved",
  s"-Ddrift.events=${baseDirectory.value}/target/drift/events"
)
```

```scala
// src/test/scala/example/items/ItemSuite.scala
import drift.Drift

class ItemSuite extends munit.FunSuite:
  test("returns existing item") {
    val c = Drift.expect("item-get", "found", "http")
    val res = send(c.whenString("request"))
    c.verify("status", res.status, "name", res.name)
  }
```

```bash
drift show .drift/contracts --as json --out target/drift/resolved
sbt test
drift gate .drift/contracts --events target/drift/events
```

- **`verified` vs `bound`**: Quando il test legge **tutti** i campi `then` del caso tramite `Drift.expect` (o li verifica con `c.verify(...)` nelle suite basate su closure come **Scala 3 / MUnit**), il caso raggiunge lo stato **`verified`**. Se il test passa senza leggere tutti i campi `then`, viene registrato come **`bound`**.

### Opzione B: JavaScript / TypeScript (`bridges/drift.mjs`)

```js
import { test } from 'node:test';
import { runDriftCase } from './drift.mjs';

test('returns existing item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', {
      status: res.status,
      name:   res.body.name,
    });
  });
});
```

```bash
node --test
drift gate .drift/contracts --events .drift/events
```

### Opzione C: Python 3 (`bridges/drift.py`)

```python
import drift

def test_found():
    def verify(d):
        res = send(d.when("found", "request"))
        d.check("found", {"status": res.status, "name": res.name})

    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_found",
        cases=["found"],
        level="http",
        fn=verify,
    )
```

```bash
pytest
drift gate .drift/contracts --events .drift/events
```

### Opzione D: Rust (`bridges/rust` · `drift_rust`)

```rust
use drift_rust::{canonical_rust_test_id, run_drift_case, RunOptions};

#[test]
fn test_found() {
    let tid = canonical_rust_test_id("catalog", module_path!(), "test_found");
    run_drift_case(
        RunOptions {
            contract: "item-get".to_string(),
            test: tid,
            cases: vec!["found".to_string()],
            level: "http".to_string(),
            ..Default::default()
        },
        |ctx| {
            let payload = send(ctx.when_str("found", "request")?);
            ctx.check_projection("found", &payload)
        },
    ).expect("drift case verified");
}
```

```bash
drift show .drift/contracts --as json --out target/drift/resolved
DRIFT_RESOLVED=target/drift/resolved DRIFT_EVENTS=target/drift/events cargo test
drift gate .drift/contracts --events target/drift/events
```

### Opzione E: V (`bridges/v/drift_v`)

```v
import drift_v

fn test_found() {
	res := drift_v.run_drift_case(drift_v.RunOptions{
		contract: 'item-get'
		test:     'items_test#test_found'
		cases:    ['found']
		level:    'http'
	}, fn (mut ctx drift_v.DriftContext) ! {
		payload := send(ctx.when_str('found', 'request')!)
		ctx.check_projection('found', payload)!
	}) or { panic(err) }
	assert res == 'passed'
}
```

```bash
drift show .drift/contracts --as json --out .drift-work/resolved
DRIFT_RESOLVED=.drift-work/resolved DRIFT_EVENTS=.drift-work/events v -path "bridges/v|@vlib|@vmodules" test .
drift gate .drift/contracts --events .drift-work/events
```

### Sezione Dedicata Legacy & Monoliti: Java 6+ / JUnit 4 (`DriftJUnit4.java`), PHP 8.2+ (`Drift.php`) e COBOL 85 (`drift_cobol.py`)

Mentre i bridge principali puntano alle ultime versioni **LTS/stable** (`drift-junit` su Java 25 LTS / Scala 3.9 LTS / JUnit 5 Platform, `drift.mjs` su Node.js 24 LTS, `drift.py` su Python 3.14, `drift_rust` su Rust Edition 2024, `drift_v` su V 0.5.2), per i monoliti legacy e i carve-out enterprise sono disponibili bridge dedicati senza dipendenze:
- **Java 6–8 / JUnit 4 (`drift.junit4.DriftJUnit4`, `bridges/legacy/junit4/DriftJUnit4.java`)**: collega `DriftJUnit4.Listener` al `RunListener` JUnit 4 per generare gli inventari `.meta.json` e gli eventi `bound` senza dipendenze da JUnit 5, e invoca `DriftJUnit4.verify(contract, caseId, observations, frames)` e `DriftJUnit4.replayCounterexamples(...)` nei test delle slice estratte.
- **PHP 8.2+ (`Drift\Drift`, `bridges/Drift.php`)**: verifica proiezioni RFC 6901 JSON Pointer, clausole relazionali/negative (`forbid_keys`, `not_in`), write frame per caso (`checkFrame`) e fixture `*.cex.json`, scrivendo sidecar atomici `.events.jsonl` e `.meta.json`.
- **COBOL 85 Batch / Copybook (`drift_cobol`, `bridges/drift_cobol.py`)**: analizza layout copybook `PIC` (`--copybook`), serializza i `when` JSON in record a larghezza fissa (`PIC X`, `PIC 9`, `PIC S9...V99`), vincola gli input `.cbl`/`.cpy` in `.meta.json` (o invia record grezzi `drift.observation/1` decodificati dal kernel) ed emette ricevute di cutover `drift.parity-receipt/1` tra batch mainframe e nuovi microservizi.
- **C++20 (`bridges/drift_cpp.hpp`), C# / .NET / Unity (`bridges/Drift.cs`) e Godot 4 GDScript (`bridges/drift.gd`)**: bridge single-file senza dipendenze per motori real-time, simulazioni e codice nativo, con supporto per invarianti di traiettoria tolleranti al tuning (`monotonic`, `sum_total`, `step_max_delta`), tolleranze numeriche (`approx`, `abs_tol`, `rel_tol`, `balance_fields`), replay deterministico dei tick (`drift.sim-receipt/1`), `forbid_keys` ricorsivo, collector frame non osservati e `checkLogSink`.

---

## Livello 2: Selezione Incrementale, Blast Radius e Scaffolding da Specifiche/Tracce (`Pro`)

Quando il numero di slice cresce, **DRIFT Pro** usa il grafo di `scope.code`, `scope.reads` e `scope.writes` (su Java, Scala, JS/TS, Python, Rust, V, C++, C#, GDScript, PHP, COBOL e Pug/Sass/CSS) per selezionare solo i test e i budget di performance toccati da una modifica—allargando automaticamente a tutti i test in caso di dubbio:

```bash
# Elenca solo i file di test (o genera un piano drift.test-plan/1) impattati dai file sorgente modificati
drift select .drift/contracts --events .drift/events --changed src/items.js --files
drift select .drift/contracts --events .drift/events --changed src/items.js --plan --cmd node --test

# Riusa le prove precedenti per i contratti non toccati mantenendo il gate attivo
drift gate .drift/contracts --events .drift/events --base HEAD --changed src/items.js

# Analizza il blast radius, la mappa di dominio (@tree) o compila capsule @recall
drift impact .drift --writes items --transitive
drift recall query "@tree" .drift
drift recall query "item lookup #getItem /800t" .drift
drift plan .drift/contracts --pack ready

# Genera profili da OpenAPI 3.x (incluso 3.2 QUERY) o AsyncAPI, e contratti da WSDL, copybook COBOL o tracce runtime observe()
drift new .drift/profiles/items-api@1.toml --openapi openapi.json
drift new .drift/profiles/items-events@1.toml --asyncapi asyncapi.json
drift new .drift/contracts/item-soap.toml --wsdl items.wsdl --profile http-json@1
drift new .drift/contracts/item-batch.toml --copybook ORDREC.cpy --profile batch@1
drift new .drift/contracts/item-legacy.toml --from-upstream .drift-work/observed.jsonl --profile http-json@1
drift export boundary .drift/contracts --out target/drift/boundary.json
```

Nei progetti Maven, `-Ddrift.changed=auto` cattura uno snapshot dell'albero Git durante `prepare` e riusa automaticamente gli shard non toccati mantenendo `gate` attivo.

---

## Livello 3: Policy `core@1`, Audit Architetturali e Mutation Testing (`Enterprise`)

Per i servizi mission-critical, aggiungi una sezione `[policy]` a `.drift/config.toml` e ri-approva la configurazione:

```toml
drift = "0.2"
kind = "config"

[area]
owner = "alice"

[policy]
pack = "core@1"
approvers = ["alice", "bob"]
proof = "verified"
```

Con `pack = "core@1"`:
1. Solo gli owner elencati in `approvers` possono approvare i contratti (`DR-E603` altrimenti).
2. Ogni caso deve raggiungere almeno lo stato `verified`.
3. Impostando `proof = "killed"`, ogni mutante sintetico dei valori `then` (e `--when`) generato da `drift mutants` deve essere intercettato e ucciso (`killed`) dai test, mentre `sweep --flow` verifica il dataflow cross-contratto, deadlock FSM, compensazioni Saga, consegne duplicate, compatibilità multi-epoca AsyncAPI e confini di sicurezza/budget:

```bash
# Verifica ownership dell'area, dataflow, protocolli FSM/Saga e compatibilità multi-epoca AsyncAPI
drift sweep check .drift/contracts --root . --flow --asyncapi asyncapi.json --epoch-manifest epochs.json

# Genera i mutanti del contratto, esegui i test in-process ed emetti l'attestazione firmata OpenSSH
drift mutants .drift/contracts --out .drift-work/mutants.json
DRIFT_MUTANTS=.drift-work/mutants.json DRIFT_MUTATION_EVENTS=.drift-work/mutation-events node --test
drift gate .drift/contracts --events .drift/events \
  --mutants .drift-work/mutants.json --mutation-events .drift-work/mutation-events \
  --attest target/drift/attestation.json --ssh-sign ~/.ssh/id_ed25519 \
  --trust-root .drift/allowed_signers --verify-time 2026-11-08T09:00:00Z \
  --as junit > target/drift/junit.xml
```

---

## Autocompletamento nell'Editor (VS Code e JetBrains)

DRIFT include gli JSON Schema per contratti, profili e `.drift/config.toml` (installati in `~/.local/share/drift/schemas/` su Linux/macOS e `%LOCALAPPDATA%\Programs\drift\schemas\` su Windows, oppure in `schemas/` nel repository).

Aggiungi a `.vscode/settings.json` (con l'estensione **Even Better TOML** / Taplo):

```json
{
  "evenBetterToml.schema.associations": {
    ".*\\.drift/contracts/.*\\.toml$": "./schemas/drift-contract-0.2.schema.json",
    ".*\\.drift/profiles/.*\\.toml$": "./schemas/drift-profile-0.2.schema.json",
    ".*\\.drift/config\\.toml$": "./schemas/drift-config-0.2.schema.json"
  }
}
```

---

## Codici Diagnostici più Comuni (`DR-E*`)

Esegui `drift explain <CODICE>` per ottenere la spiegazione completa e la correzione suggerita.

| Codice | Nome | Significato e Correzione |
|---|---|---|
| `DR-E004` | `toml.comment` | I commenti `#` non sono ammessi nei file TOML di DRIFT. Sposta il testo in `intent`, `ask`, `note`, `why` o `because`. |
| `DR-E102` | `contract.id_mismatch` | Il campo `id = "..."` deve coincidere con il nome del file (`<id>.toml`). |
| `DR-E201` | `profile.missing` | Il profilo indicato in `[use].profile` non è presente in `.drift/profiles/`. |
| `DR-E203` | `vocab.unknown_when` / `then` | Un caso usa un predicato non dichiarato nel `[vocabulary]` del profilo o in `[use.vocabulary]`. |
| `DR-E601` | `approval.stale` | Il contratto o la configurazione sono stati modificati dopo l'approvazione. Revisiona con `drift review --brief` e riesegui `drift approve --by <owner>`. |
| `DR-E602` | `approval.blocked` | Il contratto contiene ancora `indirect = "unknown"`, un valore `"todo"` o una domanda aperta `[open.<id>]`. |
| `DR-E603` | `approval.unauthorized` | L'approvatore indicato in `[approval].by` non compare in `.drift/config.toml` `[policy].approvers`. |
