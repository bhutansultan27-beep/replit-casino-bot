# Antaria Casino Telegram Bot

## Overview
This is a Telegram casino bot built with Python using the python-telegram-bot library. It features various gambling games including dice, blackjack, roulette, and more.

## Project Structure
- `main.py` - Main bot application with all command handlers and game logic
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `blackjack.py` - Blackjack game logic implementation
- `predict_handler.py` - Prediction game handler for emoji dice games

## Tech Stack
- Python 3.11
- python-telegram-bot (v22.x with job-queue)
- Flask + Flask-SQLAlchemy (for database ORM)
- PostgreSQL database
- Gunicorn (for production)

## Required Environment Variables
- `TELEGRAM_BOT_TOKEN` - Your Telegram Bot API token (REQUIRED)
- `DATABASE_URL` - PostgreSQL connection string (auto-configured)
- `SESSION_SECRET` - Flask session secret
- `ADMIN_IDS` - Comma-separated list of Telegram user IDs for admin access

## Running the Bot
The bot runs via the "Telegram Bot" workflow using `python main.py`. It requires the TELEGRAM_BOT_TOKEN to be set as a secret.

## Database Models
- **User** - Stores user balance, stats, referral info
- **Game** - Records game history
- **Transaction** - Transaction logs
- **GlobalState** - Global configuration (house balance, stickers, etc.)

## Recent Changes
- 2026-01-18: Migrated to Replit environment, fixed telegram package conflict
