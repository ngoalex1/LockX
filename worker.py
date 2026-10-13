"""Background scan orchestration and evidence hashing primitives."""
import hashlib
from datetime import datetime, timezone

from connectors import MarketplaceConnector, SearchProfile


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def score_candidate(profile: SearchProfile, title: str, image_score: float | None = None) -> float:
    """Conservative explainable score; production should add calibrated ML evaluation."""
    haystack = title.lower()
    terms = [profile.brand, profile.model, profile.reference]
    text_hits = sum(bool(term and term.lower() in haystack) for term in terms)
    text_score = text_hits / max(1, sum(bool(x) for x in terms))
    return round((text_score * .65) + ((image_score or 0) * .35), 3)


async def scan_case(profile: SearchProfile, connectors: list[MarketplaceConnector]) -> list[dict]:
    findings: list[dict] = []
    for connector in connectors:
        # Queue infrastructure should enforce connector.rate_limit_policy() prior
        # to this call and record retries/audit events.
        for listing in await connector.search(profile):
            confidence = score_candidate(profile, listing.title)
            if confidence >= .45:
                findings.append({
                    "connector_key": connector.key,
                    "listing": listing,
                    "confidence": confidence,
                    "found_at": datetime.now(timezone.utc).isoformat(),
                })
    return findings
