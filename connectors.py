"""Compliant marketplace connector contract.

No connector may use browser automation to bypass authentication, CAPTCHAs,
rate limits, robots directives, or marketplace terms. Implementers provide an
official API client or a contractually-permitted feed in `search`.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchProfile:
    case_id: str
    brand: str
    model: str
    reference: str | None
    serial_number: str | None
    distinctive_details: str | None


@dataclass(frozen=True)
class NormalizedListing:
    external_id: str
    url: str
    title: str
    description: str | None
    price: str | None
    location: str | None
    image_urls: list[str]
    raw: dict


class MarketplaceConnector(Protocol):
    key: str

    async def health(self) -> dict: ...
    async def search(self, profile: SearchProfile) -> list[NormalizedListing]: ...
    def rate_limit_policy(self) -> dict: ...


class OfficialApiConnector:
    """Base class for a source already authorized through its official API."""
    key = "official-api-example"

    async def health(self) -> dict:
        return {"key": self.key, "status": "not_configured", "access": "official_api_only"}

    async def search(self, profile: SearchProfile) -> list[NormalizedListing]:
        # Install an authenticated, source-specific SDK/client here. This base
        # intentionally returns nothing until credentials and terms are approved.
        return []

    def rate_limit_policy(self) -> dict:
        return {"requests_per_minute": 30, "backoff": "exponential", "honor_retry_after": True}
