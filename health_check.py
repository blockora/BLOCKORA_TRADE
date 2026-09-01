"""Full System Health Check - syntax, imports, DB, config, env"""
import os, sys, py_compile, sqlite3, json
sys.path.insert(0, '.')

print("=" * 60)
print("  BLOCKORA_TRADE FULL HEALTH CHECK")
print("=" * 60)

# [1] SYNTAX CHECK - saari .py files
print("\n[1/5] SYNTAX CHECK")
bad, count = [], 0
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', 'backup', 'logs', 'cache')]
    for f in files:
        if f.endswith('.py'):
            count += 1
            try:
                py_compile.compile(os.path.join(root, f), doraise=True)
            except Exception as e:
                bad.append((os.path.join(root, f), str(e)[:70]))
print(f"  Checked {count} files")
if bad:
    for p, e in bad: print(f"  ❌ {p}: {e}")
else:
    print("  ✅ All files syntax OK")

# [2] IMPORT CHECK - saare modules
print("\n[2/5] IMPORT CHECK")
mods = ['core.config_manager', 'core.logger_manager', 'core.system_health', 'core.system_shutdown',
        'data.market_data_engine', 'data.option_chain_engine', 'data.data_freshness_guard',
        'database.db_manager', 'engines.confidence.confidence_engine',
        'engines.decision.master_decision_engine', 'engines.decision.decision_validator',
        'engines.ranking.strike_ranking_engine', 'engines.risk.risk_engine',
        'engines.learning.outcome_tracker', 'engines.liquidity.liquidity_engine',
        'engines.regime.market_regime_engine', 'telegram.telegram_bot', 'telegram.subscription_manager']
for m in mods:
    try:
        __import__(m); print(f"  ✅ {m}")
    except Exception as e:
        print(f"  ❌ {m}: {e}")

# [3] DATABASE CHECK
print("\n[3/5] DATABASE CHECK")
con = sqlite3.connect('database/blockora_trade.db')
tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for t in ['ai_decisions', 'subscribers', 'signal_tracker', 'learning_weights', 'pending_payments']:
    print(f"  {'✅' if t in tabs else '❌'} {t}")

# [4] CONFIG CHECK
print("\n[4/5] CONFIG CHECK")
an = json.load(open('config/settings.json')).get('analysis', {})
for k in ['min_confidence_threshold', 'expiry_weekday', 'cycle_interval_seconds']:
    print(f"  {'✅' if k in an else '⚠️'} analysis.{k} = {an.get(k)}")

# [5] ENV CHECK
print("\n[5/5] ENV CHECK")
env = {}
import os as _os
if not _os.path.exists('.env'):
    print("  ⚠️  .env file not found")
    print("  💡 Run: cp .env.example .env  (then fill secrets)")
    print("\n" + "=" * 60)
    print("  HEALTH CHECK: DEGRADED (.env missing)")
    print("=" * 60)
    raise SystemExit(1)
try:
    for line in open('.env'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); env[k.strip()] = v.strip()
except Exception as e:
    print(f"  ❌ .env read error: {e}")
    raise SystemExit(1)
missing = []
for k in ['ANGEL_API_KEY', 'ANGEL_CLIENT_ID', 'ANGEL_PASSWORD', 'ANGEL_TOTP_SECRET',
          'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_CHANNEL_ID', 'UPI_ID']:
    present = bool(env.get(k))
    print(f"  {'✅' if present else '❌'} {k}")
    if not present: missing.append(k)

print("\n" + "=" * 60)
if missing:
    print(f"  HEALTH CHECK: ⚠️ DEGRADED ({len(missing)} env vars missing)")
    print("=" * 60)
    raise SystemExit(1)
print("  HEALTH CHECK COMPLETE — ALL OK ✅")
print("=" * 60)
raise SystemExit(0)
