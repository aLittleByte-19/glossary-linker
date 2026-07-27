# Glossary Linker - Guida utente

Glossary Linker collega documenti LaTeX alla pagina pubblica del glossario, mantenendo controllo editoriale sulle occorrenze ambigue. L'app lavora in locale, esporta un unico JSON per l'app Angular di Documentazione, salva lo stato del job su disco e non modifica i sorgenti finché non scegli esplicitamente cosa salvare nella schermata finale.

## Prima configurazione

Apri le impostazioni dall'icona in alto a destra e controlla ambiente locale, root del progetto, porta del server e strumenti LaTeX. Le impostazioni personali restano in `glossary-linker.local.yml`, inclusi:

- `glossary_path`, il sorgente LaTeX;
- `glossary_json_path`, il file JSON del glossario generato.

Le regole editoriali condivise e l'URL pubblico stanno in `glossary-linker.yml`. Le voci rilevate e revisionate sono salvate nello stato locale `.glossary-linker/entries.yml`; nessuno di questi file locali viene tracciato da Git.

## Preparare ed esportare il glossario

1. Dalla home seleziona `Esporta glossario JSON` e premi `Continua`.
2. Nel passo `Input glossario` indica il file `.tex` e il file JSON da generare. Se incolli anche del contenuto LaTeX, il testo incollato ha la precedenza sul file.
3. Nel passo `Rilevamento entry` scegli `Auto`, `\subsection{Termine}` oppure un comando specifico nel formato `\comando{Termine}`, quindi premi `Rileva voci`.
4. Nel passo `Revisione voci rilevate` escludi i falsi positivi, correggi le definizioni e aggiungi gli alias separati da virgola.
5. Controlla ancora il percorso mostrato nel passo `Esportazione JSON` e premi `Salva JSON revisionato`.

Il salvataggio applica inclusioni, definizioni e alias presenti nel form, aggiorna lo stato locale delle voci e scrive atomicamente il JSON nel percorso indicato. Il sorgente `.tex` non viene modificato. Ogni voce conserva l'ID corrente; Documentazione costruisce il relativo anchor pubblico aggiungendo il prefisso `gls-`.

`Scarica JSON dal sorgente` non equivale al salvataggio revisionato: rilegge il `.tex` configurato e scarica la conversione diretta, senza inviare eventuali modifiche del form non ancora salvate. Usalo soltanto quando vuoi il contenuto derivato direttamente dal sorgente; per il JSON editoriale definitivo usa `Salva JSON revisionato`.

Frammento reale prodotto dal glossario di Documentazione:

```json
{
  "id": "soglia-di-confidenza",
  "term": "Soglia di Confidenza",
  "definition": "Valore limite per l'intervento manuale (es. 80%).",
  "aliases": []
}
```

Le versioni precedenti salvavano le voci in `glossary-linker.entries.yml`: al primo avvio il tool importa automaticamente quel file nel nuovo stato locale, se presente.

Esempio minimo:

```tex
\subsection{Accuratezza}
Metrica che misura quanto una previsione è corretta.
```

## Linkare documenti

L'operazione `Linka documenti` guida il processo in più step: scelta dei file, regole, glossario, revisione manuale e output. Puoi selezionare singoli `.tex` oppure scansionare una cartella dentro la root del progetto.

![Selezione dei documenti](screenshots/02-documenti.png)

Nel passo Glossario controlli l'URL pubblico, le definizioni, gli alias e la modalità delle voci. Le voci automatiche vengono linkate nelle occorrenze valide; le voci manuali entrano nella revisione occorrenza per occorrenza.

Configura l'URL pubblico:

```text
https://alittlebyte-19.github.io/Documentazione/glossario.html
```

I link prodotti hanno la forma `https://alittlebyte-19.github.io/Documentazione/glossario.html#gls-id`. L'URL non viene copiato nel JSON.

Quando un job è già partito, la rilevazione automatico/manuale resta bloccata nello snapshot corrente. Puoi correggere il glossario per i processi futuri, ma per cambiare quelle modalità nel job in corso devi chiuderlo e ripartire.

## Revisione manuale

La revisione mostra una occorrenza alla volta: termine o alias rilevato, definizione, file, riga, sezione e contesto con parola evidenziata.

![Processo di revisione manuale](screenshots/04-revisione.png)

`Collega` e `Salta` salvano la scelta e avanzano all'occorrenza successiva. Le azioni estese applicano la stessa decisione al termine corrente, al file corrente o a tutte le occorrenze compatibili.

## Output dei documenti

La schermata finale genera i documenti elaborati e il report. Il salvataggio standard produce file `.linked.tex`, utili per controllare il risultato senza toccare gli originali. La sovrascrittura dei sorgenti è disponibile solo come scelta esplicita.

![Report finale e opzioni di salvataggio](screenshots/05-output.png)

Il report può essere salvato in Markdown o JSON. Non è il JSON del glossario: descrive soltanto l'esecuzione sui documenti.

## Contratto JSON

Il file del glossario contiene soltanto `title` ed `entries`; ogni voce contiene soltanto `id`, `term`, `definition` e `aliases`. L'output è UTF-8, deterministico, leggibile e termina con newline.

Termini e definizioni vuoti, ID non validi o duplicati, termini duplicati e markup HTML interrompono l'esportazione senza lasciare file parziali. Gli alias vengono ripuliti e deduplicati.

Imposta il percorso direttamente destinabile a Documentazione:

```yaml
glossary_json_path: /percorso/Documentazione/.github/site-src/glossary.json
```

La CLI genera direttamente il file senza aprire l'interfaccia:

```bash
.venv/bin/glossary-linker-cli \
  --config glossary-linker.yml \
  --glossary /percorso/Glossario.tex \
  --glossary-json /percorso/glossary.json
```

Se `glossary_json_path` punta a `.github/site-src/glossary.json`, Glossary Linker aggiorna quel file nel repository Documentazione ma non costruisce né pubblica l'app Angular. Dopo l'esportazione controlla la modifica, esegui il normale build o l'anteprima di Documentazione e pubblica il sito con il relativo flusso di rilascio.

Le vecchie configurazioni `glossary_html_path` vengono migrate automaticamente allo stesso nome con estensione `.json`, con un messaggio di deprecazione. Il tool non mantiene route o renderer HTML.

## Problemi comuni

Se il glossario rileva voci sbagliate, cambia metodo di parsing o indica il comando LaTeX corretto. Se una voce è comunque un falso positivo, escludila prima del salvataggio.

Se la compilazione PDF fallisce, controlla il log: di solito il problema è un binario LaTeX non trovato, un pacchetto mancante, un asset assente o un documento che compila solo dalla root originale.

Se un link apre il glossario ma non arriva alla voce giusta, verifica che il JSON pubblicato contenga l'ID atteso e che l'app Angular esponga l'elemento `id="gls-id"`. Rigenera il JSON e ricostruisci Documentazione.

Se non sai se una voce deve essere automatica o manuale, usa Manuale per parole corte, comuni o ambigue. Usa Automatico per termini tecnici chiari e poco ambigui.
