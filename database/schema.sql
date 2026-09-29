-- BLOCKORA_TRADE v3 — SQLite schema v1 (see docs/SCHEMA.md)
-- Append-only design: market history and recommendations are never updated.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS underlying_ticks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_ts TEXT NOT NULL,
  received_ts TEXT NOT NULL,
  latency_ms REAL,
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  ltp REAL,
  change_pct REAL,
  quality_status TEXT NOT NULL DEFAULT 'UNKNOWN'
);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON underlying_ticks(snapshot_ts);

CREATE TABLE IF NOT EXISTS chain_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_ts TEXT NOT NULL,
  received_ts TEXT NOT NULL,
  latency_ms REAL,
  source TEXT NOT NULL,
  expiry TEXT NOT NULL,
  strike REAL NOT NULL,
  option_type TEXT NOT NULL CHECK (option_type IN ('CE','PE')),
  ltp REAL, bid REAL, ask REAL, iv REAL,
  volume INTEGER, oi INTEGER, change_oi INTEGER,
  quality_status TEXT NOT NULL DEFAULT 'UNKNOWN'
);
CREATE INDEX IF NOT EXISTS idx_chain_ts ON chain_snapshots(snapshot_ts);
CREATE INDEX IF NOT EXISTS idx_chain_contract ON chain_snapshots(expiry, strike, option_type);

CREATE TABLE IF NOT EXISTS candles (
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bar_ts TEXT NOT NULL,            -- bar OPEN time, UTC ISO
  bar_close_ts TEXT NOT NULL,      -- open + timeframe; ingestion refuses bars whose close is in the future
  open REAL NOT NULL, high REAL NOT NULL,
  low REAL NOT NULL, close REAL NOT NULL,
  volume INTEGER,
  source TEXT NOT NULL,
  quality_status TEXT NOT NULL DEFAULT 'OK',
  PRIMARY KEY (symbol, timeframe, bar_ts)
);

CREATE TABLE IF NOT EXISTS indicators (
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bar_ts TEXT NOT NULL,
  name TEXT NOT NULL,              -- e.g. rsi14, ema20, atr14, vwap, adx14
  value REAL,
  quality_status TEXT NOT NULL DEFAULT 'OK',
  PRIMARY KEY (symbol, timeframe, bar_ts, name)
);

CREATE TABLE IF NOT EXISTS features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_ts TEXT NOT NULL,
  expiry TEXT NOT NULL,
  strike REAL NOT NULL,
  option_type TEXT NOT NULL,
  payload TEXT NOT NULL,           -- JSON feature vector (docs/SCHEMA.md)
  quality_flags TEXT               -- JSON
);
CREATE INDEX IF NOT EXISTS idx_features_ts ON features(snapshot_ts);

CREATE TABLE IF NOT EXISTS component_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_ts TEXT NOT NULL,
  strike REAL NOT NULL,
  option_type TEXT NOT NULL,
  family TEXT NOT NULL,
  component TEXT NOT NULL,
  score REAL,                      -- 0..10
  confidence TEXT NOT NULL DEFAULT 'REAL'   -- REAL / ESTIMATED / UNAVAILABLE
);
CREATE INDEX IF NOT EXISTS idx_cscores_ts ON component_scores(snapshot_ts);

CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_ts TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('RECOMMENDATION','NO_TRADE')),
  market_bias TEXT,
  side TEXT CHECK (side IN ('CALL','PUT')),
  strike REAL, expiry TEXT,
  entry REAL, stop_loss REAL, t1 REAL, t2 REAL, t3 REAL,
  expected_hold_min INTEGER,
  model_score REAL,
  calibrated_confidence REAL,      -- NULL unless a frozen calibrator provides it
  calibrated_state TEXT DEFAULT 'UNAVAILABLE',
  risk_pct REAL, reward_risk REAL, trade_grade TEXT,
  key_reasons TEXT,                -- JSON list
  rejected_alternatives TEXT,      -- JSON list
  no_trade_reason TEXT,
  diagnostics TEXT,                -- JSON
  pipeline_version TEXT NOT NULL,
  weights_hash TEXT,
  calibrator_hash TEXT,
  outcome_id INTEGER,
  created_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recs_ts ON recommendations(decision_ts);

CREATE TABLE IF NOT EXISTS outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER NOT NULL REFERENCES recommendations(id),
  outcome TEXT NOT NULL CHECK (outcome IN ('WIN_T1','WIN_T2','WIN_T3','LOSS','TIMEOUT')),
  mfe REAL, mae REAL,
  bars_to_outcome INTEGER,
  seconds_to_outcome INTEGER,
  exit_reason TEXT,
  evaluated_ts TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'LIVE_REPLAY',   -- LIVE_REPLAY / BACKTEST
  data_quality TEXT NOT NULL DEFAULT 'OK'
);
CREATE INDEX IF NOT EXISTS idx_outcomes_rec ON outcomes(recommendation_id);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_ts TEXT NOT NULL,
  finished_ts TEXT,
  config_hash TEXT NOT NULL,
  data_start TEXT, data_end TEXT,
  costs_json TEXT,
  status TEXT NOT NULL DEFAULT 'RUNNING'
);

CREATE TABLE IF NOT EXISTS backtest_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES backtest_runs(id),
  decision_ts TEXT NOT NULL,
  side TEXT, strike REAL, expiry TEXT, option_type TEXT,
  entry REAL, stop_loss REAL, target REAL,
  outcome TEXT, pnl_points REAL, pnl_pct REAL,
  costs_json TEXT, mfe REAL, mae REAL
);

CREATE TABLE IF NOT EXISTS calibration_models (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_type TEXT NOT NULL,        -- BUCKETED / LOGISTIC / ISOTONIC / PLATT
  fit_ts TEXT NOT NULL,
  train_window TEXT NOT NULL,      -- JSON {start, end}
  bucket_table TEXT,               -- JSON
  coefficients TEXT,               -- JSON
  metrics TEXT,                    -- JSON {brier, ece, roc_auc, n, ...}
  is_active INTEGER NOT NULL DEFAULT 0,
  calibrator_hash TEXT UNIQUE
);

INSERT OR REPLACE INTO schema_version(version, applied_ts)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ','now'));
