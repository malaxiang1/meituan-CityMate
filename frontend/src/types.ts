export type Coordinates = {
  lat: number;
  lng: number;
};

export type PlaceSuggestion = {
  name: string;
  address: string;
  location: Coordinates;
  source: string;
};

export type UserBrief = {
  city: string;
  origin_name: string;
  origin: Coordinates;
  start_time: string;
  duration_hours: number;
  budget: number;
  party_size: number;
  mood: string;
  preferences: string[];
  hard_constraints: string[];
  transport_mode: "walk" | "transit" | "drive";
};

export type WeatherSnapshot = {
  condition: string;
  temperature_c: number;
  is_rainy: boolean;
  source: string;
};

export type ContextSnapshot = {
  city: string;
  center: Coordinates;
  weather: WeatherSnapshot;
  generated_at: string;
};

export type PoiCandidate = {
  id: string;
  name: string;
  category: string;
  location: Coordinates;
  address: string;
  price_per_person: number | null;
  rating: number | null;
  review_count: number;
  rating_source: string;
  popularity: number;
  novelty: number;
  tags: string[];
  indoor: boolean;
  opening_hours: string;
  phone: string;
  business_area: string;
  source: string;
  image_url: string;
  photo_source: string;
  platform_url: string;
  merchant_id: string;
  merchant_source: string;
  deal_summary: string;
  description: string;
};

export type ItineraryStop = {
  poi: PoiCandidate;
  start_time: string;
  end_time: string;
  stay_minutes: number;
  travel_minutes_from_previous: number;
  note: string;
};

export type CritiqueReport = {
  errors: string[];
  warnings: string[];
  repair_suggestions: string[];
};

export type Itinerary = {
  id: string;
  title: string;
  theme: string;
  score: number;
  total_cost: number;
  total_travel_minutes: number;
  risk_tags: string[];
  reasons: string[];
  stops: ItineraryStop[];
  route_geometry: Coordinates[];
  critique: CritiqueReport;
};

export type PlanResponse = {
  brief: UserBrief;
  context: ContextSnapshot;
  itineraries: Itinerary[];
  agents_trace: string[];
  data_warnings: string[];
};

export type SystemProfile = {
  name: string;
  environment: string;
  agent_framework: string;
  llm_provider: string;
  map_provider: string;
  amap_enabled: boolean;
  merchant_api_enabled: boolean;
  live_data_default: boolean;
  nodes: string[];
};

export type PlanPayload = {
  query: string;
  city: string;
  origin_name: string;
  start_time: string;
  duration_hours?: number;
  budget?: number;
  party_size?: number;
  use_live_data: boolean;
};
