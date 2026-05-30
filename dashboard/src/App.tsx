import { useEffect } from "react";
import { api } from "./api/client";
import { ClosedTrades } from "./components/ClosedTrades";
import { DrawdownChart } from "./components/DrawdownChart";
import { EquityCurve } from "./components/EquityCurve";
import { OpenPositions } from "./components/OpenPositions";
import { PnLPanel } from "./components/PnLPanel";
import { RiskStats } from "./components/RiskStats";
import { StrategyPerformance } from "./components/StrategyPerformance";
import { SystemStatus } from "./components/SystemStatus";
import { usePolling } from "./hooks/usePolling";
import { useWebSocket } from "./hooks/useWebSocket";
import type { Portfolio, Position } from "./types";

export function App() {
  const { lastMessage, connected } = useWebSocket();
  const { data: portfolio, refresh: refreshPortfolio } = usePolling<Portfolio>(
    () => api.portfolio(),
    5000,
  );
  const { data: positions, refresh: refreshPositions } = usePolling<Position[]>(
    () => api.positions(),
    5000,
  );

  // On a relevant live event, refresh the most affected panels immediately.
  useEffect(() => {
    if (!lastMessage) return;
    if (
      lastMessage.type.startsWith("trade.") ||
      lastMessage.type === "ticker.update"
    ) {
      refreshPortfolio();
      refreshPositions();
    }
  }, [lastMessage, refreshPortfolio, refreshPositions]);

  return (
    <div className="app">
      <div className="topbar">
        <h1>🤖 QuantBot</h1>
        <span className="badge">
          <span className={`dot ${connected ? "live" : "down"}`} />
          {connected ? "live" : "offline"}
        </span>
      </div>

      <div className="grid">
        <div className="col-8">
          <PnLPanel portfolio={portfolio} />
        </div>
        <div className="col-4">
          <SystemStatus wsConnected={connected} />
        </div>

        <div className="col-8">
          <EquityCurve />
        </div>
        <div className="col-4">
          <RiskStats />
        </div>

        <div className="col-12">
          <DrawdownChart />
        </div>

        <div className="col-6">
          <OpenPositions positions={positions ?? []} />
        </div>
        <div className="col-6">
          <StrategyPerformance />
        </div>

        <div className="col-12">
          <ClosedTrades />
        </div>
      </div>
    </div>
  );
}
