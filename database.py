import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import asyncio


class DatabaseManager:
    def __init__(self, filename: str = "casino_data.json"):
        self.filename = filename
        self.data: Dict[str, Any] = {
            "users": {},
            "games": [],
            "pending_pvp": {},
            "house_balance": 6973.0
        }
        self.auto_save_task = None
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.data = json.load(f)
                if "house_balance" not in self.data:
                    self.data["house_balance"] = 6973.0
                print(f"✅ Loaded database from {self.filename}")
            except Exception as e:
                print(f"⚠️ Error loading database: {e}")
                self.save_data()
        else:
            self.save_data()
            print(f"✅ Created new database: {self.filename}")
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving database: {e}")
    
    def backup_data(self) -> str:
        """Create a timestamped backup"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"casino_data_backup_{timestamp}.json"
        try:
            with open(backup_filename, 'w') as f:
                json.dump(self.data, f, indent=2)
            return backup_filename
        except Exception as e:
            print(f"❌ Error creating backup: {e}")
            return ""
    
    async def auto_save_loop(self):
        """Auto-save every 5 minutes"""
        while True:
            await asyncio.sleep(300)
            self.save_data()
            print(f"💾 Auto-saved at {datetime.now().strftime('%H:%M:%S')}")
    
    def get_user(self, user_id: int) -> Dict[str, Any]:
        """Get user data, create if doesn't exist"""
        user_id_str = str(user_id)
        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = {
                "balance": 1000.0,
                "playthrough_required": 0.0,
                "total_wagered": 0.0,
                "total_pnl": 0.0,
                "games_played": 0,
                "games_won": 0,
                "first_wager_date": None,
                "last_bonus_claim": None,
                "wagered_since_last_withdrawal": 0.0,
                "referral_code": None,
                "referred_by": None,
                "referral_earnings": 0.0,
                "unclaimed_referral_earnings": 0.0,
                "referral_count": 0,
                "achievements": [],
                "win_streak": 0,
                "best_win_streak": 0,
                "created_at": datetime.now().isoformat(),
                "transactions": [],
                "username": None
            }
            self.save_data()
        return self.data["users"][user_id_str]
    
    def update_user(self, user_id: int, updates: Dict[str, Any]):
        """Update user data"""
        user_id_str = str(user_id)
        user = self.get_user(user_id)
        user.update(updates)
        self.save_data()
    
    def add_transaction(self, user_id: int, transaction_type: str, amount: float, description: str):
        """Add a transaction to user's history"""
        user = self.get_user(user_id)
        transaction = {
            "type": transaction_type,
            "amount": amount,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }
        user["transactions"].append(transaction)
        self.save_data()
    
    def record_game(self, game_data: Dict[str, Any]):
        """Record a game in history"""
        game_data["timestamp"] = datetime.now().isoformat()
        self.data["games"].append(game_data)
        if len(self.data["games"]) > 1000:
            self.data["games"] = self.data["games"][-1000:]
        self.save_data()
    
    def get_leaderboard(self, sort_by: str = "total_wagered", limit: int = 100) -> list:
        """Get leaderboard sorted by specified metric"""
        users = []
        for user_id, user_data in self.data["users"].items():
            users.append({
                "user_id": user_id,
                "username": user_data.get("username", f"User{user_id}"),
                "balance": user_data.get("balance", 0),
                "total_wagered": user_data.get("total_wagered", 0),
                "total_pnl": user_data.get("total_pnl", 0),
                "games_played": user_data.get("games_played", 0)
            })
        
        users.sort(key=lambda x: x[sort_by], reverse=True)
        return users[:limit]
    
    def calculate_rp_level(self, user_id: int) -> int:
        """Calculate Respect Points level"""
        user = self.get_user(user_id)
        
        total_wagered = user.get("total_wagered", 0)
        achievement_count = len(user.get("achievements", []))
        
        days_active = 0
        if user.get("created_at"):
            created = datetime.fromisoformat(user["created_at"])
            days_active = (datetime.now() - created).days
        
        rp_points = (total_wagered / 100) + (achievement_count * 50) + (days_active * 2)
        
        level = int(rp_points / 100) + 1
        return level
    
    def check_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Check if user has unlocked achievement"""
        user = self.get_user(user_id)
        achievements = user.get("achievements", [])
        
        if achievement_id in achievements:
            return False
        
        unlocked = False
        
        if achievement_id == "first_bet" and user.get("games_played", 0) >= 1:
            unlocked = True
        elif achievement_id == "high_roller" and user.get("total_wagered", 0) >= 100:
            unlocked = True
        elif achievement_id == "win_streak" and user.get("best_win_streak", 0) >= 5:
            unlocked = True
        elif achievement_id == "jackpot" and user.get("total_pnl", 0) >= 1000:
            unlocked = True
        elif achievement_id == "referrer" and user.get("referral_count", 0) >= 10:
            unlocked = True
        elif achievement_id == "leveled_up" and self.calculate_rp_level(user_id) >= 10:
            unlocked = True
        
        if unlocked:
            achievements.append(achievement_id)
            self.update_user(user_id, {"achievements": achievements})
        
        return unlocked
    
    def get_house_balance(self) -> float:
        """Get current house balance"""
        return self.data.get("house_balance", 6973.0)
    
    def update_house_balance(self, amount: float):
        """Update house balance by adding/subtracting amount"""
        self.data["house_balance"] = self.data.get("house_balance", 6973.0) + amount
        self.save_data()
