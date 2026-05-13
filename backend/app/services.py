from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from .schemas import Coordinates, PlaceSuggestion, PoiCandidate, WeatherSnapshot
from .seed_data import CITY_CENTERS, SEED_POIS, SHANGHAI_CENTER
from .vendor_data import apply_vendor_data


CATEGORY_IMAGE_FALLBACKS = {
    "cafe": "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=480&q=75",
    "bookstore": "https://images.unsplash.com/photo-1519682337058-a94d519337bc?auto=format&fit=crop&w=480&q=75",
    "exhibition": "https://images.unsplash.com/photo-1564399580075-5dfe19c205f3?auto=format&fit=crop&w=480&q=75",
    "park": "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=480&q=75",
    "walk": "https://images.unsplash.com/photo-1518005020951-eccb494ad742?auto=format&fit=crop&w=480&q=75",
    "dining": "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=480&q=75",
    "market": "https://images.unsplash.com/photo-1533900298318-6b8da08a523e?auto=format&fit=crop&w=480&q=75",
    "mall": "https://images.unsplash.com/photo-1519567241046-7f570eee3ce6?auto=format&fit=crop&w=480&q=75",
    "workshop": "https://images.unsplash.com/photo-1452860606245-08befc0ff44b?auto=format&fit=crop&w=480&q=75",
    "bar": "https://images.unsplash.com/photo-1514933651103-005eec06c04b?auto=format&fit=crop&w=480&q=75",
}

AMAP_POI_TYPES = "050000|060000|080000|110000|140000"
AMAP_V5_EXTRA_FIELDS = "business,photos,indoor,navi"


def _out_of_china(lat: float, lng: float) -> bool:
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lat: float, lng: float) -> Coordinates:
    if _out_of_china(lat, lng):
        return Coordinates(lat=lat, lng=lng)
    earth_radius = 6378245.0
    ee = 0.00669342162296594323
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((earth_radius * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (earth_radius / sqrt_magic * math.cos(rad_lat) * math.pi)
    mg_lat = lat + d_lat
    mg_lng = lng + d_lng
    return Coordinates(lat=lat * 2 - mg_lat, lng=lng * 2 - mg_lng)


def wgs84_to_gcj02(lat: float, lng: float) -> Coordinates:
    if _out_of_china(lat, lng):
        return Coordinates(lat=lat, lng=lng)
    earth_radius = 6378245.0
    ee = 0.00669342162296594323
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((earth_radius * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (earth_radius / sqrt_magic * math.cos(rad_lat) * math.pi)
    return Coordinates(lat=lat + d_lat, lng=lng + d_lng)


def haversine_km(a: Coordinates, b: Coordinates) -> float:
    radius_km = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    d_lat = math.radians(b.lat - a.lat)
    d_lng = math.radians(b.lng - a.lng)
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def estimate_travel_minutes(a: Coordinates, b: Coordinates, mode: str = "transit") -> int:
    km = haversine_km(a, b)
    if mode == "walk":
        minutes = km / 4.2 * 60
    elif mode == "drive":
        minutes = km / 22 * 60 + 6
    else:
        minutes = km / 16 * 60 + 8
    return max(5, min(45, round(minutes)))


def city_center(city: str) -> Coordinates:
    return CITY_CENTERS.get(normalize_city_name(city), SHANGHAI_CENTER)


def normalize_city_name(city: str) -> str:
    cleaned = city.strip()
    for suffix in ("市", "城区", "地区"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned or "上海"


@dataclass
class OpenDataResult:
    pois: list[PoiCandidate]
    warnings: list[str]


class OpenDataClient:
    def __init__(self, timeout: float | None = None, map_provider: str | None = None, amap_key: str | None = None) -> None:
        self.timeout = timeout or float(os.getenv("CITYMATE_REQUEST_TIMEOUT", "6.0"))
        self.map_provider = (map_provider or os.getenv("CITYMATE_MAP_PROVIDER", "open")).lower()
        self.amap_key = amap_key or os.getenv("AMAP_WEB_SERVICE_KEY", os.getenv("CITYMATE_AMAP_KEY", ""))
        self.user_agent = "CityMate-Demo/0.1 (hackathon demo; contact: local)"

    @property
    def amap_enabled(self) -> bool:
        return self.map_provider in {"amap", "gaode"} and bool(self.amap_key)

    async def geocode(self, place: str, city: str) -> Coordinates:
        if self.amap_enabled:
            try:
                return await self._amap_geocode(place, city)
            except Exception:
                pass
        return await self._nominatim_geocode(place, city)

    async def search_places(self, query: str, city: str, limit: int = 8) -> list[PlaceSuggestion]:
        cleaned = query.strip()
        if not cleaned:
            return []
        if self.amap_enabled:
            try:
                suggestions = await self._amap_search_places(cleaned, city, limit)
                if suggestions:
                    return suggestions
            except Exception:
                pass
        return await self._nominatim_search_places(cleaned, city, limit)

    async def weather(self, location: Coordinates) -> WeatherSnapshot:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": location.lat,
            "longitude": location.lng,
            "current": "temperature_2m,weather_code,precipitation",
            "timezone": "Asia/Shanghai",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            current = response.json().get("current", {})
        code = int(current.get("weather_code", 3))
        precipitation = float(current.get("precipitation", 0))
        is_rainy = precipitation > 0 or code in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}
        condition = "有雨" if is_rainy else "多云"
        return WeatherSnapshot(
            condition=condition,
            temperature_c=float(current.get("temperature_2m", 22)),
            is_rainy=is_rainy,
            source="open-meteo",
        )

    async def overpass_pois(self, center: Coordinates, radius_m: int = 3800) -> OpenDataResult:
        if self.amap_enabled:
            try:
                result = await self._amap_pois(center, radius_m)
                if result.pois:
                    return result
            except Exception:
                pass
        return await self._overpass_pois(center, radius_m)

    async def route_minutes(self, points: list[Coordinates]) -> int | None:
        if len(points) < 2:
            return 0
        coords = ";".join(f"{point.lng},{point.lat}" for point in points)
        url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
        params = {"overview": "false", "alternatives": "false", "steps": "false"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            routes = response.json().get("routes", [])
        if not routes:
            return None
        return round(float(routes[0].get("duration", 0)) / 60)

    async def route_geometry(self, points: list[Coordinates], mode: str = "transit", city: str = "") -> list[Coordinates]:
        if len(points) < 2:
            return []
        if self.amap_enabled:
            try:
                geometry = await self._amap_route_geometry(points, mode, city)
                if geometry:
                    return geometry
            except Exception:
                pass
        try:
            return await self._osrm_route_geometry(points)
        except Exception:
            return []

    async def _nominatim_geocode(self, place: str, city: str) -> Coordinates:
        if city and city not in {"中国", "全国"}:
            query = f"{city} {place}".strip()
        else:
            query = f"{place} 中国".strip()
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "cn"}
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not payload:
            return city_center(city)
        return Coordinates(lat=float(payload[0]["lat"]), lng=float(payload[0]["lon"]))

    async def _nominatim_search_places(self, query: str, city: str, limit: int = 8) -> list[PlaceSuggestion]:
        if city and city not in {"中国", "全国"}:
            search_query = f"{city} {query}".strip()
        else:
            search_query = f"{query} 中国".strip()
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": search_query,
            "format": "jsonv2",
            "limit": max(1, min(limit, 10)),
            "countrycodes": "cn",
            "addressdetails": 1,
        }
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        suggestions: list[PlaceSuggestion] = []
        seen: set[str] = set()
        for item in payload:
            display = str(item.get("display_name", "")).strip()
            if not display or "lat" not in item or "lon" not in item:
                continue
            name = str(item.get("name") or display.split(",")[0]).strip()
            key = f"{name}-{item.get('lat')}-{item.get('lon')}"
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                PlaceSuggestion(
                    name=name[:60],
                    address=display,
                    location=Coordinates(lat=float(item["lat"]), lng=float(item["lon"])),
                    source="nominatim",
                )
            )
        return suggestions

    async def _overpass_pois(self, center: Coordinates, radius_m: int = 3800) -> OpenDataResult:
        query = f"""
        [out:json][timeout:8];
        (
          node["amenity"~"cafe|restaurant|bar|theatre|arts_centre"](around:{radius_m},{center.lat},{center.lng});
          node["tourism"~"museum|gallery|attraction"](around:{radius_m},{center.lat},{center.lng});
          node["shop"~"books|mall|craft"](around:{radius_m},{center.lat},{center.lng});
          node["leisure"~"park|garden"](around:{radius_m},{center.lat},{center.lng});
        );
        out body 45;
        """
        warnings: list[str] = []
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            response = await client.post("https://overpass-api.de/api/interpreter", data={"data": query})
            response.raise_for_status()
            payload = response.json()
        pois = [self._overpass_element_to_poi(item) for item in payload.get("elements", [])]
        pois = apply_vendor_data([poi for poi in pois if poi is not None])
        if not pois:
            warnings.append("开放 POI 查询没有返回可用地点，已使用内置数据。")
        return OpenDataResult(pois=pois[:30], warnings=warnings)

    async def _amap_geocode(self, place: str, city: str) -> Coordinates:
        payload = await self._amap_get(
            "/v3/geocode/geo",
            {
                "address": place,
                "city": "" if city in {"中国", "全国"} else city,
            },
        )
        geocodes = payload.get("geocodes") or []
        if not geocodes:
            return city_center(city)
        return self._parse_amap_location(geocodes[0].get("location", ""))

    async def _amap_search_places(self, query: str, city: str, limit: int = 8) -> list[PlaceSuggestion]:
        try:
            payload = await self._amap_get(
                "/v5/place/text",
                {
                    "keywords": query,
                    "region": "" if city in {"中国", "全国"} else city,
                    "city_limit": "true",
                    "page_size": max(1, min(limit, 25)),
                    "page_num": 1,
                    "show_fields": "business",
                },
            )
            suggestions = self._amap_payload_to_place_suggestions(payload, limit)
            if suggestions:
                return suggestions
        except Exception:
            pass
        payload = await self._amap_get(
            "/v3/place/text",
            {
                "keywords": query,
                "city": "" if city in {"中国", "全国"} else city,
                "citylimit": "true",
                "offset": max(1, min(limit, 25)),
                "page": 1,
                "extensions": "base",
            },
        )
        return self._amap_payload_to_place_suggestions(payload, limit)

    def _amap_payload_to_place_suggestions(self, payload: dict[str, Any], limit: int) -> list[PlaceSuggestion]:
        suggestions: list[PlaceSuggestion] = []
        seen: set[str] = set()
        for item in payload.get("pois") or []:
            name = str(item.get("name") or "").strip()
            location = str(item.get("location") or "").strip()
            if not name or not location:
                continue
            key = f"{name}-{location}"
            if key in seen:
                continue
            seen.add(key)
            address = self._amap_address(item)
            suggestions.append(
                PlaceSuggestion(
                    name=name[:60],
                    address=address,
                    location=self._parse_amap_location(location),
                    source="amap",
                )
            )
            if len(suggestions) >= limit:
                break
        return suggestions

    async def _amap_pois(self, center: Coordinates, radius_m: int) -> OpenDataResult:
        try:
            items = await self._amap_poi_items_v5(center, radius_m)
        except Exception:
            return await self._amap_pois_v3(center, radius_m)
        if not items:
            return await self._amap_pois_v3(center, radius_m)
        try:
            detail_items = await self._amap_detail_items([str(item.get("id") or "") for item in items[:20]])
        except Exception:
            detail_items = []
        detail_by_id = {str(item.get("id") or ""): item for item in detail_items}
        merged_items = [self._merge_amap_item(item, detail_by_id.get(str(item.get("id") or ""))) for item in items]
        pois = [self._amap_item_to_poi(item) for item in merged_items]
        pois = apply_vendor_data([poi for poi in pois if poi is not None])
        warnings = [] if pois else ["高德地图 POI 查询没有返回可用地点，已使用内置数据。"]
        return OpenDataResult(pois=pois[:30], warnings=warnings)

    async def amap_keyword_pois(
        self,
        city: str,
        center: Coordinates,
        keywords: list[str],
        radius_m: int = 6500,
        limit_each: int = 6,
    ) -> list[PoiCandidate]:
        if not self.amap_enabled:
            return []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for keyword in keywords[:4]:
            clean = keyword.strip()
            if not clean:
                continue
            try:
                payload = await self._amap_get(
                    "/v5/place/text",
                    {
                        "keywords": clean[:30],
                        "region": "" if city in {"中国", "全国"} else city,
                        "city_limit": "true",
                        "page_size": max(1, min(limit_each, 6)),
                        "page_num": 1,
                        "show_fields": AMAP_V5_EXTRA_FIELDS,
                    },
                )
            except Exception:
                continue
            for item in payload.get("pois") or []:
                poi_id = str(item.get("id") or "")
                location = str(item.get("location") or "")
                key = poi_id or f"{item.get('name')}-{location}"
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
            await asyncio.sleep(0.12)
        try:
            detail_items = await self._amap_detail_items([str(item.get("id") or "") for item in items[:18]])
        except Exception:
            detail_items = []
        detail_by_id = {str(item.get("id") or ""): item for item in detail_items}
        pois = []
        for item in items:
            merged = self._merge_amap_item(item, detail_by_id.get(str(item.get("id") or "")))
            poi = self._amap_item_to_poi(merged)
            if poi is None:
                continue
            if haversine_km(center, poi.location) <= max(2.0, radius_m / 1000):
                pois.append(poi)
        return apply_vendor_data(pois)

    async def _amap_poi_items_v5(self, center: Coordinates, radius_m: int) -> list[dict[str, Any]]:
        gcj_center = wgs84_to_gcj02(center.lat, center.lng)
        radius = max(1000, min(radius_m, 50000))
        base_params: dict[str, object] = {
            "location": f"{gcj_center.lng:.6f},{gcj_center.lat:.6f}",
            "radius": radius,
            "sortrule": "weight",
            "page_num": 1,
            "show_fields": AMAP_V5_EXTRA_FIELDS,
        }
        type_queries = [AMAP_POI_TYPES, "050000", "060000", "080000", "110000", "140000"]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, type_query in enumerate(type_queries):
            payload = await self._amap_get(
                "/v5/place/around",
                {
                    **base_params,
                    "types": type_query,
                    "page_size": 25 if index == 0 else 10,
                },
            )
            for item in payload.get("pois") or []:
                poi_id = str(item.get("id") or "")
                location = str(item.get("location") or "")
                key = poi_id or f"{item.get('name')}-{location}"
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(item)
        return items

    async def _amap_detail_items(self, poi_ids: list[str]) -> list[dict[str, Any]]:
        detail_items: list[dict[str, Any]] = []
        ids = [poi_id for poi_id in poi_ids if poi_id]
        for start in range(0, len(ids), 10):
            chunk = ids[start : start + 10]
            payload = await self._amap_get(
                "/v5/place/detail",
                {
                    "id": "|".join(chunk),
                    "show_fields": AMAP_V5_EXTRA_FIELDS,
                },
            )
            detail_items.extend(item for item in payload.get("pois") or [] if isinstance(item, dict))
        return detail_items

    def _merge_amap_item(self, base: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
        if not detail:
            return base
        merged = dict(base)
        for key, value in detail.items():
            if value not in (None, "", []):
                merged[key] = value
        return merged

    async def _amap_pois_v3(self, center: Coordinates, radius_m: int) -> OpenDataResult:
        gcj_center = wgs84_to_gcj02(center.lat, center.lng)
        payload = await self._amap_get(
            "/v3/place/around",
            {
                "location": f"{gcj_center.lng:.6f},{gcj_center.lat:.6f}",
                "radius": max(1000, min(radius_m, 50000)),
                "types": AMAP_POI_TYPES,
                "sortrule": "weight",
                "offset": 25,
                "page": 1,
                "extensions": "all",
            },
        )
        pois = [self._amap_item_to_poi(item) for item in payload.get("pois") or []]
        pois = apply_vendor_data([poi for poi in pois if poi is not None])
        warnings = [] if pois else ["高德地图 POI 查询没有返回可用地点，已使用内置数据。"]
        return OpenDataResult(pois=pois[:30], warnings=warnings)

    async def _amap_route_geometry(self, points: list[Coordinates], mode: str, city: str) -> list[Coordinates]:
        converted = [wgs84_to_gcj02(point.lat, point.lng) for point in points]
        origin = converted[0]
        destination = converted[-1]
        waypoints = converted[1:-1]
        endpoint = "/v3/direction/walking" if mode == "walk" and not waypoints else "/v3/direction/driving"
        params: dict[str, object] = {
            "origin": f"{origin.lng:.6f},{origin.lat:.6f}",
            "destination": f"{destination.lng:.6f},{destination.lat:.6f}",
            "extensions": "base",
        }
        if endpoint.endswith("driving") and waypoints:
            params["waypoints"] = ";".join(f"{point.lng:.6f},{point.lat:.6f}" for point in waypoints)
            params["strategy"] = 2
        payload = await self._amap_get(endpoint, params)
        paths = (payload.get("route") or {}).get("paths") or []
        if not paths:
            return []
        coordinates: list[Coordinates] = []
        for step in paths[0].get("steps") or []:
            coordinates.extend(self._parse_amap_polyline(step.get("polyline", "")))
        return _dedupe_coordinates(coordinates)

    async def _osrm_route_geometry(self, points: list[Coordinates]) -> list[Coordinates]:
        coords = ";".join(f"{point.lng},{point.lat}" for point in points)
        url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
        params = {"overview": "full", "geometries": "geojson", "alternatives": "false", "steps": "false"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            routes = response.json().get("routes", [])
        if not routes:
            return []
        raw_coordinates = routes[0].get("geometry", {}).get("coordinates", [])
        return [Coordinates(lat=float(lat), lng=float(lng)) for lng, lat in raw_coordinates if lng is not None and lat is not None]

    async def _amap_get(self, path: str, params: dict[str, object]) -> dict[str, Any]:
        request_params = {"key": self.amap_key, "output": "JSON", **params}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"https://restapi.amap.com{path}", params=request_params)
            response.raise_for_status()
            payload = response.json()
        if str(payload.get("status")) != "1":
            message = payload.get("info") or payload.get("infocode") or "amap request failed"
            raise RuntimeError(str(message))
        return payload

    def _amap_item_to_poi(self, item: dict[str, Any]) -> PoiCandidate | None:
        name = str(item.get("name") or "").strip()
        location = str(item.get("location") or "").strip()
        if not name or not location:
            return None
        category = self._category_from_amap(item)
        price = self._price_from_amap(item)
        rating = self._rating_from_amap(item)
        image_url = self._photo_url_from_amap(item)
        indoor = bool(item.get("indoor_map") == "1" or category not in {"park", "walk", "market"})
        indoor_payload = item.get("indoor") if isinstance(item.get("indoor"), dict) else {}
        indoor = bool(indoor_payload.get("indoor_map") == "1" or indoor)
        business_area = self._business_area_from_amap(item)
        tags = self._amap_tags(item, category, indoor, business_area)
        return PoiCandidate(
            id=f"amap-{item.get('id')}",
            name=name[:40],
            category=category,
            location=self._parse_amap_location(location),
            address=self._amap_address(item),
            price_per_person=price,
            rating=rating,
            review_count=0,
            rating_source="amap_poi" if rating is not None else "",
            popularity=min(0.86, max(0.45, (rating or 4.2) / 5 + 0.06)),
            novelty={"bookstore": 0.68, "exhibition": 0.66, "workshop": 0.72, "walk": 0.62}.get(category, 0.52),
            tags=tags,
            indoor=indoor,
            opening_hours=self._opening_hours_from_amap(item),
            phone=self._phone_from_amap(item),
            business_area=business_area,
            source="amap",
            image_url=image_url,
            photo_source="amap_photo" if image_url else "",
            platform_url=str(item.get("website") or ""),
            merchant_id=str(item.get("id") or ""),
            merchant_source="amap",
            description=self._amap_description(item, category),
        )

    def _parse_amap_location(self, value: str) -> Coordinates:
        lng_text, lat_text = value.split(",", 1)
        return gcj02_to_wgs84(float(lat_text), float(lng_text))

    def _parse_amap_polyline(self, value: str) -> list[Coordinates]:
        coordinates: list[Coordinates] = []
        for pair in str(value or "").split(";"):
            if "," not in pair:
                continue
            try:
                coordinates.append(self._parse_amap_location(pair))
            except ValueError:
                continue
        return coordinates

    def _amap_address(self, item: dict[str, Any]) -> str:
        pieces = [item.get("pname"), item.get("cityname"), item.get("adname"), item.get("address")]
        return "".join(self._clean_amap_text(piece) for piece in pieces if self._clean_amap_text(piece))

    def _rating_from_amap(self, item: dict[str, Any]) -> float | None:
        business = self._amap_business(item)
        try:
            raw = business.get("rating")
            if raw in (None, "", [], "[]"):
                return None
            return max(0.0, min(5.0, float(raw)))
        except (TypeError, ValueError):
            return None

    def _price_from_amap(self, item: dict[str, Any]) -> int | None:
        business = self._amap_business(item)
        try:
            raw = business.get("cost")
            if raw in (None, "", [], "[]"):
                return None
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if value > 0:
            return max(0, round(value))
        return None

    def _amap_business(self, item: dict[str, Any]) -> dict[str, Any]:
        business = item.get("business") if isinstance(item.get("business"), dict) else {}
        biz_ext = item.get("biz_ext") if isinstance(item.get("biz_ext"), dict) else {}
        return {**biz_ext, **business}

    def _clean_amap_text(self, value: Any) -> str:
        if value in (None, "", [], "[]"):
            return ""
        if isinstance(value, list):
            return "、".join(str(part).strip() for part in value if str(part).strip())
        return str(value).strip()

    def _photo_url_from_amap(self, item: dict[str, Any]) -> str:
        photos = item.get("photos") if isinstance(item.get("photos"), list) else []
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            url = self._clean_amap_text(photo.get("url"))
            if url.startswith(("http://", "https://")):
                return url
        return ""

    def _opening_hours_from_amap(self, item: dict[str, Any]) -> str:
        business = self._amap_business(item)
        for key in ("opentime_week", "opentime_today", "opentime2", "open_time"):
            value = self._clean_amap_text(business.get(key))
            if value:
                return value[:120]
        return ""

    def _phone_from_amap(self, item: dict[str, Any]) -> str:
        value = self._clean_amap_text(self._amap_business(item).get("tel") or item.get("tel"))
        return value[:80]

    def _business_area_from_amap(self, item: dict[str, Any]) -> str:
        value = self._clean_amap_text(self._amap_business(item).get("business_area") or item.get("business_area"))
        return value[:40]

    def _amap_tags(self, item: dict[str, Any], category: str, indoor: bool, business_area: str) -> list[str]:
        business = self._amap_business(item)
        candidates = [category, "高德地图"]
        type_text = self._clean_amap_text(item.get("type"))
        if type_text:
            candidates.append(type_text.split(";")[-1])
        for key in ("keytag", "rectag"):
            value = self._clean_amap_text(business.get(key))
            if value:
                candidates.append(value)
        for tag in self._clean_amap_text(business.get("tag")).replace("，", ",").split(",")[:4]:
            if tag.strip():
                candidates.append(tag.strip())
        if business_area:
            candidates.append(f"{business_area}商圈")
        candidates.append("室内" if indoor else "户外")
        tags: list[str] = []
        for tag in candidates:
            clean = tag.strip()[:24]
            if clean and clean not in tags:
                tags.append(clean)
        return tags

    def _amap_description(self, item: dict[str, Any], category: str) -> str:
        category_labels = {
            "cafe": "咖啡/茶饮地点",
            "bookstore": "书店或阅读空间",
            "exhibition": "文化展览地点",
            "market": "街区或休闲地点",
            "walk": "城市漫游地点",
            "mall": "商场或综合体",
            "dining": "餐饮地点",
            "park": "公园绿地",
            "workshop": "体验类地点",
            "bar": "小酒馆",
        }
        business = self._amap_business(item)
        parts = [category_labels.get(category, "本地生活地点")]
        for key in ("keytag", "rectag"):
            value = self._clean_amap_text(business.get(key))
            if value:
                parts.append(value[:30])
                break
        type_text = self._clean_amap_text(item.get("type")).split(";")[-1]
        if type_text:
            parts.append(type_text)
        business_area = self._business_area_from_amap(item)
        if business_area:
            parts.append(f"{business_area}周边")
        return " · ".join(dict.fromkeys(part for part in parts if part))

    def _category_from_amap(self, item: dict[str, Any]) -> str:
        typed_text = f"{item.get('type', '')} {item.get('typecode', '')}"
        full_text = f"{typed_text} {item.get('name', '')}"
        if any(word in full_text for word in ["咖啡", "茶艺", "茶馆"]):
            return "cafe"
        if any(word in full_text for word in ["酒吧", "酒馆"]):
            return "bar"
        if any(word in typed_text for word in ["餐饮", "中餐", "西餐", "小吃", "美食", "快餐", "餐厅", "冷饮", "甜品"]):
            return "dining"
        if any(word in full_text for word in ["书店", "图书"]):
            return "bookstore"
        if any(word in full_text for word in ["博物馆", "美术馆", "展览", "艺术", "剧场", "文化"]):
            return "exhibition"
        if any(word in typed_text for word in ["公园", "植物园", "风景名胜", "景区"]):
            return "park"
        if any(word in typed_text for word in ["商场", "购物中心", "百货", "购物服务"]):
            return "mall"
        if any(word in full_text for word in ["手工", "DIY", "体验", "工坊"]):
            return "workshop"
        return "market"

    def _overpass_element_to_poi(self, item: dict[str, Any]) -> PoiCandidate | None:
        tags = item.get("tags", {})
        name = tags.get("name") or tags.get("name:zh") or tags.get("name:en")
        if not name or "lat" not in item or "lon" not in item:
            return None
        category = self._category_from_tags(tags)
        indoor = category not in {"park", "walk", "market"}
        return PoiCandidate(
            id=f"osm-{item.get('type', 'node')}-{item.get('id')}",
            name=name[:40],
            category=category,
            location=Coordinates(lat=float(item["lat"]), lng=float(item["lon"])),
            address=tags.get("addr:full", tags.get("addr:street", "")),
            price_per_person=None,
            rating=None,
            review_count=0,
            rating_source="",
            popularity=0.50,
            novelty=0.60,
            tags=[category, "开放数据"] + (["室内"] if indoor else ["户外"]),
            indoor=indoor,
            opening_hours=tags.get("opening_hours", ""),
            source="overpass",
            image_url=self._image_from_tags(tags),
            photo_source=self._photo_source_from_tags(tags),
            description=self._open_map_description(category, tags),
        )

    def _open_map_description(self, category: str, tags: dict[str, str]) -> str:
        labels = {
            "cafe": "咖啡/茶饮地点",
            "dining": "餐饮地点",
            "bar": "小酒馆",
            "exhibition": "文化展览地点",
            "bookstore": "书店或阅读空间",
            "mall": "商场或综合体",
            "park": "公园绿地",
            "workshop": "体验类地点",
            "market": "街区或休闲地点",
        }
        source_type = tags.get("amenity") or tags.get("tourism") or tags.get("shop") or tags.get("leisure")
        return " · ".join(part for part in [labels.get(category, "本地生活地点"), source_type] if part)

    def _image_from_tags(self, tags: dict[str, str]) -> str:
        image = tags.get("image", "")
        if image.startswith("http://") or image.startswith("https://"):
            return image
        commons = tags.get("wikimedia_commons", "")
        if commons.startswith("File:"):
            filename = quote(commons.removeprefix("File:"), safe="")
            return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=480"
        return ""

    def _photo_source_from_tags(self, tags: dict[str, str]) -> str:
        if tags.get("image"):
            return "openstreetmap_image"
        if tags.get("wikimedia_commons", "").startswith("File:"):
            return "wikimedia_commons"
        return ""

    def _category_from_tags(self, tags: dict[str, str]) -> str:
        amenity = tags.get("amenity", "")
        tourism = tags.get("tourism", "")
        shop = tags.get("shop", "")
        leisure = tags.get("leisure", "")
        if amenity == "cafe":
            return "cafe"
        if amenity == "restaurant":
            return "dining"
        if amenity == "bar":
            return "bar"
        if amenity in {"theatre", "arts_centre"} or tourism in {"museum", "gallery"}:
            return "exhibition"
        if shop == "books":
            return "bookstore"
        if shop == "mall":
            return "mall"
        if shop == "craft":
            return "workshop"
        if leisure in {"park", "garden"}:
            return "park"
        return "market"


def seed_pois_for_city(city: str, center: Coordinates | None = None) -> list[PoiCandidate]:
    city_name = normalize_city_name(city)
    if city_name == "上海":
        return _with_image_fallbacks(apply_vendor_data([poi.model_copy(deep=True) for poi in SEED_POIS]))
    return _with_image_fallbacks(apply_vendor_data(_generic_pois_for_city(city_name, center or city_center(city_name))))


def _with_image_fallbacks(pois: list[PoiCandidate]) -> list[PoiCandidate]:
    enriched: list[PoiCandidate] = []
    for poi in pois:
        if poi.image_url:
            enriched.append(poi)
            continue
        fallback = CATEGORY_IMAGE_FALLBACKS.get(poi.category, CATEGORY_IMAGE_FALLBACKS["walk"])
        enriched.append(poi.model_copy(update={"image_url": fallback, "photo_source": poi.photo_source or "category_fallback"}))
    return enriched


def _dedupe_coordinates(coordinates: list[Coordinates]) -> list[Coordinates]:
    deduped: list[Coordinates] = []
    last_key = ""
    for coordinate in coordinates:
        key = f"{coordinate.lat:.6f},{coordinate.lng:.6f}"
        if key == last_key:
            continue
        deduped.append(coordinate)
        last_key = key
    return deduped


def _generic_pois_for_city(city: str, center: Coordinates) -> list[PoiCandidate]:
    templates = [
        ("fallback-cafe", "城市会客厅咖啡", "cafe", 48, 4.3, 0.58, 0.55, True, ["咖啡", "室内", "轻松"], 0.010, -0.008),
        ("fallback-exhibition", "公共文化展区", "exhibition", 30, 4.2, 0.45, 0.64, True, ["展览", "室内", "低预算"], -0.006, 0.009),
        ("fallback-park", "中心公园慢逛", "park", 0, 4.2, 0.50, 0.50, False, ["公园", "散步", "低预算"], 0.012, 0.011),
        ("fallback-bookstore", "本地书店停靠", "bookstore", 42, 4.3, 0.42, 0.66, True, ["书店", "安静", "室内"], -0.011, -0.006),
        ("fallback-dining", "社区轻晚餐", "dining", 68, 4.2, 0.52, 0.48, True, ["餐饮", "低预算", "室内"], 0.004, 0.014),
        ("fallback-walk", "老街区漫游", "walk", 0, 4.2, 0.40, 0.68, False, ["街区", "散步", "小众"], -0.014, 0.005),
        ("fallback-mall", "城市综合体", "mall", 75, 4.1, 0.62, 0.42, True, ["商场", "室内", "雨天"], 0.008, -0.014),
        ("fallback-workshop", "手作体验空间", "workshop", 118, 4.3, 0.38, 0.72, True, ["手作", "互动", "室内"], -0.008, -0.012),
    ]
    pois: list[PoiCandidate] = []
    for index, (suffix, name, category, price, rating, popularity, novelty, indoor, tags, lat_delta, lng_delta) in enumerate(templates, start=1):
        pois.append(
            PoiCandidate(
                id=f"{normalize_city_name(city)}-{suffix}",
                name=f"{city}{name}",
                category=category,
                location=Coordinates(lat=center.lat + lat_delta, lng=center.lng + lng_delta),
                address=f"{city}市中心周边",
                price_per_person=price,
                rating=rating,
                review_count=0,
                rating_source="fallback_estimate",
                popularity=popularity,
                novelty=novelty,
                tags=tags,
                indoor=indoor,
                opening_hours="10:00-22:00",
                source="city_fallback",
                photo_source="category_fallback",
                description="全国城市兜底候选点；开启开放数据时会优先使用地图返回的真实 POI。",
            )
        )
    return pois


def now_utc() -> datetime:
    return datetime.utcnow()
