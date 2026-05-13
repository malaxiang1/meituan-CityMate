from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import (
    AgentBundle,
    BudgetAgent,
    ContextAgent,
    CriticAgent,
    ExperienceAgent,
    PoiScoutAgent,
    PreferenceAgent,
    ReplannerAgent,
    RoutePlannerAgent,
)
from .config import get_settings
from .llm import build_llm_client
from .schemas import ContextSnapshot, Itinerary, PlanRequest, PlanResponse, PoiCandidate, ReplanRequest, UserBrief
from .services import OpenDataClient
from .vendor_data import VendorDataClient


def route_rank_key(item: Itinerary, brief: UserBrief) -> tuple[float, float, float]:
    budget_fit = 1.0 if item.total_cost <= brief.budget else 0.0
    budget_ratio = 1 - min(2.0, item.total_cost / max(brief.budget, 1)) / 2
    known_prices = sum(1 for stop in item.stops if stop.poi.price_per_person is not None)
    budget_route = 1.0 if brief.budget / max(brief.party_size, 1) <= 150 and item.title.startswith("低预算线") else 0.0
    return (budget_fit, budget_route, known_prices / max(1, len(item.stops)), budget_ratio, item.score)


class PlanState(TypedDict, total=False):
    request: PlanRequest
    brief: UserBrief
    context: ContextSnapshot
    pois: list[PoiCandidate]
    itineraries: list[Itinerary]
    search_keywords: list[str]
    trace: list[str]
    warnings: list[str]
    repair_attempts: int


class ReplanState(TypedDict, total=False):
    request: ReplanRequest
    brief: UserBrief
    context: ContextSnapshot
    pois: list[PoiCandidate]
    updated: Itinerary
    alternatives: list[Itinerary]
    itineraries: list[Itinerary]
    search_keywords: list[str]
    trace: list[str]
    warnings: list[str]


class CityMateWorkflow:
    framework = "LangGraph"

    def __init__(self) -> None:
        self.settings = get_settings()
        bundle = AgentBundle(
            client=OpenDataClient(
                timeout=self.settings.request_timeout,
                map_provider=self.settings.map_provider,
                amap_key=self.settings.amap_web_service_key,
            ),
            vendor=VendorDataClient(self.settings),
        )
        self.bundle = bundle
        self.llm = build_llm_client(self.settings)
        self.preference = PreferenceAgent()
        self.context = ContextAgent(bundle)
        self.scout = PoiScoutAgent(bundle)
        self.route_planner = RoutePlannerAgent()
        self.budget = BudgetAgent()
        self.critic = CriticAgent()
        self.experience = ExperienceAgent()
        self.replanner = ReplannerAgent(self.route_planner, self.critic, self.budget, self.experience)
        self.plan_graph = self._build_plan_graph()
        self.replan_graph = self._build_replan_graph()

    async def plan(self, request: PlanRequest) -> PlanResponse:
        state = await self.plan_graph.ainvoke(
            {"request": request, "trace": [self._framework_trace()], "warnings": [], "repair_attempts": 0}
        )
        return PlanResponse(
            brief=state["brief"],
            context=state["context"],
            itineraries=state["itineraries"][:3],
            agents_trace=state["trace"],
            data_warnings=state["warnings"],
        )

    async def replan(self, request: ReplanRequest) -> PlanResponse:
        state = await self.replan_graph.ainvoke({"request": request, "trace": [self._framework_trace()], "warnings": []})
        return PlanResponse(
            brief=state["brief"],
            context=state["context"],
            itineraries=state["itineraries"][:3],
            agents_trace=state["trace"],
            data_warnings=state["warnings"],
        )

    def system_profile(self) -> dict[str, Any]:
        return {
            "name": self.settings.app_name,
            "environment": self.settings.environment,
            "agent_framework": self.framework,
            "llm_provider": self.settings.llm_provider,
            "map_provider": self.settings.map_provider,
            "amap_enabled": self.bundle.client.amap_enabled,
            "merchant_api_enabled": self.bundle.vendor.enabled,
            "live_data_default": self.settings.use_live_data,
            "nodes": [
                "PreferenceAgent",
                "LLMPreferenceAgent",
                "ContextAgent",
                "SemanticSearchAgent",
                "PoiScoutAgent",
                "RoutePlannerAgent",
                "BudgetAgent",
                "CriticAgent",
                "ReplannerAgent",
                "ExperienceAgent",
                "LLMExperienceAgent",
            ],
        }

    def _build_plan_graph(self):
        graph: StateGraph = StateGraph(PlanState)
        graph.add_node("preference", self._preference_node)
        graph.add_node("context", self._context_node)
        graph.add_node("poi_scout", self._poi_scout_node)
        graph.add_node("route_planner", self._route_planner_node)
        graph.add_node("review", self._review_node)
        graph.add_node("repair", self._repair_node)
        graph.add_node("experience", self._experience_node)
        graph.add_edge(START, "preference")
        graph.add_edge("preference", "context")
        graph.add_edge("context", "poi_scout")
        graph.add_edge("poi_scout", "route_planner")
        graph.add_edge("route_planner", "review")
        graph.add_conditional_edges("review", self._repair_or_experience, {"repair": "repair", "experience": "experience"})
        graph.add_edge("repair", "review")
        graph.add_edge("experience", END)
        return graph.compile()

    def _build_replan_graph(self):
        graph: StateGraph = StateGraph(ReplanState)
        graph.add_node("feedback", self._feedback_node)
        graph.add_node("context", self._replan_context_node)
        graph.add_node("poi_scout", self._replan_poi_scout_node)
        graph.add_node("replan_current", self._replan_current_node)
        graph.add_node("alternatives", self._replan_alternatives_node)
        graph.add_node("compose", self._replan_compose_node)
        graph.add_edge(START, "feedback")
        graph.add_edge("feedback", "context")
        graph.add_edge("context", "poi_scout")
        graph.add_edge("poi_scout", "replan_current")
        graph.add_edge("replan_current", "alternatives")
        graph.add_edge("alternatives", "compose")
        graph.add_edge("compose", END)
        return graph.compile()

    def _framework_trace(self) -> str:
        return "LangGraph: 使用 StateGraph 编排规则 Agent、LLM Agent、条件修复边和重排子流程（真实数据优先，缺失字段不做估算展示）。"

    @property
    def _llm_enabled(self) -> bool:
        return self.settings.llm_provider.lower() not in {"", "mock", "none"}

    async def _llm_preference_payload(self, request: PlanRequest, brief: UserBrief) -> dict[str, object]:
        system = (
            "你是 CityMate 的 LLMPreferenceAgent 和 SemanticSearchAgent。"
            "只输出 JSON，不要输出解释。不要编造具体商家、价格、评分、电话。"
            "你的任务是从用户需求中提取偏好，并生成可用于高德地图检索的通用关键词。"
        )
        user = json.dumps(
            {
                "query": request.query,
                "form": {
                    "city": request.city,
                    "origin_name": request.origin_name,
                    "start_time": request.start_time,
                    "duration_hours": request.duration_hours,
                    "budget": request.budget,
                    "party_size": request.party_size,
                },
                "rule_brief": brief.model_dump(mode="json"),
                "output_schema": {
                    "city": "城市名，可省略",
                    "mood": "放松/探索/约会/亲子/美食/安静/社交",
                    "preferences": ["小众", "好拍照", "地铁方便", "室内", "低预算", "安静", "互动", "文艺", "自然", "美食"],
                    "hard_constraints": ["室内", "不吃辣", "少走路", "低预算"],
                    "transport_mode": "walk/transit/drive",
                    "search_keywords": "6 到 10 个高德地图通用检索词，如 咖啡馆、书店、展览、低价小吃、公园",
                },
            },
            ensure_ascii=False,
        )
        return await self.llm.complete_json(system, user)

    async def _llm_feedback_payload(self, feedback: str, brief: UserBrief) -> dict[str, object]:
        system = (
            "你是 CityMate 的重排语义解析 Agent。只输出 JSON。"
            "根据用户反馈提取新的偏好、硬约束和地图检索词，不要编造商家或价格。"
        )
        user = json.dumps(
            {
                "feedback": feedback,
                "current_brief": brief.model_dump(mode="json"),
                "output_schema": {
                    "mood": "可省略",
                    "preferences": ["小众", "好拍照", "地铁方便", "室内", "低预算", "安静", "互动", "文艺", "自然", "美食", "天气友好", "少走路"],
                    "hard_constraints": ["室内", "不吃辣", "少走路", "低预算"],
                    "transport_mode": "walk/transit/drive",
                    "search_keywords": "3 到 8 个高德地图通用检索词",
                },
            },
            ensure_ascii=False,
        )
        return await self.llm.complete_json(system, user)

    def _apply_llm_brief(self, brief: UserBrief, request: PlanRequest | None, payload: dict[str, object]) -> UserBrief:
        updated = brief.model_copy(deep=True)
        if isinstance(payload.get("city"), str) and (request is None or request.city == "上海"):
            city = str(payload["city"]).strip().replace("市", "")
            if 2 <= len(city) <= 10:
                updated.city = city
        if isinstance(payload.get("mood"), str):
            mood = str(payload["mood"]).strip()[:8]
            if mood:
                updated.mood = mood
        mode = payload.get("transport_mode")
        if mode in {"walk", "transit", "drive"}:
            updated.transport_mode = mode  # type: ignore[assignment]
        if request is None or request.budget is None:
            budget = self._safe_int(payload.get("budget"))
            if budget is not None:
                updated.budget = max(80, min(5000, budget))
        if request is None or request.duration_hours is None:
            duration = self._safe_float(payload.get("duration_hours"))
            if duration is not None:
                updated.duration_hours = max(1.5, min(12, duration))
        if request is None or request.party_size is None:
            party_size = self._safe_int(payload.get("party_size"))
            if party_size is not None:
                updated.party_size = max(1, min(12, party_size))
        for value in self._clean_label_list(payload.get("preferences"), 10):
            if value not in updated.preferences:
                updated.preferences.append(value)
        for value in self._clean_label_list(payload.get("hard_constraints"), 8):
            if value not in updated.hard_constraints:
                updated.hard_constraints.append(value)
        return updated

    def _llm_search_keywords(self, payload: dict[str, object], brief: UserBrief) -> list[str]:
        keywords = self._clean_label_list(payload.get("search_keywords"), 6)
        fallback_map = {
            "小众": ["独立书店", "小众展览", "街区咖啡"],
            "好拍照": ["美术馆", "创意园", "城市景观"],
            "室内": ["商场", "博物馆", "书店"],
            "低预算": ["公园", "免费展览", "低价小吃"],
            "安静": ["书店", "茶馆", "咖啡馆"],
            "互动": ["手作体验", "DIY", "剧场"],
            "美食": ["小吃", "本帮菜", "咖啡馆"],
        }
        for preference in brief.preferences:
            keywords.extend(fallback_map.get(preference, []))
        keywords.extend(["咖啡馆", "书店", "展览", "餐饮"])
        deduped: list[str] = []
        for keyword in keywords:
            clean = keyword.strip()[:30]
            if clean and clean not in deduped:
                deduped.append(clean)
        return deduped[:6]

    async def _llm_explain_itineraries(
        self,
        itineraries: list[Itinerary],
        brief: UserBrief,
        context: ContextSnapshot,
    ) -> tuple[list[Itinerary], list[str]]:
        if not self._llm_enabled or not itineraries:
            return itineraries, []
        routes = []
        for itinerary in itineraries[:3]:
            routes.append(
                {
                    "id": itinerary.id,
                    "title": itinerary.title,
                    "theme": itinerary.theme,
                    "total_cost": itinerary.total_cost,
                    "total_travel_minutes": itinerary.total_travel_minutes,
                    "risk_tags": itinerary.risk_tags,
                    "stops": [
                        {
                            "name": stop.poi.name,
                            "category": stop.poi.category,
                            "address": stop.poi.address,
                            "price_per_person": stop.poi.price_per_person,
                            "rating": stop.poi.rating,
                            "opening_hours": stop.poi.opening_hours,
                            "business_area": stop.poi.business_area,
                            "tags": stop.poi.tags[:6],
                            "start_time": stop.start_time,
                            "stay_minutes": stop.stay_minutes,
                        }
                        for stop in itinerary.stops
                    ],
                }
            )
        system = (
            "你是 CityMate 的 LLMExperienceAgent。只输出 JSON。"
            "你只能基于输入中的真实 POI 字段写路线主题和理由；缺失的价格、评分、电话、营业时间必须说未公开或不提，不能补造。"
            "理由要解释为什么这条路线匹配用户预算、偏好、天气和交通，不要写泛泛的广告文案。"
        )
        user = json.dumps(
            {
                "brief": brief.model_dump(mode="json"),
                "weather": context.weather.model_dump(mode="json"),
                "routes": routes,
                "output_schema": {"routes": [{"id": "原路线 id", "theme": "一句话主题", "reasons": ["3 到 5 条中文理由"]}]},
            },
            ensure_ascii=False,
        )
        try:
            payload = await self.llm.complete_json(system, user)
        except Exception:
            return itineraries, ["LLMExperienceAgent: 本地大模型解释暂不可用，保留规则解释。"]
        route_payloads = payload.get("routes")
        if not isinstance(route_payloads, list):
            return itineraries, ["LLMExperienceAgent: 大模型解释格式不完整，保留规则解释。"]
        by_id = {str(item.get("id")): item for item in route_payloads if isinstance(item, dict)}
        updated: list[Itinerary] = []
        for itinerary in itineraries:
            item = by_id.get(itinerary.id)
            if not item:
                updated.append(itinerary)
                continue
            theme = str(item.get("theme") or itinerary.theme).strip()[:80]
            reasons = [
                self._sanitize_llm_reason(reason, itinerary)[:140]
                for reason in self._clean_label_list(item.get("reasons"), 5)
                if len(reason) >= 4
            ]
            updated.append(itinerary.model_copy(update={"theme": theme or itinerary.theme, "reasons": reasons or itinerary.reasons}, deep=True))
        return updated, ["LLMExperienceAgent: 已用本地大模型生成路线主题和解释，且仅引用已检索到的真实字段。"]

    def _sanitize_llm_reason(self, reason: str, itinerary: Itinerary) -> str:
        clean = reason.strip()
        has_free_stop = any(stop.poi.price_per_person == 0 for stop in itinerary.stops)
        if not has_free_stop and "免费" in clean:
            clean = clean.replace("免费的", "地图未公开人均的")
            clean = clean.replace("免费", "地图未公开人均")
        if not all(stop.poi.price_per_person is not None for stop in itinerary.stops):
            clean = clean.replace("总价控制在预算内", "已知花费暂低于预算，未公开人均仍需确认")
            clean = clean.replace("控制在预算内", "已知花费暂低于预算，未公开人均仍需确认")
        return clean

    def _clean_label_list(self, value: object, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            clean = item.strip().replace("\n", " ")
            if 1 <= len(clean) <= 80 and clean not in result:
                result.append(clean)
            if len(result) >= limit:
                break
        return result

    def _safe_int(self, value: object) -> int | None:
        try:
            if value in (None, "", []):
                return None
            return int(float(str(value)))
        except (TypeError, ValueError):
            return None

    def _safe_float(self, value: object) -> float | None:
        try:
            if value in (None, "", []):
                return None
            return float(str(value))
        except (TypeError, ValueError):
            return None

    async def _preference_node(self, state: PlanState) -> PlanState:
        brief, trace = self.preference.parse(state["request"])
        search_keywords: list[str] = []
        warnings: list[str] = []
        if self._llm_enabled:
            try:
                llm_payload = await self._llm_preference_payload(state["request"], brief)
                brief = self._apply_llm_brief(brief, state["request"], llm_payload)
                search_keywords = self._llm_search_keywords(llm_payload, brief)
                trace.append("LLMPreferenceAgent/SemanticSearchAgent: 已用本地大模型增强需求解析并生成地图检索词。")
            except Exception:
                warnings.append("本地大模型解析暂不可用，已使用规则解析结果。")
        return {"brief": brief, "search_keywords": search_keywords, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _context_node(self, state: PlanState) -> PlanState:
        context, trace, warnings = await self.context.build(state["brief"], state["request"].use_live_data)
        return {"context": context, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _poi_scout_node(self, state: PlanState) -> PlanState:
        pois, trace, warnings = await self.scout.collect(
            state["brief"],
            state["context"],
            state["request"].use_live_data,
            state.get("search_keywords", []),
        )
        return {"pois": pois, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _route_planner_node(self, state: PlanState) -> PlanState:
        itineraries, trace = self.route_planner.build(state["brief"], state["context"], state["pois"])
        return {"itineraries": itineraries, "trace": state["trace"] + trace}

    async def _review_node(self, state: PlanState) -> PlanState:
        reviewed = [self.critic.review(self.budget.review(item, state["brief"]), state["brief"], state["context"]) for item in state["itineraries"]]
        trace = state["trace"] + ["BudgetAgent/CriticAgent: 完成预算、天气、距离和类别约束质检。"]
        return {"itineraries": reviewed, "trace": trace}

    def _repair_or_experience(self, state: PlanState) -> str:
        needs_repair = any(item.critique.errors for item in state["itineraries"])
        if needs_repair and state.get("repair_attempts", 0) < 1:
            return "repair"
        return "experience"

    async def _repair_node(self, state: PlanState) -> PlanState:
        repaired = [self._repair_once(item, state["brief"], state["context"], state["pois"]) for item in state["itineraries"]]
        return {
            "itineraries": repaired,
            "repair_attempts": state.get("repair_attempts", 0) + 1,
            "trace": state["trace"] + ["ReplannerAgent: Critic 触发条件边，执行一轮局部修复。"],
        }

    async def _experience_node(self, state: PlanState) -> PlanState:
        enriched = [self.experience.enrich(item, state["brief"], state["context"]) for item in state["itineraries"]]
        enriched, llm_trace = await self._llm_explain_itineraries(enriched, state["brief"], state["context"])
        enriched, geometry_trace = await self._with_route_geometries(enriched, state["brief"], state["request"].use_live_data)
        return {
            "itineraries": sorted(enriched, key=lambda item: route_rank_key(item, state["brief"]), reverse=True),
            "trace": state["trace"] + ["ExperienceAgent: 生成面向用户的主题、理由和风险标签。"] + llm_trace + geometry_trace,
        }

    async def _feedback_node(self, state: ReplanState) -> ReplanState:
        request = state["request"]
        brief = self.preference.apply_feedback(request.brief, request.feedback)
        search_keywords: list[str] = []
        trace = ["PreferenceAgent: 将用户反馈写回结构化约束。"]
        warnings: list[str] = []
        if self._llm_enabled:
            try:
                payload = await self._llm_feedback_payload(request.feedback, brief)
                brief = self._apply_llm_brief(brief, None, payload)
                search_keywords = self._llm_search_keywords(payload, brief)
                trace.append("LLMPreferenceAgent/SemanticSearchAgent: 已用本地大模型理解重排反馈并生成补充检索词。")
            except Exception:
                warnings.append("本地大模型反馈解析暂不可用，已使用规则反馈解析。")
        return {"brief": brief, "search_keywords": search_keywords, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _replan_context_node(self, state: ReplanState) -> ReplanState:
        context, trace, warnings = await self.context.build(state["brief"], state["request"].use_live_data)
        return {"context": context, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _replan_poi_scout_node(self, state: ReplanState) -> ReplanState:
        pois, trace, warnings = await self.scout.collect(
            state["brief"],
            state["context"],
            state["request"].use_live_data,
            state.get("search_keywords", []),
        )
        return {"pois": pois, "trace": state["trace"] + trace, "warnings": state["warnings"] + warnings}

    async def _replan_current_node(self, state: ReplanState) -> ReplanState:
        request = state["request"]
        updated = self.replanner.replan(request.current_itinerary, state["brief"], request.feedback, state["context"], state["pois"])
        return {"updated": updated, "trace": state["trace"] + ["ReplannerAgent: 对当前路线做局部替换和重排。"]}

    async def _replan_alternatives_node(self, state: ReplanState) -> ReplanState:
        alternatives, trace = self.route_planner.build(state["brief"], state["context"], state["pois"])
        enriched: list[Itinerary] = []
        for item in alternatives[:2]:
            item = self.critic.review(self.budget.review(item, state["brief"]), state["brief"], state["context"])
            if item.critique.errors:
                item = self._repair_once(item, state["brief"], state["context"], state["pois"])
            enriched.append(self.experience.enrich(item, state["brief"], state["context"]))
        return {"alternatives": enriched, "trace": state["trace"] + trace}

    async def _replan_compose_node(self, state: ReplanState) -> ReplanState:
        itineraries = [state["updated"], *state["alternatives"]]
        itineraries, llm_trace = await self._llm_explain_itineraries(itineraries, state["brief"], state["context"])
        itineraries, geometry_trace = await self._with_route_geometries(
            itineraries,
            state["brief"],
            state["request"].use_live_data,
        )
        return {
            "itineraries": sorted(itineraries, key=lambda item: route_rank_key(item, state["brief"]), reverse=True),
            "trace": state["trace"] + ["LangGraph: 重排子流程完成，输出主方案和备选方案。"] + llm_trace + geometry_trace,
        }

    def _repair_once(self, itinerary: Itinerary, brief: UserBrief, context: ContextSnapshot, pois: list[PoiCandidate]) -> Itinerary:
        if "雨天包含户外节点" in itinerary.critique.errors:
            return self.replanner.replan(itinerary, brief, "换室内", context, pois)
        if "预算超出过多" in itinerary.critique.errors:
            return self.replanner.replan(itinerary, brief, "便宜一点", context, pois)
        return itinerary

    async def _with_route_geometries(
        self,
        itineraries: list[Itinerary],
        brief: UserBrief,
        use_live_data: bool,
    ) -> tuple[list[Itinerary], list[str]]:
        if not use_live_data:
            return itineraries, []
        with_geometry: list[Itinerary] = []
        has_geometry = False
        for itinerary in itineraries:
            points = [brief.origin] + [stop.poi.location for stop in itinerary.stops]
            geometry = await self.bundle.client.route_geometry(points, brief.transport_mode, brief.city)
            has_geometry = has_geometry or bool(geometry)
            with_geometry.append(itinerary.model_copy(update={"route_geometry": geometry}, deep=True))
        trace = ["MapData: 已调用路线服务补全真实地图折线。"] if has_geometry else []
        return with_geometry, trace
