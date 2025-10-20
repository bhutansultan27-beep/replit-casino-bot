# Antaria Casino Bot

A feature-rich Telegram casino bot with dice and coinflip games, smart bonus system, achievements, and social features.

## Project Overview

This is a complete Telegram gambling bot built with Python and the python-telegram-bot library. It includes:
- Two casino games (Dice and CoinFlip) with PvP and bot modes
- Smart bonus system with playthrough requirements
- Achievement and leveling system
- Referral program with commission tracking
- Leaderboard with pagination
- Complete user wallet and transaction management

## Recent Changes

**Simplified Interface & Messaging (2025-10-20)**
- Removed achievements system and all related commands
- Removed RP (Respect Points) system and level tracking
- Removed "Double & Play" buttons from dice and coinflip games
- Simplified button labels: removed 🟡 and ⚪ emojis from Heads/Tails buttons
- Changed all win/loss messages to lowercase format: "@user won $40" instead of "🎉 @User Won $40"
- Updated help text to remove references to removed features

**Enhanced UI & Match History (2025-10-20)**
- Added `/history` command to view last 15 games with detailed results
- Transaction history now filters to show only deposits, withdrawals, and tips
- Added green (🟢) and red (🔴) color indicators for incoming vs outgoing transactions
- Game results now display player usernames instead of generic "You Won" messages
- PvP matches show actual player names in results

**All-In Betting & House Balance (2025-10-20)**
- Added "all" option to `/dice` and `/flip` commands to wager entire balance
- Usage: `/dice all` or `/flip all` to go all-in
- Added `/housebal` command to view house balance
- Initialized house balance at $6973
- House balance now fluctuates based on bot's winnings/losses in games
- Updated dice and coinflip game logic to track house performance
- Not linked to any crypto wallet - purely for display

**Initial Implementation (2025-10-20)**
- Created database manager with JSON storage and auto-save functionality
- Implemented core bot structure with all game mechanics
- Added dice and coinflip games with both PvP and bot modes
- Built bonus system with first-time $5 bonus and daily 1% bonus
- Created achievement system with 6 unlockable badges
- Implemented referral system with unique links and commission tracking
- Added paginated leaderboard and complete stats tracking
- Set up Respect Points (RP) level system

## Project Architecture

### Core Files
- `main.py` - Main bot application with all commands and game logic
- `database.py` - Database manager handling JSON storage, auto-save, and backups
- `casino_data.json` - Auto-generated JSON database (gitignored)

### Key Features
1. **Games**: Dice (roll 1-6, highest wins) and CoinFlip (heads/tails, 2x payout)
2. **Bonus System**: $5 locked first-time bonus + 1% daily bonus based on wagered amount
3. **Referral System**: Unique referral links with 1% commission on referral volume
4. **Leaderboard**: Paginated display of top players by total wagered

## Configuration

### Environment Variables
- `BOT_TOKEN` - Telegram bot token from @BotFather (required)

### Getting Your Bot Token
1. Message @BotFather on Telegram
2. Send `/newbot`
3. Follow the prompts to create your bot
4. Copy the token and add it to Replit Secrets

## User Commands

- `/start` or `/help` - Welcome message and overview
- `/balance` - Check balance with deposit/withdraw buttons (transactions show deposits, withdrawals, tips)
- `/bonus` - Claim daily bonus (1% of total wagered, 24h cooldown)
- `/stats` - View personal statistics
- `/history` - View your last 15 game matches with results
- `/leaderboard [page]` - View top players by wagered amount
- `/referral` - Get referral link and claim rewards
- `/housebal` - View the house balance (starts at $6973)
- `/dice <amount|all> [@player]` - Play dice game (PvP or vs bot), use "all" to wager entire balance
- `/coinflip <amount|all> <heads/tails> [@player]` - Play coinflip (PvP or vs bot), use "all" to wager entire balance
- `/backup` - Create manual database backup

## Game Rules

### Dice
- Roll 1-6, highest number wins
- 2x payout on win
- Draw = both players refunded (PvP only)

### CoinFlip
- Choose heads or tails
- 2x payout on win
- No draw possible

## Database Structure

The bot uses JSON for data persistence with:
- Auto-save every 5 minutes
- Manual backup command
- Transaction logging
- User balance and stats tracking
- Game history

## Security Features

- Playthrough requirements prevent bonus abuse
- 24-hour cooldown on bonus claims
- Balance validation on all transactions
- Anti-spam withdrawal protection
- Automatic backups

## Development Notes

- Built with python-telegram-bot v22.5
- Async/await patterns for performance
- Comprehensive error handling
- Inline keyboards for better UX
- No confirmation prompts for instant gameplay

## Future Enhancements

- Admin panel for user management
- Tournament system
- VIP tiers
- Additional games (slots, poker, blackjack)
- Analytics dashboard
- Blockchain integration for real money
