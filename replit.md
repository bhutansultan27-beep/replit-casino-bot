# Antaria Casino Telegram Bot

## Overview
This is a Telegram casino bot with gambling games including dice, darts, basketball, soccer, bowling, roulette, blackjack, coinflip, and prediction games. It uses PostgreSQL for persistent data storage.

## Project Structure
- `main.py` - Main bot logic with all command handlers and game logic
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `database.py` - Legacy JSON database manager (not used with PostgreSQL)
- `blackjack.py` - Blackjack game logic implementation
- `predict_handler.py` - Handler for prediction games

## Required Environment Variables
- `TELEGRAM_BOT_TOKEN` or `TELEGRAM_TOKEN` - Telegram Bot API token (required)
- `ADMIN_IDS` - Comma-separated list of admin Telegram user IDs
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)
- `SESSION_SECRET` - Flask session secret

## Database
Uses PostgreSQL with the following tables:
- `users` - User accounts and balances
- `games` - Game history
- `transactions` - Transaction history
- `global_state` - Global configuration (house balance, stickers, etc.)

## Running the Bot
The bot runs via `python main.py` and uses long polling to receive Telegram updates.

## Recent Changes
- 2026-01-14: Migrated to Replit environment with PostgreSQL database
