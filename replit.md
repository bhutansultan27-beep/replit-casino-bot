# Antaria Casino Bot

A Telegram-based casino bot with games like blackjack, roulette, and more.

## Overview
This is a Python Telegram bot that provides casino gaming functionality including:
- Blackjack
- Roulette
- PvP games
- User balance management
- Referral system
- Achievements and leaderboards

## Tech Stack
- Python 3.12
- python-telegram-bot library
- Flask + SQLAlchemy for database management
- PostgreSQL database

## Project Structure
- `main.py` - Main bot application with all command handlers
- `blackjack.py` - Blackjack game logic
- `models.py` - SQLAlchemy database models
- `database.py` - Legacy JSON database manager (replaced by PostgreSQL)
- `predict_handler.py` - Prediction handler utilities

## Required Environment Variables
- `TELEGRAM_TOKEN` or `TELEGRAM_BOT_TOKEN` - Telegram bot API token (required)
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)
- `ADMIN_IDS` - Comma-separated list of admin Telegram user IDs (optional)
- `LTC_MASTER_ADDRESS` - Litecoin master address for deposits (optional)
- `LTC_USD_RATE` - LTC to USD rate (default: 100)
- `XMR_USD_RATE` - XMR to USD rate (default: 160)
- `DEPOSIT_FEE_PERCENT` - Deposit fee percentage (default: 2)

## Running the Bot
The bot runs via `python main.py` and connects to Telegram using the bot token.

## Database
Uses Replit's built-in PostgreSQL database with the following tables:
- users - User accounts and balances
- games - Game history
- transactions - Transaction records
- global_state - Global settings like house balance
