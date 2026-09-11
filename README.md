# CiteMind

<p align="center">
  <img src="assets/Logo.png" alt="CiteMind">
</p>

**Local bibliography, webography, and academic knowledge manager for Windows.**

CiteMind helps you collect, organize, read, and connect research sources in a local archive. It supports books, articles, theses, web resources, and PDFs, with assisted import, full-text search, relationship graphs, and bibliographic export.

## Main features

* local project archives in SQLite format (`.db`);
* management of bibliographic references, web resources, and theses;
* import from PDF, BibTeX, RIS, CSV, DOI, and URLs;
* metadata retrieval through bibliographic services, with review and editing of imported data;
* linking and reading PDFs associated with sources;
* notes, reading status, annotations, and thematic organization;
* full-text search across the archive;
* knowledge graph and citation/reference DAG;
* local note and summary generation via Ollama, when configured;
* export to DOCX, PDF, BibTeX, and BibLaTeX;
* customizable citation styles;
* multilingual interface and light/dark themes.

## Installation on Windows

1. Download `CiteMind_Setup.exe` from the **Releases** section on GitHub.
2. Run the installer and follow the setup wizard.
3. Launch CiteMind from the Start menu or the shortcut created by the installer.
4. On first launch, choose **New Project** to create an archive or **Open Project** to use an existing `.db` file.

> Windows may display a warning for an application that is not yet recognized by SmartScreen. Make sure the file comes from the official CiteMind release before allowing it to run.

### Data and backups

Project data is stored in the `.db` file selected by the user. To create a backup, simply close CiteMind and copy the file to a safe location. If PDFs are linked by file path, make sure to include the folder containing them in the backup as well.

## Ollama and AI features (optional)

AI-powered summarization and analysis are optional and use Ollama locally:

1. Install Ollama from [ollama.com/download](https://ollama.com/download).
2. Download at least one model, for example `ollama pull gemma4`.
3. Start Ollama if it is not already running.
4. Configure the URL and model in CiteMind's AI settings.

Without Ollama, CiteMind continues to work normally for source management, search, import, reading, and export.

## Running from source

Requirements: Python 3.11 or later and the dependencies listed in `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

To create a Windows executable with PyInstaller:

```powershell
pip install pyinstaller
pyinstaller main.spec
```

The installer distributed to users is built separately from the application build.

## Documentation

* [User Manual](docs/MANUALE.md)
* [CiteMind License](app/licenses/LICENSE_CiteMind.txt)
* [Ollama License](app/licenses/LICENSE_Ollama.txt)

## Project status

CiteMind is under active development. Before using an important archive, keep a backup copy of the `.db` file.

