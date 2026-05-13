from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .schemas import Coordinates, PlaceSuggestion, PlanRequest, PlanResponse, ReplanRequest
from .services import city_center
from .workflow import CityMateWorkflow

app = FastAPI(title="CityMate API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workflow = CityMateWorkflow()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system")
async def system_profile() -> dict[str, object]:
    return workflow.system_profile()


@app.get("/api/map/config")
async def map_config() -> dict[str, object]:
    profile = workflow.system_profile()
    return {
        "provider": profile.get("map_provider", "open"),
        "amap_enabled": profile.get("amap_enabled", False),
        "tile_url": "",
        "attribution": "地图数据来自 OpenStreetMap；国内生产部署可在前端配置合规瓦片服务。",
    }


@app.get("/api/places/search", response_model=list[PlaceSuggestion])
async def search_places(
    q: str = Query(..., min_length=1),
    city: str = "上海",
    limit: int = Query(8, ge=1, le=10),
) -> list[PlaceSuggestion]:
    try:
        suggestions = await workflow.scout.bundle.client.search_places(q, city, limit)
    except Exception:
        suggestions = []
    if suggestions:
        return suggestions
    center = city_center(city)
    return [
        PlaceSuggestion(
            name=f"{city}市中心",
            address="地图服务暂不可用时的城市中心兜底",
            location=Coordinates(lat=center.lat, lng=center.lng),
            source="city_fallback",
        )
    ]


@app.post("/api/plan", response_model=PlanResponse)
async def plan(request: PlanRequest) -> PlanResponse:
    return await workflow.plan(request)


@app.post("/api/replan", response_model=PlanResponse)
async def replan(request: ReplanRequest) -> PlanResponse:
    return await workflow.replan(request)
