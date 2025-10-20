import os
import asyncio
import random
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from database import DatabaseManager


ACHIEVEMENT_INFO = {
    "first_bet": {"name": "🎲 First Bet", "desc": "Place your first bet"},
    "high_roller": {"name": "💰 High Roller", "desc": "Bet over $100"},
    "win_streak": {"name": "🔥 Win Streak", "desc": "Win 5 games in a row"},
    "jackpot": {"name": "🎰 Jackpot", "desc": "Reach $1000 in total profit"},
    "referrer": {"name": "👥 Referrer", "desc": "Refer 10 friends"},
    "leveled_up": {"name": "📈 Leveled Up", "desc": "Reach level 10"}
}


class AntariaCasinoBot:
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager()
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
    
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
        self.app.add_handler(CommandHandler("achievements", self.achievements_command))
        self.app.add_handler(CommandHandler("referral", self.referral_command))
        self.app.add_handler(CommandHandler("ref", self.referral_command))
        self.app.add_handler(CommandHandler("rp", self.rp_command))
        self.app.add_handler(CommandHandler("dice", self.dice_command))
        self.app.add_handler(CommandHandler("coinflip", self.coinflip_command))
        self.app.add_handler(CommandHandler("flip", self.coinflip_command))
        self.app.add_handler(CommandHandler("tip", self.tip_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome message"""
        user = update.effective_user
        user_data = self.db.get_user(user.id)
        
        if user_data.get("username") != user.username:
            self.db.update_user(user.id, {"username": user.username})
        
        playthrough_msg = f"\n⚠️ Playthrough Required: ${user_data['playthrough_required']:.2f}" if user_data['playthrough_required'] > 0 else ""
        
        welcome_text = f"""
🎰 **Welcome to Antaria Casino** 🎰

Hey {user.first_name}! Ready to test your luck?

💰 **Your Balance**: ${user_data['balance']:.2f}{playthrough_msg}

**🎮 Games:**
/dice <amount> - Roll the highest number (1-6)
/flip <amount> [@player] - Classic coin flip

**💎 Features:**
/bal - Check balance & deposit/withdraw
/tip <amount> @user - Send money to another player
/bonus - Claim your daily bonus (1% of wagered)
/stats - View your statistics
/global - Top players by volume
/achievements - View your badges
/ref - Get your referral link
/rp - Check your Respect Points level

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
            [InlineKeyboardButton("💵 Deposit", callback_data="deposit"),
             InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
            [InlineKeyboardButton("📜 Transaction History", callback_data="transactions")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def bonus_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Claim daily bonus"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        last_claim = user_data.get('last_bonus_claim')
        if last_claim:
            last_claim_time = datetime.fromisoformat(last_claim)
            time_diff = datetime.now() - last_claim_time
            if time_diff < timedelta(hours=24):
                remaining = timedelta(hours=24) - time_diff
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                await update.message.reply_text(
                    f"⏰ Daily bonus on cooldown!\n"
                    f"Time remaining: {hours}h {minutes}m"
                )
                return
        
        wagered_since_withdrawal = user_data.get('wagered_since_last_withdrawal', 0)
        bonus_amount = wagered_since_withdrawal * 0.01
        
        if bonus_amount < 0.01:
            await update.message.reply_text(
                f"📊 Current bonus: ${bonus_amount:.2f}\n"
                f"Total wagered since last withdrawal: ${wagered_since_withdrawal:.2f}\n\n"
                f"Minimum bonus to claim: $0.01\n"
                f"Keep playing to earn more!"
            )
            return
        
        user_data['balance'] += bonus_amount
        user_data['playthrough_required'] += bonus_amount
        user_data['last_bonus_claim'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "bonus", bonus_amount, "Daily bonus claimed")
        
        await update.message.reply_text(
            f"🎁 **Daily Bonus Claimed!**\n\n"
            f"Amount: ${bonus_amount:.2f}\n"
            f"Based on: ${wagered_since_withdrawal:.2f} wagered\n"
            f"New Balance: ${user_data['balance']:.2f}\n\n"
            f"⚠️ You must wager this bonus before withdrawing",
            parse_mode="Markdown"
        )
    
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
        
        level = self.db.calculate_rp_level(user_id)
        
        stats_text = f"""
📊 **Your Statistics**

👤 Level: {level}
🎮 Games Played: {games_played}
📈 Win Rate: {win_rate:.1f}%
💰 Total Wagered: ${user_data.get('total_wagered', 0):.2f}
📊 Total P&L: ${user_data.get('total_pnl', 0):.2f}
🔥 Best Win Streak: {user_data.get('best_win_streak', 0)}
📅 First Wager: {first_wager_str}
🏆 Achievements: {len(user_data.get('achievements', []))}/6
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
        
        for idx, player in enumerate(page_data, start=start_idx + 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            leaderboard_text += f"{medal} **{player['username']}**\n"
            leaderboard_text += f"   💰 Wagered: ${player['total_wagered']:.2f}\n\n"
        
        keyboard = []
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"lb_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"lb_page_{page + 1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("🔢 Go to Page", callback_data="lb_goto")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
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
    
    async def achievements_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show achievements"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        unlocked = user_data.get('achievements', [])
        
        achievements_text = "🏆 **Your Achievements**\n\n"
        
        for ach_id, ach_info in ACHIEVEMENT_INFO.items():
            status = "✅" if ach_id in unlocked else "❌"
            achievements_text += f"{status} {ach_info['name']}\n"
            achievements_text += f"   {ach_info['desc']}\n\n"
        
        await update.message.reply_text(achievements_text, parse_mode="Markdown")
    
    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show referral link and earnings"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not user_data.get('referral_code'):
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
        if user_data.get('unclaimed_referral_earnings', 0) > 0:
            keyboard.append([InlineKeyboardButton("💰 Claim Earnings", callback_data="claim_referral")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(referral_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def rp_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show Respect Points level"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        level = self.db.calculate_rp_level(user_id)
        
        total_wagered = user_data.get('total_wagered', 0)
        achievement_count = len(user_data.get('achievements', []))
        
        days_active = 0
        if user_data.get('created_at'):
            created = datetime.fromisoformat(user_data['created_at'])
            days_active = (datetime.now() - created).days
        
        rp_text = f"""
⭐ **Respect Points (RP)**

Current Level: **{level}**

📊 RP Breakdown:
• Wagering: {total_wagered / 100:.0f} RP
• Achievements: {achievement_count * 50} RP
• Days Active: {days_active * 2} RP

💡 Level up by playing more, unlocking achievements, and staying active!
"""
        
        await update.message.reply_text(rp_text, parse_mode="Markdown")
    
    async def dice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play dice game"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: /dice <amount>")
            return
        
        try:
            wager = float(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid wager amount")
            return
        
        if wager <= 0:
            await update.message.reply_text("❌ Wager must be positive")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"dice_bot_{wager}")],
            [InlineKeyboardButton("👥 Play vs Player", callback_data=f"dice_player_{wager}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎲 **Dice Game**\n\nWager: ${wager:.2f}\n\nChoose your opponent:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def dice_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play dice against the bot"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        chat_id = update.effective_chat.id
        
        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        
        player_roll = player_dice_msg.dice.value
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(3.5)
        
        if player_roll > bot_roll:
            profit = wager
            user_data['balance'] += profit
            user_data['games_won'] += 1
            user_data['win_streak'] += 1
            user_data['best_win_streak'] = max(user_data.get('best_win_streak', 0), user_data['win_streak'])
            result_text = f"🎉 **You Won!** +${profit:.2f}"
        elif player_roll < bot_roll:
            user_data['balance'] -= wager
            profit = -wager
            user_data['win_streak'] = 0
            result_text = f"😢 **You Lost!** -${wager:.2f}"
        else:
            profit = 0
            result_text = f"🤝 **Draw!** Bet refunded"
        
        user_data['games_played'] += 1
        user_data['total_wagered'] += wager
        user_data['wagered_since_last_withdrawal'] += wager
        user_data['total_pnl'] += profit
        
        if user_data['playthrough_required'] > 0:
            user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
        
        if not user_data.get('first_wager_date'):
            user_data['first_wager_date'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "dice_bot", profit, f"Dice vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "dice_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": "win" if profit > 0 else "loss" if profit < 0 else "draw"
        })
        
        await self.check_and_notify_achievements(update, context, user_id)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
    
    async def dice_vs_bot_from_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play dice against bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        player_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        bot_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        
        player_roll = player_dice_msg.dice.value
        bot_roll = bot_dice_msg.dice.value
        
        await asyncio.sleep(3.5)
        
        if player_roll > bot_roll:
            profit = wager
            user_data['balance'] += profit
            user_data['games_won'] += 1
            user_data['win_streak'] += 1
            user_data['best_win_streak'] = max(user_data.get('best_win_streak', 0), user_data['win_streak'])
            result_text = f"🎉 **You Won!** +${profit:.2f}"
        elif player_roll < bot_roll:
            user_data['balance'] -= wager
            profit = -wager
            user_data['win_streak'] = 0
            result_text = f"😢 **You Lost!** -${wager:.2f}"
        else:
            profit = 0
            result_text = f"🤝 **Draw!** Bet refunded"
        
        user_data['games_played'] += 1
        user_data['total_wagered'] += wager
        user_data['wagered_since_last_withdrawal'] += wager
        user_data['total_pnl'] += profit
        
        if user_data['playthrough_required'] > 0:
            user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
        
        if not user_data.get('first_wager_date'):
            user_data['first_wager_date'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "dice_bot", profit, f"Dice vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "dice_bot",
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": "win" if profit > 0 else "loss" if profit < 0 else "draw"
        })
        
        await self.check_and_notify_achievements(update, context, user_id)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
    
    async def create_open_dice_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Create an open dice challenge for anyone to accept"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        
        if wager > user_data['balance']:
            await query.edit_message_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        challenge_id = f"dice_open_{user_id}_{int(datetime.now().timestamp())}"
        self.db.data['pending_pvp'][challenge_id] = {
            "type": "dice",
            "challenger": user_id,
            "opponent": None,
            "wager": wager,
            "created_at": datetime.now().isoformat()
        }
        self.db.save_data()
        
        keyboard = [[InlineKeyboardButton("✅ Accept Challenge", callback_data=f"accept_dice_{challenge_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎲 **Open Dice Challenge!**\n\n"
            f"Challenger: {username}\n"
            f"Wager: ${wager:.2f}\n\n"
            f"Anyone can accept this challenge!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    async def dice_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, opponent_id: int):
        """Initiate PvP dice game"""
        user_id = update.effective_user.id
        
        challenge_id = f"dice_{user_id}_{opponent_id}_{int(datetime.now().timestamp())}"
        self.db.data['pending_pvp'][challenge_id] = {
            "type": "dice",
            "challenger": user_id,
            "opponent": opponent_id,
            "wager": wager,
            "created_at": datetime.now().isoformat()
        }
        self.db.save_data()
        
        keyboard = [
            [InlineKeyboardButton("✅ Accept", callback_data=f"accept_dice_{challenge_id}"),
             InlineKeyboardButton("❌ Decline", callback_data=f"decline_{challenge_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🎲 <b>Dice Challenge!</b>\n\n"
            f"Wager: ${wager:.2f}\n"
            f"Waiting for opponent to accept...",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    async def coinflip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play coinflip game"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: /flip <amount> [@player]")
            return
        
        try:
            wager = float(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid wager amount")
            return
        
        if wager <= 0:
            await update.message.reply_text("❌ Wager must be positive")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        opponent_id = None
        if update.message.entities:
            for entity in update.message.entities:
                if entity.type == "text_mention":
                    opponent_id = entity.user.id
                    break
        
        if opponent_id:
            keyboard = [
                [InlineKeyboardButton("🟡 Heads", callback_data=f"flip_pvp_{wager}_{opponent_id}_heads")],
                [InlineKeyboardButton("⚪ Tails", callback_data=f"flip_pvp_{wager}_{opponent_id}_tails")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🪙 **Coin Flip vs Player**\n\nWager: ${wager:.2f}\n\nChoose your side:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🟡 Heads", callback_data=f"flip_bot_{wager}_heads")],
                [InlineKeyboardButton("⚪ Tails", callback_data=f"flip_bot_{wager}_tails")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🪙 **Coin Flip vs Bot**\n\nWager: ${wager:.2f}\n\nChoose your side:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    
    async def coinflip_vs_bot_from_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play coinflip against bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        await context.bot.send_message(chat_id=chat_id, text="🪙")
        
        await asyncio.sleep(1)
        
        result = random.choice(['heads', 'tails'])
        
        if choice == result:
            profit = wager
            user_data['balance'] += profit
            user_data['games_won'] += 1
            user_data['win_streak'] += 1
            user_data['best_win_streak'] = max(user_data.get('best_win_streak', 0), user_data['win_streak'])
            result_text = f"🎉 **You Won!** +${profit:.2f}\n\nYou chose: {choice.capitalize()}\nResult: {result.capitalize()}\n\n💰 **New Balance:** ${user_data['balance']:.2f}"
        else:
            user_data['balance'] -= wager
            profit = -wager
            user_data['win_streak'] = 0
            result_text = f"😢 **You Lost!** -${wager:.2f}\n\nYou chose: {choice.capitalize()}\nResult: {result.capitalize()}\n\n💰 **New Balance:** ${user_data['balance']:.2f}"
        
        user_data['games_played'] += 1
        user_data['total_wagered'] += wager
        user_data['wagered_since_last_withdrawal'] += wager
        user_data['total_pnl'] += profit
        
        if user_data['playthrough_required'] > 0:
            user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
        
        if not user_data.get('first_wager_date'):
            user_data['first_wager_date'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "coinflip_bot", profit, f"CoinFlip vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "coinflip_bot",
            "player_id": user_id,
            "wager": wager,
            "choice": choice,
            "result": result,
            "outcome": "win" if profit > 0 else "loss"
        })
        
        await self.check_and_notify_achievements(update, context, user_id)
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
    
    async def coinflip_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play coinflip against the bot"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        chat_id = update.effective_chat.id
        
        await context.bot.send_message(chat_id=chat_id, text="🪙")
        
        await asyncio.sleep(1)
        
        result = random.choice(['heads', 'tails'])
        
        if choice == result:
            profit = wager
            user_data['balance'] += profit
            user_data['games_won'] += 1
            user_data['win_streak'] += 1
            user_data['best_win_streak'] = max(user_data.get('best_win_streak', 0), user_data['win_streak'])
            result_text = f"🎉 **You Won!** +${profit:.2f}\n\n💰 **New Balance:** ${user_data['balance'] + profit:.2f}"
        else:
            user_data['balance'] -= wager
            profit = -wager
            user_data['win_streak'] = 0
            result_text = f"😢 **You Lost!** -${wager:.2f}\n\n💰 **New Balance:** ${user_data['balance'] - wager:.2f}"
        
        user_data['games_played'] += 1
        user_data['total_wagered'] += wager
        user_data['wagered_since_last_withdrawal'] += wager
        user_data['total_pnl'] += profit
        
        if user_data['playthrough_required'] > 0:
            user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
        
        if not user_data.get('first_wager_date'):
            user_data['first_wager_date'] = datetime.now().isoformat()
        
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "coinflip_bot", profit, f"CoinFlip vs Bot - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "coinflip_bot",
            "player_id": user_id,
            "wager": wager,
            "choice": choice,
            "result": result,
            "outcome": "win" if profit > 0 else "loss"
        })
        
        await self.check_and_notify_achievements(update, context, user_id)
        
        await update.message.reply_text(result_text, parse_mode="Markdown")
    
    async def coinflip_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str, opponent_id: int):
        """Initiate PvP coinflip game"""
        user_id = update.effective_user.id
        
        opposite_choice = 'tails' if choice == 'heads' else 'heads'
        
        challenge_id = f"coinflip_{user_id}_{opponent_id}_{int(datetime.now().timestamp())}"
        self.db.data['pending_pvp'][challenge_id] = {
            "type": "coinflip",
            "challenger": user_id,
            "opponent": opponent_id,
            "wager": wager,
            "challenger_choice": choice,
            "opponent_choice": opposite_choice,
            "created_at": datetime.now().isoformat()
        }
        self.db.save_data()
        
        keyboard = [
            [InlineKeyboardButton("✅ Accept", callback_data=f"accept_coinflip_{challenge_id}"),
             InlineKeyboardButton("❌ Decline", callback_data=f"decline_{challenge_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🪙 <b>CoinFlip Challenge!</b>\n\n"
            f"Wager: ${wager:.2f}\n"
            f"Your choice: {choice.capitalize()}\n"
            f"Opponent gets: {opposite_choice.capitalize()}\n\n"
            f"Waiting for opponent to accept...",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    async def coinflip_pvp_from_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str, opponent_id: int):
        """Initiate PvP coinflip game from button"""
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        opposite_choice = 'tails' if choice == 'heads' else 'heads'
        
        challenge_id = f"coinflip_{user_id}_{opponent_id}_{int(datetime.now().timestamp())}"
        self.db.data['pending_pvp'][challenge_id] = {
            "type": "coinflip",
            "challenger": user_id,
            "opponent": opponent_id,
            "wager": wager,
            "challenger_choice": choice,
            "opponent_choice": opposite_choice,
            "created_at": datetime.now().isoformat()
        }
        self.db.save_data()
        
        keyboard = [
            [InlineKeyboardButton("✅ Accept", callback_data=f"accept_coinflip_{challenge_id}"),
             InlineKeyboardButton("❌ Decline", callback_data=f"decline_{challenge_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🪙 <b>CoinFlip Challenge!</b>\n\n"
                 f"Wager: ${wager:.2f}\n"
                 f"Your choice: {choice.capitalize()}\n"
                 f"Opponent gets: {opposite_choice.capitalize()}\n\n"
                 f"Waiting for opponent to accept...",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    async def tip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send money to another user"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        if not context.args:
            await update.message.reply_text("Usage: /tip <amount> @user")
            return
        
        try:
            amount = float(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount")
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive")
            return
        
        if amount > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        recipient_id = None
        recipient_username = None
        
        if update.message.entities:
            for entity in update.message.entities:
                if entity.type == "text_mention":
                    recipient_id = entity.user.id
                    break
                elif entity.type == "mention":
                    offset = entity.offset
                    length = entity.length
                    recipient_username = update.message.text[offset:offset+length].lstrip('@')
                    break
        
        if not recipient_id and len(context.args) > 1:
            potential_username = context.args[1].lstrip('@')
            for uid, data in self.db.data['users'].items():
                user_username = data.get('username') if data else None
                if user_username and user_username.lower() == potential_username.lower():
                    recipient_id = int(uid)
                    break
        
        if recipient_username and not recipient_id:
            for uid, data in self.db.data['users'].items():
                user_username = data.get('username') if data else None
                if user_username and user_username.lower() == recipient_username.lower():
                    recipient_id = int(uid)
                    break
        
        if not recipient_id:
            await update.message.reply_text("❌ User not found. They need to start the bot first!")
            return
        
        if recipient_id == user_id:
            await update.message.reply_text("❌ You can't tip yourself!")
            return
        
        recipient_data = self.db.get_user(recipient_id)
        recipient_name = recipient_data.get('username', f'User{recipient_id}')
        
        user_data['balance'] -= amount
        recipient_data['balance'] += amount
        
        self.db.update_user(user_id, user_data)
        self.db.update_user(recipient_id, recipient_data)
        
        self.db.add_transaction(user_id, "tip_sent", -amount, f"Tipped ${amount:.2f} to {recipient_name}")
        self.db.add_transaction(recipient_id, "tip_received", amount, f"Received ${amount:.2f} tip")
        
        await update.message.reply_text(
            f"✅ **Tip Sent!**\n\n"
            f"Amount: ${amount:.2f}\n"
            f"To: {recipient_name}\n"
            f"Your New Balance: ${user_data['balance']:.2f}",
            parse_mode="Markdown"
        )
    
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create manual backup"""
        backup_file = self.db.backup_data()
        if backup_file:
            await update.message.reply_text(f"✅ Backup created: {backup_file}")
        else:
            await update.message.reply_text("❌ Backup failed")
    
    async def check_and_notify_achievements(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Check for new achievements"""
        for ach_id in ACHIEVEMENT_INFO.keys():
            if self.db.check_achievement(user_id, ach_id):
                chat_id = update.effective_chat.id if update.effective_chat else None
                if chat_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🏆 **Achievement Unlocked!**\n{ACHIEVEMENT_INFO[ach_id]['name']}\n{ACHIEVEMENT_INFO[ach_id]['desc']}",
                        parse_mode="Markdown"
                    )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "deposit":
            await query.edit_message_text(
                "💵 **Deposit Instructions**\n\n"
                "This is a demo bot. In production, you would:\n"
                "1. Integrate with a payment processor\n"
                "2. Generate unique payment addresses\n"
                "3. Automatically credit deposits\n\n"
                "For testing, contact an admin to add funds.",
                parse_mode="Markdown"
            )
        
        elif data == "withdraw":
            user_data = self.db.get_user(user_id)
            if user_data['playthrough_required'] > 0:
                await query.edit_message_text(
                    f"⚠️ **Withdrawal Locked**\n\n"
                    f"You must wager ${user_data['playthrough_required']:.2f} more to unlock withdrawals.\n\n"
                    f"This prevents bonus abuse.",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    "💸 **Withdrawal Request**\n\n"
                    "This is a demo bot. In production, you would:\n"
                    "1. Enter withdrawal amount\n"
                    "2. Provide wallet address\n"
                    "3. Admin approval for large amounts\n"
                    "4. Automatic processing\n\n"
                    f"Available: ${user_data['balance']:.2f}",
                    parse_mode="Markdown"
                )
        
        elif data == "transactions":
            user_data = self.db.get_user(user_id)
            transactions = user_data.get('transactions', [])[-10:]
            
            if not transactions:
                await query.edit_message_text("📜 No transactions yet")
                return
            
            tx_text = "📜 **Recent Transactions**\n\n"
            for tx in reversed(transactions):
                amount_str = f"+${tx['amount']:.2f}" if tx['amount'] >= 0 else f"-${abs(tx['amount']):.2f}"
                tx_text += f"{tx['type']}: {amount_str}\n{tx['description']}\n\n"
            
            await query.edit_message_text(tx_text, parse_mode="Markdown")
        
        elif data == "claim_referral":
            user_data = self.db.get_user(user_id)
            unclaimed = user_data.get('unclaimed_referral_earnings', 0)
            
            if unclaimed > 0:
                user_data['balance'] += unclaimed
                user_data['unclaimed_referral_earnings'] = 0
                self.db.update_user(user_id, user_data)
                self.db.add_transaction(user_id, "referral", unclaimed, "Referral earnings claimed")
                
                await query.edit_message_text(
                    f"💰 **Claimed ${unclaimed:.2f} in referral earnings!**",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text("❌ No referral earnings to claim")
        
        elif data.startswith("lb_page_"):
            page = int(data.split("_")[2])
            await self.show_leaderboard_page(update, page)
        
        elif data.startswith("dice_bot_"):
            wager = float(data.replace("dice_bot_", ""))
            await query.delete_message()
            await self.dice_vs_bot_from_button(update, context, wager)
        
        elif data.startswith("dice_player_"):
            wager = float(data.replace("dice_player_", ""))
            await self.create_open_dice_challenge(update, context, wager)
        
        elif data.startswith("accept_dice_"):
            challenge_id = data.replace("accept_dice_", "")
            await self.execute_dice_pvp(update, context, challenge_id)
        
        elif data.startswith("flip_bot_"):
            parts = data.replace("flip_bot_", "").split("_")
            wager = float(parts[0])
            choice = parts[1]
            await query.delete_message()
            await self.coinflip_vs_bot_from_button(update, context, wager, choice)
        
        elif data.startswith("flip_pvp_"):
            parts = data.replace("flip_pvp_", "").split("_")
            wager = float(parts[0])
            opponent_id = int(parts[1])
            choice = parts[2]
            await query.delete_message()
            await self.coinflip_pvp_from_button(update, context, wager, choice, opponent_id)
        
        elif data.startswith("accept_coinflip_"):
            challenge_id = data.replace("accept_coinflip_", "")
            await self.execute_coinflip_pvp(update, context, challenge_id)
        
        elif data.startswith("decline_"):
            challenge_id = data.split("_", 1)[1]
            if challenge_id in self.db.data['pending_pvp']:
                del self.db.data['pending_pvp'][challenge_id]
                self.db.save_data()
            await query.edit_message_text("❌ Challenge declined")
    
    async def execute_dice_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Execute PvP dice game"""
        query = update.callback_query
        chat_id = query.message.chat_id
        
        if challenge_id not in self.db.data['pending_pvp']:
            await query.edit_message_text("❌ Challenge expired or invalid")
            return
        
        challenge = self.db.data['pending_pvp'][challenge_id]
        challenger_id = challenge['challenger']
        opponent_id = query.from_user.id
        wager = challenge['wager']
        
        if opponent_id == challenger_id:
            await query.answer("You can't accept your own challenge!", show_alert=True)
            return
        
        challenger_data = self.db.get_user(challenger_id)
        opponent_data = self.db.get_user(opponent_id)
        
        if challenger_data['balance'] < wager:
            await query.edit_message_text("❌ Challenger has insufficient funds")
            del self.db.data['pending_pvp'][challenge_id]
            self.db.save_data()
            return
        
        if opponent_data['balance'] < wager:
            await query.edit_message_text("❌ You have insufficient funds")
            return
        
        await query.edit_message_text("🎲 **Game Started!**")
        
        challenger_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        opponent_dice_msg = await context.bot.send_dice(chat_id=chat_id, emoji="🎲")
        
        challenger_roll = challenger_dice_msg.dice.value
        opponent_roll = opponent_dice_msg.dice.value
        
        await asyncio.sleep(3.5)
        
        if challenger_roll > opponent_roll:
            challenger_data['balance'] += wager
            opponent_data['balance'] -= wager
            challenger_data['games_won'] += 1
            result_text = "🎉 Challenger wins!"
        elif opponent_roll > challenger_roll:
            opponent_data['balance'] += wager
            challenger_data['balance'] -= wager
            opponent_data['games_won'] += 1
            result_text = "🎉 Opponent wins!"
        else:
            result_text = "🤝 Draw! Bets refunded"
        
        for uid in [challenger_id, opponent_id]:
            user_data = self.db.get_user(uid)
            user_data['games_played'] += 1
            user_data['total_wagered'] += wager
            user_data['wagered_since_last_withdrawal'] += wager
            if user_data['playthrough_required'] > 0:
                user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
            self.db.update_user(uid, user_data)
        
        del self.db.data['pending_pvp'][challenge_id]
        self.db.save_data()
        
        await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")
    
    async def execute_coinflip_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Execute PvP coinflip game"""
        query = update.callback_query
        
        if challenge_id not in self.db.data['pending_pvp']:
            await query.edit_message_text("❌ Challenge expired or invalid")
            return
        
        challenge = self.db.data['pending_pvp'][challenge_id]
        challenger_id = challenge['challenger']
        opponent_id = challenge['opponent']
        wager = challenge['wager']
        challenger_choice = challenge['challenger_choice']
        
        if query.from_user.id != opponent_id:
            await query.answer("This challenge is not for you!", show_alert=True)
            return
        
        challenger_data = self.db.get_user(challenger_id)
        opponent_data = self.db.get_user(opponent_id)
        
        if challenger_data['balance'] < wager:
            await query.edit_message_text("❌ Challenger has insufficient funds")
            del self.db.data['pending_pvp'][challenge_id]
            self.db.save_data()
            return
        
        if opponent_data['balance'] < wager:
            await query.edit_message_text("❌ You have insufficient funds")
            return
        
        result = random.choice(['heads', 'tails'])
        
        result_text = f"🪙 **PvP CoinFlip**\n\n"
        result_text += f"Result: **{result.capitalize()}**\n\n"
        
        if challenger_choice == result:
            challenger_data['balance'] += wager
            opponent_data['balance'] -= wager
            challenger_data['games_won'] += 1
            result_text += "🎉 Challenger wins!"
        else:
            opponent_data['balance'] += wager
            challenger_data['balance'] -= wager
            opponent_data['games_won'] += 1
            result_text += "🎉 Opponent wins!"
        
        for uid in [challenger_id, opponent_id]:
            user_data = self.db.get_user(uid)
            user_data['games_played'] += 1
            user_data['total_wagered'] += wager
            user_data['wagered_since_last_withdrawal'] += wager
            if user_data['playthrough_required'] > 0:
                user_data['playthrough_required'] = max(0, user_data['playthrough_required'] - wager)
            self.db.update_user(uid, user_data)
        
        del self.db.data['pending_pvp'][challenge_id]
        self.db.save_data()
        
        await query.edit_message_text(result_text, parse_mode="Markdown")
    
    async def post_init(self, application):
        """Start auto-save after application initializes"""
        asyncio.create_task(self.db.auto_save_loop())
        print("💾 Auto-save enabled (every 5 minutes)")
    
    def run(self):
        """Run the bot"""
        print("🎰 Antaria Casino Bot Starting...")
        print(f"✅ Database loaded: {len(self.db.data['users'])} users")
        print("🚀 Bot is running!")
        
        self.app.post_init = self.post_init
        self.app.run_polling()


def main():
    bot_token = os.getenv("BOT_TOKEN")
    
    if not bot_token:
        print("❌ Error: BOT_TOKEN environment variable not set!")
        print("Set it with: export BOT_TOKEN='your_token_here'")
        return
    
    bot = AntariaCasinoBot(bot_token)
    bot.run()


if __name__ == "__main__":
    main()
