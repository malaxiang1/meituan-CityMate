from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    lat: float
    lng: float


class PlaceSuggestion(BaseModel):
    name: str
    address: str = ""
    location: Coordinates
    source: str = "nominatim"


class PlanRequest(BaseModel):
    query: str = Field(..., min_length=2)
    city: str = "上海"
    origin_name: str = "人民广场"
    start_time: str = "周六 14:00"
    duration_hours: float | None = None
    budget: int | None = None
    party_size: int | None = None
    use_live_data: bool = True


class ReplanRequest(BaseModel):
    feedback: str = Field(..., min_length=1)
    current_itinerary: "Itinerary"
    brief: "UserBrief"
    use_live_data: bool = True


class UserBrief(BaseModel):
    city: str = "上海"
    origin_name: str = "人民广场"
    origin: Coordinates = Field(default_factory=lambda: Coordinates(lat=31.2304, lng=121.4737))
    start_time: str = "周六 14:00"
    duration_hours: float = 4
    budget: int = 300
    party_size: int = 2
    mood: str = "放松"
    preferences: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    transport_mode: Literal["walk", "transit", "drive"] = "transit"


class WeatherSnapshot(BaseModel):
    condition: str = "多云"
    temperature_c: float = 22
    is_rainy: bool = False
    source: str = "mock"


class ContextSnapshot(BaseModel):
    city: str
    center: Coordinates
    weather: WeatherSnapshot
    generated_at: datetime


class PoiCandidate(BaseModel):
    id: str
    name: str
    category: str
    location: Coordinates
    address: str = ""
    price_per_person: int | None = None
    rating: float | None = None
    review_count: int = 0
    rating_source: str = "seed_estimate"
    popularity: float = 0.5
    novelty: float = 0.5
    tags: list[str] = Field(default_factory=list)
    indoor: bool = True
    opening_hours: str = "10:00-22:00"
    phone: str = ""
    business_area: str = ""
    source: str = "seed"
    image_url: str = ""
    photo_source: str = ""
    platform_url: str = ""
    merchant_id: str = ""
    merchant_source: str = ""
    deal_summary: str = ""
    description: str = ""


class ItineraryStop(BaseModel):
    poi: PoiCandidate
    start_time: str
    end_time: str
    stay_minutes: int
    travel_minutes_from_previous: int
    note: str


class CritiqueReport(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)


class Itinerary(BaseModel):
    id: str
    title: str
    theme: str
    score: float
    total_cost: int
    total_travel_minutes: int
    risk_tags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    stops: list[ItineraryStop]
    route_geometry: list[Coordinates] = Field(default_factory=list)
    critique: CritiqueReport = Field(default_factory=CritiqueReport)


class PlanResponse(BaseModel):
    brief: UserBrief
    context: ContextSnapshot
    itineraries: list[Itinerary]
    agents_trace: list[str]
    data_warnings: list[str] = Field(default_factory=list)
