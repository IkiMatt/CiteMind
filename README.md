# CiteMind

**Gestore locale di bibliografie, sitografie e conoscenza accademica per Windows.**

CiteMind aiuta a raccogliere, organizzare, leggere e collegare le fonti di una ricerca in un archivio locale. Supporta libri, articoli, tesi, risorse web e PDF, con importazione assistita, ricerca full-text, grafi delle relazioni ed esportazione bibliografica.

## Funzionalita principali

- archivi di progetto locali in formato SQLite (`.db`);
- inserimento di bibliografia, sitografia e tesi;
- importazione da PDF, BibTeX, RIS, CSV, DOI e URL;
- recupero dei metadati tramite servizi bibliografici e revisione dei dati importati;
- collegamento e lettura dei PDF associati alle fonti;
- note, stato di lettura, annotazioni e organizzazione tematica;
- ricerca full-text nell'archivio;
- grafo della conoscenza e DAG delle citazioni/riferimenti;
- generazione di note e sintesi locali tramite Ollama, quando configurato;
- esportazione in DOCX, PDF, BibTeX e BibLaTeX;
- stili citazionali personalizzabili;
- interfaccia in piu lingue e tema chiaro/scuro.

## Installazione su Windows

1. Scarica `CiteMind_Setup.exe` dalla sezione **Releases** di GitHub.
2. Avvia l'installer e segui la procedura guidata.
3. Avvia CiteMind dal menu Start o dal collegamento creato dall'installer.
4. Al primo avvio scegli **Nuovo progetto** per creare un archivio oppure **Apri progetto** per usare un file `.db` esistente.

> Windows potrebbe mostrare un avviso per un'applicazione non ancora riconosciuta da SmartScreen. Verifica che il file provenga dalla release ufficiale di CiteMind prima di autorizzarne l'esecuzione.

### Dati e backup

I dati del progetto sono contenuti nel file `.db` scelto dall'utente. Per eseguire un backup è sufficiente chiudere CiteMind e copiare il file in una posizione sicura. Se i PDF sono collegati tramite percorso, includi nel backup anche la cartella che li contiene.

## Ollama e funzioni AI (opzionale)

Le funzioni di sintesi e analisi AI sono opzionali e usano Ollama in locale:

1. Installa Ollama da [ollama.com/download](https://ollama.com/download).
2. Scarica almeno un modello, ad esempio `ollama pull gemma4`.
3. Avvia Ollama, se non è già attivo.
4. Configura URL e modello nelle impostazioni AI di CiteMind.

Senza Ollama CiteMind continua a funzionare per gestione, ricerca, importazione, lettura ed esportazione delle fonti.

## Avvio da sorgente

Requisiti: Python 3.11 o superiore e le dipendenze elencate in `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Per creare un eseguibile Windows con PyInstaller:

```powershell
pip install pyinstaller
pyinstaller main.spec
```

L'installer distribuito agli utenti viene prodotto separatamente a partire dal build dell'applicazione.

## Documentazione

- [Manuale utente](docs/MANUALE.md)
- [Licenza CiteMind](app/licenses/LICENSE_CiteMind.txt)
- [Licenza Ollama](app/licenses/LICENSE_Ollama.txt)

## Stato del progetto

CiteMind è in sviluppo attivo. Prima di usare un archivio importante, mantieni una copia di backup del file `.db`.
