# Antaria Casino Telegram Bot

## Overview
A Telegram casino/gambling bot built with Python, featuring various games and user management.

## Tech Stack
- **Language**: Python 3.11
- **Framework**: Flask with SQLAlchemy ORM
- **Database**: PostgreSQL (with SQLite fallback)
- **Bot Library**: python-telegram-bot
- **Package Manager**: uv

## Project Structure
- `main.py` - Main bot application with all game logic and handlers
- `models.py` - SQLAlchemy database models (User, Game, Transaction, GlobalState)
- `blackjack.py` - Blackjack game implementation
- `predict_handler.py` - Prediction game handler
- `pyproject.toml` - Python dependencies

## Environment Variables
- `TELEGRAM_BOT_TOKEN` or `TELEGRAM_TOKEN` - Required for bot to function
- `DATABASE_URL` - PostgreSQL connection string (auto-configured by Replit)

## Running the Bot
The bot runs in polling mode, continuously listening for Telegram messages.

## Database Models
- **User**: Player profiles with balance, stats, achievements
- **Game**: Game session data
- **Transaction**: Deposit/withdrawal history
- **GlobalState**: Global bot state (house balance, stickers, etc.)
