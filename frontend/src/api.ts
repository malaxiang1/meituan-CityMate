import type { Itinerary, PlaceSuggestion, PlanPayload, PlanResponse, SystemProfile, UserBrief } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

async function request<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: payload ? "POST" : "GET",
    headers: payload ? { "Content-Type": "application/json" } : undefined,
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function createPlan(payload: PlanPayload): Promise<PlanResponse> {
  return request<PlanResponse>("/api/plan", payload);
}

export function replan(feedback: string, currentItinerary: Itinerary, brief: UserBrief, useLiveData: boolean): Promise<PlanResponse> {
  return request<PlanResponse>("/api/replan", {
    feedback,
    current_itinerary: currentItinerary,
    brief,
    use_live_data: useLiveData,
  });
}

export function getSystemProfile(): Promise<SystemProfile> {
  return request<SystemProfile>("/api/system");
}

export function searchPlaces(city: string, query: string): Promise<PlaceSuggestion[]> {
  const params = new URLSearchParams({ city, q: query, limit: "8" });
  return request<PlaceSuggestion[]>(`/api/places/search?${params.toString()}`);
}
