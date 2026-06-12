import { useState } from "react";
import { api } from "../api/client";
import { clock, cls, money, signedMoney } from "../format";
import { usePolling } from "../hooks/usePolling";
import type { Account } from "../types";

/**
 * Account overview: the exchange WALLET (truth — on testnet, faucet play-money)
 * next to the BOT's own tracked equity, per-asset balances, and the deposit/
 * withdrawal ledger. Capital changes are NOT counted as profit.
 */
export function AccountPage() {
  const { data, refresh } = usePolling<Account>(() => api.account(), 8000);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function adjust(sign: 1 | -1) {
    const raw = parseFloat(amount);
    if (!Number.isFinite(raw) || raw <= 0) {
      setMsg({ ok: false, text: "Enter a positive amount." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.adjustCapital(String(sign * raw));
      setMsg({ ok: r.ok, text: r.detail });
      setAmount("");
      await refresh();
    } catch (e) {
      setMsg({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  const wallet = data?.wallet_equity ?? null;
  const drift =
    wallet != null && data ? wallet - data.bot_equity : null;

  return (
    <>
      <div className="panel">
        <h2>Account</h2>
        <div className="grid">
          <div className="col-4 stat">
            <span className="label">Bot equity (tracked)</span>
            <span className="value">{money(data?.bot_equity)}</span>
          </div>
          <div className="col-4 stat">
            <span className="label">Bot cash (free)</span>
            <span className="value">{money(data?.bot_cash)}</span>
          </div>
          <div className="col-4 stat">
            <span className="label">Wallet equity (exchange)</span>
            <span className="value">{wallet == null ? "—" : money(wallet)}</span>
          </div>
        </div>
        <p className="hint">
          The <b>wallet</b> is the exchange's real balance — on testnet that's free faucet
          play-money, so it legitimately differs from the bot's tracked equity
          {drift != null && Math.abs(drift) > 0.01 ? (
            <>
              {" "}(currently <b>{signedMoney(drift)}</b> more in the wallet)
            </>
          ) : null}
          . This difference is normal, not a bug.
        </p>
      </div>

      <div className="panel">
        <h2>Exchange balances</h2>
        {!data || data.assets.length === 0 ? (
          <div className="empty">No non-zero balances reported.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Free</th>
                <th>Locked</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {data.assets.map((a) => (
                <tr key={a.asset}>
                  <td>{a.asset}</td>
                  <td>{a.free.toLocaleString()}</td>
                  <td className={a.locked > 0 ? "neg" : "muted"}>{a.locked.toLocaleString()}</td>
                  <td>{a.total.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Deposit / withdraw capital</h2>
        <div className="manual-trade">
          <input
            className="cap-input"
            type="number"
            placeholder="amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <button className="btn-buy" disabled={busy} onClick={() => adjust(1)}>
            Deposit
          </button>
          <button className="btn-sell" disabled={busy} onClick={() => adjust(-1)}>
            Withdraw
          </button>
        </div>
        {msg && <div className={msg.ok ? "note ok" : "note err"}>{msg.text}</div>}
        <p className="hint">
          Use this AFTER you actually add/remove funds on the exchange. It moves the bot's
          capital baseline — it is <b>NOT</b> counted as profit, so your return% stays honest.
        </p>
      </div>

      <div className="panel">
        <h2>Capital history</h2>
        {!data || data.capital_history.length === 0 ? (
          <div className="empty">No deposits or withdrawals recorded.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Type</th>
                <th>Amount</th>
                <th>Equity after</th>
              </tr>
            </thead>
            <tbody>
              {[...data.capital_history].reverse().map((c, i) => (
                <tr key={i}>
                  <td>{clock(c.ts)}</td>
                  <td className={c.amount >= 0 ? "pos" : "neg"}>
                    {c.amount >= 0 ? "Deposit" : "Withdraw"}
                  </td>
                  <td className={cls(c.amount)}>{signedMoney(c.amount)}</td>
                  <td>{c.equity_after == null ? "—" : money(c.equity_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
