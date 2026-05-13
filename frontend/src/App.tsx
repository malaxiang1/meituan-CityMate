import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import {
  Banknote,
  Bot,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Clock3,
  CloudRain,
  ExternalLink,
  Gift,
  Home,
  Leaf,
  Loader2,
  MapPin,
  Moon,
  Navigation,
  Phone,
  RefreshCw,
  RotateCcw,
  Route,
  Save,
  Search,
  ShieldCheck,
  Shuffle,
  Sparkles,
  Star,
  Sun,
  Umbrella,
  Users,
  WalletCards,
  X,
} from "lucide-react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { createPlan, getSystemProfile, replan, searchPlaces } from "./api";
import cityMatePin from "./assets/citymate-pin.png";
import type { Itinerary, ItineraryStop, PlaceSuggestion, PlanPayload, PlanResponse, SystemProfile } from "./types";

const DEFAULT_QUERY = "周六下午在上海，4 小时，预算 300，两个人，想轻松一点，不想太网红，最好地铁方便。";
const DEFAULT_DATE = toDateInputValue(new Date());
const DEFAULT_TIME = "14:00";
const TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  import.meta.env.VITE_MAP_ATTRIBUTION || "&copy; OpenStreetMap contributors";

const CITY_OPTIONS = [
  "上海",
  "北京",
  "广州",
  "深圳",
  "杭州",
  "南京",
  "苏州",
  "成都",
  "重庆",
  "武汉",
  "西安",
  "长沙",
  "郑州",
  "青岛",
  "济南",
  "厦门",
  "福州",
  "宁波",
  "无锡",
  "合肥",
  "南昌",
  "昆明",
  "贵阳",
  "南宁",
  "海口",
  "三亚",
  "天津",
  "沈阳",
  "大连",
  "长春",
  "哈尔滨",
  "兰州",
  "西宁",
  "银川",
  "乌鲁木齐",
  "拉萨",
  "香港",
  "澳门",
  "台北",
  "佛山",
  "东莞",
  "珠海",
  "常州",
  "扬州",
  "嘉兴",
  "绍兴",
  "温州",
  "泉州",
  "桂林",
  "丽江",
  "大理",
];

const DEFAULT_ORIGINS: Record<string, string> = {
  上海: "人民广场",
  北京: "王府井",
  广州: "体育西路",
  深圳: "市民中心",
  杭州: "武林广场",
  南京: "新街口",
  苏州: "观前街",
  成都: "天府广场",
  重庆: "解放碑",
  武汉: "江汉路",
  西安: "钟楼",
  长沙: "五一广场",
  郑州: "二七广场",
  青岛: "五四广场",
  济南: "泉城广场",
  厦门: "中山路",
  福州: "三坊七巷",
  天津: "和平路",
};

const CITY_ALIASES: Record<string, string[]> = {
  上海: ["shanghai", "sh", "sha"],
  北京: ["beijing", "bj", "peking"],
  广州: ["guangzhou", "gz", "canton"],
  深圳: ["shenzhen", "sz"],
  杭州: ["hangzhou", "hz"],
  南京: ["nanjing", "nj"],
  苏州: ["suzhou", "su"],
  成都: ["chengdu", "cd"],
  重庆: ["chongqing", "cq"],
  武汉: ["wuhan", "wh"],
  西安: ["xian", "xa"],
  长沙: ["changsha", "cs"],
  郑州: ["zhengzhou", "zz"],
  青岛: ["qingdao", "qd"],
  济南: ["jinan", "jn"],
  厦门: ["xiamen", "xm", "amoy"],
  福州: ["fuzhou", "fz"],
  宁波: ["ningbo", "nb"],
  无锡: ["wuxi", "wx"],
  合肥: ["hefei", "hf"],
  南昌: ["nanchang", "nc"],
  昆明: ["kunming", "km"],
  贵阳: ["guiyang", "gy"],
  南宁: ["nanning", "nn"],
  海口: ["haikou"],
  三亚: ["sanya"],
  天津: ["tianjin", "tj"],
  沈阳: ["shenyang"],
  大连: ["dalian", "dl"],
  长春: ["changchun", "cc"],
  哈尔滨: ["haerbin", "harbin", "heb"],
  兰州: ["lanzhou", "lz"],
  西宁: ["xining", "xn"],
  银川: ["yinchuan", "yc"],
  乌鲁木齐: ["wulumuqi", "urumqi", "wlmq"],
  拉萨: ["lasa", "lhasa", "ls"],
  香港: ["xianggang", "hongkong", "hk"],
  澳门: ["aomen", "macau", "mo"],
  台北: ["taibei", "taipei", "tb"],
  佛山: ["foshan", "fs"],
  东莞: ["dongguan", "dg"],
  珠海: ["zhuhai", "zh"],
  常州: ["changzhou", "cz"],
  扬州: ["yangzhou", "yz"],
  嘉兴: ["jiaxing", "jx"],
  绍兴: ["shaoxing", "sx"],
  温州: ["wenzhou", "wz"],
  泉州: ["quanzhou", "qz"],
  桂林: ["guilin", "gl"],
  丽江: ["lijiang", "lj"],
  大理: ["dali", "dl"],
};

const PREFERENCE_CHIPS = ["轻松", "小众", "文艺", "美食", "自然", "室内", "拍照"];

const ROUTE_ICONS = [Leaf, Search, Banknote];

const FEEDBACKS = [
  { label: "下雨了", icon: CloudRain },
  { label: "便宜一点", icon: Banknote },
  { label: "更小众", icon: Star },
  { label: "少走路", icon: Navigation },
  { label: "换室内", icon: Home },
];

function markerIconFor(index: number) {
  return L.divIcon({
    className: `citymate-marker citymate-marker-${index + 1}`,
    html: `<span>${index + 1}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function toDateInputValue(date: Date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatStartTime(date: string, time: string) {
  if (!date) return time;
  return `${date} ${time || "14:00"}`;
}

function normalizeCityKeyword(value: string) {
  return value.trim().replace(/市$/, "").toLowerCase().replace(/[\s_-]+/g, "");
}

function cityMatches(cityName: string, keyword: string) {
  const normalizedKeyword = normalizeCityKeyword(keyword);
  if (!normalizedKeyword) return true;
  const normalizedCity = normalizeCityKeyword(cityName);
  const aliases = CITY_ALIASES[cityName] ?? [];
  return normalizedCity.includes(normalizedKeyword) || aliases.some((alias) => alias.includes(normalizedKeyword));
}

function matchCities(keyword: string) {
  const normalizedKeyword = normalizeCityKeyword(keyword);
  if (!normalizedKeyword) return CITY_OPTIONS;
  return CITY_OPTIONS.filter((item) => cityMatches(item, keyword));
}

function resolveCityInput(value: string) {
  const normalizedKeyword = normalizeCityKeyword(value);
  if (!normalizedKeyword) return null;
  return (
    CITY_OPTIONS.find((item) => {
      const aliases = CITY_ALIASES[item] ?? [];
      return normalizeCityKeyword(item) === normalizedKeyword || aliases.includes(normalizedKeyword);
    }) ?? null
  );
}

function isCustomChineseCity(value: string) {
  const normalized = value.trim().replace(/市$/, "");
  return /^[\u4e00-\u9fff]{2,10}$/.test(normalized) && !resolveCityInput(normalized);
}

function App() {
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const cityInputRef = useRef<HTMLInputElement | null>(null);
  const cityAutocompleteRef = useRef<HTMLDivElement | null>(null);
  const originAutocompleteRef = useRef<HTMLDivElement | null>(null);
  const cityMenuRef = useRef<HTMLDivElement | null>(null);
  const blindSpinTimerRef = useRef<number | null>(null);
  const blindRevealTimerRef = useRef<number | null>(null);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [city, setCity] = useState("上海");
  const [cityDraft, setCityDraft] = useState("上海");
  const [origin, setOrigin] = useState("人民广场");
  const [originSuggestions, setOriginSuggestions] = useState<PlaceSuggestion[]>([]);
  const [originOpen, setOriginOpen] = useState(false);
  const [originLoading, setOriginLoading] = useState(false);
  const [startDate, setStartDate] = useState(DEFAULT_DATE);
  const [startClock, setStartClock] = useState(DEFAULT_TIME);
  const [duration, setDuration] = useState(4);
  const [budget, setBudget] = useState(300);
  const [partySize, setPartySize] = useState(2);
  const [useLiveData, setUseLiveData] = useState(true);
  const [response, setResponse] = useState<PlanResponse | null>(null);
  const [systemProfile, setSystemProfile] = useState<SystemProfile | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [activePrefs, setActivePrefs] = useState<string[]>(["轻松"]);
  const [loading, setLoading] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [darkMode, setDarkMode] = useState(false);
  const [cityMenuOpen, setCityMenuOpen] = useState(false);
  const [cityInputOpen, setCityInputOpen] = useState(false);
  const [citySearch, setCitySearch] = useState("");
  const [blindBoxOpen, setBlindBoxOpen] = useState(false);
  const [blindDrawing, setBlindDrawing] = useState(false);
  const [blindResultIndex, setBlindResultIndex] = useState<number | null>(null);
  const [leftWidth, setLeftWidth] = useState(440);
  const [rightWidth, setRightWidth] = useState(440);

  const selected = response?.itineraries[selectedIndex] ?? null;
  const workspaceColumns = `${leftWidth}px 8px minmax(520px, 1fr) 8px ${rightWidth}px`;
  const filteredCities = useMemo(() => {
    return matchCities(citySearch).slice(0, 24);
  }, [citySearch]);
  const citySuggestions = useMemo(() => matchCities(cityDraft).slice(0, 8), [cityDraft]);
  const citySearchCustom = isCustomChineseCity(citySearch);
  const cityDraftCustom = isCustomChineseCity(cityDraft);

  useEffect(() => {
    getSystemProfile()
      .then(setSystemProfile)
      .catch(() => setSystemProfile(null));
  }, []);

  useEffect(() => {
    return () => {
      if (blindSpinTimerRef.current) window.clearInterval(blindSpinTimerRef.current);
      if (blindRevealTimerRef.current) window.clearTimeout(blindRevealTimerRef.current);
    };
  }, []);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!cityMenuRef.current?.contains(target)) {
        setCityMenuOpen(false);
      }
      if (!cityAutocompleteRef.current?.contains(target)) {
        if (cityInputOpen && !resolveCityInput(cityDraft) && !isCustomChineseCity(cityDraft)) {
          setCityDraft(city);
        }
        setCityInputOpen(false);
      }
      if (!originAutocompleteRef.current?.contains(target)) {
        setOriginOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [city, cityDraft, cityInputOpen]);

  useEffect(() => {
    const keyword = origin.trim();
    if (!originOpen || keyword.length < 1) {
      setOriginSuggestions([]);
      return;
    }
    let cancelled = false;
    setOriginLoading(true);
    const timer = window.setTimeout(() => {
      searchPlaces(city, keyword)
        .then((items) => {
          if (!cancelled) setOriginSuggestions(items);
        })
        .catch(() => {
          if (!cancelled) setOriginSuggestions([]);
        })
        .finally(() => {
          if (!cancelled) setOriginLoading(false);
        });
    }, 260);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [city, origin, originOpen]);

  const mapCenter = useMemo<[number, number]>(() => {
    if (selected?.stops.length) {
      return [selected.stops[0].poi.location.lat, selected.stops[0].poi.location.lng];
    }
    return [31.2304, 121.4737];
  }, [selected]);

  async function runPlan(toastMessage: string | false = "已生成 3 条候选路线，并完成预算与质量检查。") {
    const resolvedCity = resolveCityInput(cityDraft) ?? (isCustomChineseCity(cityDraft) ? cityDraft.trim().replace(/市$/, "") : null);
    if (!resolvedCity) {
      setError("请从城市候选中选择有效城市；例如输入 beijing 后选择“北京”。");
      setToast(null);
      setCityInputOpen(true);
      cityInputRef.current?.focus();
      return null;
    }
    const payloadOrigin = resolvedCity !== city && DEFAULT_ORIGINS[resolvedCity] ? DEFAULT_ORIGINS[resolvedCity] : origin;
    if (resolvedCity !== city) {
      setCity(resolvedCity);
      setCityDraft(resolvedCity);
      setOrigin(payloadOrigin);
    }
    if (!payloadOrigin.trim()) {
      setError("请选择或输入一个起点。");
      setToast(null);
      setOriginOpen(true);
      return null;
    }
    setLoading(true);
    setActiveAction("plan");
    setError(null);
    if (toastMessage !== false) setToast(null);
    try {
      const payload: PlanPayload = {
        query,
        city: resolvedCity,
        origin_name: payloadOrigin,
        start_time: formatStartTime(startDate, startClock),
        duration_hours: duration,
        budget,
        party_size: partySize,
        use_live_data: useLiveData,
      };
      const result = await createPlan(payload);
      setResponse(result);
      setSelectedIndex(0);
      setBlindResultIndex(null);
      if (toastMessage !== false) setToast(toastMessage);
      return result;
    } catch (err) {
      setError(formatError(err));
      return null;
    } finally {
      setLoading(false);
      setActiveAction(null);
    }
  }

  async function handlePlan() {
    await runPlan();
  }

  async function handleReplan(feedback: string) {
    if (!response || !selected) return;
    setLoading(true);
    setActiveAction(feedback);
    setError(null);
    setToast(null);
    try {
      const result = await replan(feedback, selected, response.brief, useLiveData);
      setResponse(result);
      setSelectedIndex(0);
      setBlindResultIndex(null);
      setToast(`已根据“${feedback}”优化路线，尽量保留原有结构。`);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setLoading(false);
      setActiveAction(null);
    }
  }

  function togglePreference(label: string) {
    setActivePrefs((current) => {
      if (current.includes(label)) return current.filter((item) => item !== label);
      return [...current, label];
    });
    if (!query.includes(label)) {
      setQuery((current) => `${current.replace(/。$/, "")}，偏好${label}。`);
    }
  }

  function resetForm() {
    setQuery(DEFAULT_QUERY);
    setCity("上海");
    setCityDraft("上海");
    setOrigin("人民广场");
    setOriginSuggestions([]);
    setOriginOpen(false);
    setStartDate(DEFAULT_DATE);
    setStartClock(DEFAULT_TIME);
    setDuration(4);
    setBudget(300);
    setPartySize(2);
    setActivePrefs(["轻松"]);
    setError(null);
    setToast(null);
  }

  function savePreference() {
    localStorage.setItem(
      "citymate:lastPreference",
      JSON.stringify({
        query,
        city,
        origin,
        startDate,
        startClock,
        duration,
        budget,
        partySize,
        activePrefs,
        savedAt: new Date().toISOString(),
      }),
    );
    setToast("已保存当前偏好到本地。");
  }

  function showAlternatives() {
    if (!response) return;
    setSelectedIndex((current) => (current + 1) % response.itineraries.length);
    setToast("已切换到下一条备选方案。");
  }

  async function openBlindBox() {
    if (loading || blindDrawing) return;
    setBlindBoxOpen(true);
    setBlindResultIndex(null);
    let source = response;
    if (!source?.itineraries.length) {
      setToast("正在先装好三条路线，再开盲盒。");
      source = await runPlan(false);
    }
    if (!source?.itineraries.length) {
      setBlindDrawing(false);
      return;
    }
    const routes = source.itineraries;
    if (blindSpinTimerRef.current) window.clearInterval(blindSpinTimerRef.current);
    if (blindRevealTimerRef.current) window.clearTimeout(blindRevealTimerRef.current);

    setBlindDrawing(true);
    let spin = 0;
    blindSpinTimerRef.current = window.setInterval(() => {
      spin += 1;
      setSelectedIndex(spin % routes.length);
    }, 120);

    blindRevealTimerRef.current = window.setTimeout(() => {
      if (blindSpinTimerRef.current) window.clearInterval(blindSpinTimerRef.current);
      const pick = Math.floor(Math.random() * routes.length);
      setSelectedIndex(pick);
      setBlindResultIndex(pick);
      setBlindDrawing(false);
      setToast(`路线盲盒开出了「${routes[pick].title}」。`);
    }, 1600);
  }

function showSystemStatus() {
    const framework = systemProfile?.agent_framework ?? "LangGraph";
    const provider = systemProfile?.llm_provider === "mock" ? "Mock LLM" : systemProfile?.llm_provider ?? "Mock LLM";
    const mapProvider = systemProfile?.amap_enabled ? "高德地图" : "开放地图服务";
    const merchant = systemProfile?.merchant_api_enabled ? "已接入授权商家 API" : "未配置授权商家 API";
    setToast(`当前运行：${framework} 多智能体编排，模型层为 ${provider}，地图为 ${mapProvider}，${merchant}。`);
  }

  function toggleTheme() {
    setDarkMode((current) => {
      const next = !current;
      setToast(next ? "已切换到夜晚模式。" : "已切换到白天模式。");
      return next;
    });
  }

  function selectCity(nextCity: string) {
    const cleanCity = nextCity.trim().replace(/市$/, "");
    if (!cleanCity) return;
    const previousCity = city;
    setCity(cleanCity);
    setCityDraft(cleanCity);
    setOrigin(DEFAULT_ORIGINS[cleanCity] ?? "市中心");
    setOriginSuggestions([]);
    setOriginOpen(false);
    setCitySearch("");
    setCityMenuOpen(false);
    setCityInputOpen(false);
    setQuery((current) => {
      if (previousCity && current.includes(previousCity)) return current.split(previousCity).join(cleanCity);
      return `${current.replace(/。$/, "")}，城市改为${cleanCity}。`;
    });
    setToast(`已切换到 ${cleanCity}，开放数据会优先检索当地真实地点。`);
  }

  function commitCityInput(value: string) {
    const resolved = resolveCityInput(value) ?? citySuggestions[0] ?? null;
    if (resolved) {
      selectCity(resolved);
      return;
    }
    if (isCustomChineseCity(value)) {
      selectCity(value.trim().replace(/市$/, ""));
      return;
    }
    setError("没有找到这个城市，请从候选项里选择。");
    setToast(null);
    setCityInputOpen(true);
  }

  function commitCitySearch() {
    const resolved = resolveCityInput(citySearch) ?? filteredCities[0] ?? null;
    if (resolved) {
      selectCity(resolved);
      return;
    }
    if (isCustomChineseCity(citySearch)) {
      selectCity(citySearch.trim().replace(/市$/, ""));
      return;
    }
    setToast("没有找到匹配城市，请输入中文城市名或选择候选项。");
  }

  function selectOrigin(place: PlaceSuggestion) {
    setOrigin(place.name);
    setOriginSuggestions([]);
    setOriginOpen(false);
    setToast(`起点已设为 ${place.name}。`);
  }

  function commitOriginInput() {
    const first = originSuggestions[0];
    if (first) {
      selectOrigin(first);
      return;
    }
    if (!origin.trim()) {
      setError("请选择或输入一个起点。");
      setOriginOpen(true);
      return;
    }
    setOriginOpen(false);
  }

  function startResize(side: "left" | "right", event: ReactPointerEvent<HTMLDivElement>) {
    const workspace = workspaceRef.current;
    if (!workspace) return;
    event.preventDefault();
    const rect = workspace.getBoundingClientRect();
    const startX = event.clientX;
    const startLeft = leftWidth;
    const startRight = rightWidth;
    const minLeft = 340;
    const minRight = 360;
    const minCenter = 520;
    const reservedGap = 72;

    function onPointerMove(moveEvent: PointerEvent) {
      const delta = moveEvent.clientX - startX;
      if (side === "left") {
        const maxLeft = Math.max(minLeft, rect.width - startRight - minCenter - reservedGap);
        setLeftWidth(clamp(startLeft + delta, minLeft, maxLeft));
      } else {
        const maxRight = Math.max(minRight, rect.width - startLeft - minCenter - reservedGap);
        setRightWidth(clamp(startRight - delta, minRight, maxRight));
      }
    }

    function onPointerUp() {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
      document.body.classList.remove("is-resizing");
    }

    document.body.classList.add("is-resizing");
    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
  }

  return (
    <main className={`app-shell ${darkMode ? "theme-dark" : ""}`}>
      <header className="topbar">
        <div className="brand-lockup">
          <div className="logo-combo">
            <span className="logo-pin">
              <img src={cityMatePin} alt="" />
            </span>
            <span className="logo-wordmark">
              <span>
                City<strong>Mate</strong>
              </span>
              <em>— 周末探索 —</em>
            </span>
          </div>
          <span className="demo-pill">
            <Sparkles size={15} />
            Multi-Agent Demo
          </span>
        </div>
        <div className="top-actions">
          <button className="toolbar-pill" type="button" onClick={showSystemStatus}>
            <Bot size={18} />
            {systemProfile?.llm_provider === "mock" ? "Mock LLM" : systemProfile?.llm_provider ?? "Mock LLM"}
          </button>
          <div className="city-menu-wrap" ref={cityMenuRef}>
            <button className={`toolbar-plain ${cityMenuOpen ? "toolbar-active" : ""}`} type="button" onClick={() => setCityMenuOpen((current) => !current)}>
              <MapPin size={20} />
              {city}
              <ChevronDown size={16} />
            </button>
            {cityMenuOpen && (
              <div className="city-popover">
                <div className="city-popover-head">
                  <strong>选择城市</strong>
                  <span>支持全国任意城市</span>
                </div>
                <div className="city-search">
                  <Search size={15} />
                  <input
                    autoFocus
                    value={citySearch}
                    placeholder="搜索或输入城市"
                    onChange={(event) => setCitySearch(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitCitySearch();
                    }}
                  />
                </div>
                <div className="city-grid">
                  {filteredCities.map((item) => (
                    <button key={item} type="button" className={item === city ? "city-option-active" : ""} onClick={() => selectCity(item)}>
                      {item}
                    </button>
                  ))}
                </div>
                {citySearchCustom && (
                  <button className="city-custom" type="button" onClick={() => selectCity(citySearch)}>
                    使用“{citySearch.trim().replace(/市$/, "")}”（开放地图搜索）
                  </button>
                )}
              </div>
            )}
          </div>
          <button className={`toolbar-icon ${darkMode ? "toolbar-active" : ""}`} type="button" onClick={toggleTheme} aria-label="切换白天夜晚模式">
            {darkMode ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <button className="avatar" type="button" onClick={savePreference} aria-label="保存当前偏好">
            C
          </button>
        </div>
      </header>

      <div ref={workspaceRef} className="workspace-grid" style={{ gridTemplateColumns: workspaceColumns }}>
        <aside className="planner-panel">
          <div className="panel-title">
            <CalendarDays size={20} />
            <h2>行程需求</h2>
          </div>

          <div className="form-grid">
            <Field label="城市" icon={<MapPin size={16} />}>
              <div className="city-autocomplete" ref={cityAutocompleteRef}>
                <input
                  ref={cityInputRef}
                  value={cityDraft}
                  onFocus={() => setCityInputOpen(true)}
                  onChange={(event) => {
                    setCityDraft(event.target.value);
                    setCityInputOpen(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitCityInput(cityDraft);
                    }
                    if (event.key === "Escape") {
                      setCityDraft(city);
                      setCityInputOpen(false);
                    }
                  }}
                />
                {cityInputOpen && (
                  <div className="city-suggest-list">
                    {citySuggestions.length > 0 ? (
                      citySuggestions.map((item) => (
                        <button key={item} type="button" className={item === city ? "city-suggest-active" : ""} onClick={() => selectCity(item)}>
                          <span>{item}</span>
                          <em>{(CITY_ALIASES[item] ?? [])[0] ?? "city"}</em>
                        </button>
                      ))
                    ) : cityDraftCustom ? (
                      <button type="button" onClick={() => selectCity(cityDraft.trim().replace(/市$/, ""))}>
                        <span>{cityDraft.trim().replace(/市$/, "")}</span>
                        <em>开放地图搜索</em>
                      </button>
                    ) : (
                      <div className="city-suggest-empty">未找到城市，请选择候选项</div>
                    )}
                  </div>
                )}
              </div>
            </Field>
            <Field label="起点" icon={<MapPin size={16} />}>
              <div className="place-autocomplete" ref={originAutocompleteRef}>
                <input
                  value={origin}
                  placeholder="搜索地铁站、商圈、景点"
                  onFocus={() => setOriginOpen(true)}
                  onChange={(event) => {
                    setOrigin(event.target.value);
                    setOriginOpen(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      commitOriginInput();
                    }
                    if (event.key === "Escape") setOriginOpen(false);
                  }}
                />
                {originOpen && (
                  <div className="place-suggest-list">
                    {originLoading ? (
                      <div className="place-suggest-empty">
                        <Loader2 className="animate-spin" size={14} />
                        正在搜索地图地点
                      </div>
                    ) : originSuggestions.length > 0 ? (
                      originSuggestions.map((place) => (
                        <button key={`${place.name}-${place.location.lat}-${place.location.lng}`} type="button" onClick={() => selectOrigin(place)}>
                          <span>{place.name}</span>
                          <em>{place.address || place.source}</em>
                        </button>
                      ))
                    ) : (
                      <div className="place-suggest-empty">输入后从地图 API 搜索地点</div>
                    )}
                  </div>
                )}
              </div>
            </Field>
            <Field label="时间" icon={<CalendarDays size={16} />}>
              <div className="datetime-inline">
                <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                <input type="time" value={startClock} onChange={(event) => setStartClock(event.target.value)} />
              </div>
            </Field>
            <Field label="时长" icon={<Clock3 size={16} />}>
              <input type="number" min={2} max={10} value={duration} onChange={(event) => setDuration(Number(event.target.value))} />
            </Field>
            <Field label="预算 (RMB)" icon={<WalletCards size={16} />}>
              <input type="number" min={80} step={20} value={budget} onChange={(event) => setBudget(Number(event.target.value))} />
            </Field>
            <Field label="人数" icon={<Users size={16} />}>
              <input type="number" min={1} max={8} value={partySize} onChange={(event) => setPartySize(Number(event.target.value))} />
            </Field>
          </div>

          <div className="pref-block">
            <span>偏好（可多选）</span>
            <div className="pref-grid">
              {PREFERENCE_CHIPS.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={`pref-chip ${activePrefs.includes(label) ? "pref-chip-active" : ""}`}
                  onClick={() => togglePreference(label)}
                >
                  {label}
                  {activePrefs.includes(label) && <CheckCircle2 size={14} />}
                </button>
              ))}
            </div>
          </div>

          <label className="demand-box">
            <span>自然语言需求</span>
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} maxLength={200} rows={6} />
            <small>{query.length}/200</small>
          </label>

          <label className="switch-row">
            <span>开放数据</span>
            <input type="checkbox" checked={useLiveData} onChange={(event) => setUseLiveData(event.target.checked)} />
          </label>

          <button className="primary-button" onClick={handlePlan} disabled={loading || query.trim().length < 2}>
            {loading ? <Loader2 className="animate-spin" size={18} /> : <Sparkles size={18} />}
            生成路线
          </button>
          <button className="blind-entry-button" onClick={openBlindBox} disabled={loading || blindDrawing} type="button">
            {loading || blindDrawing ? <Loader2 className="animate-spin" size={18} /> : <Gift size={18} />}
            路线盲盒
          </button>

          <div className="utility-row">
            <button className="ghost-button" onClick={resetForm} type="button">
              <RotateCcw size={17} />
              重置
            </button>
            <button className="ghost-button" onClick={savePreference} type="button">
              <Save size={17} />
              保存为偏好
            </button>
          </div>

          {error && <div className="error-box">{error}</div>}
          {toast && <div className="toast-box">{toast}</div>}

          <AgentStatus systemProfile={systemProfile} activeAction={activeAction} />
        </aside>

        <div className="resize-handle" role="separator" aria-label="调整输入区宽度" onPointerDown={(event) => startResize("left", event)} />

        <section className="result-panel">
          {!response || !selected ? (
            <EmptyState loading={loading || blindDrawing} onPlan={handlePlan} onBlindBox={openBlindBox} />
          ) : (
            <RouteBoard
              response={response}
              selected={selected}
              selectedIndex={selectedIndex}
              onSelect={setSelectedIndex}
              onReplan={handleReplan}
              onBlindBox={openBlindBox}
              loading={loading}
              blindDrawing={blindDrawing}
              activeAction={activeAction}
            />
          )}
        </section>

        <div className="resize-handle" role="separator" aria-label="调整地图区宽度" onPointerDown={(event) => startResize("right", event)} />

        <aside className="map-panel">
          <div className="map-frame">
            <RouteMap selected={selected} center={mapCenter} />
            <div className="map-provider-chip">{systemProfile?.amap_enabled ? "高德 POI + 路线" : "开放地图"}</div>
            {selected && <MapLegend selected={selected} />}
          </div>
          {response && selected ? (
            <>
              <WeatherCard response={response} selected={selected} />
              <QualityCard selected={selected} budget={response.brief.budget} onShowAlternatives={showAlternatives} />
            </>
          ) : (
            <div className="map-empty">
              <Route size={26} />
              <span>生成路线后展示地图和质量检查</span>
            </div>
          )}
        </aside>
      </div>
      <BlindBoxOverlay
        open={blindBoxOpen}
        response={response}
        drawing={blindDrawing}
        resultIndex={blindResultIndex}
        selectedIndex={selectedIndex}
        onDraw={openBlindBox}
        onClose={() => {
          if (!blindDrawing) setBlindBoxOpen(false);
        }}
      />
    </main>
  );
}

function Field({ label, icon, children }: { label: string; icon: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="input-shell">
        {icon}
        {children}
      </div>
    </label>
  );
}

function AgentStatus({ systemProfile, activeAction }: { systemProfile: SystemProfile | null; activeAction: string | null }) {
  const agents = ["PreferenceAgent", "Map/POI", "Data", "Critic"];
  const details = [
    "需求解析",
    systemProfile?.amap_enabled ? "高德地图" : "开放地图",
    systemProfile?.merchant_api_enabled ? "授权商家" : "地图字段",
    "方案评估",
  ];
  return (
    <section className="agent-card">
      <div className="agent-title">
        <Bot size={18} />
        <span>多智能体协作中</span>
      </div>
      <div className="agent-grid">
        {agents.map((agent, index) => (
          <div className="agent-mini" key={agent}>
            <strong>{agent}</strong>
            <span>{details[index]}</span>
            {index === 3 && activeAction && activeAction !== "plan" ? <Loader2 className="animate-spin" size={15} /> : <CheckCircle2 size={15} />}
          </div>
        ))}
      </div>
      <p>{systemProfile?.agent_framework ?? "LangGraph"} 编排状态图，支持真实地图检索、字段补全和动态重排。</p>
    </section>
  );
}

function RouteBoard({
  response,
  selected,
  selectedIndex,
  onSelect,
  onReplan,
  onBlindBox,
  loading,
  blindDrawing,
  activeAction,
}: {
  response: PlanResponse;
  selected: Itinerary;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onReplan: (feedback: string) => void;
  onBlindBox: () => void;
  loading: boolean;
  blindDrawing: boolean;
  activeAction: string | null;
}) {
  return (
    <div className="route-board">
      <div className="route-toolbar">
        <div className="route-tabs">
          {response.itineraries.map((itinerary, index) => {
            const Icon = ROUTE_ICONS[index] ?? Route;
            return (
              <button key={itinerary.id} className={`route-tab ${selectedIndex === index ? "route-tab-active" : ""}`} onClick={() => onSelect(index)}>
                <Icon size={18} />
                {itinerary.title}
              </button>
            );
          })}
        </div>
        <button className="blind-mini-button" type="button" onClick={onBlindBox} disabled={loading || blindDrawing}>
          {blindDrawing ? <Loader2 className="animate-spin" size={17} /> : <Shuffle size={17} />}
          抽一条
        </button>
      </div>

      <SummaryCard response={response} selected={selected} />
      {response.data_warnings.length > 0 && <DataWarnings warnings={response.data_warnings} />}

      <div className="timeline-shell">
        {selected.stops.map((stop, index) => (
          <TimelineStop key={`${stop.poi.id}-${index}`} stop={stop} index={index} partySize={response.brief.party_size} />
        ))}
      </div>

      <div className="quick-actions">
        <span>快速调整建议</span>
        <div>
          {FEEDBACKS.map(({ label, icon: Icon }) => (
            <button key={label} onClick={() => onReplan(label)} disabled={loading} type="button">
              {activeAction === label ? <Loader2 className="animate-spin" size={17} /> : <Icon size={17} />}
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ response, selected }: { response: PlanResponse; selected: Itinerary }) {
  const risk = selected.risk_tags.includes("预算内") ? "低" : "中";
  return (
    <section className="summary-card">
      <Metric label="花费" value={routeCostValue(selected)} detail={routeCostDetail(selected, response.brief.budget)} accent />
      <Metric label="总通勤" value={`${selected.total_travel_minutes} 分钟`} detail="地铁 + 步行" />
      <Metric label="风险" value={risk} detail={response.context.weather.is_rainy ? "雨天优先室内" : "天气友好"} ok />
      <Metric label="评分" value={`${Math.round(selected.score)}`} detail="综合体验分" suffix="/100" />
    </section>
  );
}

function DataWarnings({ warnings }: { warnings: string[] }) {
  return (
    <div className="data-warning-row">
      {warnings.slice(0, 3).map((warning) => (
        <span key={warning}>{warning}</span>
      ))}
    </div>
  );
}

function TimelineStop({ stop, index, partySize }: { stop: ItineraryStop; index: number; partySize: number }) {
  const imageSrc = stop.poi.image_url;
  const hasRating = stop.poi.rating !== null;
  const pricePerPerson = stop.poi.price_per_person;
  const hasPrice = pricePerPerson !== null;
  const totalPrice = pricePerPerson === null ? null : pricePerPerson * partySize;
  const introText = userFacingDescription(stop.poi.description, stop.note);
  const ratingSource = visibleRatingSourceLabel(stop.poi.rating_source);
  const photoSource = visiblePhotoSourceLabel(stop.poi.photo_source);
  const merchantSource = visibleMerchantSourceLabel(stop.poi.merchant_source);
  return (
    <article className="timeline-stop">
      <div className="timeline-number">{index + 1}</div>
      <div className="time-col">
        <strong>{stop.start_time}</strong>
        <span>({stop.stay_minutes} 分钟)</span>
      </div>
      {imageSrc ? (
        <img
          className="stop-thumb"
          src={imageSrc}
          alt=""
          onError={(event) => {
            event.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <div className="stop-thumb stop-thumb-empty">
          <MapPin size={20} />
        </div>
      )}
      <div className="stop-copy">
        <div className="stop-head">
          {stop.poi.platform_url ? (
            <a href={stop.poi.platform_url} target="_blank" rel="noreferrer">
              {stop.poi.name}
            </a>
          ) : (
            <h3>{stop.poi.name}</h3>
          )}
          <span className={`type-badge ${stop.poi.indoor ? "indoor" : "outdoor"}`}>{stop.poi.indoor ? "室内" : "户外"}</span>
        </div>
        <div className="rating-row">
          {hasRating ? (
            <span className="rating-chip">
              <Star size={13} />
              {stop.poi.rating!.toFixed(1)}
              {stop.poi.review_count > 0 && <em>({formatCount(stop.poi.review_count)}评)</em>}
            </span>
          ) : (
            <span className="source-chip muted">暂无评分</span>
          )}
          {ratingSource && <span className="source-chip">{ratingSource}</span>}
          {photoSource && <span className="source-chip muted">{photoSource}</span>}
          {merchantSource && <span className="source-chip merchant">{merchantSource}</span>}
        </div>
        <p>{introText}</p>
        {stop.poi.deal_summary && (
          <div className="deal-line">
            <Sparkles size={13} />
            <span>{stop.poi.deal_summary}</span>
          </div>
        )}
        {stop.poi.address && (
          <div className="address-line">
            <MapPin size={13} />
            <span>{stop.poi.address}</span>
          </div>
        )}
        {(stop.poi.opening_hours || stop.poi.phone || stop.poi.business_area) && (
          <div className="poi-facts">
            {stop.poi.opening_hours && (
              <span>
                <Clock3 size={13} />
                {stop.poi.opening_hours}
              </span>
            )}
            {stop.poi.phone && (
              <span>
                <Phone size={13} />
                {stop.poi.phone}
              </span>
            )}
            {stop.poi.business_area && <span>{stop.poi.business_area}</span>}
          </div>
        )}
        {stop.poi.platform_url && (
          <a className="merchant-link" href={stop.poi.platform_url} target="_blank" rel="noreferrer">
            <ExternalLink size={13} />
            打开商家页
          </a>
        )}
        <div className="transport-line">
          <Navigation size={14} />
          <span>地铁/步行约 {stop.travel_minutes_from_previous} 分钟 · {categoryLabel(stop.poi.category)}</span>
        </div>
      </div>
      <div className="price-col">
        <strong>{totalPrice === null ? "—" : `¥${totalPrice}`}</strong>
        <span>{hasPrice ? (pricePerPerson === 0 ? "免费" : `人均 ¥${pricePerPerson}`) : "人均待商家确认"}</span>
      </div>
    </article>
  );
}

function WeatherCard({ response, selected }: { response: PlanResponse; selected: Itinerary }) {
  return (
    <section className="side-card weather-card">
      <div className="weather-main">
        <CloudRain size={34} />
        <div>
          <strong>{response.context.weather.condition}</strong>
          <span>{Math.round(response.context.weather.temperature_c)}°C</span>
        </div>
        <ChevronDown size={18} />
      </div>
      <div className="weather-stats">
        <MiniStat label="通勤时间" value={`${selected.total_travel_minutes} 分钟`} />
        <MiniStat label="花费" value={routeCostValue(selected)} />
        <MiniStat label="天气来源" value={sourceLabel(response.context.weather.source)} />
      </div>
    </section>
  );
}

function QualityCard({ selected, budget, onShowAlternatives }: { selected: Itinerary; budget: number; onShowAlternatives: () => void }) {
  const checks = [
    { label: "预算匹配", value: routeBudgetCheck(selected, budget) },
    { label: "地铁方便", value: selected.total_travel_minutes <= 80 ? "全程通勤可控" : "通勤略长" },
    { label: "雨天可替换", value: selected.stops.some((stop) => !stop.poi.indoor) ? "可一键切换室内" : "已提供室内方案" },
  ];
  return (
    <section className="side-card quality-card">
      <div className="side-title">
        <ShieldCheck size={20} />
        <h3>质量检查</h3>
      </div>
      {checks.map((check) => (
        <div className="check-row" key={check.label}>
          <CheckCircle2 size={18} />
          <strong>{check.label}</strong>
          <span>{check.value}</span>
        </div>
      ))}
      <button type="button" className="outline-action" onClick={onShowAlternatives}>
        查看备选方案
      </button>
    </section>
  );
}

function MapLegend({ selected }: { selected: Itinerary }) {
  return (
    <div className="map-legend">
      {selected.stops.map((stop, index) => (
        <div key={`${stop.poi.id}-legend`}>
          <span className={`legend-index legend-index-${index + 1}`}>{index + 1}</span>
          {stop.poi.name}
        </div>
      ))}
      <div className="legend-line">
        <i />
        真实路线
      </div>
    </div>
  );
}

function RouteMap({ selected, center }: { selected: Itinerary | null; center: [number, number] }) {
  const points = selected?.stops.map((stop) => [stop.poi.location.lat, stop.poi.location.lng] as [number, number]) ?? [];
  const routeLine =
    selected?.route_geometry && selected.route_geometry.length > 1
      ? selected.route_geometry.map((point) => [point.lat, point.lng] as [number, number])
      : points;
  return (
    <MapContainer key={`${center[0]}-${center[1]}-${selected?.id ?? "empty"}`} center={center} zoom={13} scrollWheelZoom className="h-full w-full">
      <MapResizeObserver watchKey={selected?.id ?? "empty"} />
      <TileLayer attribution={TILE_ATTRIBUTION} url={TILE_URL} />
      {routeLine.length > 1 && <Polyline positions={routeLine} pathOptions={{ color: "#0878d8", weight: 4, opacity: 0.86 }} />}
      {selected?.stops.map((stop, index) => (
        <Marker key={`${stop.poi.id}-${index}`} position={[stop.poi.location.lat, stop.poi.location.lng]} icon={markerIconFor(index)}>
          <Popup>
            {stop.poi.image_url && <img className="popup-thumb" src={stop.poi.image_url} alt="" />}
            <strong>{index + 1}. {stop.poi.name}</strong>
            <br />
            {stop.start_time}-{stop.end_time}
            <br />
            {stop.poi.rating === null ? "暂无评分" : `${stop.poi.rating.toFixed(1)} 分`}
            {stop.poi.rating_source ? ` · ${sourceLabel(stop.poi.rating_source)}` : ""}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}

function MapResizeObserver({ watchKey }: { watchKey: string }) {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    const invalidate = () => map.invalidateSize({ animate: false });
    invalidate();
    const resizeObserver = new ResizeObserver(invalidate);
    resizeObserver.observe(container);
    const timer = window.setTimeout(invalidate, 180);
    return () => {
      window.clearTimeout(timer);
      resizeObserver.disconnect();
    };
  }, [map, watchKey]);

  return null;
}

function BlindBoxOverlay({
  open,
  response,
  drawing,
  resultIndex,
  selectedIndex,
  onDraw,
  onClose,
}: {
  open: boolean;
  response: PlanResponse | null;
  drawing: boolean;
  resultIndex: number | null;
  selectedIndex: number;
  onDraw: () => void;
  onClose: () => void;
}) {
  if (!open) return null;
  const routes = response?.itineraries ?? [];
  const result = resultIndex === null ? null : routes[resultIndex];
  return (
    <div className="blind-overlay" role="dialog" aria-modal="true" aria-label="路线盲盒">
      <div className="blind-panel">
        <button className="blind-close" type="button" onClick={onClose} disabled={drawing} aria-label="关闭路线盲盒">
          <X size={18} />
        </button>
        <div className="blind-title">
          <span className="blind-title-icon">
            <Gift size={24} />
          </span>
          <div>
            <strong>路线盲盒</strong>
            <span>{drawing ? "多智能体正在洗牌路线" : "把选择权交给一点点随机性"}</span>
          </div>
        </div>

        <div className={`blind-stage ${drawing ? "is-drawing" : "is-revealed"}`}>
          <span className="blind-glow" />
          {[0, 1, 2].map((slot) => {
            const route = routes[slot];
            const active = slot === selectedIndex;
            return (
              <div className={`blind-card blind-card-${slot + 1} ${active ? "blind-card-active" : ""}`} key={slot}>
                <Sparkles size={18} />
                <strong>{drawing ? "未知路线" : route?.title ?? "待生成路线"}</strong>
                <span>{drawing ? "正在随机抽取" : route ? `${routeCostValue(route)} · ${route.total_travel_minutes} 分钟` : "先生成路线"}</span>
              </div>
            );
          })}
          <span className="blind-confetti blind-confetti-1" />
          <span className="blind-confetti blind-confetti-2" />
          <span className="blind-confetti blind-confetti-3" />
          <span className="blind-confetti blind-confetti-4" />
        </div>

        {result ? (
          <div className="blind-result">
            <span>本次开出</span>
            <strong>{result.title}</strong>
            <p>{result.theme}</p>
          </div>
        ) : (
          <p className="blind-hint">{drawing ? "别眨眼，路线正在快速切换。" : "点击按钮，让系统从候选路线里抽一条。"}</p>
        )}

        <div className="blind-actions">
          <button className="primary-button" type="button" onClick={onDraw} disabled={drawing}>
            {drawing ? <Loader2 className="animate-spin" size={18} /> : <Shuffle size={18} />}
            {drawing ? "抽取中" : result ? "再抽一次" : "开始抽取"}
          </button>
          <button className="ghost-button" type="button" onClick={onClose} disabled={drawing}>
            收起
          </button>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ loading, onPlan, onBlindBox }: { loading: boolean; onPlan: () => void; onBlindBox: () => void }) {
  return (
    <div className="empty-state">
      <div className="empty-symbol">
        <Route size={34} />
      </div>
      <h2>生成一条周末路线</h2>
      <p>左侧填写需求后，系统会生成路线、地图、预算和质量检查。</p>
      <button className="primary-button empty-action" onClick={onPlan} disabled={loading}>
        {loading ? <Loader2 className="animate-spin" size={18} /> : <Sparkles size={18} />}
        生成默认路线
      </button>
      <button className="blind-empty-button" onClick={onBlindBox} disabled={loading} type="button">
        {loading ? <Loader2 className="animate-spin" size={18} /> : <Gift size={18} />}
        直接开盲盒
      </button>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  suffix,
  accent,
  ok,
}: {
  label: string;
  value: string;
  detail: string;
  suffix?: string;
  accent?: boolean;
  ok?: boolean;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={accent ? "metric-accent" : ok ? "metric-ok" : ""}>
        {value}
        {suffix && <small>{suffix}</small>}
      </strong>
      <em>{detail}</em>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function knownPriceStats(itinerary: Itinerary) {
  const total = itinerary.stops.length;
  const known = itinerary.stops.filter((stop) => stop.poi.price_per_person !== null).length;
  return { total, known };
}

function routeCostValue(itinerary: Itinerary) {
  const { total, known } = knownPriceStats(itinerary);
  if (known === 0) return "待确认";
  if (known < total) return `¥${itinerary.total_cost}+`;
  return `¥${itinerary.total_cost}`;
}

function routeCostDetail(itinerary: Itinerary, budget: number) {
  const { total, known } = knownPriceStats(itinerary);
  if (known === total) return `预算参考 ¥${budget}`;
  if (known === 0) return "地图未公开人均";
  return `已知 ${known}/${total} 个地点价格`;
}

function routeBudgetCheck(itinerary: Itinerary, budget: number) {
  const { total, known } = knownPriceStats(itinerary);
  if (known === total) return `已知花费 ¥${itinerary.total_cost}，预算参考 ¥${budget}`;
  if (known === 0) return "暂无可核验人均，建议现场或电话确认";
  return `已知花费 ¥${itinerary.total_cost}（${known}/${total} 可核验）`;
}

function categoryLabel(category: string) {
  const labels: Record<string, string> = {
    cafe: "咖啡馆",
    bookstore: "书店",
    exhibition: "展览空间",
    market: "街区",
    walk: "城市漫游",
    mall: "商场",
    dining: "餐饮",
    park: "公园",
    workshop: "手作",
    bar: "小酒馆",
  };
  return labels[category] ?? category;
}

function sourceLabel(source: string) {
  if (source.includes("dianping")) return "大众点评";
  if (source.includes("meituan")) return "美团";
  if (source.includes("amap")) return "高德地图";
  if (source.includes("openstreetmap")) return "开放地图";
  if (source.includes("seed")) return "本地数据";
  return source || "本地数据";
}

function visibleRatingSourceLabel(source: string) {
  if (!source || source.includes("amap")) return "";
  if (source.includes("dianping")) return "大众点评评分";
  if (source.includes("meituan")) return "美团评分";
  return sourceLabel(source);
}

function visiblePhotoSourceLabel(source: string) {
  if (!source || source.includes("amap") || source.includes("fallback")) return "";
  if (source.includes("meituan")) return "美团图";
  if (source.includes("dianping")) return "点评图";
  if (source.includes("wikimedia")) return "Wikimedia";
  if (source.includes("openstreetmap")) return "OSM 图";
  return source;
}

function visibleMerchantSourceLabel(source: string) {
  if (!source || source.includes("amap")) return "";
  if (source.includes("meituan")) return "美团商家";
  if (source.includes("dianping")) return "点评商家";
  return source;
}

function userFacingDescription(raw: string, fallback: string) {
  const value = (raw || "").trim();
  if (!value) return fallback;
  if (value.includes("来自高德地图 Web 服务")) return fallback;
  if (value.includes("开放 POI") || value.includes("演示估算")) return fallback;
  return value;
}

function formatCount(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return value.toLocaleString();
}

function formatError(err: unknown) {
  if (!(err instanceof Error)) return "请求失败";
  try {
    const parsed = JSON.parse(err.message);
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail.map((item: { msg?: string }) => item.msg ?? JSON.stringify(item)).join("；");
    }
  } catch {
    return err.message;
  }
  return err.message;
}

export default App;
