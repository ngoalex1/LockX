"""Approved marketplace connector registry.

Every connector in this module uses an official API or a contractually
permitted data feed. There is deliberately no scraping, login automation,
CAPTCHA handling, or rate-limit circumvention here.
"""
from __future__ import annotations

import base64
import os
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class SearchProfile:
    case_id: str
    brand: str
    model: str
    reference: str | None
    serial_number: str | None
    distinctive_details: str | None

    def queries(self) -> list[str]:
        """Small, explainable query set that stays within a source's quota."""
        core = " ".join(part for part in (self.brand, self.model) if part).strip()
        queries = [" ".join(part for part in (core, self.reference) if part).strip(), core]
        if self.serial_number:
            queries.append(" ".join(part for part in (self.brand, self.serial_number) if part))
        return list(dict.fromkeys(query for query in queries if query))


@dataclass(frozen=True)
class NormalizedListing:
    external_id: str
    url: str
    title: str
    description: str | None
    price: str | None
    currency: str | None
    location: str | None
    image_urls: list[str]
    raw: dict


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    name: str
    access: str
    status: str
    description: str
    supports_text: bool
    supports_listing_images: bool
    owner_photo_sharing: str
    credential_environment: tuple[str, ...] = ()

    def public(self) -> dict:
        return asdict(self) | {
            "configured": bool(self.credential_environment) and all(os.getenv(key) for key in self.credential_environment),
            "policy": "official_api_or_authorized_feed_only",
        }


SOURCE_CATALOG = (
    SourceDefinition("ebay_browse", "eBay", "official_api", "awaiting_credentials", "Browse API keyword results; image search is considered only after explicit owner consent.", True, True, "explicit_consent_required", ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")),
    SourceDefinition("chrono24_partner", "Chrono24", "partner_or_written_authorization_required", "access_required", "Connector reserved for a Chrono24-approved partnership or permitted feed.", True, True, "written_terms_and_owner_consent_required"),
    SourceDefinition("facebook_marketplace", "Facebook Marketplace", "approved_meta_access_required", "access_required", "Inactive unless Meta provides approved marketplace listing access for this use case.", False, False, "not_available"),
    SourceDefinition("craigslist", "Craigslist", "approved_feed_required", "not_connected", "No automated monitoring is performed without a permitted feed or written authorization.", False, False, "not_available"),
    SourceDefinition("auction_dealer_feed", "Auction & dealer feeds", "licensed_or_partner_feed", "access_required", "Normalized connector for approved auction houses, dealers, and watch marketplaces.", True, True, "contract_and_owner_consent_required"),
)


class MarketplaceConnector(Protocol):
    key: str
    async def search(self, profile: SearchProfile) -> list[NormalizedListing]: ...
    def rate_limit_policy(self) -> dict: ...


class EbayBrowseConnector:
    """Official eBay Browse API connector, activated only with app credentials."""
    key = "ebay_browse"
    token_url = "https://api.ebay.com/identity/v1/oauth2/token"
    search_url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    def __init__(self, client_id: str, client_secret: str, marketplace_id: str = "EBAY_US"):
        self.client_id, self.client_secret, self.marketplace_id = client_id, client_secret, marketplace_id

    def rate_limit_policy(self) -> dict:
        return {"requests_per_minute": 20, "backoff": "exponential", "honor_retry_after": True}

    async def _token(self, client: httpx.AsyncClient) -> str:
        encoded = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = await client.post(self.token_url, headers={"Authorization": f"Basic {encoded}", "Content-Type": "application/x-www-form-urlencoded"}, data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
        response.raise_for_status()
        return response.json()["access_token"]

    async def search(self, profile: SearchProfile) -> list[NormalizedListing]:
        seen: set[str] = set(); results: list[NormalizedListing] = []
        async with httpx.AsyncClient(timeout=20) as client:
            token = await self._token(client)
            headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id}
            for query in profile.queries():
                response = await client.get(self.search_url, headers=headers, params={"q": query, "limit": 25})
                response.raise_for_status()
                for item in response.json().get("itemSummaries", []):
                    external_id = item.get("itemId")
                    if not external_id or external_id in seen: continue
                    seen.add(external_id)
                    images = [entry["imageUrl"] for entry in [item.get("image"), *item.get("additionalImages", [])] if entry and entry.get("imageUrl")]
                    price, location = item.get("price") or {}, item.get("itemLocation") or {}
                    results.append(NormalizedListing(external_id, item.get("itemWebUrl") or item.get("itemAffiliateWebUrl") or "", item.get("title") or "Untitled eBay listing", item.get("shortDescription"), price.get("value"), price.get("currency"), ", ".join(part for part in (location.get("city"), location.get("stateOrProvince"), location.get("country")) if part), images, item))
        return results


def configured_connectors() -> list[MarketplaceConnector]:
    client_id, client_secret = os.getenv("EBAY_CLIENT_ID"), os.getenv("EBAY_CLIENT_SECRET")
    return [EbayBrowseConnector(client_id, client_secret, os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US"))] if client_id and client_secret else []


def source_catalog() -> list[dict]:
    return [source.public() for source in SOURCE_CATALOG]
