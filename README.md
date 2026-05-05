# Glossary Linker

![Home dell'applicazione](docs/screenshots/01-operazione.png)

Glossary Linker è un'app locale per aggiungere link controllati al glossario dentro documenti LaTeX. Genera un glossario HTML con anchor stabili, inserisce nei documenti la macro `\glslink{id}{testo visibile}` e lascia all'utente la revisione dei termini ambigui.

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

Per installare anche gli strumenti di test usa `--dev` su macOS/Linux o `-Dev` su PowerShell. Gli script creano la virtualenv, installano il pacchetto in modo editabile e preparano i file locali necessari se mancano.

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

1. **Linkare documenti**: Scansiona i sorgenti e inserisce i link al glossario.
2. **Aggiornamento**: Aggiorna documenti già linkati con nuove voci aggiunte al glossario.
3. **Formattazione**: Trasforma un glossario `.tex` (basato su `\subsection` o comandi custom) in un HTML navigabile.

### Revisione Editoriale
Il cuore del tool è la revisione manuale: per ogni termine ambiguo o marcato come "manuale", l'app mostra il contesto esatto nel sorgente LaTeX per permetterti di decidere se inserire il link o saltarlo.

![Revisione delle occorrenze](docs/screenshots/04-revisione.png)
*Esempio di revisione manuale: l'utente decide se inserire il link in base al contesto.*

### Glossario HTML
I link inseriti puntano a un glossario HTML moderno, ricercabile e pronto per la pubblicazione.

![Glossario HTML generato](docs/screenshots/06-glossary-html.png)
*Il glossario HTML finale con ricerca e navigazione rapida.*

## Configurazione

Il comportamento del linker è guidato da `glossary-linker.yml`:

```yaml
glossary_html_url: http://127.0.0.1:8765/glossary-html
glossary_html_path: Glossario.html
html_anchor_format: "#gls-{id}"
```

In locale conviene lasciare l'URL dell'app. Per la pubblicazione sostituisci `glossary_html_url` con l'URL remoto dello stesso HTML generato.

## Documentazione

La guida completa è in [docs/USER_GUIDE.md](docs/USER_GUIDE.md). Lì trovi il flusso consigliato, le regole editoriali, la revisione manuale, l'output e la risoluzione dei problemi comuni.

## CLI

La CLI usa lo stesso core della GUI:

```bash
glossary-linker-cli examples/documento.tex --config glossary-linker.yml
```

È pensata soprattutto per automazioni future; il wizard web resta il percorso principale.

## Test

Con le dipendenze dev installate:

```bash
pytest -q
```

Per eliminare artifact temporanei LaTeX da una directory:

```bash
scripts/clean_latex_artifacts.py .
```
