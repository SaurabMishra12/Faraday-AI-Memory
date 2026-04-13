# Faraday Memory: Data Ingestion Guide

Your AI memory system has built-in smart parsers designed to ingest various file formats. You do not need to convert your documents manually — the ingestion pipeline handles extraction, chunking, and vector embedding automatically based on file extensions.

## 📥 Where to Drop Files

You have two primary designated "Drop Zones". The `sync.py push` command recursively scans these directories and all their subfolders:

1. **Your Obsidian Vault's Inbox or Reference Folders**
   - `00 - Inbox/`
   - `01 - Raw Sources/`
2. **The Dedicated Raw Data Directory**
   - `Faraday/ai-memory-mcp/data_raw/`

## 📄 Supported Formats & Naming Rules

### 1. ChatGPT Exports (JSON)
*   **Format:** `.json`
*   **Rule:** The filename **must** contain the word `conversations`.
*   **Example:** `chatgpt_conversations.json` or `conversations_2025.json`
*   *Behavior:* Explodes the dump and parses it specifically tracking Human vs AI messages.

### 2. Gemini Exports (HTML / Takeout)
*   **Format:** `.html`
*   **Rule:** The filename **must** contain the word `activity` or `gemini`.
*   **Example:** `My_Gemini_Activity.html`
*   *Behavior:* Strips out Google tracking headers and parses out prompts and responses cleanly.

### 3. PDF Documents (Coursework, Papers, E-books)
*   **Format:** `.pdf`
*   **Rule:** Standard PDF documents (text-based). 
*   **Example:** `Linear_Algebra_Notes.pdf` or `Attention_Is_All_You_Need.pdf`
*   *Behavior:* Extracts multi-page text using PDFMiner/PyMuPDF into logical reading chunks.

### 4. Images & Scans (Diagrams, Receipts, Screenshots)
*   **Format:** `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tiff`
*   **Rule:** Can be named anything.
*   **Requirements:** You must have [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed on your system. 
*   *Behavior:* Automatically performs Optical Character Recognition (OCR) to rip the text out of the image and inject it into your vector database.

### 5. Plain Text, Emails, Code, CSVs, and Markdown
*   **Format:** `.md`, `.txt`, `.csv`, `.log`, `.rst`
*   **Rule:** Can be named anything.
*   **Example:** `Meeting_Notes.md` or `email_invoice.txt`
*   *Behavior:* The default fallback. Reads the file as plain structured text and intelligently slices it up. Large CSVs are skipped if they exceed 15MB to prevent clogging the embedding memory.

---

## 🚀 How to Add It to the Cloud

Once your files are dropped into the folders:
1. Open your terminal in the `ai-memory-mcp` folder.
2. Run the ingestion and cloud synchronization command:
   ```bash
   python sync.py push
   ```
3. The script will:
   - Identify *only* the new files.
   - Run the appropriate parser (OCR, HTML extractor, etc.).
   - Break them down into semantic chunks and generate embeddings.
   - Compress the new database.
   - Securely upload the compressed database to Supabase.
   
Your Claude mobile app (and Antigravity!) will automatically have access to this new data upon their next query!
