from datetime import datetime, timezone
import pytest
import credit_analytics
import credit_wallet as credits

NOW = datetime(2026, 11, 13, 20, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(credit_analytics.time, "time", lambda: NOW)
    with credits.database() as db:
        credits.entry(db, "owner", 2, "purchase", "paid")
        db.execute("INSERT INTO credit_checkouts(id,owner_id,pack_id,amount_cents,credits,provider,status,created,request_key) VALUES ('c','owner','starter',100,2,'paypal','paid',?,'k')", (NOW,))
        db.execute("INSERT INTO credit_payments VALUES ('paid','c','owner',100,2,50,1)")
        credits.entry(db, "owner", 1000, "admin_grant", "free")
        credits.entry(db, "owner", -1, "verification", "v1")
        credits.entry(db, "owner", 1, "technical_refund", "v2")
        for i, (status, analysis_status) in enumerate([('confirmed','complete'), ('mismatch','complete'), ('inconclusive','complete'), ('inconclusive','failed'), ('processing','pending')]):
            db.execute("INSERT INTO ih_requests(id,owner_id,token,listing,status,created,expires,submitted,plan,analysis_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (str(i), 'owner', 'token'+str(i), '{}', status, NOW, NOW+1000, NOW, '{}', analysis_status))
        db.execute("INSERT INTO ih_requests(id,owner_id,token,listing,created,expires,plan) VALUES ('draft','owner','draft','{}',?,?,'{}')", (NOW, NOW+1000))


def test_paid_promotional_and_activity_metrics_are_separate(seeded):
    result = credit_analytics.analytics(7)
    summary = result['summary']
    assert (result['currency'], result['timezone'], len(result['daily'])) == ('USD', 'UTC', 7)
    assert summary['gross_sales_cents'] == 100
    assert summary['refunds_cents'] == 50
    assert summary['net_payments_cents'] == 50
    assert summary['payments_count'] == 1
    assert summary['credits_purchased'] == 2
    assert summary['credits_granted'] == 1000
    assert summary['credits_used'] == 0
    assert summary['current_credit_balance'] == 1002
    assert summary['wallet_accounts'] == 1
    assert summary['verifications_total'] == 5
    assert [summary[k] for k in ('verified','mismatch','inconclusive','failed','pending')] == [1,1,1,1,1]
    assert result['daily'][-1]['gross_sales_cents'] == 100
    assert result['daily'][-1]['verifications'] == 5
    assert all(row['verifications'] == 0 for row in result['daily'][:-1])


def test_utc_window_boundary_and_old_purchase_refund_excluded(seeded):
    since = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
    with credits.database() as db:
        db.execute("UPDATE credit_ledger SET created=? WHERE kind='purchase'", (since-1,))
        db.execute("UPDATE credit_ledger SET created=? WHERE kind='admin_grant'", (since,))
        db.execute("UPDATE ih_requests SET submitted=? WHERE id='0'", (since-1,))
        db.execute("UPDATE ih_requests SET submitted=? WHERE id='1'", (since,))
    result = credit_analytics.analytics(7)
    assert result['start'] == '2026-11-07'
    assert result['summary']['gross_sales_cents'] == result['summary']['refunds_cents'] == 0
    assert result['summary']['credits_granted'] == 1000
    assert result['summary']['verifications_total'] == 4
    assert result['daily'][0]['verifications'] == 1
    assert credit_analytics.analytics(30)['summary']['gross_sales_cents'] == 100


def test_snapshot_does_not_settle_checks_or_call_provider(seeded, monkeypatch):
    monkeypatch.setattr(credits, 'reconcile', lambda *_: pytest.fail('analytics must be read-only'))
    monkeypatch.setattr(credits, 'paypal_call', lambda *_: pytest.fail('no provider API'))
    with credits.database() as db:
        before = db.execute('SELECT COUNT(*) FROM credit_ledger').fetchone()[0]
    credit_analytics.analytics(90)
    with credits.database() as db:
        assert db.execute('SELECT COUNT(*) FROM credit_ledger').fetchone()[0] == before


def test_empty_database_reports_zero_not_fake_data(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCKX_DATA_DIR', str(tmp_path))
    with credits.database():
        pass
    result = credit_analytics.analytics(30)
    assert all(value == 0 for value in result['summary'].values())
    assert len(result['daily']) == 30


@pytest.mark.parametrize('days', [0,1,8,365,-7])
def test_unbounded_ranges_rejected(days):
    with pytest.raises(ValueError):
        credit_analytics.analytics(days)
