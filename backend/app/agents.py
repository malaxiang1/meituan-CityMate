from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from .schemas import (
    ContextSnapshot,
    Coordinates,
    CritiqueReport,
    Itinerary,
    ItineraryStop,
    PlanRequest,
    PlanResponse,
    PoiCandidate,
    ReplanRequest,
    UserBrief,
    WeatherSnapshot,
)
from .seed_data import CITY_CENTERS
from .services import OpenDataClient, city_center, estimate_travel_minutes, haversine_km, normalize_city_name, now_utc, seed_pois_for_city
from .vendor_data import VendorDataClient


CATEGORY_LABELS = {
    "cafe": "咖啡",
    "bookstore": "书店",
    "exhibition": "展览",
    "market": "街区",
    "walk": "散步",
    "mall": "商场",
    "dining": "晚餐",
    "park": "公园",
    "workshop": "手作",
    "bar": "小酒馆",
}


def poi_price(poi: PoiCandidate) -> int:
    return poi.price_per_person if poi.price_per_person is not None else 0


def poi_sort_price(poi: PoiCandidate) -> int:
    return poi.price_per_person if poi.price_per_person is not None else 10_000


def poi_rating(poi: PoiCandidate) -> float:
    return poi.rating if poi.rating is not None else 4.2


def all_prices_known(itinerary: Itinerary) -> bool:
    return all(stop.poi.price_per_person is not None for stop in itinerary.stops)


@dataclass
class AgentBundle:
    client: OpenDataClient
    vendor: VendorDataClient


class PreferenceAgent:
    def parse(self, request: PlanRequest) -> tuple[UserBrief, list[str]]:
        query = request.query
        trace = ["PreferenceAgent: 抽取城市、预算、时长、人数、情绪和偏好。"]
        city = self._extract_city(query, request.city)
        budget = request.budget or self._extract_budget(query) or 300
        duration = request.duration_hours or self._extract_duration(query) or 4
        party_size = request.party_size or self._extract_party_size(query) or 2
        start_time = request.start_time or self._extract_start_time(query)
        preferences = self._extract_preferences(query)
        hard_constraints = self._extract_constraints(query)
        mood = self._extract_mood(query)
        transport_mode = "transit" if "地铁" in query or "公交" in query else "walk" if "步行" in query else "transit"
        brief = UserBrief(
            city=city,
            origin_name=request.origin_name or "人民广场",
            origin=city_center(city),
            start_time=start_time,
            duration_hours=duration,
            budget=budget,
            party_size=party_size,
            mood=mood,
            preferences=preferences,
            hard_constraints=hard_constraints,
            transport_mode=transport_mode,
        )
        return brief, trace

    def apply_feedback(self, brief: UserBrief, feedback: str) -> UserBrief:
        updated = brief.model_copy(deep=True)
        if any(word in feedback for word in ["雨", "室内", "热", "冷"]):
            self._add_once(updated.hard_constraints, "室内")
            self._add_once(updated.preferences, "天气友好")
        if any(word in feedback for word in ["便宜", "省钱", "低预算", "贵"]):
            updated.budget = max(80, round(updated.budget * 0.8))
            self._add_once(updated.preferences, "低预算")
        if any(word in feedback for word in ["少走", "别累", "近一点", "少通勤"]):
            self._add_once(updated.preferences, "少走路")
        if any(word in feedback for word in ["小众", "别网红", "不网红"]):
            self._add_once(updated.preferences, "小众")
        return updated

    def _extract_budget(self, query: str) -> int | None:
        match = re.search(r"(?:预算|人均|总共|控制在|不超过)\s*(\d{2,5})", query)
        return int(match.group(1)) if match else None

    def _extract_city(self, query: str, request_city: str) -> str:
        for city in sorted(CITY_CENTERS, key=len, reverse=True):
            if city in query or f"{city}市" in query:
                return city
        return normalize_city_name(request_city)

    def _extract_duration(self, query: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|h|H)", query)
        return float(match.group(1)) if match else None

    def _extract_party_size(self, query: str) -> int | None:
        if any(word in query for word in ["两个人", "俩人", "两人", "2个人", "2人"]):
            return 2
        if "三人" in query or "3人" in query:
            return 3
        match = re.search(r"(\d+)\s*(?:个人|人)", query)
        return int(match.group(1)) if match else None

    def _extract_start_time(self, query: str) -> str:
        match = re.search(r"(\d{1,2})(?:[:：点])(\d{0,2})", query)
        if match:
            minute = match.group(2) or "00"
            return f"周六 {int(match.group(1)):02d}:{int(minute):02d}"
        if "上午" in query:
            return "周六 10:00"
        if "晚上" in query:
            return "周六 18:00"
        return "周六 14:00"

    def _extract_preferences(self, query: str) -> list[str]:
        mapping = {
            "小众": ["小众", "不网红", "别网红", "不太网红", "不想太网红"],
            "好拍照": ["拍照", "出片"],
            "地铁方便": ["地铁", "交通方便"],
            "室内": ["室内", "下雨", "雨天"],
            "低预算": ["便宜", "低预算", "省钱"],
            "安静": ["安静", "不吵"],
            "互动": ["手作", "互动", "体验"],
        }
        result: list[str] = []
        for label, words in mapping.items():
            if any(word in query for word in words):
                result.append(label)
        return result

    def _extract_constraints(self, query: str) -> list[str]:
        constraints: list[str] = []
        if any(word in query for word in ["不吃辣", "不能吃辣"]):
            constraints.append("不吃辣")
        if any(word in query for word in ["室内", "下雨", "雨天"]):
            constraints.append("室内")
        return constraints

    def _extract_mood(self, query: str) -> str:
        if any(word in query for word in ["约会", "情侣"]):
            return "约会"
        if any(word in query for word in ["亲子", "孩子"]):
            return "亲子"
        if any(word in query for word in ["探索", "新鲜", "小众"]):
            return "探索"
        if any(word in query for word in ["轻松", "放松", "治愈", "不累"]):
            return "放松"
        return "放松"

    def _add_once(self, values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)


class ContextAgent:
    def __init__(self, bundle: AgentBundle) -> None:
        self.bundle = bundle

    async def build(self, brief: UserBrief, use_live_data: bool) -> tuple[ContextSnapshot, list[str], list[str]]:
        trace = ["ContextAgent: 获取城市中心、天气和时间上下文。"]
        warnings: list[str] = []
        center = city_center(brief.city)
        weather = WeatherSnapshot()
        if use_live_data:
            try:
                center = await self.bundle.client.geocode(brief.city, "中国")
                brief.origin = await self.bundle.client.geocode(brief.origin_name, brief.city)
                trace.append("ContextAgent: 已使用开放地理编码定位城市和起点。")
            except Exception:
                brief.origin = center
                warnings.append("地理编码 API 暂不可用，已使用内置城市中心。")
            try:
                weather = await self.bundle.client.weather(center)
            except Exception:
                warnings.append("天气 API 暂不可用，已使用多云 Mock 天气。")
        if "室内" in brief.hard_constraints:
            weather.is_rainy = True
            weather.condition = "用户指定室内优先"
        context = ContextSnapshot(city=brief.city, center=center, weather=weather, generated_at=now_utc())
        return context, trace, warnings


class PoiScoutAgent:
    def __init__(self, bundle: AgentBundle) -> None:
        self.bundle = bundle

    async def collect(
        self,
        brief: UserBrief,
        context: ContextSnapshot,
        use_live_data: bool,
        search_keywords: list[str] | None = None,
    ) -> tuple[list[PoiCandidate], list[str], list[str]]:
        trace = ["PoiScoutAgent: 合并本地兜底 POI、真实地图 POI 与授权商家数据。"]
        warnings: list[str] = []
        pois = [] if use_live_data else seed_pois_for_city(brief.city, context.center)
        if use_live_data:
            try:
                result = await self.bundle.client.overpass_pois(context.center, radius_m=5200)
                existing = {poi.name for poi in pois}
                pois.extend([poi for poi in result.pois if poi.name not in existing])
                warnings.extend(result.warnings)
            except Exception:
                warnings.append("开放 POI API 暂不可用，已使用本地兜底候选点。")
            if search_keywords:
                try:
                    keyword_pois = await self.bundle.client.amap_keyword_pois(brief.city, context.center, search_keywords)
                    existing_ids = {poi.id for poi in pois}
                    existing_names = {poi.name for poi in pois}
                    pois.extend(
                        poi for poi in keyword_pois if poi.id not in existing_ids and poi.name not in existing_names
                    )
                    if keyword_pois:
                        trace.append(f"SemanticSearchAgent: 使用 LLM 检索词补充 {len(keyword_pois)} 个高德真实 POI。")
                except Exception:
                    warnings.append("LLM 检索词补充 POI 暂不可用，已保留周边 POI 结果。")
        if len(pois) < 8 and (not use_live_data or not pois):
            existing = {poi.name for poi in pois}
            fallback = [poi for poi in seed_pois_for_city(brief.city, context.center) if poi.name not in existing]
            pois.extend(fallback)
            if use_live_data:
                warnings.append("真实地图返回的可规划地点不足，已补充本地兜底候选点。")
        elif use_live_data and len(pois) < 8:
            warnings.append("真实地图返回的可规划地点偏少，当前路线未补入本地估算地点。")
        if use_live_data and self.bundle.vendor.enabled:
            pois, vendor_warnings = await self.bundle.vendor.enrich_pois(pois, brief.city)
            warnings.extend(vendor_warnings)
            if not vendor_warnings:
                trace.append("PoiScoutAgent: 已调用授权商家 API 覆盖门店评分、图片、价格和链接。")
        return self._rank_for_brief(pois, brief, context), trace, warnings

    def _rank_for_brief(self, pois: list[PoiCandidate], brief: UserBrief, context: ContextSnapshot) -> list[PoiCandidate]:
        return sorted(pois, key=lambda poi: self._poi_score(poi, brief, context), reverse=True)

    def _poi_score(self, poi: PoiCandidate, brief: UserBrief, context: ContextSnapshot) -> float:
        score = poi_rating(poi) / 5
        score += poi.novelty * 0.25 if "小众" in brief.preferences else poi.popularity * 0.12
        if "室内" in brief.hard_constraints and poi.indoor:
            score += 0.35
        if context.weather.is_rainy and poi.indoor:
            score += 0.25
        if "低预算" in brief.preferences and poi.price_per_person is not None and poi.price_per_person <= 60:
            score += 0.25
        if "好拍照" in brief.preferences and any(tag in poi.tags for tag in ["拍照", "艺术", "街区"]):
            score += 0.18
        if "安静" in brief.preferences and any(tag in poi.tags for tag in ["安静", "书店", "茶"]):
            score += 0.18
        if "少走路" in brief.preferences:
            score -= haversine_km(brief.origin, poi.location) * 0.06
        return score


class RoutePlannerAgent:
    ROUTE_TEMPLATES = [
        ("healing", "治愈放松线", "咖啡开场，接一个轻文化节点，再用安静晚餐收尾", ["cafe", "exhibition", "bookstore", "dining"], [40, 45, 55, 60]),
        ("explore", "轻探索线", "小众街区、文化停靠和轻晚餐串成半日探索", ["cafe", "bookstore", "walk", "dining"], [40, 50, 45, 60]),
        ("budget", "低预算线", "优先选择免费或未公开人均的公共空间，把已知花费压到预算内", ["park", "walk", "bookstore", "dining"], [35, 40, 45, 55]),
    ]

    def build(self, brief: UserBrief, context: ContextSnapshot, pois: list[PoiCandidate]) -> tuple[list[Itinerary], list[str]]:
        trace = ["RoutePlannerAgent: 生成 3 条候选路线并按偏好、预算、距离打分。"]
        itineraries = []
        used_route_signatures: set[str] = set()
        for route_id, title, theme, categories, stays in self.ROUTE_TEMPLATES:
            budget_mode = route_id == "budget" or "低预算" in brief.preferences
            categories, stays = self._budget_adjust(categories, stays, brief, budget_mode)
            route = self._build_route(route_id, title, theme, categories, stays, brief, context, pois, budget_mode)
            signature = "-".join(stop.poi.id for stop in route.stops)
            if signature in used_route_signatures:
                route = self._build_route(route_id, title, theme, list(reversed(categories)), stays, brief, context, pois, budget_mode)
            used_route_signatures.add("-".join(stop.poi.id for stop in route.stops))
            itineraries.append(route)
        return sorted(itineraries, key=lambda item: self._route_rank_key(item, brief), reverse=True), trace

    def rebuild_from_stops(self, itinerary: Itinerary, brief: UserBrief, stops: list[PoiCandidate]) -> Itinerary:
        stay_minutes = [stop.stay_minutes for stop in itinerary.stops]
        rebuilt_stops = self._schedule_stops(stops, stay_minutes, brief, itinerary.title)
        total_cost = sum(poi_price(stop.poi) for stop in rebuilt_stops) * brief.party_size
        total_travel = sum(stop.travel_minutes_from_previous for stop in rebuilt_stops)
        return itinerary.model_copy(
            update={
                "id": f"replan-{uuid4().hex[:8]}",
                "total_cost": total_cost,
                "total_travel_minutes": total_travel,
                "stops": rebuilt_stops,
                "score": self._route_score(rebuilt_stops, total_cost, total_travel, brief),
            },
            deep=True,
        )

    def _build_route(
        self,
        route_id: str,
        title: str,
        theme: str,
        categories: list[str],
        stay_minutes: list[int],
        brief: UserBrief,
        context: ContextSnapshot,
        pois: list[PoiCandidate],
        budget_mode: bool = False,
    ) -> Itinerary:
        selected: list[PoiCandidate] = []
        for category in categories:
            selected.append(self._pick_poi(category, selected, pois, brief, context, budget_mode, stay_minutes, len(selected)))
        stops = self._schedule_stops(selected, stay_minutes, brief, title)
        total_cost = sum(poi_price(stop.poi) for stop in stops) * brief.party_size
        total_travel = sum(stop.travel_minutes_from_previous for stop in stops)
        score = self._route_score(stops, total_cost, total_travel, brief)
        return Itinerary(
            id=f"{route_id}-{uuid4().hex[:8]}",
            title=title,
            theme=theme,
            score=score,
            total_cost=total_cost,
            total_travel_minutes=total_travel,
            risk_tags=[],
            reasons=[],
            stops=stops,
        )

    def _pick_poi(
        self,
        category: str,
        selected: list[PoiCandidate],
        pois: list[PoiCandidate],
        brief: UserBrief,
        context: ContextSnapshot,
        budget_mode: bool = False,
        stay_minutes: list[int] | None = None,
        index: int = 0,
    ) -> PoiCandidate:
        used = {poi.id for poi in selected}
        alternatives = {
            "exhibition": ["exhibition", "bookstore", "mall"],
            "market": ["market", "walk", "park", "bookstore", "mall"],
            "park": ["park", "walk", "bookstore", "mall"],
            "walk": ["walk", "market", "bookstore"],
            "workshop": ["workshop", "exhibition", "bookstore"],
            "dining": ["dining", "market", "mall"],
            "cafe": ["cafe", "bookstore"],
        }
        candidate_categories = alternatives.get(category, [category])
        candidates = [poi for poi in pois if poi.id not in used and poi.category in candidate_categories]
        anchor = selected[-1].location if selected else brief.origin
        if "室内" in brief.hard_constraints or context.weather.is_rainy:
            indoor_candidates = [poi for poi in candidates if poi.indoor]
            if indoor_candidates:
                candidates = indoor_candidates
        if budget_mode or self._budget_pressure(brief) or "低预算" in brief.preferences:
            budget_candidates = [poi for poi in candidates if self._budget_candidate_allowed(poi)]
            if budget_candidates:
                candidates = budget_candidates
            remaining_budget_per_person = self._remaining_budget_per_person(selected, brief)
            low_price_cap = self._low_budget_price_cap(brief)
            low_budget_candidates = [
                poi
                for poi in candidates
                if poi.price_per_person is None or poi.price_per_person <= min(remaining_budget_per_person, low_price_cap)
            ]
            if low_budget_candidates:
                candidates = low_budget_candidates
            candidates = sorted(
                candidates,
                key=lambda poi: (
                    self._budget_price_bucket(poi, remaining_budget_per_person, low_price_cap),
                    poi.category != category,
                    poi_sort_price(poi),
                    haversine_km(anchor, poi.location),
                    -poi.novelty,
                ),
            )
            if candidates and all(
                poi.price_per_person is not None and poi.price_per_person > min(remaining_budget_per_person, low_price_cap)
                for poi in candidates
            ):
                budget_fallback = next(
                    (
                        poi
                        for poi in pois
                        if poi.id not in used
                        and self._budget_candidate_allowed(poi)
                        and (poi.price_per_person is None or poi.price_per_person <= low_price_cap)
                    ),
                    None,
                )
                if budget_fallback:
                    return budget_fallback
                repeat_budget_fallback = next(
                    (
                        poi
                        for poi in pois
                        if self._budget_candidate_allowed(poi)
                        and (poi.price_per_person is None or poi.price_per_person <= low_price_cap)
                    ),
                    None,
                )
                if repeat_budget_fallback:
                    return repeat_budget_fallback
        else:
            candidates = sorted(candidates, key=lambda poi: self._candidate_score(poi, brief, anchor), reverse=True)
        if candidates:
            return candidates[0]
        if budget_mode or self._budget_pressure(brief) or "低预算" in brief.preferences:
            low_price_cap = self._low_budget_price_cap(brief)
            budget_fallback = next(
                (
                    poi
                    for poi in pois
                    if poi.id not in used
                    and self._budget_candidate_allowed(poi)
                    and (poi.price_per_person is None or poi.price_per_person <= low_price_cap)
                ),
                None,
            )
            if budget_fallback:
                return budget_fallback
            repeat_budget_fallback = next(
                (
                    poi
                    for poi in pois
                    if self._budget_candidate_allowed(poi)
                    and (poi.price_per_person is None or poi.price_per_person <= low_price_cap)
                ),
                None,
            )
            if repeat_budget_fallback:
                return repeat_budget_fallback
        fallback = next((poi for poi in pois if poi.id not in used), pois[0])
        return fallback

    def _candidate_score(self, poi: PoiCandidate, brief: UserBrief, anchor: Coordinates | None = None) -> float:
        score = poi_rating(poi) + poi.novelty * 0.6
        if "小众" in brief.preferences:
            score += poi.novelty - poi.popularity * 0.4
        if "低预算" in brief.preferences:
            score -= poi_price(poi) / 100
        if anchor:
            score -= haversine_km(anchor, poi.location) * 0.08
        return score

    def _remaining_budget_per_person(self, selected: list[PoiCandidate], brief: UserBrief) -> int:
        spent = sum(poi_price(poi) for poi in selected)
        return max(0, round(brief.budget / max(brief.party_size, 1) - spent))

    def _budget_price_bucket(self, poi: PoiCandidate, remaining_budget_per_person: int, low_price_cap: int) -> int:
        if poi.price_per_person is not None and poi.price_per_person <= min(remaining_budget_per_person, low_price_cap):
            return 0
        if poi.price_per_person is None:
            return 1
        if poi.price_per_person <= remaining_budget_per_person:
            return 2
        return 3

    def _low_budget_price_cap(self, brief: UserBrief) -> int:
        per_person_budget = brief.budget / max(brief.party_size, 1)
        return max(25, min(60, round(per_person_budget * 0.45)))

    def _budget_candidate_allowed(self, poi: PoiCandidate) -> bool:
        high_end_words = ["万豪", "丽思", "半岛", "宝格丽", "四季", "五星", "奢华", "酒店", "宾馆", "饭店"]
        if any(word in poi.name for word in high_end_words) and (poi.price_per_person is None or poi.price_per_person > 70):
            return False
        return True

    def _route_rank_key(self, itinerary: Itinerary, brief: UserBrief) -> tuple[float, float, float]:
        budget_fit = 1.0 if itinerary.total_cost <= brief.budget else 0.0
        budget_ratio = 1 - min(2.0, itinerary.total_cost / max(brief.budget, 1)) / 2
        known_prices = sum(1 for stop in itinerary.stops if stop.poi.price_per_person is not None)
        budget_route = 1.0 if self._budget_pressure(brief) and itinerary.title.startswith("低预算线") else 0.0
        return (budget_fit, budget_route, known_prices / max(1, len(itinerary.stops)), budget_ratio, itinerary.score)

    def _budget_pressure(self, brief: UserBrief) -> bool:
        return brief.budget / max(brief.party_size, 1) <= 120

    def _budget_adjust(self, categories: list[str], stays: list[int], brief: UserBrief, budget_mode: bool) -> tuple[list[str], list[int]]:
        if not budget_mode and not self._budget_pressure(brief):
            return categories, stays
        adjusted = [
            "park" if category in {"workshop", "exhibition"} else category
            for category in categories
        ]
        if "dining" not in adjusted:
            adjusted[-1] = "dining"
        return adjusted[:4], [35, 40, 45, 55][: len(adjusted[:4])]

    def _schedule_stops(
        self,
        pois: list[PoiCandidate],
        stay_minutes: list[int],
        brief: UserBrief,
        title: str,
    ) -> list[ItineraryStop]:
        current_location = brief.origin
        current_time = self._parse_clock(brief.start_time)
        stops: list[ItineraryStop] = []
        for index, poi in enumerate(pois):
            travel = estimate_travel_minutes(current_location, poi.location, brief.transport_mode)
            current_time += timedelta(minutes=travel if index > 0 else max(0, travel - 8))
            stay = stay_minutes[index] if index < len(stay_minutes) else 55
            end_time = current_time + timedelta(minutes=stay)
            stops.append(
                ItineraryStop(
                    poi=poi,
                    start_time=current_time.strftime("%H:%M"),
                    end_time=end_time.strftime("%H:%M"),
                    stay_minutes=stay,
                    travel_minutes_from_previous=travel if index > 0 else max(0, travel - 8),
                    note=self._stop_note(poi, title),
                )
            )
            current_location = poi.location
            current_time = end_time
        return stops

    def _route_score(self, stops: list[ItineraryStop], total_cost: int, total_travel: int, brief: UserBrief) -> float:
        if not stops:
            return 0
        preference_score = sum(self._candidate_score(stop.poi, brief) for stop in stops) / (len(stops) * 5.5)
        feasibility = max(0, 1 - total_travel / max(1, brief.duration_hours * 60))
        budget_score = 1 if total_cost <= brief.budget else max(0, 1 - (total_cost - brief.budget) / max(brief.budget, 1))
        novelty = sum(stop.poi.novelty for stop in stops) / len(stops)
        diversity = len({stop.poi.category for stop in stops}) / len(stops)
        score = 100 * (
            0.25 * preference_score
            + 0.20 * feasibility
            + 0.15 * budget_score
            + 0.15 * novelty
            + 0.10 * diversity
            + 0.10 * 0.85
            + 0.05 * 0.90
        )
        return round(min(98, max(45, score)), 1)

    def _parse_clock(self, start_time: str) -> datetime:
        match = re.search(r"(\d{1,2}):(\d{2})", start_time)
        hour, minute = (14, 0)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
        return datetime(2026, 5, 2, hour, minute)

    def _stop_note(self, poi: PoiCandidate, title: str) -> str:
        label = CATEGORY_LABELS.get(poi.category, poi.category)
        if "低预算" in title:
            return f"{label}节点，控制花费同时保留体验密度。"
        if poi.novelty >= 0.7:
            return f"{label}节点，小众度高，适合作为路线记忆点。"
        return f"{label}节点，和前后安排衔接顺。"


class BudgetAgent:
    def review(self, itinerary: Itinerary, brief: UserBrief) -> Itinerary:
        risk_tags = [
            tag
            for tag in itinerary.risk_tags
            if tag not in {"略超预算", "预算内", "价格待确认"}
        ]
        if itinerary.total_cost > brief.budget:
            risk_tags.append("略超预算")
            penalty = min(12, (itinerary.total_cost - brief.budget) / max(brief.budget, 1) * 20)
            itinerary.score = round(max(40, itinerary.score - penalty), 1)
        elif not all_prices_known(itinerary):
            risk_tags.append("价格待确认")
        else:
            risk_tags.append("预算内")
        return itinerary.model_copy(update={"risk_tags": sorted(set(risk_tags))})


class CriticAgent:
    def review(self, itinerary: Itinerary, brief: UserBrief, context: ContextSnapshot) -> Itinerary:
        report = CritiqueReport()
        if len(itinerary.stops) < 3:
            report.errors.append("节点过少")
            report.repair_suggestions.append("补充一个咖啡或书店节点")
        if itinerary.total_cost > brief.budget * 1.2:
            report.errors.append("预算超出过多")
            report.repair_suggestions.append("替换高价餐饮或体验节点")
        elif not all_prices_known(itinerary):
            report.warnings.append("部分商家未公开人均")
        if itinerary.total_travel_minutes > brief.duration_hours * 18:
            report.warnings.append("通勤时间偏长")
            report.repair_suggestions.append("优先选择同商圈或相邻街区")
        if context.weather.is_rainy:
            outdoor = [stop.poi.name for stop in itinerary.stops if not stop.poi.indoor]
            if outdoor:
                report.errors.append("雨天包含户外节点")
                report.repair_suggestions.append(f"替换户外节点：{', '.join(outdoor)}")
        categories = [stop.poi.category for stop in itinerary.stops]
        if len(categories) != len(set(categories)):
            report.warnings.append("路线类别略重复")
        risk_tags = list(itinerary.risk_tags)
        if report.errors:
            risk_tags.append("需修复")
        if report.warnings:
            risk_tags.append("有提醒")
        return itinerary.model_copy(update={"critique": report, "risk_tags": sorted(set(risk_tags))}, deep=True)


class ExperienceAgent:
    def enrich(self, itinerary: Itinerary, brief: UserBrief, context: ContextSnapshot) -> Itinerary:
        names = " → ".join(stop.poi.name for stop in itinerary.stops)
        reasons = [
            f"匹配「{brief.mood}」心情，节奏控制在 {brief.duration_hours:g} 小时左右。",
            f"路线结构：{names}。",
            self._cost_reason(itinerary),
        ]
        if "小众" in brief.preferences:
            reasons.append("已提高小众和低曝光地点权重，避免只给热门网红点。")
        if context.weather.is_rainy or "室内" in brief.hard_constraints:
            reasons.append("已优先选择室内或天气友好的停靠点。")
        clean_risks = [tag for tag in itinerary.risk_tags if tag != "需修复"]
        return itinerary.model_copy(update={"reasons": reasons, "risk_tags": clean_risks}, deep=True)

    def _cost_reason(self, itinerary: Itinerary) -> str:
        known_count = sum(1 for stop in itinerary.stops if stop.poi.price_per_person is not None)
        if known_count == len(itinerary.stops):
            return f"已知门店花费合计约 {itinerary.total_cost} 元，通勤约 {itinerary.total_travel_minutes} 分钟。"
        if known_count:
            return f"已知门店花费合计约 {itinerary.total_cost} 元，其余地点地图未公开人均；通勤约 {itinerary.total_travel_minutes} 分钟。"
        return f"地图未公开本路线地点人均；通勤约 {itinerary.total_travel_minutes} 分钟。"


class ReplannerAgent:
    def __init__(self, planner: RoutePlannerAgent, critic: CriticAgent, budget: BudgetAgent, experience: ExperienceAgent) -> None:
        self.planner = planner
        self.critic = critic
        self.budget = budget
        self.experience = experience

    def replan(
        self,
        current: Itinerary,
        brief: UserBrief,
        feedback: str,
        context: ContextSnapshot,
        pois: list[PoiCandidate],
    ) -> Itinerary:
        used: set[str] = set()
        new_pois: list[PoiCandidate] = []
        cheap_feedback = any(word in feedback for word in ["便宜", "省钱", "低预算", "贵"]) or "低预算" in current.title
        for stop in current.stops:
            replacement = stop.poi
            if stop.poi.id in used:
                replacement = self._find_replacement(stop.poi, pois, used, indoor=False, cheap=cheap_feedback, novelty=True)
            elif any(word in feedback for word in ["雨", "室内"]) and not stop.poi.indoor:
                replacement = self._find_replacement(stop.poi, pois, used, indoor=True, cheap=cheap_feedback)
            elif cheap_feedback and poi_price(stop.poi) > 70:
                replacement = self._find_replacement(stop.poi, pois, used, indoor=False, cheap=True)
            elif any(word in feedback for word in ["小众", "不网红", "别网红"]):
                replacement = self._find_replacement(stop.poi, pois, used, indoor=False, cheap=False, novelty=True)
            used.add(replacement.id)
            new_pois.append(replacement)
        if any(word in feedback for word in ["少走", "近一点", "少通勤"]):
            new_pois = self._nearest_order(new_pois, brief.origin)
        rebuilt = self.planner.rebuild_from_stops(current, brief, new_pois)
        rebuilt = rebuilt.model_copy(update={"title": f"{current.title} · 已重排", "theme": f"{current.theme}；根据反馈「{feedback}」做了局部替换"})
        rebuilt = self.budget.review(rebuilt, brief)
        rebuilt = self.critic.review(rebuilt, brief, context)
        return self.experience.enrich(rebuilt, brief, context)

    def _find_replacement(
        self,
        original: PoiCandidate,
        pois: list[PoiCandidate],
        used: set[str],
        indoor: bool,
        cheap: bool,
        novelty: bool = False,
    ) -> PoiCandidate:
        category_groups = {
            "park": {"bookstore", "mall", "exhibition", "cafe", "market", "dining"},
            "walk": {"bookstore", "mall", "exhibition", "cafe", "market", "dining"},
            "market": {"bookstore", "mall", "workshop", "cafe", "market", "dining"},
        }
        allowed = category_groups.get(original.category, {original.category, "bookstore", "cafe", "mall", "exhibition"})
        candidates = [poi for poi in pois if poi.id not in used and poi.id != original.id and poi.category in allowed]
        if indoor:
            candidates = [poi for poi in candidates if poi.indoor]
        if cheap:
            budget_candidates = [poi for poi in candidates if self.planner._budget_candidate_allowed(poi)]
            if budget_candidates:
                candidates = budget_candidates
            cheap_limit = 70 if original.price_per_person is None else max(70, min(poi_price(original), 120))
            affordable_known = [
                poi for poi in candidates if poi.price_per_person is not None and poi.price_per_person <= cheap_limit
            ]
            unknown_price = [poi for poi in candidates if poi.price_per_person is None]
            if affordable_known:
                candidates = affordable_known
            elif unknown_price:
                candidates = unknown_price
            return sorted(candidates, key=lambda poi: (poi_sort_price(poi), -poi_rating(poi)))[0] if candidates else original
        if indoor:
            return sorted(candidates, key=lambda poi: (poi_sort_price(poi), -poi_rating(poi), -poi.novelty))[0] if candidates else original
        if novelty:
            return sorted(candidates, key=lambda poi: poi.novelty, reverse=True)[0] if candidates else original
        return sorted(candidates, key=lambda poi: (poi.indoor, poi_rating(poi), poi.novelty), reverse=True)[0] if candidates else original

    def _nearest_order(self, pois: list[PoiCandidate], origin: Coordinates) -> list[PoiCandidate]:
        remaining = pois[:]
        ordered: list[PoiCandidate] = []
        current = origin
        while remaining:
            next_poi = min(remaining, key=lambda poi: haversine_km(current, poi.location))
            ordered.append(next_poi)
            remaining.remove(next_poi)
            current = next_poi.location
        return ordered
