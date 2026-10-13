# LockX — Stolen Watch Recovery

A dependency-free product prototype for `lockx.ai`. Open `index.html` in a browser to use the dashboard. A FastAPI service starter is included in `backend/` for the production integration path.

## Product surface included

- Watch recovery case intake and private case records
- Active monitoring command center, scan timeline, and source directory
- Candidate-match review queue with confidence signals
- Evidence and alert UX (the UI communicates preservation status)
- Source-aware copy: official APIs, partner feeds, and permitted public results only
- Responsive desktop/mobile layout

## Production integration contract

The interface is intentionally static until it is connected to the included API starter or another LockX backend. A production implementation should use a `/api/v1` interface such as:

| Resource | Key operations |
| --- | --- |
| `/cases` | Create, list, view, pause/resume a recovery case |
| `/cases/{id}/photos` | Signed upload; generate image descriptors asynchronously |
| `/cases/{id}/matches` | Paginated candidate matches; approve, dismiss, escalate |
| `/sources` | Connector health and authorization status |
| `/scans` | View jobs; schedule a new compliant scan |
| `/evidence/{id}` | Immutable snapshot metadata, SHA-256 digest, provenance |
| `/alerts` | Notification preferences and delivery history |

Recommended domain model: `RecoveryCase`, `CasePhoto`, `SearchProfile`, `Connector`, `ScanJob`, `ListingCandidate`, `MatchAssessment`, `EvidenceSnapshot`, `Alert`, and `AuditEvent`.

Each marketplace connector should implement: `authorize()`, `health()`, `search(searchProfile)`, `normalize(result)`, and `rateLimitPolicy()`. Connectors must use official APIs or documented/allowed access only—never CAPTCHA bypasses, login automation, robots-rule evasion, or limit circumvention.

## Start the backend

With Python 3.11+ available on your deployment machine:

```sh
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

The starter uses in-memory storage strictly for local API exploration. Replace it with Postgres, your LockX authentication dependency, object storage, and a real queue before launch.

For a real deployment, host this frontend on Vercel or Cloudflare Pages; use an authenticated API service, managed Postgres/object storage, and a queue worker for scheduled scans and image analysis.
