# Antaria Casino Telegram Bot

## Overview
This is a Telegram casino bot built with Python using the `python-telegram-bot` library. It provides various gambling games and features for Telegram users.

## Project Structure
- `main.py` - Main bot application with all command handlers and game logic
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `database.py` - Legacy JSON database manager (not currently used, replaced by PostgreSQL)
- `blackjack.py` - Blackjack game logic and mechanics
- `predict_handler.py` - Handler for prediction-based games

## Database
The bot uses PostgreSQL for data persistence. Key tables:
- `users` - User accounts with balance, stats, achievements
- `games` - Game history records
- `transactions` - Transaction history
- `global_state` - Global configuration (house balance, dynamic admins, stickers)

## Environment Variables Required
- `TELEGRAM_BOT_TOKEN` - Your Telegram bot token from @BotFather (format: `123456789:ABCDefGHIJKLmnoPQRStuvWXYz`)
- `ADMIN_IDS` - Comma-separated list of Telegram user IDs for admin access
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)

## Rapid Setup
To get the bot running instantly, run:
```bash
python setup.py
```
This will:
1. Fix dependency conflicts automatically.
2. Sync all required packages.
3. Verify your environment variables.

## Running the Bot
The bot runs via the "Telegram Bot" workflow (`python main.py`).

## Features
- Multiple casino games: Dice, Darts, Basketball, Soccer, Bowling, Coinflip, Roulette, Blackjack
- PvP betting between users
- User balance management with deposits/withdrawals
- Referral system
- Leaderboards
- Admin commands for managing users and house balance

## Recent Changes
- January 2026: Migrated to Replit environment with PostgreSQL database
