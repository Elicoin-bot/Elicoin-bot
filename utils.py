import json
import os

DB_FILE = "database.json"

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
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)
