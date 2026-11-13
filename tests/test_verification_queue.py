"""Durable upload, credit and separate-process queue integration tests."""
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

import credit_wallet as credits
import in_hand as ih
import verification_queue as queue
import verification_worker as worker
from test_in_hand import ALICE, BASE, assessment, create, setup, video
from test_in_hand_fast import chunk, detail, finish
from test_in_hand_recovery import video_start


@pytest.fixture
def durable(setup):
    client, clock, tmp, monkeypatch = setup
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "1")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "gpt-4.1")
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "1")
    monkeypatch.setattr(queue, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    monkeypatch.setattr(ih, "prepare_reference_features", lambda *_: None)
    monkeypatch.setattr(ih, "vision_call", lambda *_args, **_kwargs: assessment())
    ih.limited.__globals__.get("_buckets", {}).clear()
    with credits.database() as db:
        queue.schema(db)
        credits.entry(db, "alice", 3, "admin_grant", str(uuid4()))
    return client, clock, tmp, monkeypatch


def upload(durable, *, variant=0, **listing):
    client, clock, tmp, _ = durable
    response = create(client, auto_publish=True, **listing)
    assert response.status_code == 201, response.text
    record = response.json()
    stage = video_start(client, record)
    assert chunk(client, record, stage, 0, video(tmp, 10, variant)).status_code == 200
    clock[0] += 30  # The final upload took longer than the actual recording.
    response = finish(client, record, stage, recording_seconds=10)
    assert response.status_code == 202, response.text
    return record, stage, response.json()


def accounting(request_id):
    with credits.database() as db:
        check = dict(db.execute("SELECT * FROM credit_checks WHERE request_id=?", (request_id,)).fetchone())
        balance = db.execute("SELECT SUM(delta) FROM credit_ledger WHERE owner_id='alice'").fetchone()[0]
        reservations = db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification' AND owner_id='alice'").fetchone()[0]
        refunds = db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='technical_refund' AND owner_id='alice'").fetchone()[0]
    return check, balance, reservations, refunds


def test_receipt_commits_all_evidence_job_and_one_credit_before_any_ai(durable):
    client, _, _, monkeypatch = durable
    calls = []
    monkeypatch.setattr(ih, "vision_call", lambda *_a, **_k: calls.append(True))
    record, stage, receipt = upload(durable)
    assert receipt["queue"]["state"] == "queued" and receipt["status"] == "processing"
    assert calls == []
    with credits.database() as db:
        job = db.execute("SELECT * FROM verification_jobs WHERE request_id=?", (record["id"],)).fetchone()
        saved = json.loads(job["manifest"])
        assert len(saved["media"]) == 5 and saved["model"] == "gpt-4.1"
        session = db.execute("SELECT * FROM ih_sessions WHERE id=?", (stage["session_id"],)).fetchone()
        assert saved["captured_at"] == session["finished"] == session["started"] + 10
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='video'", (record["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='frame'", (record["id"],)).fetchone()[0] == 0
    check, balance, reservations, refunds = accounting(record["id"])
    assert (check["state"], balance, reservations, refunds) == ("reserved", 2, 1, 0)
    # Recovering a lost finish response never creates a second job or charge.
    duplicate = finish(client, record, stage, recording_seconds=10)
    assert duplicate.status_code == 202 and duplicate.json()["queue"]["state"] == "queued"
    assert accounting(record["id"])[1:] == (2, 1, 0)


def test_separate_worker_decodes_compares_publishes_once_and_owner_sees_queue(durable):
    client, _, _, monkeypatch = durable
    record, _, _ = upload(durable)
    calls = []
    monkeypatch.setattr(ih, "vision_call", lambda *_a, **_k: (calls.append(True), assessment())[1])
    assert worker.run_once("integration-worker") is True
    assert worker.run_once("integration-worker") is False
    final = detail(client, record)
    assert final["status"] == "confirmed" and final["queue"]["state"] == "completed"
    assert final["publication_status"] == "ready"
    assert calls == [True]
    check, balance, reservations, refunds = accounting(record["id"])
    assert (check["state"], balance, reservations, refunds) == ("consumed", 2, 1, 0)
    phone = client.get(BASE + f"/seller/{record['token']}/result").json()
    assert phone["queue"]["state"] == "completed"
    assert not {"manifest", "fence", "lease_owner", "owner_id"}.intersection(phone["queue"])
    assert client.get(BASE + f"/requests/{record['id']}", headers={"Authorization": "Bearer bob"}).status_code == 404


def test_transient_timeout_retries_saved_evidence_without_second_credit(durable):
    client, clock, _, monkeypatch = durable
    record, _, _ = upload(durable)
    calls = []
    def provider(*_a, **_k):
        calls.append(True)
        if len(calls) == 1:
            raise httpx.ReadTimeout("local fake timeout")
        return assessment()
    monkeypatch.setattr(ih, "vision_call", provider)
    assert worker.run_once("first")
    waiting = detail(client, record)
    assert waiting["queue"]["state"] == "retrying" and waiting["analysis_status"] == "queued"
    assert accounting(record["id"])[1:] == (2, 1, 0)
    clock[0] = waiting["queue"]["retry_at"] + .1
    assert worker.run_once("retry")
    assert detail(client, record)["queue"]["state"] == "completed"
    assert accounting(record["id"])[1:] == (2, 1, 0) and len(calls) == 2


def test_complete_mismatch_is_terminal_and_never_rerolled(durable):
    client, clock, _, monkeypatch = durable
    record, _, _ = upload(durable)
    calls = []
    result = assessment(same_item="contradicted", photos=[{"photo_index": i, "finding": "contradicted", "evidence": "A different physical item.", "frame_indices": [i]} for i in range(4)])
    monkeypatch.setattr(ih, "vision_call", lambda *_a, **_k: (calls.append(True), result)[1])
    worker.run_once("worker")
    clock[0] += 600
    assert worker.run_once("later") is False
    final = detail(client, record)
    assert final["status"] == "mismatch" and final["queue"]["state"] == "completed"
    assert client.post(BASE + f"/requests/{record['id']}/analyze", headers=ALICE).status_code == 409
    assert len(calls) == 1 and accounting(record["id"])[0]["state"] == "consumed"


def test_nonretryable_provider_error_restores_once_and_retains_evidence(durable):
    client, _, _, monkeypatch = durable
    record, _, _ = upload(durable)
    request = httpx.Request("POST", "https://example.invalid/never-called")
    error = httpx.HTTPStatusError("fake billing error", request=request,
        response=httpx.Response(429, request=request, json={"error": {"code": "insufficient_quota"}}))
    monkeypatch.setattr(ih, "vision_call", lambda *_a, **_k: (_ for _ in ()).throw(error))
    worker.run_once("worker")
    assert worker.run_once("later") is False
    assert detail(client, record)["queue"]["state"] == "failed"
    assert accounting(record["id"])[1:] == (3, 1, 1)
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='video'", (record["id"],)).fetchone()[0] == 1


def test_competing_process_claims_cannot_own_same_job(durable):
    record, _, _ = upload(durable)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(queue.claim_job, ["worker-a", "worker-b", "worker-c", "worker-d"]))
    winners = [claim for claim in claims if claim]
    assert len(winners) == 1 and winners[0]["request_id"] == record["id"]


def test_fifo_order_and_wait_expiry_restore_exactly_once(durable):
    _, clock, _, _ = durable
    first, _, _ = upload(durable, variant=0)
    second, _, _ = upload(durable, variant=1)
    assert queue.claim_job("worker")["request_id"] == first["id"]
    clock[0] += 86401
    assert queue.claim_job("later") is None
    assert queue.claim_job("later-again") is None
    with credits.database() as db:
        assert all(r[0] == "failed" for r in db.execute("SELECT state FROM verification_jobs"))
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='technical_refund'").fetchone()[0] == 2
        assert db.execute("SELECT SUM(delta) FROM credit_ledger WHERE owner_id='alice'").fetchone()[0] == 3


def test_sse_revision_changes_when_only_queue_changes(durable):
    record, _, _ = upload(durable)
    initial = ih.seller_event_state(record["token"])
    assert initial["queue"]["state"] == "queued"
    queue.claim_job("worker")
    running = ih.seller_event_state(record["token"], initial)
    assert running["revision"] != initial["revision"] and running["queue"]["state"] == "running"


def test_disk_guard_rolls_back_finish_without_credit_or_job(durable):
    client, clock, tmp, monkeypatch = durable
    record = create(client).json()
    stage = video_start(client, record)
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    clock[0] += 10.1
    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    response = finish(client, record, stage, recording_seconds=10)
    assert response.status_code == 503
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM verification_jobs").fetchone()[0] == 0
        assert db.execute("SELECT SUM(delta) FROM credit_ledger WHERE owner_id='alice'").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE role='video'").fetchone()[0] == 0


def test_worker_retirement_finishes_current_job_and_never_claims_another(monkeypatch):
    stop, retire = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(queue, "enabled", lambda: True)
    def one_job(_worker_id):
        calls.append("job-start")
        retire.set()  # Manager shrinks the pool while this job is running.
        calls.append("job-complete")
        return True
    monkeypatch.setattr(worker, "run_once", one_job)
    worker.worker_loop(stop, retire)
    assert calls == ["job-start", "job-complete"] and not stop.is_set()


def test_durable_job_is_consumed_in_a_distinct_os_process_without_network(durable):
    client, _, tmp, _ = durable
    record, _, _ = upload(durable)
    with credits.database() as db:
        db.execute("UPDATE verification_jobs SET next_run=0 WHERE request_id=?", (record["id"],))
    result_json = assessment().model_dump_json()
    script = "\n".join([
        "import os, in_hand as ih, verification_worker as worker",
        "ih.vision_call=lambda *_a, **_k: ih.VisualAssessment.model_validate_json(" + repr(result_json) + ")",
        "assert worker.run_once('separate-test-process')",
        "print('completed-by-pid',os.getpid())",
    ])
    environment = dict(os.environ, LOCKX_DATA_DIR=str(tmp), OPENAI_API_KEY="local-test-placeholder")
    response = subprocess.run([sys.executable, "-c", script], cwd=Path(worker.__file__).parent,
                              env=environment, capture_output=True, text=True, timeout=30)
    assert response.returncode == 0, response.stderr
    assert response.stdout.strip() == "completed-by-pid " + response.stdout.strip().split()[-1]
    assert int(response.stdout.strip().split()[-1]) != os.getpid()
    assert detail(client, record)["queue"]["state"] == "completed"
    assert accounting(record["id"])[1:] == (2, 1, 0)
