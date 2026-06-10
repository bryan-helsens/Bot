// Lightweight API client. All calls are same-origin relative ("/api/...") so the
// Vite dev proxy (and nginx in production) routes them to the FastAPI backend.

import type {
  Config,
  EquityPoint,
  Health,
  LogEntry,
  Portfolio,
  Position,
  RiskStatus,
  StrategyPerformance,
  SystemStatus,
  Trade,
  TradingStats,
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
  stats: () => request<TradingStats>("/portfolio/stats"),
  config: () => request<Config>("/system/config"),
  closeAll: () =>
    request<{ detail: string; ok: boolean }>("/system/close-all", { method: "POST" }),
  pause: () =>
    request<{ detail: string; ok: boolean }>("/system/pause", { method: "POST" }),
  unpause: () =>
    request<{ detail: string; ok: boolean }>("/system/unpause", { method: "POST" }),
  closePosition: (symbol: string) =>
    request<{ detail: string; ok: boolean }>(`/positions/${symbol}/close`, { method: "POST" }),
  adjustCapital: (amount: string) =>
    request<{ detail: string; ok: boolean }>("/system/capital", {
      method: "POST",
      body: JSON.stringify({ amount }),
    }),
  emergencyStop: () =>
    request<{ detail: string; ok: boolean }>("/system/emergency-stop", { method: "POST" }),
  resume: () =>
    request<{ detail: string; ok: boolean }>("/system/resume", { method: "POST" }),
  logs: (limit = 200, level?: string) =>
    request<LogEntry[]>(
      `/system/logs?limit=${limit}${level ? `&level=${level}` : ""}`,
    ),
  activity: (limit = 50) => request<LogEntry[]>(`/system/activity?limit=${limit}`),
  testOrder: (symbol: string, side: "buy" | "sell") =>
    request<{ detail: string; ok: boolean }>("/system/test-order", {
      method: "POST",
      body: JSON.stringify({ symbol, side }),
    }),
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
};
