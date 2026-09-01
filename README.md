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
    |-- engines/         # 30+ Analysis engines
    |-- models/          # Data models
    |-- strategies/      # Trading strategies
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

## Disclaimer

This is a Decision Support System only. It does not guarantee profits.
Trading involves risk. Always trade responsibly.

---
**Version:** 2.1 | **Status:** Live Integration Verification Pending
