"""Read-only business totals from LockX's recorded ledger, never provider estimates."""
from datetime import datetime, timedelta, timezone
import time


def analytics(days=30):
    if days not in {7, 30, 90}:
        raise ValueError("Choose 7, 30 or 90 days")
    from in_hand import database

    now = time.time()
    today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    # Include today only up to the snapshot, never future-dated records.
    since = start.timestamp()
    daily = {(start + timedelta(days=i)).strftime("%Y-%m-%d"):
             {"date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
              "gross_sales_cents": 0, "payments_count": 0, "verifications": 0,
              "credits_used": 0, "credits_granted": 0} for i in range(days)}
    summary = dict.fromkeys(("gross_sales_cents", "refunds_cents", "net_payments_cents",
                            "payments_count", "credits_purchased", "credits_granted", "credits_used",
                            "current_credit_balance", "wallet_accounts", "verifications_total",
                            "verified", "mismatch", "inconclusive", "failed", "pending"), 0)
    with database(read_only=True) as db:
        db.execute("BEGIN")  # One consistent snapshot; no reconciliation or provider calls.
        payment_rows = db.execute("""SELECT date(l.created,'unixepoch') AS day,
            COUNT(*) AS payments_count, SUM(p.amount_cents) AS gross_sales_cents,
            SUM(p.refunded_cents) AS refunds_cents, SUM(p.credits) AS credits_purchased
            FROM credit_payments p JOIN credit_ledger l
              ON l.kind='purchase' AND l.reference=p.payment_id
            WHERE l.created>=? AND l.created<=? GROUP BY day""", (since, now)).fetchall()
        for row in payment_rows:
            for key in ("payments_count", "gross_sales_cents", "refunds_cents", "credits_purchased"):
                summary[key] += int(row[key] or 0)
            for key in ("payments_count", "gross_sales_cents"):
                daily[row["day"]][key] = int(row[key] or 0)
        summary["net_payments_cents"] = summary["gross_sales_cents"] - summary["refunds_cents"]
        rows = db.execute("""SELECT date(created,'unixepoch') AS day,
            SUM(CASE WHEN kind IN ('verification','technical_refund') THEN -delta ELSE 0 END) AS credits_used,
            SUM(CASE WHEN kind='admin_grant' THEN delta ELSE 0 END) AS credits_granted
            FROM credit_ledger WHERE created>=? AND created<=? GROUP BY day""", (since, now)).fetchall()
        for row in rows:
            for key in ("credits_used", "credits_granted"):
                value = int(row[key] or 0)
                summary[key] += value
                daily[row["day"]][key] = value
        wallets = db.execute("SELECT COUNT(*) AS accounts, COALESCE(SUM(balance),0) AS balance FROM credit_wallets").fetchone()
        summary.update(wallet_accounts=wallets["accounts"], current_credit_balance=wallets["balance"])
        rows = db.execute("""SELECT date(submitted,'unixepoch') AS day,status,analysis_status,COUNT(*) AS count
            FROM ih_requests WHERE submitted>=? AND submitted<=? GROUP BY day,status,analysis_status""", (since, now)).fetchall()
        for row in rows:
            count = row["count"]
            summary["verifications_total"] += count
            daily[row["day"]]["verifications"] += count
            if row["analysis_status"] in {"failed", "unavailable"}:
                outcome = "failed"
            elif row["analysis_status"] == "complete":
                outcome = {"confirmed": "verified", "mismatch": "mismatch"}.get(row["status"], "inconclusive")
            else:
                outcome = "pending"
            summary[outcome] += count
    return {"currency": "USD", "timezone": "UTC", "days": days,
            "start": start.strftime("%Y-%m-%d"), "end": today.strftime("%Y-%m-%d"),
            "generated_at": now, "summary": summary, "daily": list(daily.values()),
            "notes": [
                "Sales dates use the time LockX recorded the paid credit grant. Unpaid checkouts are excluded.",
                "Refunds and net payments refer to purchases recorded in the selected period, including later recorded refunds. Processing fees and operating costs are excluded.",
                "Free credit grants are separate from purchased credits and sales. Net credits used subtracts technical credit restorations recorded in the period.",
                "Verification results count submitted inspection records, including retries; drafts are excluded. Matched means a visual match, not item authenticity.",
                "Wallet accounts and current credit balance are all-time snapshot totals. This dashboard does not query PayPal live."
            ]}
