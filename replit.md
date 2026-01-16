# Antaria Casino Telegram Bot

## Quick Start for AI Agents
1. **Critical Package Warning**: Do NOT install the `telegram` package. It conflicts with `python-telegram-bot`. Use `python-telegram-bot[job-queue]`.
2. **Environment**: Ensure `TELEGRAM_TOKEN` and `DATABASE_URL` (PostgreSQL) are set.
3. **Run Command**: Always use `python main.py` in a **console** workflow. Do not use webview.
4. **Database**: SQLAlchemy models are in `models.py`.

## Overview
This is a Telegram casino bot built with Python using the `python-telegram-bot` library.

## Project Structure
- `main.py`: Main bot application.
- `models.py`: SQLAlchemy database models.
- `blackjack.py`: Blackjack game logic.
- `predict_handler.py`: Prediction-based games logic.

## Recent Changes
- Migrated to PostgreSQL.
- Removed legacy `database.py` and `setup.py` to prevent environment confusion.
- Configured "Telegram Bot" console workflow.
