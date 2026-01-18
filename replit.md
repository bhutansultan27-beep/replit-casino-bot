# Antaria Casino Bot

## Overview
A Telegram casino bot built with Python and python-telegram-bot library. It provides various gambling games and features for Telegram users.

## Project Structure
- `main.py` - Main bot application with all command handlers and game logic (6000+ lines)
- `models.py` - SQLAlchemy database models for Users, Games, Transactions, and GlobalState
- `app.py` - Flask app configuration with SQLAlchemy setup
- `blackjack.py` - Blackjack game logic
- `predict_handler.py` - Prediction/betting handler

## Tech Stack
- **Language**: Python 3.11
- **Bot Framework**: python-telegram-bot 22.5
- **Database**: PostgreSQL (Neon-backed via Replit)
- **ORM**: SQLAlchemy with Flask-SQLAlchemy
- **Web Framework**: Flask (for database initialization)

## Database Models
- **User**: Stores user balances, stats, referral info, achievements
- **Game**: Records game history with JSON data
- **Transaction**: Logs all financial transactions
- **GlobalState**: Key-value store for house balance, stickers, pending PvP games

## Environment Variables
- `TELEGRAM_TOKEN` - Bot API token from BotFather
- `ADMIN_IDS` - Comma-separated Telegram user IDs for admin access
- `DATABASE_URL` - PostgreSQL connection string (auto-provided)
- `SESSION_SECRET` - Flask session secret

## Running the Bot
The bot runs as a console workflow using `python main.py`. It uses polling mode to receive Telegram updates.

## Bot Commands
### User Commands
- `/start`, `/help` - Welcome message and help
- `/balance`, `/bal` - Check balance
- `/bonus` - Claim daily bonus
- `/stats` - View user statistics
- `/leaderboard`, `/global` - Global leaderboard
- `/referral`, `/ref` - Referral system
- `/history` - Transaction history

### Gambling Commands
- `/bet`, `/wager` - Place bets
- `/dice` - Dice game
- `/darts` - Darts game
- `/basketball`, `/bball` - Basketball game
- `/soccer`, `/football` - Soccer game
- `/bowling` - Bowling game
- `/roll` - Roll dice
- `/predict` - Prediction game
- `/coinflip`, `/flip` - Coin flip
- `/roulette` - Roulette game
- `/blackjack`, `/bj` - Blackjack game
- `/tip` - Tip another user
- `/deposit` - Deposit funds
- `/withdraw` - Withdraw funds
- `/matches` - View active matches

### Admin Commands
- `/p [amount]` - Add balance to self
- `/s [seconds]` - Set bet expiration time

## Deployment
Deploy as a VM (always-on) since the bot needs to continuously poll for updates.
