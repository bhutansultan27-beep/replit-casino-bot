import os
import json
import logging
import hmac
import hashlib
from datetime import datetime
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebhookServer:
    def __init__(self, bot, port=5000):
        self.bot = bot
        self.port = port
        self.app = web.Application()
        self.setup_routes()
        
    def setup_routes(self):
        self.app.router.add_post('/webhook/deposit', self.handle_deposit_webhook)
        self.app.router.add_get('/health', self.health_check)
        
    async def health_check(self, request):
        return web.json_response({"status": "ok"})
    
    async def handle_deposit_webhook(self, request):
        try:
            data = await request.json()
            logger.info(f"Received deposit webhook: {data}")
            
            address = data.get('address')
            amount = float(data.get('amount', 0))
            tx_id = data.get('txid') or data.get('tx_id') or data.get('id')
            confirmations = int(data.get('confirmations', 0))
            status = data.get('status', '')
            
            required_confirmations = int(os.getenv('LTC_REQUIRED_CONFIRMATIONS', '3'))
            
            if confirmations < required_confirmations:
                logger.info(f"Waiting for confirmations: {confirmations}/{required_confirmations}")
                return web.json_response({"status": "pending", "message": f"Waiting for {required_confirmations} confirmations"})
            
            user_id = self.find_user_by_deposit_address(address)
            if not user_id:
                logger.warning(f"No user found for deposit address: {address}")
                return web.json_response({"status": "error", "message": "Unknown address"}, status=400)
            
            if self.is_deposit_processed(tx_id):
                logger.info(f"Deposit already processed: {tx_id}")
                return web.json_response({"status": "ok", "message": "Already processed"})
            
            deposit_fee_percent = float(os.getenv('DEPOSIT_FEE_PERCENT', '2'))
            ltc_to_usd_rate = float(os.getenv('LTC_USD_RATE', '100'))
            
            usd_amount = amount * ltc_to_usd_rate
            fee = usd_amount * (deposit_fee_percent / 100)
            credited_amount = round(usd_amount - fee, 2)
            
            user_data = self.bot.db.get_user(user_id)
            user_data['balance'] += credited_amount
            self.bot.db.update_user(user_id, user_data)
            
            self.bot.db.add_transaction(user_id, "deposit", credited_amount, f"LTC Deposit (Auto) - TX: {tx_id[:16]}...")
            
            self.mark_deposit_processed(tx_id, user_id, amount, credited_amount)
            
            try:
                await self.bot.app.bot.send_message(
                    chat_id=user_id,
                    text=f"✅ **Deposit Confirmed!**\n\nReceived: {amount:.8f} LTC\nCredited: **${credited_amount:.2f}**\n\nNew Balance: ${user_data['balance']:.2f}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
            
            logger.info(f"Deposit processed: User {user_id}, Amount ${credited_amount:.2f}")
            return web.json_response({"status": "ok", "credited": credited_amount})
            
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)
    
    def find_user_by_deposit_address(self, address):
        for user_id, user_data in self.bot.db.data['users'].items():
            if user_data.get('ltc_deposit_address') == address:
                return int(user_id)
        return None
    
    def is_deposit_processed(self, tx_id):
        processed = self.bot.db.data.get('processed_deposits', [])
        return tx_id in processed
    
    def mark_deposit_processed(self, tx_id, user_id, ltc_amount, usd_amount):
        if 'processed_deposits' not in self.bot.db.data:
            self.bot.db.data['processed_deposits'] = []
        if 'deposit_history' not in self.bot.db.data:
            self.bot.db.data['deposit_history'] = []
            
        self.bot.db.data['processed_deposits'].append(tx_id)
        self.bot.db.data['deposit_history'].append({
            'tx_id': tx_id,
            'user_id': user_id,
            'ltc_amount': ltc_amount,
            'usd_amount': usd_amount,
            'timestamp': datetime.now().isoformat()
        })
        
        if len(self.bot.db.data['processed_deposits']) > 1000:
            self.bot.db.data['processed_deposits'] = self.bot.db.data['processed_deposits'][-1000:]
        
        self.bot.db.save_data()
    
    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        logger.info(f"Webhook server started on port {self.port}")
