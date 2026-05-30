import type { Position } from "../types";

function cls(value: string): string {
  const n = parseFloat(value);
  return n > 0 ? "pos" : n < 0 ? "neg" : "";
}

export function OpenPositions({ positions }: { positions: Position[] }) {
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
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
