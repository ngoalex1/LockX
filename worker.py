"""Marketplace scan scoring and evidence primitives."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from connectors import MarketplaceConnector, SearchProfile


def evidence_digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def score_candidate(profile: SearchProfile, title: str, description: str | None = None) -> tuple[float, list[str]]:
    haystack = f"{title} {description or ''}".lower()
    terms = (("brand", profile.brand, .22), ("model", profile.model, .28), ("reference", profile.reference, .35), ("serial", profile.serial_number, .85))
    reasons = [label for label, value, _ in terms if value and value.lower() in haystack]
    score = min(1.0, sum(weight for _, value, weight in terms if value and value.lower() in haystack))
    if "brand" in reasons and "model" in reasons: score = max(score, .55)
    return round(score, 3), reasons


async def scan_case(profile: SearchProfile, connectors: list[MarketplaceConnector]) -> list[dict]:
    findings: list[dict] = []
    for connector in connectors:
        for listing in await connector.search(profile):
            confidence, reasons = score_candidate(profile, listing.title, listing.description)
            if confidence < .45: continue
            captured_at = datetime.now(timezone.utc).isoformat()
            evidence = {"source": connector.key, "external_id": listing.external_id, "url": listing.url, "title": listing.title, "captured_at": captured_at}
            findings.append({"connector_key": connector.key, "listing": listing, "confidence": confidence, "text_reasons": reasons, "image_score": None, "visual_status": "listing_images_available" if listing.image_urls else "no_listing_images", "evidence_sha256": evidence_digest(evidence), "found_at": captured_at})
    return findings
