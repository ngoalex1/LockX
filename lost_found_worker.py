"""Recover durable photo jobs after a service restart.

Run once with the same LOCKX_DATA_DIR and credentials as the API service.
Use --retry-failed only deliberately: it may make new paid vision requests.
"""
import argparse
from lost_found import database, process_sighting


def run(retry_failed=False):
    with database() as db:
        if retry_failed:
            # The operator must ensure no still-running task owns these leases.
            db.execute("UPDATE sightings SET analysis_status='pending' WHERE analysis_status IN ('processing','analysis_failed','media_failed','manual_review')")
        ids = [r[0] for r in db.execute("SELECT id FROM sightings WHERE analysis_status='pending'")]
    for sighting_id in ids:
        process_sighting(sighting_id)
    print(f"Processed {len(ids)} pending finder reports.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true")
    run(parser.parse_args().retry_failed)
