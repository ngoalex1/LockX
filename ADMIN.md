# LockX administration

Open `https://lockx.ai/Ngoalex1` and sign in with the administrator's usual email link. The credit wallet also shows an **Admin dashboard** link after the server confirms access.

Administrator access is assigned to verified Supabase user UUIDs in the server-only `LOCKX_CREDIT_ADMIN_IDS` environment variable (comma separated). Email address text, browser settings and editable user metadata cannot grant permission. The page address is not an access credential.

## Complimentary credits

1. Enter an existing customer's email and choose **Look up customer**. New customers must sign in once first.
2. Enter 1–10,000 whole credits and a reason.
3. Choose **Review credit grant**, verify the recipient and amount, then add the credits.

Grants add to the existing balance. Each grant records its recipient, administrator, amount, reason and timestamp in the persistent SQLite audit ledger. Safe retries use the same request key and cannot add the same grant twice. Grants do not create a payment or send an email. Purchased credits remain separate.

## Business analytics

The 7-, 30- and 90-day views use UTC dates and recorded server data. Gross sales include only confirmed paid credit grants. Refund and net totals apply to the selected purchase cohort; they include refunds subsequently recorded against those purchases. Net payments exclude processing fees and operating costs. Current wallet balance and account totals are all-time snapshots.

Item-check outcomes count submitted records, including retries. A matched result describes a visual match rather than brand authenticity. Net credits used subtracts technical restorations recorded in the period.

## Social and campaign attribution

Use the campaign-link builder to label each platform, campaign and post. Share the generated homepage URL, for example:

`https://lockx.ai/?utm_source=instagram&utm_medium=social&utm_campaign=launch&utm_content=story-01`

Tracking begins with this release and does not reconstruct historical traffic. First-party, 24-hour browser-session visits link to checkout and verification records. Campaign panels group outcomes by the visit's UTC start date, including later linked outcomes through the report snapshot. Purchase conversion counts distinct paying visits divided by tracked visits. Actual payments and verification outcomes come from server records.

Different devices, blocked tracking, removed link labels and lost browser sessions can leave activity unattributed. Reach, impressions, likes, ad spend and platform ROAS are not supplied by this system. Attribution stores bounded campaign labels, opaque visit IDs and timestamps; it does not store full URLs, IP addresses, email addresses or browser fingerprints in marketing tables. Global Privacy Control and Do Not Track signals disable browser tracking. Analytics is asynchronous; an unavailable attribution service does not prevent a purchase.

## Verification queue

The queue panel shows saved submissions, automatic retries, capacity waits, worker heartbeats and recent completion/failure counts. It excludes private evidence and customer contact details. Queue position is advisory; a waiting-time estimate is omitted until reliable timing history exists.

The approved AI processing allowance is $100 over the rolling last 60 minutes. **Used or reserved** includes recorded provider cost plus provisional allowances for in-flight or unknown outcomes; recorded cost is already part of that total. It is a ceiling, not a fixed charge. Hosting, storage and payment fees are separate. Processing pauses safely when admission headroom is exhausted.

See [QUEUE.md](QUEUE.md) for deployment, evidence preservation, technical retry and worker recovery details. This initial single-volume release does not establish 10,000-verification/hour capacity.
