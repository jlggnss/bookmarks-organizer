# Bookmarks Organizer

![Bookmarks Organizer](/header.png)

AI-powered bookmark organizer that reads your exported bookmarks (Netscape format), categorizes them into folders using **Google Gemini** or any **OpenAI-compatible LLM**, supports **interactive Excel curation & cleanup**, and exports them back — ready to import into any browser.

## Features

- **Parse & export** standard Netscape Bookmark File Format (works with Chrome, Firefox, Safari, Edge, etc.)
- **📊 Excel Table Export & Import**:
  - Export bookmarks to a styled, auto-filtered Excel sheet (`.xlsx`)
  - Human-readable dates (`YYYY-MM-DD HH:MM:SS`) to quickly spot ancient links
  - Domain breakdown for easy site filtering
  - URL duplicate detection (`Duplicate` column with highlight)
  - Quick cleanup: simply delete rows in Excel or mark `Status` column as `Delete`
  - Convert back to browser HTML with one command or feed directly into AI
- **🔒 Toolbar Preservation (`--preserve-toolbar`)**:
  - Protects bookmarks located directly on the **Bookmarks Bar** so your custom shortened toolbar titles are never modified or moved into subfolders by AI
- **🚀 Dual AI Providers**:
  - **Google Gemini** (via official `google-genai` SDK, default: `gemini-3.8-flash`)
  - **OpenAI** (GPT-4o, GPT-4o-mini, etc.)
  - **OpenRouter** or local LLMs (Ollama, LM Studio)
- **Automatic provider detection** based on your API key prefix (`AIza...` for Gemini) or model name
- **Protected folders** — keep specific folders untouched
- **Uncategorized mode** — only sort new/uncategorized bookmarks while preserving your existing structure
- **Batch processing** — handles large collections efficiently
- **Stop & resume** — automatically saves progress; resume after interruptions
- **Retry with backoff** — gracefully handles rate limits (429), timeouts, and transient API errors

## Requirements

- Python 3.10+
- An API key for:
  - **Google Gemini** (get one free at [Google AI Studio](https://aistudio.google.com/))
  - OR an **OpenAI-compatible API** that supports structured JSON output (`response_format: { type: "json_object" }`)
  - *(Note: You do not need any API key if you are only converting between HTML and Excel!)*

## Quick Start

```bash
# Clone and install
git clone https://github.com/rb81/bookmarks-organizer.git
cd bookmarks-organizer
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Gemini API key (or OpenAI key)

# Run (auto-detects Gemini or OpenAI from your key)
python main.py bookmarks.html
```

---

## 📊 Excel Curation & Cleanup Workflow

Clean up your bookmarks in Excel before or after running AI categorization:

### 1. Export HTML to Excel Table
```bash
python main.py bookmarks.html --to-excel bookmarks.xlsx
```
Open `bookmarks.xlsx` in Excel:
- **Sort by Date Added** to find and delete obsolete, temporary links.
- **Filter by Domain** to review all bookmarks from a specific website.
- **Spot Duplicates** marked in the `Duplicate` column.
- **Delete unwanted bookmarks** by either deleting the row in Excel or changing `Status` from `Keep` to `Delete`.

### 2. Convert Cleaned Excel back to HTML (without AI)
```bash
python main.py bookmarks.xlsx -o bookmarks_cleaned.html --no-ai
```

### 3. Run AI Organization Directly on Cleaned Excel
```bash
python main.py bookmarks.xlsx -o bookmarks_organized.html
```

---

## Configuration

### Environment Variables (`.env`)

#### Option 1: Google Gemini (Recommended)

```bash
# Required: Gemini API Key (starts with AIza...)
GEMINI_API_KEY=AIzaSy-your-key-here

# Optional: Gemini model (default: gemini-3.8-flash)
GEMINI_MODEL=gemini-3.8-flash
```

#### Option 2: OpenAI / OpenRouter / Local LLMs

```bash
# Required: OpenAI API key
API_KEY=sk-your-key-here

# Optional (defaults shown)
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
```

### Config File (`config.yaml`)

```yaml
# Provider setting (auto, gemini, or openai)
provider: auto

# Default Gemini model
gemini_model: gemini-3.8-flash

# Default OpenAI model
model: gpt-4o-mini

# Protect direct Bookmarks Bar bookmarks (preserves shortened toolbar titles)
preserve_toolbar: true

max_categories: 20
batch_size: 10
protected_folders:
  - Favorites
  - Reading List
```

---

## Usage

```bash
# Organize bookmarks with auto-detected provider
python main.py bookmarks.html

# Organize with toolbar preservation (preserves short toolbar titles)
python main.py bookmarks.html --preserve-toolbar

# Explicitly use Google Gemini
python main.py bookmarks.html --provider gemini --model gemini-3.8-flash

# Explicitly use OpenAI
python main.py bookmarks.html --provider openai --model gpt-4o-mini

# Export to Excel for manual cleanup
python main.py bookmarks.html --to-excel bookmarks.xlsx

# Convert Excel back to HTML without AI
python main.py bookmarks.xlsx -o bookmarks_cleaned.html --no-ai

# Specify output file (HTML or Excel)
python main.py bookmarks.html -o organized.html
python main.py bookmarks.html -o organized.xlsx

# Only organize uncategorized bookmarks (preserves existing folders)
python main.py bookmarks.html --uncategorized-only

# Start fresh (ignore saved progress)
python main.py bookmarks.html --no-resume

# See all options
python main.py --help
```

### Stop & Resume

If you interrupt the process (Ctrl+C) or it encounters an issue mid-run, progress is automatically saved to `progress.json`. Simply run the same command again and it will resume where it left off. Use `--no-resume` to discard saved progress and start fresh.

### Error Handling

The organizer handles transient API failures gracefully across both Gemini and OpenAI:

- **Rate limits (429)** — waits and retries (up to 3 attempts with increasing delays)
- **Timeouts** — retries with exponential backoff
- **Connection errors** — retries with backoff
- **Server errors (5xx)** — retries with backoff
- **Client errors (4xx)** — fails immediately without wasteful retries (e.g., invalid API key)
- **Invalid responses** — marks affected bookmarks as "Uncategorized" rather than crashing

---

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test suites
pytest tests/test_excel.py
pytest tests/test_gemini.py
```

## Project Structure

```
bookmarks-organizer/
├── main.py              # CLI entry point with provider auto-detection & Excel flags
├── src/
│   ├── excel.py         # Excel table export & import with date/domain/toolbar parsing
│   ├── llm_interface.py # Base interface, shared prompts & JSON validator
│   ├── gemini_llm.py    # Google Gemini provider (google-genai SDK)
│   ├── openai_llm.py    # OpenAI / OpenAI-compatible provider
│   ├── llm_factory.py   # Provider factory & key/model auto-detection
│   ├── models.py        # Bookmark & Folder dataclasses
│   ├── parser.py        # Netscape HTML parser with toolbar preservation
│   ├── writer.py        # Netscape HTML writer with toolbar attributes
│   ├── organizer.py     # Bookmark categorization logic
│   └── progress.py      # Stop/resume persistence
├── tests/
│   ├── test_excel.py    # Excel export, import, date & deletion tests
│   ├── test_gemini.py   # Gemini & provider factory tests
│   ├── test_organizer.py# Organizer & categorization tests
│   ├── test_parser.py   # Parser & extraction tests
│   ├── test_progress.py # Progress persistence tests
│   └── test_writer.py   # Writer & round-trip tests
├── config.yaml          # User settings
├── .env.example         # Environment template
├── requirements.txt
└── README.md
```

## License

MIT License — see [LICENSE](LICENSE) for details.
