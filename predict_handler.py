import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

async def handle_predict(bot_instance, update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if data.startswith("setup_predict_select_"):
        parts = data.split("_")
        wager = float(parts[3])
        prediction = parts[4]
        game_mode = parts[5]
        if not hasattr(bot_instance, "_predict_selections"):
            bot_instance._predict_selections = {}
        bot_instance._predict_selections[user_id] = prediction
        await bot_instance._setup_predict_interface(update, context, wager, game_mode)
        return

    if data.startswith("predict_start_"):
        parts = data.split("_")
        wager = float(parts[2])
        game_mode = parts[3]
        
        prediction = getattr(bot_instance, "_predict_selections", {}).get(user_id)
        if not prediction:
            await query.answer("❌ Please select a prediction first!", show_alert=True)
            return
        
        user_data = bot_instance.db.get_user(user_id)
        if wager > user_data['balance']:
            await query.answer(f"❌ Balance: ${user_data['balance']:.2f}", show_alert=True)
            return
        
        if hasattr(bot_instance, "_predict_selections") and user_id in bot_instance._predict_selections:
            del bot_instance._predict_selections[user_id]
        
        user_data['balance'] -= wager
        
        emoji_map = {"dice": "🎲", "basketball": "🏀", "soccer": "⚽", "darts": "🎯", "bowling": "🎳"}
        dice_emoji = emoji_map.get(game_mode, "🎲")
        dice_message = await context.bot.send_dice(chat_id=chat_id, emoji=dice_emoji)
        actual_val = dice_message.dice.value
        
        await asyncio.sleep(4)
        
        is_win = False
        multiplier = 6.0
        if game_mode in ["dice", "darts", "bowling"]:
            is_win = str(actual_val) == str(prediction)
            multiplier = 6.0
        elif game_mode == "basketball":
            actual_outcome = "score" if actual_val in [3, 5] else "miss"
            is_win = prediction == actual_outcome
            if prediction == "score": multiplier = 3.0
            elif prediction == "miss": multiplier = 2.0
            else: multiplier = 6.0
        elif game_mode == "soccer":
            if actual_val in [4, 5]: actual_outcome = "goal"
            elif actual_val == 6: actual_outcome = "bar"
            else: actual_outcome = "miss"
            is_win = prediction == actual_outcome
            if prediction == "goal": multiplier = 3.0
            elif prediction == "miss": multiplier = 1.5
            else: multiplier = 6.0

        if is_win:
            payout = wager * multiplier
            profit = payout - wager
            user_data['balance'] += payout
            user_data['games_won'] += 1
            user_display = f"**{user_data.get('username', f'User{user_id}')}**"
            result_text = f"🎉 {user_display} won **${profit:.2f}**!"
            bot_instance.db.update_house_balance(-profit)
        else:
            profit = -wager
            result_text = f"❌ [emojigamblebot](tg://user?id=8575155625) won **${wager:.2f}**"
            bot_instance.db.update_house_balance(wager)
        
        user_data['total_wagered'] += wager
        user_data['games_played'] += 1
        bot_instance.db.update_user(user_id, user_data)
        
        bot_instance.db.add_transaction(user_id, f"predict_{game_mode}", profit, f"Predict {game_mode.upper()} - Wager: ${wager:.2f}")
        bot_instance.db.record_game({
            'type': f'predict_{game_mode}',
            'player_id': user_id,
            'wager': wager,
            'predicted': prediction,
            'actual': actual_val,
            'result': 'win' if is_win else 'loss',
            'timestamp': datetime.now().isoformat()
        })
        
        keyboard = [[InlineKeyboardButton("Play Again", callback_data=f"setup_mode_predict_{wager:.2f}_{game_mode}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=result_text, 
            reply_markup=reply_markup, 
            parse_mode="Markdown",
            reply_to_message_id=dice_message.message_id
        )
        return
