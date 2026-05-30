// Lightweight API client. All calls are same-origin relative ("/api/...") so the
// Vite dev proxy (and nginx in production) routes them to the FastAPI backend.

import type {
  EquityPoint,
  Health,
  Portfolio,
  Position,
  RiskStatus,
  StrategyPerformance,
  SystemStatus,
  Trade,
} from "../types";

const BASE = "/api";

let authToken: string | null = localStorage.getItem("qb_token");

export function setToken(token: string | null): void {
  authToken = token;
  if (token) localStorage.setItem("qb_token", token);
  else localStorage.removeItem("qb_token");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string>),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`API ${response.status}: ${text}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  systemStatus: () => request<SystemStatus>("/system/status"),
  portfolio: () => request<Portfolio>("/portfolio"),
  equityCurve: () => request<EquityPoint[]>("/portfolio/equity-curve"),
  allocation: () => request<Record<string, number>>("/portfolio/allocation"),
  positions: () => request<Position[]>("/positions"),
  trades: (limit = 100) => request<Trade[]>(`/trades?limit=${limit}`),
  strategyPerformance: () => request<StrategyPerformance[]>("/strategies/performance"),
  riskStatus: () => request<RiskStatus>("/risk/status"),
  emergencyStop: () =>
    request<{ detail: string; ok: boolean }>("/system/emergency-stop", { method: "POST" }),
  resume: () =>
    request<{ detail: string; ok: boolean }>("/system/resume", { method: "POST" }),
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
};
