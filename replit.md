# Antaria Casino Bot

## Overview
This is a Telegram bot for a casino game platform called Antaria Casino. It uses PostgreSQL for data storage and python-telegram-bot for the Telegram API integration.

## Project Architecture
- `main.py` - Main bot application with all handlers and game logic
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `blackjack.py` - Blackjack game implementation
- `predict_handler.py` - Prediction game handler
- `app.py` - Flask app configuration for database

## Key Dependencies
- python-telegram-bot[job-queue] - Telegram bot framework
- Flask + Flask-SQLAlchemy - Web framework and ORM
- PostgreSQL - Database (via psycopg2-binary)

## Running the Bot
The bot runs with `python main.py` and requires the `TELEGRAM_BOT_TOKEN` environment variable to be set.

## Recent Changes
- January 16, 2026: Completed import to Replit environment
  - Fixed package conflicts (removed conflicting `telegram` package)
  - Configured PostgreSQL database
  - Set up workflow for running the bot
