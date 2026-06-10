import { useState } from "react";
import { api } from "../api/client";
import type { Position } from "../types";

function cls(value: string): string {
  const n = parseFloat(value);
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

export function OpenPositions({ positions }: { positions: Position[] }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function close(symbol: string) {
    setBusy(symbol);
    try {
      await api.closePosition(symbol);
    } catch {
      /* errors surface in the Activity/Logs panels */
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <h2>Open Positions ({positions.length})</h2>
      {positions.length === 0 ? (
        <div className="empty">No open positions.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Mark</th>
              <th>uPnL</th>
              <th>Stop</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.id}>
                <td>{p.symbol}</td>
                <td className={p.side === "long" ? "pos" : "neg"}>{p.side}</td>
                <td>{parseFloat(p.quantity).toFixed(4)}</td>
                <td>{parseFloat(p.entry_price).toFixed(2)}</td>
                <td>{p.mark_price ? parseFloat(p.mark_price).toFixed(2) : "—"}</td>
                <td className={cls(p.unrealized_pnl)}>
                  {parseFloat(p.unrealized_pnl).toFixed(2)}
                </td>
                <td>{p.stop_loss ? parseFloat(p.stop_loss).toFixed(2) : "—"}</td>
                <td>
                  <button
                    className="btn-sell btn-sm"
                    disabled={busy === p.symbol}
                    onClick={() => close(p.symbol)}
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
