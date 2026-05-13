# CityMate Architecture

## 系统目标

CityMate 面向“周末闲时活动规划”场景，不做单点 POI 推荐，而是输出可执行的本地生活路线。系统核心是把模糊意图变成结构化约束，再通过多智能体状态图完成候选生成、约束检查和动态重排。

## Agent Graph

主流程由 `backend/app/workflow.py` 中的 LangGraph `StateGraph` 编排：

```text
START
  -> PreferenceAgent
  -> ContextAgent
  -> PoiScoutAgent
  -> RoutePlannerAgent
  -> BudgetAgent + CriticAgent
  -> conditional:
       repair needed -> ReplannerAgent -> review
       valid route   -> ExperienceAgent
  -> END
```

重排流程：

```text
START
  -> PreferenceAgent feedback merge
  -> ContextAgent
  -> PoiScoutAgent
  -> ReplannerAgent
  -> RoutePlannerAgent alternatives
  -> compose
  -> END
```

## Agent Responsibilities

- `PreferenceAgent`：抽取城市、预算、人数、时间、偏好、硬约束。
- `ContextAgent`：聚合天气、城市中心点和运行上下文。
- `PoiScoutAgent`：合并真实地图 POI、授权商家数据与内置种子数据。
- `RoutePlannerAgent`：按路线模板、预算压力、类别多样性和距离生成候选方案。
- `BudgetAgent`：估算总花费并标记预算风险。
- `CriticAgent`：检查预算、天气、距离、类别重复和节点数量。
- `ReplannerAgent`：对雨天、低预算、少走路、小众偏好做局部替换。
- `ExperienceAgent`：生成主题、推荐理由和展示标签。

## Data Sources

- Seed POI：默认上海本地生活种子数据，保证离线可用。
- 高德 Web 服务：配置 `CITYMATE_MAP_PROVIDER=amap` 和 `AMAP_WEB_SERVICE_KEY` 后，用于地理编码、地点搜索、周边 POI 与路线折线。
- Nominatim：开放地理编码兜底。
- Overpass：开放 POI 检索兜底。
- Open-Meteo：天气。
- OSRM：路线折线和时长估算兜底；失败时用 haversine 兜底。
- 授权商家数据：`CITYMATE_VENDOR_DATA_PATH` 支持本地 JSON 覆盖；`CITYMATE_VENDOR_API_URL` 支持内部授权商家 API 覆盖评分、价格、图片、优惠和商家链接。

## LLM Strategy

`backend/app/llm.py` 提供两类客户端：

- `MockLLMClient`：默认使用，无密钥可运行。
- `OpenAICompatibleLLMClient`：通过 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL` 接入 OpenAI-compatible 服务。

当前版本把关键规划逻辑放在可测试的确定性 Agent 中，LLM 层用于后续升级偏好理解、解释生成、多人偏好协商和对话记忆。

## Public API

- `GET /api/health`
- `GET /api/system`
- `GET /api/map/config`
- `POST /api/plan`
- `POST /api/replan`

## Acceptance Criteria

- 默认中文输入能返回 3 条路线。
- 每条路线包含时间线、预算、通勤、POI 坐标、真实路线折线和推荐理由。
- 开放 API 不可用时仍能通过种子数据返回结果。
- “下雨了，换室内”能触发重排，并把主路线变成室内优先。
- Agent trace 中能看到 LangGraph 和各 Agent 节点。
