import { api } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { SystemStatus as Status } from "../types";

export function SystemStatus({ wsConnected }: { wsConnected: boolean }) {
  const { data, error } = usePolling<Status>(() => api.systemStatus(), 5000);

  return (
    <div className="panel">
      <h2>System Status</h2>
      {error && <div className="error">{error}</div>}
      {data && (
        <table>
          <tbody>
            <tr>
              <th>Engine</th>
              <td>
                <span className={`dot ${data.running ? "live" : "down"}`} />{" "}
                {data.running ? "Running" : "Stopped"}
              </td>
            </tr>
            <tr>
              <th>WebSocket</th>
              <td>
                <span className={`dot ${wsConnected ? "live" : "down"}`} />{" "}
                {wsConnected ? "Connected" : "Disconnected"}
              </td>
            </tr>
            <tr>
              <th>Mode</th>
              <td>{data.trading_mode}</td>
            </tr>
            <tr>
              <th>Symbols</th>
              <td>{data.symbols.join(", ")}</td>
            </tr>
            <tr>
              <th>Strategies</th>
              <td>{data.strategies}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
