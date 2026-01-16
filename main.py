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

# --- 1. Database Manager (PostgreSQL) ---
from flask import Flask
from models import db, User, Game, Transaction, GlobalState

class DatabaseManager:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
        self.app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_recycle": 300, "pool_pre_ping": True}
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()
            # Initialize house balance if not exists
            house_balance_state = db.session.get(GlobalState, "house_balance")
            if not house_balance_state:
                db.session.add(GlobalState(key="house_balance", value={"amount": 10000.00}))
            
            dynamic_admins_state = db.session.get(GlobalState, "dynamic_admins")
            if not dynamic_admins_state:
                db.session.add(GlobalState(key="dynamic_admins", value={"ids": []}))
            
            stickers_state = db.session.get(GlobalState, "stickers")
            if not stickers_state:
                db.session.add(GlobalState(key="stickers", value={"roulette": {}}))
            db.session.commit()

    @property
    def data(self):
        # Compatibility layer for existing code that accesses self.db.data
        with self.app.app_context():
            house_balance_state = db.session.get(GlobalState, "house_balance")
            house_balance = house_balance_state.value["amount"] if house_balance_state else 10000.00
            
            dynamic_admins_state = db.session.get(GlobalState, "dynamic_admins")
            dynamic_admins = dynamic_admins_state.value["ids"] if dynamic_admins_state else []
            
            stickers_state = db.session.get(GlobalState, "stickers")
            stickers = stickers_state.value if stickers_state else {}
            
            pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
            pending_pvp = pending_pvp_state.value if pending_pvp_state else {}
            
            return {
                "house_balance": house_balance,
                "dynamic_admins": dynamic_admins,
                "stickers": stickers,
                "pending_pvp": pending_pvp
            }

    def save_data(self):
        # Compatibility layer
        pass

    def update_pending_pvp(self, pending_pvp_data: Dict[str, Any]):
        with self.app.app_context():
            state = db.session.get(GlobalState, "pending_pvp")
            if not state:
                state = GlobalState(key="pending_pvp", value=pending_pvp_data)
                db.session.add(state)
            else:
                # Force SQLAlchemy to detect change in JSON
                state.value = dict(pending_pvp_data)
            db.session.commit()

    def get_user(self, user_id: int) -> Dict[str, Any]:
        with self.app.app_context():
            from sqlalchemy import select
            user = db.session.execute(select(User).filter_by(user_id=user_id)).scalar_one_or_none()
            if not user:
                user = User(user_id=user_id, username=f"User{user_id}")
                db.session.add(user)
                db.session.commit()
            return self._user_to_dict(user)

    def _user_to_dict(self, user):
        return {c.name: getattr(user, c.name) for c in user.__table__.columns}

    def update_user(self, user_id: int, updates: Dict[str, Any]):
        with self.app.app_context():
            from sqlalchemy import update
            db.session.execute(update(User).filter_by(user_id=user_id).values(updates))
            db.session.commit()

    def get_house_balance(self) -> float:
        with self.app.app_context():
            return db.session.get(GlobalState, "house_balance").value["amount"]

    def update_house_balance(self, change: float):
        with self.app.app_context():
            state = db.session.get(GlobalState, "house_balance")
            val = state.value.copy()
            val["amount"] += change
            state.value = val
            db.session.commit()

    def add_transaction(self, user_id: int, type: str, amount: float, description: str):
        with self.app.app_context():
            tx = Transaction(user_id=user_id, type=type, amount=amount, description=description)
            db.session.add(tx)
            db.session.commit()

    def record_game(self, game_data: Dict[str, Any]):
        with self.app.app_context():
            g = Game(data=game_data)
            db.session.add(g)
            db.session.commit()

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        with self.app.app_context():
            from sqlalchemy import select
            users = db.session.execute(select(User).order_by(User.total_wagered.desc()).limit(50)).scalars().all()
            return [{"username": u.username or f"User{u.user_id}", "total_wagered": u.total_wagered} for u in users]

    def save_data(self):
        pass # No longer needed for SQL

# --- 2. Antaria Casino Bot Class ---
class AntariaCasinoBot:
    def __init__(self, token: str):
        self.token = token
        # Initialize the internal database manager
        self.db = DatabaseManager()
        
        self.emoji_map = {
            "dice": "🎲",
            "basketball": "🏀",
            "soccer": "⚽",
            "darts": "🎯",
            "bowling": "🎳",
            "coinflip": "🪙"
        }
        
        # Admin user IDs from environment variable (permanent admins)
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        self.env_admin_ids = set()
        if admin_ids_str:
            try:
                self.env_admin_ids = set(int(id.strip()) for id in admin_ids_str.split(",") if id.strip())
                logger.info(f"Loaded {len(self.env_admin_ids)} permanent admin(s) from environment")
            except ValueError:
                logger.error("Invalid ADMIN_IDS format. Use comma-separated numbers.")
        
        # Load dynamic admins from database
        if 'dynamic_admins' not in self.db.data:
            self.db.data['dynamic_admins'] = []
            self.db.save_data()
        
        self.dynamic_admin_ids = set(self.db.data.get('dynamic_admins', []))
        if self.dynamic_admin_ids:
            logger.info(f"Loaded {len(self.dynamic_admin_ids)} dynamic admin(s) from database")
        
        # Initialize bot application
        token = os.environ.get("TELEGRAM_TOKEN")
        self.app = Application.builder().token(token).build()
        self.app.bot_data['casino_bot'] = self # Store reference for access from handlers if needed
        # Add job queue check
        if not self.app.job_queue:
            logger.warning("Job queue is not available. Some features like challenge expiration may not work.")
        self.setup_handlers()
        
        # Dictionary to store ongoing PvP challenges
        self.pending_pvp: Dict[str, Any] = self.db.data.get('pending_pvp', {})
        
        # Track button ownership: (chat_id, message_id) -> user_id mapping
        self.button_ownership: Dict[tuple, int] = {}
        # Track clicked buttons to prevent re-use: (chat_id, message_id, callback_data)
        self.clicked_buttons: set = set()
        
        # Sticker configuration - Load from database or initialize with defaults
        if 'stickers' not in self.db.data:
            self.db.data['stickers'] = {
                "roulette": {
                    "00": "CAACAgQAAxkBAAEPnjFo-TLLYpgTZExC4IIOG6PIXwsviAAC1BgAAkmhgFG_0u82E59m3DYE",
                    "0": "CAACAgQAAxkBAAEPnjNo-TMFaqDdWCkRDNlus4jcuamAAwACOh0AAtQAAYBRlMLfm2ulRSM2BA",
                    "1": "CAACAgQAAxkBAAEPnjRo-TMFH5o5R9ztNtTFBJmQVK_t3wACqBYAAvTrgVE4WCoxbBzVCDYE",
                    "2": "CAACAgQAAxkBAAEPnjdo-TMvGdoX-f6IAuR7kpYO-hh9fwAC1RYAAob0eVF1zbcG00UjMzYE",
                    "3": "CAACAgQAAxkBAAEPnjho-TMwui0CFuGEK5iwS7xMRDiPfgACSRgAAs74gVEyHQtTsRykGjYE",
                    "4": "CAACAgQAAxkBAAEPnj1o-TNGYNdmhy4n5Uyp3pzWmukTgAACfBgAAg3IgFGEjdLKewti5zYE",
                    "5": "CAACAgQAAxkBAAEPnj5o-TNHTKLFF2NpdxfLhHnsnFGTXgACyhYAAltygVECKXn73kUyCjYE",
                    "6": "CAACAgQAAxkBAAEPnkFo-TNPGqrsJJwZNwUe_I6k4W86cwACyxoAAgutgVGyiCe4lNK2-DYE",
                    "7": "CAACAgQAAxkBAAEPnkJo-TNPksXPcYnpXDWYQC68AAGlqzQAAtUYAAKU_IFRJTHChQd2yfw2BA",
                    "8": "CAACAgQAAxkBAAEPnkdo-TQOIBN5WtoKKnvcthXdcy0LLgACgBQAAmlWgVFImh6M5RcAAdI2BA",
                    "9": "CAACAgQAAxkBAAEPnkho-TQO92px4jOuq80nT2uWjURzSAAC4BcAAvPKeVFBx-TZycAWDzYE",
                    "10": "CAACAgQAAxkBAAEPnkto-TZ8-6moW-biByRYl8J2QEPnTwAC8hgAArnAgFGen1zgHwABLPc2BA",
                    "11": "CAACAgQAAxkBAAEPnkxo-TZ8ncZZ7FYYyFMJHXRv2rB0TwAC2RMAAmzdgVEao0YAAdIy41g2BA",
                    "12": "CAACAgQAAxkBAAEPnk1o-TZ9z6xAxxIeccUPXoQQ9VaikQACVRgAAovngVFUjR-qYgq8LDYE",
                    "13": "CAACAgQAAxkBAAEPnlFo-TbUs79Rm549dK3JK2L3P83q-QACTR0AAmc0gFHXnJ509OdiOjYE",
                    "14": "CAACAgQAAxkBAAEPnlJo-TbUCpjrhSxP-x84jkBerEYB8AACQxkAAqXDeVEQ5uCH3dK9OjYE",
                    "15": "CAACAgQAAxkBAAEPnlNo-TbUZokc7ubz-neSYtK9kxQ0DAACrRYAAlBWgVH9BqGde-NivjYE",
                    "16": "CAACAgQAAxkBAAEPnlRo-TbUiOcqxKI6HNExFR8yT3qyvAACrxsAAkcfeVG9im0F0tuZPzYE",
                    "17": "CAACAgQAAxkBAAEPnllo-TdIFRtpAW3PeDbxD2QxTgjk2QACLhgAAiuXgVHaPo1woXZEYTYE",
                    "18": "CAACAgQAAxkBAAEPnlpo-TdI9Gdz2Nv3icxluy8jC3keBwACYxkAAnx7eFGsZP2AXXBKwzYE",
                    "19": "CAACAgQAAxkBAAEPnlto-TdIUktLbTIhkihQz3ymy4lUIwACKRkAArDwgFH0iKqIPPiHYDYE",
                    "20": "CAACAgQAAxkBAAEPnlxo-TdJVrOSPiCRuD8Jc0XGvF3B8AACcxoAAr7OeFGSuSoHyKxf5TYE",
                    "21": "CAACAgQAAxkBAAEPnl1o-TdJ1jlMSjGQPO0zkaS_rOv5JQACxhcAAv1dgFF3khtGYFneYzYE",
                    "22": "CAACAgQAAxkBAAEPnmNo-Te2OhfAwfprG1HfmY-UNtkEAgADGQACE8KAUSJTKzPQQQ9INgQ",
                    "23": "CAACAgQAAxkBAAEPnmRo-Te3rAHmt7_CRgFp55KSNVYdKwACTBgAAundgVF6unXyM34ZYzYE",
                    "24": "CAACAgQAAxkBAAEPnmVo-Te3LcVARwsUx3Akt75bruvNXAAC4RoAAnkvgFHRL4l2927wnDYE",
                    "25": "CAACAgQAAxkBAAEPnmZo-Te3lY0O1JxF8tTLYJJhN1QcnAAC5hcAAiPegFFsMkNzpqfR0zYE",
                    "26": "CAACAgQAAxkBAAEPnmto-TgIsR6UdO8EukNYajboFnX3mgACzSAAAn15gVG-oQ4oaJLYrzYE",
                    "27": "CAACAgQAAxkBAAEPnmxo-TgIVFkyEf19Je-9awnfcm0HNAACoBcAAjK0gVFqoRMWJ0V2AjYE",
                    "28": "CAACAgQAAxkBAAEPnm1o-TgIEaTKLI1hP_FD5NoPNMoRrQAC8xUAAjTtgVFbDjOI7hjkyDYE",
                    "29": "CAACAgQAAxkBAAEPnm5o-TgIrfmuYVnfQps2DUcaDPJtYAACehcAAgL2eFFyvPJETxqlljYE",
                    "30": "CAACAgQAAxkBAAEPnm9o-TgIumJ40cFAJ7xQVVJu8yioGQACrBUAAqMsgVEiKujpQgVfJDYE",
                    "31": "CAACAgQAAxkBAAEPnndo-ThreZX7kJJpPO5idNcOeIWZpQACDhsAArW6gFENcv6I97q9xDYE",
                    "32": "CAACAgQAAxkBAAEPni9o-Ssij-qcC2-pLlmtFrUQr5AUgQACWxcAAsmneVGFqOYh9w81_TYE",
                    "33": "CAACAgQAAxkBAAEPnnto-Thsmi6zNRuaeXnBFpXJ-w2JnQACjBkAAo3JeFEYXOtgIzFLjTYE",
                    "34": "CAACAgQAAxkBAAEPnnlo-ThrHvyKnt3O8UiLblKzGgWqzQACWBYAAvn3gVElI6JyUvoRYzYE",
                    "35": "CAACAgQAAxkBAAEPnn9o-Tij1sCB1_UVenRU6QvBnfFKagACkhYAAsKTgFHHcm9rj3PDyDYE",
                    "36": "CAACAgQAAxkBAAEPnoBo-Tik1zRaZMCVCaOi9J1FtVvEiAACrBcAAtbQgVFt8Uw1gyn4MDYE"
                }
            }
            self.db.save_data()
        
        self.stickers = self.db.data['stickers']
        
        # Dictionary to store active Blackjack games: user_id -> BlackjackGame instance
        self.blackjack_sessions: Dict[int, BlackjackGame] = {}

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
        self.app.add_handler(CommandHandler("bet", self.bet_command))
        self.app.add_handler(CommandHandler("wager", self.bet_command))
        self.app.add_handler(CommandHandler("dice", self.dice_command))
        self.app.add_handler(CommandHandler("darts", self.darts_command))
        self.app.add_handler(CommandHandler("basketball", self.basketball_command))
        self.app.add_handler(CommandHandler("bball", self.basketball_command))
        self.app.add_handler(CommandHandler("soccer", self.soccer_command))
        self.app.add_handler(CommandHandler("football", self.soccer_command))
        self.app.add_handler(CommandHandler("bowling", self.bowling_command))
        self.app.add_handler(CommandHandler("predict", self.predict_command))
        self.app.add_handler(CommandHandler("coinflip", self.coinflip_command))
        self.app.add_handler(CommandHandler("flip", self.coinflip_command))
        self.app.add_handler(CommandHandler("roulette", self.roulette_command))
        self.app.add_handler(CommandHandler("blackjack", self.blackjack_command))
        self.app.add_handler(CommandHandler("bj", self.blackjack_command))
        self.app.add_handler(CommandHandler("tip", self.tip_command))
        self.app.add_handler(CommandHandler("deposit", self.deposit_command))
        self.app.add_handler(CommandHandler("withdraw", self.withdraw_command))
        self.app.add_handler(CommandHandler("matches", self.matches_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        self.app.add_handler(CommandHandler("savesticker", self.save_sticker_command))
        self.app.add_handler(CommandHandler("stickers", self.list_stickers_command))
        self.app.add_handler(CommandHandler("saveroulette", self.save_roulette_stickers_command))
        
        # Admin commands
        self.app.add_handler(CommandHandler("admin", self.admin_command))
        self.app.add_handler(CommandHandler("givebal", self.givebal_command))
        self.app.add_handler(CommandHandler("setbal", self.setbal_command))
        self.app.add_handler(CommandHandler("p", self.p_command))
        self.app.add_handler(CommandHandler("allusers", self.allusers_command))
        self.app.add_handler(CommandHandler("userinfo", self.userinfo_command))
        self.app.add_handler(CommandHandler("addadmin", self.addadmin_command))
        self.app.add_handler(CommandHandler("removeadmin", self.removeadmin_command))
        self.app.add_handler(CommandHandler("listadmins", self.listadmins_command))
        self.app.add_handler(CommandHandler("pendingdeposits", self.pending_deposits_command))
        self.app.add_handler(CommandHandler("approvedeposit", self.approve_deposit_command))
        self.app.add_handler(CommandHandler("pendingwithdraws", self.pending_withdraws_command))
        self.app.add_handler(CommandHandler("processwithdraw", self.process_withdraw_command))
        self.app.add_handler(CommandHandler("s", self.s_command))
        
        self.app.add_handler(MessageHandler(filters.Sticker.ALL, self.sticker_handler))
        self.app.add_handler(MessageHandler(filters.Dice.ALL, self.handle_emoji_response))
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
    
    async def s_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set the expiration time for bets (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /s [seconds]\nExample: /s 60")
            return
            
        try:
            seconds = int(context.args[0])
            if seconds < 10:
                await update.message.reply_text("❌ Minimum expiration time is 10 seconds.")
                return
            
            self.db.data['expiration_seconds'] = seconds
            self.db.save_data()
            await update.message.reply_text(f"✅ Expiration time set to {seconds} seconds.")
        except ValueError:
            await update.message.reply_text("❌ Invalid number of seconds.")

    async def check_expired_challenges(self, context: ContextTypes.DEFAULT_TYPE):
        """Check for challenges older than 5 minutes and handle refunds/forfeits"""
        try:
            current_time = datetime.now()
            expired_challenges = []
            
            expiration_limit = self.db.data.get('expiration_seconds', 300)
            
            for challenge_id, challenge in list(self.pending_pvp.items()):
                chat_id = challenge.get('chat_id')
                wager = challenge.get('wager', 0)
                
                # Generic V2 Timeout
                if challenge_id.startswith("v2_bot_") or challenge_id.startswith("v2_pvp_"):
                    emoji_wait = challenge.get('emoji_wait')
                    wait_started = None
                    if emoji_wait:
                        wait_started = datetime.fromisoformat(emoji_wait)
                    else:
                        created_at = challenge.get('created_at')
                        if created_at:
                            wait_started = datetime.fromisoformat(created_at)
                    
                    if wait_started:
                        time_diff = (current_time - wait_started).total_seconds()
                        # If the game has started (rolls > 0), give more time (15 mins)
                        limit = 900 if challenge.get('cur_rolls', 0) > 0 or challenge.get('p_pts', 0) > 0 or challenge.get('b_pts', 0) > 0 else expiration_limit
                        
                        if time_diff > limit:
                            expired_challenges.append(challenge_id)
                            if challenge_id.startswith("v2_bot_"):
                                pid = challenge['player']
                                # Bot game expiry: 
                                # If they are at the cashout stage, auto-cashout
                                if challenge.get('waiting_for_cashout'):
                                    cashout_val = self.calculate_cashout(challenge['p_pts'], challenge['b_pts'], challenge['pts'], challenge['wager'])
                                    user_data = self.db.get_user(pid)
                                    user_data['balance'] += cashout_val
                                    self.db.update_user(pid, user_data)
                                    self.db.update_house_balance(-(cashout_val - challenge['wager'])) # Adjust house balance correctly
                                    
                                    if chat_id:
                                        await context.bot.send_message(
                                            chat_id=chat_id, 
                                            text=f"⏰ @{user_data['username']} didn't pick an option. Auto-cashed out for ${cashout_val:.2f}."
                                        )
                                    expired_challenges.append(challenge_id)
                                    continue

                                # If no wager deducted (user never sent first emoji) -> just expire
                                # If wager was deducted -> check if bot responded
                                # Actually, in bot game, if user sent some but bot didn't finish, refund.
                                # But if user stopped sending halfway, they shouldn't get refund.
                                if challenge.get('wager_deducted'):
                                    # Current round rolls: challenge['cur_rolls']
                                    # If player hasn't finished the rolls for the CURRENT round
                                    if challenge.get('cur_rolls', 0) >= challenge.get('rolls', 0):
                                        # Player finished current round, but bot didn't respond (timeout)
                                        self.db.update_user(pid, {'balance': self.db.get_user(pid)['balance'] + wager})
                                        if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Rukia timed out. ${wager:.2f} refunded.")
                                    else:
                                        # Player didn't finish their rolls for this round
                                        if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Game expired.")
                                else:
                                    if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Game expired.")
                            else:
                                p1, p2 = challenge['challenger'], challenge['opponent']
                                # PvP Expiry:
                                # Only refund if the OTHER player is the one who didn't roll.
                                # If P1 rolled and P2 didn't, refund P1.
                                # If P1 didn't roll (even if P2 was ready), no refund for P1.
                                
                                # Current turn status
                                if challenge.get('waiting_p1'):
                                    # P1 didn't roll -> P1 forfeits, P2 (if joined/deducted) gets refund
                                    if challenge.get('p2_deducted'):
                                        self.db.update_user(p2, {'balance': self.db.get_user(p2)['balance'] + wager})
                                    if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Series expired. @{self.db.get_user(p1)['username']} abandoned.")
                                elif challenge.get('waiting_p2'):
                                    # P2 didn't roll -> P2 forfeits, P1 gets refund
                                    if challenge.get('p1_deducted'):
                                        self.db.update_user(p1, {'balance': self.db.get_user(p1)['balance'] + wager})
                                    if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Series expired. @{self.db.get_user(p2)['username']} abandoned.")
                                else:
                                    # Generic cleanup
                                    if chat_id: await context.bot.send_message(chat_id=chat_id, text=f"⏰ Series expired.")
                    continue
                if 'created_at' in challenge and challenge.get('opponent') is None:
                    created_at = datetime.fromisoformat(challenge['created_at'])
                    time_diff = (current_time - created_at).total_seconds()
                    
                    if time_diff > expiration_limit:
                        expired_challenges.append(challenge_id)
                        
                        # Refund the challenger
                        challenger_id = challenge['challenger']
                        # challenger_data = self.db.get_user(challenger_id) # Removing duplicate read
                        
                        self.db.update_user(challenger_id, {
                            'balance': self.db.get_user(challenger_id)['balance'] + wager
                        })
                        
                        if chat_id:
                            try:
                                await self.app.bot.send_message(
                                    chat_id=chat_id,
                                    text=f"⏰ Challenge expired after 5 minutes. ${wager:.2f} has been refunded to @{challenger_data['username']}.",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"Failed to send expiration message: {e}")
                
                # Case 2: Waiting for challenger emoji - challenger forfeits, acceptor gets refund
                elif challenge.get('waiting_for_challenger_emoji') and 'emoji_wait_started' in challenge:
                    wait_started = datetime.fromisoformat(challenge['emoji_wait_started'])
                    time_diff = (current_time - wait_started).total_seconds()
                    
                    if time_diff > expiration_limit:
                        expired_challenges.append(challenge_id)
                        
                        challenger_id = challenge['challenger']
                        acceptor_id = challenge['opponent']
                        challenger_data = self.db.get_user(challenger_id)
                        acceptor_data = self.db.get_user(acceptor_id)
                        
                        # Challenger forfeits to house
                        self.db.update_house_balance(wager)
                        
                        # Acceptor gets refunded
                        self.db.update_user(acceptor_id, {
                            'balance': acceptor_data['balance'] + wager
                        })
                        
                        if chat_id:
                            try:
                                await self.app.bot.send_message(
                                    chat_id=chat_id,
                                    text=f"⏰ @{challenger_data['username']} didn't send their emoji within 5 minutes and forfeited ${wager:.2f} to the house. @{acceptor_data['username']} has been refunded ${wager:.2f}.",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"Failed to send forfeit message: {e}")
                
                # Case 3: Waiting for opponent/player emoji - opponent forfeits, challenger/bot gets paid
                elif challenge.get('waiting_for_emoji') and 'emoji_wait_started' in challenge:
                    wait_started = datetime.fromisoformat(challenge['emoji_wait_started'])
                    time_diff = (current_time - wait_started).total_seconds()
                    
                    if time_diff > expiration_limit:
                        expired_challenges.append(challenge_id)
                        
                        # Check if PvP or bot vs player
                        if challenge.get('opponent'):
                            # PvP case: opponent forfeits, challenger gets refund
                            challenger_id = challenge['challenger']
                            opponent_id = challenge['opponent']
                            challenger_data = self.db.get_user(challenger_id)
                            opponent_data = self.db.get_user(opponent_id)
                            
                            # Opponent forfeits to house
                            self.db.update_house_balance(wager)
                            
                            # Challenger gets refunded
                            self.db.update_user(challenger_id, {
                                'balance': challenger_data['balance'] + wager
                            })
                            
                            if chat_id:
                                try:
                                    await self.app.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"⏰ @{opponent_data['username']} didn't send their emoji within 5 minutes and forfeited ${wager:.2f} to the house. @{challenger_data['username']} has been refunded ${wager:.2f}.",
                                        parse_mode="Markdown"
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to send forfeit message: {e}")
                        
                        elif challenge.get('player'):
                            # Bot vs player: player forfeits, house keeps money
                            player_id = challenge['player']
                            player_data = self.db.get_user(player_id)
                            
                            # Player forfeits to house (money already taken)
                            self.db.update_house_balance(wager)
                            
                            if chat_id:
                                try:
                                    await self.app.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"⏰ @{player_data['username']} didn't send their emoji within 5 minutes and forfeited ${wager:.2f} to the house.",
                                        parse_mode="Markdown"
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to send forfeit message: {e}")
            
            # Remove expired challenges
            for challenge_id in expired_challenges:
                del self.pending_pvp[challenge_id]
            
            if expired_challenges:
                self.db.data['pending_pvp'] = self.pending_pvp
                self.db.save_data()
                logger.info(f"Expired/forfeited {len(expired_challenges)} challenge(s)")
                
        except Exception as e:
            logger.error(f"Error checking expired challenges: {e}")
    
    # --- COMMAND HANDLERS ---
    
    def ensure_user_registered(self, update: Update) -> Dict[str, Any]:
        """Ensure user exists and has username set"""
        user = update.effective_user
        user_data = self.db.get_user(user.id)
        
        # Update username if it has changed or is not set
        if user.username and user_data.get("username") != user.username:
            self.db.update_user(user.id, {"username": user.username, "user_id": user.id})
            user_data = self.db.get_user(user.id)
        
        return user_data
    
    async def send_with_buttons(self, chat_id: int, text: str, keyboard: InlineKeyboardMarkup, user_id: int, parse_mode: str = "Markdown"):
        """Send a message with buttons and register ownership"""
        sent_message = await self.app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=parse_mode
        )
        self.button_ownership[(chat_id, sent_message.message_id)] = user_id
        return sent_message
    
    def is_admin(self, user_id: int) -> bool:
        """Check if a user is an admin (environment or dynamic)"""
        return user_id in self.env_admin_ids or user_id in self.dynamic_admin_ids
    
    def find_user_by_username_or_id(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Find a user by username (@username) or user ID"""
        # Remove @ if present
        if identifier.startswith('@'):
            username = identifier[1:]
            # Search by username
            for user_data in self.db.data['users'].values():
                if user_data.get('username', '').lower() == username.lower():
                    return user_data
            return None
        else:
            # Try to parse as user ID
            try:
                user_id = int(identifier)
                return self.db.get_user(user_id)
            except ValueError:
                return None
    
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
        
        welcome_text = f"""
🎰 <b>Antaria Casino</b>
💰 Balance: <b>${user_data['balance']:,.2f}</b>

<b>Games:</b>
/dice 10 - Dice 🎲
/darts 10 - Darts 🎯
/basketball 10 - Basketball 🏀
/soccer 10 - Soccer ⚽
/bowling 10 - Bowling 🎳
/flip 10 heads - Coin Flip 🪙
/predict 10 #6 - Predict 🎱

<b>Menu:</b>
/bal - Balance
/bonus - Get bonus
/stats - Your stats
"""
        await update.message.reply_text(welcome_text, parse_mode="HTML")
    
    async def get_live_rate(self, crypto_id: str) -> float:
        """Fetch live crypto rate from CoinGecko with caching."""
        now = datetime.now()
        cache_key = f"rate_{crypto_id}"
        
        # Check cache (10 minutes)
        if hasattr(self, '_rate_cache') and cache_key in self._rate_cache:
            rate, expiry = self._rate_cache[cache_key]
            if now < expiry:
                return rate
        else:
            self._rate_cache = {}

        try:
            import requests
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_id}&vs_currencies=usd"
            response = requests.get(url, timeout=5)
            data = response.json()
            rate = float(data[crypto_id]['usd'])
            
            # Update cache
            self._rate_cache[cache_key] = (rate, now + timedelta(minutes=10))
            return rate
        except Exception as e:
            logger.error(f"Error fetching {crypto_id} rate: {e}")
            # Fallback to env or defaults
            if crypto_id == "monero":
                return float(os.getenv('XMR_USD_RATE', '160.0'))
            elif crypto_id == "litecoin":
                return float(os.getenv('LTC_USD_RATE', '100.0'))
            return 100.0

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show balance with deposit/withdraw buttons"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        # Fetch live XMR rate
        xmr_usd_rate = await self.get_live_rate("monero")
        xmr_balance = user_data['balance'] / xmr_usd_rate
        
        balance_text = f"Your balance: <b>${user_data['balance']:,.2f}</b> ({xmr_balance:.5f} XMR)"
        
        keyboard = [
            [InlineKeyboardButton("💳 Deposit", callback_data="deposit_mock"),
             InlineKeyboardButton("💸 Withdraw", callback_data="withdraw_mock")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            balance_text, 
            reply_markup=reply_markup, 
            parse_mode="HTML",
            reply_to_message_id=update.message.message_id
        )
    
    async def bonus_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bonus status"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        wagered_since_withdrawal = user_data.get('wagered_since_last_withdrawal', 0)
        bonus_amount = wagered_since_withdrawal * 0.01
        
        if bonus_amount < 0.01:
            await update.message.reply_text("🎁 No bonus available yet\n\nPlay games to earn bonus!", parse_mode="Markdown")
            return
        
        bonus_text = f"🎁 **Bonus Available: ${bonus_amount:.2f}**\n\nClaim it below!"
        
        keyboard = [[InlineKeyboardButton("💰 Claim Now", callback_data="claim_daily_bonus")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = await update.message.reply_text(bonus_text, reply_markup=reply_markup, parse_mode="Markdown")
        self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show player statistics"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        games_played = user_data.get('games_played', 0)
        games_won = user_data.get('games_won', 0)
        win_rate = (games_won / games_played * 100) if games_played > 0 else 0
        
        stats_text = f"""
📊 **Your Stats**

🎮 Games: {games_played} played, {games_won} won
📈 Win Rate: {win_rate:.0f}%
💵 Total Wagered: ${user_data.get('total_wagered', 0):.2f}
💰 Profit/Loss: ${user_data.get('total_pnl', 0):.2f}
🔥 Best Streak: {user_data.get('best_win_streak', 0)} wins
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
        
        leaderboard_text = f"🏆 **Leaderboard** ({page + 1}/{total_pages})\n\n"
        
        if not leaderboard:
            leaderboard_text += "No players yet"
        
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
👥 **Referral**

Link: `{referral_link}`

Referrals: {user_data.get('referral_count', 0)}
Earned: ${user_data.get('referral_earnings', 0):.2f}
Unclaimed: ${user_data.get('unclaimed_referral_earnings', 0):.2f}
"""
        
        keyboard = []
        if user_data.get('unclaimed_referral_earnings', 0) >= 0.01:
            keyboard.append([InlineKeyboardButton("💰 Claim Earnings", callback_data="claim_referral")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.message.reply_text(referral_text, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def housebal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show house balance"""
        house_balance = self.db.get_house_balance()
        
        housebal_text = f"🏦 House: ${house_balance:.2f}"
        
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
            await update.message.reply_text("📜 No history yet")
            return
        
        history_text = "🎮 **History** (Last 15)\n\n"
        
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
                    history_text += f"   You: {player_roll} | Rukia: {bot_roll} | {time_str}\n\n"
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
    
    async def bet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, amount: Optional[float] = None):
        """Unified betting command with game selection menu."""
        user_id = update.effective_user.id
        self.db.get_user(user_id) # Ensure registered
        
        if amount is None:
            if not context.args:
                await update.effective_message.reply_text("Usage: /bet <amount|all>")
                return
                
            amount_str = context.args[0].lower()
            user_data = self.db.get_user(user_id)
            
            if amount_str == 'all':
                amount = user_data['balance']
            else:
                try:
                    # Remove common currency symbols and commas
                    clean_str = amount_str.replace('$', '').replace(',', '')
                    # If there are any letters (excluding 'all' which is handled above), ignore the message
                    if any(c.isalpha() for c in clean_str):
                        return
                    amount = float(clean_str)
                except ValueError:
                    # Silently ignore invalid numeric formats with letters
                    return
        
        user_data = self.db.get_user(user_id)
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00")
            return
            
        if amount > user_data['balance']:
            await update.effective_message.reply_text(f"❌ Insufficient balance! (${user_data['balance']:.2f})")
            return

        keyboard = [
            [InlineKeyboardButton("🎲 Dice", callback_data=f"setup_mode_dice_{amount:.2f}"),
             InlineKeyboardButton("🎱 Predict", callback_data=f"setup_mode_predict_{amount:.2f}")],
            [InlineKeyboardButton("🎯 Darts", callback_data=f"setup_mode_darts_{amount:.2f}"),
             InlineKeyboardButton("🏀 Basketball", callback_data=f"setup_mode_basketball_{amount:.2f}")],
            [InlineKeyboardButton("⚽ Soccer", callback_data=f"setup_mode_soccer_{amount:.2f}"),
             InlineKeyboardButton("🎳 Bowling", callback_data=f"setup_mode_bowling_{amount:.2f}")],
            [InlineKeyboardButton("🪙 CoinFlip", callback_data=f"flip_bot_{amount:.2f}"),
             InlineKeyboardButton("🃏 Blackjack", callback_data=f"bj_bot_{amount:.2f}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"💰 **Bet: ${amount:.2f}**\nSelect a game to play:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await self.send_with_buttons(
                update.effective_chat.id,
                f"💰 **Bet: ${amount:.2f}**\nSelect a game to play:",
                reply_markup,
                user_id
            )

    def _get_next_game_mode(self, current: str) -> str:
        modes = ["dice", "darts", "basketball", "bowling", "soccer"]
        try:
            idx = modes.index(current)
            return modes[(idx + 1) % len(modes)]
        except:
            return "dice"

    def _get_prev_game_mode(self, current: str) -> str:
        modes = ["dice", "darts", "basketball", "bowling", "soccer"]
        try:
            idx = modes.index(current)
            return modes[(idx - 1) % len(modes)]
        except:
            return "dice"

    def _calculate_emoji_multiplier(self, rolls: int, pts: int) -> float:
        """
        Calculate multiplier for emoji games.
        Since it's a 50/50 chance for each player overall regardless of series length,
        the multiplier is set to a constant 1.95x.
        """
        return 1.95

    async def _show_emoji_game_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, game_mode: str, step: str = "mode", params: Dict = None):
        """Display the setup menu for emoji games (mode, rolls, points)"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        params = params or {}
        
        emoji_map = {
            "dice": "🎲",
            "darts": "🎯",
            "basketball": "🏀",
            "soccer": "⚽",
            "bowling": "🎳"
        }
        current_emoji = emoji_map.get(game_mode, "🎲")
        
        # Consistent multiplier for PvP/Bot series
        multiplier = 1.95
        
        # Check if we should skip to game start (last step completed)
        if step == "confirm":
            # Extract collected params
            mode = params.get('mode', 'normal')
            rolls = params.get('rolls', 1)
            pts = params.get('pts', 3)
            
            # Start game directly without extra bet menu
            if game_mode in ["dice", "basketball", "soccer", "darts", "bowling"]:
                # Always use v2_bot for consistent series play
                challenge_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
                self.pending_pvp[challenge_id] = {
                    "type": "series_bot",
                    "player": user_id,
                    "wager": wager,
                    "mode": mode,
                    "rolls": rolls,
                    "pts": pts,
                    "emoji": self.emoji_map.get(game_mode, "🎲"),
                    "game_mode": game_mode,
                    "player_points": 0,
                    "bot_points": 0,
                    "player_rolls": [],
                    "bot_rolls": [],
                    "waiting_for_emoji": True,
                    "chat_id": chat_id,
                    "wager_deducted": True
                }
                
                user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
                
                text = (
                    f"{current_emoji} vs 🤖\n"
                    f"Target: {pts}\n"
                    f"Mode: {'Normal' if mode == 'normal' else 'Crazy'}\n\n"
                    f"👉 Send your {rolls} {current_emoji} now!"
                )
                
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                return
            # Add other games as needed
            return

        keyboard = []
        
        if step == "mode":
            text = (
                f"{current_emoji} <b>{game_mode.replace('_', ' ').capitalize()}</b>\n\n"
                f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
                f"Multiplier: <b>{multiplier:.2f}x</b>\n\n"
                f"Choose your game mode:"
            )
            keyboard.append([
                InlineKeyboardButton("Normal (Highest)", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_rolls_normal"),
                InlineKeyboardButton("Crazy (Lowest)", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_rolls_inverted")
            ])
        elif step == "rolls":
            mode = params.get("mode")
            text = (
                f"{current_emoji} <b>{game_mode.replace('_', ' ').capitalize()}</b>\n\n"
                f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
                f"Multiplier: <b>{multiplier:.2f}x</b>\n\n"
                f"Choose the amount of rolls:"
            )
            keyboard.append([
                InlineKeyboardButton("1 Roll", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_points_1_{mode}"),
                InlineKeyboardButton("2 Rolls", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_points_2_{mode}")
            ])
        elif step == "points":
            mode = params.get("mode")
            rolls = params.get("rolls")
            text = (
                f"{current_emoji} <b>{game_mode.replace('_', ' ').capitalize()}</b>\n\n"
                f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
                f"Multiplier: <b>{multiplier:.2f}x</b>\n\n"
                f"Choose the amount of points:"
            )
            keyboard.append([
                InlineKeyboardButton("1 Pt", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_final_1_{rolls}_{mode}"),
                InlineKeyboardButton("2 Pts", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_final_2_{rolls}_{mode}"),
                InlineKeyboardButton("3 Pts", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_final_3_{rolls}_{mode}")
            ])
        
        # Opponent selection row (Only in groups)
        is_private = update.effective_chat.type == "private"
        if not is_private and step == "final":
            keyboard.append([
                InlineKeyboardButton("🤖 vs Bot" + (" ✅" if not params or params.get('opponent') == 'bot' else ""), callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_final_{pts}_{rolls}_{mode}_bot"),
                InlineKeyboardButton("👥 vs Player" + (" ✅" if params and params.get('opponent') == 'player' else ""), callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_final_{pts}_{rolls}_{mode}_player")
            ])
        
        # Bet control row
        # Ensure wager stays at least 1.0
        half_wager = max(1.0, wager / 2)
        double_wager = wager * 2
        
        # Build callback suffix for preserving settings during half/double
        suffix = ""
        if step == "rolls":
            suffix = f"_{params.get('mode', 'normal')}"
        elif step == "points":
            suffix = f"_{params.get('rolls', 1)}_{params.get('mode', 'normal')}"
        elif step == "final":
            suffix = f"_{params.get('pts', 3)}_{params.get('rolls', 1)}_{params.get('mode', 'normal')}"
            if params.get('opponent'):
                suffix += f"_{params['opponent']}"

        keyboard.append([
            InlineKeyboardButton("Half Bet", callback_data=f"emoji_setup_{game_mode}_{half_wager:.2f}_{step}{suffix}"),
            InlineKeyboardButton(f"Bet: ${wager:,.2f}", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_{step}{suffix}"),
            InlineKeyboardButton("Double Bet", callback_data=f"emoji_setup_{game_mode}_{double_wager:.2f}_{step}{suffix}")
        ])
        
        # Ensure we don't have vs Bot/Player in DMs
        if is_private:
            # Re-filter keyboard to remove any opponent selection buttons that might have been added
            keyboard = [row for row in keyboard if not any(btn.text and ("vs Bot" in btn.text or "vs Player" in btn.text) for btn in row)]
            if params:
                params['opponent'] = 'bot'

        if step in ["mode", "rolls", "points"]:
            # Custom title based on current step
            step_titles = {"mode": "Game Mode", "rolls": "Rolls", "points": "Target Score"}
            current_step_title = step_titles.get(step, step.capitalize())
            
            # Prepare summary of selected settings
            mode_val = params.get('mode', 'normal')
            mode_display = "Normal" if mode_val == 'normal' else "Crazy"
            rolls_val = params.get('rolls')
            pts_val = params.get('pts')
            
            # Conditionally build the setup summary
            setup_details = ""
            if step != "mode":
                setup_details += f"• Mode: {mode_display}\n"
            if rolls_val is not None:
                setup_details += f"• Rolls: {rolls_val}\n"
            if pts_val is not None:
                setup_details += f"• Target Score: {pts_val}\n"
            
            setup_details += f"• Bet: ${wager:,.2f}\n\n"

            text = (
                f"{current_emoji} <b>{game_mode.replace('_', ' ').title()}</b>\n\n"
                f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
                f"Multiplier: <b>{multiplier:.2f}x</b>\n\n"
                f"<b>Current Setup:</b>\n"
                f"{setup_details}"
                f"Choose your {current_step_title.lower()}:"
            )
            
            # Opponent display (only in groups)
            if not is_private:
                text += f"\n\nOpponent: {params.get('opponent', 'vs Bot') if params else 'vs Bot'}"
            
        # Navigation row
        next_game = self._get_next_game_mode(game_mode)
        prev_game = self._get_prev_game_mode(game_mode)
        
        # Consistent emoji mapping
        emoji_map = {
            "dice": "🎲",
            "basketball": "🏀",
            "soccer": "⚽",
            "darts": "🎯",
            "bowling": "🎳",
            "coinflip": "🪙"
        }
        current_emoji = emoji_map.get(game_mode, "🎲")
        
        keyboard.append([
            InlineKeyboardButton("⬅️", callback_data=f"emoji_setup_{prev_game}_{wager:.2f}_{step}{suffix}"),
            InlineKeyboardButton(f"Mode: {current_emoji}", callback_data="none"),
            InlineKeyboardButton("➡️", callback_data=f"emoji_setup_{next_game}_{wager:.2f}_{step}{suffix}")
        ])
            
        # Back button
        back_button = None
        if step == "mode":
            back_button = InlineKeyboardButton("⬅️ Cancel", callback_data="setup_cancel")
        elif step == "rolls":
            back_button = InlineKeyboardButton("⬅️ Back", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_mode")
        elif step == "points":
            back_button = InlineKeyboardButton("⬅️ Back", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_rolls_{params.get('mode', 'normal')}")
        
        if back_button:
            keyboard.append([back_button])

        if step == "final":
            mode = params.get("mode")
            rolls = params.get("rolls")
            pts = params.get("pts")
            opponent = params.get("opponent", "bot")
            
            mode_display = "Normal" if mode == "normal" else "Crazy"
            opponent_display = "vs Bot" if opponent == "bot" else "vs Player"
            
            text = (
                f"{current_emoji} <b>{game_mode.replace('_', ' ').title()}</b>\n\n"
                f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
                f"Multiplier: <b>{self._calculate_emoji_multiplier(rolls, pts):.2f}x</b>\n\n"
                f"<b>Game Details:</b>\n"
                f"• Mode: <b>{mode_display}</b>\n"
                f"• Rolls: <b>{rolls}</b>\n"
                f"• Target Score: <b>{pts}</b>\n"
                f"• Bet: <b>${wager:,.2f}</b>\n"
            )
            
            is_private = update.effective_chat.type == "private"
            if not is_private:
                text += f"Opponent: <b>{opponent_display}</b>\n"
            
            text += f"\nReady to start?"
            
            # Mode selection row
            next_game = self._get_next_game_mode(game_mode)
            prev_game = self._get_prev_game_mode(game_mode)
            keyboard.append([
                InlineKeyboardButton("⬅️", callback_data=f"emoji_setup_{prev_game}_{wager:.2f}_{step}{suffix}"),
                InlineKeyboardButton(f"Mode: {current_emoji}", callback_data="none"),
                InlineKeyboardButton("➡️", callback_data=f"emoji_setup_{next_game}_{wager:.2f}_{step}{suffix}")
            ])

        # Action row
        pts_val = params.get("pts") if params else None
        rolls_val = params.get("rolls") if params else None
        mode_val = params.get("mode") if params else "normal"
        opponent_val = params.get("opponent", "bot") if params else "bot"
        
        start_callback = f"emoji_setup_{game_mode}_{wager:.2f}_start_{pts_val}_{rolls_val}_{mode_val}" if (opponent_val == "bot" or is_private) else f"v2_pvp_{game_mode}_{wager:.2f}_{rolls_val}_{mode_val}_{pts_val}"
        
        if step == "final":
            back_btn = InlineKeyboardButton("⬅️ Back", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_points_{params.get('rolls', 1)}_{params.get('mode', 'normal')}")
            keyboard.append([
                back_btn,
                InlineKeyboardButton("✅ Start", callback_data=start_callback)
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            sent_msg = await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            # Store message ID if this is a bot game so we can track replies
            if opponent_val == "bot":
                # Find the challenge and update it
                for cid, challenge in self.pending_pvp.items():
                    if cid.startswith("v2_bot_") and challenge.get('player') == update.effective_user.id:
                         challenge['msg_id'] = sent_msg.message_id
                         break
        else:
            sent_msg = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
            if opponent_val == "bot":
                for cid, challenge in self.pending_pvp.items():
                    if cid.startswith("v2_bot_") and challenge.get('player') == update.effective_user.id:
                         challenge['msg_id'] = sent_msg.message_id
                         break
        
        self.db.update_pending_pvp(self.pending_pvp)

    async def _show_game_prediction_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, game_mode: str = "dice"):
        """Display the game prediction menu as shown in the screenshot"""
        # Route to multi-step setup for emoji games
        if game_mode in ["dice", "basketball", "soccer", "darts", "bowling"]:
            await self._show_emoji_game_setup(update, context, wager, game_mode)
            return

        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        # Ensure wager is at least 1.0
        wager = max(1.0, wager)
        
        # Consistent multiplier for prediction games
        multiplier = 1.95
        
        emoji_map = {
            "dice": "🎲",
            "basketball": "🏀",
            "soccer": "⚽",
            "darts": "🎯",
            "bowling": "🎳",
            "coinflip": "🪙"
        }
        
        modes = ["dice", "darts", "basketball", "bowling", "soccer", "coinflip"]
        current_idx = modes.index(game_mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        prev_mode = modes[(current_idx - 1) % len(modes)]
        
        current_emoji = emoji_map.get(game_mode, "🎲")
        
        # Get current selections
        selections = getattr(self, "_predict_selections", {}).get(user_id, set())
        if not isinstance(selections, set):
            selections = set()
            
        selection_list = sorted(list(selections))
        
        # Calculate multiplier
        if game_mode == "coinflip":
            multiplier = 1.95
        else:
            if selections:
                if game_mode in ["dice", "darts", "bowling"]:
                    total_outcomes = 6
                elif game_mode in ["basketball", "soccer"]:
                    total_outcomes = 3
                else:
                    total_outcomes = 6
                multiplier = round((total_outcomes / len(selections)) * 0.95, 2)
            else:
                multiplier = 0.00

        text = (
            f"{current_emoji} <b>{game_mode.replace('_', ' ').capitalize()}</b>\n\n"
            f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
            f"Multiplier: <b>{multiplier:.2f}x</b>\n\n"
            f"Make your selection:"
        )
        
        keyboard = []
        
        # Prediction buttons
        is_private = update.effective_chat.type == "private"
        
        if game_mode in ["dice", "darts", "bowling"]:
            row1, row2 = [], []
            for i in range(1, 7):
                label = f"{i} ✅" if str(i) in selections else str(i)
                btn = InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{i}_{game_mode}")
                if i <= 3: row1.append(btn)
                else: row2.append(btn)
            keyboard.append(row1)
            keyboard.append(row2)
        elif game_mode == "basketball":
            row = []
            for opt in ["score", "miss", "stuck"]:
                label = f"{opt.capitalize()} ✅" if opt in selections else opt.capitalize()
                row.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{opt}_{game_mode}"))
            keyboard.append(row)
        elif game_mode == "soccer":
            row = []
            for opt in ["goal", "miss", "bar"]:
                label = f"{opt.capitalize()} ✅" if opt in selections else opt.capitalize()
                row.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{opt}_{game_mode}"))
            keyboard.append(row)
        elif game_mode == "coinflip":
            row = []
            for opt in ["heads", "tails"]:
                label = f"{opt.capitalize()} ✅" if opt in selections else opt.capitalize()
                row.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{opt}_{game_mode}"))
            keyboard.append(row)

        # VS Player / VS Bot buttons (Only in groups)
        if not is_private and game_mode in ["dice", "darts", "basketball", "soccer", "bowling"]:
            keyboard.append([
                InlineKeyboardButton("🆚 Player", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_mode"),
                InlineKeyboardButton("🤖 Bot", callback_data=f"emoji_setup_{game_mode}_{wager:.2f}_start_1_1_normal")
            ])
        
        # Bet adjustment row
        keyboard.append([
            InlineKeyboardButton("½", callback_data=f"setup_bet_half_{wager:.2f}_{game_mode}"),
            InlineKeyboardButton(f"Bet: ${wager:.2f}", callback_data="none"),
            InlineKeyboardButton("2x", callback_data=f"setup_bet_double_{wager:.2f}_{game_mode}")
        ])
        
        # Navigation row
        keyboard.append([
            InlineKeyboardButton("⬅️", callback_data=f"predict_menu_{wager:.2f}_{prev_mode}"),
            InlineKeyboardButton(f"Mode: {current_emoji}", callback_data=f"setup_mode_predict_{wager:.2f}_{game_mode}"),
            InlineKeyboardButton("➡️", callback_data=f"predict_menu_{wager:.2f}_{next_mode}")
        ])
        
        # Action row
        keyboard.append([
            InlineKeyboardButton("⬅️ Back", callback_data="main_menu"),
            InlineKeyboardButton("✅ Start", callback_data=f"predict_start_{wager:.2f}_{game_mode}")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            # Always reply to the command message
            sent_msg = await update.message.reply_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode="HTML",
                reply_to_message_id=update.message.message_id
            )
            self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id

    async def dice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play dice game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass
        
        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "dice")

    async def darts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play darts game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "darts")

    async def basketball_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play basketball game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "basketball")

    async def soccer_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play soccer game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "soccer")

    async def bowling_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play bowling game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "bowling")

    async def coinflip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play coinflip game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass
        await self._show_game_prediction_menu(update, context, amount, "coinflip")

    async def _setup_predict_interface(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, game_mode: str = "dice"):
        """Display the prediction interface as shown in the screenshot"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        
        emoji_map = {
            "dice": "🎲",
            "basketball": "🏀",
            "soccer": "⚽",
            "darts": "🎯",
            "bowling": "🎳"
        }
        
        modes = ["dice", "basketball", "soccer", "darts", "bowling"]
        current_idx = modes.index(game_mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        prev_mode = modes[(current_idx - 1) % len(modes)]
        
        current_emoji = emoji_map.get(game_mode, "🎲")
        
        # Get current selections
        selections = getattr(self, "_predict_selections", {}).get(user_id, set())
        if not isinstance(selections, set):
            selections = {str(selections)} if selections != "None" else set()
            
        selection_list = sorted(list(selections))
        selection_text = f"Selected: <b>{', '.join([s.capitalize() for p in selection_list])}</b>" if selections else "Selected: <b>None</b>"
        
        if selections:
            multiplier = round(6.0 / len(selections), 2)
            multiplier_text = f"Multiplier: <b>{multiplier:.2f}x</b>"
        else:
            multiplier_text = "Multiplier: <b>Choose your prediction</b>"

        text = (
            f"{current_emoji} <b>{game_mode.replace('_', ' ').capitalize()} Prediction</b>\n\n"
            f"Your balance: <b>${user_data['balance']:,.2f}</b>\n"
            f"{multiplier_text}\n\n"
            f"Make your prediction:"
        )
        
        # Define prediction buttons based on mode
        if game_mode == "dice" or game_mode == "darts" or game_mode == "bowling":
            prediction_buttons = []
            for i in range(1, 7):
                label = f"{i} ✅" if str(i) in selections else str(i)
                prediction_buttons.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{i}_{game_mode}"))
            prediction_rows = [prediction_buttons[:3], prediction_buttons[3:]]
        elif game_mode == "basketball":
            options = ["score", "miss", "stuck"]
            prediction_buttons = []
            for opt in options:
                label = f"{opt.capitalize()} ✅" if opt in selections else opt.capitalize()
                prediction_buttons.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{opt}_{game_mode}"))
            prediction_rows = [prediction_buttons]
        elif game_mode == "soccer":
            options = ["goal", "miss", "bar"]
            prediction_buttons = []
            for opt in options:
                label = f"{opt.capitalize()} ✅" if opt in selections else opt.capitalize()
                prediction_buttons.append(InlineKeyboardButton(label, callback_data=f"setup_predict_select_{wager:.2f}_{opt}_{game_mode}"))
            prediction_rows = [prediction_buttons]

        keyboard = []
        keyboard.extend(prediction_rows)
        keyboard.extend([
            [InlineKeyboardButton("Half Bet", callback_data=f"setup_mode_predict_{max(1.0, wager/2):.2f}_{game_mode}"),
             InlineKeyboardButton(f"Bet: ${wager:,.2f}", callback_data="none"),
             InlineKeyboardButton("Double Bet", callback_data=f"setup_mode_predict_{wager*2:.2f}_{game_mode}")],
            [InlineKeyboardButton("⬅️", callback_data=f"setup_mode_predict_{wager:.2f}_{prev_mode}"),
             InlineKeyboardButton(f"Mode: {current_emoji}", callback_data="none"),
             InlineKeyboardButton("➡️", callback_data=f"setup_mode_predict_{wager:.2f}_{next_mode}")],
            [InlineKeyboardButton("⬅️ Back", callback_data=f"setup_bet_back_{wager:.2f}"),
             InlineKeyboardButton("✅ Start", callback_data=f"predict_start_{wager:.2f}_{game_mode}")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    
    async def darts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play darts game setup"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text("Usage: `/darts <amount|all>`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Min: $0.01")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs emojigamblebot", callback_data=f"darts_bot_{wager:.2f}")],
            [InlineKeyboardButton("👥 Create PvP Challenge", callback_data=f"darts_player_open_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = await update.message.reply_text(
            f"🎯 **Darts Game**\n\nWager: ${wager:.2f}\n\nChoose your opponent:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
    
    async def basketball_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play basketball game setup"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text("Usage: `/basketball <amount|all>`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Min: $0.01")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        keyboard = [
            [InlineKeyboardButton("🤖 Play vs emojigamblebot", callback_data=f"basketball_bot_{wager:.2f}")],
            [InlineKeyboardButton("👥 Create PvP Challenge", callback_data=f"basketball_player_open_{wager:.2f}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = await update.message.reply_text(
            f"🏀 **Basketball Game**\n\nWager: ${wager:.2f}\n\nChoose your opponent:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
    
    async def bet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, amount: Optional[float] = None):
        """Unified betting command with game selection menu."""
        user_id = update.effective_user.id
        self.db.get_user(user_id) # Ensure registered
        
        if amount is None:
            if not context.args:
                await update.effective_message.reply_text("Usage: /bet <amount|all>")
                return
                
            amount_str = context.args[0].lower()
            user_data = self.db.get_user(user_id)
            
            if amount_str == 'all':
                amount = user_data['balance']
            else:
                try:
                    # Remove common currency symbols and commas
                    clean_str = amount_str.replace('$', '').replace(',', '')
                    # If there are any letters (excluding 'all' which is handled above), ignore the message
                    if any(c.isalpha() for c in clean_str):
                        return
                    amount = float(clean_str)
                except ValueError:
                    # Silently ignore invalid numeric formats with letters
                    return
        
        user_data = self.db.get_user(user_id)
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00")
            return
            
        if amount > user_data['balance']:
            await update.effective_message.reply_text(f"❌ Insufficient balance! (${user_data['balance']:.2f})")
            return

        keyboard = [
            [InlineKeyboardButton("🎲 Dice", callback_data=f"setup_mode_dice_{amount:.2f}"),
             InlineKeyboardButton("🎱 Predict", callback_data=f"setup_mode_predict_{amount:.2f}")],
            [InlineKeyboardButton("🎯 Darts", callback_data=f"setup_mode_darts_{amount:.2f}"),
             InlineKeyboardButton("🏀 Basketball", callback_data=f"setup_mode_basketball_{amount:.2f}")],
            [InlineKeyboardButton("⚽ Soccer", callback_data=f"setup_mode_soccer_{amount:.2f}"),
             InlineKeyboardButton("🎳 Bowling", callback_data=f"setup_mode_bowling_{amount:.2f}")],
            [InlineKeyboardButton("🪙 CoinFlip", callback_data=f"flip_bot_{amount:.2f}"),
             InlineKeyboardButton("🃏 Blackjack", callback_data=f"bj_bot_{amount:.2f}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"💰 **Bet: ${amount:.2f}**\nSelect a game to play:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await self.send_with_buttons(
                update.effective_chat.id,
                f"💰 **Bet: ${amount:.2f}**\nSelect a game to play:",
                reply_markup,
                user_id
            )

    async def dice_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play dice game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass
        
        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "dice")

    async def darts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play darts game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "darts")

    async def basketball_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play basketball game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "basketball")

    async def soccer_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play soccer game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "soccer")

    async def bowling_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play bowling game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass

        # Ensure minimum bet
        if amount < 1.0:
            await update.effective_message.reply_text("❌ Minimum bet is $1.00", reply_to_message_id=update.effective_message.message_id)
            return

        await self._show_game_prediction_menu(update, context, amount, "bowling")

    async def _generic_emoji_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, game_name: str, emoji: str):
        """Generic emoji game setup with nested options"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text(f"Usage: `/{game_name} <amount|all>`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if any(c.isalpha() for c in arg):
                    return
                wager = round(float(arg), 2)
            except ValueError:
                return
        
        if wager < 1.0:
            await update.message.reply_text("❌ Minimum bet is $1.00")
            return
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return

        # Record game attempt
        # Removed redundant record_game on initiation to avoid double counting in matches list
        
        keyboard = [
            [InlineKeyboardButton("Normal", callback_data=f"setup_mode_normal_{game_name}_{wager:.2f}"),
             InlineKeyboardButton("Crazy", callback_data=f"setup_mode_crazy_{game_name}_{wager:.2f}")]
        ]
        await update.message.reply_text(
            f"{emoji} **{game_name.capitalize()} Game**\n\nWager: ${wager:.2f}\n\nChoose Mode:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    async def predict_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play dice predict game - predict what you'll roll with multiple choices"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/predict <amount|all> #<number1>,#<number2>...`\nExample: `/predict 5 #1,#3,#6`", parse_mode="HTML")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                wager = round(float(arg), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount", parse_mode="HTML")
                return
        
        if wager < 1.0:
            await update.message.reply_text("❌ Minimum bet is $1.00", parse_mode="HTML")
            return
            
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: <b>${user_data['balance']:,.2f}</b>", parse_mode="HTML")
            return

        # Parse predictions
        pred_arg = context.args[1]
        raw_predictions = [p.strip() for p in pred_arg.split(',')]
        predictions = set()
        
        for p in raw_predictions:
            if not p.startswith('#'):
                await update.message.reply_text(f"❌ Prediction {p} must start with #", parse_mode="HTML")
                return
            try:
                num = int(p[1:])
                if 1 <= num <= 6:
                    predictions.add(num)
                else:
                    await update.message.reply_text(f"❌ Number {p} must be between 1 and 6", parse_mode="HTML")
                    return
            except ValueError:
                await update.message.reply_text(f"❌ Invalid prediction: {p}", parse_mode="HTML")
                return

        if not predictions:
            await update.message.reply_text("❌ No valid predictions provided", parse_mode="HTML")
            return
            
        if len(predictions) > 5:
            await update.message.reply_text("❌ You can't predict all 6 numbers (or 5 for logic sanity)", parse_mode="HTML")
            return

        # Multiplier logic: 6 / number of choices
        multiplier = round(6.0 / len(predictions), 2)
        
        # Deduct wager
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        
        # Send the dice
        dice_message = await update.message.reply_dice(emoji="🎲")
        actual_roll = dice_message.dice.value
        
        await asyncio.sleep(4)
        
        if actual_roll in predictions:
            payout = wager * multiplier
            profit = payout - wager
            new_balance = user_data['balance'] + payout # User balance was already deducted
            
            self.db.update_user(user_id, {
                'balance': new_balance,
                'total_wagered': user_data['total_wagered'] + wager,
                'wagered_since_last_withdrawal': user_data.get('wagered_since_last_withdrawal', 0) + wager,
                'games_played': user_data['games_played'] + 1,
                'games_won': user_data['games_won'] + 1
            })
            self.db.update_house_balance(-profit)
            
            user_display = f"<b>{user_data.get('username', f'User{user_id}')}</b>"
            await update.message.reply_text(
                f"🎉 {user_display} won <b>${profit:,.2f}</b>! ({multiplier}x)",
                parse_mode="HTML",
                reply_to_message_id=update.message.message_id
            )
        else:
            self.db.update_user(user_id, {
                'total_wagered': user_data['total_wagered'] + wager,
                'wagered_since_last_withdrawal': user_data.get('wagered_since_last_withdrawal', 0) + wager,
                'games_played': user_data['games_played'] + 1
            })
            self.db.update_house_balance(wager)
            
            await update.message.reply_text(
                f"❌ <a href=\"tg://user?id=8575155625\">emojigamblebot</a> won <b>${wager:,.2f}</b>",
                parse_mode="HTML",
                reply_to_message_id=update.message.message_id
            )
        
        self.db.record_game({
            'type': 'dice_predict',
            'player_id': user_id,
            'wager': wager,
            'predictions': list(predictions),
            'actual_roll': actual_roll,
            'result': 'win' if actual_roll in predictions else 'loss',
            'payout': (wager * multiplier) if actual_roll in predictions else 0
        })
    
    async def coinflip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play coinflip game setup"""
        amount = 1.0
        if context.args:
            try:
                arg = context.args[0].lower().replace('$', '').replace(',', '')
                if arg == 'all':
                    user_id = update.effective_user.id
                    user_data = self.db.get_user(user_id)
                    amount = user_data['balance']
                else:
                    amount = float(arg)
            except ValueError:
                pass
        await self._show_game_prediction_menu(update, context, amount, "coinflip")
    
    async def roulette_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Play roulette game"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if not context.args:
            await update.message.reply_text("Usage: `/roulette <amount|all>` or `/roulette <amount> #<number>`", parse_mode="Markdown")
            return
        
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Min: $0.01")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        if len(context.args) > 1 and context.args[1].startswith('#'):
            try:
                number_str = context.args[1][1:]
                if number_str == "00":
                    specific_num = 37
                else:
                    specific_num = int(number_str)
                    if specific_num < 0 or specific_num > 36:
                        await update.message.reply_text("❌ Number must be 0-36 or 00")
                        return
                
                await self.roulette_play_direct(update, context, wager, f"num_{specific_num}")
                return
            except ValueError:
                await update.message.reply_text("❌ Invalid number format. Use #0, #1, #2, ... #36, or #00")
                return
        
        keyboard = [
            [InlineKeyboardButton("Red (2x)", callback_data=f"roulette_{wager:.2f}_red"),
             InlineKeyboardButton("Black (2x)", callback_data=f"roulette_{wager:.2f}_black")],
            [InlineKeyboardButton("Green (14x)", callback_data=f"roulette_{wager:.2f}_green")],
            [InlineKeyboardButton("Odd (2x)", callback_data=f"roulette_{wager:.2f}_odd"),
             InlineKeyboardButton("Even (2x)", callback_data=f"roulette_{wager:.2f}_even")],
            [InlineKeyboardButton("Low (2x)", callback_data=f"roulette_{wager:.2f}_low"),
             InlineKeyboardButton("High (2x)", callback_data=f"roulette_{wager:.2f}_high")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = await update.message.reply_text(
            f"🎰 **Roulette** - Wager: ${wager:.2f}\n\n"
            f"**Choose your bet:**\n"
            f"• Red/Black: 2x payout\n"
            f"• Odd/Even: 2x payout\n"
            f"• Green (0/00): 14x payout\n"
            f"• Low (1-18)/High (19-36): 2x payout\n\n"
            f"*Tip: Bet on a specific number with `/roulette <amount> #<number>` for 36x payout!*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
    
    async def blackjack_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start a Blackjack game"""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        # Check if user already has an active game
        if user_id in self.blackjack_sessions:
            await update.message.reply_text("❌ You already have an active Blackjack game. Finish it first or use /stand to end it.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🃏 **Blackjack Rules**\n\n"
                "Get as close to 21 as possible without going over!\n\n"
                "**Card Values:**\n"
                "• 2-10: Face value\n"
                "• J, Q, K: 10 points\n"
                "• Ace: 1 or 11 points\n\n"
                "**Payouts:**\n"
                "• Blackjack (Ace + 10): 3:2 (1.5x)\n"
                "• Regular Win: 1:1\n"
                "• Push (tie): Bet returned\n\n"
                "**Actions:**\n"
                "• Hit: Take another card\n"
                "• Stand: Keep current hand\n"
                "• Double: Double bet, get 1 card\n"
                "• Split: Split pairs into 2 hands\n"
                "• Surrender: Forfeit and lose half bet\n\n"
                "**Usage:** `/blackjack <amount|all>`",
                parse_mode="Markdown"
            )
            return
        
        # Parse wager
        wager = 0.0
        if context.args[0].lower() == "all":
            wager = user_data['balance']
        else:
            try:
                wager = round(float(context.args[0]), 2)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount")
                return
        
        if wager <= 0.01:
            await update.message.reply_text("❌ Min: $0.01")
            return
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        # Deduct wager from balance
        user_data['balance'] -= wager
        self.db.update_user(user_id, user_data)
        
        # Create new Blackjack game
        game = BlackjackGame(bet_amount=wager)
        game.start_game()
        self.blackjack_sessions[user_id] = game
        
        # Display game state
        await self._display_blackjack_state(update, context, user_id)
    
    async def _display_blackjack_state(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Display the current Blackjack game state with action buttons"""
        if user_id not in self.blackjack_sessions:
            return
        
        game = self.blackjack_sessions[user_id]
        state = game.get_game_state()
        
        # Build message text
        message = "🃏 **Blackjack**\n\n"
        message += f"**Dealer:** {state['dealer']['cards']} "
        if state['game_over']:
            message += f"(Value: {state['dealer']['value']})\n\n"
        else:
            message += f"(Showing: {state['dealer']['value']})\n\n"
        
        # Display all player hands
        for hand in state['player_hands']:
            hand_status = ""
            if len(state['player_hands']) > 1:
                hand_status = f"**Hand {hand['id'] + 1}:** "
            
            hand_status += f"{hand['cards']} (Value: {hand['value']}) "
            hand_status += f"- Bet: ${hand['bet']:.2f}"
            
            if hand['status'] == 'Blackjack':
                hand_status += " 🎉 BLACKJACK!"
            elif hand['status'] == 'Bust':
                hand_status += " 💥 BUST"
            elif hand['is_current_turn']:
                hand_status += " ⬅️ Your turn"
            
            message += hand_status + "\n"
        
        # Insurance info
        if state['is_insurance_available']:
            message += f"\n**Insurance available:** ${state['insurance_bet']:.2f}\n"
        
        # Game over - show results
        if state['game_over']:
            message += f"\n**Final Result:**\n"
            if state['dealer']['final_status'] == 'Bust':
                message += f"Dealer busts with {state['dealer']['value']}!\n\n"
            elif state['dealer']['is_blackjack']:
                message += "Dealer has Blackjack!\n\n"
            
            total_payout = state['total_payout']
            if total_payout > 0:
                message += f"✅ **You won ${total_payout:.2f}!**"
            elif total_payout < 0:
                message += f"❌ **You lost ${abs(total_payout):.2f}**"
            else:
                message += "🤝 **Push** - Bet returned"
            
            # Update user balance
            user_data = self.db.get_user(user_id)
            # Add back: total payout + all hand bets + insurance bet (if taken)
            insurance_refund = state['insurance_bet'] if state['insurance_bet'] > 0 else 0
            user_data['balance'] += total_payout + sum(h['bet'] for h in state['player_hands']) + insurance_refund
            user_data['total_wagered'] += sum(h['bet'] for h in state['player_hands'])
            user_data['total_pnl'] += total_payout
            user_data['games_played'] += 1
            if total_payout > 0:
                user_data['games_won'] += 1
            self.db.update_user(user_id, user_data)
            
            # Record game
            self.db.record_game({
                'game_type': 'blackjack',
                'user_id': user_id,
                'username': user_data.get('username', 'Unknown'),
                'wager': sum(h['bet'] for h in state['player_hands']),
                'payout': total_payout,
                'result': 'win' if total_payout > 0 else ('loss' if total_payout < 0 else 'push')
            })
            
            # Remove session
            del self.blackjack_sessions[user_id]
            
            await update.effective_message.reply_text(message, parse_mode="Markdown")
            return
        
        # Build action buttons for current hand
        keyboard = []
        current_hand = state['player_hands'][state['current_hand_index']]
        
        if current_hand['is_current_turn']:
            actions = current_hand.get('actions', {})
            
            # Always show Hit and Stand
            keyboard.append([
                InlineKeyboardButton("Hit", callback_data=f"bj_{user_id}_hit"),
                InlineKeyboardButton("Stand", callback_data=f"bj_{user_id}_stand")
            ])
            
            # Double Down button
            if actions.get('can_double'):
                keyboard.append([InlineKeyboardButton("Double Down", callback_data=f"bj_{user_id}_double")])
            
            # Split button
            if actions.get('can_split'):
                keyboard.append([InlineKeyboardButton("Split", callback_data=f"bj_{user_id}_split")])
            
            # Surrender button
            if actions.get('can_surrender'):
                keyboard.append([InlineKeyboardButton("Surrender", callback_data=f"bj_{user_id}_surrender")])
        
        # Insurance button
        if state['is_insurance_available']:
            keyboard.append([InlineKeyboardButton("Take Insurance", callback_data=f"bj_{user_id}_insurance")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await update.effective_message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
    
    async def tip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send money to another player."""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/tip <amount> @user`", parse_mode="Markdown")
            return
        
        try:
            amount = round(float(context.args[0]), 2)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount")
            return
            
        if amount <= 0.01:
            await update.message.reply_text("❌ Min: $0.01")
            return
            
        if amount > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return

        recipient_username = context.args[1].lstrip('@')
        recipient_data = next((u for u in self.db.data['users'].values() if u.get('username') == recipient_username), None)

        if not recipient_data:
            await update.message.reply_text(f"❌ Could not find user with username @{recipient_username}.")
            return
            
        if recipient_data['user_id'] == user_id:
            await update.message.reply_text("❌ You cannot tip yourself.")
            return

        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data=f"tip_confirm_{recipient_data['user_id']}_{amount:.2f}"),
             InlineKeyboardButton("❌ Cancel", callback_data="tip_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"You want to tip **{recipient_username}** with **${amount:.2f}**. Is that correct?",
            reply_markup=reply_markup,
            parse_mode="Markdown",
            reply_to_message_id=update.message.message_id
        )

    async def deposit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user their unique deposit address for automatic deposits."""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        
        user_deposit_address = user_data.get('ltc_deposit_address')
        
        if not user_deposit_address:
            master_address = os.getenv("LTC_MASTER_ADDRESS", "")
            if master_address:
                user_deposit_address = master_address
                deposit_memo = f"User ID: {user_id}"
            else:
                await update.message.reply_text("❌ Deposits not configured. Contact admin.")
                return
        else:
            deposit_memo = None
        
        # Fetch live rates
        ltc_rate = await self.get_live_rate("litecoin")
        deposit_fee = float(os.getenv('DEPOSIT_FEE_PERCENT', '2'))
        
        deposit_text = f"""💰 **LTC Deposit**

Send Litecoin to this address:
`{user_deposit_address}`"""
        
        if deposit_memo:
            deposit_text += f"""

**Important:** Include your User ID in the memo/note:
`{user_id}`"""
        
        deposit_text += f"""

**Rate:** 1 LTC = ${ltc_rate:.2f}
**Fee:** {deposit_fee}%

Your balance will be credited automatically after 3 confirmations (~10 minutes).

⚠️ Only send LTC to this address!"""
        
        await update.message.reply_text(deposit_text, parse_mode="Markdown")

    async def withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Submit a withdrawal request for admin processing."""
        user_data = self.ensure_user_registered(update)
        user_id = update.effective_user.id
        username = user_data.get('username', f'User{user_id}')
        
        if len(context.args) < 2:
            await update.message.reply_text(
                f"💸 **Withdraw LTC**\n\nYour balance: **${user_data['balance']:.2f}**\n\nUsage: `/withdraw <amount> <your_ltc_address>`\n\n**Example:** `/withdraw 50 LTC1abc123...`",
                parse_mode="Markdown"
            )
            return
        
        try:
            amount = round(float(context.args[0]), 2)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.", parse_mode="Markdown")
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        
        if amount > user_data['balance']:
            await update.message.reply_text(f"❌ Insufficient balance. You have ${user_data['balance']:.2f}")
            return
        
        if amount < 1.00:
            await update.message.reply_text("❌ Minimum withdrawal is $1.00")
            return
        
        ltc_address = context.args[1]
        
        # Deduct balance immediately (hold for withdrawal)
        user_data['balance'] -= amount
        self.db.update_user(user_id, user_data)
        
        # Store pending withdrawal
        if 'pending_withdrawals' not in self.db.data:
            self.db.data['pending_withdrawals'] = []
        
        withdrawal_request = {
            'user_id': user_id,
            'username': username,
            'amount': amount,
            'ltc_address': ltc_address,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        }
        
        self.db.data['pending_withdrawals'].append(withdrawal_request)
        self.db.save_data()
        
        await update.message.reply_text(
            f"✅ **Withdrawal Request Submitted**\n\nAmount: **${amount:.2f}**\nTo: `{ltc_address}`\n\nAn admin will process your withdrawal soon.\n\nNew balance: ${user_data['balance']:.2f}",
            parse_mode="Markdown"
        )
        
        # Notify admins
        for admin_id in list(self.env_admin_ids) + list(self.dynamic_admin_ids):
            try:
                await self.app.bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 **New Withdrawal Request**\n\nUser: @{username} (ID: {user_id})\nAmount: ${amount:.2f}\nLTC Address: `{ltc_address}`\n\nUse `/processwithdraw {user_id}` after sending.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")

    async def pending_deposits_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View all pending deposits (Admin only)."""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        
        pending = self.db.data.get('pending_deposits', [])
        pending = [d for d in pending if d.get('status') == 'pending']
        
        if not pending:
            await update.message.reply_text("✅ No pending deposits.")
            return
        
        text = "📥 **Pending Deposits**\n\n"
        for i, dep in enumerate(pending[-20:], 1):
            text += f"{i}. @{dep['username']} (ID: {dep['user_id']})\n   Amount: ${dep['amount']:.2f}\n   TX: `{dep['tx_id']}`\n\n"
        
        text += "Use `/approvedeposit <user_id> <amount>` to approve."
        await update.message.reply_text(text, parse_mode="Markdown")

    async def approve_deposit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Approve a deposit and credit user balance (Admin only)."""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/approvedeposit <user_id> <amount>`", parse_mode="Markdown")
            return
        
        try:
            target_user_id = int(context.args[0])
            amount = round(float(context.args[1]), 2)
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or amount.")
            return
        
        user_data = self.db.get_user(target_user_id)
        user_data['balance'] += amount
        self.db.update_user(target_user_id, user_data)
        self.db.add_transaction(target_user_id, "deposit", amount, "LTC Deposit (Approved)")
        
        # Mark deposit as approved
        pending = self.db.data.get('pending_deposits', [])
        for dep in pending:
            if dep['user_id'] == target_user_id and dep.get('status') == 'pending':
                dep['status'] = 'approved'
                break
        self.db.save_data()
        
        await update.message.reply_text(
            f"✅ **Deposit Approved**\n\nUser ID: {target_user_id}\nAmount: ${amount:.2f}\nNew Balance: ${user_data['balance']:.2f}",
            parse_mode="Markdown"
        )
        
        # Notify user
        try:
            await self.app.bot.send_message(
                chat_id=target_user_id,
                text=f"✅ **Deposit Approved!**\n\nAmount: **${amount:.2f}** has been credited.\n\nNew Balance: ${user_data['balance']:.2f}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {e}")

    async def pending_withdraws_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View all pending withdrawals (Admin only)."""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        
        pending = self.db.data.get('pending_withdrawals', [])
        pending = [w for w in pending if w.get('status') == 'pending']
        
        if not pending:
            await update.message.reply_text("✅ No pending withdrawals.")
            return
        
        text = "📤 **Pending Withdrawals**\n\n"
        for i, wit in enumerate(pending[-20:], 1):
            text += f"{i}. @{wit['username']} (ID: {wit['user_id']})\n   Amount: ${wit['amount']:.2f}\n   LTC: `{wit['ltc_address']}`\n\n"
        
        text += "Use `/processwithdraw <user_id>` after sending LTC."
        await update.message.reply_text(text, parse_mode="Markdown")

    async def process_withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Mark a withdrawal as processed (Admin only)."""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        
        if len(context.args) < 1:
            await update.message.reply_text("Usage: `/processwithdraw <user_id>`", parse_mode="Markdown")
            return
        
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
        
        # Find and mark withdrawal as processed
        pending = self.db.data.get('pending_withdrawals', [])
        processed = None
        for wit in pending:
            if wit['user_id'] == target_user_id and wit.get('status') == 'pending':
                wit['status'] = 'processed'
                processed = wit
                break
        
        if not processed:
            await update.message.reply_text("❌ No pending withdrawal found for this user.")
            return
        
        self.db.add_transaction(target_user_id, "withdrawal", -processed['amount'], f"LTC Withdrawal to {processed['ltc_address'][:20]}...")
        self.db.save_data()
        
        await update.message.reply_text(
            f"✅ **Withdrawal Processed**\n\nUser ID: {target_user_id}\nAmount: ${processed['amount']:.2f}\nSent to: `{processed['ltc_address']}`",
            parse_mode="Markdown"
        )
        
        # Notify user
        try:
            await self.app.bot.send_message(
                chat_id=target_user_id,
                text=f"✅ **Withdrawal Sent!**\n\n**${processed['amount']:.2f}** has been sent to your LTC address.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {target_user_id}: {e}")

    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sends the database file as a backup (Admin only)."""
        if not self.is_admin(update.effective_user.id):
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
    
    async def save_sticker_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save a sticker file_id for roulette numbers"""
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                f"Usage: `/savesticker <number> <file_id>`\nNumbers: 00, 0-36",
                parse_mode="Markdown"
            )
            return
        
        number = context.args[0]
        file_id = context.args[1]
        
        # Validate number is valid roulette number
        valid_numbers = ['00', '0'] + [str(i) for i in range(1, 37)]
        if number not in valid_numbers:
            await update.message.reply_text(f"❌ Invalid number. Must be: 00, 0, 1, 2, 3... 36")
            return
        
        # Save to database
        if 'roulette' not in self.stickers:
            self.stickers['roulette'] = {}
        
        self.stickers['roulette'][number] = file_id
        self.db.data['stickers'] = self.stickers
        self.db.save_data()
        
        await update.message.reply_text(f"✅ Sticker saved for roulette number '{number}'!")
        
    async def list_stickers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all configured stickers"""
        sticker_text = "🎨 **Roulette Stickers**\n\n"
        
        roulette_stickers = self.stickers.get('roulette', {})
        
        # Count how many are set
        all_numbers = ['00', '0'] + [str(i) for i in range(1, 37)]
        saved_count = sum(1 for num in all_numbers if num in roulette_stickers and roulette_stickers[num])
        
        sticker_text += f"Saved: {saved_count}/38"
        await update.message.reply_text(sticker_text, parse_mode="Markdown")
    
    async def save_roulette_stickers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save all 38 roulette stickers to the database"""
        # Initialize roulette stickers if not present
        if 'roulette' not in self.stickers:
            self.stickers['roulette'] = {}
        
        # Save all 38 roulette sticker IDs
        self.stickers['roulette'] = {
            "00": "CAACAgQAAxkBAAEPnjFo-TLLYpgTZExC4IIOG6PIXwsviAAC1BgAAkmhgFG_0u82E59m3DYE",
            "0": "CAACAgQAAxkBAAEPnjNo-TMFaqDdWCkRDNlus4jcuamAAwACOh0AAtQAAYBRlMLfm2ulRSM2BA",
            "1": "CAACAgQAAxkBAAEPnjRo-TMFH5o5R9ztNtTFBJmQVK_t3wACqBYAAvTrgVE4WCoxbBzVCDYE",
            "2": "CAACAgQAAxkBAAEPnjdo-TMvGdoX-f6IAuR7kpYO-hh9fwAC1RYAAob0eVF1zbcG00UjMzYE",
            "3": "CAACAgQAAxkBAAEPnjho-TMwui0CFuGEK5iwS7xMRDiPfgACSRgAAs74gVEyHQtTsRykGjYE",
            "4": "CAACAgQAAxkBAAEPnj1o-TNGYNdmhy4n5Uyp3pzWmukTgAACfBgAAg3IgFGEjdLKewti5zYE",
            "5": "CAACAgQAAxkBAAEPnj5o-TNHTKLFF2NpdxfLhHnsnFGTXgACyhYAAltygVECKXn73kUyCjYE",
            "6": "CAACAgQAAxkBAAEPnkFo-TNPGqrsJJwZNwUe_I6k4W86cwACyxoAAgutgVGyiCe4lNK2-DYE",
            "7": "CAACAgQAAxkBAAEPnkJo-TNPksXPcYnpXDWYQC68AAGlqzQAAtUYAAKU_IFRJTHChQd2yfw2BA",
            "8": "CAACAgQAAxkBAAEPnkdo-TQOIBN5WtoKKnvcthXdcy0LLgACgBQAAmlWgVFImh6M5RcAAdI2BA",
            "9": "CAACAgQAAxkBAAEPnkho-TQO92px4jOuq80nT2uWjURzSAAC4BcAAvPKeVFBx-TZycAWDzYE",
            "10": "CAACAgQAAxkBAAEPnkto-TZ8-6moW-biByRYl8J2QEPnTwAC8hgAArnAgFGen1zgHwABLPc2BA",
            "11": "CAACAgQAAxkBAAEPnkxo-TZ8ncZZ7FYYyFMJHXRv2rB0TwAC2RMAAmzdgVEao0YAAdIy41g2BA",
            "12": "CAACAgQAAxkBAAEPnk1o-TZ9z6xAxxIeccUPXoQQ9VaikQACVRgAAovngVFUjR-qYgq8LDYE",
            "13": "CAACAgQAAxkBAAEPnlFo-TbUs79Rm549dK3JK2L3P83q-QACTR0AAmc0gFHXnJ509OdiOjYE",
            "14": "CAACAgQAAxkBAAEPnlJo-TbUCpjrhSxP-x84jkBerEYB8AACQxkAAqXDeVEQ5uCH3dK9OjYE",
            "15": "CAACAgQAAxkBAAEPnlNo-TbUZokc7ubz-neSYtK9kxQ0DAACrRYAAlBWgVH9BqGde-NivjYE",
            "16": "CAACAgQAAxkBAAEPnlRo-TbUiOcqxKI6HNExFR8yT3qyvAACrxsAAkcfeVG9im0F0tuZPzYE",
            "17": "CAACAgQAAxkBAAEPnllo-TdIFRtpAW3PeDbxD2QxTgjk2QACLhgAAiuXgVHaPo1woXZEYTYE",
            "18": "CAACAgQAAxkBAAEPnlpo-TdI9Gdz2Nv3icxluy8jC3keBwACYxkAAnx7eFGsZP2AXXBKwzYE",
            "19": "CAACAgQAAxkBAAEPnlto-TdIUktLbTIhkihQz3ymy4lUIwACKRkAArDwgFH0iKqIPPiHYDYE",
            "20": "CAACAgQAAxkBAAEPnlxo-TdJVrOSPiCRuD8Jc0XGvF3B8AACcxoAAr7OeFGSuSoHyKxf5TYE",
            "21": "CAACAgQAAxkBAAEPnl1o-TdJ1jlMSjGQPO0zkaS_rOv5JQACxhcAAv1dgFF3khtGYFneYzYE",
            "22": "CAACAgQAAxkBAAEPnmNo-Te2OhfAwfprG1HfmY-UNtkEAgADGQACE8KAUSJTKzPQQQ9INgQ",
            "23": "CAACAgQAAxkBAAEPnmRo-Te3rAHmt7_CRgFp55KSNVYdKwACTBgAAundgVF6unXyM34ZYzYE",
            "24": "CAACAgQAAxkBAAEPnmVo-Te3LcVARwsUx3Akt75bruvNXAAC4RoAAnkvgFHRL4l2927wnDYE",
            "25": "CAACAgQAAxkBAAEPnmZo-Te3lY0O1JxF8tTLYJJhN1QcnAAC5hcAAiPegFFsMkNzpqfR0zYE",
            "26": "CAACAgQAAxkBAAEPnmto-TgIsR6UdO8EukNYajboFnX3mgACzSAAAn15gVG-oQ4oaJLYrzYE",
            "27": "CAACAgQAAxkBAAEPnmxo-TgIVFkyEf19Je-9awnfcm0HNAACoBcAAjK0gVFqoRMWJ0V2AjYE",
            "28": "CAACAgQAAxkBAAEPnm1o-TgIEaTKLI1hP_FD5NoPNMoRrQAC8xUAAjTtgVFbDjOI7hjkyDYE",
            "29": "CAACAgQAAxkBAAEPnm5o-TgIrfmuYVnfQps2DUcaDPJtYAACehcAAgL2eFFyvPJETxqlljYE",
            "30": "CAACAgQAAxkBAAEPnm9o-TgIumJ40cFAJ7xQVVJu8yioGQACrBUAAqMsgVEiKujpQgVfJDYE",
            "31": "CAACAgQAAxkBAAEPnndo-ThreZX7kJJpPO5idNcOeIWZpQACDhsAArW6gFENcv6I97q9xDYE",
            "32": "CAACAgQAAxkBAAEPni9o-Ssij-qcC2-pLlmtFrUQr5AUgQACWxcAAsmneVGFqOYh9w81_TYE",
            "33": "CAACAgQAAxkBAAEPnnto-Thsmi6zNRuaeXnBFpXJ-w2JnQACjBkAAo3JeFEYXOtgIzFLjTYE",
            "34": "CAACAgQAAxkBAAEPnnlo-ThrHvyKnt3O8UiLblKzGgWqzQACWBYAAvn3gVElI6JyUvoRYzYE",
            "35": "CAACAgQAAxkBAAEPnn9o-Tij1sCB1_UVenRU6QvBnfFKagACkhYAAsKTgFHHcm9rj3PDyDYE",
            "36": "CAACAgQAAxkBAAEPnoBo-Tik1zRaZMCVCaOi9J1FtVvEiAACrBcAAtbQgVFt8Uw1gyn4MDYE"
        }
        
        # Save to database
        self.db.data['stickers'] = self.stickers
        self.db.save_data()
        
        await update.message.reply_text("✅ All 38 roulette stickers have been saved to the database!")
    
    async def sticker_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming stickers silently"""
        pass
    
    # --- ADMIN COMMANDS ---
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check if user is an admin"""
        user_id = update.effective_user.id
        
        if self.is_admin(user_id):
            is_env_admin = user_id in self.env_admin_ids
            admin_type = "Permanent Admin" if is_env_admin else "Dynamic Admin"
            
            admin_text = f"""✅ You are a {admin_type}!

Admin Commands:
• /givebal [@username or ID] [amount] - Give money to a user
• /p [amount] - Instantly add balance to yourself
• /setbal [@username or ID] [amount] - Set a user's balance
• /allusers - View all registered users
• /userinfo [@username or ID] - View detailed user info
• /backup - Download database backup
• /addadmin [user_id] - Make someone an admin
• /removeadmin [user_id] - Remove admin access
• /listadmins - List all admins

Examples:
/givebal @john 100
/setbal 123456789 500
/addadmin 987654321
/removeadmin 987654321"""
            await update.message.reply_text(admin_text)
        else:
            await update.message.reply_text("❌ You are not an admin.")
    
    async def givebal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Give balance to a user (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /givebal [@username or user_id] [amount]\nExample: /givebal @john 100")
            return
        
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        
        target_user = self.find_user_by_username_or_id(context.args[0])
        if not target_user:
            await update.message.reply_text(f"❌ User '{context.args[0]}' not found.")
            return
        
        target_user_id = target_user['user_id']
        target_user['balance'] += amount
        self.db.update_user(target_user_id, target_user)
        self.db.add_transaction(target_user_id, "admin_give", amount, f"Admin grant by {update.effective_user.id}")
        
        username_display = f"@{target_user.get('username', target_user_id)}"
        await update.message.reply_text(
            f"✅ Gave ${amount:.2f} to {username_display}\n"
            f"New balance: ${target_user['balance']:.2f}"
        )
    
    async def setbal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set a user's balance (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /setbal [@username or user_id] [amount]\nExample: /setbal @john 500")
            return
        
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
        
        if amount < 0:
            await update.message.reply_text("❌ Amount cannot be negative.")
            return
        
        target_user = self.find_user_by_username_or_id(context.args[0])
        if not target_user:
            await update.message.reply_text(f"❌ User '{context.args[0]}' not found.")
            return
        
        target_user_id = target_user['user_id']
        old_balance = target_user['balance']
        target_user['balance'] = amount
        self.db.update_user(target_user_id, target_user)
        self.db.add_transaction(target_user_id, "admin_set", amount - old_balance, f"Admin set balance by {update.effective_user.id}")
        
        username_display = f"@{target_user.get('username', target_user_id)}"
        await update.message.reply_text(
            f"✅ Set balance for {username_display}\n"
            f"Old balance: ${old_balance:.2f}\n"
            f"New balance: ${amount:.2f}"
        )
    
    async def p_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Instantly add balance to the calling user (Admin only)"""
        user_id = update.effective_user.id
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
            
        if not context.args:
            await update.message.reply_text("Usage: /p [amount]\nExample: /p 100")
            return
            
        try:
            amount = float(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
            
        user_data = self.db.get_user(user_id)
        user_data['balance'] += amount
        self.db.update_user(user_id, user_data)
        self.db.add_transaction(user_id, "admin_p", amount, f"Self-grant /p by {user_id}")
        
        await update.message.reply_text(f"✅ Added ${amount:.2f} to your balance.\nNew balance: ${user_data['balance']:.2f}")

    async def allusers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View all registered users (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        users = self.db.data['users']
        
        if not users:
            await update.message.reply_text("No users registered yet.")
            return
        
        users_text = f"👥 **All Users ({len(users)})**\n\n"
        
        for user_id_str, user_data in list(users.items())[:50]:
            username = user_data.get('username', 'N/A')
            balance = user_data.get('balance', 0)
            users_text += f"ID: `{user_id_str}` | @{username} | ${balance:.2f}\n"
        
        if len(users) > 50:
            users_text += f"\n...and {len(users) - 50} more users"
        
        await update.message.reply_text(users_text, parse_mode="Markdown")
    
    async def userinfo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View detailed user information (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /userinfo [@username or user_id]\nExample: /userinfo @john")
            return
        
        target_user = self.find_user_by_username_or_id(context.args[0])
        if not target_user:
            await update.message.reply_text(f"❌ User '{context.args[0]}' not found.")
            return
        
        target_user_id = target_user['user_id']
        
        info_text = f"""
👤 **User Info: {target_user_id}**

Username: @{target_user.get('username', 'N/A')}
Balance: ${target_user.get('balance', 0):.2f}
Playthrough: ${target_user.get('playthrough_required', 0):.2f}

**Stats:**
Games Played: {target_user.get('games_played', 0)}
Games Won: {target_user.get('games_won', 0)}
Total Wagered: ${target_user.get('total_wagered', 0):.2f}
Total P&L: ${target_user.get('total_pnl', 0):.2f}
Best Win Streak: {target_user.get('best_win_streak', 0)}

**Referrals:**
Referred By: {target_user.get('referred_by', 'None')}
Referral Count: {target_user.get('referral_count', 0)}
Referral Earnings: ${target_user.get('referral_earnings', 0):.2f}
"""
        
        await update.message.reply_text(info_text, parse_mode="Markdown")
    
    async def addadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a new admin (Admin only - requires environment admin)"""
        user_id = update.effective_user.id
        
        # Only permanent admins (from environment) can add new admins
        if user_id not in self.env_admin_ids:
            await update.message.reply_text("❌ Only permanent admins can add new admins.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /addadmin [user_id]\nExample: /addadmin 123456789")
            return
        
        try:
            new_admin_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please provide a numeric ID.")
            return
        
        # Check if already an admin
        if self.is_admin(new_admin_id):
            admin_type = "permanent" if new_admin_id in self.env_admin_ids else "dynamic"
            await update.message.reply_text(f"❌ User {new_admin_id} is already a {admin_type} admin.")
            return
        
        # Add to dynamic admins
        self.dynamic_admin_ids.add(new_admin_id)
        self.db.data['dynamic_admins'] = list(self.dynamic_admin_ids)
        self.db.save_data()
        
        await update.message.reply_text(f"✅ User {new_admin_id} has been added as an admin!")
        
        # Notify the new admin if they exist in the system
        try:
            await self.app.bot.send_message(
                chat_id=new_admin_id,
                text="🎉 You have been granted admin privileges! Use /admin to see available commands."
            )
        except Exception as e:
            logger.info(f"Could not notify new admin {new_admin_id}: {e}")
    
    async def removeadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove an admin (Admin only - requires environment admin)"""
        user_id = update.effective_user.id
        
        # Only permanent admins (from environment) can remove admins
        if user_id not in self.env_admin_ids:
            await update.message.reply_text("❌ Only permanent admins can remove admins.")
            return
        
        if not context.args:
            await update.message.reply_text("Usage: /removeadmin [user_id]\nExample: /removeadmin 123456789")
            return
        
        try:
            admin_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please provide a numeric ID.")
            return
        
        # Prevent removing permanent admins
        if admin_id in self.env_admin_ids:
            await update.message.reply_text("❌ Cannot remove permanent admins from environment.")
            return
        
        # Check if they are a dynamic admin
        if admin_id not in self.dynamic_admin_ids:
            await update.message.reply_text(f"❌ User {admin_id} is not a dynamic admin.")
            return
        
        # Remove from dynamic admins
        self.dynamic_admin_ids.discard(admin_id)
        self.db.data['dynamic_admins'] = list(self.dynamic_admin_ids)
        self.db.save_data()
        
        await update.message.reply_text(f"✅ Removed admin privileges from user {admin_id}!")
        
        # Notify the user if possible
        try:
            await self.app.bot.send_message(
                chat_id=admin_id,
                text="Your admin privileges have been removed."
            )
        except Exception as e:
            logger.info(f"Could not notify removed admin {admin_id}: {e}")
    
    async def listadmins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all admins (Admin only)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ This command is for administrators only.")
            return
        
        admin_text = "👑 **Admin List**\n\n"
        
        if self.env_admin_ids:
            admin_text += "**Permanent Admins (from environment):**\n"
            for admin_id in sorted(self.env_admin_ids):
                user_data = self.db.data['users'].get(str(admin_id))
                username = user_data.get('username', 'N/A') if user_data else 'N/A'
                admin_text += f"• {admin_id} (@{username})\n"
            admin_text += "\n"
        
        if self.dynamic_admin_ids:
            admin_text += "**Dynamic Admins (added via commands):**\n"
            for admin_id in sorted(self.dynamic_admin_ids):
                user_data = self.db.data['users'].get(str(admin_id))
                username = user_data.get('username', 'N/A') if user_data else 'N/A'
                admin_text += f"• {admin_id} (@{username})\n"
        else:
            if not self.env_admin_ids:
                admin_text += "No admins configured."
            else:
                admin_text += "No dynamic admins added yet.\n"
                admin_text += "Use /addadmin to add more admins."
        
        await update.message.reply_text(admin_text, parse_mode="Markdown")
    
    async def send_sticker(self, chat_id: int, outcome: str, profit: float = 0):
        """Send a sticker based on game outcome"""
        try:
            sticker_key = None
            
            if outcome == "win":
                if profit >= 50:
                    sticker_key = "jackpot"
                elif profit >= 10:
                    sticker_key = "big_win"
                else:
                    sticker_key = "win"
            elif outcome == "loss":
                sticker_key = "loss"
            elif outcome == "draw":
                sticker_key = "draw"
            elif outcome == "bonus_claim":
                sticker_key = "bonus_claim"
            
            if sticker_key and self.stickers.get(sticker_key):
                await self.app.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=self.stickers[sticker_key]
                )
        except Exception as e:
            logger.error(f"Error sending sticker: {e}")

    # --- GAME LOGIC ---

    def _update_user_stats(self, user_id: int, wager: float, profit: float, result: str):
        """Update user statistics after a game."""
        with self.db.app.app_context():
            from sqlalchemy import select
            user = db.session.execute(select(User).filter_by(user_id=user_id)).scalar_one_or_none()
            if not user:
                return

            user.total_wagered += wager
            user.total_pnl += profit
            user.games_played += 1
            if result == "win":
                user.games_won += 1
                user.win_streak += 1
                if user.win_streak > user.best_win_streak:
                    user.best_win_streak = user.win_streak
            else:
                user.win_streak = 0
            
            db.session.commit()


    async def dice_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play dice against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        msg_id = query.message.message_id
        
        if wager > user_data['balance']:
            await query.answer(f"❌ Insufficient balance! Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        # Deduct wager and log transaction
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, "Bet on Dice vs Bot")
        
        # Initialize V2 bot game state (Unified logic)
        game_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
        game_state = {
            "game": "dice",
            "mode": "normal",
            "rolls": 1,
            "pts": 1,
            "p_pts": 0,
            "b_pts": 0,
            "p_rolls": [],
            "cur_rolls": 0,
            "wager": wager,
            "wager_deducted": True,
            "emoji": "🎲",
            "player": user_id,
            "chat_id": chat_id,
            "msg_id": msg_id,
            "emoji_wait": datetime.now().isoformat(),
            "waiting_for_emoji": True,
            "created_at": datetime.now().isoformat()
        }
        
        self.pending_pvp[game_id] = game_state
        self.db.update_pending_pvp(self.pending_pvp)
        
        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🎲 **Match accepted!**\n\nPlayer 1: {user_mention}\nPlayer 2: Bot\n\n**{user_mention}**, your turn! To start, click the button below! 🎲",
            reply_to_message_id=msg_id,
            parse_mode="Markdown"
        )

    async def darts_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play darts against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await query.answer(f"❌ Insufficient balance! Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, "Bet on Darts vs Bot")
        
        game_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
        game_state = {
            "game": "darts",
            "mode": "normal",
            "rolls": 1,
            "pts": 1,
            "p_pts": 0,
            "b_pts": 0,
            "p_rolls": [],
            "cur_rolls": 0,
            "wager": wager,
            "wager_deducted": True,
            "emoji": "🎯",
            "player": user_id,
            "chat_id": chat_id,
            "emoji_wait": datetime.now().isoformat(),
            "waiting_for_emoji": True,
            "created_at": datetime.now().isoformat()
        }
        
        self.pending_pvp[game_id] = game_state
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        bot_mention = f"[{context.bot.username or 'Bot'}](tg://user?id={context.bot.id})"
        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🎯 **Match accepted!**\n\nPlayer 1: {user_mention}\nPlayer 2: Bot\n\n**{user_mention}**, your turn! To start, click the button below! 🎯",
            reply_to_message_id=query.message.message_id,
            parse_mode="Markdown"
        )

    async def basketball_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play basketball against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await query.answer(f"❌ Insufficient balance! Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, "Bet on Basketball vs Bot")
        
        game_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
        game_state = {
            "game": "basketball",
            "mode": "normal",
            "rolls": 1,
            "pts": 1,
            "p_pts": 0,
            "b_pts": 0,
            "p_rolls": [],
            "cur_rolls": 0,
            "wager": wager,
            "wager_deducted": True,
            "emoji": "🏀",
            "player": user_id,
            "chat_id": chat_id,
            "emoji_wait": datetime.now().isoformat(),
            "waiting_for_emoji": True,
            "created_at": datetime.now().isoformat()
        }
        
        self.pending_pvp[game_id] = game_state
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        bot_mention = f"[{context.bot.username or 'Bot'}](tg://user?id={context.bot.id})"
        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🏀 **Match accepted!**\n\nPlayer 1: {user_mention}\nPlayer 2: Bot\n\n**{user_mention}**, your turn! To start, click the button below! 🏀",
            reply_to_message_id=query.message.message_id,
            parse_mode="Markdown"
        )

    async def soccer_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play soccer against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await query.answer(f"❌ Insufficient balance! Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, "Bet on Soccer vs Bot")
        
        game_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
        game_state = {
            "game": "soccer",
            "mode": "normal",
            "rolls": 1,
            "pts": 1,
            "p_pts": 0,
            "b_pts": 0,
            "p_rolls": [],
            "cur_rolls": 0,
            "wager": wager,
            "wager_deducted": True,
            "emoji": "⚽",
            "player": user_id,
            "chat_id": chat_id,
            "emoji_wait": datetime.now().isoformat(),
            "waiting_for_emoji": True,
            "created_at": datetime.now().isoformat()
        }
        
        self.pending_pvp[game_id] = game_state
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        bot_mention = f"[{context.bot.username or 'Bot'}](tg://user?id={context.bot.id})"
        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🎮 **Soccer Series**\n\n{bot_mention} vs {user_mention}\n\n{user_mention} your turn! Send ⚽",
            parse_mode="Markdown"
        )

    async def bowling_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float):
        """Play bowling against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await query.answer(f"❌ Insufficient balance! Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, "Bet on Bowling vs Bot")
        
        game_id = f"v2_bot_{user_id}_{int(datetime.now().timestamp())}"
        game_state = {
            "game": "bowling",
            "mode": "normal",
            "rolls": 1,
            "pts": 1,
            "p_pts": 0,
            "b_pts": 0,
            "p_rolls": [],
            "cur_rolls": 0,
            "wager": wager,
            "wager_deducted": True,
            "emoji": "🎳",
            "player": user_id,
            "chat_id": chat_id,
            "emoji_wait": datetime.now().isoformat(),
            "waiting_for_emoji": True,
            "created_at": datetime.now().isoformat()
        }
        
        self.pending_pvp[game_id] = game_state
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        bot_mention = f"[{context.bot.username or 'Bot'}](tg://user?id={context.bot.id})"
        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
        
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🎮 **Bowling Series**\n\n{bot_mention} vs {user_mention}\n\n{user_mention} your turn! Send 🎳",
            parse_mode="Markdown"
        )

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

        chat_id = query.message.chat_id
        
        challenge_id = f"dice_open_{user_id}_{int(datetime.now().timestamp())}"
        self.pending_pvp[challenge_id] = {
            "type": "dice",
            "challenger": user_id,
            "challenger_roll": None,
            "opponent": None,
            "wager": wager,
            "emoji": "🎲",
            "chat_id": chat_id,
            "waiting_for_challenger_emoji": False,
            "created_at": datetime.now().isoformat()
        }
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        keyboard = [[InlineKeyboardButton("✅ Accept Challenge", callback_data=f"accept_dice_{challenge_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🎲 **Dice PvP Challenge!**\n\n"
            f"Challenger: @{username}\n"
            f"Wager: **${wager:.2f}**\n\n"
            f"Click below to accept!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def accept_dice_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Accept a pending dice challenge and resolve it."""
        query = update.callback_query

        challenge = self.pending_pvp.get(challenge_id)
        if not challenge:
            await query.edit_message_text("❌ This challenge has expired or was canceled.")
            return
        
        # Check if challenge has expired (>5 minutes old)
        if 'created_at' in challenge:
            created_at = datetime.fromisoformat(challenge['created_at'])
            time_diff = (datetime.now() - created_at).total_seconds()
            if time_diff > 300:
                await query.edit_message_text("❌ This challenge has expired after 5 minutes.")
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
        
        # Tell challenger to send their emoji first
        await query.edit_message_text(
            f"@{challenger_user['username']} your turn",
            parse_mode="Markdown"
        )
        
        # Update challenge to mark acceptor and wait for challenger emoji
        challenge['opponent'] = acceptor_id
        challenge['waiting_for_challenger_emoji'] = True
        challenge['waiting_for_emoji'] = False
        challenge['emoji_wait_started'] = datetime.now().isoformat()
        self.pending_pvp[challenge_id] = challenge
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()

    async def create_emoji_pvp_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, game_type: str, emoji: str):
        """Create an emoji-based PvP challenge (darts, basketball, soccer)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        
        if wager > user_data['balance']:
            await query.answer("❌ Insufficient balance to cover the wager.", show_alert=True)
            return
        
        # Deduct wager from challenger balance immediately
        self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
        
        chat_id = query.message.chat_id
        
        challenge_id = f"{game_type}_open_{user_id}_{int(datetime.now().timestamp())}"
        self.pending_pvp[challenge_id] = {
            "type": game_type,
            "challenger": user_id,
            "challenger_roll": None,
            "opponent": None,
            "wager": wager,
            "emoji": emoji,
            "chat_id": chat_id,
            "waiting_for_challenger_emoji": False,
            "created_at": datetime.now().isoformat()
        }
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        keyboard = [[InlineKeyboardButton("✅ Accept Challenge", callback_data=f"accept_{game_type}_{challenge_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"{emoji} **{game_type.upper()} PvP Challenge!**\n\n"
            f"Challenger: @{username}\n"
            f"Wager: **${wager:.2f}**\n\n"
            f"Click below to accept!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def accept_emoji_pvp_challenge(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Accept a pending emoji PvP challenge"""
        query = update.callback_query
        
        challenge = self.pending_pvp.get(challenge_id)
        if not challenge:
            await query.answer("❌ This challenge has expired or was canceled.", show_alert=True)
            return
        
        # Check if challenge has expired (>5 minutes old)
        if 'created_at' in challenge:
            created_at = datetime.fromisoformat(challenge['created_at'])
            time_diff = (datetime.now() - created_at).total_seconds()
            if time_diff > 300:
                await query.answer("❌ This challenge has expired after 5 minutes.", show_alert=True)
                return
        
        acceptor_id = query.from_user.id
        wager = challenge['wager']
        challenger_id = challenge['challenger']
        challenger_user = self.db.get_user(challenger_id)
        acceptor_user = self.db.get_user(acceptor_id)
        game_type = challenge['type']
        emoji = challenge['emoji']
        chat_id = challenge['chat_id']
        
        if acceptor_id == challenger_id:
            await query.answer("❌ You cannot accept your own challenge.", show_alert=True)
            return
        
        if wager > acceptor_user['balance']:
            await query.answer(f"❌ Insufficient balance. You need ${wager:.2f} to accept.", show_alert=True)
            return
        
        # Deduct wager from acceptor balance
        self.db.update_user(acceptor_id, {'balance': acceptor_user['balance'] - wager})
        
        # Tell challenger to send their emoji first
        await query.edit_message_text(
            f"@{challenger_user['username']} your turn",
            parse_mode="Markdown"
        )
        
        # Update challenge to mark acceptor and wait for challenger emoji
        challenge['opponent'] = acceptor_id
        challenge['waiting_for_challenger_emoji'] = True
        challenge['waiting_for_emoji'] = False
        challenge['emoji_wait_started'] = datetime.now().isoformat()
        self.pending_pvp[challenge_id] = challenge
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()

    def calculate_cashout(self, p_pts, b_pts, target_pts, wager):
        """
        Calculate cashout value based on win probability.
        Uses a simplified binomial distribution approximation.
        """
        if p_pts >= target_pts: return wager * 2
        if b_pts >= target_pts: return 0
        
        # Simplified probability: each round is 50/50 (ignoring draws for simplicity)
        # We need to win (target - p_pts) rounds before bot wins (target - b_pts)
        needed_p = target_pts - p_pts
        needed_b = target_pts - b_pts
        
        # Total maximum rounds left is (needed_p + needed_b - 1)
        # Using a pre-calculated small table or simplified ratio for 1-3 pts
        # Since points are 1, 2, or 3, we can handle cases
        
        # Probability of player winning series
        prob = 0.5 # Default
        if needed_p == 1 and needed_b == 1: prob = 0.5
        elif needed_p == 1 and needed_b == 2: prob = 0.75
        elif needed_p == 1 and needed_b == 3: prob = 0.875
        elif needed_p == 2 and needed_b == 1: prob = 0.25
        elif needed_p == 2 and needed_b == 2: prob = 0.5
        elif needed_p == 2 and needed_b == 3: prob = 0.6875
        elif needed_p == 3 and needed_b == 1: prob = 0.125
        elif needed_p == 3 and needed_b == 2: prob = 0.3125
        elif needed_p == 3 and needed_b == 3: prob = 0.5

        # Cashout = (Probability * Total Payout) * (1 - House Edge)
        # Total Payout is wager * 2. House edge is ~5%.
        cashout_val = (prob * (wager * 2)) * 0.95
        return max(0, round(cashout_val, 2))

    async def handle_emoji_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.dice: return
        user_id = update.effective_user.id
        emoji = update.message.dice.emoji
        val = update.message.dice.value
        chat_id = update.message.chat_id
        
        # Determine if this message is a reply to a bot message
        is_reply = False
        if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
            is_reply = True
            replied_to_id = update.message.reply_to_message.message_id
        
        logger.info(f"Received dice roll: user={user_id}, emoji={emoji}, value={val}, is_reply={is_reply}")

        # Scoring logic
        if emoji in ["⚽", "🏀"]: score = 1 if val >= 4 else 0
        else: score = val

        # Ensure pending_pvp is up to date
        with self.db.app.app_context():
            pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
            self.pending_pvp = pending_pvp_state.value if pending_pvp_state else {}
        
        logger.info(f"Checking for matching game in {len(self.pending_pvp)} pending challenges")
        
        # Priority check for V2 bot games
        for cid, challenge in list(self.pending_pvp.items()):
            if cid.startswith("v2_bot_") and challenge.get('player') == user_id and challenge.get('emoji') == emoji:
                # If it's a reply, it MUST be to the correct message. 
                # If it's NOT a reply, we'll still accept it if it's in the same chat (convenience)
                msg_id_match = True
                if is_reply:
                    if challenge.get('msg_id') and replied_to_id != challenge.get('msg_id'):
                        msg_id_match = False
                
                if challenge.get('chat_id') == chat_id and challenge.get('waiting_for_emoji') and msg_id_match:
                    logger.info(f"Match found for V2 Bot game: {cid}")
                    
                    # Ensure state keys exist
                    if 'cur_rolls' not in challenge: challenge['cur_rolls'] = 0
                    if 'p_pts' not in challenge: challenge['p_pts'] = 0
                    if 'b_pts' not in challenge: challenge['b_pts'] = 0
                    if 'p_rolls' not in challenge: challenge['p_rolls'] = []
                    if 'rolls' not in challenge: challenge['rolls'] = 1
                    if 'pts' not in challenge: challenge['pts'] = 3
                    if 'mode' not in challenge: challenge['mode'] = 'normal'
                    
                    # Check balance if wager not yet deducted
                    if not challenge.get('wager_deducted'):
                        user_data = self.db.get_user(user_id)
                        if user_data['balance'] < (challenge['wager'] - 0.001):
                            await update.message.reply_text(f"❌ Insufficient balance to start the game! (Balance: ${user_data['balance']:.2f}, Wager: ${challenge['wager']:.2f})")
                            del self.pending_pvp[cid]
                            with self.db.app.app_context():
                                pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
                                if pending_pvp_state:
                                    pending_pvp_state.value = self.pending_pvp
                                    db.session.commit()
                            return
                        self.db.update_user(user_id, {'balance': max(0, user_data['balance'] - challenge['wager'])})
                        self.db.add_transaction(user_id, "game_bet", -challenge['wager'], f"Bet on {challenge.get('game_mode', 'game')} vs Bot")
                        challenge['wager_deducted'] = True
                    
                    # Add roll to state
                    challenge['p_rolls'].append(score)
                    challenge['cur_rolls'] += 1
                    challenge['waiting_for_cashout'] = False
                    
                    if challenge['cur_rolls'] < challenge['rolls']:
                        # Still need more rolls
                        user_mention = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
                        await update.message.reply_text(f"{user_mention} roll again {emoji} ({challenge['cur_rolls']}/{challenge['rolls']})")
                        with self.db.app.app_context():
                            pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
                            if pending_pvp_state:
                                pending_pvp_state.value = self.pending_pvp
                                db.session.commit()
                        return
                    
                    # Player finished rolls, now bot rolls
                    challenge['waiting_for_emoji'] = False
                    
                    with self.db.app.app_context():
                        pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
                        if pending_pvp_state:
                            pending_pvp_state.value = self.pending_pvp
                            db.session.commit()
                    
                    p_tot = sum(challenge['p_rolls'][-challenge['rolls']:])
                    await context.bot.send_message(chat_id=chat_id, text=f"<b>Rukia</b>, your turn!")
                    
                    b_tot = 0
                    for _ in range(challenge['rolls']):
                        await asyncio.sleep(2)
                        d = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
                        bv = d.dice.value
                        if emoji in ["⚽", "🏀"]:
                            b_val = 1 if bv >= 4 else 0
                        else:
                            b_val = bv
                        b_tot += b_val
                        await asyncio.sleep(3.5)
                    
                    # Update challenge after bot rolls to ensure final score is captured
                    with self.db.app.app_context():
                        pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
                        self.pending_pvp = pending_pvp_state.value if pending_pvp_state else {}
                    challenge = self.pending_pvp.get(cid)
                    if not challenge: return
                    
                    win = None
                    if challenge['mode'] == "normal":
                        if p_tot > b_tot: win = "p"
                        elif b_tot > p_tot: win = "b"
                    else: # crazy
                        if p_tot < b_tot: win = "p"
                        elif b_tot < p_tot: win = "b"
                    
                    if win == "p": challenge['p_pts'] += 1
                    elif win == "b": challenge['b_pts'] += 1
                    
                    challenge['cur_rolls'] = 0
                    challenge['emoji_wait'] = datetime.now().isoformat()
                    
                    if challenge['p_pts'] >= challenge['pts'] or challenge['b_pts'] >= challenge['pts']:
                        # Series ended
                        w = challenge['wager']
                        if challenge['p_pts'] >= challenge['pts']:
                            u = self.db.get_user(user_id)
                            payout = w * 1.95
                            u['balance'] += payout # Payout
                            self.db.update_user(user_id, u)
                            self.db.update_house_balance(-(w * 0.95))
                            
                            user_username = u.get('username', f'User{user_id}')
                            win_text = (
                                f"🏆 <b>Game over!</b>\n\n"
                                f"<b>Score:</b>\n"
                                f"{user_username} • {challenge['p_pts']}\n"
                                f"Rukia • {challenge['b_pts']}\n\n"
                                f"🎉 Congratulations, <b>{user_username}</b>! You won <b>${payout:,.2f}</b>!"
                            )
                            
                            keyboard = [
                                [
                                    InlineKeyboardButton("🔄 Play Again", callback_data=f"v2_bot_{challenge['game']}_{wager:.2f}_{challenge['rolls']}_{challenge['mode']}_{challenge['pts']}"),
                                    InlineKeyboardButton("🔄 Double", callback_data=f"v2_bot_{challenge['game']}_{wager*2:.2f}_{challenge['rolls']}_{challenge['mode']}_{challenge['pts']}")
                                ]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            
                            # Reply to the initial setup message if available
                            msg_id = challenge.get('message_id')
                            if msg_id:
                                await context.bot.send_message(chat_id=chat_id, text=win_text, reply_to_message_id=msg_id, reply_markup=reply_markup, parse_mode="HTML")
                            else:
                                await context.bot.send_message(chat_id=chat_id, text=win_text, reply_markup=reply_markup, parse_mode="HTML")
                            
                            self._update_user_stats(user_id, w, w * 0.95, "win")
                        else:
                            self.db.update_house_balance(w)
                            user_data = self.db.get_user(user_id)
                            user_username = user_data.get('username', f'User{user_id}')
                            loss_text = (
                                f"🏆 <b>Game over!</b>\n\n"
                                f"<b>Score:</b>\n"
                                f"{user_username} • {challenge['p_pts']}\n"
                                f"Rukia • {challenge['b_pts']}\n\n"
                                f"<b>Rukia</b> wins <b>${w * 1.95:,.2f}</b>"
                            )
                            keyboard = [
                                [
                                    InlineKeyboardButton("🔄 Play Again", callback_data=f"v2_bot_{challenge['game']}_{wager:.2f}_{challenge['rolls']}_{challenge['mode']}_{challenge['pts']}"),
                                    InlineKeyboardButton("🔄 Double", callback_data=f"v2_bot_{challenge['game']}_{wager*2:.2f}_{challenge['rolls']}_{challenge['mode']}_{challenge['pts']}")
                                ]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)
                            await context.bot.send_message(chat_id=chat_id, text=loss_text, reply_markup=reply_markup, parse_mode="HTML")
                            self._update_user_stats(user_id, w, -w, "loss")
                        
                        del self.pending_pvp[cid]
                    else:
                        # Next round
                        challenge['waiting_for_emoji'] = True
                        challenge['p_rolls'] = []
                        
                        user_data = self.db.get_user(user_id)
                        user_username = user_data.get('username', f'User{user_id}')
                        
                        round_text = (
                            f"<b>Score</b>\n\n"
                            f"{user_username}: {challenge['p_pts']}\n"
                            f"Rukia: {challenge['b_pts']}\n\n"
                            f"<b>{user_username}</b>, your turn!"
                        )
                        
                        cashout_val = self.calculate_cashout(challenge['p_pts'], challenge['b_pts'], challenge['pts'], challenge['wager'])
                        cashout_multiplier = round(cashout_val / challenge['wager'], 2) if challenge['wager'] > 0 else 0
                        
                        keyboard = [[InlineKeyboardButton(f"💰 Cashout ${cashout_val:.2f} ({cashout_multiplier}x)", callback_data=f"v2_cashout_{cid}")]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await context.bot.send_message(chat_id=chat_id, text=round_text, reply_markup=reply_markup, parse_mode="HTML")
                    
                    with self.db.app.app_context():
                        pending_pvp_state = db.session.get(GlobalState, "pending_pvp")
                        if pending_pvp_state:
                            pending_pvp_state.value = self.pending_pvp
                            db.session.commit()
                    return

            # Generic V2 PvP
            if cid.startswith("v2_pvp_") and challenge.get('emoji') == emoji:
                if challenge.get('waiting_p1') and challenge['challenger'] == user_id:
                    if not challenge.get('p1_deducted'):
                        user_data = self.db.get_user(user_id)
                        if user_data['balance'] < (challenge['wager'] - 0.001):
                            await update.message.reply_text(f"❌ Insufficient balance to roll! (Balance: ${user_data['balance']:.2f})")
                            return
                        self.db.update_user(user_id, {'balance': max(0, user_data['balance'] - challenge['wager'])})
                        challenge['p1_deducted'] = True
                    
                    challenge['p1_rolls'].append(score)
                    if len(challenge['p1_rolls']) >= challenge['rolls']:
                        challenge['waiting_p1'], challenge['waiting_p2'] = False, True
                        p2_data = self.db.get_user(challenge['opponent'])
                        await update.message.reply_text(f"✅ @{p2_data['username']} turn!")
                    challenge['emoji_wait'] = datetime.now().isoformat()
                    self.db.save_data()
                    return
                if challenge.get('waiting_p2') and challenge['opponent'] == user_id:
                    if not challenge.get('p2_deducted'):
                        user_data = self.db.get_user(user_id)
                        if user_data['balance'] < (challenge['wager'] - 0.001):
                            await update.message.reply_text(f"❌ Insufficient balance to roll! (Balance: ${user_data['balance']:.2f})")
                            return
                        self.db.update_user(user_id, {'balance': max(0, user_data['balance'] - challenge['wager'])})
                        challenge['p2_deducted'] = True
                    
                    challenge['p2_rolls'].append(score)
                    if len(challenge['p2_rolls']) >= challenge['rolls']:
                        challenge['waiting_p2'] = False
                    challenge['emoji_wait'] = datetime.now().isoformat()
                    self.db.save_data()
                    return
        challenge_id_to_resolve = None
        challenge_to_resolve = None
        
        for cid, challenge in self.pending_pvp.items():
            logger.info(f"Checking challenge {cid}: emoji={challenge.get('emoji')}, waiting_for_challenger={challenge.get('waiting_for_challenger_emoji')}, waiting={challenge.get('waiting_for_emoji')}, chat={challenge.get('chat_id')}, player={challenge.get('player')}, opponent={challenge.get('opponent')}")
            
            # Check if waiting for challenger's emoji
            if (challenge.get('waiting_for_challenger_emoji') and 
                challenge.get('emoji') == emoji and
                challenge.get('chat_id') == chat_id and
                challenge.get('challenger') == user_id):
                challenge_id_to_resolve = cid
                challenge_to_resolve = challenge
                logger.info(f"Found challenger emoji challenge: {cid}")
                
                # Wait for animation
                await asyncio.sleep(3)
                
                # Save challenger's roll and tell acceptor to go
                challenge['challenger_roll'] = roll_value
                challenge['waiting_for_challenger_emoji'] = False
                challenge['waiting_for_emoji'] = True
                challenge['emoji_wait_started'] = datetime.now().isoformat()
                self.pending_pvp[cid] = challenge
                self.db.data['pending_pvp'] = self.pending_pvp
                self.db.save_data()
                
                acceptor_user = self.db.get_user(challenge['opponent'])
                await context.bot.send_message(chat_id=chat_id, text=f"@{acceptor_user['username']} your turn", parse_mode="Markdown")
                return
            
            # Check if waiting for acceptor's emoji (or bot vs player)
            if (challenge.get('waiting_for_emoji') and 
                challenge.get('emoji') == emoji and
                challenge.get('chat_id') == chat_id):
                # Check if it's PvP (opponent) or bot vs player (player)
                if challenge.get('opponent') == user_id or challenge.get('player') == user_id:
                    challenge_id_to_resolve = cid
                    challenge_to_resolve = challenge
                    logger.info(f"Found matching challenge: {cid}")
                    break
        
        if not challenge_to_resolve or not challenge_id_to_resolve:
            logger.info("No matching pending game found")
            return  # Not a pending emoji response
        
        # Resolve the challenge
        await asyncio.sleep(3)  # Wait for emoji animation
        
        game_type = challenge_to_resolve['type']
        wager = challenge_to_resolve['wager']
        
        # Check if it's a bot vs player game
        if game_type in ['dice_bot', 'darts_bot', 'basketball_bot', 'soccer_bot', 'bowling_bot']:
            await self.resolve_bot_vs_player_game(update, context, challenge_to_resolve, challenge_id_to_resolve, roll_value)
            return
        
        # It's a PvP game
        challenger_id = challenge_to_resolve['challenger']
        challenger_roll = challenge_to_resolve['challenger_roll']
        acceptor_roll = roll_value
        
        challenger_user = self.db.get_user(challenger_id)
        acceptor_user = self.db.get_user(user_id)
        
        # Remove challenge from pending
        del self.pending_pvp[challenge_id_to_resolve]
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        # Determine winner
        winner_id = None
        loser_id = None
        result_text = ""

        # Normalize rolls for soccer: 4 and 5 are both goals (value 1), 1-3 are misses (value 0)
        c_val = challenger_roll
        a_val = acceptor_roll
        if game_type.startswith("soccer"):
            c_val = 1 if challenger_roll >= 4 else 0
            a_val = 1 if acceptor_roll >= 4 else 0

        if c_val > a_val:
            winner_id = challenger_id
            loser_id = user_id
            winner_user = self.db.get_user(winner_id)
            winner_display = f"<b>{winner_user.get('username', f'User{winner_id}')}</b>"
            result_text = f"🎉 {winner_display} won <b>${wager:,.2f}</b>"
        elif a_val > c_val:
            winner_id = user_id
            loser_id = challenger_id
            winner_user = self.db.get_user(winner_id)
            winner_display = f"<b>{winner_user.get('username', f'User{winner_id}')}</b>"
            result_text = f"🎉 {winner_display} won <b>${wager:,.2f}</b>"
        else:
            # Draw: refund both wagers (already deducted)
            self.db.update_user(challenger_id, {'balance': challenger_user['balance'] + wager})
            self.db.update_user(user_id, {'balance': acceptor_user['balance'] + wager})
            result_text = "🤝 Draw! Refunded"
            
            self._update_user_stats(challenger_id, wager, 0.0, "draw")
            self._update_user_stats(user_id, wager, 0.0, "draw")
            
            self.db.record_game({"type": f"{game_type}_pvp", "challenger": challenger_id, "opponent": user_id, "wager": wager, "result": "draw"})
            
            keyboard = [
                [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"{game_type}_bot_{wager:.2f}")],
                [InlineKeyboardButton("👥 Create PvP Challenge", callback_data=f"{game_type}_player_open_{wager:.2f}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(chat_id=chat_id, text=result_text, reply_markup=reply_markup, parse_mode="Markdown")
            return
        
        # Handle Win/Loss
        # Both players have already been deducted the 'wager' amount.
        # Winner gets both wagers (wager * 2)
        winnings = wager * 2
        winner_profit = wager
        
        winner_user = self.db.get_user(winner_id)
        # We need to update the balance properly. 
        # The user object retrieved might be stale if we used update_user earlier, 
        # but here we just need to add the winnings to their current state.
        self.db.update_user(winner_id, {'balance': winner_user['balance'] + winnings})
        
        self._update_user_stats(winner_id, wager, winner_profit, "win")
        # Fix: Don't subtract the wager again in _update_user_stats since it was already deducted at start
        self._update_user_stats(loser_id, wager, 0, "loss")
        
        self.db.add_transaction(winner_id, f"{game_type}_pvp_win", winner_profit, f"{game_type.upper()} PvP Win vs {self.db.get_user(loser_id)['username']}")
        self.db.add_transaction(loser_id, f"{game_type}_pvp_loss", -wager, f"{game_type.upper()} PvP Loss vs {self.db.get_user(winner_id)['username']}")
        self.db.record_game({"type": f"{game_type}_pvp", "challenger": challenger_id, "opponent": user_id, "wager": wager, "result": "win"})
        
        winner_username = winner_user.get('username', f'User{winner_id}')
        final_text = (
            f"🏆 <b>Game over!</b>\n\n"
            f"🎉 Congratulations, <b>{winner_username}</b>! You won <b>${wager:,.2f}</b>!"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 Play Again", callback_data=f"{game_type.replace('_pvp', '_bot')}_{wager:.2f}"),
                InlineKeyboardButton("🔄 Double", callback_data=f"{game_type.replace('_pvp', '_bot')}_{wager*2:.2f}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=final_text, 
            reply_markup=reply_markup, 
            parse_mode="HTML",
            reply_to_message_id=update.effective_message.message_id
        )

    async def resolve_bot_vs_player_game(self, update: Update, context: ContextTypes.DEFAULT_TYPE, challenge: Dict, challenge_id: str, player_roll: int):
        """Resolve a bot vs player game"""
        user_id = challenge['player']
        bot_roll = challenge['bot_roll']
        wager = challenge['wager']
        game_type = challenge['type']
        emoji = challenge['emoji']
        chat_id = challenge['chat_id']
        
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        
        # Remove from pending
        del self.pending_pvp[challenge_id]
        self.db.data['pending_pvp'] = self.pending_pvp
        self.db.save_data()
        
        # Determine result
        profit = 0.0
        result = "draw"

        # Normalize rolls for soccer: 4 and 5 are both goals (value 1), 1-3 are misses (value 0)
        p_val = player_roll
        b_val = bot_roll
        if game_type.startswith("soccer"):
            p_val = 1 if player_roll >= 4 else 0
            b_val = 1 if bot_roll >= 4 else 0

        if p_val > b_val:
            # WIN: Give back initial bet (already deducted) + profit (wager)
            profit = wager
            result = "win"
            user_data['balance'] += (wager * 2) # Wager back + profit
            self.db.update_user(user_id, user_data)
            
            # Winner display name bold without @
            user_display = f"<b>{user_data.get('username', f'User{user_id}')}</b>"
            result_text = (
                f"🏆 <b>Game over!</b>\n\n"
                f"🎉 Congratulations, <b>{user_display}</b>! You won <b>${profit:,.2f}</b>!"
            )
            self.db.update_house_balance(-wager)
        elif p_val < b_val:
            # LOSS: Already deducted, house keeps it
            profit = -wager
            result = "loss"
            result_text = f"💀 <b>Game over!</b>\n\n❌ <a href=\"tg://user?id=8575155625\">emojigamblebot</a> won <b>${wager:,.2f}</b>"
            self.db.update_house_balance(wager)
        else:
            # Draw - refund wager
            user_data['balance'] += wager
            self.db.update_user(user_id, user_data)
            username_display = user_data.get('username', f'User{user_id}')
            result_text = f"🤝 <b>Game over!</b>\n\n<b>{username_display}</b> - Draw, bet refunded"
        
        # Update stats (unless draw, which already refunded)
        if result != "draw":
            self._update_user_stats(user_id, wager, profit, result)
        
        self.db.add_transaction(user_id, game_type, profit, f"{game_type.upper().replace('_', ' ')} - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": game_type,
            "player_id": user_id,
            "wager": wager,
            "player_roll": player_roll,
            "bot_roll": bot_roll,
            "result": result
        })
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 Play Again", callback_data=f"{game_type.replace('_bot', '_bot')}_{wager:.2f}"),
                InlineKeyboardButton("🔄 Double", callback_data=f"{game_type.replace('_bot', '_bot')}_{wager*2:.2f}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=result_text, 
            reply_markup=reply_markup, 
            parse_mode="HTML",
            reply_to_message_id=update.effective_message.message_id if update.effective_message else None
        )

    async def coinflip_vs_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play coinflip against the bot (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        # Send coin emoji and determine result
        await context.bot.send_message(chat_id=chat_id, text="🪙")
        await asyncio.sleep(2)
        
        # Random coin flip result
        result = random.choice(['heads', 'tails'])
        
        # Determine result
        profit = 0.0
        outcome = "loss"
        
        if choice == result:
            profit = wager
            outcome = "win"
            user_display = f"@{username}" if user_data.get('username') else username
            result_text = f"✅ {user_display} won ${profit:.2f}"
            self.db.update_house_balance(-wager)
        else:
            profit = -wager
            user_display = f"@{username}" if user_data.get('username') else username
            result_text = f"❌ [emojigamblebot](tg://user?id=8575155625) won ${wager:.2f}"
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

        keyboard = [
            [InlineKeyboardButton("Heads again", callback_data=f"flip_bot_{wager:.2f}_heads")],
            [InlineKeyboardButton("Tails again", callback_data=f"flip_bot_{wager:.2f}_tails")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await self.send_with_buttons(chat_id, result_text, reply_markup, user_id)
        
        # Send sticker based on outcome
        await self.send_sticker(chat_id, outcome, profit)

    async def roulette_play_direct(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play roulette directly from command (for specific number bets)"""
        user_id = update.effective_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = update.message.chat_id
        
        if wager > user_data['balance']:
            await update.message.reply_text(f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
        blacks = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]
        greens = [0, 37]
        
        all_numbers = reds + blacks + greens
        result_num = random.choice(all_numbers)
        
        if result_num in reds:
            result_color = "red"
            result_emoji = "🔴"
        elif result_num in blacks:
            result_color = "black"
            result_emoji = "⚫"
        else:
            result_color = "green"
            result_emoji = "🟢"
            
        result_display = "0" if result_num == 0 else "00" if result_num == 37 else str(result_num)
        
        roulette_stickers = self.stickers.get('roulette', {})
        sticker_id = roulette_stickers.get(result_display)
        
        if sticker_id:
            await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
        else:
            await update.message.reply_text("🎰 Spinning the wheel...")
        
        await asyncio.sleep(2.5)
        
        if choice.startswith("num_"):
            bet_num = int(choice.split("_")[1])
            bet_display = "0" if bet_num == 0 else "00" if bet_num == 37 else str(bet_num)
            
            if bet_num == result_num:
                profit = wager * 35
                outcome = "win"
                user_display = f"@{username}" if user_data.get('username') else username
                result_text = f"✅ Won ${profit:.2f}!"
                self.db.update_house_balance(-profit)
            else:
                profit = -wager
                outcome = "loss"
                user_display = f"@{username}" if user_data.get('username') else username
                result_text = f"❌ [emojigamblebot](tg://user?id=8575155625) won ${wager:.2f}"
                self.db.update_house_balance(wager)
            
            self._update_user_stats(user_id, wager, profit, outcome)
            self.db.add_transaction(user_id, "roulette", profit, f"Roulette - Bet: #{bet_display} - Wager: ${wager:.2f}")
            self.db.record_game({
                "type": "roulette",
                "player_id": user_id,
                "wager": wager,
                "choice": f"#{bet_display}",
                "result": result_display,
                "result_color": result_color,
                "outcome": outcome
            })
            
            await update.message.reply_text(result_text, parse_mode="Markdown")

    async def roulette_play(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wager: float, choice: str):
        """Play roulette (called from button)"""
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        username = user_data.get('username', f'User{user_id}')
        chat_id = query.message.chat_id
        
        if wager > user_data['balance']:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Balance: ${user_data['balance']:.2f}")
            return
        
        reds = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
        blacks = [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]
        greens = [0, 37]
        
        all_numbers = reds + blacks + greens
        result_num = random.choice(all_numbers)
        
        if result_num in reds:
            result_color = "red"
            result_emoji = "🔴"
        elif result_num in blacks:
            result_color = "black"
            result_emoji = "⚫"
        else:
            result_color = "green"
            result_emoji = "🟢"
            
        result_display = "0" if result_num == 0 else "00" if result_num == 37 else str(result_num)
        
        roulette_stickers = self.stickers.get('roulette', {})
        sticker_id = roulette_stickers.get(result_display)
        
        if sticker_id:
            await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
        else:
            await context.bot.send_message(chat_id=chat_id, text="🎰 Spinning the wheel...")
        
        await asyncio.sleep(2.5)
        
        profit = 0.0
        outcome = "loss"
        multiplier = 0
        won = False
        bet_description = choice.upper()
        
        if choice == "red" and result_num in reds:
            won = True
            multiplier = 2
            bet_description = "RED"
        elif choice == "black" and result_num in blacks:
            won = True
            multiplier = 2
            bet_description = "BLACK"
        elif choice == "green" and result_num in greens:
            won = True
            multiplier = 14
            bet_description = "GREEN"
        elif choice == "odd" and result_num > 0 and result_num != 37 and result_num % 2 == 1:
            won = True
            multiplier = 2
            bet_description = "ODD"
        elif choice == "even" and result_num > 0 and result_num != 37 and result_num % 2 == 0:
            won = True
            multiplier = 2
            bet_description = "EVEN"
        elif choice == "low" and result_num >= 1 and result_num <= 18:
            won = True
            multiplier = 2
            bet_description = "LOW (1-18)"
        elif choice == "high" and result_num >= 19 and result_num <= 36:
            won = True
            multiplier = 2
            bet_description = "HIGH (19-36)"
        
        if won:
            profit = wager * (multiplier - 1)
            outcome = "win"
            user_display = f"@{username}" if user_data.get('username') else username
            result_text = f"✅ {user_display} won ${profit:.2f}"
            self.db.update_house_balance(-profit)
        else:
            profit = -wager
            outcome = "loss"
            user_display = f"@{username}" if user_data.get('username') else username
            result_text = f"❌ [emojigamblebot](tg://user?id=8575155625) won ${wager:.2f}"
            self.db.update_house_balance(wager)
        
        self._update_user_stats(user_id, wager, profit, outcome)
        self.db.add_transaction(user_id, "roulette", profit, f"Roulette - Bet: {bet_description} - Wager: ${wager:.2f}")
        self.db.record_game({
            "type": "roulette",
            "player_id": user_id,
            "wager": wager,
            "choice": choice,
            "result": result_display,
            "result_color": result_color,
            "outcome": outcome
        })
        
        keyboard = [
            [InlineKeyboardButton("Red (2x)", callback_data=f"roulette_{wager:.2f}_red"),
             InlineKeyboardButton("Black (2x)", callback_data=f"roulette_{wager:.2f}_black")],
            [InlineKeyboardButton("Green (14x)", callback_data=f"roulette_{wager:.2f}_green")],
            [InlineKeyboardButton("Odd (2x)", callback_data=f"roulette_{wager:.2f}_odd"),
             InlineKeyboardButton("Even (2x)", callback_data=f"roulette_{wager:.2f}_even")],
            [InlineKeyboardButton("Low (2x)", callback_data=f"roulette_{wager:.2f}_low"),
             InlineKeyboardButton("High (2x)", callback_data=f"roulette_{wager:.2f}_high")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.send_with_buttons(chat_id, result_text, reply_markup, user_id)

    # --- CALLBACK HANDLER ---

    async def start_generic_v2_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE, game: str, wager: float, rolls: int, mode: str, pts: int):
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat_id

        # Check for active game
        for active_cid, active_challenge in self.pending_pvp.items():
            if active_cid.startswith("v2_bot_") and active_challenge.get('player') == user_id:
                await query.answer("❌ You already have an active game! Finish it first.", show_alert=True)
                return

        user_data = self.db.get_user(user_id)
        if wager > user_data['balance']:
            await query.answer("❌ Insufficient balance", show_alert=True)
            return
            
        # Deduct balance immediately
        self.db.update_user(user_id, {"balance": user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, f"{game.capitalize()} vs Bot")
            
        cid = f"v2_bot_{game}_{user_id}_{int(datetime.now().timestamp())}"
        emoji_map = {"dice": "🎲", "darts": "🎯", "basketball": "🏀", "soccer": "⚽", "bowling": "🎳"}
        emoji = emoji_map.get(game, "🎲")
        
        self.pending_pvp[cid] = {
            "type": f"{game}_bot_v2", "player": user_id, "wager": wager, "game": game, "emoji": emoji,
            "rolls": rolls, "mode": mode, "pts": pts, "chat_id": chat_id,
            "p_pts": 0, "b_pts": 0, "p_rolls": [], "cur_rolls": 0, "emoji_wait": datetime.now().isoformat(),
            "wager_deducted": True, "message_id": query.message.message_id,
            "waiting_for_emoji": False # Not waiting for manual user roll anymore
        }
        self.db.update_pending_pvp(self.pending_pvp)
        
        p1_name = user_data.get('username', f'User{user_id}')
        msg_text = (
            f"{emoji} <b>Match accepted!</b>\n\n"
            f"Player 1: <b>{p1_name}</b>\n"
            f"Player 2: <b>Bot</b>\n\n"
            f"<b>{p1_name}</b>, your turn! To start, click the button below! {emoji}"
        )
        kb = [[InlineKeyboardButton("✅ Send emoji", callback_data=f"v2_send_emoji_{cid}")]]
        await context.bot.send_message(
            chat_id=chat_id, 
            text=msg_text, 
            reply_markup=InlineKeyboardMarkup(kb), 
            reply_to_message_id=query.message.message_id,
            parse_mode="HTML"
        )

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        data = query.data
        message_id = query.message.message_id
        
        if data.startswith("v2_send_emoji_"):
            cid = data.replace("v2_send_emoji_", "")
            challenge = self.pending_pvp.get(cid)
            if not challenge or challenge.get('player') != user_id:
                await query.answer("❌ Game no longer valid.", show_alert=True)
                return
            
            await query.answer()
            # Remove the button
            await query.edit_message_reply_markup(reply_markup=None)
            
            emoji = challenge['emoji']
            # Send emoji for user
            msg = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
            val = msg.dice.value
            score = (1 if val >= 4 else 0) if emoji in ["⚽", "🏀"] else val
            challenge['p_rolls'].append(score)
            
            await asyncio.sleep(4)
            
            p_tot = sum(challenge['p_rolls'])
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"<b>Rukia</b>, your turn!", 
                reply_to_message_id=query.message.message_id,
                parse_mode="HTML"
            )
            
            # Bot rolls
            b_tot = 0
            for _ in range(challenge['rolls']):
                await asyncio.sleep(2)
                d = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
                b_tot += (1 if d.dice.value >= 4 else 0) if emoji in ["⚽", "🏀"] else d.dice.value
                await asyncio.sleep(4)
            
            # Re-load challenge for safety
            self.pending_pvp = self.db.data.get('pending_pvp', {})
            challenge = self.pending_pvp.get(cid)
            if not challenge: return
            
            # Resolve Round/Series
            # Determing Round winner
            round_win = None
            if challenge.get('mode', 'normal') == "normal":
                if p_tot > b_tot: round_win = "p"
                elif b_tot > p_tot: round_win = "b"
            else:
                if p_tot < b_tot: round_win = "p"
                elif b_tot < p_tot: round_win = "b"
            
            if round_win == "p": challenge['p_pts'] += 1
            elif round_win == "b": challenge['b_pts'] += 1
            
            target_pts = challenge.get('pts', 1)
            if challenge['p_pts'] >= target_pts or challenge['b_pts'] >= target_pts:
                # Series End
                w = challenge['wager']
                if challenge['p_pts'] >= target_pts:
                    payout = w * 1.95
                    u = self.db.get_user(user_id)
                    u['balance'] += payout
                    self.db.update_user(user_id, {'balance': u['balance']})
                    self.db.update_house_balance(-(payout - w))
                    
                    p1_name = u.get('username', f'User{user_id}')
                    win_text = (
                        f"🏆 <b>Game over!</b>\n\n"
                        f"<b>Score:</b>\n"
                        f"{p1_name} • {challenge['p_pts']}\n"
                        f"Rukia • {challenge['b_pts']}\n\n"
                        f"🎉 Congratulations, <b>{p1_name}</b>! You won <b>${payout:,.2f}</b>!"
                    )
                    kb = [[InlineKeyboardButton("🔄 Play Again", callback_data=f"{challenge['game']}_bot_{w:.2f}"),
                           InlineKeyboardButton("🔄 Double", callback_data=f"{challenge['game']}_bot_{w*2:.2f}")]]
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=win_text, 
                        reply_markup=InlineKeyboardMarkup(kb), 
                        reply_to_message_id=query.message.message_id,
                        parse_mode="HTML"
                    )
                else:
                    self.db.update_house_balance(w)
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=f"💀 <b>DEFEAT!</b> Rukia won {challenge['b_pts']}-{challenge['p_pts']}. Lost ${w:.2f}", 
                        reply_to_message_id=query.message.message_id,
                        parse_mode="HTML"
                    )
                
                del self.pending_pvp[cid]
            else:
                # Next Round
                challenge['p_rolls'] = []
                u = self.db.get_user(user_id)
                p1_name = u.get('username', f'User{user_id}')
                text = (
                    f"{emoji} <b>Match accepted!</b>\n\n"
                    f"Player 1: <b>{p1_name}</b>\n"
                    f"Player 2: <b>Bot</b>\n\n"
                    f"<b>Score:</b>\n{p1_name}: {challenge['p_pts']}\nBot: {challenge['b_pts']}\n\n"
                    f"<b>{p1_name}</b>, your turn! To start, click the button below! {emoji}"
                )
                kb = [[InlineKeyboardButton("✅ Send emoji", callback_data=f"v2_send_emoji_{cid}")]]
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            
            self.db.update_pending_pvp(self.pending_pvp)
            return
        query = update.callback_query
        user_id = query.from_user.id
        user_data = self.db.get_user(user_id)
        
        if wager > user_data['balance']:
            await query.answer("❌ Insufficient balance", show_alert=True)
            return
            
        # Deduct balance immediately for challenger
        self.db.update_user(user_id, {"balance": user_data['balance'] - wager})
        self.db.add_transaction(user_id, "game_bet", -wager, f"{game.capitalize()} PvP (Challenger)")
            
        cid = f"v2_pvp_{game}_{user_id}_{int(datetime.now().timestamp())}"
        emoji_map = {"dice": "🎲", "darts": "🎯", "basketball": "🏀", "soccer": "⚽", "bowling": "🎳"}
        emoji = emoji_map.get(game, "🎲")
        
        self.pending_pvp[cid] = {
            "type": f"{game}_pvp_v2", "challenger": user_id, "opponent": None, "wager": wager, "game": game,
            "emoji": emoji, "rolls": rolls, "mode": mode, "pts": pts, "chat_id": query.message.chat_id,
            "p1_pts": 0, "p2_pts": 0, "p1_rolls": [], "p2_rolls": [], "waiting_p1": False, "waiting_p2": False,
            "emoji_wait": datetime.now().isoformat(),
            "p1_deducted": True, "p2_deducted": False
        }
        self.db.save_data()
        keyboard = [[InlineKeyboardButton("Join Challenge", callback_data=f"v2_accept_{cid}")]]
        msg_text = f"{emoji} **{game.capitalize()} PvP**\nChallenger: @{user_data['username']}\nWager: ${wager:.2f}\nMode: {mode.capitalize()}\nTarget: {pts}\n\nClick below to join!"
        await context.bot.send_message(chat_id=query.message.chat_id, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def accept_generic_v2_pvp(self, update: Update, context: ContextTypes.DEFAULT_TYPE, cid: str):
        query = update.callback_query
        user_id = query.from_user.id
        challenge = self.pending_pvp.get(cid)
        if not challenge or challenge['challenger'] == user_id:
            await query.answer("❌ Cannot join", show_alert=True)
            return
        
        user_data = self.db.get_user(user_id)
        if user_data['balance'] < challenge['wager']:
            await query.answer("❌ Insufficient balance", show_alert=True)
            return
            
        # Deduct balance for opponent
        self.db.update_user(user_id, {"balance": user_data['balance'] - challenge['wager']})
        self.db.add_transaction(user_id, "game_bet", -challenge['wager'], f"{challenge['game'].capitalize()} PvP (Opponent)")
            
        challenge['opponent'] = user_id
        challenge['p2_deducted'] = True
        await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Challenge Accepted! Starting...")
        asyncio.create_task(self.generic_v2_pvp_loop(context, cid))

    async def generic_v2_pvp_loop(self, context: ContextTypes.DEFAULT_TYPE, cid: str):
        challenge = self.pending_pvp.get(cid)
        if not challenge: return
        chat_id = challenge['chat_id']
        p1_id, p2_id = challenge['challenger'], challenge['opponent']
        p1_data, p2_data = self.db.get_user(p1_id), self.db.get_user(p2_id)
        
        while challenge['p1_pts'] < challenge['pts'] and challenge['p2_pts'] < challenge['pts']:
            await context.bot.send_message(chat_id=chat_id, text=f"Round Start! Score: {challenge['p1_pts']} - {challenge['p2_pts']}\n👉 @{p1_data['username']}, send your {challenge['rolls']} {challenge['emoji']} now!")
            challenge['p1_rolls'], challenge['p2_rolls'] = [], []
            challenge['waiting_p1'], challenge['waiting_p2'] = True, False
            challenge['emoji_wait'] = datetime.now().isoformat()
            self.db.save_data()
            while len(challenge['p1_rolls']) < challenge['rolls'] or len(challenge['p2_rolls']) < challenge['rolls']:
                await asyncio.sleep(2)
                challenge = self.pending_pvp.get(cid)
                if not challenge: return
            
            p1_tot, p2_tot = sum(challenge['p1_rolls']), sum(challenge['p2_rolls'])
            win = None
            if challenge['mode'] == "normal":
                if p1_tot > p2_tot: win = "p1"
                elif p2_tot > p1_tot: win = "p2"
            else:
                if p1_tot < p2_tot: win = "p1"
                elif p2_tot < p1_tot: win = "p2"
            
            if win == "p1": challenge['p1_pts'] += 1
            elif win == "p2": challenge['p2_pts'] += 1
            
            p1_username = p1_data.get('username', f'User{p1_id}')
            p2_username = p2_data.get('username', f'User{p2_id}')
            score_text = f"<b>{p1_username}</b>: {challenge['p1_pts']}\n<b>{p2_username}</b>: {challenge['p2_pts']}"
            await context.bot.send_message(chat_id=chat_id, text=f"Round Result: {p1_tot} vs {p2_tot}. Point to {'you' if win else 'Draw'}!\n\n{score_text}", parse_mode="HTML")
            await asyncio.sleep(1)

        wager = challenge['wager']
        winner_id = p1_id if challenge['p1_pts'] >= challenge['pts'] else p2_id
        loser_id = p2_id if winner_id == p1_id else p1_id
        # Both players already had wager deducted when accepting/starting
        # Winner gets (wager * 2) total payout
        self.db.update_user(winner_id, {'balance': self.db.get_user(winner_id)['balance'] + wager})
        self._update_user_stats(winner_id, wager, wager, "win")
        # Fix: Don't subtract the wager again in _update_user_stats since it was already deducted at start
        self._update_user_stats(loser_id, wager, 0, "loss")
        
        winner_data = self.db.get_user(winner_id)
        winner_username = winner_data.get('username', f'User{winner_id}')
        payout = wager * 1.95 # Adjusted for house edge if needed, or wager*2 for pvp.
        # User requested bolded name without @ and bolded amount
        win_msg = f"🏆 <b>{winner_username}</b> won <b>${wager*2:.2f}</b>!"
        
        await context.bot.send_message(chat_id=chat_id, text=win_msg, parse_mode="HTML")
        del self.pending_pvp[cid]
        self.db.save_data()

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        data = query.data
        message_id = query.message.message_id
        ownership_key = (chat_id, message_id)

        # Check if button was already clicked (prevent spam)
        button_key = (chat_id, message_id, data)
        if button_key in self.clicked_buttons:
            await query.answer("❌ This button has already been used!", show_alert=True)
            return

        # Ensure user is registered
        self.ensure_user_registered(update)

        if data.startswith("v2_send_emoji_"):
            cid = data.replace("v2_send_emoji_", "")
            challenge = self.pending_pvp.get(cid)
            if not challenge or challenge.get('player') != user_id:
                await query.answer("❌ Game no longer valid.", show_alert=True)
                return
            
            await query.answer()
            self.clicked_buttons.add(button_key)
            # Remove the button
            await query.edit_message_reply_markup(reply_markup=None)
            
            emoji = challenge['emoji']
            # Send emoji for user
            msg = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
            val = msg.dice.value
            score = (1 if val >= 4 else 0) if emoji in ["⚽", "🏀"] else val
            challenge['p_rolls'].append(score)
            
            await asyncio.sleep(4)
            
            p_tot = sum(challenge['p_rolls'])
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"<b>Rukia</b>, your turn!", 
                reply_to_message_id=query.message.message_id,
                parse_mode="HTML"
            )
            
            # Bot rolls
            b_tot = 0
            for _ in range(challenge['rolls']):
                await asyncio.sleep(2)
                d = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
                b_tot += (1 if d.dice.value >= 4 else 0) if emoji in ["⚽", "🏀"] else d.dice.value
                await asyncio.sleep(4)
            
            # Re-load challenge for safety
            self.pending_pvp = self.db.data.get('pending_pvp', {})
            challenge = self.pending_pvp.get(cid)
            if not challenge: return
            
            # Determine Round winner
            round_win = None
            if challenge.get('mode', 'normal') == "normal":
                if p_tot > b_tot: round_win = "p"
                elif b_tot > p_tot: round_win = "b"
            else:
                if p_tot < b_tot: round_win = "p"
                elif b_tot < p_tot: round_win = "b"
            
            if round_win == "p": challenge['p_pts'] += 1
            elif round_win == "b": challenge['b_pts'] += 1
            
            target_pts = challenge.get('pts', 1)
            if challenge['p_pts'] >= target_pts or challenge['b_pts'] >= target_pts:
                # Series End
                w = challenge['wager']
                if challenge['p_pts'] >= target_pts:
                    payout = w * 1.95
                    u = self.db.get_user(user_id)
                    u['balance'] += payout
                    self.db.update_user(user_id, {'balance': u['balance']})
                    self.db.update_house_balance(-(payout - w))
                    
                    p1_name = u.get('username', f'User{user_id}')
                    win_text = (
                        f"🏆 <b>Game over!</b>\n\n"
                        f"<b>Score:</b>\n"
                        f"{p1_name} • {challenge['p_pts']}\n"
                        f"Rukia • {challenge['b_pts']}\n\n"
                        f"🎉 Congratulations, <b>{p1_name}</b>! You won <b>${payout:,.2f}</b>!"
                    )
                    kb = [[InlineKeyboardButton("🔄 Play Again", callback_data=f"{challenge['game']}_bot_{w:.2f}"),
                           InlineKeyboardButton("🔄 Double", callback_data=f"{challenge['game']}_bot_{w*2:.2f}")]]
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=win_text, 
                        reply_markup=InlineKeyboardMarkup(kb), 
                        reply_to_message_id=query.message.message_id,
                        parse_mode="HTML"
                    )
                else:
                    self.db.update_house_balance(w)
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=f"💀 <b>DEFEAT!</b> Rukia won {challenge['b_pts']}-{challenge['p_pts']}. Lost ${w:.2f}", 
                        reply_to_message_id=query.message.message_id,
                        parse_mode="HTML"
                    )
                
                del self.pending_pvp[cid]
            else:
                # Next Round
                challenge['p_rolls'] = []
                u = self.db.get_user(user_id)
                p1_name = u.get('username', f'User{user_id}')
                text = (
                    f"{emoji} <b>Match accepted!</b>\n\n"
                    f"Player 1: <b>{p1_name}</b>\n"
                    f"Player 2: <b>Bot</b>\n\n"
                    f"<b>Score:</b>\n{p1_name}: {challenge['p_pts']}\nBot: {challenge['b_pts']}\n\n"
                    f"<b>{p1_name}</b>, your turn! To start, click the button below! {emoji}"
                )
                kb = [[InlineKeyboardButton("✅ Send emoji", callback_data=f"v2_send_emoji_{cid}")]]
                await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            
            self.db.update_pending_pvp(self.pending_pvp)
            return

        if data.startswith("cashout_"):
            cid = data.split("_", 1)[1]
            challenge = self.pending_pvp.get(cid)
            if not challenge or challenge.get('player') != user_id:
                await query.answer("❌ Game no longer valid.", show_alert=True)
                return
            
            # Cashout logic: Refund wager (since game is in progress)
            wager = challenge['wager']
            user_data = self.db.get_user(user_id)
            user_data['balance'] += wager
            self.db.update_user(user_id, user_data)
            self.db.add_transaction(user_id, "cashout", wager, f"Cashout from {challenge['game']}")
            
            del self.pending_pvp[cid]
            self.db.save_data()
            
            await query.answer("💰 Cashed out successfully!", show_alert=True)
            await query.edit_message_text(f"💰 <b>Cashed Out!</b>\n\nRefunded ${wager:,.2f} to your balance.", parse_mode="HTML")
            return
            
        try:
            # First handle "none" to avoid any other processing
            if data == "none":
                try:
                    await query.answer()
                except:
                    pass
                return

            # Custom menu switching
            if data.startswith("predict_menu_") or data.startswith("emoji_setup_") or data.startswith("setup_bet_"):
                # Always allow bet adjustments regardless of ownership for better UX
                pass
            elif ownership_key in self.button_ownership:
                owner_id = self.button_ownership[ownership_key]
                if user_id != owner_id:
                    await query.answer("❌ This is not your game/menu!", show_alert=True)
                    return

            if data == "none":
                try:
                    await query.answer()
                except:
                    pass
                return

            if data.startswith("emoji_setup_"):
                parts = data.split("_")
                if len(parts) >= 5:
                    game_mode = parts[2]
                    wager = float(parts[3])
                    step = parts[4]
                    
                    # Parse params from suffix
                    params = {}
                    if step == "mode":
                        # emoji_setup_{game_mode}_{wager}_mode
                        pass
                    elif step == "rolls":
                        # emoji_setup_{game_mode}_{wager}_rolls_{mode}
                        params["mode"] = parts[5] if len(parts) > 5 else "normal"
                    elif step == "points":
                        # emoji_setup_{game_mode}_{wager}_points_{rolls}_{mode}
                        params["rolls"] = int(parts[5]) if len(parts) > 5 else 1
                        params["mode"] = parts[6] if len(parts) > 6 else "normal"
                    elif step == "final":
                        # emoji_setup_{game_mode}_{wager}_final_{pts}_{rolls}_{mode}_{opt_opponent}
                        params["pts"] = int(parts[5]) if len(parts) > 5 else 1
                        params["rolls"] = int(parts[6]) if len(parts) > 6 else 1
                        params["mode"] = parts[7] if len(parts) > 7 else "normal"
                        if len(parts) > 8:
                            params["opponent"] = parts[8]

                    await self._show_emoji_game_setup(update, context, wager, game_mode, step, params)
                    return

            if data.startswith("predict_menu_"):
                parts = data.split("_")
                wager = float(parts[2])
                game_mode = parts[3]
                await self._show_game_prediction_menu(update, context, wager, game_mode)
                return

            if data.startswith("setup_bet_"):
                parts = data.split("_")
                action = parts[2]
                wager = float(parts[3])
                game_mode = parts[4]
                
                new_wager = wager
                if action == "half":
                    new_wager = wager / 2
                elif action == "double":
                    new_wager = wager * 2
                    
                if new_wager < 1.0:
                    try:
                        await query.answer("❌ Minimum bet is $1.00", show_alert=False)
                    except:
                        pass
                    return
                
                try:
                    await query.answer()
                except:
                    pass
                    
                await self._show_game_prediction_menu(update, context, new_wager, game_mode)
                return
        except Exception as e:
            logger.error(f"Error in button_callback: {e}")
            return

    async def soccer_player_v2_loop(self, context: ContextTypes.DEFAULT_TYPE, challenge_id: str):
        """Manage the loop for a Soccer V2 PvP game - Manual Emoji Submission"""
        challenge = self.pending_pvp.get(challenge_id)
        if not challenge: return
        
        chat_id = challenge['chat_id']
        p1_id = challenge['challenger']
        p2_id = challenge['opponent']
        p1_data = self.db.get_user(p1_id)
        p2_data = self.db.get_user(p2_id)
        
        while challenge['p1_points'] < challenge['pts'] and challenge['p2_points'] < challenge['pts']:
            # Round Start
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"⚽ **Round Start!**\nSeries Score: @{p1_data['username']} {challenge['p1_points']} - {challenge['p2_points']} @{p2_data['username']}\n"
                     f"👉 @{p1_data['username']}, send your {challenge['rolls']} ⚽ emoji(s) now!",
                parse_mode="Markdown"
            )
            
            # Reset turn rolls
            challenge['p1_turn_rolls'] = []
            challenge['p2_turn_rolls'] = []
            challenge['waiting_for_p1'] = True
            challenge['waiting_for_p2'] = False
            challenge['emoji_wait_started'] = datetime.now().isoformat()
            self.db.save_data()
            
            # We use a loop with sleep to check if both players rolled. 
            # In a real bot, we'd handle this via the event loop, but for simplicity:
            while len(challenge['p1_turn_rolls']) < challenge['rolls'] or len(challenge['p2_turn_rolls']) < challenge['rolls']:
                await asyncio.sleep(2)
                challenge = self.pending_pvp.get(challenge_id)
                if not challenge: return # Expired/Cancelled
                
            # Round Result
            p1_total = sum(challenge['p1_turn_rolls'])
            p2_total = sum(challenge['p2_turn_rolls'])
            
            win = None
            if challenge['mode'] == "normal":
                if p1_total > p2_total: win = "p1"
                elif p2_total > p1_total: win = "p2"
            else:
                if p1_total < p2_total: win = "p1"
                elif p2_total < p1_total: win = "p2"
                
            if win == "p1": challenge['p1_points'] += 1
            elif win == "p2": challenge['p2_points'] += 1
            
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"Round Result: @{p1_data['username']} {p1_total} vs @{p2_data['username']} {p2_total}\n"
                     f"Point to {'you' if win else 'Draw'}!"
            )

    async def matches_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show previous 10 matches with pagination"""
        self.ensure_user_registered(update)
        user_id = update.effective_user.id
        await self.show_matches_page(update, 0, user_id)

    async def show_matches_page(self, update: Update, page: int, user_id: int):
        # Fetch games from database
        user_games = []
        with self.db.app.app_context():
            from sqlalchemy import select, or_, cast, String
            from models import Game
            # Use cast(Game.data['field'], String) instead of .astext for compatibility
            # Also handle potential lack of index or different JSONB operator support in the environment
            query = select(Game).order_by(Game.id.desc())
            db_games = db.session.execute(query).scalars().all()
            
            search_id = str(user_id)
            for g in db_games:
                data = g.data
                if (str(data.get('player_id')) == search_id or 
                    str(data.get('challenger')) == search_id or 
                    str(data.get('opponent')) == search_id):
                    user_games.append(data)
        
        total_pages = (len(user_games) + 4) // 5
        if total_pages == 0:
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text("📜 No matches found.")
            else:
                await update.message.reply_text("📜 No matches found.")
            return

        start_idx = page * 5
        end_idx = start_idx + 5
        page_games = user_games[start_idx:end_idx]
        
        text = f"📜 **Your Matches (Page {page + 1}/{total_pages})**\n\n"
        for g in page_games:
            ts = g.get('timestamp', '')
            time_str = datetime.fromisoformat(ts).strftime("%m/%d %H:%M") if ts else "N/A"
            wager = g.get('wager', 0.0)
            
            game_emojis = {
                "dice": "🎲", "darts": "🎯", "basketball": "🏀",
                "soccer": "⚽", "bowling": "🎳", "slots": "🎰",
                "coinflip": "🪙", "blackjack": "🃏", "roulette": "🎡"
            }
            
            raw_type = g.get('type', 'Game').split('_')[0].lower()
            emoji_icon = game_emojis.get(raw_type, "")
            g_display = emoji_icon if emoji_icon else raw_type.capitalize()
            
            # Extract result/score/winner
            result = g.get('result', g.get('outcome', 'N/A')).capitalize()
            winner_name = "N/A"
            
            is_pvp = "_pvp" in g.get('type', '')
            if is_pvp:
                p1_id = g.get('challenger')
                p2_id = g.get('opponent')
                
                # Get usernames
                p1_data = self.db.get_user(p1_id)
                p2_data = self.db.get_user(p2_id)
                p1_user = f"@{p1_data['username']}" if p1_data.get('username') else f"User {p1_id}"
                p2_user = f"@{p2_data['username']}" if p2_data.get('username') else f"User {p2_id}"
                
                match_up = f"{p1_user} vs {p2_user}"
                
                if result.lower() == "win":
                    winner_name = p1_user
                else:
                    winner_name = p2_user
            else:
                p_id = g.get('player_id')
                p_data = self.db.get_user(p_id)
                p_user = f"@{p_data['username']}" if p_data.get('username') else f"User {p_id}"
                
                match_up = f"{p_user} vs Bot"
                
                if result.lower() == "win":
                    winner_name = p_user
                elif result.lower() in ["loss", "defeat"]:
                    winner_name = "@botusername"
                elif result.lower() == "draw":
                    winner_name = "Draw"
            
            score = ""
            if 'p_pts' in g and 'b_pts' in g:
                score = f" (Score: {g['p_pts']}-{g['b_pts']})"
            elif 'p1_pts' in g and 'p2_pts' in g:
                score = f" (Score: {g['p1_pts']}-{g['p2_pts']})"
            
            text += f"*{time_str}* | **{g_display}** | Bet: `${wager:.2f}`\n"
            text += f"{match_up}\n"
            text += f"Winner: {winner_name}{score}\n\n"
            
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"match_page_{page-1}_{user_id}"))
        if page < total_pages - 1:
            buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"match_page_{page+1}_{user_id}"))
            
        reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            sent_msg = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
            self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handles all inline button presses."""
        query = update.callback_query
        
        # Ensure user is registered and username is updated
        self.ensure_user_registered(update)
        
        data = query.data
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        
        # Check if button was already clicked (prevent spam)
        button_key = (chat_id, message_id, data)
        if button_key in self.clicked_buttons:
            await query.answer("❌ This button has already been used!", show_alert=True)
            return
        
        # Check button ownership
        public_buttons = ["v2_accept_", "lb_page_", "match_page_", "transactions_history", "deposit_mock", "withdraw_mock"]
        is_public = any(data.startswith(prefix) for prefix in public_buttons)
        
        ownership_key = (chat_id, message_id)
        if not is_public and ownership_key in self.button_ownership:
            if self.button_ownership[ownership_key] != user_id:
                await query.answer("❌ This button is not for you!", show_alert=True)
                return
        
        await query.answer()
        
        # Mark button as clicked for game buttons
        if any(data.startswith(prefix) for prefix in ["v2_bot_", "v2_pvp_", "v2_accept_", "roulette_", "claim_daily_bonus", "claim_referral"]):
            self.clicked_buttons.add(button_key)
        
        try:
            if data == "none":
                try:
                    await query.answer()
                except:
                    pass
                return

            if data.startswith("match_page_"):
                parts = data.split('_')
                if len(parts) < 4:
                    await query.answer("❌ Invalid match page data!", show_alert=True)
                    return
                page = int(parts[2])
                target_user_id = int(parts[3])
                await self.show_matches_page(update, page, target_user_id)
                return

            # Emoji game setup callbacks
            if data.startswith("v2_send_emoji_"):
                cid = data.replace("v2_send_emoji_", "")
                challenge = self.pending_pvp.get(cid)
                if not challenge or challenge.get('player') != user_id:
                    await query.answer("❌ Game no longer valid.", show_alert=True)
                    return
                
                await query.answer()
                # Remove the button
                await query.edit_message_reply_markup(reply_markup=None)
                
                emoji = challenge['emoji']
                # Send emoji for user
                msg = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
                val = msg.dice.value
                score = (1 if val >= 4 else 0) if emoji in ["⚽", "🏀"] else val
                challenge['p_rolls'].append(score)
                
                await asyncio.sleep(4)
                
                p_tot = sum(challenge['p_rolls'])
                await context.bot.send_message(chat_id=chat_id, text=f"<b>Rukia</b>, your turn!", parse_mode="HTML")
                
                # Bot rolls
                b_tot = 0
                for _ in range(challenge['rolls']):
                    await asyncio.sleep(2)
                    d = await context.bot.send_dice(chat_id=chat_id, emoji=emoji)
                    b_tot += (1 if d.dice.value >= 4 else 0) if emoji in ["⚽", "🏀"] else d.dice.value
                    await asyncio.sleep(4)
                
                # Re-load challenge for safety
                self.pending_pvp = self.db.data.get('pending_pvp', {})
                challenge = self.pending_pvp.get(cid)
                if not challenge: return
                
                # Resolve Round/Series
                round_win = None
                if challenge.get('mode', 'normal') == "normal":
                    if p_tot > b_tot: round_win = "p"
                    elif b_tot > p_tot: round_win = "b"
                else:
                    if p_tot < b_tot: round_win = "p"
                    elif b_tot < p_tot: round_win = "b"
                
                if round_win == "p": challenge['p_pts'] += 1
                elif round_win == "b": challenge['b_pts'] += 1
                
                target_pts = challenge.get('pts', 1)
                if challenge['p_pts'] >= target_pts or challenge['b_pts'] >= target_pts:
                    # Series End
                    w = challenge['wager']
                    if challenge['p_pts'] >= target_pts:
                        payout = w * 1.95
                        u = self.db.get_user(user_id)
                        u['balance'] += payout
                        self.db.update_user(user_id, {'balance': u['balance']})
                        self.db.update_house_balance(-(payout - w))
                        
                        p1_name = u.get('username', f'User{user_id}')
                        win_text = (
                            f"🏆 <b>Game over!</b>\n\n"
                            f"<b>Score:</b>\n"
                            f"{p1_name} • {challenge['p_pts']}\n"
                            f"Rukia • {challenge['b_pts']}\n\n"
                            f"🎉 Congratulations, <b>{p1_name}</b>! You won <b>${payout:,.2f}</b>!"
                        )
                        kb = [[InlineKeyboardButton("🔄 Play Again", callback_data=f"v2_bot_{challenge['game']}_{w:.2f}_{challenge['rolls']}_{challenge['mode']}_{target_pts}"),
                               InlineKeyboardButton("🔄 Double", callback_data=f"v2_bot_{challenge['game']}_{w*2:.2f}_{challenge['rolls']}_{challenge['mode']}_{target_pts}")]]
                        await context.bot.send_message(chat_id=chat_id, text=win_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                    else:
                        self.db.update_house_balance(w)
                        u = self.db.get_user(user_id)
                        p1_name = u.get('username', f'User{user_id}')
                        loss_text = (
                            f"🏆 <b>Game over!</b>\n\n"
                            f"<b>Score:</b>\n"
                            f"{p1_name} • {challenge['p_pts']}\n"
                            f"Rukia • {challenge['b_pts']}\n\n"
                            f"<b>Rukia</b> wins <b>${w * 1.95:,.2f}</b>"
                        )
                        kb = [[InlineKeyboardButton("🔄 Play Again", callback_data=f"v2_bot_{challenge['game']}_{w:.2f}_{challenge['rolls']}_{challenge['mode']}_{target_pts}"),
                               InlineKeyboardButton("🔄 Double", callback_data=f"v2_bot_{challenge['game']}_{w*2:.2f}_{challenge['rolls']}_{challenge['mode']}_{target_pts}")]]
                        await context.bot.send_message(chat_id=chat_id, text=loss_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                    
                    del self.pending_pvp[cid]
                else:
                    # Next Round
                    challenge['p_rolls'] = []
                    u = self.db.get_user(user_id)
                    p1_name = u.get('username', f'User{user_id}')
                    text = (
                        f"<b>Score</b>\n\n"
                        f"{p1_name}: {challenge['p_pts']}\n"
                        f"Rukia: {challenge['b_pts']}\n\n"
                        f"<b>{p1_name}</b>, your turn! To start, click the button below! {emoji}"
                    )
                    cashout_val = self.calculate_cashout(challenge['p_pts'], challenge['b_pts'], challenge['pts'], challenge['wager'])
                    cashout_multiplier = round(cashout_val / challenge['wager'], 2) if challenge['wager'] > 0 else 0
                    kb = [
                        [InlineKeyboardButton("✅ Send emoji", callback_data=f"v2_send_emoji_{cid}")],
                        [InlineKeyboardButton(f"💰 Cashout ${cashout_val:.2f} ({cashout_multiplier}x)", callback_data=f"v2_cashout_{cid}")]
                    ]
                    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                
                self.db.update_pending_pvp(self.pending_pvp)
                return

            if data == "button_unavailable":
                await query.answer("❌ This button is no longer available as the game has started!", show_alert=True)
                return

            if data == "none":
                try:
                    await query.answer()
                except:
                    pass
                return

            if data.startswith("emoji_setup_"):
                parts = data.split("_")
                # Parts: emoji_setup, game_mode, wager, step, [pts, rolls, mode, opponent]
                if len(parts) < 5:
                    await query.answer("❌ Invalid setup data!", show_alert=True)
                    return
                g_mode = parts[1] # Fix index: data.split("_") -> ["emoji", "setup", game_mode, wager, step, ...]
                wager = float(parts[3])
                next_step = parts[4]
                
                params = {}
                if next_step == "rolls":
                    if len(parts) > 5:
                        params["mode"] = parts[5]
                elif next_step == "points":
                    if len(parts) > 5:
                        params["rolls"] = int(parts[5])
                    if len(parts) > 6:
                        params["mode"] = parts[6]
                elif next_step == "final":
                    if len(parts) > 5:
                        params["pts"] = int(parts[5])
                    if len(parts) > 6:
                        params["rolls"] = int(parts[6])
                    if len(parts) > 7:
                        params["mode"] = parts[7]
                    if len(parts) > 8:
                        params["opponent"] = parts[8]
                elif next_step == "start":
                    if len(parts) >= 8:
                        pts = int(parts[5])
                        rolls = int(parts[6])
                        mode = parts[7]
                        
                        # Start the game
                        await self.start_generic_v2_bot(update, context, g_mode, wager, rolls, mode, pts)
                        
                        # Mark the message as "started" in the context of button interaction
                        try:
                            current_markup = query.message.reply_markup
                            if current_markup:
                                new_keyboard = []
                                for row in current_markup.inline_keyboard:
                                    new_row = []
                                    for button in row:
                                        new_row.append(InlineKeyboardButton(
                                            text=button.text,
                                            callback_data="button_unavailable"
                                        ))
                                    new_keyboard.append(new_row)
                                
                                await query.edit_message_reply_markup(
                                    reply_markup=InlineKeyboardMarkup(new_keyboard)
                                )
                        except Exception as e:
                            logger.error(f"Error updating buttons to unavailable: {e}")
                        return
                
                elif next_step == "mode":
                    # Cycle emoji modes
                    await self._show_emoji_game_setup(update, context, wager, g_mode, "mode", params)
                    return
                
                await self._show_emoji_game_setup(update, context, wager, g_mode, next_step, params)
                return

            # Custom menu switching
            if data.startswith("predict_menu_") or data.startswith("emoji_setup_"):
                parts = data.split("_")
                wager_idx = 2 if data.startswith("predict_menu_") else 3
                try:
                    wager = float(parts[wager_idx])
                    if wager < 1.0:
                        # Auto-fix wager if it's below minimum
                        new_parts = list(parts)
                        new_parts[wager_idx] = "1.00"
                        data = "_".join(new_parts)
                        await query.answer("⚠️ Minimum bet is $1.00. Adjusted to $1.00.", show_alert=True)
                except (ValueError, IndexError):
                    pass

            if data == "none":
                try:
                    await query.answer()
                except:
                    pass
                return

            if data.startswith("emoji_setup_"):
                parts = data.split("_")
                if len(parts) >= 5:
                    game_mode = parts[2]
                    wager = float(parts[3])
                    step = parts[4]
                    
                    # Parse params from suffix
                    params = {}
                    if step == "mode":
                        # emoji_setup_{game_mode}_{wager}_mode
                        pass
                    elif step == "rolls":
                        # emoji_setup_{game_mode}_{wager}_rolls_{mode}
                        params["mode"] = parts[5] if len(parts) > 5 else "normal"
                    elif step == "points":
                        # emoji_setup_{game_mode}_{wager}_points_{rolls}_{mode}
                        params["rolls"] = int(parts[5]) if len(parts) > 5 else 1
                        params["mode"] = parts[6] if len(parts) > 6 else "normal"
                    elif step == "final":
                        # emoji_setup_{game_mode}_{wager}_final_{pts}_{rolls}_{mode}_{opt_opponent}
                        params["pts"] = int(parts[5]) if len(parts) > 5 else 1
                        params["rolls"] = int(parts[6]) if len(parts) > 6 else 1
                        params["mode"] = parts[7] if len(parts) > 7 else "normal"
                        if len(parts) > 8:
                            params["opponent"] = parts[8]

                    await self._show_emoji_game_setup(update, context, wager, game_mode, step, params)
                    return

            if data.startswith("predict_menu_"):
                parts = data.split("_")
                wager = float(parts[2])
                game_mode = parts[3]
                await self._show_game_prediction_menu(update, context, wager, game_mode)
                return

            if data.startswith("setup_bet_"):
                parts = data.split("_")
                action = parts[2]
                wager = float(parts[3])
                game_mode = parts[4]
                
                new_wager = wager
                if action == "half":
                    new_wager = wager / 2
                elif action == "double":
                    new_wager = wager * 2
                    
                if new_wager < 1.0:
                    try:
                        await query.answer("❌ Minimum bet is $1.00", show_alert=False)
                    except Exception as e:
                        logger.error(f"Error answering query: {e}")
                    return
                
                try:
                    await query.answer()
                except:
                    pass
                    
                await self._show_game_prediction_menu(update, context, new_wager, game_mode)
                return

            if data.startswith("setup_mode_dice_"):
                wager = float(data.split("_")[3])
                await self._show_game_prediction_menu(update, context, wager, "dice")
                return

            if data.startswith("setup_mode_darts_"):
                wager = float(data.split("_")[3])
                await self._show_game_prediction_menu(update, context, wager, "darts")
                return

            if data.startswith("setup_mode_basketball_"):
                wager = float(data.split("_")[3])
                await self._show_game_prediction_menu(update, context, wager, "basketball")
                return

            if data.startswith("setup_mode_soccer_"):
                wager = float(data.split("_")[3])
                await self._show_game_prediction_menu(update, context, wager, "soccer")
                return

            if data.startswith("setup_mode_bowling_"):
                wager = float(data.split("_")[3])
                await self._show_game_prediction_menu(update, context, wager, "bowling")
                return

            if data.startswith("flip_bot_"):
                wager = float(data.split("_")[2])
                await self._show_game_prediction_menu(update, context, wager, "coinflip")
                return

            if data.startswith("setup_mode_predict_"):
                parts = data.split("_")
                wager = float(parts[3])
                game_mode = parts[4] if len(parts) > 4 else "dice"
                await self._setup_predict_interface(update, context, wager, game_mode)
                return
            
            elif data == "setup_cancel":
                await query.message.delete()
                return

            elif data.startswith("setup_bet_back_"):
                parts = data.split("_")
                if len(parts) < 4:
                    await query.answer("❌ Invalid button data!", show_alert=True)
                    return
                wager = float(parts[3])
                await self.bet_command(update, context, amount=wager)
                return
            
            if data.startswith("setup_predict_select_") or data.startswith("predict_start_"):
                from predict_handler import handle_predict
                await handle_predict(self, update, context)
                return

            if ownership_key in self.button_ownership:
                owner_id = self.button_ownership[ownership_key]
                if user_id != owner_id:
                    await query.answer("❌ This is not your game/menu!", show_alert=True)
                    return

            if data == "tip_cancel":
                await query.message.delete()
                return
                
            elif data.startswith("tip_confirm_"):
                parts = data.split("_")
                target_id = int(parts[2])
                amount = float(parts[3])
                
                user_data = self.db.get_user(user_id)
                if user_data['balance'] < amount:
                    await query.answer("❌ Insufficient balance!", show_alert=True)
                    return
                    
                recipient_data = self.db.get_user(target_id)
                
                # Perform transaction
                user_data['balance'] -= amount
                recipient_data['balance'] += amount
                
                self.db.update_user(user_id, user_data)
                self.db.update_user(target_id, recipient_data)
                
                self.db.add_transaction(user_id, "tip_sent", -amount, f"Tip to @{recipient_data.get('username', target_id)}")
                self.db.add_transaction(target_id, "tip_received", amount, f"Tip from @{user_data.get('username', user_id)}")
                
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Tip successful! **{recipient_data.get('username', target_id)}** receives **${amount:.2f}**!",
                    parse_mode="Markdown"
                )
                
                # Notify receiver
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text=f"🎁 You received a tip of **${amount:.2f}** from **{user_data.get('username', user_id)}**!",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                return

            # Generic game setup (Initial step from /bet menu)
            if data.startswith("setup_mode_") and not (data.startswith("setup_mode_normal_") or data.startswith("setup_mode_crazy_")):
                parts = data.split("_")
                if len(parts) >= 3:
                    game, wager = parts[2], float(parts[3])
                    keyboard = [
                        [InlineKeyboardButton("Normal", callback_data=f"setup_mode_normal_{game}_{wager:.2f}"),
                         InlineKeyboardButton("Crazy", callback_data=f"setup_mode_crazy_{game}_{wager:.2f}")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}**\nWager: ${wager:.2f}\n\nChoose Game Mode:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            # Generic setup handlers
            elif data.startswith("setup_mode_normal_"):
                parts = data.split('_')
                if len(parts) >= 4:
                    game, wager = parts[3], float(parts[4])
                    keyboard = [
                        [InlineKeyboardButton("1", callback_data=f"setup_pts_{game}_{wager:.2f}_normal_1")],
                        [InlineKeyboardButton("2", callback_data=f"setup_pts_{game}_{wager:.2f}_normal_2")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}**\nWager: ${wager:.2f}\nMode: Normal\n\nHow many rolls per round?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            elif data.startswith("setup_mode_crazy_"):
                parts = data.split('_')
                if len(parts) >= 4:
                    game, wager = parts[3], float(parts[4])
                    keyboard = [
                        [InlineKeyboardButton("1", callback_data=f"setup_pts_{game}_{wager:.2f}_crazy_1")],
                        [InlineKeyboardButton("2", callback_data=f"setup_pts_{game}_{wager:.2f}_crazy_2")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}**\nWager: ${wager:.2f}\nMode: Crazy\n\nHow many rolls per round?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            elif data.startswith("setup_rolls_"):
                parts = data.split('_')
                if len(parts) >= 5:
                    game, wager, mode = parts[2], float(parts[3]), parts[4]
                    keyboard = [
                        [InlineKeyboardButton("1", callback_data=f"setup_pts_{game}_{wager:.2f}_{mode}_1")],
                        [InlineKeyboardButton("2", callback_data=f"setup_pts_{game}_{wager:.2f}_{mode}_2")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}**\nWager: ${wager:.2f}\nMode: {mode}\n\nHow many rolls per round?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            elif data.startswith("setup_pts_"):
                parts = data.split('_')
                if len(parts) >= 6:
                    game, wager, mode, rolls = parts[2], float(parts[3]), parts[4], int(parts[5])
                    keyboard = [
                        [InlineKeyboardButton("1", callback_data=f"setup_opp_{game}_{wager:.2f}_{mode}_{rolls}_1")],
                        [InlineKeyboardButton("2", callback_data=f"setup_opp_{game}_{wager:.2f}_{mode}_{rolls}_2")],
                        [InlineKeyboardButton("3", callback_data=f"setup_opp_{game}_{wager:.2f}_{mode}_{rolls}_3")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}**\nWager: ${wager:.2f}\nMode: {mode}\nRolls: {rolls}\n\nChoose Target Score:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            elif data.startswith("setup_opp_"):
                parts = data.split('_')
                if len(parts) >= 7:
                    game, wager, mode, rolls, pts = parts[2], float(parts[3]), parts[4], int(parts[5]), int(parts[6])
                    keyboard = [
                        [InlineKeyboardButton("🤖 Play vs Bot", callback_data=f"v2_bot_{game}_{wager:.2f}_{rolls}_{mode}_{pts}")],
                        [InlineKeyboardButton("👥 Create PvP", callback_data=f"v2_pvp_{game}_{wager:.2f}_{rolls}_{mode}_{pts}")]
                    ]
                    await query.edit_message_text(f"**{game.capitalize()}** Ready!\n\nWager: ${wager:.2f}\nMode: {mode}\nRolls: {rolls}\nTarget: {pts}\n\nChoose Opponent:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            if data.startswith("v2_bot_") or data.startswith("dice_bot_") or data.startswith("basketball_bot_") or data.startswith("soccer_bot_") or data.startswith("darts_bot_") or data.startswith("bowling_bot_"):
                parts = data.split('_')
                if len(parts) >= 3:
                    if data.startswith("v2_bot_"):
                        game = parts[2]
                        wager = float(parts[3])
                        
                        # If it's a full "Play Again" / "Double" callback (v2_bot_game_wager_rolls_mode_pts)
                        if len(parts) >= 7:
                            rolls = int(parts[4])
                            mode = parts[5]
                            pts = int(parts[6])
                            # Go directly to final confirmation step with these settings
                            await self._show_emoji_game_setup(update, context, wager, game, "final", {"rolls": rolls, "mode": mode, "pts": pts})
                            return
                        # Special edit buttons: v2_bot_edit_{field}_{game}_{wager}_{rolls}_{mode}_{pts}
                        elif len(parts) >= 8 and parts[2] == "edit":
                            field = parts[3]
                            game = parts[4]
                            wager = float(parts[5])
                            rolls = int(parts[6])
                            mode = parts[7]
                            pts = int(parts[8])
                            await self._show_emoji_game_setup(update, context, wager, game, field, {"rolls": rolls, "mode": mode, "pts": pts})
                            return
                        # If it's just the initiation (v2_bot_game_wager)
                        else:
                            await self._show_emoji_game_setup(update, context, wager, game, "mode", {})
                            return
                    else:
                        game = parts[0]
                        wager = float(parts[2])
                        await self._show_emoji_game_setup(update, context, wager, game, "mode", {})
                        return
                return

            elif data.startswith("v2_pvp_"):
                parts = data.split('_')
                if len(parts) >= 7:
                    game, wager, rolls, mode, pts = parts[2], float(parts[3]), int(parts[4]), parts[5], int(parts[6])
                    await self.start_generic_v2_pvp(update, context, game, wager, rolls, mode, pts)
                return

            elif data.startswith("v2_accept_"):
                cid = data.replace("v2_accept_", "")
                await self.accept_generic_v2_pvp(update, context, cid)
            
            elif data.startswith("v2_cashout_"):
                cid = data.replace("v2_cashout_", "")
                challenge = self.pending_pvp.get(cid)
                if not challenge or challenge.get('player') != user_id:
                    await query.answer("❌ Game not found or not yours!", show_alert=True)
                    return
                
                cashout_val = self.calculate_cashout(challenge['p_pts'], challenge['b_pts'], challenge['pts'], challenge['wager'])
                user_data = self.db.get_user(user_id)
                
                # Update user balance
                user_data['balance'] += cashout_val
                self.db.update_user(user_id, user_data)
                
                profit = cashout_val - challenge['wager']
                self.db.update_house_balance(-profit)
                
                # Commit changes (Postgres)
                with self.db.app.app_context():
                    db.session.commit()
                
                await query.edit_message_text(f"💰 **CASHOUT SUCCESSFUL!**\nYou cashed out for **${cashout_val:.2f}**\nNet: {'+' if profit >=0 else ''}${profit:.2f}")
                del self.pending_pvp[cid]
                
                # Update global state for pending_pvp
                with self.db.app.app_context():
                    gs = db.session.get(GlobalState, "pending_pvp")
                    if gs:
                        gs.value = self.pending_pvp
                        db.session.commit()
                return
            
            if data.startswith("bj_bot_"):
                # Already handled in the bj_ block above
                return

            elif data.startswith("slots_bot_"):
                wager = float(data.split("_")[2])
                user_data = self.db.get_user(user_id)
                if wager > user_data['balance']:
                    await query.answer(f"❌ Insufficient balance! (${user_data['balance']:.2f})", show_alert=True)
                    return
                # Deduct wager and start slots
                self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
                dice_message = await context.bot.send_dice(chat_id=chat_id, emoji="🎰")
                slot_value = dice_message.dice.value
                double_match_values = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24, 25, 26, 27, 30, 31, 32, 33, 34, 37, 38, 39, 40, 41, 44, 45, 46, 47, 48, 51, 52, 53, 54, 55, 58, 59, 60, 61, 62]
                await asyncio.sleep(3)
                payout_multiplier = 0
                if slot_value == 64: payout_multiplier = 10
                elif slot_value in [1, 22, 43]: payout_multiplier = 5
                elif slot_value in double_match_values: payout_multiplier = 2
                payout = wager * payout_multiplier
                profit = payout - wager
                keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"slots_{wager:.2f}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if payout > 0:
                    user_data['balance'] += payout
                    user_data['total_wagered'] += wager
                    user_data['games_played'] += 1
                    user_data['games_won'] += 1
                    self.db.update_user(user_id, user_data)
                    self.db.update_house_balance(-profit)
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ @{user_data['username']}\nwon ${profit:.2f}", parse_mode="Markdown")
                else:
                    user_data['total_wagered'] += wager
                    user_data['games_played'] += 1
                    self.db.update_user(user_id, user_data)
                    self.db.update_house_balance(wager)
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=f"❌ [emojigamblebot](tg://user?id=8575155625) won ${wager:.2f}", reply_markup=reply_markup)
                self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
                self.db.record_game({'type': 'slots_bot', 'player_id': user_id, 'wager': wager, 'slot_value': slot_value, 'result': 'win' if profit > 0 else 'loss', 'payout': profit})
                return

            elif data.startswith("roulette_menu_"):
                wager = float(data.split("_")[2])
                keyboard = [
                    [InlineKeyboardButton("🔴 Red (2x)", callback_data=f"roulette_{wager:.2f}_red"),
                     InlineKeyboardButton("⚫ Black (2x)", callback_data=f"roulette_{wager:.2f}_black")],
                    [InlineKeyboardButton("🟢 Green (36x)", callback_data=f"roulette_{wager:.2f}_green")],
                    [InlineKeyboardButton("Odd (2x)", callback_data=f"roulette_{wager:.2f}_odd"),
                     InlineKeyboardButton("Even (2x)", callback_data=f"roulette_{wager:.2f}_even")]
                ]
                await query.edit_message_text(f"🎡 **Roulette**\nWager: ${wager:.2f}\n\nChoose your bet:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            # Game Callbacks (Darts PvP)
            elif data.startswith("darts_player_open_"):
                wager = float(data.split('_')[3])
                await self.create_emoji_pvp_challenge(update, context, wager, "darts", "🎯")
            
            elif data.startswith("accept_darts_"):
                challenge_id = data.split('_', 2)[2]
                await self.accept_emoji_pvp_challenge(update, context, challenge_id)
            
            # Game Callbacks (Basketball PvP)
            elif data.startswith("basketball_player_open_"):
                wager = float(data.split('_')[3])
                await self.create_emoji_pvp_challenge(update, context, wager, "basketball", "🏀")
            
            elif data.startswith("accept_basketball_"):
                challenge_id = data.split('_', 2)[2]
                await self.accept_emoji_pvp_challenge(update, context, challenge_id)
            
            # Game Callbacks (Soccer PvP)
            elif data.startswith("soccer_player_open_"):
                wager = float(data.split('_')[3])
                await self.create_emoji_pvp_challenge(update, context, wager, "soccer", "⚽")
            
            elif data.startswith("accept_soccer_"):
                challenge_id = data.split('_', 2)[2]
                await self.accept_emoji_pvp_challenge(update, context, challenge_id)
            
            # Game Callbacks (Bowling PvP)
            elif data.startswith("bowling_player_open_"):
                wager = float(data.split('_')[3])
                await self.create_emoji_pvp_challenge(update, context, wager, "bowling", "🎳")
            
            elif data.startswith("accept_bowling_"):
                challenge_id = data.split('_', 2)[2]
                await self.accept_emoji_pvp_challenge(update, context, challenge_id)
            
            # Game Callbacks (CoinFlip vs Bot)
            elif data.startswith("flip_bot_"):
                parts = data.split('_')
                wager = float(parts[2])
                choice = parts[3]
                await self.coinflip_vs_bot(update, context, wager, choice)
            
            # Game Callbacks (Roulette)
            elif data.startswith("roulette_"):
                parts = data.split('_')
                wager = float(parts[1])
                choice = parts[2]
                await self.roulette_play(update, context, wager, choice)
            
            # Game Callbacks (Slots play again)
            elif data.startswith("slots_"):
                wager = float(data.split('_')[1])
                
                user_data = self.db.get_user(user_id)
                
                if wager > user_data['balance']:
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Balance: ${user_data['balance']:.2f}")
                    return
                
                # Deduct wager from user balance
                self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
                
                # Send the slot machine emoji and wait for result
                dice_message = await context.bot.send_dice(chat_id=chat_id, emoji="🎰")
                slot_value = dice_message.dice.value
                
                # Slot machine values range from 1-64
                double_match_values = [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 23, 24, 25, 26, 27, 30, 31, 32, 33, 34, 37, 38, 39, 40, 41, 44, 45, 46, 47, 48, 51, 52, 53, 54, 55, 58, 59, 60, 61, 62]
                
                await asyncio.sleep(3)
                
                payout_multiplier = 0
                
                if slot_value == 64:
                    payout_multiplier = 10
                elif slot_value in [1, 22, 43]:
                    payout_multiplier = 5
                elif slot_value in double_match_values:
                    payout_multiplier = 2
                
                payout = wager * payout_multiplier
                profit = payout - wager
                
                # Add play-again button
                keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"slots_{wager:.2f}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Update user balance and stats
                if payout > 0:
                    new_balance = user_data['balance'] + payout
                    self.db.update_user(user_id, {
                        'balance': new_balance,
                        'total_wagered': user_data['total_wagered'] + wager,
                        'wagered_since_last_withdrawal': user_data.get('wagered_since_last_withdrawal', 0) + wager,
                        'games_played': user_data['games_played'] + 1,
                        'games_won': user_data['games_won'] + 1
                    })
                    self.db.update_house_balance(-profit)
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=f"@{user_data['username']} won ${profit:.2f}", reply_markup=reply_markup)
                    self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
                else:
                    self.db.update_user(user_id, {
                        'total_wagered': user_data['total_wagered'] + wager,
                        'wagered_since_last_withdrawal': user_data.get('wagered_since_last_withdrawal', 0) + wager,
                        'games_played': user_data['games_played'] + 1
                    })
                    self.db.update_house_balance(wager)
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=f"@{user_data['username']} lost ${wager:.2f}", reply_markup=reply_markup)
                    self.button_ownership[(sent_msg.chat_id, sent_msg.message_id)] = user_id
                
                # Record game
                self.db.record_game({
                    'type': 'slots_bot',
                    'player_id': user_id,
                    'wager': wager,
                    'slot_value': slot_value,
                    'result': 'win' if profit > 0 else 'loss',
                    'payout': profit
                })

            # Leaderboard Pagination
            elif data.startswith("lb_page_"):
                page = int(data.split('_')[2])
                await self.show_leaderboard_page(update, page)
                
            # Utility Callbacks
            elif data == "claim_daily_bonus":
                user_data = self.db.get_user(user_id)
                bonus_amount = user_data.get('wagered_since_last_withdrawal', 0) * 0.01

                if bonus_amount < 0.01:
                     await query.edit_message_text("❌ Minimum bonus to claim is $0.01.")
                     return

                # Process claim
                user_data['balance'] += bonus_amount
                user_data['wagered_since_last_withdrawal'] = 0.0 # Reset wagered amount
                self.db.update_user(user_id, user_data)
                
                self.db.add_transaction(user_id, "bonus_claim", bonus_amount, "Bonus Claim")
                
                await query.edit_message_text(f"✅ **Bonus Claimed!**\nYou received **${bonus_amount:.2f}**.\n\nYour new balance is ${user_data['balance']:.2f}.", parse_mode="Markdown")

            elif data == "claim_referral":
                user_data = self.db.get_user(user_id)
                claim_amount = user_data.get('unclaimed_referral_earnings', 0)
                
                if claim_amount < 0.01:
                    await query.edit_message_text("❌ Minimum unclaimed earnings to claim is $0.01.")
                    return
                
                # Process claim
                user_data['balance'] += claim_amount
                user_data['unclaimed_referral_earnings'] = 0.0
                self.db.update_user(user_id, user_data)
                
                self.db.add_transaction(user_id, "referral_claim", claim_amount, "Referral Earnings Claim")
                
                await query.edit_message_text(f"✅ **Referral Earnings Claimed!**\nYou received **${claim_amount:.2f}**.\n\nYour new balance is ${user_data['balance']:.2f}.", parse_mode="Markdown")

            # Deposit/Withdrawal buttons
            elif data == "deposit_mock":
                user_data = self.db.get_user(user_id)
                user_deposit_address = user_data.get('ltc_deposit_address')
                
                if not user_deposit_address:
                    master_address = os.getenv("LTC_MASTER_ADDRESS", "")
                    if master_address:
                        user_deposit_address = master_address
                    else:
                        await query.edit_message_text("❌ Deposits not configured. Contact admin.", parse_mode="Markdown")
                        return
                
                deposit_fee = float(os.getenv('DEPOSIT_FEE_PERCENT', '2'))
                ltc_rate = float(os.getenv('LTC_USD_RATE', '100'))
                
                deposit_text = f"""💰 **LTC Deposit**

Send Litecoin to:
`{user_deposit_address}`

**Rate:** 1 LTC = ${ltc_rate:.2f}
**Fee:** {deposit_fee}%

Your balance will be credited automatically after 3 confirmations.

⚠️ Only send LTC to this address!"""
                
                await query.edit_message_text(deposit_text, parse_mode="Markdown")
            
            elif data == "withdraw_mock":
                user_data = self.db.get_user(user_id)
                if user_data['balance'] < 1.00:
                    await query.edit_message_text(f"❌ **Withdrawal Failed**: Minimum withdrawal is $1.00. Current balance: ${user_data['balance']:.2f}", parse_mode="Markdown")
                else:
                    withdraw_text = f"""💸 **LTC Withdrawal Request**

Your balance: **${user_data['balance']:.2f}**

To withdraw, use:
`/withdraw <amount> <your_ltc_address>`

**Example:** `/withdraw 50 LTC1abc123...`

⚠️ Withdrawals are processed manually by admin."""
                    await query.edit_message_text(withdraw_text, parse_mode="Markdown")

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
            
            # Blackjack button handlers
            elif data.startswith("bj_"):
                parts = data.split('_')
                if len(parts) < 3:
                    await query.answer("❌ Invalid button data!", show_alert=True)
                    return
                
                # Check for "bj_bot_<wager>" format (initiation from menu)
                if parts[1] == "bot":
                    try:
                        wager = float(parts[2])
                    except (IndexError, ValueError):
                        await query.answer("❌ Invalid wager!", show_alert=True)
                        return
                        
                    user_id = query.from_user.id
                    user_data = self.db.get_user(user_id)
                    if wager > user_data['balance']:
                        await query.answer(f"❌ Insufficient balance! (${user_data['balance']:.2f})", show_alert=True)
                        return
                    
                    if user_id in self.blackjack_sessions:
                        await query.answer("❌ You already have an active Blackjack game!", show_alert=True)
                        return

                    self.db.update_user(user_id, {'balance': user_data['balance'] - wager})
                    from blackjack import BlackjackGame
                    game = BlackjackGame(bet_amount=wager)
                    game.start_game()
                    self.blackjack_sessions[user_id] = game
                    await self._display_blackjack_state(update, context, user_id)
                    return

                # Normal gameplay actions: bj_<user_id>_<action>
                try:
                    game_user_id = int(parts[1])
                    action = parts[2]
                except (IndexError, ValueError):
                    await query.answer("❌ Invalid action data!", show_alert=True)
                    return
                
                # Verify this is the correct user's game
                if user_id != game_user_id:
                    await query.answer("❌ This is not your game!", show_alert=True)
                    return
                
                if game_user_id not in self.blackjack_sessions:
                    await query.edit_message_text("❌ Game session expired. Start a new game with /blackjack")
                    return
                
                game = self.blackjack_sessions[game_user_id]
                
                # Execute the action
                if action == "hit":
                    game.hit()
                elif action == "stand":
                    game.stand()
                elif action == "double":
                    # Check if user has enough balance for double down
                    user_data = self.db.get_user(user_id)
                    current_hand = game.player_hands[game.current_hand_index]
                    additional_bet = current_hand['bet']
                    
                    if user_data['balance'] < additional_bet:
                        await query.answer("❌ Insufficient balance to double down!", show_alert=True)
                        return
                    
                    # Deduct additional bet
                    user_data['balance'] -= additional_bet
                    self.db.update_user(user_id, user_data)
                    
                    game.double_down()
                elif action == "split":
                    # Check if user has enough balance for split
                    user_data = self.db.get_user(user_id)
                    current_hand = game.player_hands[game.current_hand_index]
                    additional_bet = current_hand['bet']
                    
                    if user_data['balance'] < additional_bet:
                        await query.answer("❌ Insufficient balance to split!", show_alert=True)
                        return
                    
                    # Deduct additional bet
                    user_data['balance'] -= additional_bet
                    self.db.update_user(user_id, user_data)
                    
                    game.split()
                elif action == "surrender":
                    game.surrender()
                elif action == "insurance":
                    # Check if user has enough balance for insurance
                    user_data = self.db.get_user(user_id)
                    insurance_cost = game.initial_bet / 2
                    
                    if user_data['balance'] < insurance_cost:
                        await query.answer("❌ Insufficient balance for insurance!", show_alert=True)
                        return
                    
                    # Deduct insurance cost
                    user_data['balance'] -= insurance_cost
                    self.db.update_user(user_id, user_data)
                    
                    game.take_insurance()
                
                # Update the display with new game state
                await self._display_blackjack_state(update, context, user_id)
            
            else:
                await query.edit_message_text("Something went wrong or this button is for a different command!")
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error in button_callback: {error_str}")
            # Don't send error message for known non-critical issues or if message was already handled
            if "Minimum bet" in error_str or "query is answered" in error_str or "Message is not modified" in error_str:
                try:
                    await query.answer()
                except:
                    pass
                return
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text="An unexpected error occurred. Please try the command again.")
            except:
                pass


    def run(self):
        """Start the bot."""
        # Schedule task to check for expired challenges every 5 seconds
        if not self.app.job_queue:
            logger.warning("JobQueue is not available. Timer-based features will not work.")
        else:
            self.app.job_queue.run_repeating(self.check_expired_challenges, interval=5, first=5)
        
        self.app.run_polling(poll_interval=1.0)


async def main():
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("!!! FATAL ERROR: Please set the TELEGRAM_BOT_TOKEN environment variable. !!!")
        return
    
    logger.info("Starting Antaria Casino Bot...")
    bot = AntariaCasinoBot(token=BOT_TOKEN)
    
    if bot.app.job_queue:
        bot.app.job_queue.run_repeating(bot.check_expired_challenges, interval=5, first=5)
    else:
        logger.warning("JobQueue is not available. Timer-based features will not work.")
    
    await bot.app.initialize()
    await bot.app.start()
    await bot.app.updater.start_polling(poll_interval=1.0)
    
    logger.info("Bot is running with polling mode...")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if bot.app.updater:
            await bot.app.updater.stop()
        await bot.app.stop()
        await bot.app.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
