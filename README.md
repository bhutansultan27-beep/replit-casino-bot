# 🎰 Antaria Casino Bot

A premium Telegram gambling bot with advanced features, social mechanics, and anti-abuse protections.

## 🚀 Quick Start

Your bot is **already running**! You can find it on Telegram and start using it immediately.

### How to Use

1. Open Telegram and search for your bot
2. Send `/start` to begin
3. You'll receive $5 locked bonus to get started
4. Play games to unlock your bonus and start winning!

## 🎮 Available Games

### 🎲 Dice Game
Roll the dice and bet on who gets the higher number!

**Commands:**
```
/dice 10          # Bet $10 against the bot
/dice 50 @friend  # Challenge a friend with $50
```

**Rules:**
- Both players roll 1-6
- Highest roll wins 2x the bet
- Draws refund both players (PvP only)

### 🪙 CoinFlip
Classic heads or tails - double or nothing!

**Commands:**
```
/coinflip 10 heads          # Bet $10 on heads vs bot
/coinflip 25 tails @friend  # Challenge friend to opposite side
```

**Rules:**
- Choose heads or tails
- Win = 2x your bet
- Lose = lose your bet

## 💰 Bonus System

### First-Time Bonus
- New players get **$5 locked bonus**
- Must wager $5 to unlock withdrawals
- Prevents instant withdrawal abuse

### Daily Bonus
- Get **1% of total wagered** since last withdrawal
- 24-hour cooldown between claims
- Use `/bonus` to claim
- Must play through bonus before withdrawing

## 📊 Player Commands

| Command | Description |
|---------|-------------|
| `/start` or `/help` | Welcome message and overview |
| `/bal` | Check balance with deposit/withdraw options |
| `/stats` | View your personal statistics |
| `/bonus` | Claim your daily bonus |
| `/achievements` | View unlocked badges |
| `/referral` | Get your referral link and earnings |
| `/leaderboard` | Browse top players |
| `/rp` | Check your Respect Points level |
| `/backup` | Create manual database backup |

## 🏆 Achievements

Unlock special badges by completing challenges:

| Achievement | Requirement |
|------------|-------------|
| 🎲 First Bet | Place your first bet |
| 💰 High Roller | Bet over $100 total |
| 🔥 Win Streak | Win 5 games in a row |
| 🎰 Jackpot | Reach $1000 in total profit |
| 👥 Referrer | Refer 10 friends |
| 📈 Leveled Up | Reach level 10 |

## 👥 Referral System

Earn **1% commission** on your referrals' betting volume!

1. Use `/referral` to get your unique link
2. Share with friends
3. Earn automatically as they play
4. Claim earnings anytime

## 📈 Respect Points (RP)

Your level is calculated from:
- **Total wagered**: 1 RP per $100
- **Achievements**: 50 RP each
- **Account age**: 2 RP per day

Use `/rp` to check your current level!

## 🔒 Security Features

- ✅ Playthrough requirements prevent bonus abuse
- ✅ 24-hour cooldown on bonus claims
- ✅ Balance validation on all transactions
- ✅ Automatic database backups every 5 minutes
- ✅ Transaction logging for all operations

## 🛠️ Technical Details

### Architecture
- **Language**: Python 3.11
- **Framework**: python-telegram-bot v22.5
- **Database**: JSON with auto-save
- **Async**: Full async/await for performance

### Files
- `main.py` - Bot logic and game mechanics
- `database.py` - Data persistence and management
- `casino_data.json` - User data (auto-generated)

## 📝 For Developers

### Database Structure
```json
{
  "users": {
    "user_id": {
      "balance": 0.0,
      "locked_bonus": 5.0,
      "playthrough_required": 5.0,
      "total_wagered": 0.0,
      "total_pnl": 0.0,
      "games_played": 0,
      "games_won": 0,
      "achievements": [],
      "referral_code": "abc123",
      "transactions": []
    }
  },
  "games": [],
  "pending_pvp": {}
}
```

### Auto-Save
- Saves every 5 minutes automatically
- Manual backup with `/backup`
- Backups named: `casino_data_backup_YYYYMMDD_HHMMSS.json`

## 🎊 Next Steps

### Recommended Enhancements
1. **Admin Panel**
   - User management
   - Balance adjustments
   - Withdrawal approvals

2. **More Games**
   - Slots with jackpots
   - Poker tournaments
   - Blackjack tables

3. **VIP System**
   - Tiered memberships
   - Enhanced bonuses
   - Exclusive games

4. **Analytics**
   - Player behavior tracking
   - Revenue metrics
   - Engagement stats

5. **Payment Integration**
   - Real deposits via crypto
   - Automated withdrawals
   - Multiple currencies

## ⚠️ Important Notes


## 🎮 Start Playing!

Your bot is live and ready! Open Telegram, find your bot, and send `/start` to begin your casino adventure!

Good luck! 🍀
# antariaversion1
