# glossary-linker

Applicazione locale per collegare documenti LaTeX alle voci di un glossario
pubblicato come PDF, con revisione manuale per i termini ambigui.

## Stato

Prima versione funzionale:

- core Python indipendente dalla GUI;
- wizard web locale con Flask;
- configurazione editoriale condivisa in `glossary-linker.yml`;
- configurazione personale non versionata in `glossary-linker.local.yml`;
- parser glossario per `\subsection{Termine}` e `\glossaryentry{id}{Termine}`;
- formattatore per caricare/incollare un glossario `.tex` e normalizzarlo;
- linking conservativo con macro `\glslink{id}{testo visibile}`;
- revisione manuale occorrenza per occorrenza;
- report finale in Markdown o JSON;
- compilazione PDF tramite LaTeX installato localmente.

## Installazione locale

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp glossary-linker.local.example.yml glossary-linker.local.yml
```

## Avvio wizard

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

1. Scegli l'operazione.
2. Indica glossario, URL finale di `Glossario.pdf` e documenti da processare.
3. Carica o incolla un glossario `.tex` se deve essere formattato.
4. Controlla la preview delle voci e imposta ogni voce su Automatico o Manuale.
5. Revisiona le occorrenze manuali.
6. Salva gli output `.linked.tex`, sovrascrivi solo su conferma o compila PDF.

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
le `\subsection{...}` in `\glossaryentry{id}{...}` e aggiunge la macro:

```tex
\providecommand{\glossaryentry}[2]{\subsection{#2}\label{gls:#1}}
```

## Formato link nei documenti

I documenti non ricevono `\href{...}{...}` sparsi nel testo. L'app inserisce:

```tex
\glslink{id}{testo visibile}
```

e aggiunge nel preambolo, se manca, una definizione basata su
`glossary_pdf_url` e `anchor_format` in `glossary-linker.yml`.

## CLI minima

```bash
glossary-linker-cli examples/documento.tex --config glossary-linker.yml
```

La CLI usa lo stesso core della GUI ed e pensata come base per automazioni
future.

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
