// Shared API types mirroring the FastAPI response schemas.

export interface Health {
  status: string;
  version: string;
  trading_mode: string;
  uptime_seconds: number;
  database: boolean;
  redis: boolean;
}

export interface SystemStatus {
  running: boolean;
  trading_mode: string;
  symbols: string[];
  strategies: number;
  connected: boolean;
  started_at: string | null;
  paused: boolean;
  last_candle_age: number | null;
  last_trade_age: number | null;
  active_streams: number;
  open_positions: number;
  candle_stale: boolean;
}

export interface CoinDetail {
  symbol: string;
  has_position: boolean;
  side: string | null;
  quantity: string;
  entry_price: string | null;
  opened_at: string | null;
  mark_price: string | null;
  value: string;
  unrealized_pnl: string;
  stop_loss: string | null;
  realized_pnl: string;
  trade_count: number;
  win_rate: number;
  total_fees: string;
  trades: Trade[];
  rsi: number | null;
  prices: number[];
  times: string[];
  price_timeframe: string | null;
}

export interface TradingStats {
  today_pnl: string;
  week_pnl: string;
  today_trades: number;
  total_trades: number;
  win_rate: number;
  total_fees: string;
  best_trade: string;
  worst_trade: string;
}

export interface Config {
  sizing_method: string;
  risk_per_trade: string;
  default_stop_loss_pct: string;
  trailing_stop_pct: string;
  take_profit_levels: string[];
  max_open_trades: number;
  max_exposure_per_coin: string;
  max_portfolio_exposure: string;
  max_daily_loss: string;
  max_drawdown: string;
  symbols: string[];
  timeframes: string[];
  min_consensus: number;
}

export interface Portfolio {
  equity: string;
  cash: string;
  unrealized_pnl: string;
  realized_pnl: string;
  exposure: string;
  exposure_pct: string;
  total_return_pct: string;
  open_positions: number;
  max_drawdown: string;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
}

export interface Position {
  id: string;
  symbol: string;
  side: string;
  quantity: string;
  entry_price: string;
  mark_price: string | null;
  unrealized_pnl: string;
  stop_loss: string | null;
  leverage: number;
  opened_at: string;
}

export interface Trade {
  id: string;
  symbol: string;
  side: string;
  strategy: string | null;
  quantity: string;
  entry_price: string;
  exit_price: string;
  net_pnl: string;
  return_pct: string;
  exit_reason: string;
  opened_at: string;
  closed_at: string;
}

export interface StrategyPerformance {
  strategy: string;
  net_profit: number;
  profit_factor: number;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_trades: number;
}

export interface RiskStatus {
  circuit_breaker_active: boolean;
  circuit_breaker_cooldown: number;
  emergency_shutdown: boolean;
  emergency_reason: string;
  daily_pnl: string;
  weekly_pnl: string;
  current_drawdown: string;
  open_trades: number;
  max_open_trades: number;
}

export interface WsMessage {
  type: string;
  payload: Record<string, unknown>;
  ts: string;
}

export interface LogEntry {
  ts: string | null;
  level: string;
  event: string;
  logger: string;
  data: Record<string, string>;
}

export interface DailyPnlPoint {
  date: string;
  pnl: number;
  trades: number;
}

export interface ScannerRow {
  symbol: string;
  price: number;
  rsi: number | null;
  ema_fast: number | null;
  ema_slow: number | null;
  trend: string | null;
  ema_gap_pct: number | null;
  signal: string;
  timeframe: string | null;
  has_position: boolean;
  muted: boolean;
}

export interface CoinAnalytics {
  name: string;
  trades: number;
  net_pnl: string;
  win_rate: number;
  wins: number;
  losses: number;
  avg_win: string;
  avg_loss: string;
  profit_factor: number;
  total_fees: string;
  avg_hold_seconds: number;
  best: string;
  worst: string;
}

export interface Analytics {
  quote_asset: string;
  total_trades: number;
  net_pnl: string;
  gross_profit: string;
  gross_loss: string;
  win_rate: number;
  profit_factor: number;
  expectancy: string;
  avg_hold_seconds: number;
  total_fees: string;
  by_coin: CoinAnalytics[];
  by_strategy: CoinAnalytics[];
  by_exit_reason: Record<string, number>;
}

export interface TaxYear {
  year: number;
  trades: number;
  realized_pnl: string;
  gross_profit: string;
  gross_loss: string;
  fees: string;
  wins: number;
  losses: number;
  capital_added: string;
}

export interface TaxReport {
  quote_asset: string;
  is_testnet: boolean;
  years: TaxYear[];
  notes: Record<string, string>;
}

export interface Report {
  days: number;
  quote_asset: string;
  trades: number;
  net_pnl: string;
  gross_profit: string;
  gross_loss: string;
  fees: string;
  fees_pct_of_gross: number | null;
  win_rate: number;
  profit_factor: number;
  expectancy: string;
  avg_hold_seconds: number;
  bot_return_pct: number;
  benchmark_pct: number | null;
  beats_benchmark: boolean | null;
  verdict: string;
}

export interface StrategyInfo {
  name: string;
  class: string;
  symbols: string[];
  timeframes: string[];
  params: Record<string, number | string | boolean>;
  default_params: Record<string, number | string | boolean>;
}

export interface AssetBalance {
  asset: string;
  free: number;
  locked: number;
  total: number;
}

export interface CapitalEntry {
  ts: string | null;
  amount: number;
  equity_after: number | null;
}

export interface Account {
  quote_asset: string;
  wallet_equity: number | null;
  bot_equity: number;
  bot_cash: number;
  assets: AssetBalance[];
  capital_history: CapitalEntry[];
}
