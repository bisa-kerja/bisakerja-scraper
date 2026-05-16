# 🕷️ FastAPI Scraper Pipeline Documentation

## Overview

Dokumen ini menjelaskan alur end-to-end sistem scraping job dari berbagai platform:

- Glints
- Kalibrr
- JobStreet
- Dealls

Pipeline ini bertujuan untuk:

1. Mengambil data job secara otomatis setiap hari
2. Menormalisasi data sesuai schema backend utama (immutable)
3. Melengkapi data menggunakan AI (OpenAI)
4. Sinkronisasi ke database utama
5. Melakukan notification handoff ke Backend API (email tetap domain backend)

# 🧠 Core Principles

## 1. Schema is Source of Truth

- Schema database backend **tidak boleh diubah**
- Scraper wajib mengikuti struktur:
  - `JobListing`
  - `Company`
  - `JobSkill`
  - `JobRequirement`

👉 Artinya:

> Scraper = Adapter layer, bukan penentu schema

## 2. Decoupled Architecture

Scraper system **terpisah dari backend utama**

```text
[ FastAPI Scraper ]
        ↓
[ Local Scraper DB ]
        ↓
[ Normalization + AI Enrichment ]
        ↓
[ Main Backend DB ]
```

## 3. Batch & Async Processing

- Hindari processing langsung semua data
- Gunakan batching:
  - AI: per 10 jobs
  - Sync: chunked insert

# 🏗️ High-Level Architecture

```text
                ┌────────────────────┐
                │   External APIs    │
                │ (Glints, etc)      │
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
                │  Scraper Service   │ (FastAPI)
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
                │  Local Scraper DB  │
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
                │ AI Enrichment      │ (OpenAI)
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
                │ Main Backend DB    │
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
                │ Backend Email      │
                │ Worker             │
                └────────────────────┘
```

# ⏰ Daily Pipeline Flow

## 🌙 00:00 AM — Scraping Phase

### Step 1: Trigger Scheduler

Gunakan:

- `APScheduler` daemon (`python -m cli.daemon`) di service scheduler
- atau `cron` eksternal yang memicu command internal terkontrol

```bash
0 0 * * *
```

### Step 2: Run Scraper per Platform

| Platform  | Method         |
| --------- | -------------- |
| Glints    | GraphQL        |
| Kalibrr   | Next.js API    |
| JobStreet | Search page SSR (auth optional) |
| Dealls    | REST           |

### Step 3: Store Raw Data

Data disimpan ke **local scraper DB**

Contoh table:

```sql
scraped_jobs_raw
```

Field:

- source_platform
- raw_payload (JSON)
- scraped_at

## 🧹 02:00 AM — Normalization Phase

### Step 4: Transform → Match Prisma Schema

Mapping ke:

- `JobListing`
- `Company`
- `JobRequirement`

### ⚠️ Constraint

Schema berikut **HARUS dipatuhi**:

- `externalJobId` wajib unik
- `sourcePlatformId` harus valid
- `companyId` harus resolved

### Step 5: Deduplication

Gunakan:

```ts
unique: [sourcePlatformId, externalJobId];
```

## 🤖 04:00 AM — AI Enrichment Phase

### Step 6: Batch Processing (per 10 jobs)

Kenapa batching:

- hemat cost
- avoid rate limit
- lebih stabil

### Step 7: AI Tasks

Gunakan OpenAI untuk:

#### 🧠 Skill Extraction

Input:

```json
{
  "title": "...",
  "description": "..."
}
```

Output:

```json
["React", "Node.js", "Docker"]
```

#### 🧾 Requirement Structuring

Mapping ke:

- `JobRequirement`
  - type: SKILL / EXPERIENCE / EDUCATION

### Step 8: Insert to Local Structured Tables

- `job_skills_staging`
- `job_requirements_staging`
- `ai_request_logs` (saat AI enrichment aktif)

## 🔄 06:00 AM — Sync Phase

### Step 9: Upsert to Main DB

Metode:

```ts
upsert (based on externalJobId)
```

### Step 10: Maintain Status

Set:

- `lastSeenAt`
- `status = ACTIVE`

Jika tidak ditemukan lagi:

- mark as `STALE` / `EXPIRED`

## 📧 08:00 AM — Notification Handoff

### Step 11: Handoff Kandidat Job ke Backend

Scraper hanya kirim kandidat job tersinkronisasi + metadata freshness.
Filter user, matching preferensi, ranking, dan delivery email dilakukan di Backend API/notification worker.

### Step 12: Backend Menangani Matching + Delivery

Boundary:

```text
Scraper: notify-handoff payload only
Backend: preference filter + recommendation + email send
```

# 🧩 Data Mapping Strategy

## Example Mapping

| Source Field | Target                |
| ------------ | --------------------- |
| title        | JobListing.title      |
| companyName  | Company.name          |
| location     | city + province       |
| salary       | salaryMin / salaryMax |
| description  | description           |

## Skill Mapping

Flow:

```text
AI output → normalize → match Skill.slug → insert JobSkill
```

# 🧠 AI Integration Design

## Queue-Based Processing

Gunakan:

- Local DB-backed queue (`stage_jobs`) sebagai default runtime
- Redis/Celery opsional untuk scale lanjut

```text
scraped_jobs → queue → AI worker → DB
```

## Logging

Gunakan tabel:

- `AiRequestLog`

Track:

- latency
- success/failure
- model

# ⚠️ Important Considerations

## 1. Rate Limiting

- delay scraping per platform
- random interval

## 2. Anti-Bot Handling

- rotate user-agent
- optional proxy

## 3. Failure Recovery

Gunakan:

- retry mechanism
- dead letter queue

## 4. Data Quality

Pastikan:

- tidak ada null critical field
- sanitize HTML

# 🚀 Recommended Tech Stack

## Scraper

- FastAPI
- httpx / requests
- Playwright (optional)

## Queue

- Local DB queue (`stage_jobs`) / worker internal
- Redis + Celery / RQ (future option)

## DB

- PostgreSQL (local staging)

## Scheduler

- APScheduler daemon / Cron

# 🧠 Final Verdict

Arsitektur ini:

✅ scalable
✅ production-ready
✅ modular
✅ AI-ready

# 🔥 Suggested Improvements (Important)

1. Tambahkan **retry layer**
2. Pisahkan **AI enrich worker dedicated** dari jalur sync kritikal
3. Pisahkan:
   - raw data
   - normalized data

4. Tambahkan **monitoring (log ingestion run)**

# 🎯 Summary

Pipeline harian:

```text
00:00 → Scrape
02:00 → Normalize
04:00 → AI Enrich
06:00 → Sync DB
08:00 → Notify Handoff (Backend handles email)
```
