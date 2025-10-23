# Comprehensive Casino Bot AI Prompt

Build a fully-featured Telegram casino bot with the following complete specifications:

---

## 🎯 CORE ARCHITECTURE

### Platform & Technologies
- **Platform**: Telegram Bot (python-telegram-bot library v22.5+)
- **Language**: Python 3.11+ with async/await
- **Database**: JSON file-based storage with auto-save
- **Framework**: python-telegram-bot with Application, CommandHandler, CallbackQueryHandler

### File Structure
```
main.py           - All bot logic, commands, and game handlers
casino_data.json  - Auto-generated database file (user data, games, transactions)
pyproject.toml    - Dependencies (python-telegram-bot[all]>=22.5)
```

---

## 💾 DATABASE STRUCTURE

### JSON Schema
```json
{
  "users": {
    "user_id_string": {
      "user_id": int,
      "username": "string",
      "balance": 5.00,
      "playthrough_required": 5.00,
      "last_bonus_claim": "ISO_datetime or null",
      "total_wagered": 0.0,
      "total_pnl": 0.0,
      "games_played": 0,
      "games_won": 0,
      "win_streak": 0,
      "best_win_streak": 0,
      "wagered_since_last_withdrawal": 0.0,
      "first_wager_date": "ISO_datetime or null",
      "referral_code": "unique_code or null",
      "referred_by": "referrer_code or null",
      "referral_count": 0,
      "referral_earnings": 0.0,
      "unclaimed_referral_earnings": 0.0,
      "achievements": []
    }
  },
  "games": [],
  "transactions": {
    "user_id_string": [
      {
        "type": "string",
        "amount": float,
        "description": "string",
        "timestamp": "ISO_datetime"
      }
    ]
  },
  "pending_pvp": {},
  "house_balance": 10000.00,
  "dynamic_admins": [],
  "stickers": {
    "roulette": {
      "00": "sticker_file_id",
      "0": "sticker_file_id",
      "1-36": "sticker_file_ids"
    }
  }
}
```

### Database Manager Class
- Load/save JSON file with error handling
- Auto-initialize new users with $5 bonus and $5 playthrough requirement
- Methods: `get_user()`, `update_user()`, `get_house_balance()`, `update_house_balance()`, `add_transaction()`, `record_game()`, `get_leaderboard()`
- Keep only last 500 games to prevent file bloat

---

## 🎮 GAME MECHANICS

### 1. DICE GAME 🎲

**Command**: `/dice <amount|all> [@username]`

**Rules**:
- Both players roll 1-6
- Highest roll wins 2x bet
- PvP draws refund both players
- Bot vs player draws = player loses

**Implementation**:
```python
# Bot Mode: Instant roll comparison
player_roll = await update.message.reply_dice(emoji="🎲")
await asyncio.sleep(3)
bot_roll = await update.message.reply_dice(emoji="🎲")

# Win: player gets 2x wager
# Loss: house gets wager
# PvP Draw: both refunded

# PvP Mode: Challenge system
1. Create challenge with wager, store in pending_pvp
2. Other player accepts via button
3. Challenger rolls first
4. Opponent rolls
5. Compare results and pay winner
```

**Payouts**:
- Win: 2x wager (profit = 1x wager)
- Loss: Lose wager
- Draw (PvP only): Full refund

---

### 2. DARTS GAME 🎯

**Command**: `/darts <amount|all> [@username]`

**Rules**:
- Darts score 1-6 based on hit location
- Highest score wins 2x bet
- Bullseye (6) beats all
- Same rules as dice for draws

**Implementation**:
```python
# Same flow as dice but with emoji="🎯"
# Scoring: 1-6 based on Telegram's dart game value
```

---

### 3. BASKETBALL GAME 🏀

**Command**: `/basketball <amount|all>` or `/bball <amount|all> [@username]`

**Rules**:
- Score 1-5 based on shot success
- Higher score wins 2x bet
- 5 = perfect swish

**Implementation**:
```python
# emoji="🏀"
# Score range: 1-5
# Same comparison logic as dice/darts
```

---

### 4. SOCCER/FOOTBALL GAME ⚽

**Command**: `/soccer <amount|all>` or `/football <amount|all> [@username]`

**Rules**:
- Score 1-5 based on kick quality
- Higher score wins 2x bet

**Implementation**:
```python
# emoji="⚽"
# Score range: 1-5
```

---

### 5. BOWLING GAME 🎳

**Command**: `/bowling <amount|all>`

**Rules**:
- Roll to knock down 1-6 pins
- **Strike** (6 pins) = 3x payout
- **Spare** (5 pins) = 2x payout
- **4+ pins** = 1.5x payout
- **<4 pins** = loss

**Implementation**:
```python
# emoji="🎳"
bowling_value = dice_message.dice.value  # 1-6

if bowling_value == 6:
    payout_multiplier = 3  # Strike
elif bowling_value == 5:
    payout_multiplier = 2  # Spare
elif bowling_value >= 4:
    payout_multiplier = 1.5
else:
    payout_multiplier = 0  # Loss
```

**Display Format**:
```
🎳 Strike! All 6 pins down!
💵 Bet: $10.00
💰 Won: $20.00
💳 New Balance: $50.00
```

---

### 6. COINFLIP GAME 🪙

**Command**: `/coinflip <amount|all> <heads|tails> [@username]`

**Rules**:
- Choose heads or tails
- Correct guess = 2x payout
- Wrong guess = loss
- PvP: opponent gets opposite side automatically

**Implementation**:
```python
# Telegram doesn't have coin emoji, simulate with random
result = random.choice(['heads', 'tails'])

# Display as:
# 🪙 Coin landed on: HEADS! or TAILS!

# PvP: If challenger picks heads, opponent auto-assigned tails
```

---

### 7. PREDICT GAME 🔮

**Command**: `/predict <amount|all> #<1-6>`

**Rules**:
- Predict what number you'll roll (1-6)
- Correct prediction = 5x payout
- Wrong prediction = loss

**Implementation**:
```python
# Parse prediction: #1, #2, #3, #4, #5, or #6
predicted_number = int(context.args[1][1:])  # Remove #

player_roll = await update.message.reply_dice(emoji="🎲")
await asyncio.sleep(3)

if player_roll.dice.value == predicted_number:
    payout_multiplier = 5  # WIN!
else:
    payout_multiplier = 0  # LOSS

# Display:
# 🔮 You predicted: #6
# 🎲 You rolled: 6
# 💰 CORRECT! Won $40.00
```

---

### 8. ROULETTE GAME 🎡

**Command**: `/roulette <amount|all>`

**Rules**:
- Spin European roulette (0-36, plus 00)
- Select number via buttons (0-36, 00)
- Colors: Red (1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36), Black (2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35), Green (0, 00)
- Bet types with payouts:
  - **Straight (single number)**: 35x
  - **Red/Black**: 2x
  - **Even/Odd**: 2x
  - **1-18/19-36**: 2x
  - **Dozens** (1-12, 13-24, 25-36): 3x
  - **Columns**: 3x

**Implementation Flow**:
```python
1. Show bet type buttons:
   [Straight] [Red] [Black]
   [Even] [Odd] [1-18] [19-36]
   [1st 12] [2nd 12] [3rd 12]

2. If "Straight" selected → Show number grid:
   [00] [0] [1] [2] [3]
   [4] [5] [6] [7] [8] ...
   [34] [35] [36]

3. User selects number/bet type
4. Deduct wager
5. Spin animation: Send custom sticker for result
6. Calculate win based on bet type
7. Update balance and show result

# Sticker system (optional enhancement):
# Store Telegram sticker file_ids for each number 0-36 and 00
# Send appropriate sticker for visual result
```

**Display Format**:
```
🎡 Roulette landed on: 17 (Black, Odd)

Your bet: Red
Result: ❌ Loss

💵 Lost: $10.00
💳 Balance: $40.00
```

---

## 🔘 BUTTON LOGIC SYSTEM

### Button Ownership Tracking
```python
# Track which user created which buttons
self.button_ownership: Dict[tuple, int] = {}
# Key: (chat_id, message_id), Value: user_id

# Track clicked buttons to prevent re-use
self.clicked_buttons: set = set()
# Elements: (chat_id, message_id, callback_data)
```

### Button Callback Flow
```python
async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    
    # 1. Check button ownership
    ownership_key = (query.message.chat_id, query.message.message_id)
    if ownership_key in self.button_ownership:
        owner_id = self.button_ownership[ownership_key]
        if user_id != owner_id:
            await query.answer("❌ This isn't your button!", show_alert=True)
            return
    
    # 2. Check if already clicked
    click_key = (query.message.chat_id, query.message.message_id, query.data)
    if click_key in self.clicked_buttons:
        await query.answer("❌ Button already used!", show_alert=True)
        return
    
    # 3. Mark as clicked
    self.clicked_buttons.add(click_key)
    
    # 4. Parse callback data and execute action
    data_parts = query.data.split('_')
    action = data_parts[0]
    
    if action == "dice":
        await self.handle_dice_bot_game(query, data_parts)
    elif action == "bowling":
        await self.handle_bowling_game(query, data_parts)
    # ... etc for each game type
    
    # 5. Remove buttons after use
    await query.edit_message_reply_markup(reply_markup=None)
```

### Common Button Patterns

**Play Again Buttons**:
```python
keyboard = [[InlineKeyboardButton("🎲 Roll Again", callback_data=f"dice_{wager:.2f}")]]
```

**Game Mode Selection**:
```python
keyboard = [
    [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"dice_bot_{wager:.2f}")],
    [InlineKeyboardButton("👥 Challenge Player", callback_data=f"dice_player_open_{wager:.2f}")]
]
```

**PvP Accept/Decline**:
```python
keyboard = [
    [InlineKeyboardButton("✅ Accept Challenge", callback_data=f"accept_dice_{challenge_id}")],
    [InlineKeyboardButton("❌ Decline", callback_data=f"decline_dice_{challenge_id}")]
]
```

---

## 👥 PVP CHALLENGE SYSTEM

### Challenge Lifecycle

**1. Create Challenge**:
```python
challenge_id = hashlib.md5(f"{challenger_id}{time.time()}".encode()).hexdigest()[:8]

challenge = {
    'challenge_id': challenge_id,
    'challenger': challenger_id,
    'opponent': opponent_id or None,  # None if open challenge
    'wager': wager,
    'game_type': 'dice',
    'created_at': datetime.now().isoformat(),
    'chat_id': update.effective_chat.id
}

self.pending_pvp[challenge_id] = challenge

# Deduct wager from challenger immediately
self.db.update_user(challenger_id, {'balance': user_data['balance'] - wager})
```

**2. Accept Challenge**:
```python
# Verify opponent has enough balance
# Deduct wager from opponent
# Set opponent in challenge dict
challenge['opponent'] = opponent_id
challenge['waiting_for_challenger_emoji'] = True
challenge['emoji_wait_started'] = datetime.now().isoformat()

# Prompt challenger to roll
```

**3. Challenger Rolls**:
```python
# Challenger sends emoji (dice, darts, etc)
# Store result in challenge
challenge['challenger_result'] = emoji_value
challenge['waiting_for_challenger_emoji'] = False
challenge['waiting_for_emoji'] = True  # Now opponent's turn
challenge['emoji_wait_started'] = datetime.now().isoformat()
```

**4. Opponent Rolls**:
```python
# Opponent sends emoji
challenge['opponent_result'] = emoji_value

# Compare results
if challenger_result > opponent_result:
    winner = challenger
elif opponent_result > challenger_result:
    winner = opponent
else:  # Draw
    # Refund both players
    
# Pay winner 2x wager
# Update stats
# Remove challenge from pending_pvp
```

### Timeout System
```python
# Check every 5 seconds for expired challenges
async def check_expired_challenges(self, context):
    current_time = datetime.now()
    
    for challenge_id, challenge in list(self.pending_pvp.items()):
        # Case 1: Unaccepted challenge (30 seconds)
        if challenge.get('opponent') is None:
            if time_diff > 30:
                # Refund challenger
                
        # Case 2: Waiting for challenger emoji (30 seconds)
        elif challenge.get('waiting_for_challenger_emoji'):
            if time_diff > 30:
                # Challenger forfeits to house
                # Refund opponent
                
        # Case 3: Waiting for opponent emoji (30 seconds)
        elif challenge.get('waiting_for_emoji'):
            if time_diff > 30:
                # Opponent forfeits to house
                # Refund challenger
```

---

## 💰 ECONOMY SYSTEM

### New User Setup
```python
new_user = {
    "user_id": user_id,
    "username": username,
    "balance": 5.00,  # $5 starter bonus
    "playthrough_required": 5.00,  # Must wager $5 before withdrawal
    ...
}
```

### Playthrough System
```python
# On every bet placed:
total_wagered += wager
wagered_since_last_withdrawal += wager

# Calculate remaining playthrough
remaining_playthrough = max(0, playthrough_required - wagered_since_last_withdrawal)

# User can only withdraw when remaining_playthrough == 0
```

### Daily Bonus
```python
# Calculate bonus: 1% of wagered since last withdrawal
bonus_amount = wagered_since_last_withdrawal * 0.01

# Requirements:
# - 24 hour cooldown since last claim
# - Must have wagered since last withdrawal

# On claim:
user['balance'] += bonus_amount
user['playthrough_required'] += bonus_amount  # Bonus must be wagered
user['last_bonus_claim'] = datetime.now().isoformat()
```

### Referral System
```python
# User gets unique referral code
referral_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8]

# Referral link: t.me/YourBot?start=ref_{referral_code}

# When referee makes bet:
referrer['referral_earnings'] += wager * 0.01  # 1% commission
referrer['unclaimed_referral_earnings'] += wager * 0.01

# Referrer can claim earnings anytime
# Claimed earnings go directly to balance (no playthrough)
```

### House Balance
```python
# Track casino's profit/loss
# Increases when players lose
# Decreases when players win
# Used for analytics and risk management
```

---

## 👨‍💼 ADMIN SYSTEM

### Two-Tier Admin Structure

**Environment Admins** (permanent):
```python
# Set via environment variable ADMIN_IDS
ADMIN_IDS = "123456789,987654321"
self.env_admin_ids = set(int(id.strip()) for id in ADMIN_IDS.split(","))
```

**Dynamic Admins** (database-stored):
```python
# Stored in database['dynamic_admins']
# Can be added/removed by environment admins only
```

### Admin Commands

**`/addadmin <user_id>` or `/addadmin @username`**:
- Only env admins can use
- Add user to dynamic_admins list
- Persist to database

**`/removeadmin <user_id>` or `/removeadmin @username`**:
- Only env admins can use
- Remove from dynamic_admins
- Cannot remove env admins

**`/listadmins`**:
- Shows all admins (env and dynamic)
- Indicates which are permanent vs dynamic

**`/givebal <user_id|@username> <amount>`**:
- Add money to user's balance
- No playthrough requirement added
- Logs transaction

**`/setbal <user_id|@username> <amount>`**:
- Set user's balance to exact amount
- Clears playthrough requirement
- Logs transaction

**`/userinfo <user_id|@username>`**:
- Display full user data
- Shows balance, stats, playthrough, referrals, etc

**`/allusers`**:
- List all registered users
- Shows user_id, username, balance
- Paginated if >50 users

**`/housebal`**:
- Show current house balance
- Profit/loss indicator

---

## 📊 STATS & FEATURES

### `/stats` Command
```
📊 Your Statistics

💰 Balance: $50.00
⚠️ Playthrough Required: $5.00

🎮 Games Played: 42
🏆 Games Won: 25
📈 Win Rate: 59.5%
💵 Total Wagered: $200.00
📊 Total P&L: +$15.00
🔥 Current Streak: 3 wins
⭐ Best Streak: 7 wins

👥 Referrals: 5 players
💸 Referral Earnings: $12.50
```

### `/leaderboard` or `/global` Command
```
🏆 Top Players by Total Wagered

1. @Player1 - $5,000.00
2. @Player2 - $3,500.00
3. @Player3 - $2,800.00
...
```

### `/balance` or `/bal` Command
```
💰 Your Balance

Balance: $50.00
⚠️ Playthrough Required: $5.00

[💳 Deposit] [💸 Withdraw]
```
- Deposit/Withdraw buttons (placeholder functionality)

### `/tip <@username> <amount>` Command
```python
# Transfer money between users
# Deduct from sender, add to recipient
# Must have sufficient balance
# No playthrough requirement added to recipient
```

### `/backup` Command
```python
# Create manual backup of database
filename = f"casino_data_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
# Copy casino_data.json to backup file
# Send confirmation to user
```

---

## 🎨 UI/UX BEST PRACTICES

### Message Formatting
- Use **Markdown** for all messages (`parse_mode="Markdown"`)
- Bold for important info: `**JACKPOT!**`
- Emojis for visual appeal
- Clear structure with line breaks

### Result Messages Format
```
🎲 Dice Game Result

You rolled: 5 🎲
Bot rolled: 3 🎲

💰 YOU WIN!

💵 Bet: $10.00
💰 Won: $10.00
💳 New Balance: $60.00

[🎲 Roll Again]
```

### Error Messages
- Concise and clear
- Use ❌ emoji
- Examples:
  - `❌ Insufficient balance`
  - `❌ Min bet: $0.01`
  - `❌ Invalid amount`
  - `❌ This button isn't yours!`

### Button Labels
- Use emojis: `🎲 Roll Again`, `✅ Accept`, `❌ Decline`
- Clear action names
- Keep text short

---

## ⚙️ TECHNICAL REQUIREMENTS

### Environment Variables
```bash
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321  # Optional, comma-separated
```

### Initialization
```python
async def main():
    bot = AntariaCasinoBot(token=os.getenv("BOT_TOKEN"))
    
    # Schedule repeating tasks
    bot.app.job_queue.run_repeating(
        bot.check_expired_challenges,
        interval=5,  # Every 5 seconds
        first=5
    )
    
    # Start bot
    logger.info("Starting Antaria Casino Bot...")
    await bot.app.run_polling()
```

### Error Handling
- Try/except on all user inputs
- Graceful handling of:
  - Invalid numbers
  - Missing arguments
  - Insufficient balance
  - Network errors
- Log errors to console

### Data Persistence
- Auto-save after every transaction
- Keep backups of casino_data.json
- Handle corrupted JSON gracefully
- Initialize with defaults if file missing

---

## 🎯 COMMAND REFERENCE

### Player Commands
```
/start - Welcome message and game list
/help - Same as /start
/balance, /bal - Show balance with deposit/withdraw
/bonus - Claim daily bonus
/stats - Personal statistics
/leaderboard, /global - Top players
/referral, /ref - Referral link and earnings
/tip <@user> <amount> - Send money to another player
/backup - Create database backup

/dice <amount|all> [@user] - Dice game
/darts <amount|all> [@user] - Darts game
/basketball, /bball <amount|all> [@user] - Basketball
/soccer, /football <amount|all> [@user] - Soccer
/bowling <amount|all> - Bowling game
/coinflip, /flip <amount|all> <heads|tails> [@user] - Coin flip
/predict <amount|all> #<1-6> - Predict dice roll
/roulette <amount|all> - Roulette game
```

### Admin Commands
```
/admin - Admin panel info
/givebal <user> <amount> - Add money to user
/setbal <user> <amount> - Set user balance
/userinfo <user> - User details
/allusers - List all users
/housebal - House balance
/addadmin <user> - Add admin (env admins only)
/removeadmin <user> - Remove admin (env admins only)
/listadmins - Show all admins
```

### Sticker Commands (Optional)
```
/savesticker <number> - Save roulette sticker (while replying to sticker)
/stickers - List saved sticker counts
/saveroulette - Bulk save roulette stickers
```

---

## 🔐 SECURITY CONSIDERATIONS

1. **Balance Validation**: Always verify balance before deducting
2. **Button Ownership**: Prevent users from clicking others' buttons
3. **Input Sanitization**: Validate all user inputs (amounts, usernames)
4. **Playthrough Enforcement**: Cannot withdraw with pending playthrough
5. **Admin Verification**: Check admin status before privileged operations
6. **Transaction Logging**: Record all balance changes
7. **Forfeit System**: Handle abandoned PvP games fairly

---

## 📝 ADDITIONAL NOTES

### Achievements System (Optional Enhancement)
```python
achievements = [
    {"id": "first_bet", "name": "🎲 First Bet", "description": "Place your first bet"},
    {"id": "high_roller", "name": "💰 High Roller", "description": "Bet over $100 total"},
    {"id": "win_streak_5", "name": "🔥 Win Streak", "description": "Win 5 games in a row"},
    {"id": "jackpot", "name": "🎰 Jackpot", "description": "Reach $1000 in total profit"},
    {"id": "referrer_10", "name": "👥 Referrer", "description": "Refer 10 friends"},
]

# Award achievements when conditions met
# Store in user['achievements'] list
# Display in /stats or /achievements command
```

### Auto-Save System
```python
# Scheduler saves database every 5 minutes
bot.app.job_queue.run_repeating(
    lambda context: bot.db.save_data(),
    interval=300,  # 5 minutes
    first=300
)
```

### Respect Points System (Optional)
```python
# Calculate RP from:
# - Total wagered: 1 RP per $100
# - Achievements: 50 RP each
# - Account age: 2 RP per day

# Show level/tier based on RP
# Command: /rp
```

---

## 🚀 IMPLEMENTATION CHECKLIST

- [ ] Set up python-telegram-bot Application
- [ ] Create DatabaseManager class with JSON persistence
- [ ] Implement user registration and balance system
- [ ] Add playthrough requirement logic
- [ ] Build button ownership tracking system
- [ ] Implement all 8 games with bot mode
- [ ] Add PvP challenge system with timeout handling
- [ ] Create admin command system (two-tier)
- [ ] Add daily bonus system
- [ ] Implement referral system
- [ ] Build stats and leaderboard
- [ ] Add tip command
- [ ] Create comprehensive error handling
- [ ] Test all game flows (bot vs player, PvP)
- [ ] Test edge cases (insufficient balance, expired challenges)
- [ ] Deploy and configure environment variables

---

This prompt contains the complete logic, mechanics, and implementation details for recreating the entire Antaria Casino Bot. Use it as a comprehensive reference for building or modifying the bot with AI assistance.
