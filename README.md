# Glossary Linker

Estratto reale di una voce generata da `Glossario.tex`:

```json
{
  "id": "soglia-di-confidenza",
  "term": "Soglia di Confidenza",
  "definition": "Valore limite per l'intervento manuale (es. 80%).",
  "aliases": []
}
```

Glossary Linker è un'app locale per aggiungere link controllati al glossario dentro documenti LaTeX. Esporta i dati in un unico JSON UTF-8, inserisce nei documenti la macro `\glslink{id}{testo visibile}` e lascia all'utente la revisione dei termini ambigui. La pagina pubblica viene generata esclusivamente dall'app Angular di Documentazione.

Il flusso è pensato per non toccare subito i sorgenti: l'app produce prima file `.linked.tex` e solo nella schermata finale permette di salvare o sovrascrivere.

## Installazione

Su macOS/Linux:

```bash
scripts/install.sh
```

Su Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Per installare anche gli strumenti di test usa `--dev` su macOS/Linux o `-Dev` su PowerShell. Gli script creano la virtualenv e installano il pacchetto in modo editabile.

## Avvio

Su macOS/Linux:

```bash
.venv/bin/glossary-linker
```

Su Windows:

```powershell
.\.venv\Scripts\glossary-linker.exe
```

Poi apri `http://127.0.0.1:8765`. La porta e le preferenze del computer stanno in `glossary-linker.local.yml`, che non va versionato.

## Funzionalità principali

L'app copre tre operazioni fondamentali per la gestione di un progetto LaTeX:

1. **Linkare documenti**: scansiona i sorgenti e inserisce i link alla pagina pubblica del glossario.
2. **Aggiornamento**: aggiorna documenti già linkati con nuove voci aggiunte al glossario.
3. **Esportazione**: trasforma un glossario `.tex` basato su `\subsection` o comandi custom nel JSON consumato da Documentazione.

### Revisione editoriale

Per ogni termine ambiguo o marcato come manuale, l'app mostra il contesto esatto nel sorgente LaTeX per permettere di decidere se inserire il link o saltarlo.

![Revisione delle occorrenze](docs/screenshots/04-revisione.png)

### File JSON prodotto

Il solo file del glossario prodotto è `glossary.json`, con contratto deterministico. Il documento contiene `title` e l'array `entries`; ogni voce ha esclusivamente i campi `id`, `term`, `definition` e `aliases`, come nell'estratto reale sopra.

Il file può sostituire direttamente `.github/site-src/glossary.json` nel repository Documentazione. Gli anchor pubblici rimangono `gls-{id}` e l'URL non viene inserito nel JSON.

### Esportazione dall'interfaccia

1. Dalla home seleziona `Esporta glossario JSON`.
2. Indica il sorgente `.tex` e il percorso del JSON da generare.
3. Seleziona il metodo di rilevamento e usa `Rileva voci`.
4. Controlla inclusioni, definizioni e alias.
5. Usa `Salva JSON revisionato` per applicare i valori del form e scrivere il file nel percorso mostrato.

`Scarica JSON dal sorgente` è un'operazione diversa: rilegge il `.tex` configurato e scarica la conversione diretta, senza includere modifiche del form non ancora salvate. Per produrre il JSON editoriale definitivo usa `Salva JSON revisionato`.

Se il percorso punta a `.github/site-src/glossary.json` nel repository Documentazione, il file sorgente del sito viene aggiornato immediatamente. Glossary Linker non esegue però il build Angular e non pubblica il sito: verifica la modifica, ricostruisci Documentazione e pubblicala con il suo normale flusso di rilascio.

## Configurazione

`glossary-linker.yml` contiene l'URL pubblico usato nei documenti e le regole condivise:

```yaml
glossary_html_url: https://alittlebyte-19.github.io/Documentazione/glossario.html
html_anchor_format: "#gls-{id}"
```

I percorsi dipendenti dalla macchina vengono salvati in `glossary-linker.local.yml`, che non è tracciato da Git:

```yaml
glossary_path: /percorso/Glossario.tex
glossary_json_path: /percorso/Documentazione/.github/site-src/glossary.json
```

`glossary_html_url` è solo l'URL pubblico usato nei documenti linkati; `glossary_json_path` è solo il percorso locale di output. Le voci revisionate si trovano nello stato locale `.glossary-linker/entries.yml`.

Le configurazioni precedenti con `glossary_html_path` vengono migrate in modo esplicito allo stesso percorso con estensione `.json` e producono un avviso di deprecazione. Nessun HTML viene generato.

## CLI

La CLI usa lo stesso serializzatore della GUI. Per generare soltanto il JSON:

```bash
.venv/bin/glossary-linker-cli \
  --config glossary-linker.yml \
  --glossary examples/glossario.tex \
  --glossary-json glossary.json
```

Per linkare anche documenti, aggiungili come argomenti posizionali. Senza `--glossary-json`, il percorso viene letto da `glossary_json_path` nella configurazione locale.

## Documentazione

La guida completa è in [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Test

Con le dipendenze dev installate:

```bash
.venv/bin/pytest -q
```

Per eliminare artifact temporanei LaTeX da una directory:

```bash
scripts/clean_latex_artifacts.py .
```
