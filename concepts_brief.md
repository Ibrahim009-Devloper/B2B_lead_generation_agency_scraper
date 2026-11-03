# RFC Concepts Brief: Stateless Lead Gen Pipeline, Direct Google Sheets Ingestion & Adaptive Concurrency

* **Author:** EGM Multi-Lens Brainstorm Swarm
* **Date:** 2026-11-03
* **Status:** Approved Concept / Implementation Specification
* **Target ICP & Guidelines:** Aligned with `GEMINI.md` v3.1

---

## 1. Executive Summary & Problem Statement

Current constraints on zero-cost deployment environments (Render Free Tier 512MB RAM cap) cause:
1. **Memory Bloat & OOM Kills:** Accumulating scraped HTML, deep lead summaries, and logs in local SQLite or RAM causes container crashes.
2. **Container Spin-down:** Render terminates web processes after 15 minutes of idle HTTP traffic.
3. **Redundant Pagination Crawls:** Restarting scrapers from page 1 wastes search requests and proxy tokens on previously processed agencies.
4. **Heavy Cloud API Dependencies:** Direct Google Sheets API requires bulky OAuth service account JSON files and token refresh handling.

### The Solution:
A **stateless streaming architecture** where:
- Python performs 100% of directory scraping, DNS MX validation, and filtering.
- AI (Groq/Gemini) performs strictly verification and summarization on pre-qualified leads.
- A **Google Apps Script Webhook** ingests verified leads via batched POST requests (5x/min rate limit).
- A **Tiny SQLite DB (<5MB)** maintains permanent lifetime domain and email deduplication hashes only.
- A lightweight **`/health` endpoint** prevents Render sleep via `cron-job.org` pings.
- A **`scraped_pages.json`** cursor file preserves directory pagination offsets across runs.

---

## 2. Multi-Lens Brainstorm Synthesis

### 🔍 Lens 1: Design Critic & Ergonomics (`egm-design`)
* **Google Apps Script Webhook Advantage:** Zero credential rotation. The user simply pastes a Google Sheet Webhook URL into `.env`. No GCP Project, OAuth consents, or expiring Service Account keys needed.
* **Batch Ingestion Ergonomics:** Rather than posting 1 lead per request, the worker flushes a JSON payload with `leads: [...]`. This minimizes HTTP handshake overhead and ensures Google Sheet cells update smoothly without cell contention locks.
* **Status Visibility:** The CLI/Dashboard exposes stream metrics: `[STREAMER] Flushed 4 leads to Google Sheet | Total Today: 48 | Memory: 42MB`.

### ⚡ Lens 2: Codebase Details & Mechanics (`egm-codebase-details`)
* **302 Redirect Handling:** Google Apps Script Webapps return an HTTP 302 redirect to `script.googleusercontent.com`. The Python HTTP client (`httpx.AsyncClient(follow_redirects=True)` or `curl_cffi`) is mandatory; otherwise, the request halts at the redirect with no data appended.
* **Tiny SQLite Schema:**
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;

  CREATE TABLE IF NOT EXISTS scraped_domains (
      domain_hash TEXT PRIMARY KEY,
      domain TEXT NOT NULL,
      status TEXT NOT NULL, -- 'VERIFIED', 'REJECTED', 'NO_EMAIL'
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS scraped_emails (
      email_hash TEXT PRIMARY KEY,
      email TEXT NOT NULL,
      domain TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_email_domain ON scraped_emails(domain);
  ```
* **No Payload Storage:** Leads are never written to SQLite tables. Only the domain string and MD5/SHA256 hash are recorded. SQLite file remains <5MB indefinitely.

### 🌐 Lens 3: System Architecture & Macro Constraints (`egm-zoom-out`)
* **Render Free Tier Compatibility:** 512MB RAM ceiling is strictly protected. Bounded queue (`asyncio.Queue(maxsize=100)`) backpressures the scraper if the webhook network stalls.
* **Keepalive Mechanism:** `cron-job.org` sends an HTTP GET to `/health` every 5 minutes. The response responds within <10ms:
  ```json
  {
    "status": "healthy",
    "uptime_seconds": 18400,
    "memory_rss_mb": 46.2,
    "active_workers": 2,
    "queue_depth": 0,
    "leads_streamed_today": 84
  }
  ```
* **Graceful Degradation:** If the Webhook fails (e.g. Google network timeout), exponential backoff retries up to 3 times. If failures persist, the batch is temporarily written to a fallback `failed_leads.jsonl` rather than crashing the process.

### 🎯 Lens 4: Domain Logic & ICP Alignment (`egm-comprehension`)
* **100% Alignment with `GEMINI.md`:**
  - Zero-Email Drop: If no DNS MX or valid email is found, candidate is marked `NO_EMAIL` in SQLite and dropped with 0 AI token usage.
  - Verification: AI verifies the 4 strict conditions (Real Business, Service Buying Need, 2–50 employee sweet spot, Email matching).
  - 12 Columns Preserved: All 12 columns mandated by `GEMINI.md` Section 4 are mapped directly to Google Sheet rows.

### 🚀 Lens 5: Implementation Readiness (`egm-implementation-readiness`)
* **Implementation Blueprint:**
  1. `google_apps_script/Code.gs`: Deployable Apps Script with `doPost(e)` accepting batch arrays.
  2. `core/db.py`: Async SQLite dedup manager with WAL mode.
  3. `core/sheet_streamer.py`: Async background worker loop sleeping 12s, draining queue, batch POSTing to Webhook.
  4. `core/pagination.py`: `scraped_pages.json` reader/writer with atomic file swap.
  5. `main.py`: FastAPI app with `/health` and pipeline lifespan runner.

### 📐 Lens 6: Structural Modularity (`egm-structural`)
```
My_lead_generation_agent/
├── google_apps_script/
│   └── Code.gs                 # Google Apps Script Webhook handler
├── core/
│   ├── config.py               # Env vars (WEBHOOK_URL, CONCURRENCY)
│   ├── dedup_db.py             # Tiny SQLite WAL dedup
│   ├── sheet_streamer.py       # Rate-limited background queue worker
│   ├── pagination.py           # scraped_pages.json state manager
│   ├── scraper.py              # Multi-source scraper (curl_cffi)
│   ├── dns_verifier.py         # DNS MX record check
│   └── ai_verifier.py          # Groq/Gemini business verifier
├── api/
│   └── routes.py               # /health and control endpoints
├── scraped_pages.json          # Persistent page cursors
├── dedup.db                    # Tiny SQLite index (<5MB)
├── main.py                     # ASGI server entrypoint
└── GEMINI.md                   # Core system instructions
```

---

## 3. Google Apps Script Webhook Specification

### Target Google Sheet:
`https://docs.google.com/spreadsheets/d/1yM7NdHxgcEVECEeGNevnXLsVtt_Fcu1fF-yJnSc5GSA/edit?gid=0#gid=0`

### `Code.gs` Implementation:
```javascript
function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.tryLock(10000);
  
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // Auto-initialize header row if empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        "Company Name", "Website Domain", "Verification Status",
        "Primary Verified Email", "Email Category", "Backup Emails",
        "Decision Maker Name & Role", "Complete Business Summary",
        "Their Target Clients", "How to Pitch / Personalization Guide",
        "Ready Personalized Cold Email", "Source Footprint", "Timestamp"
      ]);
    }
    
    var data = JSON.parse(e.postData.contents);
    var leads = data.leads || [data];
    var rows = [];
    
    for (var i = 0; i < leads.length; i++) {
      var item = leads[i];
      rows.push([
        item.company_name || "",
        item.website_domain || "",
        item.verification_status || "",
        item.primary_email || "",
        item.email_category || "",
        Array.isArray(item.backup_emails) ? item.backup_emails.join(", ") : (item.backup_emails || ""),
        item.decision_maker || "",
        item.business_summary || "",
        item.target_clients || "",
        item.pitch_guide || "",
        item.cold_email || "",
        item.source_footprint || "",
        new Date().toISOString()
      ]);
    }
    
    if (rows.length > 0) {
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      appended_count: rows.length
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
```

---

## 4. Work Breakdown & Action Items

| Phase | Component | Key Tasks |
|---|---|---|
| **P1** | **Google Apps Script** | Deploy `Code.gs` to target spreadsheet as Web App (Execute as Me, Anyone can access). |
| **P2** | **Tiny SQLite Dedup** | Implement `core/dedup_db.py` with domain and email hash indexing, WAL mode. |
| **P3** | **Webhook Streamer** | Build `core/sheet_streamer.py` with 12s interval flushing and `follow_redirects=True`. |
| **P4** | **Directory Pagination**| Implement `core/pagination.py` to persist GoodFirms/Clutch page indices in `scraped_pages.json`. |
| **P5** | **FastAPI Keepalive** | Add GET `/health` route with memory RSS and queue depth metrics for `cron-job.org`. |
| **P6** | **Pipeline Integration**| Wire queue into scraping pipeline, dropping heavy HTML payloads from RAM immediately after qualification. |
