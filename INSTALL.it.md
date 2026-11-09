# Installare DRIFT

[English](INSTALL.md) · **Italiano** · [Guida Pratica](GUIDE.it.md) · [Edizioni](EDITIONS.md)

DRIFT è un solo comando, `drift`, con parti facoltative: una skill per
l'agente, un bridge JUnit / Scala MUnit e plugin Maven per i progetti JVM, e i
bridge senza dipendenze per JavaScript (`drift.mjs`), Python (`drift.py`), Rust
(`drift_rust`), V (`drift_v`), C++20 (`drift_cpp.hpp`), C# (`Drift.cs`),
GDScript (`drift.gd`), PHP (`Drift.php`), COBOL (`drift_cobol.py`) e JUnit 4
legacy (`DriftJUnit4.java`). L'installer mette tutto nel tuo account utente.
Non servono diritti di amministratore né la rete, e un solo comando rimuove
tutto ciò che ha installato.

## In breve

| | Ubuntu e altri Linux | macOS (Apple Silicon & Intel) | Windows 10 e 11 |
|---|---|---|---|
| Ricevi | `drift-0.5.0-linux-x64.tar.gz` | `drift-0.5.0-macos-arm64.tar.gz` o `drift-0.5.0-macos-x64.tar.gz` | `drift-0.5.0-windows-x64.zip` |
| Installa | `tar -xzf drift-0.5.0-linux-x64.tar.gz`<br>`./drift-0.5.0-linux-x64/install.sh` | `tar -xzf drift-0.5.0-macos-arm64.tar.gz`<br>`./drift-0.5.0-macos-arm64/install.sh` | Estrai lo zip, doppio clic su `install.cmd` |
| Verifica | `drift version` | `drift version` | `drift version` in un nuovo terminale |
| Rimuovi | `~/.local/share/drift/install.sh --uninstall` | `~/.local/share/drift/install.sh --uninstall` | Impostazioni › App › DRIFT › Disinstalla |

> **Installazione diretta dal repository pubblico GitHub (`rad-ox/drift`):**
> Esegui `./install.sh` su Linux o macOS, oppure `.\install.cmd` su Windows, direttamente dalla radice del repository.

Ricevi l'archivio (e `SHA256SUMS`, se fornito a parte) tramite un canale
attendibile; ogni archivio contiene inoltre uno `SHA256SUMS` interno con i
checksum di tutti i file del pacchetto. Il checksum rileva danni accidentali,
ma non autentica chi ha creato il pacchetto: per verificarne l'autenticità
confronta il valore su un secondo canale attendibile.

## Cosa serve

- **Linux**: Ubuntu 20.04 o successivo, o qualunque Linux x86 a 64 bit (il binario è statico e non richiede librerie).
- **macOS**: macOS 12+ su Apple Silicon (`macos-arm64`) o Intel (`macos-x64`).
- **Windows**: Windows 10 o 11 a 64 bit (`windows-x64`).
- Solo per il bridge JUnit 5 (`drift-junit`): JDK 25 LTS e Maven 3.6.3 o successivo (per i monoliti legacy Java 6–8 / JUnit 4 usa `bridges/legacy/junit4/DriftJUnit4.java`).
- Solo per i bridge JavaScript o Python: Node.js 24 LTS (18+ supportato) o Python 3.14 (3.11+ supportato).
  `drift` da solo non richiede altro.
- Solo per la skill: un agente che legge le skill da `~/.copilot/skills` o
  `~/.agents/skills`, come GitHub Copilot CLI, Claude Code, Codex o Pi.

## Ubuntu e altri Linux

1. Se hai ricevuto `SHA256SUMS` insieme all'archivio, mettili nella stessa
   cartella, apri lì un terminale e verifica l'archivio:

   ```bash
   sha256sum --ignore-missing -c SHA256SUMS
   ```

   Deve comparire `drift-0.5.0-linux-x64.tar.gz: OK`. Qualunque altro esito
   indica un file danneggiato o diverso: fattelo rimandare. (Se hai ricevuto
   solo il `.tar.gz`, il passo 2 verifica lo `SHA256SUMS` interno all'archivio.)
2. Estrai e installa:

   ```bash
   tar -xzf drift-0.5.0-linux-x64.tar.gz
   (cd drift-0.5.0-linux-x64 && sha256sum -c SHA256SUMS)
   ./drift-0.5.0-linux-x64/install.sh
   ```

   Ogni passo stampa `✓`. Una riga con `!` ti dice cosa fare, per esempio
   `~/.local/bin entra nel PATH al prossimo login; in questo terminale
   esegui: . ~/.profile`.
3. Verifica: `drift version` stampa `drift 0.5.0 (schema 0.2, digest dr1, build <id>)`,
   dove `<id>` indica il sorgente da cui è stato costruito il pacchetto.

Dopo puoi cancellare la cartella estratta.

## Windows 10 e 11

1. Se hai ricevuto `SHA256SUMS` insieme allo zip, mettili nella stessa
   cartella, apri PowerShell in quella cartella e verifica il download:

   ```powershell
   (Get-FileHash .\drift-0.5.0-windows-x64.zip).Hash -eq (-split (Select-String windows-x64 .\SHA256SUMS).Line)[0]
   ```

   Deve comparire `True`. (La cartella estratta contiene inoltre uno
   `SHA256SUMS` interno con gli hash di tutti i file del pacchetto.)
2. Clic destro sullo zip, **Estrai tutto…**, poi **Estrai**.
3. Nella cartella estratta fai doppio clic su **`install.cmd`**. Una finestra
   mostra ogni passo e alla fine attende Invio. Da terminale esegui invece
   `.\install.cmd`.
4. Apri un **nuovo** terminale, perché il PATH cambia solo per le nuove
   finestre, ed esegui `drift version`.

L'installer aggiunge `drift` al PATH utente ed elenca DRIFT in Impostazioni ›
App. Dopo puoi cancellare la cartella estratta.

## Cosa va dove

| | Linux | Windows |
|---|---|---|
| Comando | `~/.local/bin/drift` | `%LOCALAPPDATA%\Programs\drift\bin\drift.exe` |
| Guida, esempio, schemi, disinstallazione | `~/.local/share/drift/` | `%LOCALAPPDATA%\Programs\drift\` |
| Bridge JS e Python | `~/.local/share/drift/bridges/drift.mjs`, `drift.py` | `%LOCALAPPDATA%\Programs\drift\bridges\drift.mjs`, `drift.py` |
| Skill dell'agente | `~/.copilot/skills/drift/` (e `~/.agents/skills/` se presente o con `--hooks`) | `%USERPROFILE%\.copilot\skills\drift\` (e `%USERPROFILE%\.agents\skills\`) |
| Hook dell'agente (opt-in) | `~/.pi/agent/extensions/drift.ts`, `~/.copilot/hooks/drift.json`, `~/.codex/hooks.json`, `~/.claude/settings.json` | `%USERPROFILE%\.pi\agent\extensions\drift.ts`, `%USERPROFILE%\.copilot\hooks\drift.json` |
| Bridge JUnit | `~/.m2/repository/drift/drift-junit/0.5.0/` | `%USERPROFILE%\.m2\repository\drift\drift-junit\0.5.0\` |
| Plugin Maven | `~/.m2/repository/drift/drift-maven-plugin/0.5.0/` | `%USERPROFILE%\.m2\repository\drift\drift-maven-plugin\0.5.0\` |
| Impostazioni modificate | nessuna: l'installer stampa solo un suggerimento sul PATH | PATH utente e una voce in Impostazioni › App |

Se `~/.m2/settings.xml` imposta `<localRepository>`, il bridge e il plugin
vanno lì.
I profili della shell non vengono mai modificati.

## Opzioni

| Linux: `install.sh` | Windows: `install.cmd` | Effetto |
|---|---|---|
| `--prefix DIR` | `-Prefix DIR` | installa altrove; su Linux in `DIR/bin` e `DIR/share/drift` |
| `--skills-dir DIR` | `-SkillsDir DIR` | usa un'altra cartella di skill dell'agente |
| `--no-skill` | `-NoSkill` | non installa la skill dell'agente |
| `--hooks` | `-Hooks` | installa gli hook/estensioni automatici per gli agenti rilevati (Pi, Copilot, Claude, Codex, Cursor, Gemini) |
| `--no-hooks` | `-NoHooks` | salta gli hook automatici senza chiedere |
| `--update-check` | `-UpdateCheck` | installa gli hook con il controllo opzionale delle release GitHub |
| `--no-update-check` | `-NoUpdateCheck` | omette o rimuove solo il controllo delle release |
| `--hooks-dir DIR` | `-HooksDir DIR` | installa il file hook automatico in `DIR/drift.json` |
| `--maven-repo DIR` | `-MavenRepo DIR` | usa un altro repository Maven locale |
| `--no-maven` | `-NoMaven` | non installa il bridge JUnit e il plugin Maven |
| | `-NoPath` | non modifica il PATH utente |
| `--dry-run` | `-DryRun` | mostra i passi senza cambiare nulla |
| `--uninstall` | `-Uninstall` | rimuove quanto installato |
| `--lang en` o `--lang it` | `-Lang en` o `-Lang it` | lingua dei messaggi; la predefinita segue il sistema |
| `--help` | `-Help` | elenca tutte le opzioni |

Anche `DRIFT_LANG=it` sceglie l'italiano, e `NO_COLOR=1` disattiva i colori.

Con gli hook abilitati, l'installer chiede separatamente se installare il
controllo delle release (predefinito **Sì**). Senza interazione mantiene una
scelta precedente; alla prima installazione non lo abilita implicitamente.
L'installer resta offline. Il componente selezionato controlla `rad-ox/drift`
all'avvio/ripresa nelle aree DRIFT e segnala soltanto release stabili più
recenti: non scarica né installa aggiornamenti e non blocca la sessione.
`DRIFT_UPDATE_CHECK=0` sospende le richieste. La policy installata in
`hooks/release/release-policy.json` contiene repository e limiti temporali
(2 secondi per la richiesta, 3 complessivi).
Anche l'installazione da sorgente presenta la domanda:
`make install UPDATE_CHECK=0` esclude esplicitamente il componente.
Rifiutarlo lascia operativi gli hook ordinari. Su POSIX serve Python 3;
su Windows viene usata PowerShell nativa.

## Primi passi

L'installer lascia un piccolo esempio accanto a questa guida:

```bash
drift check ~/.local/share/drift/example/.drift                                    # stampa: ok: 3 file(s)
drift review ~/.local/share/drift/example/.drift --brief                           # pacchetto di revisione deterministico
drift show ~/.local/share/drift/example/.drift/contracts/item-get.toml --as json   # vista risolta per i test
drift help
drift explain DR-E601
```

Su Windows l'esempio è in `$env:LOCALAPPDATA\Programs\drift\example\.drift`.
Un agente che legge `~/.copilot/skills` trova la skill `drift` al prossimo
avvio; la skill descrive l'intero flusso di lavoro.

## Progetti Maven e Scala / sbt (bridge JUnit / MUnit e plugin)

Aggiungi la dipendenza di test e il plugin al `pom.xml` del progetto. La skill
installata spiega come marcare i test, in `references/jvm-bridge.md`.

```xml
<dependency>
  <groupId>drift</groupId>
  <artifactId>drift-junit</artifactId>
  <version>0.5.0</version>
  <scope>test</scope>
</dependency>
```

```xml
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
```

Poi un solo comando, uguale su Linux e Windows, esporta i contratti, esegue i
test e interroga il gate:

```bash
mvn verify
```

Nei progetti **Scala 3 / sbt** (ad esempio MUnit `FunSuite`), risolvi
`drift-junit` dal repository Maven locale in `build.sbt`:

```scala
scalaVersion := "3.9.0"
resolvers += Resolver.mavenLocal
libraryDependencies += "drift" % "drift-junit" % "0.5.0" % Test
Test / fork := true
Test / javaOptions ++= Seq(
  s"-Ddrift.resolved=${baseDirectory.value}/target/drift/resolved",
  s"-Ddrift.events=${baseDirectory.value}/target/drift/events"
)
```

Poi esporta le viste, esegui `sbt test` (chiamando `Drift.expect(contract, caseId, level)`
e `c.verify(...)` in ciascun test) e verifica il gate:

```bash
drift show .drift/contracts --as json --out target/drift/resolved
sbt test
drift gate .drift/contracts --events target/drift/events
```

- La build fallisce quando un contratto non è verde e ne stampa il motivo. Un
  test rieseguito sostituisce il suo risultato precedente; `mvn clean verify`
  riparte da zero.
- Il plugin usa il `drift` installato; `-Ddrift.skip` lo disattiva.
- Se la configurazione di surefire imposta un proprio `<argLine>`, includi
  `@{argLine}`.
- La prima build scarica JUnit e i plugin Maven come ogni build Maven, quindi
  richiede la rete o un mirror.

Senza il plugin, su Linux:

```bash
drift show .drift/contracts --as json --out target/drift/resolved
mvn test -Ddrift.resolved="$PWD/target/drift/resolved" -Ddrift.events="$PWD/target/drift/events.jsonl"
drift gate .drift/contracts --events target/drift/events.jsonl
```

Su Windows, in PowerShell:

```powershell
drift show .drift\contracts --as json --out target\drift\resolved
mvn test "-Ddrift.resolved=$PWD\target\drift\resolved" "-Ddrift.events=$PWD\target\drift\events.jsonl"
drift gate .drift\contracts --events target\drift\events.jsonl
```

In PowerShell metti tra virgolette ogni argomento `-D...`: senza virgolette
PowerShell lo spezza al punto.

## Progetti JavaScript e Python (`drift.mjs` e `drift.py`)

L'installer copia i bridge senza dipendenze per JavaScript e Python 3 in
`~/.local/share/drift/bridges/` su Linux e in
`%LOCALAPPDATA%\Programs\drift\bridges\` su Windows (presenti anche in
`bridges/drift.mjs` e `bridges/drift.py` dentro il pacchetto estratto). Copia
il bridge del tuo runtime nella cartella di test del progetto (per esempio
`test/drift.mjs` o `tests/drift.py`), oppure aggiungi la cartella `bridges` a
`NODE_PATH` / `PYTHONPATH`.

In **JavaScript / TypeScript** (`node --test`, Vitest o Jest):

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runDriftCase } from './drift.mjs';

test('returns item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', { status: (v) => assert.equal(res.status, v) });
  });
});
```

Con Vitest o Jest passa `test: 'ItemTest#returns_item'` al posto del contesto
`t` di `node:test`.

In **Python 3** (`pytest` o `python3 -m unittest`):

```python
import drift

def test_found():
    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_found",
        cases=["found"],
        level="http",
        fn=lambda d: d.check(
            "found",
            {"status": lambda v: assert_eq(send(d.when("found", "request")).status, v)},
        ),
    )
```

Esporta le viste risolte, esegui i test e interroga il gate:

```bash
drift show .drift/contracts --as json --out .drift/resolved
DRIFT_RESOLVED=.drift/resolved DRIFT_EVENTS=.drift/events node --test   # oppure npx vitest run, npx jest, pytest
drift gate .drift/contracts --events .drift/events
```

Se `DRIFT_RESOLVED` e `DRIFT_EVENTS` non sono impostate e `drift` è nel `PATH`,
entrambi i bridge risolvono automaticamente `.drift/contracts` (o
`.drift/resolved` / `.drift-work/resolved`) e scrivono gli eventi in
`.drift/events` (o `.drift-work/events`), quindi puoi anche eseguire
direttamente `node --test` o `pytest` e poi `drift gate` dalla radice
dell'area. Usa `drift select --changed <file>... --files` (o `selectFiles` /
`select_files`) per passare a `node --test` o `pytest` i soli file di test
toccati.

| Variabile d'ambiente | Scopo |
|---|---|
| `DRIFT_RESOLVED` | Cartella o file `.json` delle viste esportate (risolte automaticamente da `.drift/` o `.drift-work/resolved` se omessa) |
| `DRIFT_EVENTS` | File o cartella di output per gli eventi `.jsonl` e gli inventari `.meta.json` (predefinita: `.drift/events` o `.drift-work/events`) |
| `DRIFT_CLI` | Percorso dell'eseguibile `drift` usato nell'auto-risoluzione di `.drift/contracts` (se `drift` non è nel `PATH`) |
| `DRIFT_SNAPSHOT` | OID dell'albero Git registrato nei sidecar `.meta.json` per il riuso basato su snapshot |

## Aggiornamento

Esegui l'installer del pacchetto più recente. Sostituisce `drift` e la skill e
aggiunge le nuove versioni del bridge e del plugin. Le versioni precedenti
restano, perché i progetti potrebbero usarle ancora.

## Disinstallazione

- Linux: `~/.local/share/drift/install.sh --uninstall`. Se hai installato con
  `--prefix DIR`, esegui `DIR/share/drift/install.sh --uninstall`.
- Windows: Impostazioni › App › App installate › DRIFT › Disinstalla, oppure
  esegui `%LOCALAPPDATA%\Programs\drift\uninstall.cmd`.

La disinstallazione rimuove esattamente ciò che l'installer ha registrato nel
suo manifest. Contratti e progetti non vengono toccati.

## Problemi comuni

**`drift: command not found` su Linux.** Esegui `. ~/.profile` o rientra
nella sessione. Se non basta, aggiungi a `~/.bashrc` la riga stampata
dall'installer, per esempio `export PATH="$HOME/.local/bin:$PATH"`.

**`drift` non è riconosciuto su Windows.** Apri un nuovo terminale. Un
terminale avviato da una finestra aperta prima dell'installazione mantiene il
vecchio PATH; se serve, esci e rientra nella sessione di Windows. Con
`-NoPath`, chiama `drift.exe` con il percorso completo.

**"L'esecuzione di script è disabilitata nel sistema".** Avvia `install.cmd`,
non `install.ps1`: consente lo script solo per questa esecuzione. Se la tua
organizzazione impone una policy, chiedi all'IT, oppure copia a mano
`bin\drift.exe` in una cartella del PATH e `skill\drift` in
`%USERPROFILE%\.copilot\skills\drift`.

**Windows chiede se eseguire `install.cmd`, o blocca `drift.exe`.** I file non
sono firmati e arrivano da un altro computer. Scegli **Esegui**; per evitare la
domanda, sblocca lo zip prima di estrarlo: clic destro › Proprietà › Annulla
blocco, oppure `Unblock-File .\drift-0.5.0-windows-x64.zip`. Se le regole
aziendali bloccano i programmi in `%LOCALAPPDATA%`, installa con `-Prefix` in
una cartella consentita o chiedi all'IT.

**Maven: `Could not find artifact drift:drift-junit:jar:0.5.0`** (o
`drift-maven-plugin`). Maven usa un repository locale diverso da quello
dell'installer, per esempio tramite `-Dmaven.repo.local` o un file di
impostazioni in un altro posto. Riesegui l'installer con `--maven-repo DIR` o
`-MavenRepo DIR` che punti a quello.

**Maven: "... is drift X, the plugin is Y".** Il `drift` nel PATH e il plugin
hanno versioni diverse. Installa il pacchetto della versione del plugin,
oppure indica al plugin un `drift` della stessa versione con
`-Ddrift.cli=PERCORSO`.

**Caratteri strani nel JSON esportato su Windows.** Esporta con `--out`, o con
il plugin: così `drift` scrive i file da solo. Una vista rediretta con `>`
richiede prima `[Console]::OutputEncoding = [Text.Encoding]::UTF8` in Windows
PowerShell 5.1 e in PowerShell da 7.0 a 7.3. Il bridge legge file UTF-8 e
UTF-16, con o senza byte order mark.

**Fine riga.** I contratti con fine riga Windows (CRLF) danno lo stesso esito
di quelli con LF in check, fmt e approve; `drift fmt` scrive LF.

**Proxy.** Eseguito da un archivio di rilascio estratto, l'installer non usa la rete (eseguito da un `git clone` privo di binari locali, `install.sh` scarica e verifica via SHA-256 il pacchetto della piattaforma da GitHub Releases). Per Maven: configura il suo
proxy in `~/.m2/settings.xml`.

**Quarantena Gatekeeper su macOS.** Se macOS blocca il binario scaricato da un
browser perché non firmato, rimuovi l'attributo di quarantena sulla cartella
estratta prima di eseguire `install.sh`:
`xattr -dr com.apple.quarantine ./drift-0.5.0-macos-*`.
