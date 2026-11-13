"""Separate bounded process workers for the single-volume verification queue."""
import argparse
import logging
import multiprocessing
import os
import signal
import threading
import time
from uuid import uuid4

# Set before importing OpenCV or starting image-rendering threads.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import verification_queue as queue

log = logging.getLogger("lockx.verification.worker")


def run_once(worker_id=None):
    worker_id = worker_id or str(uuid4())
    claim = queue.claim_job(worker_id)
    if not claim:
        return False
    stop = threading.Event()
    def renew():
        while not stop.wait(min(10, queue.lease_seconds()/3)):
            try:
                queue.heartbeat(claim)
            except queue.LeaseLost:
                return
            except Exception:
                log.warning("Verification heartbeat will retry")
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    context = queue.CURRENT_CLAIM.set(claim)
    error = None
    try:
        import in_hand as ih
        with queue.database() as db:
            db.execute("BEGIN IMMEDIATE")
            queue.ensure_current(db,claim)
            row = db.execute("SELECT * FROM ih_requests WHERE id=?", (claim["request_id"],)).fetchone()
            if row["analysis_status"] == "complete":
                mode = "publish"
            else:
                frames = db.execute("SELECT 1 FROM ih_media WHERE request_id=? AND role='frame'", (claim["request_id"],)).fetchone()
                mode = "compare" if frames else "decode"
                db.execute("UPDATE ih_requests SET analysis_status=? WHERE id=?", ("pending" if frames else "decoding",claim["request_id"]))
        if mode == "publish":
            ih.auto_publish_confirmed(claim["request_id"],queue_claim=claim)
        elif mode == "decode":
            ih.finish_scan_background(claim["request_id"],claim["session_id"],queue_claim=claim)
        else:
            ih.analyze(claim["request_id"],queue_claim=claim)
    except queue.LeaseLost:
        return True
    except Exception as exc:
        error = exc
        # Never log provider bodies, evidence, URLs, tokens or exception text.
        log.warning("Verification attempt did not complete (%s)",type(exc).__name__)
    finally:
        queue.CURRENT_CLAIM.reset(context)
        stop.set()
        thread.join(timeout=2)
    queue.finish_job(claim,error)
    return True


def worker_loop(stop, retire=None):
    import cv2
    cv2.setNumThreads(1)
    worker_id = str(uuid4())
    while not stop.is_set() and not (retire and retire.is_set()):
        if not queue.enabled():
            stop.wait(2)
            continue
        try:
            if not run_once(worker_id):
                queue.heartbeat(worker_id=worker_id)
                stop.wait(1)
        except Exception as exc:
            log.warning("Verification worker will recover its durable lease (%s)",type(exc).__name__)
            stop.wait(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        run_once()
        return
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    for name in (signal.SIGTERM,signal.SIGINT):
        signal.signal(name,lambda *_:stop.set())
    children = []
    try:
        while not stop.is_set():
            alive = []
            for process,retire in children:
                if process.is_alive():
                    alive.append((process,retire))
                else:
                    process.join()
            children = alive
            status = queue.admin_status()
            backlog = sum(status["states"][state] for state in queue.ACTIVE)
            target = queue.desired_workers(backlog)
            nonretiring = [(process,retire) for process,retire in children if not retire.is_set()]
            for process,retire in nonretiring[target:]:
                retire.set()  # Finish the current durable job, then leave the pool.
            while sum(not retire.is_set() for _,retire in children) < target and len(children) < queue.max_workers():
                retire = context.Event()
                process = context.Process(target=worker_loop,args=(stop,retire),daemon=False)
                process.start()
                children.append((process,retire))
            stop.wait(3)
    finally:
        stop.set()
        deadline = time.monotonic()+20
        for process,_ in children:
            process.join(timeout=max(0,deadline-time.monotonic()))
        for process,_ in children:
            if process.is_alive():
                process.terminate()
        for process,_ in children:
            process.join(timeout=2)


if __name__ == "__main__":
    main()
