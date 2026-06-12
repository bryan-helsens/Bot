import { useEffect, useState } from "react";
import { api } from "./api/client";
import { AccountPage } from "./components/AccountPage";
import { ActivityFeed } from "./components/ActivityFeed";
import { Allocation } from "./components/Allocation";
import { Balances } from "./components/Balances";
import { ClosedTrades } from "./components/ClosedTrades";
import { CoinDetail } from "./components/CoinDetail";
import { ConfigPanel } from "./components/ConfigPanel";
import { Controls } from "./components/Controls";
import { DailyPnL } from "./components/DailyPnL";
import { DrawdownChart } from "./components/DrawdownChart";
import { EquityCurve } from "./components/EquityCurve";
import { Health } from "./components/Health";
import { Login } from "./components/Login";
import { LogPanel } from "./components/LogPanel";
import { ManualTrade } from "./components/ManualTrade";
import { MarketScanner } from "./components/MarketScanner";
import { OpenPositions } from "./components/OpenPositions";
import { PnLPanel } from "./components/PnLPanel";
import { ProfitReport } from "./components/ProfitReport";
import { RiskStats } from "./components/RiskStats";
import { RiskTuner } from "./components/RiskTuner";
import { StrategyPerformance } from "./components/StrategyPerformance";
import { StrategyTuner } from "./components/StrategyTuner";
import { SystemStatus } from "./components/SystemStatus";
import { TradeAnalytics } from "./components/TradeAnalytics";
import { usePolling } from "./hooks/usePolling";
import { useWebSocket } from "./hooks/useWebSocket";
import type { Portfolio, Position } from "./types";

type Page =
  | "overview"
  | "market"
  | "positions"
  | "coins"
  | "analytics"
  | "performance"
  | "account"
  | "controls"
  | "logs";

const PAGES: { id: Page; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "market", label: "Market Scanner" },
  { id: "positions", label: "Positions & Trades" },
  { id: "coins", label: "Coin detail" },
  { id: "analytics", label: "Trade Analytics" },
  { id: "performance", label: "Performance" },
  { id: "account", label: "Account" },
  { id: "controls", label: "Controls & Config" },
  { id: "logs", label: "Logs" },
];

export function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    const onRequired = () => setAuthed(false);
    window.addEventListener("qb-auth-required", onRequired);
    api
      .authStatus()
      .then(({ required }) => {
        if (!required) setAuthed(true);
        else setAuthed(Boolean(localStorage.getItem("qb_token")));
      })
      .catch(() => setAuthed(true)); // status unreachable -> don't lock the user out
    return () => window.removeEventListener("qb-auth-required", onRequired);
  }, []);

  if (authed === null) return <div className="app" />;
  if (authed === false) return <Login onSuccess={() => setAuthed(true)} />;
  return <Dashboard />;
}

function Dashboard() {
  const { lastMessage, connected } = useWebSocket();
  const [page, setPage] = useState<Page>("overview");
  const { data: portfolio, refresh: refreshPortfolio } = usePolling<Portfolio>(
    () => api.portfolio(),
    5000,
  );
  const { data: positions, refresh: refreshPositions } = usePolling<Position[]>(
    () => api.positions(),
    5000,
  );

  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type.startsWith("trade.") || lastMessage.type === "ticker.update") {
      refreshPortfolio();
      refreshPositions();
    }
  }, [lastMessage, refreshPortfolio, refreshPositions]);

  const pos = positions ?? [];

  return (
    <div className="app">
      <div className="topbar">
        <h1>🤖 QuantBot</h1>
        <nav className="nav">
          {PAGES.map((p) => (
            <button
              key={p.id}
              className={`nav-btn ${page === p.id ? "active" : ""}`}
              onClick={() => setPage(p.id)}
            >
              {p.label}
            </button>
          ))}
        </nav>
        <span className="badge">
          <span className={`dot ${connected ? "live" : "down"}`} />
          {connected ? "live" : "offline"}
        </span>
      </div>

      {page === "overview" && (
        <div className="grid">
          <div className="col-8"><PnLPanel portfolio={portfolio} /></div>
          <div className="col-4"><SystemStatus wsConnected={connected} /></div>
          <div className="col-4"><Health /></div>
          <div className="col-8"><EquityCurve /></div>
          <div className="col-12"><DrawdownChart /></div>
        </div>
      )}

      {page === "market" && (
        <div className="grid">
          <div className="col-12"><MarketScanner /></div>
        </div>
      )}

      {page === "analytics" && (
        <div className="grid">
          <div className="col-12"><TradeAnalytics /></div>
        </div>
      )}

      {page === "account" && (
        <div className="grid">
          <div className="col-12"><AccountPage /></div>
        </div>
      )}

      {page === "positions" && (
        <div className="grid">
          <div className="col-6"><Balances portfolio={portfolio} positions={pos} /></div>
          <div className="col-6"><Allocation /></div>
          <div className="col-12"><OpenPositions positions={pos} /></div>
          <div className="col-6"><ActivityFeed /></div>
          <div className="col-6"><ClosedTrades /></div>
        </div>
      )}

      {page === "coins" && (
        <div className="grid">
          <div className="col-12"><CoinDetail /></div>
          <div className="col-6"><ActivityFeed /></div>
          <div className="col-6"><Allocation /></div>
        </div>
      )}

      {page === "performance" && (
        <div className="grid">
          <div className="col-12"><ProfitReport /></div>
          <div className="col-12"><EquityCurve /></div>
          <div className="col-7"><DailyPnL /></div>
          <div className="col-5"><Health /></div>
          <div className="col-12"><DrawdownChart /></div>
          <div className="col-12"><StrategyPerformance /></div>
        </div>
      )}

      {page === "controls" && (
        <div className="grid">
          <div className="col-6"><Controls /></div>
          <div className="col-6"><ManualTrade /></div>
          <div className="col-6"><RiskStats /></div>
          <div className="col-6"><RiskTuner /></div>
          <div className="col-12"><StrategyTuner /></div>
          <div className="col-6"><ConfigPanel /></div>
        </div>
      )}

      {page === "logs" && (
        <div className="grid">
          <div className="col-7"><LogPanel /></div>
          <div className="col-5"><ActivityFeed /></div>
        </div>
      )}
    </div>
  );
}
