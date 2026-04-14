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

## The "Hold My Hand" Framework Setup Guide

Look, if you want to deploy this, you actually have to do some work. Follow these steps or enjoy your amnesic AI.

### Step 1: The Local Data Hoarder Setup
You're going to generate the embeddings on your own machine because doing it in the cloud for free is a myth.
1. Clone this repository to your machine. 
2. Install the requirements like every other Python project in existence: \`pip install -r requirements.txt\`
3. Put your messy `.md`, `.json`, `.pdf`, etc. into the `data_raw/` directory.
4. *(Optional but painful)*: If you want to extract text from images, go install `Tesseract-OCR` on your host machine. Don't blame me for the terrible Windows installers, complain to Google.

### Step 2: Setting up Supabase (The Giant Cloud Bucket)
Your FAISS vector index will get massive. You can't just shove a 200MB SQLite DB into a Docker image and pretend it's fine. We need cloud storage.
1. Go to [Supabase](https://supabase.com) and create a free project.
2. Create a private storage bucket named `faraday-memory`.
3. Go to Project Settings -> API, and copy your `Project URL` and `service_role` key (yes, the service role, because we bypass Row Level Security. Live a little).
4. Export them into your local environment variables:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`

### Step 3: Feeding Time
Time to crunch those vectors. Run the ingestion and push script:
```bash
# This will ingest your files, run the transformer model, 
# compress the massive SQLite blobs, automatically chunk them if they exceed 40MB,
# and push them directly to your Supabase bucket.
python sync.py push
```
*(Wait a few minutes. It's doing heavy math on your CPU. Go get a coffee.)*

### Step 4: The Cloud Brain (Hugging Face Spaces)
Now we need the actual MCP Server running 24/7 so Claude or Cursor can talk to it.
1. Go to [Hugging Face Spaces](https://huggingface.co/spaces) and create a new **Docker** Space.
2. Connect your GitHub fork of this repository to it.
3. **CRITICAL:** In the Space Settings -> Variables and secrets, add the following secrets:
   - `SUPABASE_URL` (From Step 2)
   - `SUPABASE_KEY` (From Step 2)
   - `FARADAY_API_KEY` (Make up a secure password here. This protects your data from random script kiddies on the internet).
4. The Docker container will build, boot up, auto-download the chunks from Supabase, reassemble them in memory, and start an MCP SSE server on port `7860`.

### Step 5: Connecting the AIs
Connect any MCP-compatible agent (Claude Desktop, Cursor, etc.) directly to your new shiny cloud server.
```json
// Example for Claude Desktop (claude_desktop_config.json)
{
  "mcpServers": {
    "faraday": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/inspector",
        "https://<your-space-name>.hf.space/sse"
      ],
      "env": {
        "X-API-Key": "<your_FARADAY_API_KEY>"
      }
    }
  }
}
```

Enjoy not having to constantly remind your AI what programming language you are using, or copying and pasting the exact same system architecture prompt for the 45th time.

---
*Disclaimer: Absolutely no personal data, keys, or vector blobs are included in this repo. I strictly `.gitignore`'d all of it. If you fork this and manage to leak your own API keys by committing them, that's entirely on you.*

