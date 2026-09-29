# BLOCKORA_TRADE

## AI Powered NIFTY Options Decision Engine
### Version 2.1 | Platform: Android Termux

---

## CRITICAL POLICY

> This system generates RECOMMENDATIONS ONLY.
> It does NOT execute trades automatically.
> The final trading decision is ALWAYS made by the user.

---

## Objective

BLOCKORA_TRADE is an AI-powered options recommendation system designed
exclusively for NIFTY derivatives. It analyzes live market data using
30+ analytical modules to provide high-probability BUY recommendations.

## Installation (Termux)

    pkg update && pkg upgrade
    pkg install python git libffi openssl
    pip install -r requirements.txt
    cp .env.example .env
    nano .env  # Add your credentials
    python main.py

## Project Structure

    BLOCKORA_TRADE/
    |-- config/          # Configuration files
    |-- core/            # Core system modules
    |-- data/            # Data engines
    |-- database/        # SQLite database
    |-- engines/         # Active analysis modules (8 folders)
    |-- telegram/        # Telegram bot
    |-- logs/            # Log files
    |-- tests/           # Test files
    |-- main.py          # Entry point
    |-- requirements.txt # Dependencies

## Confidence Scale

| Score | Grade | Action |
|-------|-------|--------|
| 95+ | Institutional | Strong BUY candidate |
| 90-94 | Excellent | BUY recommendation |
| 80-89 | Good | Conditional |
| 70-79 | Weak | Wait |
| <70 | Reject | NO TRADE |

## Required Credentials

- Angel One API Key
- Angel One Client ID
- Angel One Password
- Angel One TOTP Secret
- Telegram Bot Token
- Telegram Chat ID

## v3 Rebuild — Design & Status

A statistically-honest v3 rebuild is in progress (spec: `brain.md`, design: `docs/`). Key principles:

- `model_score` is a RANKING metric only. It is never shown as a probability.
- `calibrated_confidence` comes only from historical outcomes (docs/CALIBRATION.md) and reports
  `UNAVAILABLE` until real data exists. Confidence values are never invented.
- Hard filters veto any score. NO_TRADE is a first-class decision and the system can always return it.
- Correlated evidence (BOS/momentum/FVG/volume…) is damped via feature groups — one event cannot
  inflate the score through many redundant witnesses (docs/SCORING.md §4).

Read `docs/ARCHITECTURE.md` first, then `docs/ROADMAP.md` for phase status and open decisions.

Run tests:

    python3 -m pytest tests/

## Disclaimer

This is a Decision Support System only. It does not guarantee profits.
No claim of probability, edge or win rate is made unless backed by recorded outcomes and
calibration metrics with stated sample sizes.
Trading involves risk. Always trade responsibly.

---
**Version:** 2.1 (legacy) + v3 Phase 1 | **Status:** v3 design approved pending; legacy runtime intact
