# glossary-linker

Applicazione locale per collegare documenti LaTeX alle voci di un glossario
pubblicato come HTML generato dal tool, con revisione manuale per i termini ambigui.

## Stato

Prima versione funzionale:

- core Python indipendente dalla GUI;
- wizard web locale con Flask;
- configurazione editoriale condivisa in `glossary-linker.yml`;
- configurazione personale non versionata in `glossary-linker.local.yml`;
- parser glossario `auto`, `\subsection{Termine}` o comando personalizzato `\comando{Termine}`;
- formattatore per caricare/incollare un glossario `.tex` e generare l'HTML;
- generatore HTML del glossario con anchor stabili per ogni voce;
- linking conservativo con macro `\glslink{id}{testo visibile}`;
- revisione manuale occorrenza per occorrenza;
- report finale in Markdown o JSON;
- compilazione PDF tramite LaTeX installato localmente, quando serve produrre i documenti finali.

## Installazione locale

Modo rapido su macOS/Linux:

```bash
scripts/install.sh
```

Modo rapido su Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Gli script creano `.venv`, installano l'app in modo editabile e preparano
`glossary-linker.local.yml` se non esiste. Per installare anche pytest:

```bash
scripts/install.sh --dev
```

oppure:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev
```

Installazione manuale equivalente:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp glossary-linker.local.example.yml glossary-linker.local.yml
```

## Avvio wizard

Se hai usato lo script rapido:

```bash
.venv/bin/glossary-linker
```

su Windows:

```powershell
.\.venv\Scripts\glossary-linker.exe
```

Se invece hai attivato manualmente la virtualenv:

```bash
glossary-linker
```

Poi apri `http://127.0.0.1:8765`.

La porta si configura in `glossary-linker.local.yml`.

I campi che richiedono file, cartelle o binari possono essere compilati a mano
oppure tramite il pulsante `Scegli`, che apre la finestra nativa del filesystem.
Se il sistema non consente finestre native dal processo locale, il campo rimane
comunque editabile manualmente.

## Flusso principale

Le operazioni principali sono indipendenti:

- `Linka documenti`: scegli uno o più `.tex`, genera copie `.linked.tex` e rivedi le occorrenze manuali.
- `Aggiorna per nuove voci`: scansiona la documentazione e applica solo gli ID nuovi o indicati.
- `Formatta glossario .tex`: normalizza il glossario con ID stabili e genera il glossario HTML.

In ogni caso i sorgenti vengono sovrascritti solo su conferma esplicita.

## Formato glossario

Il parser operativo puo lavorare in tre modi:

- `auto`: prova a riconoscere il comando LaTeX che produce la lista piu lunga e coerente di voci;
- `subsection`: legge le voci introdotte da `\subsection{Termine}`;
- `custom`: legge un comando indicato dall'utente nel formato `\comando{Termine}`.

```tex
\subsection{Accuratezza}
Misura quanto una previsione e corretta.
```

Il wizard include una sezione `Formatta glossario .tex`: il sorgente non viene
sovrascritto e l'output principale e il glossario HTML con anchor `gls-id`.

## Formato link nei documenti

I documenti non ricevono `\href{...}{...}` sparsi nel testo. L'app inserisce:

```tex
\glslink{id}{testo visibile}
```

e aggiunge nel preambolo, se manca, una definizione basata su
`glossary_html_url` e `html_anchor_format` in `glossary-linker.yml`.
La resa visiva predefinita sottolinea leggermente la parola linkata e aggiunge
una `G` ad apice.

La destinazione supportata e il glossario HTML generato dal tool. Il path
locale serve all'app per esporre esattamente il file appena generato:

```yaml
glossary_html_url: http://127.0.0.1:8765/glossary-html
glossary_html_path: Glossario.html
html_anchor_format: "#gls-{id}"
```

Durante i test locali lascia l'URL dell'app: il browser apre
`http://127.0.0.1:8765/glossary-html#gls-id` mentre il server Flask e in
esecuzione e `/glossary-html` legge il file indicato da `glossary_html_path`.
Per il deploy sostituisci `glossary_html_url` con l'URL GitHub Pages dello
stesso HTML generato dal tool, per esempio
`https://nome-org.github.io/.../Glossario.html#gls-id`.

## CLI minima

```bash
glossary-linker-cli examples/documento.tex --config glossary-linker.yml
```

La CLI usa lo stesso core della GUI ed e pensata come base per automazioni
future.

## Script utili

```bash
scripts/clean_latex_artifacts.py .
```

Elimina gli artifact temporanei LaTeX sotto la directory indicata.

## Note di sicurezza editoriale

L'app non modifica mai direttamente i sorgenti senza conferma. Produce prima
file `.linked.tex`, evita il preambolo, link gia esistenti, URL, ambienti
verbatim/listing/minted e comandi configurati. Il linking automatico non
pretende correttezza semantica totale: i termini in modalita Manuale servono
proprio a gestire ambiguita e contesto.
