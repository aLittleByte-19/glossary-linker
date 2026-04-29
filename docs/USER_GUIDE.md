# Glossary Linker - Guida utente

Glossary Linker e un'app locale per aggiungere rimandi al glossario dentro documenti LaTeX. Non modifica i sorgenti appena avvii un'elaborazione: prima prepara risultati intermedi, poi sei tu a scegliere cosa salvare.

## Concetti base

- Glossario: file `.tex` che contiene le voci da linkare.
- Voce: termine del glossario, con ID stabile, termine visibile e definizione.
- Automatico: il termine viene linkato in tutte le occorrenze valide.
- Manuale: ogni occorrenza viene mostrata nella revisione manuale.
- File `.linked.tex`: copia non distruttiva del documento originale con i link inseriti.
- Macro `\glslink{id}{testo}`: macro inserita nei documenti per creare un link leggibile verso l'HTML del glossario generato dal tool.

## Flusso consigliato

- Prepara il glossario se non ha ancora ID stabili.
- Controlla le impostazioni ambiente.
- Controlla le regole editoriali.
- Linka i documenti.
- Rivedi le occorrenze manuali.
- Salva i file prodotti.

## Primo avvio

1. Apri le impostazioni dall'icona in alto a destra.
2. In `Ambiente locale`, controlla la root repo predefinita.
3. Controlla i path di `latexmk`, `pdflatex`, `xelatex` e `lualatex`.
4. Apri `Verifica ambiente`.
5. Se uno strumento risulta `not found`, torna in `Ambiente locale` e scegli il binario corretto.
6. Apri `Regole editoriali` e controlla cosa viene escluso dal linker.

Se non sai quale compilatore scegliere, lascia `latexmk`: di solito gestisce meglio piu passaggi, riferimenti e indice.

## Preparare il glossario

Apri `Formatta glossario .tex` dalla home.

Puoi scegliere un file locale oppure incollare direttamente il contenuto LaTeX. Se scegli un file locale, l'app puo sovrascriverlo alla fine. Se incolli il contenuto, salva come nuovo file.

Scegli il metodo di rilevamento:

- Automatico: usa `\glossaryentry{id}{Termine}` se presente, altrimenti prova con `\subsection{Termine}`.
- Macro strutturata: legge solo `\glossaryentry{id}{Termine}`.
- Sezioni: legge solo `\subsection{Termine}`.

Premi `Rileva e genera anteprima`. Controlla la tabella delle voci rilevate:

- lascia selezionate le voci reali;
- togli la spunta alle righe rilevate per errore;
- correggi la definizione se serve;
- aggiungi alias separati da virgola.

Alla fine scegli:

- nuovo file `.tex`;
- sovrascrittura del file sorgente;
- salvataggio e compilazione PDF, se vuoi produrre anche il PDF del glossario.

Quando una voce viene rilevata per errore, togli la spunta `Incluso`. Questo evita che finisca nella lista usata dal linker. Se una definizione e sbagliata o troppo sporca, correggila nel campo della tabella prima di salvare.

Il formato consigliato per il futuro e:

```tex
\providecommand{\glossaryentry}[2]{\subsection{#2}\hypertarget{gls:#1}{}\label{gls:#1}}
\glossaryentry{id-stabile}{Termine visibile}
Definizione della voce.
```

L'ID deve essere stabile: se lo cambi, cambiano anche gli anchor usati dai link nei documenti. L'HTML generato dal tool crea una sezione con `id="gls-id"` per ogni voce rilevata.

## Linkare documenti

Apri `Linka documenti`.

Nella pagina `Glossario e Regole` imposta:

- root progetto;
- path del glossario `.tex`;
- URL usato nei documenti per aprire il glossario HTML.

Il parsing `.tex -> .html` e obbligatorio: quando aggiorni le voci o avvii
l'elaborazione, il tool parsa il glossario, salva la lista locale delle entry e
genera l'HTML con una sezione per ogni voce. I link inseriti nei documenti
puntano sempre a `URL#gls-id`.

Per lavorare in locale lascia `http://127.0.0.1:8765/glossary-html`: il link
apre la pagina HTML servita dall'app mentre il server e in esecuzione. Per Pages
usa l'URL remoto dello stesso HTML generato dal tool, per esempio
`https://nome-org.github.io/.../Glossario.html`.

Seleziona i documenti manualmente o scansiona una cartella. I file dentro la root vengono mostrati come path relativi.

Quando usare `Linka documenti`:

- vuoi processare uno o pochi file scelti a mano;
- vuoi controllare un documento specifico;
- vuoi generare copie `.linked.tex` senza toccare gli originali.

Quando usare `Aggiorna per nuove voci glossario`:

- hai aggiunto nuove voci al glossario;
- vuoi scansionare la documentazione esistente;
- vuoi applicare solo alcuni ID nuovi.

## Revisione manuale

Le voci in modalita Manuale aprono una schermata occorrenza per occorrenza. Per ogni occorrenza vedi:

- termine;
- definizione;
- file;
- riga;
- sezione;
- contesto con parola evidenziata.

Puoi linkare o saltare la singola occorrenza, oppure applicare scelte piu ampie al file o al termine.

## Output

Nella schermata finale puoi salvare tutti i file:

- come `.linked.tex`;
- sovrascrivendo i `.tex` originali.

Il report e opzionale. Puoi generarlo in Markdown o JSON.

Usa `.linked.tex` quando vuoi controllare il risultato prima di sostituire il documento. Usa la sovrascrittura solo quando hai gia verificato che i link inseriti sono corretti.

## Impostazioni

La sezione `Ambiente locale` contiene solo impostazioni del tuo computer:

- root repo predefinita;
- binari LaTeX;
- compilatore preferito;
- timeout;
- cartella temporanea;
- pulizia dei file temporanei di compilazione;
- porta locale;
- browser preferito.

La sezione `Regole editoriali` contiene le regole condivise:

- pattern file esclusi;
- ambienti LaTeX ignorati;
- comandi ignorati;
- frontespizio, indice, titoli e didascalie.

La sezione `Verifica ambiente` controlla se i binari configurati sono raggiungibili.

## Documenti di prova

Per ripristinare le fixture dentro `vendor/` senza cancellare gli ZIP:

```bash
scripts/reset_test_documents.py
```

Su Windows:

```powershell
.\.venv\Scripts\python.exe scripts\reset_test_documents.py
```

Lo script rimuove e riestrae `vendor/documentazione-source` e
`vendor/documentazione-glossario` dagli ZIP omonimi senza modificare i file
estratti. Se il glossario originale non crea ancora `\hypertarget{gls:id}{}`,
usa `Formatta glossario .tex`: la normalizzazione deve essere generata dal tool,
non dallo script di reset. Lo stesso salvataggio produce anche `Glossario.html`
con anchor per ogni entry.

Per eliminare solo gli artifact di compilazione LaTeX:

```bash
scripts/clean_latex_artifacts.py .
```

## Note importanti

- L'app non installa TeX Live o MiKTeX.
- L'app non corregge asset mancanti nei documenti.
- L'app non garantisce correttezza semantica automatica: usa la revisione manuale per termini ambigui.
- I link al glossario puntano all'HTML generato dal tool. Assicurati che l'URL configurato sia raggiungibile e che l'HTML sia stato rigenerato dopo ogni modifica al glossario `.tex`.
- Prima di sovrascrivere sorgenti importanti, controlla sempre i risultati.

## Problemi comuni

### Il glossario rileva una voce strana

Apri `Formatta glossario .tex`, scegli un metodo di rilevamento piu esplicito e rigenera l'anteprima. Se la voce compare ancora, togli la spunta `Incluso` prima del salvataggio.

### La compilazione PDF fallisce

Controlla il log mostrato dall'app. Gli errori piu comuni sono:

- binario LaTeX non trovato;
- pacchetto LaTeX mancante;
- immagine o file incluso non presente;
- documento che compila solo dalla root del progetto originale.

Glossary Linker mostra il log, ma non modifica asset o path del progetto.

### Il link apre il glossario ma non arriva alla voce giusta

Rigenera le voci dal glossario `.tex` e controlla che l'HTML contenga un elemento con `id="gls-id"` per la voce interessata. In locale verifica che l'app sia aperta su `http://127.0.0.1:8765`; in remoto verifica che l'HTML pubblicato su Pages sia aggiornato.

### Non so se un termine deve essere automatico o manuale

Usa `Manuale` per parole corte, comuni o ambigue. Usa `Automatico` per termini tecnici chiari e poco ambigui.
