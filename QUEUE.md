# Durable verification processing

The web process saves the complete selected photos and continuous recording in
the existing persistent SQLite database before acknowledging a queued upload.
The saved evidence manifest binds its hashes, camera session, capture time and
AI model. The credit reservation and queue insertion commit in the same SQLite
transaction. A repeated finish request returns the existing receipt.

`verification_worker.py` runs separately from the web server. Its manager starts
spawned OS processes, normally two and at most eight. Backlog can increase the
pool; surplus processes retire after finishing their current job. OpenCV uses
one thread per worker. The web lifespan supervises and restarts the manager.
No browser or open computer is needed after a durable receipt is returned.

## Storage and deployment

This release uses **one persistent Railway volume and one SQLite writer domain**.
Configure `LOCKX_DATA_DIR`, or use `RAILWAY_VOLUME_MOUNT_PATH` and its `lockx`
subdirectory. The web server and its child worker manager must see that same
database. Do not deploy multiple web replicas with separate SQLite volumes and
expect a shared queue. Postgres job storage and private object storage are future
scaling work; this release does not establish capacity for 10,000 simultaneous
uploads or 10,000 verifications per hour.

Evidence stays in the existing protected database. A queued job is excluded from
the old interrupted-upload cleanup. Admission checks disk headroom before
capture and every evidence write. Queue admission is limited to 10,000 unfinished
jobs; storage headroom can impose a smaller limit. A job unfinished after 24 hours
is failed with a technical outcome and any reserved credit is restored once.
Existing owner and camera-link authorization also applies to queue status.

Publish the backend with the queue flag off, verify the persistent volume and
worker supervisor, and then enable the flag. Publish the queue-aware browser
interface only after backend support is live. Turning the flag off stops new
queue admission and workers from taking new jobs; durable jobs remain saved for
resumption. Do not remove the volume or delete queue tables during rollback.

## Configuration

| Variable | Default | Bounds / behavior |
| --- | --- | --- |
| `LOCKX_VERIFICATION_QUEUE_ENABLED` | `0` | Exactly `1` enables queued submission and workers. |
| `LOCKX_VERIFICATION_CONCURRENCY` | `2` | Base process slots, 1–8. |
| `LOCKX_VERIFICATION_MAX_WORKERS` | `8` | Hard process cap, 1–8. |
| `LOCKX_VERIFICATION_MAX_QUEUED` | `10000` | Admission cap, at most 10,000 unfinished jobs. |
| `LOCKX_VERIFICATION_MIN_FREE_MB` | `256` | At least 64 MB plus the incoming write must be free. |
| `LOCKX_VERIFICATION_LEASE_SECONDS` | `120` | 30–600 seconds; active work renews at most every 10 seconds. |
| `LOCKX_VERIFICATION_MAX_ATTEMPTS` | `5` | 1–10 technical attempts; pacing/budget waits do not consume attempts. |
| `LOCKX_VERIFICATION_HOURLY_BUDGET_USD` | `100` | Rolling 3,600-second cap, 1–100 USD. Cannot exceed 100. |

The queue pins `gpt-4.1` or `gpt-4.1-2025-04-14` when evidence is committed.
Changing the environment does not change a saved job's model. Unsupported
models fail closed. Comparison instructions, reference selection, visual checks
and the 5,000 output-token ceiling stay the same. Optional preliminary advisory
AI calls are skipped in the queued flow; its final comparison remains intact.

## Spend admission and failure behavior

Every physical AI call made while queue mode is enabled, including a technical
retry, must first reserve **$3 atomically** in the shared database. This exceeds
the known maximum price of a full 1,047,576-token GPT-4.1 input at $2 per million
plus 5,000 output tokens at $8 per million (approximately $2.136). The price
version and model are stored with the reservation. At most 18 image inputs are
allowed by the admission validator. Requests exceeding the model context fail
at the provider rather than exceeding that full-context price bound.

A confirmed provider response with valid usage replaces its reservation with
the actual input/output cost. Missing usage, timeouts, crashes or unknown
outcomes retain the entire $3 reservation until it leaves the rolling hour.
Confirmed settlement wakes budget-paused jobs to recheck newly available
headroom. Admission also paces starts at one per second. Multiple workers and
retries cannot reserve the same remaining dollars. The cost cap deliberately
limits throughput when necessary; a large arrival burst grows the queue.

HTTP 429 with a retryable rate limit, HTTP 5xx, network failures and timeouts
receive bounded retries with Retry-After/backoff. A real 429 also applies a
shared pause and reduces admission concurrency. Billing/quota exhaustion,
authentication/validation errors, malformed model output and evidence changes
do not retry automatically. Pacing and cost-budget waits are pauses, not
provider failures. A completed match, mismatch or inconclusive judgment is
never sent to AI again by queue recovery.

Each claim has an expiring lease and a monotonic fencing generation. Result
commits, evidence-derived frame writes, credit settlement and automatic photo
publication verify that generation in the same write transaction. A late worker
cannot overwrite or refund a replacement worker's work. If comparison already
committed, recovery resumes photo marking only. Existing completed comparison
credit consumption stays intact; interrupted or terminal technical failure
restores only a reserved credit, once.

## Status and operations

Seller/owner receipts and result polling include `queue` with the states
`queued`, `running`, `retrying`, `budget_wait`, `completed`, or `failed`. Timestamps
are UTC Unix seconds. Queue position is advisory. Estimated wait stays null
until there is reliable timing history; no invented completion promise is shown.

The authenticated admin queue endpoint reports state counts, oldest wait,
recent safe job states, live worker heartbeats, worker slots, and rolling actual
and reserved cost. It excludes evidence, contact details, tokens and provider
error bodies. Active workers means a heartbeat within 30 seconds; slots are the
configured/adaptive process capacity, not proof that each slot is alive.

For local isolated operation, `python verification_worker.py --once` processes
one eligible durable job without starting the manager. The normal CLI starts
the manager and honors the enable flag. For production, use the supervised web
lifespan instead of manually launching duplicate managers. Supervisor restart
recovers expired leases. Investigate storage, provider quota and worker heartbeat
before increasing concurrency; raising worker count cannot raise the $100 cap.

Tests exercise real SQLite transactions and competing claims, completed upload
receipts, exactly-once credit accounting, stale fencing, capture-time pinning,
model pinning, rolling budget races, delayed usage settlement, technical retries,
mismatch finality, retained evidence, graceful worker retirement and one mocked-AI
job consumed in a separate OS process. They make no real provider calls.
