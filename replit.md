# Antaria Casino Telegram Bot

## Overview
A Telegram casino bot built with Python that provides gambling games including dice, darts, basketball, soccer, bowling, coinflip, roulette, blackjack, and PvP challenges.

## Current State
The project is fully configured and ready to run once the TELEGRAM_BOT_TOKEN is provided.

## Project Structure
- `main.py` - Main bot application with all game handlers and command logic
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `database.py` - Database utilities
- `blackjack.py` - Blackjack game logic
- `predict_handler.py` - Prediction handler logic

## Tech Stack
- Python 3.11
- python-telegram-bot 22.x (async)
- Flask + Flask-SQLAlchemy (for database operations within bot context)
- PostgreSQL (via DATABASE_URL)
- SQLAlchemy 2.x with modern type hints

## Configuration

### Required Environment Variables
- `TELEGRAM_BOT_TOKEN` or `TELEGRAM_TOKEN` - Telegram Bot API token (required)
- `ADMIN_IDS` - Comma-separated list of admin user IDs (optional, currently set to: 7748988189)
- `DATABASE_URL` - PostgreSQL connection string (automatically configured)

### Running the Bot
The bot runs via the "Telegram Bot" workflow which executes `python main.py`.

### Deployment
Configured for VM deployment since the bot needs to run continuously for polling.

## Database Schema
- **Users** - Player accounts with balance, stats, referral info
- **Games** - Game history records
- **Transactions** - Balance change history
- **GlobalState** - House balance, admin list, sticker configs

## Features
- Multiple casino games (dice, roulette, blackjack, etc.)
- PvP challenges between users
- Referral system with earnings
- Admin commands for user management
- Automatic challenge expiration
