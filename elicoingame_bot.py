import json
import time
import requests

user_sessions = {}
user_win_streaks = {}
pvp_games = {}  # Global game session store
# Store ongoing PvP matches
active_pvp_sessions = {}



from game import TicTacToeGame,draw_board, build_game_keyboard

from apscheduler.schedulers.background import BackgroundScheduler
from utils import load_db, save_db
from game import PvPGameSession

from datetime import datetime
from threading import Timer

pvp_sessions = {}
pvp_timestamps = {}  # Track turn start time
pvp_wins = {}  # Track PvP leaderboard
pvp_queue = []
pvp_games = {}  # key: user_id → game session
pvp_timeouts = {}

from datetime import datetime, timedelta
from telegram import ( Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode )
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters)

# Your bot token from BotFather
TOKEN = '8329619252:AAFLVXZGT0U2ZsGnh3roqPK2KzzU_6nKyjw'
ADMIN_ID = "5103401547"  # Replace with your Telegram ID for manual approval

# === DATABASE ===
DATABASE_FILE = 'database.json'

def load_db():
    with open("database.json", "r") as f:
        db = json.load(f)

    # ✅ Tokenomics Wallet Setup
    db.setdefault("bot_wallet", {"balance": 3700000})
    db.setdefault("ai_wallet", {"burned": 0, "initial": 300000})
    db.setdefault("bonus_wallet", {"balance": 1000000})
    db.setdefault("locked_marketplace", {"locked": 1000000})
    db.setdefault("locked_app", {"locked": 1000000})
    db.setdefault("locked_blockchain_mint", {"locked": 3000000})

    return db


def save_db(db):
    recalculate_wallet()
    with open(DATABASE_FILE, 'w') as f:
        json.dump(db, f, indent=4)

# === START COMMAND ===
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    db = load_db()

    if str(user.id) not in db:
        db[str(user.id)] = {
            "username": user.username,
            "first_name": user.first_name,
            "registered": False,
            "balance": 0,
            "referred_by": None
        }
        save_db(db)

    menu_keyboard = [
        [InlineKeyboardButton("🎮 Introduction", callback_data='intro')],
        [InlineKeyboardButton("📝 Register/LogIn", callback_data='register')]
    ]
    reply_markup = InlineKeyboardMarkup(menu_keyboard)

    update.message.reply_text(
        "🏠 *Elicoin Game Bot – Home Menu*\n\nChoose an option below:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === INTRODUCTION ===
def show_intro(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    INTRO_TEXT = """
🏠 *Elicoin Game Bot – Welcome!*

*Welcome to Elicoin* — Africa’s first crypto-powered game where skill = rewards.  
Play. Compete. Earn. Burn. And grow your digital wealth.

🎮 *The Game: Tic Tac Toe, Reinvented*
Challenge our smart AI or duel other players in PvP — every move has real value:

✅ Win = Earn Elicoin (minus 5% fee)  
❌ Lose = Coins are burned forever  
🔥 Scarcity drives long-term value

Elicoin isn’t just a token — it’s the foundation of Africa’s next digital economy.

💰 *How It Works*
• One-time registration: ₦2000  
• Start-up reward: 200 ELI (after first win)
• Weekly bonus: +10 ELI (every 7 days)
• Referral bonus: +30 ELI per invite
• Top-ups starting ₦500

🔢 *Fixed Supply: 10,000,000 ELI*

💼 *Coin Allocation:*
• Telegram Game Rewards: 3.7M ELI  
• AI Burn Pool: 300k ELI  
• Bonus & Referral Wallet: 1M ELI  
• Marketplace Reserve: 1M ELI  (Locked)
• Future Elicoin App: 1M ELI  (Locked)
• Blockchain Mint (Dec 30): 3M ELI (Locked)

💸 *Elicoin Fee Rules (Live)*
• AI Win: 5% Fee → back to Bot Wallet  
• PvP Win: 5% Fee  
• Gift Coin: 5% Fee from sender  
• Top-up: 2.5% Fee auto-applied  
• Withdraw: 5% Fee

Click *Register* /start to begin!
"""
    query.edit_message_text(INTRO_TEXT, parse_mode=ParseMode.MARKDOWN)

# === REGISTRATION & PAYMENT PROOF ===
def handle_register(update: Update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    user_id = str(user.id)
    db = load_db()
    query.answer()

    if db.get(user_id, {}).get("registered"):
        query.edit_message_text("✅ You are already registered. Use /menu to start.")
        return

    # Register user with no balance yet
    db[user_id] = {
        "registered": True,
        "proof": None,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "balance": 0,
        "activated": False,
        "referred_by": "",
        "bonus_given": False
    }
    save_db(db)

    query.edit_message_text(
        "📝 *Registration Successful!*\n\n"
        "Your account has been created. Please wait for an admin to approve your account and grant your 20 ELI bonus.\n\n"
        "📩 If someone referred you, type their username using:\n`/refer @username`",
        parse_mode=ParseMode.MARKDOWN
    )

    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"👤 New user registered:\nUser: @{user.username or 'unknown'}\nID: {user_id}\n\nUse `/approve {user_id}` to approve and grant 20 ELI."
    )



def set_referrer(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()

    if len(context.args) != 1:
        update.message.reply_text("Usage: /refer @username")
        return

    ref_username = context.args[0].lstrip('@')

    if user_id not in db:
        update.message.reply_text("❌ Please register first using /start.")
        return

    if db[user_id].get("approved"):  # ✅ block only if approved
        update.message.reply_text("❌ You are already approved. Referral can't be set now.")
        return

    if db[user_id].get("referred_by"):
        update.message.reply_text("❌ You already submitted a referral.")
        return

    ref_id = next((uid for uid, u in db.items() if isinstance(u, dict) and u.get("username") == ref_username), None)

    if not ref_id or ref_id == user_id:
        update.message.reply_text("❌ Invalid or self-referral not allowed.")
        return

    db[user_id]["referred_by"] = ref_id
    save_db(db)  # ✅ fixed saving

    update.message.reply_text(f"✅ Referral set. You were referred by @{ref_username}.")

def approve_user(update: Update, context: CallbackContext):
    if str(update.effective_user.id) != str(ADMIN_ID):
        update.message.reply_text("🚫 You are not authorized to use this command.")
        return

    if len(context.args) != 1:
        update.message.reply_text("Usage: /approve <user_id>")
        return

    user_id = str(context.args[0])
    db = load_db()

    if user_id not in db:
        update.message.reply_text("❌ User ID not found.")
        return

    user_data = db[user_id]

    if user_data.get("approved"):
        update.message.reply_text("✅ User already approved.")
        return

    starter_bonus = 20
    referral_bonus = 30

    # Make sure bonus_wallet exists
    db.setdefault("bonus_wallet", {"balance": 1_000_000})

    # Starter bonus from bonus wallet
    if db["bonus_wallet"]["balance"] >= starter_bonus:
        user_data["balance"] = user_data.get("balance", 0) + starter_bonus
        db["bonus_wallet"]["balance"] -= starter_bonus
    else:
        update.message.reply_text("⚠️ Not enough funds in bonus wallet for starter bonus.")

    # Referral bonus from bonus wallet
    referrer = user_data.get("referred_by")
    if referrer and referrer in db:
        if db["bonus_wallet"]["balance"] >= referral_bonus:
            db[referrer]["balance"] = db[referrer].get("balance", 0) + referral_bonus
            db["bonus_wallet"]["balance"] -= referral_bonus
            context.bot.send_message(
                chat_id=int(referrer),
                text=f"🎉 You earned +{referral_bonus} ELI for referring user {user_id}!"
            )
        else:
            update.message.reply_text("⚠️ Not enough funds in bonus wallet for referral bonus.")

    # Mark as approved
    user_data["approved"] = True
    user_data["activated"] = False
    db[user_id] = user_data

    save_db(db)
    recalculate_wallet(db)

    context.bot.send_message(
        chat_id=int(user_id),
        text="✅ Your registration has been approved! Bonuses credited /menu."
    )

    update.message.reply_text(f"✅ User {user_id} approved and bonuses granted.")



def is_activated_or_under_limit(user):
    return user.get("activated") or user.get("balance", 0) < 50


def menu(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()

    user = db.get(user_id)
    if not user or not user.get("registered"):
        update.message.reply_text("🚫 You must register first. Use /start to begin.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Play AI", callback_data="play_ai"),
         InlineKeyboardButton("👥 PvP", callback_data="pvp")],
        
        [InlineKeyboardButton("🤝 Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("🎁 Share Gift", callback_data="gift")],
        
        [InlineKeyboardButton("💼 My Wallet", callback_data="wallet"),
         InlineKeyboardButton("📊 Bot Wallet", callback_data="bot_wallet")],
        
        [InlineKeyboardButton("🎯 Weekly Bonus", callback_data="bonus"),
         InlineKeyboardButton("🏆 Top Earners", callback_data="top_earners")],
        
        [InlineKeyboardButton("💸 Top-Up Elicoin", callback_data="topup"),
         InlineKeyboardButton("📍 Elicoin Marketplace", callback_data="marketplace_menu")],
        
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdrawal_menu"),
         InlineKeyboardButton("🎁 Twitter Bonus (10 ELI)", callback_data="like_twitter")],
        
        [InlineKeyboardButton("👤 My Profile", callback_data='my_profile')],

        [InlineKeyboardButton("💳 Activate Wallet", callback_data="activate_wallet")]


    ])

    safe_reply(update, "📍 *Elicoin Game Menu*", reply_markup=keyboard)

def handle_game_menu_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()

    if not db.get(user_id) or not db[user_id].get("registered"):
        query.answer()
        query.edit_message_text("🚫 You must register first. Use /start to begin.")
        return

    option = query.data
    responses = {
        "play_ai": "🎮 *Play AI Mode*\n(Starting game...)",
        "pvp": "👥 *PvP Mode*\n(Starting match...)",
        "refer": f"🤝 Share your referral link:\n`https://t.me/Eli_gamecoin_bot`",
        "wallet": f"💼 Your Elicoin Balance: {db[user_id].get('balance', 0)} ELI",
        "gift": None,
        "bot_wallet": None,
        "top_earners": None,
        "bonus": None,
        "topup": None,
        "ai_wallet": None,
        
    }

    response = responses.get(option, "❓ Unknown option")

    # Handle callable options
    if option == "play_ai":
        return start_ai_game(update, context)
    elif option == "pvp":
        return handle_pvp_callback(update, context)
    elif option == "gift":
        return context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🎁 You can gift up to 500 Elicoin daily to other players.\n\nUse:\n`/sharecoingift <user_id> <amount>`",
            parse_mode=ParseMode.MARKDOWN
        )
    elif option == "bot_wallet":
        return bot_wallet(update, context)
    elif option == "top_earners":
        show_top_earners(update, context)
    elif option == "bonus":
        return claim_bonus(update, context)    
    
    elif option == "topup":
        context.user_data["topup_pending"] = True  # 🔥 Set flag here
        return context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "💸 *Elicoin Top-Up Instructions:*\n\n"
            "₦500 – 5 ELI 👉 [Pay Now](https://flutterwave.com/pay/nv7wpdsqt0ql)\n"
            "₦1000 – 10 ELI 👉 [Pay Now](https://flutterwave.com/pay/latay2eo8igp)\n"
            "₦2000 – 20 ELI 👉 [Pay Now](https://flutterwave.com/pay/latay2eo8igp)\n"
            "₦5000 – 50 ELI 👉 [Pay Now](https://flutterwave.com/pay/c9qcdtppbijq)\n"
            "₦10000 – 100 ELI 👉 [Pay Now](https://flutterwave.com/pay/rztxhusgccmz)\n\n"
            "📸 *After payment, upload your screenshot here.*\n"
            "_Only JPG/PNG images accepted. Admin will verify and credit your wallet._"
        ),
        parse_mode=ParseMode.MARKDOWN
    )
   
        return

    elif option == "ai_wallet":
        return ai_wallet(update, context)


    # For direct messages like wallet or refer
    try:
        query.answer()
        query.edit_message_text(response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        context.bot.send_message(chat_id=query.message.chat_id, text=response, parse_mode=ParseMode.MARKDOWN)


def handle_like_twitter(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()

    # Check if already claimed
    if db.get(user_id, {}).get("twitter_bonus_claimed"):
        query.answer()
        query.edit_message_text("✅ You've already claimed your Twitter bonus.")
        return

    # Prompt user to like and upload screenshot
    query.answer()
    query.edit_message_text(
        "💙 *Like our Twitter Page to Earn 10 ELI*\n\n"
        "👉 [Click to follow us](https://x.com/Elicoin1)\n"
        "📸 After that, reply here with a screenshot showing you liked or followed us.",
        parse_mode=ParseMode.MARKDOWN
    )

    context.user_data["awaiting_twitter_screenshot"] = True


def show_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()
    user = db.get(user_id, {})

    username = user.get("username") or "Not set"
    balance = user.get("balance", 0)
    activated = "✅ Activated" if user.get("activated") else "❌ Not Activated"

    # Count referrals
    referrals = sum(1 for u in db.values() if isinstance(u, dict) and u.get("referred_by") == user_id)

    text = (
        f"👤 *My Profile*\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📛 Username: @{username}\n"
        f"💰 Balance: {balance} ELI\n"
        f"🔓 Status: {activated}\n"
        f"🤝 Referrals: {referrals}"
    )

    query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


def start_ai_game(update: Update, context: CallbackContext):
    query = update.callback_query  # ✅ This fixes your error
    user_id = str(update.effective_user.id)
    db = load_db()
    user = db.get(user_id, {})

    if not is_activated_or_under_limit(user):
        query.message.reply_text("🔒 Wallet not activated. Pay ₦2000 to continue playing.")
        return

    if user.get("balance", 0) < 10:
        query.message.reply_text("💸 You need at least 10 ELI to play against AI.")
        return

    global user_sessions

    session = user_sessions.get(user_id, {})

    # Prevent playing mid-game
    if session.get("game") and not session["game"].game_over:
        query.answer("⚠️ Finish the current game first.")
        return

    win_streak = user.get("ai_win_streak", 0)
    difficulty = "very_hard" if win_streak >= 6 else "hard" if win_streak >= 3 else "medium"

    last_starter = session.get("last_starter", "ai")
    new_starter = "user" if last_starter == "ai" else "ai"
    session["last_starter"] = new_starter

    game = TicTacToeGame(ai_starts=(new_starter == "ai"), difficulty=difficulty)
    session["game"] = game
    user_sessions[user_id] = session

    if new_starter == "ai":
        game.ai_move()

    starter_note = "🤖 *AI started the game.*" if new_starter == "ai" else "🧑 *You start the game.*"
    query.edit_message_text(
        draw_board(game.board),
        reply_markup=build_game_keyboard(game.board),
        parse_mode=ParseMode.MARKDOWN
    )


def handle_board_move(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = query.data
    pos = int(data.split("_")[1])

    session = user_sessions.get(user_id, {})
    game = session.get("game")

    if not isinstance(game, TicTacToeGame):
        query.answer("⚠️ No active game.")
        return

    if game.game_over:
        query.answer("Game already completed.")
        return

    if game.board[pos] != " ":
        query.answer("Cell already taken.")
        return

    # Player move
    if not game.make_move(pos, "X"):
        query.answer("Invalid move.")
        return

    winner = game.check_winner()
    db = load_db()

    # ✅ PLAYER WINS (AI loses)
    if winner == "X":
        game.game_over = True
        user = db.get(user_id, {})
        user["ai_win_streak"] = user.get("ai_win_streak", 0) + 1

        reward = 10
        fee = int(reward * 0.10)   # 10% fee to bot wallet
        net = reward - fee

        # Make sure bot wallet exists
        db.setdefault("bot_wallet", {}).setdefault("balance", 0)

        # Deduct the full reward from bot wallet
        db["bot_wallet"]["balance"] -= reward
        if db["bot_wallet"]["balance"] < 0:
            db["bot_wallet"]["balance"] = 0  # Avoid negative

        # Add fee back to bot wallet
        db["bot_wallet"]["balance"] += fee

        # Credit player with net reward
        user["balance"] = user.get("balance", 0) + net

        db[user_id] = user
        save_db(db)
        recalculate_wallet()

        query.edit_message_text(
            f"🏆 You won!\n+{net} ELI (10% fee deducted)\n\n{draw_board(game.board)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Play Again", callback_data="play_ai")]]),
            parse_mode=ParseMode.MARKDOWN,
        )
        user_sessions[user_id]["game"] = None
        return

    # 🤖 AI MOVE
    game.ai_move()
    winner = game.check_winner()

    # ❌ PLAYER LOSES (AI wins)
    if winner == "O":
        game.game_over = True
        burn_amount = 10

        # Deduct from player
        user_balance = db[user_id].get("balance", 0)
        db[user_id]["balance"] = max(0, user_balance - burn_amount)

        # Burned coins are lost forever (AI wallet)
        db.setdefault("ai_wallet", {}).setdefault("burned", 0)
        db["ai_wallet"]["burned"] += burn_amount

        save_db(db)
        recalculate_wallet()

        query.edit_message_text(
            "💀 You lost!\n10 ELI burned.\n\n" + draw_board(game.board),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Play Again", callback_data="play_ai")]]),
            parse_mode=ParseMode.MARKDOWN,
        )
        user_sessions[user_id]["game"] = None
        return

    # 🤝 DRAW
    if winner == "Draw":
        game.game_over = True
        save_db(db)
        recalculate_wallet()

        query.edit_message_text(
            "⚖️ It's a draw!\n\n" + draw_board(game.board),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Play Again", callback_data="play_ai")]]),
            parse_mode=ParseMode.MARKDOWN,
        )
        user_sessions[user_id]["game"] = None
        return

    # 🔁 CONTINUE GAME
    query.edit_message_text(
        draw_board(game.board),
        reply_markup=build_game_keyboard(game.board),
        parse_mode=ParseMode.MARKDOWN,
    )




def start_pvp(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()
    user = db.get(user_id, {})

    if not is_activated_or_under_limit(user):
        query.message.reply_text("🔒 Wallet not activated. Pay ₦2000 to continue playing.")
        return

    if user_id not in db or not db[user_id].get("registered"):
        query.message.reply_text("🚫 You must register first. Use /start to begin.")
        return

    if user_id in pvp_sessions:
        query.message.reply_text("⚔️ You're already in a PvP match.")
        return

    if db[user_id].get("balance", 0) < 20:
        query.message.reply_text("💸 You need at least 20 ELI to join a PvP match.")
        return

    if "pvp_queue" not in db:
        db["pvp_queue"] = []

    # Remove if already in queue
    db["pvp_queue"] = [uid for uid in db["pvp_queue"] if uid != user_id]
    db["pvp_queue"].append(user_id)
    save_db(db)  # ✅ save immediately so other players see the updated queue

    # Try to match
    if len(db["pvp_queue"]) >= 2:
        player1 = str(db["pvp_queue"].pop(0))
        player2 = str(db["pvp_queue"].pop(0))

        if db[player1].get("balance", 0) < 20 or db[player2].get("balance", 0) < 20:
            query.message.reply_text("⚠️ One player lacks enough coins. Match cancelled.")
            return

        db[player1]["balance"] -= 20
        db[player2]["balance"] -= 20
        save_db(db)

        notify_pvp_start(context, player1, player2)
        query.message.reply_text("✅ PvP match found! Check your private chat.")
        return

    query.message.reply_text("🔍 Searching for opponent... You'll be matched soon.")


def notify_pvp_start(context: CallbackContext, player1_id, player2_id):
    session = {
        "players": [player1_id, player2_id],
        "game": PvPGameSession(player1_id, player2_id),
        "last_active": time.time()
    }
    key = f"{player1_id}_{player2_id}"
    active_pvp_sessions[key] = session

    board = session["game"].get_inline_keyboard()
    text = session["game"].get_board_text() + "\n⏱ *Time left:* 60s"

    context.bot.send_message(chat_id=player1_id, text=text, reply_markup=board, parse_mode=ParseMode.MARKDOWN)
    context.bot.send_message(chat_id=player2_id, text=text, reply_markup=board, parse_mode=ParseMode.MARKDOWN)


def notify_pvp_start_with_starter(context: CallbackContext, player1_id, player2_id, starter):
    session = {
        "players": [player1_id, player2_id],
        "game": PvPGameSession(player1_id, player2_id),
        "last_active": time.time()
    }
    session["game"].current_turn = starter
    key = f"{player1_id}_{player2_id}"
    active_pvp_sessions[key] = session

    board = session["game"].get_inline_keyboard()
    text = session["game"].get_board_text() + "\n⏱ *Time left:* 60s"

    context.bot.send_message(chat_id=player1_id, text=text, reply_markup=board, parse_mode=ParseMode.MARKDOWN)
    context.bot.send_message(chat_id=player2_id, text=text, reply_markup=board, parse_mode=ParseMode.MARKDOWN)


def handle_pvp_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = query.data
    pos = int(data.split("_")[2])

    for key, session in active_pvp_sessions.items():
        if user_id in session["players"]:
            game = session["game"]
            if game.finished:
                query.answer("Game already completed.")
                return

            if user_id != game.current_player():
                query.answer("Not your turn.")
                return

            if not game.make_move(pos):
                query.answer("Invalid move.")
                return

            session["last_active"] = time.time()

            # ✅ WINNER CASE
            if game.check_win():
                winner = game.current_player()
                loser = game.other_player()

                db = load_db()
                db.setdefault("bot_wallet", {})  # ensure bot_wallet exists
                reward = 40
                fee = int(reward * 0.05)  # 5% fee
                net_reward = reward - fee

                db[winner]["balance"] += net_reward
                db["bot_wallet"]["balance"] = db["bot_wallet"].get("balance", 0) + fee

                db.setdefault("pvp_last_starter", {})
                db["pvp_last_starter"][f"{winner}_{loser}"] = winner
                save_db(db)

                winner_name = db[winner].get("username", f"User_{winner}")
                loser_name = db[loser].get("username", f"User_{loser}")

                text = f"{game.get_board_text()}\n🏆 *{winner_name} wins!* +{net_reward} ELI (5% fee taken)"
                rematch_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔁 Play Again", callback_data=f"pvp_rematch:{winner}:{loser}")]
                ])

                context.bot.edit_message_text(chat_id=winner, message_id=query.message.message_id,
                                              text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=rematch_keyboard)
                context.bot.send_message(chat_id=loser, text=f"💀 You lost! {winner_name} won the match.",
                                         reply_markup=rematch_keyboard)
                del active_pvp_sessions[key]
                return

            # ✅ DRAW CASE (no fee, full refund)
            if game.is_draw():
                db = load_db()
                db[game.players[0]]["balance"] += 20
                db[game.players[1]]["balance"] += 20
                save_db(db)

                text = f"{game.get_board_text()}\n⚖️ *Draw!* Both refunded."
                rematch_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔁 Play Again", callback_data=f"pvp_rematch:{game.players[0]}:{game.players[1]}")]
                ])

                for pid in session["players"]:
                    context.bot.send_message(chat_id=pid, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=rematch_keyboard)
                del active_pvp_sessions[key]
                return

            # ✅ CONTINUE GAME
            game.turn = 1 - game.turn
            remaining = max(0, 60 - int(time.time() - session["last_active"]))
            text = game.get_board_text() + f"\n⏱ *Time left:* {remaining}s"

            for pid in session["players"]:
                context.bot.send_message(chat_id=pid, text=text, reply_markup=game.get_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
            return


def handle_pvp_rematch(update: Update, context: CallbackContext):
    query = update.callback_query
    _, p1, p2 = query.data.split(":")
    db = load_db()

    if db.get(p1, {}).get("balance", 0) < 20 or db.get(p2, {}).get("balance", 0) < 20:
        query.message.reply_text("⚠️ One player lacks enough ELI for a rematch.")
        return

    db.setdefault("pvp_last_starter", {})
    last_starter = db["pvp_last_starter"].get(f"{p1}_{p2}", p1)
    starter = p2 if last_starter == p1 else p1
    db["pvp_last_starter"][f"{p1}_{p2}"] = starter

    db[p1]["balance"] -= 20
    db[p2]["balance"] -= 20
    save_db(db)

    notify_pvp_start_with_starter(context, p1, p2, starter)
    query.message.reply_text("🔁 Rematch starting!")


def clean_expired_pvp(context: CallbackContext):
    now = time.time()
    expired_keys = []

    for key, session in list(active_pvp_sessions.items()):
        if session["game"].finished:
            expired_keys.append(key)
            continue

        if now - session["last_active"] > 60:
            game = session["game"]
            loser = game.current_player()
            winner = game.other_player()

            db = load_db()
            db[winner]["balance"] += 40
            save_db(db)

            context.bot.send_message(chat_id=winner, text="🏆 Your opponent timed out. You won +40 ELI.")
            context.bot.send_message(chat_id=loser, text="⌛ You lost by timeout. Be faster next time.")

            expired_keys.append(key)

    for key in expired_keys:
        del active_pvp_sessions[key]


def cancel_pvp(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()

    if user_id in db.get("pvp_queue", []):
        db["pvp_queue"].remove(user_id)
        save_db(db)
        update.message.reply_text("❌ You left the PvP queue.")
    else:
        update.message.reply_text("ℹ️ You’re not in the PvP queue.")

def handle_activate_wallet(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        """🔓 *Activate Wallet Access*

To unlock full gameplay and withdrawals:

1. Send ₦2000 to the admin.
2. Include caption: `Activate {user_id}`
3. Pay ₦2000 via Flutterwave: https://flutterwave.com/pay/wxvbvvskvddj
4. After payment, send a message here with your proof (screenshot or transaction ID). Admin will confirm and activate your wallet.
""",
        parse_mode=ParseMode.MARKDOWN
    )


def recalculate_wallet(db=None):
    if db is None:
        db = load_db()

    user_balances = {
        uid: user.get("balance", 0)
        for uid, user in db.items()
        if isinstance(user, dict) and user.get("registered") and "balance" in user
    }

    total_user = sum(user_balances.values())
    bonus_balance = db.get("bonus_wallet", {}).get("balance", 0)
    bot_balance = db.get("bot_wallet", {}).get("balance", 0)
    ai_burned = db.get("ai_wallet", {}).get("burned", 0)
    bank_locked = db.get("bank_wallet", {}).get("locked", 0)

    # Corrected circulating: exclude bot wallet
    circulating = total_user + bonus_balance + bank_locked

    db["metrics"] = {
        "user_balances": total_user,
        "bonus_wallet": bonus_balance,
        "bank_locked": bank_locked,
        "bot_wallet": bot_balance,
        "ai_burned": ai_burned,
        "circulating": circulating
    }

    if circulating > 5_000_000:
        print("⚠️ Circulating exceeds total supply!")

    return db
def withdrawal_menu(update: Update, context: CallbackContext):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Start Withdrawal", callback_data="initiate_withdrawal")],
        [InlineKeyboardButton("❌ Cancel Withdrawal", callback_data="cancel_withdrawal_menu")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
    ])
    update.callback_query.message.edit_text("💼 *Withdrawal Menu*", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

def cancel_withdrawal_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)

    db = load_db()
    withdrawals = db.get("pending_withdrawals", [])
    withdrawal = next((w for w in withdrawals if w["user_id"] == user_id), None)

    if not withdrawal:
        query.edit_message_text("❌ You have no pending withdrawal to cancel.")
        return

    amount = withdrawal["amount"]

    # Refund balance and unlock
    db[user_id]["balance"] += amount
    db["bank_wallet"]["locked"] -= amount

    # Remove the withdrawal
    db["pending_withdrawals"] = [w for w in withdrawals if w["user_id"] != user_id]
    save_db(db)

    query.edit_message_text("❌ Your withdrawal has been canceled.\n💰 Coins refunded to your wallet.")

def initiate_withdrawal(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()
    user = db.get(user_id, {})

    if not user.get("activated"):
        update.callback_query.message.reply_text("🔒 You must activate your wallet to withdraw.")
        return

    context.user_data["awaiting_withdraw_amount"] = True
    update.callback_query.message.reply_text("💸 How much ELI would you like to withdraw?\n\nMinimum: 120 ELI")

def handle_combined_user_input(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    db = load_db()
    user = db.get(user_id, {})

    # Step 1: Handle Withdrawal Amount
    if context.user_data.get("awaiting_withdraw_amount"):
        try:
            amount = int(text)
        except:
            update.message.reply_text("❌ Invalid amount. Enter a number like 120")
            return

        if amount < 120:
            update.message.reply_text("❌ Minimum withdrawal is 120 ELI (100 paid, 20 fee)")
            return

        balance = user.get("balance", 0)
        if balance < amount:
            update.message.reply_text(f"❌ You have {balance} ELI, not enough to withdraw {amount}.")
            return

        context.user_data["withdraw_amount"] = amount
        context.user_data["awaiting_withdraw_amount"] = False
        context.user_data["awaiting_withdraw_account"] = True

        update.message.reply_text(
            "✅ Amount received.\nNow enter your bank details in this format:\n\n"
            "`BankName AccountNumber AccountName`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Step 2: Handle Bank Details (for withdrawal or sell offer)
    if context.user_data.get("awaiting_withdraw_account") or context.user_data.get("awaiting_bank_details"):
        parts = text.split(maxsplit=2)
        if len(parts) != 3:
            update.message.reply_text("⚠️ Invalid format. Use:\n`BankName AccountNumber AccountName`", parse_mode=ParseMode.MARKDOWN)
            return

        bank_name, account_number, account_name = parts
        context.user_data["bank_name"] = bank_name
        context.user_data["account_number"] = account_number
        context.user_data["account_name"] = account_name

        # Handle withdrawal request
        if context.user_data.get("awaiting_withdraw_account"):
            amount = context.user_data.get("withdraw_amount", 0)
            fee = int(amount * 0.20)
            net = amount - fee

            user["balance"] -= amount
            db[user_id] = user
            db.setdefault("bank_wallet", {}).setdefault("locked", 0)
            db["bank_wallet"]["locked"] += amount

            db.setdefault("pending_withdrawals", []).append({
                "user_id": user_id,
                "amount": amount,
                "fee": fee,
                "paid": net,
                "bank_name": bank_name,
                "account_number": account_number,
                "account_name": account_name,
                "timestamp": datetime.now().isoformat()
            })

            save_db(db)
            context.user_data.clear()

            update.message.reply_text(
                f"✅ Withdrawal request submitted for {net} ELI.\n"
                f"🔒 Coins locked pending admin approval.\n"
                f"💰 20% fee applied: {fee} ELI"
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve Withdrawal", callback_data=f"approve_withdraw:{user_id}")]
            ])
            context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"💸 *Withdrawal Request*\n\n"
                    f"👤 User: `{user_id}`\n"
                    f"💰 Amount: {net} ELI\n"
                    f"🧾 Fee: {fee} ELI\n"
                    f"🏦 Bank: {bank_name} {account_number} ({account_name})"
                ),
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Handle sell offer bank input
        elif context.user_data.get("awaiting_bank_details"):
            context.user_data["awaiting_bank_details"] = False
            finish_post_offer(update, context)
            return

    # Step 3: Handle Offer Input
    if context.user_data.get("awaiting_post_offer"):
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            update.message.reply_text("⚠️ Invalid offer format.\nUse: `<amount> <rate>`\nExample: `300 600`", parse_mode=ParseMode.MARKDOWN)
            return

        amount, rate = map(int, parts)
        context.user_data["amount"] = amount
        context.user_data["rate"] = rate
        context.user_data["awaiting_post_offer"] = False

        offer_type = context.user_data.get("offer_type")
        if offer_type == "buy":
            finish_post_offer(update, context)
        else:
            context.user_data["awaiting_bank_details"] = True
            update.message.reply_text("🏦 Now enter your bank details:\n`BankName AccountNumber AccountName`", parse_mode=ParseMode.MARKDOWN)
        return

    # ❌ Unknown Input
    update.message.reply_text("❌ Unexpected input. Please use the marketplace or withdrawal menu.")


def handle_withdraw_account_input(update: Update, context: CallbackContext):
    if not context.user_data.get("awaiting_withdraw_account"):
        return

    parts = update.message.text.strip().split(maxsplit=2)
    if len(parts) != 3:
        update.message.reply_text("⚠️ Invalid format. Use:\n`BankName AccountNumber AccountName`", parse_mode=ParseMode.MARKDOWN)
        return

    user_id = str(update.effective_user.id)
    db = load_db()
    user = db.get(user_id, {})
    amount = context.user_data.get("withdraw_amount")

    fee = int(amount * 0.20)
    net_amount = amount - fee

    user["balance"] -= amount
    db[user_id] = user

    db.setdefault("bank_wallet", {}).setdefault("locked", 0)
    db["bank_wallet"]["locked"] += amount

    db.setdefault("pending_withdrawals", []).append({
        "user_id": user_id,
        "amount": amount,
        "fee": fee,
        "paid": net_amount,
        "bank_name": parts[0],
        "account_number": parts[1],
        "account_name": parts[2],
        "timestamp": datetime.now().isoformat()
    })

    save_db(db)
    context.user_data["awaiting_withdraw_account"] = False
    context.user_data["withdraw_amount"] = None

    update.message.reply_text(
        f"✅ Withdrawal request submitted for {net_amount} ELI.\n"
        f"🔒 Your coins are locked pending admin approval.\n"
        f"💰 20% fee applied: {fee} ELI"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve Withdrawal", callback_data=f"approve_withdraw:{user_id}")]
    ])

    context.bot.send_message(
        chat_id=ADMIN_ID,  # Replace with your actual admin ID
        text=(
            f"💸 *Withdrawal Request*\n\n"
            f"👤 User: `{user_id}`\n"
            f"💰 Amount: {net_amount} ELI\n"
            f"🧾 Fee: {fee} ELI\n"
            f"🏦 Bank: {parts[0]} {parts[1]} ({parts[2]})"
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )



def approve_withdrawal(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.data.split(":")[1]

    db = load_db()
    withdrawals = db.get("pending_withdrawals", [])
    withdrawal = next((w for w in withdrawals if w["user_id"] == user_id), None)

    if not withdrawal:
        query.edit_message_text("❌ No pending withdrawal found.")
        return

    amount = withdrawal["amount"]
    fee = withdrawal["fee"]

    db["bank_wallet"]["locked"] -= amount
    db["bot_wallet"]["balance"] += amount

    db["pending_withdrawals"] = [w for w in withdrawals if w["user_id"] != user_id]
    save_db(db)

    context.bot.send_message(chat_id=user_id, text=f"✅ Your withdrawal of {amount - fee} ELI has been approved and paid.")
    query.edit_message_text(f"✅ Approved {amount - fee} ELI withdrawal for `{user_id}`.", parse_mode=ParseMode.MARKDOWN)

def reject_withdrawal(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.data.split(":")[1]

    db = load_db()
    withdrawals = db.get("pending_withdrawals", [])
    withdrawal = next((w for w in withdrawals if w["user_id"] == user_id), None)

    if not withdrawal:
        query.edit_message_text("❌ No pending withdrawal found.")
        return

    amount = withdrawal["amount"]

    db[user_id]["balance"] += amount
    db["bank_wallet"]["locked"] -= amount

    db["pending_withdrawals"] = [w for w in withdrawals if w["user_id"] != user_id]
    save_db(db)

    context.bot.send_message(chat_id=user_id, text="❌ Your withdrawal was rejected. Coins refunded to your wallet.")
    query.edit_message_text(f"❌ Rejected withdrawal for `{user_id}`.", parse_mode=ParseMode.MARKDOWN)



def marketplace_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(update.effective_user.id)
    db = load_db()
    user = db.get(user_id, {})

    if not user.get("activated"):
        query.message.reply_text("🔒 You must activate your wallet (₦2000) to use the marketplace.")
        return

    keyboard = [
        [InlineKeyboardButton("1️⃣ Buy Elicoin (Nigeria)", callback_data="buy_ng")],
        [InlineKeyboardButton("2️⃣ Buy Elicoin (Ghana)", callback_data="buy_gh")],
        [InlineKeyboardButton("3️⃣ Sell Elicoin", callback_data="sell_menu")],
        [InlineKeyboardButton("4️⃣ Post Offer", callback_data="post_offer")],
        [InlineKeyboardButton("📄 My Offers", callback_data="my_offers")],
        [InlineKeyboardButton("5️⃣ View Current Rate", callback_data="view_rate")],
        [InlineKeyboardButton("6️⃣ Escrow Support", callback_data="escrow_help")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="submenu")]
    ]

    query.edit_message_text("🛍 *Elicoin Marketplace Menu*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# === GIFT LOG ===
def giftlog(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    db = load_db()
    logs = db.get(user_id, {}).get("giftlog", [])
    if not logs:
        update.message.reply_text("📭 No gifting history yet.")
    else:
        message = "📜 Your recent gift log:\n"
        for entry in logs[-10:]:
            message += f"- {entry}\n"
        update.message.reply_text(message)


# === SHARE COIN GIFT ===
def gift(update: Update, context: CallbackContext):
    db = load_db()
    sender_id = str(update.effective_user.id)

    if sender_id not in db or not db[sender_id].get("registered"):
        update.message.reply_text("❌ You must register first to share coins.")
        return

    if not db[sender_id].get("activated"):
        update.message.reply_text("🔒 You must activate your wallet (₦2000) to send gifts. Use /menu to activate.")
        return

    args = context.args
    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        update.message.reply_text("⚠️ Format: /sharecoingift <user_id> <amount>")
        return

    recipient_id, amount = args
    amount = int(amount)

    if amount > 500:
        update.message.reply_text("🚫 You can only send up to 500 ELI per day.")
        return

    fee = int(amount * 0.10)
    total_deducted = amount + fee

    if db[sender_id]["balance"] < total_deducted:
        update.message.reply_text("❌ Insufficient balance.")
        return

    if recipient_id not in db:
        update.message.reply_text("❌ Recipient not found.")
        return

    context.user_data["pending_gift"] = {
        "recipient_id": recipient_id,
        "amount": amount,
        "fee": fee
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm_gift"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_gift")
        ]
    ])

    update.message.reply_text(
        f"🎁 You are about to send {amount} ELI to user `{recipient_id}`.\n"
        f"Fee: {fee} ELI\nTotal Deducted: {total_deducted} ELI\n\nConfirm?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


def handle_gift_confirmation(update: Update, context: CallbackContext):
    query = update.callback_query
    sender_id = str(query.from_user.id)
    db = load_db()

    if query.data == "confirm_gift":
        gift_data = context.user_data.get("pending_gift")
        if not gift_data:
            query.answer("❌ No pending gift.")
            return

        recipient_id = gift_data["recipient_id"]
        amount = gift_data["amount"]
        fee = gift_data["fee"]
        total_deducted = amount + fee

        if db[sender_id]["balance"] < total_deducted:
            query.edit_message_text("❌ Insufficient balance at time of confirmation.")
            context.user_data.pop("pending_gift", None)
            return

        db.setdefault("bot_wallet", {}).setdefault("balance", 0)

        db[sender_id]["balance"] -= total_deducted
        db[recipient_id]["balance"] = db[recipient_id].get("balance", 0) + amount
        db["bot_wallet"]["balance"] += fee

        db[sender_id].setdefault("giftlog", [])
        db[sender_id]["giftlog"].append(f"Sent {amount} ELI to {recipient_id} (Fee: {fee})")

        save_db(db)

        query.edit_message_text(f"✅ Gift sent! {amount} ELI to {recipient_id} (Fee: {fee})")
        context.bot.send_message(chat_id=int(recipient_id), text=f"🎁 You received {amount} ELI from user {sender_id}!")

    elif query.data == "cancel_gift":
        query.edit_message_text("❌ Gift cancelled.")

    context.user_data.pop("pending_gift", None)



def safe_reply(update: Update, text: str, **kwargs):
    if update.message:
        return update.message.reply_text(text, **kwargs)
    elif update.callback_query:
        return update.callback_query.message.reply_text(text, **kwargs)
    elif update.effective_message:
        return update.effective_message.reply_text(text, **kwargs)


def claim_bonus(update: Update, context: CallbackContext):
    db = load_db()
    user_id = str(update.effective_user.id)

    if user_id not in db or not db[user_id].get("registered"):
        update.effective_message.reply_text("🚫 You must register first using /start.")
        return

    if not db[user_id].get("activated"):
        update.effective_message.reply_text("🔒 You must activate your wallet to claim bonuses. Use /menu to activate.")
        return

    db.setdefault("bonus_wallet", {"balance": 1_000_000})
    db.setdefault("bot_wallet", {"balance": 3_700_000})
    db.setdefault("ai_wallet", {"burned": 300_000})

    BONUS_AMOUNT = 10
    MAX_CIRCULATING = 5_000_000
    now = datetime.now()

    total_user_balances = sum(
        user.get("balance", 0)
        for uid, user in db.items()
        if isinstance(user, dict) and user.get("registered") and "balance" in user
    )
    bot_balance = db["bot_wallet"]["balance"]
    bonus_balance = db["bonus_wallet"]["balance"]
    ai_burned = db["ai_wallet"]["burned"]
    current_circulating = total_user_balances + bot_balance + bonus_balance

    last_claim_str = db[user_id].get("last_bonus")
    try:
        last_claim = datetime.strptime(last_claim_str, "%Y-%m-%d") if last_claim_str else None
    except:
        last_claim = None

    days_passed = (now - last_claim).days if last_claim else 999
    if days_passed < 7:
        remaining = 7 - days_passed
        update.effective_message.reply_text(f"⏳ You can claim your next bonus in {remaining} day(s).")
        return

    if bonus_balance < BONUS_AMOUNT:
        update.effective_message.reply_text("🚫 Not enough funds in the bonus wallet.")
        return

    if current_circulating + BONUS_AMOUNT > MAX_CIRCULATING:
        update.effective_message.reply_text("🚫 Bonus would exceed total circulating cap (5M ELI).")
        return

    db[user_id]["balance"] = db[user_id].get("balance", 0) + BONUS_AMOUNT
    db["bonus_wallet"]["balance"] -= BONUS_AMOUNT
    db[user_id]["last_bonus"] = now.strftime("%Y-%m-%d")
    save_db(db)

    update.effective_message.reply_text(f"🎁 Weekly bonus claimed: +{BONUS_AMOUNT} ELI added to your wallet.")


def wallet(update: Update, context: CallbackContext):
    db = load_db()
    db.setdefault("bot_wallet", {"balance": 3700000})
    db.setdefault("ai_wallet", {"burned": 300000})
    db.setdefault("bonus_wallet", {"balance": 1000000})

    user_id = str(update.effective_user.id)
    query = update.callback_query
    query.answer()

    if user_id not in db or not db[user_id].get("registered"):
        query.message.reply_text("❌ You must be registered to check your wallet.")
        return

    user_data = db[user_id]
    balance = user_data.get("balance", 0)
    last_bonus = user_data.get("last_bonus")
    last_bonus_display = last_bonus if last_bonus else "No claim yet"

    total_burned = db["ai_wallet"]["burned"]
    bot_balance = db["bot_wallet"]["balance"]
    bonus_balance = db["bonus_wallet"]["balance"]

    query.message.reply_text(
        f"👤 *Your Elicoin Wallet*\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"💼 Balance: *{balance:,} ELI*\n"
        f"📅 Last Weekly Bonus: `{last_bonus_display}`\n\n"
        f"🏦 Bot Wallet: {bot_balance:,} ELI\n"
        f"🎯 Bonus Wallet: {bonus_balance:,} ELI\n"
        f"🔥 Total Burned (AI): {total_burned:,} ELI\n\n"
        f"💸 _Fees:_\n"
        f"• 5% on AI & PvP wins\n"
        f"• 5% on /gift and /withdraw\n"
        f"• 2.5% on top-ups\n",
        parse_mode=ParseMode.MARKDOWN
    )



def ai_wallet(update: Update, context: CallbackContext):
    db = load_db()
    user_ai_losses = sum(user.get("ai_losses", 0) for user in db.values() if isinstance(user, dict))
    burned = 300000 + user_ai_losses
    query = update.callback_query
    query.answer()
    query.message.reply_text(f"🔥 Total Elicoin Burned by AI: {burned} ELI")

def bot_wallet(update: Update, context: CallbackContext):
    db = load_db()

    # === RE-CALCULATE DYNAMIC BALANCES ===
    total_user_balances = sum(
        user.get("balance", 0)
        for user in db.values()
        if isinstance(user, dict) and user.get("registered") and "balance" in user
    )

    # Ensure all system wallets exist
    db.setdefault("bot_wallet", {"balance": 0})
    db.setdefault("bonus_wallet", {"balance": 0})
    db.setdefault("ai_wallet", {"burned": 0})
    db.setdefault("locked_wallets", {
        "marketplace": 1_000_000,
        "app": 1_000_000,
        "minting": 3_000_000
    })

    bot_balance = db["bot_wallet"]["balance"]
    ai_burned = db["ai_wallet"]["burned"]
    bonus_balance = db["bonus_wallet"]["balance"]
    locked = db["locked_wallets"]

    # Total circulating = user + bonus + bot
    circulating = total_user_balances + bonus_balance + bot_balance

    # Save metrics to DB for other uses (optional)
    db["metrics"] = {
        "user_wallets": total_user_balances,
        "bonus_wallet": bonus_balance,
        "bot_wallet": bot_balance,
        "ai_burned": ai_burned,
        "circulating": circulating,
        "timestamp": datetime.now().isoformat()
    }
    save_db(db)

    # === DISPLAY MESSAGE ===
    update.effective_message.reply_text(
        f"📊 *Elicoin Wallet Overview*\n\n"
        f"🪙 *Fixed Supply*: 10,000,000 ELI\n\n"
        f"💼 *Game Wallet (bot)*: {bot_balance:,} ELI\n"
        f"🔥 *AI Burned*: {ai_burned:,} ELI\n"
        f"🎯 *Bonus/Referral*: {bonus_balance:,} ELI\n"
        f"👥 *In User Wallets*: {total_user_balances:,} ELI\n"
        f"💹 *Total Circulating*: {circulating:,} / 5,000,000 ELI\n\n"
        f"🔒 *Locked Pools:*\n"
        f"   - Marketplace: {locked['marketplace']:,} ELI\n"
        f"   - App Reserve: {locked['app']:,} ELI\n"
        f"   - Mint Reserve: {locked['minting']:,} ELI\n",
        parse_mode=ParseMode.MARKDOWN
    )


def show_top_earners(update: Update, context: CallbackContext):
    query = update.callback_query
    db = load_db()

    # Get all registered users with balances
    users = []
    for uid, data in db.items():
        if isinstance(data, dict) and data.get("registered") and uid.isdigit():
            users.append((uid, data.get("balance", 0)))

    if not users:
        query.message.reply_text("📭 No users found.")
        return

    # Sort by balance (highest first)
    users.sort(key=lambda x: x[1], reverse=True)

    # Take top 10
    top_list = users[:10]

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    message = "🏆 *Top Earners Leaderboard*\n\n"

    for i, (uid, bal) in enumerate(top_list):
        username = db[uid].get("username") or f"User_{uid}"
        # Escape special characters in Markdown usernames
        safe_username = username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[")
        message += f"{medals[i]} {safe_username} — {bal} ELI\n"

    query.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)



TOTAL_SUPPLY = 5000000  # global constant, place at the top of your file

def approve_topup(update: Update, context: CallbackContext):
    query = update.callback_query
    db = load_db()

    if not query.data.startswith("approve_topup:"):
        return

    user_id = query.data.split(":")[1]
    user = db.get(user_id, {})
    topup = user.get("pending_topup")

    if not topup:
        query.edit_message_text("❌ No pending top-up found.")
        return

    amount = topup.get("amount", 0)
    fee = int(amount * 0.025)
    net_amount = amount - fee

    db.setdefault("bot_wallet", {})
    bot_balance = db["bot_wallet"].get("balance", 0)

    if bot_balance < amount:
        query.edit_message_text("❌ Bot wallet doesn't have enough coins to approve this top-up.")
        return

    # 🔻 Deduct full amount from bot
    db["bot_wallet"]["balance"] -= amount

    # 🔼 Credit user with net coins
    user["balance"] = user.get("balance", 0) + net_amount
    user.pop("pending_topup", None)
    db[user_id] = user

    # 🧾 Log transaction
    db.setdefault("transactions", [])
    db["transactions"].append({
        "type": "topup",
        "user_id": user_id,
        "gross": amount,
        "fee": fee,
        "net": net_amount,
        "timestamp": datetime.now().isoformat()
    })

    # 🧮 Update circulating supply (optional - for tracking/reporting)
    bank_locked = db.get("bank_wallet", {}).get("locked", 0)
    circulating = TOTAL_SUPPLY - db["bot_wallet"]["balance"] - bank_locked
    db["circulating_supply"] = circulating

    save_db(db)

    # Notify user and admin
    context.bot.send_message(chat_id=user_id, text=f"✅ Top-up of {net_amount} ELI approved.\nFee: {fee} ELI deducted.")
    query.edit_message_text(f"💸 Approved {amount} ELI for user `{user_id}` (Net: {net_amount})", parse_mode=ParseMode.MARKDOWN)

def show_transaction_log(update: Update, context: CallbackContext):
    db = load_db()
    txs = db.get("transactions", [])[-5:]  # last 5

    if not txs:
        update.message.reply_text("📭 No transactions recorded yet.")
        return

    msg = "*🧾 Recent Transactions:*\n"
    for tx in reversed(txs):
        msg += f"- {tx['type'].title()} of {tx['net']} ELI (Fee: {tx['fee']}) on {tx['timestamp'][:19]}\n"
    update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


def admin_only(func):
    def wrapper(update: Update, context: CallbackContext):
        user_id = str(update.effective_user.id)
        if isinstance(ADMIN_ID, (list, tuple, set)):
            if user_id not in ADMIN_ID:
                update.message.reply_text("⛔️ Admins only.")
                return
        elif str(user_id) != str(ADMIN_ID):
            update.message.reply_text("⛔️ Admins only.")
            return
        return func(update, context)
    return wrapper

def return_locked_funds(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only.")
        return

    args = context.args
    if len(args) != 2:
        update.message.reply_text("⚠️ Usage: /return_locked <user_id> <amount>")
        return

    target_id = args[0]
    try:
        amount = int(args[1])
    except ValueError:
        update.message.reply_text("❌ Amount must be a number.")
        return

    db = load_db()
    user = db.get(target_id)
    if not user:
        update.message.reply_text("❌ User not found.")
        return

    locked = db.get("bank_wallet", {}).get("locked", 0)
    if amount > locked:
        update.message.reply_text("❌ Not enough locked funds.")
        return

    # Return funds
    db["bank_wallet"]["locked"] -= amount
    user["balance"] = user.get("balance", 0) + amount
    db[target_id] = user
    save_db(db)

    update.message.reply_text(f"✅ Returned {amount} ELI to user `{target_id}`.")
    context.bot.send_message(chat_id=target_id, text=f"🔄 {amount} ELI returned to your wallet by admin.")


@admin_only
def admin_panel(update: Update, context: CallbackContext):
    db = load_db()
    pending = db.get("pending_withdrawals", [])

    if not pending:
        update.message.reply_text("✅ No pending withdrawal requests.")
        return

    for wd in pending:
        user_id = wd["user_id"]
        amount = wd["amount"]
        fee = wd["fee"]
        paid = wd["paid"]
        bank_name = wd["bank_name"]
        account_number = wd["account_number"]
        account_name = wd["account_name"]

        msg = (
            f"📤 *Pending Withdrawal*\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"💰 Requested: {amount} ELI\n"
            f"🧾 Paid: {paid} ELI\n"
            f"💸 Fee: {fee} ELI (20%)\n"
            f"🏦 Bank: {bank_name} {account_number} ({account_name})"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_withdrawal:{user_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_withdrawal:{user_id}"),
                InlineKeyboardButton("🔁 Return", callback_data=f"return_locked:{user_id}")
            ]
        ])

        context.bot.send_message(chat_id=update.effective_chat.id, text=msg, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)




def buy_ng(update: Update, context: CallbackContext):
    view_sell_offers_by_country(update, context, "Nigeria")

def buy_gh(update: Update, context: CallbackContext):
    view_sell_offers_by_country(update, context, "Ghana")


def sell_menu(update: Update, context: CallbackContext):
    db = load_db()
    offers = [o for o in db.get("offers", []) if o["type"] == "buy" and o["status"] == "active"]

    if not offers:
        update.effective_message.reply_text("📭 No active buy offers right now.")
        return

    message = "📥 *Buy Offers Available:*\n\n"
    for o in offers:
        flag = "🇳🇬" if o.get("country") == "Nigeria" else "🇬🇭"
        message += f"{flag} {o['amount']} ELI @ ₦{o['rate']} – Offer ID: `{o['id']}`\n"

    update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def view_sell_offers_by_country(update: Update, context: CallbackContext, country):
    db = load_db()
    offers = [
        o for o in db.get("offers", [])
        if o["type"] == "sell" and o["status"] == "active" and o["country"] == country
    ]

    if not offers:
        update.effective_message.reply_text(f"📭 No sell offers from {country}.")
        return

    message = f"💰 *Sell Offers – {country}:*\n\n"
    for o in offers:
        message += f"🔹 {o['amount']} ELI @ ₦{o['rate']} – Offer ID: `{o['id']}`\n"

    update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def handle_buy_offer_click(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    offer_id = query.data.split(":")[1]
    db = load_db()

    offer = next((o for o in db.get("offers", []) if o["id"] == offer_id and o["status"] == "active"), None)
    if not offer:
        query.message.reply_text("❌ Offer not found.")
        return

    offer["buyer_id"] = user_id
    offer["status"] = "pending_payment"
    save_db(db)

    seller_info = (
        f"🏦 *Bank Details*\n"
        f"Bank: `{offer['bank_name']}`\n"
        f"Account: `{offer['account_number']}`\n"
        f"Name: `{offer['account_name']}`\n\n"
        f"📌 *IMPORTANT*: In your payment description, ONLY write this: `{offer['user_id']}`\n"
        f"❌ Do NOT include 'Elicoin' or crypto terms.\n\n"
    )

    tips = (
        "⚠️ *Security Tips*\n"
        "• Double-check account name.\n"
        "• Keep your transfer screenshot.\n"
        "• Do not release if you didn’t receive payment."
    )

    query.message.reply_text(
        f"💸 You are buying *{offer['amount']} ELI* at ₦{offer['rate']}/coin.\n\n" + seller_info + tips,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Paid", callback_data=f"buyer_paid:{offer_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="marketplace_menu")]
        ])
    )


def handle_buyer_payment_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    offer_id = query.data.split(":")[1]
    db = load_db()

    offer = next((o for o in db.get("offers", []) if o["id"] == offer_id), None)
    if not offer or offer.get("buyer_id") != user_id:
        query.answer("❌ Not your trade.")
        return

    offer["status"] = "awaiting_release"
    save_db(db)

    context.user_data["uploading_receipt"] = offer_id

    context.bot.send_message(
        chat_id=int(offer["user_id"]),
        text=(
            f"📢 Buyer has marked payment as done for Offer `{offer_id}`.\n"
            "Please verify in your bank and wait for the screenshot proof.\n"
            "Then tap below to release the coins."
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Payment", callback_data=f"seller_confirm:{offer_id}")],
            [InlineKeyboardButton("⚠️ Dispute", callback_data=f"raise_dispute:{offer_id}")]
        ])
    )

    query.message.reply_text("✅ Now upload your payment screenshot.")

def handle_photo_combined(update: Update, context: CallbackContext):
    admin_id = ADMIN_ID
    user_id = str(update.effective_user.id)
    db = load_db()

    # Validate photo
    if not update.message.photo:
        update.message.reply_text("❌ Please send a valid screenshot/photo.")
        return

    file_id = update.message.photo[-1].file_id
    caption_text = update.message.caption or ""

    # === MARKETPLACE PAYMENT RECEIPT ===
    offer_id = context.user_data.get("uploading_receipt")
    if offer_id:
        offer = next((o for o in db.get("offers", []) if o["id"] == offer_id), None)
        if not offer:
            update.message.reply_text("❌ Trade not found.")
            return

        offer["receipt_photo"] = file_id
        save_db(db)

        seller_id = int(offer["user_id"])
        context.bot.send_photo(
            chat_id=seller_id,
            photo=file_id,
            caption=f"🧾 Buyer uploaded payment screenshot for Offer `{offer_id}`.\nPlease confirm after verifying payment."
        )

        update.message.reply_text("✅ Receipt uploaded. Waiting for seller to confirm.")
        context.user_data.pop("uploading_receipt", None)
        return

    # === TWITTER BONUS ===
    if context.user_data.get("awaiting_twitter_screenshot"):
        if db.get(user_id, {}).get("twitter_bonus_claimed"):
            update.message.reply_text("⚠️ You've already received your Twitter bonus.")
            return

        db.setdefault(user_id, {})["twitter_bonus_claimed"] = True
        db[user_id]["balance"] = db[user_id].get("balance", 0) + 10
        db.setdefault("bonus_wallet", {})["balance"] = db.get("bonus_wallet", {}).get("balance", 1000000) - 10
        save_db(db)

        update.message.reply_text("🎉 10 ELI added to your wallet! Thank you for supporting us on Twitter.")
        context.user_data["awaiting_twitter_screenshot"] = False
        return

    # === WALLET ACTIVATION PROOF ===
    if caption_text.strip().lower().startswith("activate"):
        db.setdefault(user_id, {})["pending_activation"] = True
        save_db(db)

        context.bot.send_photo(
            chat_id=admin_id,
            photo=file_id,
            caption=f"🔓 Activation proof from user `{user_id}`\n\nUse /activate {user_id} to approve.",
            parse_mode=ParseMode.MARKDOWN
        )
        update.message.reply_text("🖼 Activation screenshot sent. Awaiting admin approval.")
        return

    # === TOP-UP RECEIPT ===
    if context.user_data.get("topup_pending"):
        import re
        match = re.search(r"(\d+)", caption_text)
        if not match:
            update.message.reply_text("❌ Please include the amount in the caption (e.g. `200`).")
            return
        amount = int(match.group(1))

        db.setdefault(user_id, {})["pending_topup"] = {"amount": amount}
        save_db(db)

        caption = f"📥 Payment proof from user `{user_id}`\n💰 Amount: {amount} ELI\n\nApprove below:"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve Top-Up", callback_data=f"approve_topup:{user_id}")]
        ])
        context.bot.send_photo(
            chat_id=admin_id,
            photo=file_id,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

        update.message.reply_text("🖼 Payment proof sent. Awaiting admin approval.")
        context.user_data.pop("topup_pending", None)
        return

    # === DEFAULT CASE ===
    update.message.reply_text(
        "❌ Unrecognized screenshot.\n\n"
        "• For activation, use caption: `Activate <your user ID>`.\n"
        "• For top-up, use `/topup` and add the amount in the caption.\n"
        "• For trades, only upload receipt after marking payment.\n"
        "• For Twitter bonus, click the Twitter Share button first."
    )


def activate_user(update: Update, context: CallbackContext):
    if str(update.effective_user.id) != ADMIN_ID:
        update.message.reply_text("🚫 You are not authorized to activate wallets.")
        return

    if len(context.args) != 1:
        update.message.reply_text("Usage: /activate <user_id>")
        return

    user_id = context.args[0]
    db = load_db()

    if user_id not in db:
        update.message.reply_text("❌ User ID not found.")
        return

    user = db[user_id]
    if user.get("activated"):
        update.message.reply_text("✅ User is already activated.")
        return

    user["activated"] = True
    save_db(db)

    update.message.reply_text(f"✅ User {user_id} has been activated.")
    context.bot.send_message(chat_id=int(user_id), text="🔓 Your wallet has been activated! You can now access full features.")



def handle_seller_confirm_release(update: Update, context: CallbackContext):
    query = update.callback_query
    seller_id = str(query.from_user.id)
    offer_id = query.data.split(":")[1]
    db = load_db()

    offer = next((o for o in db.get("offers", []) if o["id"] == offer_id), None)
    if not offer or offer.get("user_id") != seller_id or offer.get("status") != "awaiting_release":
        query.answer("❌ You can't confirm this.")
        return

    buyer_id = offer["buyer_id"]
    amount = offer["amount"]

    # Release funds from escrow to buyer
    db.setdefault("bank_wallet", {}).setdefault("locked", 0)
    db["bank_wallet"]["locked"] = max(0, db["bank_wallet"]["locked"] - amount)
    db[buyer_id]["balance"] = db[buyer_id].get("balance", 0) + amount

    offer["status"] = "completed"
    save_db(db)

    # Notify both
    context.bot.send_message(chat_id=int(buyer_id), text=f"🎉 Coins received! {amount} ELI added to your wallet.")
    context.bot.send_message(chat_id=int(seller_id), text="✅ Trade completed. Coins released.")

    query.message.reply_text("✅ Payment confirmed and coins released.")


def post_offer_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    keyboard = [
        [InlineKeyboardButton("🟢 Post Buy Offer", callback_data="post_buy_offer")],
        [InlineKeyboardButton("🔴 Post Sell Offer", callback_data="post_sell_offer")],
        [InlineKeyboardButton("⬅️ Back to Marketplace", callback_data="marketplace_menu")]
    ]
    query.message.reply_text(
        "🤝 What type of offer do you want to post?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def start_post_offer_flow(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    offer_type = query.data
    if offer_type == "post_buy_offer":
        context.user_data["offer_type"] = "buy"
    elif offer_type == "post_sell_offer":
        context.user_data["offer_type"] = "sell"
    else:
        query.message.reply_text("❌ Unknown offer type.")
        return

    keyboard = [
        [InlineKeyboardButton("🇳🇬 Nigeria", callback_data="post_offer_ng")],
        [InlineKeyboardButton("🇬🇭 Ghana", callback_data="post_offer_gh")]
    ]
    query.message.reply_text(
        f"🌍 Choose country for your {context.user_data['offer_type'].upper()} offer:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def handle_post_offer_country(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data == "post_offer_ng":
        context.user_data["offer_country"] = "Nigeria"
    elif query.data == "post_offer_gh":
        context.user_data["offer_country"] = "Ghana"
    else:
        query.message.reply_text("❌ Unknown country.")
        return

    context.user_data["awaiting_post_offer"] = True

    offer_type = context.user_data.get("offer_type", "sell")
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"✍️ Enter your {offer_type.upper()} offer for *{context.user_data['offer_country']}*.\n\n"
            "📌 Format: `<amount> <rate>`\n"
            "Example: `300 550` (Means 300 ELI at ₦550/coin)"
        ),
        parse_mode=ParseMode.MARKDOWN
    )





def finish_post_offer(update: Update, context: CallbackContext):
    print("✅ finish_post_offer triggered")  # <== 🔍 Place this at the top

    user_id = str(update.effective_user.id)
    db = load_db()
    user = db.get(user_id, {})

    offer_type = context.user_data.get("offer_type")
    country = context.user_data.get("offer_country", "Nigeria")
    amount = context.user_data.get("amount")
    rate = context.user_data.get("rate")

    if offer_type == "sell" and user.get("balance", 0) < amount:
        update.message.reply_text("❌ You don't have enough Elicoin.")
        return

    offer = {
        "id": f"offer_{int(time.time())}",
        "user_id": user_id,
        "type": offer_type,
        "country": country,
        "amount": amount,
        "rate": rate,
        "payment_method": "bank",
        "status": "active",
        "escrow": True,
        "timestamp": datetime.now().isoformat()
    }

    if offer_type == "sell":
        offer["bank_name"] = context.user_data.get("bank_name")
        offer["account_number"] = context.user_data.get("account_number")
        offer["account_name"] = context.user_data.get("account_name")

        user["balance"] -= amount
        db.setdefault("bank_wallet", {}).setdefault("locked", 0)
        db["bank_wallet"]["locked"] += amount
        recalculate_wallet(db)

    db.setdefault("offers", []).append(offer)
    save_db(db)

    update.message.reply_text(
       f"✅ {offer_type.title()} offer posted:\n"
       f"💰 *{amount} ELI* @ *₦{rate} per 1 Elicoin* in *{country}*\n"

        + ("🔒 Coins locked in escrow." if offer_type == "sell" else "🟢 Waiting for sellers."),
        parse_mode=ParseMode.MARKDOWN
    )

    context.user_data.clear()


def my_offers(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    db = load_db()

    offers = [o for o in db.get("offers", []) if o["user_id"] == user_id and o["status"] == "active"]

    if not offers:
        query.message.reply_text("📭 You have no active offers.")
        return

    for o in offers:
        emoji = "🟢 Buy" if o["type"] == "buy" else "🔴 Sell"
        msg = (
            f"{emoji} Offer – `{o['id']}`\n"
            f"💰 {o['amount']} ELI @ ₦{o['rate']} in {o['country']}\n"
            f"Status: *{o['status']}*"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Offer", callback_data=f"cancel_offer:{o['id']}")]
        ])
        query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

def cancel_offer(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    offer_id = query.data.split(":")[1]

    db = load_db()
    offer = next((o for o in db.get("offers", []) if o["id"] == offer_id), None)

    if not offer or offer["user_id"] != user_id or offer["status"] != "active":
        query.answer("❌ Can't cancel this offer.")
        return

    offer["status"] = "cancelled"

    if offer["type"] == "sell":
        amount = offer["amount"]
        db.setdefault("bank_wallet", {}).setdefault("locked", 0)
        db["bank_wallet"]["locked"] = max(0, db["bank_wallet"]["locked"] - amount)
        db[user_id]["balance"] = db[user_id].get("balance", 0) + amount
        recalculate_wallet(db)

    save_db(db)

    query.message.reply_text("✅ Offer cancelled. Coins refunded (if locked).")


def get_dynamic_elicoin_price():
    db = load_db()
    TOTAL_SUPPLY = 5_000_000

    # Wallet breakdowns
    bot_balance = db.get("bot_wallet", {}).get("balance", 0)
    bonus_balance = db.get("bonus_wallet", {}).get("balance", 0)
    ai_burned = db.get("ai_wallet", {}).get("burned", 0)
    locked_escrow = db.get("bank_wallet", {}).get("locked", 0)

    # Define 'scarce' as: how much is still centrally held and controllable
    central_holdings = bot_balance + bonus_balance

    # Dynamic pricing logic based on central supply left
    if central_holdings > 3_000_000:
        price_ngn = 100
    elif central_holdings > 1_500_000:
        price_ngn = 500
    elif central_holdings > 500_000:
        price_ngn = 1000
    else:
        price_ngn = 1500

    # Convert to GHS
    try:
        resp = requests.get("https://api.exchangerate.host/latest?base=NGN&symbols=GHS", timeout=5)
        ghs_rate = resp.json()["rates"]["GHS"]
        price_ghs = round(price_ngn * ghs_rate, 2)
    except:
        price_ghs = "Unavailable"

    return {
        "price_ngn": price_ngn,
        "price_ghs": price_ghs,
        "central_supply": central_holdings,
        "bot_wallet": bot_balance,
        "bonus_wallet": bonus_balance,
        "ai_burned": ai_burned,
        "escrow_locked": locked_escrow,
        "user_balances": sum(
            user.get("balance", 0)
            for uid, user in db.items()
            if isinstance(user, dict) and "balance" in user and user.get("registered")
        )
    }

def handle_view_rate(update, context):
    query = update.callback_query
    data = get_dynamic_elicoin_price()

    msg = (
        f"📊 *Elicoin Current Price & Supply Info:*\n\n"
        f"💸 *Price:* ₦{data['price_ngn']} (~GH₵{data['price_ghs']})\n\n"
        f"💼 Bot Wallet: {data['bot_wallet']:,} ELI\n"
        f"🎁 Bonus Wallet: {data['bonus_wallet']:,} ELI\n"
        f"🔒 Locked in Escrow: {data['escrow_locked']:,} ELI\n"
        f"🔥 Burned (AI): {data['ai_burned']:,} ELI\n"
        f"👥 User Wallets: {data['user_balances']:,} ELI\n\n"
        f"🪙 *Central Supply Left:* {data['central_supply']:,} ELI\n"
        f"⚠️ When central supply is low, price increases automatically."
    )

    query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)


def escrow_help(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    message = """
🛡️ *Elicoin Escrow System Explained*

Escrow ensures safe trading by holding coins until payment is confirmed.

🔁 *How It Works*:
1. Seller posts an offer (with Escrow ON).
2. Buyer clicks Buy → coins are locked by bot.
3. Buyer pays & taps "✅ I Paid".
4. Seller confirms & bot releases coins.

🛡️ *Why Use Escrow?*
• Protects both buyers and sellers.
• Prevents scams during payments.
• Trusted middle layer (the bot).

✅ *You can turn escrow ON or OFF when posting offers.*
"""
    query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)



def mark_weekly_top_auto(bot):
    db = load_db()
    users = [(uid, data) for uid, data in db.items() if isinstance(data, dict) and "balance" in data]
    if not users:
        return

    top_user = max(users, key=lambda x: x[1].get("balance", 0))
    uid, data = top_user

    db["weekly_top"] = {
        "user_id": uid,
        "username": data.get("username") or f"User_{uid}",
        "balance": data.get("balance", 0),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_db(db)

    bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🤖 Weekly Top Earner automatically marked:\n👑 {db['weekly_top']['username']} – {db['weekly_top']['balance']} ELI"
    )


def mint_wallet(update: Update, context: CallbackContext):
    if datetime.now() < datetime(2025, 12, 30):
        update.message.reply_text("⛓️ Blockchain minting begins December 30, 2025.\n\nYou'll be able to connect your Elicoin wallet and see all balances on-chain.")
    else:
        update.message.reply_text("✅ Elicoin Wallet is live!\nVisit https://elicoin.africa/wallet (or your preferred DApp) to connect and view your coins.")

def rules(update: Update, context: CallbackContext):
    message = """
📜 *Elicoin Game Rules*

1. Only registered users can play or earn.
2. AI loss = 10 ELI permanently burned.
3. Bonus & referral payouts deducted from bonus_wallet.
4. Gifting limit = 500 ELI/day (5% fee applies).
5. Top-up requires screenshot proof (manual approval).
6. Withdrawals begin Nov 24 (5% fee).
7. Blockchain wallet distribution starts Dec 30.

📣 *Are You Ready?*
Earn, strategize, and dominate. 

# You can now send this INTRO_TEXT in /start or /rules command using:
# update.message.reply_text(INTRO_TEXT, parse_mode=ParseMode.MARKDOWN)

# Rules logic and command implementation already handled.
Invite. Win. Burn. Repeat.
"""
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# === SETUP HANDLERS ===
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("refer", set_referrer))
    dp.add_handler(CommandHandler("approve", approve_user, pass_args=True))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CallbackQueryHandler(handle_game_menu_selection, pattern='^(refer|bot_wallet|wallet|gift|bonus|topup|ai_wallet)$'))
    dp.add_handler(CallbackQueryHandler(show_intro, pattern='^intro$'))
    dp.add_handler(CallbackQueryHandler(handle_register, pattern='^register$'))
    dp.add_handler(CallbackQueryHandler(start_ai_game, pattern="^play_ai$"))
    dp.add_handler(CallbackQueryHandler(handle_board_move, pattern="^move_\\d$"))
    dp.add_handler(CallbackQueryHandler(handle_board_move, pattern='^ignore$'))
    dp.add_handler(CallbackQueryHandler(start_pvp, pattern="^pvp$"))
    dp.add_handler(CallbackQueryHandler(handle_pvp_callback, pattern="^pvp_move_"))
    dp.add_handler(CommandHandler("bonus", claim_bonus))
    dp.add_handler(CommandHandler("wallet", wallet))
    dp.add_handler(CommandHandler("bot_wallet", bot_wallet))
    dp.add_handler(CommandHandler("ai_wallet", ai_wallet))
    dp.add_handler(CommandHandler("mint_wallet", mint_wallet))
    dp.add_handler(CommandHandler("rules", rules))
    dp.add_handler(CommandHandler("admin_panel", admin_panel))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo_combined))
    # === HANDLER REGISTRATION ===
    dp.add_handler(CommandHandler("sharecoingift", gift))
    dp.add_handler(CallbackQueryHandler(handle_gift_confirmation, pattern="^(confirm_gift|cancel_gift)$"))
    dp.add_handler(CommandHandler("giftlog", giftlog))



    dp.add_handler(CallbackQueryHandler(approve_topup, pattern="^approve_topup:"))
    dp.add_handler(CommandHandler("mark_weekly_top", mark_weekly_top_auto))
    dp.add_handler(CallbackQueryHandler(marketplace_menu, pattern="^marketplace_menu$"))
    dp.add_handler(CallbackQueryHandler(withdrawal_menu, pattern="^withdrawal_menu$"))
    dp.add_handler(CallbackQueryHandler(buy_ng, pattern="^buy_ng$"))
    dp.add_handler(CallbackQueryHandler(buy_gh, pattern="^buy_gh$"))
    dp.add_handler(CallbackQueryHandler(sell_menu, pattern="^sell_menu$"))
    dp.add_handler(CommandHandler("cancel_pvp", cancel_pvp))
    # === Add handler for top earners ===
    dp.add_handler(CallbackQueryHandler(show_top_earners, pattern="^top_earners$"))
    dp.add_handler(CallbackQueryHandler(post_offer_menu, pattern="^post_offer$"))
    dp.add_handler(CallbackQueryHandler(start_post_offer_flow, pattern="^post_(buy|sell)_offer$"))
    dp.add_handler(CallbackQueryHandler(handle_post_offer_country, pattern="^post_offer_(ng|gh)$"))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_combined_user_input))

    dp.add_handler(CallbackQueryHandler(handle_view_rate, pattern="^view_rate$"))
    dp.add_handler(CallbackQueryHandler(escrow_help, pattern="^escrow_help$"))
    dp.add_handler(CallbackQueryHandler(menu, pattern="^submenu$"))
    dp.add_handler(CallbackQueryHandler(handle_buy_offer_click, pattern="^buy_offer:"))
    dp.add_handler(CallbackQueryHandler(handle_buyer_payment_confirm, pattern="^buyer_paid:"))
    dp.add_handler(CallbackQueryHandler(handle_seller_confirm_release, pattern="^seller_confirm:"))
    dp.add_handler(CallbackQueryHandler(my_offers, pattern="^my_offers$"))
    dp.add_handler(CallbackQueryHandler(cancel_offer, pattern="^cancel_offer:"))
    dp.add_handler(CallbackQueryHandler(handle_activate_wallet, pattern="^activate_wallet$"))
    dp.add_handler(CommandHandler("activate", activate_user))
    dp.add_handler(CallbackQueryHandler(initiate_withdrawal, pattern="^initiate_withdrawal$"))
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_withdraw_account_input))
    dp.add_handler(CallbackQueryHandler(approve_withdrawal, pattern="^approve_withdrawal:"))
    dp.add_handler(CallbackQueryHandler(reject_withdrawal, pattern="^reject_withdrawal:"))
    dp.add_handler(CallbackQueryHandler(cancel_withdrawal_menu, pattern="^cancel_withdrawal_menu$"))
    dp.add_handler(CommandHandler("return_locked", return_locked_funds))
    dp.add_handler(CallbackQueryHandler(handle_like_twitter, pattern="like_twitter"))
    dp.add_handler(CallbackQueryHandler(show_profile, pattern="^my_profile$"))


    job_queue = updater.job_queue
    job_queue.run_repeating(clean_expired_pvp, interval=15, first=15)



    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
    recalculate_wallet()



