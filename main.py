import os
import asyncio
import random
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

# External dependencies (assuming they are installed via pip install python-telegram-bot)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. Database Manager (Simulated File Storage) ---
# This class handles loading and saving the bot's state to a local JSON file.
class DatabaseManager:
    def __init__(self, file_path: str = 'casino_data.json'):
        self.file_path = file_path
        self.data: Dict[str, Any] = self.load_data()
        
    def load_data(self) -> Dict[str, Any]:
        """Loads data from the JSON file or returns a default structure."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading database file: {e}. Starting with default data.")
        
        # Default starting data structure
        return {
            "users": {},
            "games": [],
            "transactions": {},
            "pending_pvp": {},
            "house_balance": 10000.00, # Initial house seed money
        }

    def save_data(self):
        """Saves the current state back to the JSON file."""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.data, f, indent=4)
        except IOError as e:
            logger.error(f"Error saving database file: {e}")

    def get_user(self, user_id: int) -> Dict[str, Any]:
        """Retrieves user data, initializing a new user if necessary."""
        user_id_str = str(user_id)
        if user_id_str not in self.data['users']:
            # New player default: $5 starter bonus
            new_user = {
                "user_id": user_id,
                "username": f"User{user_id}",
                "balance": 5.00,
                "playthrough_required": 5.00, # Must wager initial bonus before withdrawal
                "last_bonus_claim": None,
                "total_wagered": 0.0,
                "total_pnl": 0.0,
                "games_played": 0,
                "games_won": 0,
                "win_streak": 0,
                "best_win_streak": 0,
                "wagered_since_last_withdrawal": 0.0,
                "first_wager_date": None,
                "referral_code": None,
                "referred_by": None,
                "referral_count": 0,
                "referral_earnings": 0.0,
                "unclaimed_referral_earnings": 0.0,
                "achievements": []
            }
            self.data['users'][user_id_str] = new_user
            self.save_data()
        return self.data['users'][user_id_str]

    def update_user(self, user_id: int, updates: Dict[str, Any]):
        """Updates specific fields for a user."""
        user_id_str = str(user_id)
        if user_id_str in self.data['users']:
            self.data['users'][user_id_str].update(updates)
            self.save_data()

    def get_house_balance(self) -> float:
        """Retrieves the current house balance."""
        return self.data['house_balance']

    def update_house_balance(self, change: float):
        """Adds or subtracts from the house balance."""
        self.data['house_balance'] += change
        self.save_data()
        
    def add_transaction(self, user_id: int, type: str, amount: float, description: str):
        """Records a transaction for historical purposes."""
        user_id_str = str(user_id)
        if user_id_str not in self.data['transactions']:
            self.data['transactions'][user_id_str] = []
        
        transaction = {
            "type": type,
            "amount": amount,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }
        self.data['transactions'][user_id_str].append(transaction)
        # Note: Transaction save is implicitly handled by self.save_data() called in update_user/update_house_balance

    def record_game(self, game_data: Dict[str, Any]):
        """Records a completed game to the global history."""
        game_data['timestamp'] = datetime.now().isoformat()
        self.data['games'].append(game_data)
        # We only keep the last 500 games to prevent the file from getting too large
        if len(self.data['games']) > 500:
            self.data['games'] = self.data['games'][-500:]
        self.save_data()

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """Returns top players by total wagered."""
        leaderboard_data = []
        for user_data in self.data['users'].values():
            leaderboard_data.append({
                "username": user_data.get('username', f'User{user_data["user_id"]}'),
                "total_wagered": user_data.get('total_wagered', 0.0)
            })
        
        # Sort by total_wagered descending
        leaderboard_data.sort(key=lambda x: x['total_wagered'], reverse=True)
        return leaderboard_data[:50] # Limit to top 50

# --- 2. Antaria Casino Bot Class ---
class AntariaCasinoBot:
    def __init__(self, token: str):
        self.token = token
        # Initialize the internal database manager
        self.db = DatabaseManager()
        
        # Initialize bot application
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
        
        # Dictionary to store ongoing PvP challenges
        self.pending_pvp: Dict[str, Any] = self.db.data.get('pending_pvp', {})

    def setup_handlers(self):
        """Setup all command and callback handlers"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.start_command))
        self.app.add_handler(CommandHandler("balance", self.balance_command))
        self.app.add_handler(CommandHandler("bal", self.balance_command))
        self.app.add_handler(CommandHandler("bonus", self.bonus_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("leaderboard", self.leaderboard_command))
        self.app.add_handler(CommandHandler("global", self.leaderboard_command))
        self.app.add_handler(CommandHandler("referral", self.referral_command))
        self.app.add_handler(CommandHandler("ref", self.referral_command))
        self.app.add_handler(CommandHandler("housebal", self.housebal_command))
        self.app.add_handler(CommandHandler("history", self.history_command))
        self.app.add_handler(CommandHandler("dice", self.dice_command))
        self.app.add_handler(CommandHandler("darts", self.darts_command))
        self.app.add_handler(CommandHandler("basketball", self.basketball_command))
        self.app.add_handler(CommandHandler("bball", self.basketball_command))
        self.app.add_handler(CommandHandler("soccer", self.soccer_command))
        self.app.add_handler(CommandHandler("football", self.soccer_command))
        self.app.add_handler(CommandHandler("coinflip", self.coinflip_command))
        self.app.add_handler(CommandHandler("flip", self.coinflip_command))
        self.app.add_handler(CommandHandler("tip", self.tip_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
    
    # --- COMMAND HANDLERS ---
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message and initial user setup."""
        user = update.effective_user
        user_data = self.db.get_user(user.id)
        
        # Update username if it has changed
        if user_data.get("username") != user.username:
            # Only update if the user has a public username set
            if user.username:
                self.db.update_user(user.id, {"username": user.username})
            user_data = self.db.get_user(user.id) # Reload data if updated
        
        # Check for referral link in /start arguments
        if context.args and context.args[0].startswith('ref_'):
            ref_code = context.args[0].split('_', 1)[1]
            if user_data.get('referred_by') is None:
                referrer_data = self.db.data['users'].get(self.db.data['users'].get(ref_code))
                if referrer_data and referrer_data['user_id'] != user.id:
                    self.db.update_user(user.id, {'referred_by': ref_code})
                    self.db.update_user(referrer_data['user_id'], {'referral_count': referrer_data.get('referral_count', 0) + 1})
                    await context.bot.send_message(
                        chat_id=referrer_data['user_id'],
                        text=f"🎉 **New Referral!** Your link brought in @{user.username or user.first_name}.",
                        parse_mode="Markdown"
                    )
        
        playthrough_msg = f"\n⚠️ Playthrough Required: ${user_data['playthrough_required']:.2f}" if user_data['playthrough_required'] > 0 else ""
        
        welcome_text = f"""
🎰 **Welcome to Antaria Casino** 🎰

Hey {user.first_name}! Ready to test your luck?

💰 **Your Balance**: ${user_data['balance']:.2f}{playthrough_msg}

**🎮 Games:**
/dice <amount|all> - Roll the highest number (1-6)
/flip <amount|all> [@player] - Classic coin flip

**💎 Features:**
/bal - Check balance & deposit/withdraw
/tip <amount> @user - Send money to another player
/bonus - Claim your daily bonus (1% of wagered)
/stats - View your statistics
/history - View your match history
/global - Top players by volume
/ref - Get your referral link
/housebal - View the house balance

**🎁 Bonuses:**
• New players get $5 starter bonus
• Daily bonus: 1% of total wagered
• Referral rewards: 1% of referral volume

Good luck! 🍀
"""
        await update.message.reply_text(welcome_text, parse_mode="Markdown")
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show balance with deposit/withdraw buttons"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        playthrough_remaining = user_data['playthrough_required']
        
        balance_text = f"""
💰 **Your Balance**

Balance: ${user_data['balance']:.2f}
"""
        
        if playthrough_remaining > 0:
            balance_text += f"\n📊 Playthrough Required: ${playthrough_remaining:.2f}"
            balance_text += f"\n⚠️ Wager ${playthrough_remaining:.2f} more to unlock withdrawals"
        else:
            balance_text += "\n✅ Withdrawals unlocked!"
        
        keyboard = [
            [InlineKeyboardButton("💵 Deposit (Mock)", callback_data="deposit_mock"),
             InlineKeyboardButton("💸 Withdraw (Mock)", callback_data="withdraw_mock")],
            [InlineKeyboardButton("📜 Transaction History", callback_data="transactions_history")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def bonus_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show daily bonus status"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        last_claim = user_data.get('last_bonus_claim')
        can_claim = True
        cooldown_text = ""
        
        if last_claim:
            last_claim_time = datetime.fromisoformat(last_claim)
            time_diff = datetime.now() - last_claim_time
            if time_diff < timedelta(hours=24):
                can_claim = False
                remaining = timedelta(hours=24) - time_diff
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                cooldown_text = f"\n⏰ Next bonus available in: {hours}h {minutes}m"
        
        wagered_since_withdrawal = user_data.get('wagered_since_last_withdrawal', 0)
        bonus_amount = wagered_since_withdrawal * 0.01
        
        bonus_text = f"🎁 **Daily Bonus**\n\n"
        bonus_text += f"📊 Current bonus: ${bonus_amount:.2f}\n"
        bonus_text += f"💰 Total wagered since last withdrawal: ${wagered_since_withdrawal:.2f}\n"
        
        if not can_claim:
            bonus_text += cooldown_text
            await update.message.reply_text(bonus_text, parse_mode="Markdown")
            return
        
        if bonus_amount < 0.01:
            bonus_text += f"\n⚠️ Minimum bonus to claim: $0.01\n"
            bonus_text += f"Keep playing to earn more!"
            await update.message.reply_text(bonus_text, parse_mode="Markdown")
            return
        
        bonus_text += f"\n✅ Bonus ready to claim!"
        
        keyboard = [[InlineKeyboardButton("💰 Claim Bonus", callback_data="claim_daily_bonus")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(bonus_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show player statistics"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        games_played = user_data.get('games_played', 0)
        win_rate = (user_data.get('games_won', 0) / games_played * 100) if games_played > 0 else 0
        
        first_wager = user_data.get('first_wager_date')
        if first_wager:
            first_wager_str = datetime.fromisoformat(first_wager).strftime("%Y-%m-%d")
        else:
            first_wager_str = "Never"
        
        stats_text = f"""
📊 **Your Statistics**

🎮 Games Played: {games_played}
📈 Win Rate: {win_rate:.1f}%
💰 Total Wagered: ${user_data.get('total_wagered', 0):.2f}
📊 Total P&L: ${user_data.get('total_pnl', 0):.2f}
🔥 Best Win Streak: {user_data.get('best_win_streak', 0)}
📅 First Wager: {first_wager_str}
"""
        
        await update.message.reply_text(stats_text, parse_mode="Markdown")
    
    async def leaderboard_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show leaderboard with pagination"""
        page = 0
        if context.args and context.args[0].isdigit():
            page = max(0, int(context.args[0]) - 1)
        
        await self.show_leaderboard_page(update, page)
    
    async def show_leaderboard_page(self, update: Update, page: int):
        """Display a specific leaderboard page"""
        leaderboard = self.db.get_leaderboard()
        items_per_page = 10
        total_pages = (len(leaderboard) + items_per_page - 1) // items_per_page
        
        page = max(0, min(page, total_pages - 1))
        
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_data = leaderboard[start_idx:end_idx]
        
        leaderboard_text = f"🏆 **Leaderboard** (Page {page + 1}/{total_pages})\n\n"
        
        if not leaderboard:
            leaderboard_text += "No players have wagered yet!"
        
        for idx, player in enumerate(page_data, start=start_idx + 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            leaderboard_text += f"{medal} **{player['username']}**\n"
            leaderboard_text += f"   💰 Wagered: ${player['total_wagered']:.2f}\n\n"
        
        keyboard = []
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"lb_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"lb_page_{page + 1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Removed "Go to Page" button for simplicity in single file
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                leaderboard_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                leaderboard_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    
    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral link and earnings"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not user_data.get('referral_code'):
            # Generate a simple, unique referral code
            referral_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8]
            self.db.update_user(user_id, {'referral_code': referral_code})
            user_data['referral_code'] = referral_code
        
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref_{user_data['referral_code']}"
        
        referral_text = f"""
👥 **Referral System**

Your Referral Link:
`{referral_link}`

📊 Statistics:
Referrals: {user_data.get('referral_count', 0)}
Total Earned: ${user_data.get('referral_earnings', 0):.2f}
Unclaimed: ${user_data.get('unclaimed_referral_earnings', 0):.2f}

💡 Earn 1% of your referrals' betting volume!
"""
        
        keyboard = []
        if user_data.get('unclaimed_referral_earnings', 0) >= 0.01:
            keyboard.append([InlineKeyboardButton("💰 Claim Earnings", callback_data="claim_referral")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(referral_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def housebal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show house balance"""
        house_balance = self.db.get_house_balance()
        
        housebal_text = f"""
🏦 **House Balance**

Current Balance: ${house_balance:.2f}

💡 The house balance fluctuates based on bot's winnings and losses in games against players.
"""
        
        await update.message.reply_text(housebal_text, parse_mode="Markdown")
    
    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show match history"""
        user_id = update.effective_user.id
        user_games = self.db.data.get('games', [])
        
        # Filter games involving the user (player_id, challenger, or opponent) and get the last 15
        user_games_filtered = [
            game for game in user_games 
            if game.get('player_id') == user_id or 
               game.get('challenger') == user_id or 
               game.get('opponent') == user_id
        ][-15:]
        
        if not user_games_filtered:
            await update.message.reply_text("📜 No match history yet. Play some games!")
            return
        
        history_text = "🎮 **Match History** (Last 15 Games)\n\n"
        
        for game in reversed(user_games_filtered):
            game_type = game.get('type', 'unknown')
            timestamp = game.get('timestamp', '')
            
            if timestamp:
                dt = datetime.fromisoformat(timestamp)
                time_str = dt.strftime("%m/%d %H:%M")
            else:
                time_str = "Unknown"
            
            if 'bot' in game_type:
                result = game.get('result', 'unknown')
                wager = game.get('wager', 0)
                
                if game_type == 'dice_bot':
                    player_roll = game.get('player_roll', 0)
                    bot_roll = game.get('bot_roll', 0)
                    result_emoji = "✅ Win" if result == "win" else "❌ Loss" if result == "loss" else "🤝 Draw"
                    history_text += f"{result_emoji} **Dice vs Bot** - ${wager:.2f}\n"
                    history_text += f"   You: {player_roll} | Bot: {bot_roll} | {time_str}\n\n"
                elif game_type == 'coinflip_bot':
                    choice = game.get('choice', 'unknown')
                    flip_result = game.get('result', 'unknown')
                    outcome = game.get('outcome', 'unknown')
                    result_emoji = "✅ Win" if outcome == "win" else "❌ Loss"
                    history_text += f"{result_emoji} **CoinFlip vs Bot** - ${wager:.2f}\n"
                    history_text += f"   Chose: {choice.capitalize()} | Result: {flip_result.capitalize()} | {time_str}\n\n"
            else:
                # PvP games are just generic matches for history view
                opponent_id = game.get('opponent') if game.get('challenger') == user_id else game.get('challenger')
                opponent_user = self.db.get_user(opponent_id)
                opponent_username = opponent_user.get('username', f'User{opponent_id}')
                
                history_text += f"🎲 **{game_type.replace('_', ' ').title()}**\n"
                history_text += f"   PvP Match vs @{opponent_username} | {time_str}\n\n"
        
        await update.message.reply_text(history_text, parse_mode="Markdown")
    
    async def dice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play dice game setup"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: `/dice <amount>` or `/dice all`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid wager amount. Please enter a number.")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Wager must be at least $0.01.")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"dice_bot_{wager:.2f}")],
            [InlineKeyboardButton("👥 Create PvP Challenge", callback_data=f"dice_player_open_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎲 **Dice Game**\n\nWager: ${wager:.2f}\n\nChoose your opponent:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def darts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play darts game setup"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: `/darts <amount>` or `/darts all`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid wager amount. Please enter a number.")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Wager must be at least $0.01.")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"darts_bot_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎯 **Darts Game**\n\nWager: ${wager:.2f}\n\nHit the bullseye! (1-6, higher is better)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def basketball_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play basketball game setup"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: `/basketball <amount>` or `/basketball all`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid wager amount. Please enter a number.")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Wager must be at least $0.01.")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"basketball_bot_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🏀 **Basketball Game**\n\nWager: ${wager:.2f}\n\nShoot for the hoop! (1-5, higher is better)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def soccer_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play soccer game setup"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: `/soccer <amount>` or `/soccer all`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid wager amount. Please enter a number.")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Wager must be at least $0.01.")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"soccer_bot_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚽ **Soccer Game**\n\nWager: ${wager:.2f}\n\nScore a goal! (1-5, higher is better)",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def coinflip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play coinflip game setup"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: `/flip <amount>` or `/flip all`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid wager amount. Please enter a number.")
                return
            
        if wager <= 0.01:
            await update.message.reply_text("❌ Wager must be at least $0.01.")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        # Check for PvP opponent mention (this part is complex and often relies on bot permissions)
        opponent_id = None
        if len(context.args) > 1 and context.args[1].startswith('@'):
            # In a real bot, we'd need to fetch user ID from username
            # For simplicity, we'll keep the Bot vs. Bot or open challenge structure for now.
            await update.message.reply_text("❌ Player-to-player challenges are currently only supported via callback buttons after initiating a game.")
            return

        # Default is Bot vs. Player with Heads/Tails selection
        keyboard = [
            [InlineKeyboardButton("Heads (vs Bot)", callback_data=f"flip_bot_{wager:.2f}_heads")],
            [InlineKeyboardButton("Tails (vs Bot)", callback_data=f"flip_bot_{wager:.2f}_tails")],
            [InlineKeyboardButton("Create PvP Challenge", callback_data=f"flip_player_open_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🪙 **Coin Flip**\n\nWager: ${wager:.2f}\n\nChoose your game mode:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def tip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send money to another player."""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/tip <amount> <@username>`", parse_mode="Markdown")
            return
        
        try:
            amount = round(float(context.args[0]), 2)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
            
        if amount <= 0.01:
            await update.message.reply_text("❌ Tip amount must be at least $0.01.")
            return
            
        if amount > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return

        recipient_username = context.args[1].lstrip('@')
        recipient_data = next((u for u in self.db.data['users'].values() if u.get('username') == recipient_username), None)

        if not recipient_data:
            await update.message.reply_text(f"❌ Could not find user with username @{recipient_username}.")
            return
            
        if recipient_data['user_id'] == user_id:
            await update.message.reply_text("❌ You cannot tip yourself.")
            return

        # Perform transaction
        user_data['balance'] -= amount
        recipient_data['balance'] += amount
        
        self.db.update_user(user_id, user_data)
        self.db.update_user(recipient_data['user_id'], recipient_data)
        
        self.db.add_transaction(user_id, "tip_sent", -amount, f"Tip to @{recipient_username}")
        self.db.add_transaction(recipient_data['user_id'], "tip_received", amount, f"Tip from @{update.effective_user.username or update.effective_user.first_name}")

        await update.message.reply_text(
            f"✅ Success! You tipped @{recipient_username} **${amount:.2f}**.",
            parse_mode="Markdown"
        )

    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sends the database file as a backup (Admin/Debugging only)."""
        # NOTE: In a real environment, you would need robust admin checks here.
        if update.effective_user.id not in [577583307]: # Replace with your user ID for testing
             await update.message.reply_text("❌ This command is for administrators only.")
             return
             
        if os.path.exists(self.db.file_path):
            await update.message.reply_document(
                document=open(self.db.file_path, 'rb'),
                filename=self.db.file_path,
                caption="Antaria Casino Database Backup"
            )
        else:
            await update.message.reply_text("❌ Database file not found.")

    # --- GAME LOGIC ---

    def _update_user_stats(self, user_id: int, wager: float, profit: float, result: str):
        """Helper to update common user stats and playthrough requirements."""
        user_data = self.db.get_user(user_id)
        
        user_data['balance'] += profit
        user_data['games_played'] += 1
        user_data['total_wagered'] += wager
        user_data['wagered_since_last_withdrawal'] += wager
        user_data['total_pnl'] += profit
        
        if result == "win":
            user_data['games_won'] += 1
            user_data['win_streak'] = user_data.get('win_streak', 0) + 1
            user_data['best_win_streak'] = max(user_data.get('best_win_streak', 0), user_data['win_streak'])
        elif result == "loss":
            user_data['win_streak'] = 0
            
        # Reduce playthrough requirement
        if user_data['playthrough_required'] > 0:
            user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)

        # Set first wager date
        if not user_data.get('first_wager_date'):
            user_data['first_wager_date'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        
        # Handle referral earnings (1% of wager)
        referrer_code = user_data.get('referred_by')
        if referrer_code:
            referrer_data = next((u for u in self.db.data['users'].values() if u.get('referral_code') == referrer_code), None)
            if referrer_data:
                referral_commission = wager * 0.01
                referrer_data['referral_earnings'] += referral_commission
                referrer_data['unclaimed_referral_earnings'] += referral_commission
                self.db.update_user(referrer_data['user_id'], referrer_data)


    async def dice_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play dice against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        # Check balance again (in case user spent money since button was generated)
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return

        # Send dice rolls (Telegram handles the animation)
        # Player roll
        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        await asyncio.sleep(2) # Wait for animation
        player_roll = player_dice_msg.dice.value
        
        # Bot roll
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        await asyncio.sleep(2) # Wait for animation
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(0.5) # Final pause for results

        # Determine result
        profit = 0.0
        result = "draw"
        
        if player_roll > bot_roll:
            profit = wager
            result = "win"
            result_text = f"🎉 **{username}** rolled **{player_roll}** vs Bot's **{bot_roll}** and won **${profit:.2f}**!"
            self.db.update_house_balance(-wager)
        elif player_roll < bot_roll:
            profit = -wager
            result = "loss"
            result_text = f"😭 **{username}** rolled **{player_roll}** vs Bot's **{bot_roll}** and lost **${wager:.2f}**."
            self.db.update_house_balance(wager)
        else:
            # Draw, wager is refunded (profit remains 0)
            result_text = f"🤝 **{username}** and Bot both rolled **{player_roll}**. It's a draw, bet refunded."
            
        # Update user stats and database
        self._update_user_stats(user_id, wager, profit, result)
        self.db.add_transaction(user_id, "dice_bot", profit, f"Dice vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "dice_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": result
        })
        
        keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"dice_bot_{wager:.2f}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def darts_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play darts against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return

        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎯")
        await asyncio.sleep(3)
        player_roll = player_dice_msg.dice.value
        
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎯")
        await asyncio.sleep(3)
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(0.5)

        profit = 0.0
        result = "draw"
        
        if player_roll > bot_roll:
            profit = wager
            result = "win"
            result_text = f"🎉 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and won **${profit:.2f}**!"
            self.db.update_house_balance(-wager)
        elif player_roll < bot_roll:
            profit = -wager
            result = "loss"
            result_text = f"😭 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and lost **${wager:.2f}**."
            self.db.update_house_balance(wager)
        else:
            result_text = f"🤝 **{username}** and Bot both scored **{player_roll}**. It's a draw, bet refunded."
            
        self._update_user_stats(user_id, wager, profit, result)
        self.db.add_transaction(user_id, "darts_bot", profit, f"Darts vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "darts_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": result
        })
        
        keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"darts_bot_{wager:.2f}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def basketball_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play basketball against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return

        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🏀")
        await asyncio.sleep(4)
        player_roll = player_dice_msg.dice.value
        
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🏀")
        await asyncio.sleep(4)
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(0.5)

        profit = 0.0
        result = "draw"
        
        if player_roll > bot_roll:
            profit = wager
            result = "win"
            result_text = f"🎉 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and won **${profit:.2f}**!"
            self.db.update_house_balance(-wager)
        elif player_roll < bot_roll:
            profit = -wager
            result = "loss"
            result_text = f"😭 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and lost **${wager:.2f}**."
            self.db.update_house_balance(wager)
        else:
            result_text = f"🤝 **{username}** and Bot both scored **{player_roll}**. It's a draw, bet refunded."
            
        self._update_user_stats(user_id, wager, profit, result)
        self.db.add_transaction(user_id, "basketball_bot", profit, f"Basketball vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "basketball_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": result
        })
        
        keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"basketball_bot_{wager:.2f}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def soccer_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play soccer against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return

        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="⚽")
        await asyncio.sleep(4)
        player_roll = player_dice_msg.dice.value
        
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="⚽")
        await asyncio.sleep(4)
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(0.5)

        profit = 0.0
        result = "draw"
        
        if player_roll > bot_roll:
            profit = wager
            result = "win"
            result_text = f"🎉 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and won **${profit:.2f}**!"
            self.db.update_house_balance(-wager)
        elif player_roll < bot_roll:
            profit = -wager
            result = "loss"
            result_text = f"😭 **{username}** scored **{player_roll}** vs Bot's **{bot_roll}** and lost **${wager:.2f}**."
            self.db.update_house_balance(wager)
        else:
            result_text = f"🤝 **{username}** and Bot both scored **{player_roll}**. It's a draw, bet refunded."
            
        self._update_user_stats(user_id, wager, profit, result)
        self.db.add_transaction(user_id, "soccer_bot", profit, f"Soccer vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "soccer_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": result
        })
        
        keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"soccer_bot_{wager:.2f}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def create_open_dice_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Create an open dice challenge for anyone to accept"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        
        if wager > user_data['balance']:
            await query.answer("❌ Insufficient balance to cover the wager.", show_alert=True)
            return
        
        # Deduct wager from challenger balance immediately
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})

        challenge_id = f"dice_open_{user_id}_{int(datetime.now().timestamp())}"
        self.pending_pvp[challenge_id] = {
            "type": "dice",
            "challenger": user_id,
            "opponent": None,
            "wager": wager,
            "created_at": datetime.now().isoformat()
        }
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        keyboard = [[InlineKeyboardButton("✅ Accept Challenge", callback_data=f"accept_dice_{challenge_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎲 **Open Dice Challenge!**\n\n"
            f"Challenger: @{username}\n"
            f"Wager: **${wager:.2f}**\n\n"
            f"Anyone can accept this challenge! Wager deducted from challenger's balance.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def accept_dice_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Accept a pending dice challenge and resolve it."""
        query = update.callback_query
        challenger_id = query.message.reply_to_message.from_user.id if query.message.reply_to_message else None

        challenge = self.pending_pvp.get(challenge_id)
        if not challenge:
            await query.edit_message_text("❌ This challenge has expired or was canceled.")
            return

        acceptor_id = query.from_user.id
        wager = challenge['wager']
        challenger_id = challenge['challenger']
        challenger_user = self.db.get_user(challenger_id)
        acceptor_user = self.db.get_user(acceptor_id)

        if acceptor_id == challenger_id:
            await query.answer("❌ You cannot accept your own challenge.", show_alert=True)
            return

        if wager > acceptor_user['balance']:
            await query.answer(f"❌ Insufficient balance. You need ${wager:.2f} to accept.", show_alert=True)
            return
        
        # Deduct wager from acceptor balance
        self.db.update_user(acceptor_id, {'balance': acceptor_user['balance'] - wager})
        
        # Resolve the challenge
        del self.pending_pvp[challenge_id]
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        # Inform users and perform rolls
        await query.edit_message_text(f"🎲 **Challenge Accepted!**\n@{acceptor_user['username']} accepted @{challenger_user['username']}'s challenge. Rolling dice...")
        
        chat_id = query.message.chat_id
        
        # Challenger's roll
        challenger_roll_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        await asyncio.sleep(2)
        challenger_roll = challenger_roll_msg.dice.value
        
        # Acceptor's roll
        acceptor_roll_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        await asyncio.sleep(2)
        acceptor_roll = acceptor_roll_msg.dice.value

        await asyncio.sleep(0.5)

        # Determine winner
        winner_id = None
        loser_id = None
        result_text = ""
        
        if challenger_roll > acceptor_roll:
            winner_id = challenger_id
            loser_id = acceptor_id
            result_text = f"**{challenger_user['username']}** rolled **{challenger_roll}** and beat **{acceptor_user['username']}**'s **{acceptor_roll}**!"
        elif acceptor_roll > challenger_roll:
            winner_id = acceptor_id
            loser_id = challenger_id
            result_text = f"**{acceptor_user['username']}** rolled **{acceptor_roll}** and beat **{challenger_user['username']}**'s **{challenger_roll}**!"
        else:
            # Draw: refund both wagers (challenger's was deducted earlier, acceptor's was deducted above)
            self.db.update_user(challenger_id, {'balance': challenger_user['balance'] + wager})
            self.db.update_user(acceptor_id, {'balance': acceptor_user['balance'] + wager})
            result_text = f"🤝 Both players rolled **{challenger_roll}**. It's a draw, wagers refunded."
            
            self._update_user_stats(challenger_id, wager, 0.0, "draw")
            self._update_user_stats(acceptor_id, wager, 0.0, "draw")
            
            self.db.record_game({"type": "dice_pvp", "challenger": challenger_id, "opponent": acceptor_id, "wager": wager, "result": "draw"})
            await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
            return

        # Handle Win/Loss
        winnings = wager * 2 # Challenger's wager + Acceptor's wager
        
        # Winner gets the pot (wager is already deducted, so profit is just their opponent's wager)
        winner_profit = wager 
        
        # Update winner balance (winnings = their wager (already paid) + winner_profit)
        winner_user = self.db.get_user(winner_id)
        winner_user['balance'] += winnings # Add back initial wager + profit
        self.db.update_user(winner_id, winner_user)

        self._update_user_stats(winner_id, wager, winner_profit, "win")
        self._update_user_stats(loser_id, wager, -wager, "loss")

        self.db.add_transaction(winner_id, "dice_pvp_win", winner_profit, f"Dice PvP Win vs {self.db.get_user(loser_id)['username']}")
        self.db.add_transaction(loser_id, "dice_pvp_loss", -wager, f"Dice PvP Loss vs {self.db.get_user(winner_id)['username']}")
        self.db.record_game({"type": "dice_pvp", "challenger": challenger_id, "opponent": acceptor_id, "wager": wager, "result": "win"})

        final_text = f"🎉 **PVP RESULT: ${wager * 2:.2f} Pot!**\n\n{result_text}\n\n🏆 **@{winner_user['username']}** wins **${winnings:.2f}**!"
        await context.bot.send_message(chat_id=chat_id, text=final_text, parse_mode="Markdown")


    async def coinflip_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play coinflip against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        # Send coin emoji (simulates flip animation)
        coin_msg = await context.bot.send_message(chat_id=chat_id, text="🪙 Flipping...")
        
        await asyncio.sleep(1) # Simulate flip time
        
        result = random.choice(['heads', 'tails'])
        
        # Determine result
        profit = 0.0
        outcome = "loss"
        
        if choice == result:
            profit = wager
            outcome = "win"
            result_text = f"🎉 **{username}** chose **{choice.capitalize()}** and won **${profit:.2f}**!"
            self.db.update_house_balance(-wager)
        else:
            profit = -wager
            result_text = f"😭 **{username}** chose **{choice.capitalize()}**. It landed on **{result.capitalize()}** and you lost **${wager:.2f}**."
            self.db.update_house_balance(wager)

        # Update user stats and database
        self._update_user_stats(user_id, wager, profit, outcome)
        self.db.add_transaction(user_id, "coinflip_bot", profit, f"CoinFlip vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "coinflip_bot",
            "player_id": user_id,
            "wager": wager,
            "choice": choice,
            "result": result, # The actual flip result
            "outcome": outcome # win or loss
        })
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=coin_msg.message_id,
            text=f"The coin landed on **{result.capitalize()}**!"
        )

        keyboard = []
        if outcome == "win":
             keyboard.append([InlineKeyboardButton(f"Play {choice.capitalize()} Again", callback_data=f"flip_bot_{wager:.2f}_{choice}")])
        else:
            keyboard.append([InlineKeyboardButton(f"Try Again", callback_data=f"flip_bot_{wager:.2f}_{choice}")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")

    # --- CALLBACK HANDLER ---

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles all inline button presses."""
        query = update.callback_query
        await query.answer() # Acknowledge the button press immediately
        
        data = query.data
        user_id = query.from_user.id
        
        try:
            # Game Callbacks (Dice vs Bot)
            if data.startswith("dice_bot_"):
                wager = float(data.split('_')[2])
                await self.dice_vs_bot(update, context, wager)
                
            # Game Callbacks (Darts vs Bot)
            elif data.startswith("darts_bot_"):
                wager = float(data.split('_')[2])
                await self.darts_vs_bot(update, context, wager)
                
            # Game Callbacks (Basketball vs Bot)
            elif data.startswith("basketball_bot_"):
                wager = float(data.split('_')[2])
                await self.basketball_vs_bot(update, context, wager)
                
            # Game Callbacks (Soccer vs Bot)
            elif data.startswith("soccer_bot_"):
                wager = float(data.split('_')[2])
                await self.soccer_vs_bot(update, context, wager)
                
            # Game Callbacks (Dice PvP)
            elif data.startswith("dice_player_open_"):
                wager = float(data.split('_')[3])
                await self.create_open_dice_challenge(update, context, wager)
                
            elif data.startswith("accept_dice_"):
                challenge_id = data.split('_', 2)[2]
                await self.accept_dice_challenge(update, context, challenge_id)
            
            # Game Callbacks (CoinFlip vs Bot)
            elif data.startswith("flip_bot_"):
                parts = data.split('_')
                wager = float(parts[2])
                choice = parts[3]
                await self.coinflip_vs_bot(update, context, wager, choice)

            # Leaderboard Pagination
            elif data.startswith("lb_page_"):
                page = int(data.split('_')[2])
                await self.show_leaderboard_page(update, page)
                
            # Utility Callbacks
            elif data == "claim_daily_bonus":
                user_data = self.db.get_user(user_id)
                bonus_amount = user_data.get('wagered_since_last_withdrawal', 0) * 0.01
                
                if bonus_amount >= 0.01 and user_data.get('last_bonus_claim') and \
                   (datetime.now() - datetime.fromisoformat(user_data['last_bonus_claim'])) < timedelta(hours=24):
                    await query.edit_message_text("❌ You can only claim your bonus once every 24 hours.")
                    return

                if bonus_amount < 0.01:
                     await query.edit_message_text("❌ Minimum bonus to claim is $0.01.")
                     return

                # Process claim
                user_data['balance'] += bonus_amount
                user_data['wagered_since_last_withdrawal'] = 0.0 # Reset wagered amount
                user_data['playthrough_required'] += bonus_amount # Playthrough requirement for the bonus
                user_data['last_bonus_claim'] = datetime.now().isoformat()
                self.db.update_user(user_id, user_data)
                
                self.db.add_transaction(user_id, "bonus_claim", bonus_amount, "Daily Bonus Claim")
                
                await query.edit_message_text(f"✅ **Daily Bonus Claimed!**\nYou received **${bonus_amount:.2f}**.\n\nYour new balance is ${user_data['balance']:.2f}.\n*Playthrough of ${bonus_amount:.2f} required for withdrawal.*", parse_mode="Markdown")

            elif data == "claim_referral":
                user_data = self.db.get_user(user_id)
                claim_amount = user_data.get('unclaimed_referral_earnings', 0)
                
                if claim_amount < 0.01:
                    await query.edit_message_text("❌ Minimum unclaimed earnings to claim is $0.01.")
                    return
                
                # Process claim
                user_data['balance'] += claim_amount
                user_data['unclaimed_referral_earnings'] = 0.0
                user_data['playthrough_required'] += claim_amount
                self.db.update_user(user_id, user_data)
                
                self.db.add_transaction(user_id, "referral_claim", claim_amount, "Referral Earnings Claim")
                
                await query.edit_message_text(f"✅ **Referral Earnings Claimed!**\nYou received **${claim_amount:.2f}**.\n\nYour new balance is ${user_data['balance']:.2f}.\n*Playthrough of ${claim_amount:.2f} required for withdrawal.*", parse_mode="Markdown")

            # Mock Deposit/Withdrawal buttons
            elif data == "deposit_mock":
                await query.edit_message_text("💵 **Deposit**: In a real bot, this would provide payment instructions. Since this is a mock, we'll give you $100.\n\nNew Balance: ${:.2f}".format(self.db.get_user(user_id)['balance'] + 100), parse_mode="Markdown")
                self.db.update_user(user_id, {'balance': self.db.get_user(user_id)['balance'] + 100})
            
            elif data == "withdraw_mock":
                user_data = self.db.get_user(user_id)
                if user_data['playthrough_required'] > 0:
                     await query.edit_message_text(f"❌ **Withdrawal Failed**: You must complete your playthrough requirement of ${user_data['playthrough_required']:.2f} before withdrawing.", parse_mode="Markdown")
                elif user_data['balance'] < 1.00:
                    await query.edit_message_text(f"❌ **Withdrawal Failed**: Minimum withdrawal is $1.00. Current balance: ${user_data['balance']:.2f}", parse_mode="Markdown")
                else:
                    withdraw_amount = user_data['balance'] # Withdraw all
                    self.db.update_user(user_id, {'balance': 0.0})
                    self.db.add_transaction(user_id, "withdrawal", -withdraw_amount, "Mock Withdrawal")
                    self.db.update_user(user_id, {'wagered_since_last_withdrawal': 0.0}) # Reset wagered stats
                    await query.edit_message_text(f"💸 **Withdrawal Complete!**\n\n**${withdraw_amount:.2f}** has been 'sent' (Mock transaction).\n\nNew Balance: $0.00", parse_mode="Markdown")

            elif data == "transactions_history":
                user_transactions = self.db.data['transactions'].get(str(user_id), [])[-10:] # Last 10
                
                if not user_transactions:
                    await query.edit_message_text("📜 No transaction history found.")
                    return
                
                history_text = "📜 **Last 10 Transactions**\n\n"
                for tx in reversed(user_transactions):
                    time_str = datetime.fromisoformat(tx['timestamp']).strftime("%m/%d %H:%M")
                    sign = "+" if tx['amount'] >= 0 else ""
                    history_text += f"*{time_str}* | `{sign}{tx['amount']:.2f}`: {tx['description']}\n"
                
                await query.edit_message_text(history_text, parse_mode="Markdown")

            # Handle decline of PvP (general)
            elif data.startswith("decline_"):
                challenge_id = data.split('_', 1)[1]
                if challenge_id in self.pending_pvp and self.pending_pvp[challenge_id]['challenger'] == user_id:
                     await query.edit_message_text("✅ Challenge canceled.")
                     del self.pending_pvp[challenge_id]
                     self.db.data['pending_pvp'] = self.pending_pvp
                     self.db.save_data()
                else:
                    await query.answer("❌ Only the challenger can cancel this game.", show_alert=True)
            
            else:
                await query.edit_message_text("Something went wrong or this button is for a different command!")
            
        except Exception as e:
            logger.error(f"Error in button_callback: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text="An unexpected error occurred. Please try the command again.")


    def run(self):
        """Start the bot."""
        self.app.run_polling(poll_interval=1.0)


if __name__ == '__main__':
    # --- IMPORTANT CONFIGURATION ---
    # 1. Get your token from BotFather on Telegram.
    # 2. Replace the placeholder below with your actual token string.
    
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE" 
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("!!! FATAL ERROR: Please replace 'YOUR_BOT_TOKEN_HERE' with your actual Telegram Bot Token. The bot will not run otherwise. !!!")
    else:
        logger.info("Starting Antaria Casino Bot...")
        bot = AntariaCasinoBot(token=BOT_TOKEN)
        bot.run()
