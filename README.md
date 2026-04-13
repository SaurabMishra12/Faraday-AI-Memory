---
title: Faraday Memory
emoji: 🧠
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# Faraday AI Memory

**Author:** Saurab Mishra

Look, I got tired of switching between five different "AI" coding tools and repeating the same context a million times like a broken record. Claude Code, Cursor, Antigravity, Copilot—they all suffer from the exact same severe, chronic amnesia every time you close the tab. You tell them your tech stack on Monday, and by Tuesday they're confidently rewriting your backend in PHP. 

So I built **Faraday**. 

Faraday is a brutally fast, brutally simple Model Context Protocol (MCP) server that slams your local documents, chat histories, emails, and PDFs directly into a vector database, compresses it, and force-feeds it to whatever vibe-coding AI toy you are currently obsessing over. 

You drop files in a folder, run a script, and suddenly your AI actually remembers who you are and what you're working on. Groundbreaking concept, I know.

---

## What It Actually Does

1. **Ingests literally everything:** Drop `.md`, `.json` (ChatGPT exports), `.html` (Gemini exports), `.pdf`, or even `.png` (images with text) into the `data_raw` folder.
2. **Chunking & Vectorization:** It chunks the files, runs them through an extremely lightweight open-source embedding model (`all-MiniLM-L6-v2`), and indexes them in FAISS.
3. **Cloud Synchronization:** Compresses the gigantic, bloated vector indexes down to a few megabytes and shoves them into a private Supabase bucket.
4. **SSE Server:** Boots up an HTTP/SSE server (perfect for Hugging Face Spaces or Cloud Run) that safely pulls your index from Supabase into memory, hiding it behind a simple API key firewall. 

Your data stays entirely under your control (no relying on bloated SaaS corporate subscriptions).

## The Local Dev Setup (If you want to run it on your own laptop)

If you're deploying this to the cloud, the `Dockerfile` takes care of the heavy lifting. But if you want to run the ingestion and test locally:

### 1. Requirements

Install the stuff. You probably already have half of this globally installed anyway.
```bash
pip install -r requirements.txt
```
*(Pro-tip: If you want it to actually read the text out of your images, you need to suffer through installing `Tesseract-OCR` on your OS level. Don't blame me, complain to Google).*

### 2. Configuration

Open `config.py`. It's stupidly simple.
- Put your raw messy files in the `data_raw/` directory.
- For the Supabase cloud connection, set these environment variables (or hardcode them if you like playing with fire):
  - `SUPABASE_URL`
  - `SUPABASE_KEY` (Needs to be the service key to bypass Row Level Security, since we use private storage buckets)

### 3. Update the Brain

Whenever you hoard more documents, just run:
```bash
python sync.py push
```
It will automatically find the new files, ignore the ones it already did, run the embeddings, compress the database, and shoot it to the cloud.

### 4. Connect to your AI

Connect any MCP-compatible agent directly to the cloud server, or run it locally:
```bash
# Local standard I/O (For Cursor / Desktop apps)
python mcp_server/main.py

# Or connect to the Cloud SSE endpoint
URL: https://<your-huggingface-space>.hf.space/sse
Header: X-API-Key: <your_secret_password>
```

Enjoy not having to constantly remind your AI what programming language you're using.

---
*No personal data, keys, or vector blobs are included in this repo. I `.gitignore`'d all of it. If you manage to leak your API keys, that's entirely on you.*
