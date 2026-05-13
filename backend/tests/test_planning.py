from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agents import PreferenceAgent, RoutePlannerAgent
from app.main import app, workflow
from app.schemas import ContextSnapshot, Coordinates, Itinerary, ItineraryStop, PlanRequest, PoiCandidate, ReplanRequest, WeatherSnapshot
from app.services import OpenDataClient, now_utc, seed_pois_for_city
from app.workflow import CityMateWorkflow


def test_preference_agent_extracts_core_fields() -> None:
    brief, _ = PreferenceAgent().parse(
        PlanRequest(
            query="周六下午在上海，4 小时，预算 300，两个人，想轻松一点，不想太网红，最好地铁方便。",
            use_live_data=False,
        )
    )

    assert brief.city == "上海"
    assert brief.duration_hours == 4
    assert brief.budget == 300
    assert brief.party_size == 2
    assert "小众" in brief.preferences
    assert brief.transport_mode == "transit"


def test_preference_agent_extracts_national_city() -> None:
    brief, _ = PreferenceAgent().parse(
        PlanRequest(
            query="周六下午在成都，4 小时，预算 300，两个人，想轻松一点。",
            city="上海",
            origin_name="天府广场",
            use_live_data=False,
        )
    )

    assert brief.city == "成都"
    assert 30 < brief.origin.lat < 31


@pytest.mark.asyncio
async def test_plan_returns_three_itineraries_with_seed_data() -> None:
    graph = CityMateWorkflow()
    response = await graph.plan(
        PlanRequest(
            query="周六下午在上海，4 小时，预算 300，两个人，想轻松一点，不想太网红，最好地铁方便。",
            use_live_data=False,
        )
    )

    assert len(response.itineraries) == 3
    for itinerary in response.itineraries:
        assert len(itinerary.stops) >= 3
        assert itinerary.total_cost > 0
        assert itinerary.total_travel_minutes >= 0
        assert itinerary.reasons
        assert all(stop.poi.location.lat and stop.poi.location.lng for stop in itinerary.stops)
    budget_cost = next(itinerary.total_cost for itinerary in response.itineraries if itinerary.title.startswith("低预算线"))
    other_costs = [itinerary.total_cost for itinerary in response.itineraries if not itinerary.title.startswith("低预算线")]
    assert budget_cost <= max(other_costs)


@pytest.mark.asyncio
async def test_non_shanghai_city_uses_local_fallback_coordinates() -> None:
    graph = CityMateWorkflow()
    response = await graph.plan(
        PlanRequest(
            query="周六下午在成都，4 小时，预算 300，两个人，想轻松一点。",
            city="成都",
            origin_name="天府广场",
            use_live_data=False,
        )
    )

    assert response.brief.city == "成都"
    assert len(response.itineraries) == 3
    assert all(stop.poi.source in {"city_fallback"} for itinerary in response.itineraries for stop in itinerary.stops)
    assert all(30 < stop.poi.location.lat < 31 for itinerary in response.itineraries for stop in itinerary.stops)


@pytest.mark.asyncio
async def test_replan_rain_replaces_outdoor_stops() -> None:
    graph = CityMateWorkflow()
    plan = await graph.plan(
        PlanRequest(
            query="周六下午在上海，4 小时，预算 300，两个人，想轻松一点，想逛街区。",
            use_live_data=False,
        )
    )
    current = next(route for route in plan.itineraries if any(not stop.poi.indoor for stop in route.stops))

    replanned = await graph.replan(
        ReplanRequest(
            feedback="下雨了，换成室内",
            current_itinerary=current,
            brief=plan.brief,
            use_live_data=False,
        )
    )

    assert replanned.itineraries
    assert all(stop.poi.indoor for stop in replanned.itineraries[0].stops)


@pytest.mark.asyncio
async def test_replan_cheaper_lowers_or_preserves_cost() -> None:
    graph = CityMateWorkflow()
    plan = await graph.plan(
        PlanRequest(
            query="周六下午在上海，4 小时，预算 500，两个人，想要手作和晚餐。",
            use_live_data=False,
        )
    )
    current = plan.itineraries[0]

    replanned = await graph.replan(
        ReplanRequest(
            feedback="便宜一点",
            current_itinerary=current,
            brief=plan.brief,
            use_live_data=False,
        )
    )

    assert replanned.itineraries[0].total_cost <= current.total_cost


def test_low_budget_route_avoids_high_known_price_stops() -> None:
    planner = RoutePlannerAgent()
    brief = PreferenceAgent().parse(
        PlanRequest(
            query="周六下午在上海，4 小时，预算 300，两个人，想轻松一点，低预算，不想太网红。",
            use_live_data=False,
        )
    )[0]
    pois = [
        PoiCandidate(
            id="park-free",
            name="城市公园",
            category="park",
            location=Coordinates(lat=31.2300, lng=121.4700),
            price_per_person=None,
            rating=4.6,
            rating_source="",
            opening_hours="",
            indoor=False,
        ),
        PoiCandidate(
            id="bookstore-free",
            name="安静书店",
            category="bookstore",
            location=Coordinates(lat=31.2310, lng=121.4710),
            price_per_person=None,
            rating=4.7,
            rating_source="",
            opening_hours="",
        ),
        PoiCandidate(
            id="dining-cheap",
            name="平价晚餐",
            category="dining",
            location=Coordinates(lat=31.2320, lng=121.4720),
            price_per_person=28,
            rating=4.5,
            rating_source="",
            opening_hours="",
        ),
        PoiCandidate(
            id="market-expensive",
            name="高价体验馆",
            category="market",
            location=Coordinates(lat=31.2330, lng=121.4730),
            price_per_person=105,
            rating=4.8,
            rating_source="",
            opening_hours="",
        ),
    ]
    context = ContextSnapshot(
        city=brief.city,
        center=brief.origin,
        weather=WeatherSnapshot(),
        generated_at=now_utc(),
    )

    itineraries, _ = planner.build(brief, context, pois)

    budget_route = next(item for item in itineraries if item.title.startswith("低预算线"))
    known_prices = [stop.poi.price_per_person for stop in budget_route.stops if stop.poi.price_per_person is not None]

    assert 105 not in known_prices


def test_workflow_declares_langgraph_framework() -> None:
    workflow = CityMateWorkflow()

    assert workflow.framework == "LangGraph"
    assert "CriticAgent" in workflow.system_profile()["nodes"]
    assert "LLMPreferenceAgent" in workflow.system_profile()["nodes"]
    assert "SemanticSearchAgent" in workflow.system_profile()["nodes"]
    assert "LLMExperienceAgent" in workflow.system_profile()["nodes"]


def test_llm_reason_sanitizer_does_not_fabricate_free_or_budget_fit() -> None:
    workflow = CityMateWorkflow()
    poi = PoiCandidate(
        id="test-unknown",
        name="未公开人均地点",
        category="exhibition",
        location=Coordinates(lat=31.23, lng=121.47),
        price_per_person=None,
        rating=None,
        rating_source="",
        opening_hours="",
    )
    itinerary = Itinerary(
        id="route-test",
        title="测试路线",
        theme="测试",
        score=80,
        total_cost=0,
        total_travel_minutes=20,
        stops=[
            ItineraryStop(
                poi=poi,
                start_time="14:00",
                end_time="15:00",
                stay_minutes=60,
                travel_minutes_from_previous=0,
                note="测试节点",
            )
        ],
    )

    sanitized = workflow._sanitize_llm_reason("这里免费，且总价控制在预算内。", itinerary)

    assert "免费" not in sanitized
    assert "总价控制在预算内" not in sanitized
    assert "未公开人均" in sanitized


def test_authorized_vendor_data_overlays_seed_poi(tmp_path, monkeypatch) -> None:
    vendor_path = tmp_path / "vendor.json"
    vendor_path.write_text(
        json.dumps(
            {
                "pois": [
                    {
                        "name": "武康大楼周边咖啡",
                        "image_url": "https://img.example.com/wukang.jpg",
                        "rating": 4.8,
                        "review_count": 2301,
                        "rating_source": "dianping_authorized",
                        "photo_source": "meituan_authorized",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CITYMATE_VENDOR_DATA_PATH", str(vendor_path))

    poi = next(item for item in seed_pois_for_city("上海") if item.name == "武康大楼周边咖啡")

    assert poi.image_url == "https://img.example.com/wukang.jpg"
    assert poi.rating == 4.8
    assert poi.review_count == 2301
    assert poi.rating_source == "dianping_authorized"


def test_authorized_vendor_data_can_overlay_by_poi_id(tmp_path, monkeypatch) -> None:
    vendor_path = tmp_path / "vendor-by-id.json"
    vendor_path.write_text(
        json.dumps(
            {
                "pois": [
                    {
                        "source_poi_id": "seed-007",
                        "merchant_id": "mt-1007",
                        "merchant_source": "meituan_authorized",
                        "deal_summary": "双人咖啡套餐 88 元",
                        "platform_url": "https://vendor.example.com/shops/mt-1007",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CITYMATE_VENDOR_DATA_PATH", str(vendor_path))

    poi = next(item for item in seed_pois_for_city("上海") if item.id == "seed-007")

    assert poi.merchant_id == "mt-1007"
    assert poi.merchant_source == "meituan_authorized"
    assert poi.deal_summary == "双人咖啡套餐 88 元"
    assert poi.platform_url.endswith("mt-1007")


def test_amap_poi_payload_maps_to_citymate_candidate() -> None:
    client = OpenDataClient(map_provider="amap", amap_key="test")

    poi = client._amap_item_to_poi(
        {
            "id": "B00155TEST",
            "name": "测试咖啡馆",
            "type": "餐饮服务;咖啡厅;咖啡厅",
            "location": "121.473700,31.230400",
            "pname": "上海市",
            "cityname": "上海市",
            "adname": "黄浦区",
            "address": "人民大道 100 号",
            "biz_ext": {"rating": "4.8", "cost": "52"},
            "photos": [{"url": "https://img.example.com/shop.jpg"}],
        }
    )

    assert poi is not None
    assert poi.source == "amap"
    assert poi.category == "cafe"
    assert poi.rating == 4.8
    assert poi.price_per_person == 52
    assert poi.merchant_source == "amap"
    assert 30 < poi.location.lat < 32
    assert 120 < poi.location.lng < 122


def test_amap_v5_business_fields_are_mapped_without_defaults() -> None:
    client = OpenDataClient(map_provider="amap", amap_key="test")

    poi = client._amap_item_to_poi(
        {
            "id": "B00155H8SM",
            "name": "星巴克(人民公园店)",
            "type": "餐饮服务;咖啡厅;星巴克咖啡",
            "location": "121.470875,31.231675",
            "address": "南京西路189号",
            "business": {
                "opentime_today": "06:30-22:00",
                "cost": "30.00",
                "keytag": "饮品",
                "rating": "4.6",
                "business_area": "人民广场片区",
                "tel": "021-63271930",
                "tag": "星冰乐,下午茶,三明治",
                "rectag": "饮品",
                "opentime_week": "周一至周四 06:30-22:00",
            },
            "photos": [{"url": "https://aos-comment.amap.com/B00155H8SM/comment/photo.jpg"}],
            "indoor": {"indoor_map": "0"},
        }
    )

    assert poi is not None
    assert poi.category == "cafe"
    assert poi.price_per_person == 30
    assert poi.rating == 4.6
    assert poi.opening_hours == "周一至周四 06:30-22:00"
    assert poi.phone == "021-63271930"
    assert poi.business_area == "人民广场片区"
    assert poi.image_url.startswith("https://aos-comment.amap.com/")
    assert "星冰乐" in poi.tags
    assert "人民广场片区周边" in poi.description


def test_amap_missing_price_and_rating_are_not_fabricated() -> None:
    client = OpenDataClient(map_provider="amap", amap_key="test")

    poi = client._amap_item_to_poi(
        {
            "id": "B00155NOPRICE",
            "name": "真实地点无价格",
            "type": "购物服务;商场;购物中心",
            "location": "121.473700,31.230400",
            "address": "人民大道 200 号",
            "biz_ext": {},
        }
    )

    assert poi is not None
    assert poi.price_per_person is None
    assert poi.rating is None
    assert poi.rating_source == ""
    assert poi.opening_hours == ""
    assert poi.phone == ""
    assert "Web 服务" not in poi.description


def test_place_search_endpoint_falls_back_to_city_center(monkeypatch) -> None:
    async def fail_search(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(workflow.scout.bundle.client, "search_places", fail_search)
    client = TestClient(app)

    response = client.get("/api/places/search", params={"city": "成都", "q": "天府广场"})

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "成都市中心"
    assert 30 < payload[0]["location"]["lat"] < 31
