# Antaria Casino Bot

A feature-rich Telegram casino bot with dice and coinflip games, smart bonus system, achievements, and social features.

## Project Overview

This is a complete Telegram gambling bot built with Python and the python-telegram-bot library. It includes:
- Five casino games using Telegram's native animated emojis (Dice, Darts, Basketball, Soccer, CoinFlip)
- Smart bonus system with playthrough requirements
- Referral program with commission tracking
- Leaderboard with pagination
- Complete user wallet and transaction management
- Match history tracking

## Recent Changes

**Simplified Emoji Game Results (2025-10-22)**
- Updated darts, basketball, and soccer games to show simplified results
- Only displays the winning amount, matching the dice game format
- Individual scores are processed in the backend but not shown to players
- Examples:
  - Before: "🎉 **@user** scored **6** vs Bot's **3** and won **$10.00**!"
  - After: "@user won $10.00"
- Cleaner, more streamlined user experience across all games

**Dynamic Admin Management (2025-10-22)**
- Added dynamic admin management system with two tiers:
  - **Permanent Admins**: Set via `ADMIN_IDS` environment variable (secure, can't be removed via commands)
  - **Dynamic Admins**: Added/removed via commands, stored in database
- New admin management commands (permanent admins only):
  - `/addadmin <user_id>` - Grant admin privileges to a user
  - `/removeadmin <user_id>` - Remove admin privileges from a dynamic admin
  - `/listadmins` - View all permanent and dynamic admins
- Only permanent admins can add/remove other admins (prevents privilege escalation)
- Admin changes are saved to database and persist across restarts
- New admins receive a notification when privileges are granted

**Admin Commands System (2025-10-22)**
- Added admin authentication system using environment variable `ADMIN_IDS`
- Admin IDs are stored as comma-separated values (e.g., `ADMIN_IDS=123456,789012`)
- Admin commands:
  - `/admin` - Check if you're an admin and view admin commands
  - `/givebal <user_id> <amount>` - Give money to a user
  - `/setbal <user_id> <amount>` - Set a user's balance
  - `/allusers` - View all registered users (up to 50)
  - `/userinfo <user_id>` - View detailed user information
  - `/backup` - Download database backup file
- Updated `/backup` command to use new admin system
- Admins are loaded on bot startup and logged

**Enhanced Roulette Betting Options (2025-10-22)**
- Simplified roulette betting with easy-to-use button interface
- **Button Bets (all without emojis):** 
  - Red (2x), Black (2x)
  - Green (14x)
  - Odd (2x), Even (2x)
  - Low 1-18 (2x), High 19-36 (2x)
- **Specific Number Bets:** Use `/roulette <amount> #<number>` for 36x payout
  - Example: `/roulette 5 #23` to bet $5 on number 23
  - Must include the # symbol before the number
  - Valid numbers: #0, #1, #2, ... #36, #00

**New Telegram Native Games (2025-10-22)**
- Added `/darts <amount|all>` - Darts game 🎯 (scores 1-6, higher wins)
- Added `/basketball <amount|all>` - Basketball game 🏀 (scores 1-5, higher wins)
- Added `/soccer <amount|all>` - Soccer game ⚽ (scores 1-5, higher wins)
- All new games use Telegram's native animated dice emojis
- Support for "all" option to wager entire balance
- Same 2x payout structure as dice game
- Draw = bet refunded (when scores match)

**Simplified Interface & Messaging (2025-10-20)**
- Removed achievements system and all related commands
- Removed RP (Respect Points) system and level tracking
- Removed "Double & Play" buttons from dice and coinflip games
- Simplified button labels: removed 🟡 and ⚪ emojis from Heads/Tails buttons
- Changed all win/loss messages to lowercase format: "@user won $40" instead of "🎉 @User Won $40"
- Added simple "Play Again" button to dice games (no emojis)
- Simplified coinflip messages to show only winner, removed extra details
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
1. **Games**: 
   - Dice 🎲 (1-6, highest wins)
   - Darts 🎯 (1-6, highest wins)
   - Basketball 🏀 (1-5, highest wins)
   - Soccer ⚽ (1-5, highest wins)
   - CoinFlip 🪙 (heads/tails, 2x payout)
2. **Bonus System**: $5 locked first-time bonus + 1% daily bonus based on wagered amount
3. **Referral System**: Unique referral links with 1% commission on referral volume
4. **Leaderboard**: Paginated display of top players by total wagered

## Configuration

### Environment Variables
- `BOT_TOKEN` - Telegram bot token from @BotFather (required)
- `ADMIN_IDS` - Comma-separated list of admin user IDs (optional)
  - Example: `123456789,987654321`
  - Get your user ID by using `/admin` command or messaging @userinfobot on Telegram

### Getting Your Bot Token
1. Message @BotFather on Telegram
2. Send `/newbot`
3. Follow the prompts to create your bot
4. Copy the token and add it to Replit Secrets

### Setting Up Admin Access
1. Find your Telegram user ID (message @userinfobot or use `/admin` to test)
2. Add your user ID to Replit Secrets as `ADMIN_IDS`
3. For multiple admins, separate IDs with commas: `123456789,987654321`
4. Restart the bot to load admin permissions

## User Commands

- `/start` or `/help` - Welcome message and overview
- `/balance` - Check balance with deposit/withdraw buttons (transactions show deposits, withdrawals, tips)
- `/bonus` - Claim daily bonus (1% of total wagered, 24h cooldown)
- `/stats` - View personal statistics
- `/history` - View your last 15 game matches with results
- `/leaderboard [page]` - View top players by wagered amount
- `/referral` - Get referral link and claim rewards
- `/housebal` - View the house balance (starts at $6973)
- `/dice <amount|all>` - Play dice game 🎲 (1-6), use "all" to wager entire balance
- `/darts <amount|all>` - Play darts game 🎯 (1-6), use "all" to wager entire balance  
- `/basketball <amount|all>` - Play basketball game 🏀 (1-5), use "all" to wager entire balance
- `/soccer <amount|all>` - Play soccer game ⚽ (1-5), use "all" to wager entire balance
- `/coinflip <amount|all> <heads/tails>` - Play coinflip game 🪙, use "all" to wager entire balance

## Admin Commands

### All Admins (Permanent & Dynamic)
These commands are available to all admins:

- `/admin` - Check admin status and view available admin commands
- `/givebal <user_id> <amount>` - Give balance to a specific user
- `/setbal <user_id> <amount>` - Set a user's balance to a specific amount
- `/allusers` - View all registered users (shows up to 50 users)
- `/userinfo <user_id>` - View detailed information about a specific user
- `/backup` - Download the database file as a backup
- `/listadmins` - View all permanent and dynamic admins

### Permanent Admins Only
These commands are only available to admins listed in the `ADMIN_IDS` environment variable:

- `/addadmin <user_id>` - Grant admin privileges to another user
- `/removeadmin <user_id>` - Remove admin privileges from a dynamic admin

Note: Permanent admins cannot be removed via commands for security.

## Game Rules

All games use Telegram's native animated dice emojis for a fun, visual experience!

### Dice 🎲
- Roll 1-6, highest number wins
- 2x payout on win
- Draw = bet refunded

### Darts 🎯
- Score 1-6, highest score wins
- 2x payout on win
- Draw = bet refunded

### Basketball 🏀
- Score 1-5, highest score wins
- 2x payout on win
- Draw = bet refunded

### Soccer ⚽
- Score 1-5, highest score wins
- 2x payout on win
- Draw = bet refunded

### CoinFlip 🪙
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
