# CityMate 周末探索多智能体项目

CityMate 是一个面向美团命题赛道的本地生活规划项目。它用本地或 OpenAI-compatible 大模型理解用户的自然语言周末愿望，通过 LangGraph 多智能体状态图把偏好、真实地图检索、预算约束、路线质检和动态重排串成可执行、可解释的上海周末活动路线。

## 功能

- `POST /api/plan`：生成 3 条周末活动路线。
- `POST /api/replan`：根据“下雨了 / 便宜一点 / 少走路 / 换室内 / 更小众”局部重排。
- `GET /api/system`：查看 Agent 框架、节点和运行配置。
- 混合数据源：开放 API 可用时补充 OSM / Overpass / OSRM / Open-Meteo 数据；配置高德 key 后优先使用高德地理编码、POI v5 扩展字段、POI 详情补全与路线折线。
- 全国城市支持：前端提供常用城市快捷选择，也支持直接输入任意城市；后端会优先用开放地图定位城市和起点，失败时退回城市中心兜底。
- 地点与时间输入：起点框通过 `/api/places/search` 调用开放地图检索候选地点；出发时间使用日期和时间选择器。
- 授权平台数据增强：可通过 `CITYMATE_VENDOR_DATA_PATH` 导入美团 / 大众点评授权数据，也可通过 `CITYMATE_VENDOR_API_URL` 接入内部授权商家 API，覆盖门店图、评分、评论数、人均、地址、优惠和平台链接。
- 大模型多智能体：`LLMPreferenceAgent` 负责语义解析，`SemanticSearchAgent` 生成高德检索词补充真实 POI，`LLMExperienceAgent` 基于已检索字段生成路线解释；未配置大模型时自动退回规则 Agent。
- 可插拔模型：支持本地 Ollama 或任意 OpenAI-compatible 服务。本机推荐 `gemma3:12b` 做中文文本规划；`qwen2.5vl:7b` 更偏视觉，当前项目不优先使用。
- 前端三栏工作台支持拖拽调整宽度，地图图例、路线 Tab、重排、保存偏好、深色模式和备选方案切换均可交互。

## 项目结构

```text
backend/   FastAPI 后端、LangGraph 工作流、开放数据适配、测试
frontend/  Vite + React + TypeScript + Leaflet 前端，可配置地图瓦片
docs/      架构和工程说明
start.sh   一键启动后端和前端
```

核心后端模块：

```text
backend/app/agents.py    业务 Agent：偏好、上下文、POI、路线、预算、质检、重排、体验文案
backend/app/workflow.py  LangGraph 状态图：节点编排、条件修复边、重排子流程
backend/app/services.py  高德 / Nominatim / Overpass / OSRM / Open-Meteo 适配和兜底算法
backend/app/vendor_data.py  授权美团 / 大众点评导出数据和商家 API 覆盖层
backend/app/llm.py       Mock / Ollama / OpenAI-compatible LLM 插拔层
```

## 快速启动

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm install
cd ..

./start.sh
```

启动后访问：

- 前端：http://127.0.0.1:5173
- 后端：http://127.0.0.1:8000/docs

前端默认通过同源 `/api` 访问后端，并由 Vite dev server 代理到 `127.0.0.1:8000`。这样在 IDE 端口转发或远程浏览器预览里也不会因为浏览器侧的 `127.0.0.1` 指向错误机器而出现 `Failed to fetch`。

默认输入：

```text
周六下午在上海，4 小时，预算 300，两个人，想轻松一点，不想太网红，最好地铁方便。
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需配置。没有任何密钥时，项目仍会使用 Mock Agent 和种子数据完整运行；如果本机有 Ollama，可直接用本地模型参与语义解析、检索规划和路线解释。

```bash
cp .env.example .env
```

GitHub 上传说明：

- 只提交 `.env.example`，不要提交本地 `.env`。
- `AMAP_WEB_SERVICE_KEY` 需要使用者自己申请。
- 如果不用本机 Ollama，而是用云端模型，`OPENAI_API_KEY` 也需要使用者自己配置。
- 如果接入授权商家 API，`CITYMATE_VENDOR_API_KEY` 和私有商家数据也不能上传。

如需显示真实平台图和评分，将授权获得的数据整理为 `docs/vendor-data.example.json` 的格式，并设置：

```bash
CITYMATE_VENDOR_DATA_PATH=/absolute/path/to/vendor-data.json
```

如需优先使用高德地图 Web 服务：

```bash
CITYMATE_MAP_PROVIDER=amap
AMAP_WEB_SERVICE_KEY=your-amap-web-service-key
```

当前高德接入会调用：

- `v3/geocode/geo`：城市和起点地理编码。
- `v5/place/around`：按当前位置检索真实 POI，并请求 `business,photos,indoor,navi` 扩展字段。
- `v5/place/detail`：对候选 POI 再按 ID 补全营业时间、电话、商圈、人均、评分、照片等字段。
- `v3/direction/*`：为路线绘制真实地图折线。

价格、评分、电话、营业时间和照片只有在高德或授权商家数据真实返回时才展示；缺失时前端显示“暂无评分 / 人均待确认”或直接隐藏字段，不用本地估算值冒充真实商家数据。

如需启用本地 Ollama 大模型：

```bash
ollama serve
ollama pull gemma3:12b

CITYMATE_LLM_PROVIDER=ollama
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_MODEL=gemma3:12b
OPENAI_API_KEY=
CITYMATE_REQUEST_TIMEOUT=20.0
```

如果使用云端 OpenAI-compatible 服务：

```bash
CITYMATE_LLM_PROVIDER=openai-compatible
OPENAI_BASE_URL=https://your-provider.example.com/v1
OPENAI_MODEL=your-model
OPENAI_API_KEY=your-api-key
```

如需接入授权商家 API：

```bash
CITYMATE_VENDOR_API_URL=https://your-internal.example.com/citymate/vendors
CITYMATE_VENDOR_API_KEY=your-token
```

后端会向 `CITYMATE_VENDOR_API_URL` POST `city` 和候选 POI 列表，期望返回 `docs/vendor-data.example.json` 同类结构。说明：项目不会内置未授权的美团 / 大众点评页面抓取逻辑；评分、门店图、优惠和商家链接会在授权数据或平台 API 提供时自动覆盖到同名或同 ID POI。若你部署环境对公网 API 网络较慢，建议把 `CITYMATE_REQUEST_TIMEOUT` 调到 `6~10` 秒。

前端地图瓦片可通过以下变量切换到合规的商业瓦片服务：

```bash
VITE_MAP_TILE_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
VITE_MAP_ATTRIBUTION=&copy; OpenStreetMap contributors
```

## 测试

```bash
. .venv/bin/activate
pytest backend/tests

cd frontend
npm run build
```

## 工程定位

本项目不是单个聊天机器人，而是“约束规划 + 多智能体协作”的本地生活系统：

- LangGraph 负责有状态编排和条件修复。
- LLM Agent 负责语义解析、检索词生成和用户可读解释；规则 Agent 负责预算、时间、距离、天气和缺失字段约束。
- 地图和商家字段来自高德或授权 API，大模型只能基于这些字段推理与表达，不能生成价格、评分、电话或虚构商家。
- 开放地图与内置种子数据并行，保证真实数据可用时更丰富、不可用时仍稳定。
