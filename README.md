# Universal Document Processor

A fast, unified document processing and multi-format conversion engine for converting documents, images, web pages, and academic papers into clean **Markdown (`.md`)**, **Plain Text (`.txt`)**, and **Structured JSON (`.json`)**.

---

## Supported Formats

### Supported Output Formats:
* **OUTPUT:-** `.md` (Markdown with YAML Frontmatter), `.txt` (Plain Text), `.json` (Structured IR Document & Semantic RAG Chunks), `all` (Generates all formats simultaneously)

### Supported Input Formats:
* **HTML:-** `.html`, `.htm`, `.xhtml`, `.mhtml`, `.mht`, Live URLs (`http://`, `https://`)
* **IMAGES:-** `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.webp`, `.gif`, `.jfif`, `.jif`, `.jpe`, `.ico`, `.svg`, `.avif`, `.heic`, `.heif`
* **WORD:-** `.docx`, `.doc`, `.docm`, `.dotx`, `.dotm`, `.rtf`, `.odt`, `.dot`
* **EXCEL:-** `.xlsx`, `.xls`, `.xlsm`, `.xltx`, `.xltm`, `.xlsb`, `.ods`
* **POWERPOINT:-** `.pptx`, `.ppt`, `.pptm`, `.ppsx`, `.ppsm`, `.potx`, `.potm`, `.odp`
* **PDF:-** `.pdf` (Native Digital PDF, Scanned / Image OCR, Hybrid Forms)
* **EPUB:-** `.epub`
* **DOI:-** Academic Paper DOIs (`10.xxxx/...`, `doi:10.xxxx/...`, `https://doi.org/...`)
* **TEXT:-** `.txt`, `.text`, `.log`, `.err`, `.out`, `.md`, `.markdown`, `.mdown`, `.mkd`, `.rst`
* **DATA:-** `.json`, `.jsonl`, `.ndjson`, `.yaml`, `.yml`, `.csv`, `.tsv`, `.xml`, `.toml`, `.ini`, `.cfg`, `.env`

---

## 1. How to Install

### Prerequisites
* **Python**: Version 3.10 or higher (fully tested and verified on Python 3.10, 3.11, 3.12, and 3.13).
* **Supported Operating Systems**: **Ubuntu / Linux, Windows 10/11, macOS**.

### Core Installation
Clone or copy this repository, then install the required core dependencies:

```bash
pip install -r requirements.txt
```

> **Note**: This installs all dependencies required for Word, Excel, PowerPoint, EPUB, HTML, Webpages, DOIs, digital PDFs, plain text/markdown, data/config formats, and standard image processing. Works out-of-the-box on both Ubuntu and Windows.

### Optional OCR Installation (for Scanned PDFs & Photos)
If you need deep-learning OCR to extract text from scanned PDFs, photos, or screenshots, use the automated installer for your OS:

* **Linux / Ubuntu / macOS / Git Bash**:
  ```bash
  bash install_ocr.sh
  ```
* **Windows (Command Prompt / PowerShell)**:
  ```cmd
  install_ocr.bat
  ```

* **Manual Setup via pip (Any OS)**:
  ```bash
  pip install -r requirements-ocr.txt
  ```

> **Hardware Acceleration & Python Compatibility Note**:
> * **CPU Mode**: Fully supported out-of-the-box on **Python 3.10, 3.11, 3.12, and 3.13**.
> * **NVIDIA GPU (CUDA) Acceleration**: PaddlePaddle precompiled CUDA binaries currently support **Python 3.10, 3.11, and 3.12**. If you created your virtual environment using Python 3.13, the installer will automatically configure the CPU runtime. To enable NVIDIA GPU acceleration, create your virtual environment with Python 3.11 or 3.12 (e.g. `python3.12 -m venv .venv`).

---

## 2. How to Run

Run the processor via `main.py`:

```bash
python main.py -i <INPUT> [OPTIONS]
```

### Command-Line Options Reference

### 1. Input and Output

| Option         | Alias                 | Description                                                   | Default                 |
|:---------------|:----------------------|:--------------------------------------------------------------|:------------------------|
| `--input`      | `-i`                  | Input file(s), URL(s), DOI(s), or directory path(s).          | **Required**            |
| `--format`     | `-f`                  | Target output format.                                         | `md`                    |
| `--type`       | `--input-type`        | Explicitly specify or override the input data type.           | `auto`                  |
| `--output-dir` | `-o`, `--target-dir`  | Custom directory to save converted files.                     | `output/<FORMAT>/`      |
| `--recursive`  | `-r`                  | Recursively scan subfolders when input is a directory.        | `False`                 |
| `--force`      | —                     | Overwrite existing output files.                              | `False`(skip if exists) |

**Allowed values:**

- `--format`: `md`, `txt`, `json`, `all`
- `--type`: `auto`, `pdf`, `docx`, `pptx`, `xlsx`, `epub`, `html`, `image`, `webpage`, `doi`, `text`, `data`, `markdown`, `json`, `csv`


### 2. OCR Configuration

| Option        | Alias                 | Description                      | Default  |
|:--------------|:----------------------|:---------------------------------|:---------|
| `--ocr-model` | `--ocr-tier`, `--tier`| OCR model performance tier.      | `high`   |
| `--ocr-mode`  | `--mode`              | OCR extraction strategy.         | `auto`   |
| `--ocr-lang`  | `--lang`              | Primary language for OCR.        | `en`     |

**Allowed values:**

- `--ocr-model`: `tiny`, `small`, `mid`, `medium`, `high`, `large`
- `--ocr-mode`: `auto`, `ocr`, `native`, `text`, `document`, `math`
- `--ocr-lang`: Language codes such as `en`, `ch`, `hi`, `fr`, `de`, `es`


### 3. Processing and RAG Chunking

| Option            | Description                                                  | Default                  |
|:------------------|:-------------------------------------------------------------|:-------------------------|
| `--parallel`      | Enable concurrent batch processing.                          | `False` (sequential)     |
| `--max-workers`   | Maximum worker threads when parallel processing is enabled.  | `4`                      |
| `--no-chunks`     | Disable semantic RAG chunk generation in JSON exports.       | `False` (chunks enabled) |
| `--chunk-size`    | Target token count per semantic RAG chunk.                   | `700`                    |
| `--chunk-overlap` | Token overlap between consecutive chunks.                    | `100`                    |

**Allowed values:**

- `--max-workers`: Integer, e.g. `2`, `4`, `8`, `16`
- `--chunk-size`: Integer (token count)
- `--chunk-overlap`: Integer (token count)


### 4. Batch Processing

| Option       | Alias | Description                                                       | Default                   |
|:-------------|:------|:------------------------------------------------------------------|:--------------------------|
| `--csv`      | `-c`  | Path to a CSV file containing URLs, DOIs, or file paths.          | `None`                    |
| `--tsv`      | `-t`  | Path to a TSV file containing URLs, DOIs, or file paths.          | `None`                    |
| `--url-col`  | —     | Name of the column containing URLs.                               | `None`                    |
| `--doi-col`  | —     | Name of the column containing DOIs.                               | `None`                    |
| `--max-rows` | —     | Maximum number of rows to process from CSV/TSV.                   | `None` (process all rows) |


### 5. DOI-Specific Options

| Option             | Description                                                     | Default |
|:-------------------|:----------------------------------------------------------------|:--------|
| `--metadata-only`  | Fetch DOI metadata and abstract only; skip full-text retrieval. | `False` |

---

### Examples

#### 1. Basic Conversion (Default Markdown)
Convert any document to Markdown using default settings:
```bash
python main.py -i document.pdf
python main.py -i report.docx
python main.py -i slides.pptx
python main.py -i spreadsheet.xlsx
python main.py -i book.epub
```
*Output saved to:* `output/md/<name>/<name>.md`

#### 2. Export All Three Formats Simultaneously
Generate Markdown (`.md`), Plain Text (`.txt`), and Structured JSON (`.json`) in one command:
```bash
python main.py -i document.pdf --format all
```

#### 3. Export Specific Formats
Generate only Plain Text or Structured JSON:
```bash
python main.py -i document.pdf --format txt
python main.py -i document.pdf --format json
```

#### 4. Specify a Custom Output Directory
Send output files directly to your desired target folder:
```bash
python main.py -i report.docx --format all --target-dir /path/to/my_exports/
```

#### 5. Explicitly Specify Input Type
Override automatic extension sniffing:
```bash
python main.py -i custom_doc.bin --type docx --format md
```

#### 6. Scanned PDF or Image with OCR Tier Control
Control OCR model accuracy and speed (`high` is default for maximum accuracy, `medium`/`small` for lightweight environments):
```bash
# Default high accuracy OCR tier
python main.py -i scanned_invoice.pdf --format all

# Lightweight, fast OCR tier
python main.py -i receipt.png --ocr-model small --format md

# High accuracy OCR tier for dense scans
python main.py -i archive_book.pdf --ocr-model high --format txt
```
*(Adaptive Circuit Breaker: If your machine encounters a hardware or memory limit on `high`, the engine automatically steps down to `medium` or `small` for the remaining batch without crashing).*

#### 7. Live Webpage Article Extraction
Extract clean article text without boilerplate, ads, or navigation menus:
```bash
python main.py -i "https://en.wikipedia.org/wiki/Artificial_intelligence" --format all
```

#### 8. Academic Paper Retrieval via DOI
Fetch academic paper metadata, find Open Access full text (JATS XML or PDF), extract mathematical formulas and citations:
```bash
python main.py -i "10.1038/s41586-020-2649-2" --format all

# Metadata and abstract only:
python main.py -i "10.1038/s41586-020-2649-2" --metadata-only
```

#### 9. Text, Logs & Markdown Documents
Convert logs, plain text, or markdown files into structured JSON or formatted outputs:
```bash
python main.py -i server.log --format all
python main.py -i notes.txt --format json
python main.py -i README.md --format txt
```

#### 10. Structured Data & Config Files
Convert JSON, YAML, CSV, TSV, XML, TOML, or INI into Markdown tables, clean text, or IR JSON:
```bash
python main.py -i config.yaml --format md
python main.py -i database.json --format all
python main.py -i metrics.csv --format md
```

#### 11. Directory Batch Processing
Convert an entire directory of documents:
```bash
# Scan a folder (non-recursive)
python main.py -i ./my_documents/ --format all

# Recursively scan all subdirectories
python main.py -i ./my_documents/ --recursive --format all
```

#### 12. Filter Directory by File Type
Process only specific formats inside a mixed folder:
```bash
# Process only PDF files inside the folder, ignoring others
python main.py -i ./mixed_folder/ --type pdf --format md
```

#### 13. High-Speed Concurrent Processing (Parallel)
Speed up batch conversion across multiple CPU cores:
```bash
python main.py -i ./large_dataset/ --recursive --parallel --max-workers 8 --format all
```

#### 14. Batch Feeds via CSV / TSV
Process lists of URLs, DOIs, or file paths from tabular sheets:
```bash
# Process URLs from a CSV file
python main.py -c articles.csv --url-col url --format all --parallel

# Process DOIs from a TSV file (first 50 papers)
python main.py -t research.tsv --doi-col doi --max-rows 50 --format all
```
