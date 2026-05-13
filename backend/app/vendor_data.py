from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .schemas import PoiCandidate


VENDOR_FIELDS = {
    "address",
    "price_per_person",
    "rating",
    "review_count",
    "rating_source",
    "image_url",
    "photo_source",
    "platform_url",
    "merchant_id",
    "merchant_source",
    "deal_summary",
    "description",
}

FIELD_ALIASES = {
    "avg_price": "price_per_person",
    "average_price": "price_per_person",
    "photo_url": "image_url",
    "shop_url": "platform_url",
    "booking_url": "platform_url",
    "url": "platform_url",
    "source": "merchant_source",
    "provider": "merchant_source",
    "deal": "deal_summary",
    "coupon": "deal_summary",
}


def apply_vendor_data(pois: list[PoiCandidate]) -> list[PoiCandidate]:
    data_path = os.getenv("CITYMATE_VENDOR_DATA_PATH", "")
    if not data_path:
        return pois
    path = Path(data_path)
    if not path.exists():
        return pois
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    by_name = _normalize_payload(payload)
    enriched: list[PoiCandidate] = []
    for poi in pois:
        patch = by_name.get(poi.name) or by_name.get(poi.id) or by_name.get(poi.merchant_id)
        if patch:
            enriched.append(poi.model_copy(update={key: value for key, value in patch.items() if key in VENDOR_FIELDS and value not in (None, "")}))
        else:
            enriched.append(poi)
    return enriched


def _normalize_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("pois", payload.get("shops", []))
        if isinstance(items, dict):
            normalized: dict[str, dict[str, Any]] = {}
            for name, value in items.items():
                if isinstance(value, dict):
                    patch = _normalize_patch(value, fallback_name=str(name))
                    _add_patch_keys(normalized, patch)
            return normalized
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict):
            patch = _normalize_patch(item)
            _add_patch_keys(result, patch)
    return result


def _normalize_patch(item: dict[str, Any], fallback_name: str = "") -> dict[str, Any]:
    patch = dict(item)
    if fallback_name and not patch.get("name"):
        patch["name"] = fallback_name
    for source, target in FIELD_ALIASES.items():
        if source in patch and target not in patch:
            patch[target] = patch[source]
    return patch


def _add_patch_keys(target: dict[str, dict[str, Any]], patch: dict[str, Any]) -> None:
    keys = [
        patch.get("name"),
        patch.get("id"),
        patch.get("poi_id"),
        patch.get("source_poi_id"),
        patch.get("merchant_id"),
    ]
    for key in keys:
        if key not in (None, ""):
            target[str(key)] = patch


class VendorDataClient:
    def __init__(self, settings: Settings) -> None:
        self.api_url = settings.vendor_api_url.rstrip("/")
        self.api_key = settings.vendor_api_key
        self.api_key_header = settings.vendor_api_key_header
        self.timeout = settings.request_timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_url)

    async def enrich_pois(self, pois: list[PoiCandidate], city: str) -> tuple[list[PoiCandidate], list[str]]:
        if not self.enabled or not pois:
            return pois, []
        warnings: list[str] = []
        try:
            payload = await self._fetch(city, pois)
        except Exception:
            return pois, ["授权商家 API 暂不可用，已保留地图和本地数据。"]
        patches = _normalize_payload(payload)
        if not patches:
            return pois, warnings
        enriched: list[PoiCandidate] = []
        for poi in pois:
            patch = patches.get(poi.name) or patches.get(poi.id)
            if patch:
                enriched.append(
                    poi.model_copy(
                        update={key: value for key, value in patch.items() if key in VENDOR_FIELDS and value not in (None, "")}
                    )
                )
            else:
                enriched.append(poi)
        return enriched, warnings

    async def _fetch(self, city: str, pois: list[PoiCandidate]) -> Any:
        headers = {"Accept": "application/json"}
        if self.api_key:
            if self.api_key_header.lower() == "authorization":
                headers[self.api_key_header] = f"Bearer {self.api_key}"
            else:
                headers[self.api_key_header] = self.api_key
        body = {
            "city": city,
            "pois": [
                {
                    "id": poi.id,
                    "name": poi.name,
                    "category": poi.category,
                    "address": poi.address,
                    "location": {"lat": poi.location.lat, "lng": poi.location.lng},
                }
                for poi in pois
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post(self.api_url, json=body)
            response.raise_for_status()
            return response.json()
