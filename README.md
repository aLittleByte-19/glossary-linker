# glossary-linker

Applicazione locale per collegare documenti LaTeX alle voci di un glossario
pubblicato come HTML generato dal tool, con revisione manuale per i termini ambigui.

## Stato

Prima versione funzionale:

- core Python indipendente dalla GUI;
- wizard web locale con Flask;
- configurazione editoriale condivisa in `glossary-linker.yml`;
- configurazione personale non versionata in `glossary-linker.local.yml`;
- parser glossario per `\subsection{Termine}`, `\glossaryentry{id}{Termine}` e glossari misti;
- formattatore per caricare/incollare un glossario `.tex` e normalizzarlo;
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

Il parser legge sia il formato attuale:

```tex
\subsection{Accuratezza}
Misura quanto una previsione e corretta.
```

sia il formato strutturato:

```tex
\glossaryentry{accuratezza}{Accuratezza}
Misura quanto una previsione e corretta.
```

Il wizard include una sezione "Inserisci o formatta glossario .tex" che converte
le `\subsection{...}` in `\glossaryentry{id}{...}`. Il parsing del `.tex` e
obbligatorio: lo stesso risultato viene usato per salvare il glossario HTML con
anchor `gls-id`.

```tex
\providecommand{\glossaryentry}[2]{\subsection{#2}\hypertarget{gls:#1}{}\label{gls:#1}}
```

## Formato link nei documenti

I documenti non ricevono `\href{...}{...}` sparsi nel testo. L'app inserisce:

```tex
\glslink{id}{testo visibile}
```

e aggiunge nel preambolo, se manca, una definizione basata su
`glossary_html_url` e `html_anchor_format` in `glossary-linker.yml`.
La resa visiva predefinita sottolinea leggermente la parola linkata e aggiunge
una `G` ad apice.

La destinazione supportata e il glossario HTML generato dal tool:

```yaml
glossary_link_target: html
glossary_html_url: http://127.0.0.1:8765/glossary-html
html_anchor_format: "#gls-{id}"
```

Durante i test locali lascia l'URL dell'app: il browser apre
`http://127.0.0.1:8765/glossary-html#gls-id` mentre il server Flask e in
esecuzione. Per il deploy sostituisci `glossary_html_url` con l'URL GitHub Pages
dello stesso HTML generato dal tool, per esempio
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
scripts/reset_test_documents.py
```

Il primo elimina gli artifact temporanei LaTeX sotto la directory indicata. Il
secondo rimpiazza le cartelle `vendor/documentazione-source` e
`vendor/documentazione-glossario` estraendole dagli ZIP omonimi, lasciando gli
ZIP al loro posto. I file estratti restano identici agli originali: la macro con
`\hypertarget{gls:#1}{}` deve essere prodotta dal tool quando formatti il
glossario, non dallo script di reset.

`scripts/refresh_vendor_fixtures.py` resta disponibile come alias compatibile
del reset.

## Note di sicurezza editoriale

L'app non modifica mai direttamente i sorgenti senza conferma. Produce prima
file `.linked.tex`, evita il preambolo, link gia esistenti, URL, ambienti
verbatim/listing/minted e comandi configurati. Il linking automatico non
pretende correttezza semantica totale: i termini in modalita Manuale servono
proprio a gestire ambiguita e contesto.

## Fixture locali

Per provare l'app su repository esterni senza modificarli, scarica archive ZIP
o copia directory prive di `.git` sotto `vendor/`. La directory `vendor/` e
ignorata da git.

I test dedicati alle fixture verificano che il tool sappia parsare il glossario
originale, generare l'HTML con anchor per ogni entry, linkare i documenti
forniti verso quell'HTML e applicare nuove entry a documenti gia linkati.
