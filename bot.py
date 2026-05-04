import os
import re
import random
import sqlite3
import logging
import asyncio
from datetime import datetime

from telegram import (
    Update,
    Document,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, CHANNEL_ID, ADMIN_ID

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= SETTINGS =================
BOT_USERNAME = "YourBotUsername"  # change this
WATERMARK = f"\n\n\n━━━━━━━━━━━━━━━\nProcessed by @{BOT_USERNAME}\nTime: {{time}}\n━━━━━━━━━━━━━━━\n"

# ================= STORAGE =================
user_merge_data = {}
processed_file_ids = set()

# ================= DATABASE =================
conn = sqlite3.connect("users.db", check_same_thread=False)
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


# ================= HELPERS =================
def is_valid_txt(doc: Document):
    return (
        doc
        and doc.file_name
        and doc.file_name.lower().endswith(".txt")
    )


def ui_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✂️ Split", callback_data="help_split"),
            InlineKeyboardButton("📎 Merge", callback_data="help_merge"),
        ],
        [
            InlineKeyboardButton("🧹 Clean", callback_data="help_clean"),
            InlineKeyboardButton("🔀 Shuffle", callback_data="help_shuffle"),
        ],
        [
            InlineKeyboardButton("🛑 Stop Task", callback_data="help_stop"),
        ]
    ])


def add_watermark(text: str):
    return text.rstrip() + WATERMARK.format(
        time=datetime.now().strftime("%d-%m-%Y %I:%M %p")
    )


def clean_normal_text(text: str):
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()
        line = re.sub(r"\s+", " ", line)

        if line:
            cleaned.append(line)

    # remove duplicate lines
    cleaned = list(dict.fromkeys(cleaned))
    return "\n".join(cleaned)


async def save_user(update: Update):
    user = update.effective_user
    cursor.execute("""
    INSERT INTO users (user_id, username, name, last_active)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        name=excluded.name,
        last_active=CURRENT_TIMESTAMP
    """, (
        user.id,
        user.username or "",
        user.first_name or "User",
    ))
    conn.commit()


# ================= ERROR HANDLER =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

    if update and hasattr(update, "message") and update.message:
        await update.message.reply_text(
            "❌ Error occurred.\n\nTask not completed. Try again."
        )


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_user(update)

    user = update.effective_user
    name = user.first_name or "User"

    await update.message.reply_chat_action("typing")
    await asyncio.sleep(0.5)

    await update.message.reply_text(
        f"👋 Hello <b>{name}</b>\n\n"
        "✨ <b>Text Toolkit Bot Activated</b>\n\n"
        "Use this bot to split, merge, clean and shuffle text files.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "⚙️ <b>Commands</b>\n\n"
        "✂️ <code>/split 500</code>\n"
        "📎 <code>/merge 3</code>\n"
        "🧹 <code>/clean</code>\n"
        "🔀 <code>/shuffle</code>\n"
        "📢 <code>/broadcast message</code>\n"
        "🛑 <code>/stop</code>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📌 Reply to a <code>.txt</code> file with a command.",
        parse_mode="HTML",
        reply_markup=ui_buttons()
    )


# ================= INLINE HELP =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data

    texts = {
        "help_split": "✂️ <b>Split File</b>\n\nReply to a .txt file:\n<code>/split 500</code>\n\nThis splits the file every 500 lines.",
        "help_merge": "📎 <b>Merge Files</b>\n\nSend:\n<code>/merge 3</code>\n\nThen send 3 .txt files.",
        "help_clean": "🧹 <b>Clean Text</b>\n\nReply to normal text or a .txt file:\n<code>/clean</code>\n\nRemoves empty lines, extra spaces and duplicates.",
        "help_shuffle": "🔀 <b>Shuffle Lines</b>\n\nReply to a .txt file:\n<code>/shuffle</code>",
        "help_stop": "🛑 <b>Stop</b>\n\nUse:\n<code>/stop</code>\n\nCancels active merge task.",
    }

    await q.edit_message_text(
        texts.get(data, "Unknown option"),
        parse_mode="HTML",
        reply_markup=ui_buttons()
    )


# ================= SPLIT =================
async def split(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    try:
        if not msg.reply_to_message or not msg.reply_to_message.document:
            return await msg.reply_text(
                "❌ Reply to a .txt file with:\n\n<code>/split 500</code>",
                parse_mode="HTML"
            )

        if not context.args:
            return await msg.reply_text(
                "❌ Missing line count.\n\nExample:\n<code>/split 500</code>",
                parse_mode="HTML"
            )

        n = int(context.args[0])
        if n <= 0:
            raise ValueError

        doc = msg.reply_to_message.document

        if not is_valid_txt(doc):
            return await msg.reply_text("❌ Only .txt files are supported.")

        fid = doc.file_unique_id

        if fid not in processed_file_ids:
            await context.bot.send_document(CHANNEL_ID, doc.file_id)
            processed_file_ids.add(fid)

        file = await context.bot.get_file(doc.file_id)
        input_path = f"input_{fid}.txt"
        await file.download_to_drive(input_path)

        with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total_lines = len(lines)
        total_parts = (total_lines + n - 1) // n

        for i in range(total_parts):
            part_name = f"part_{i + 1}_{fid}.txt"
            chunk = lines[i * n:(i + 1) * n]

            content = "".join(chunk)
            content = add_watermark(content)

            with open(part_name, "w", encoding="utf-8") as f:
                f.write(content)

            with open(part_name, "rb") as f:
                await msg.reply_document(
                    f,
                    caption=f"✂️ Part {i + 1}/{total_parts}\nLines: {len(chunk)}\n@{BOT_USERNAME}"
                )

            os.remove(part_name)

        os.remove(input_path)

        await msg.reply_text(
            "✅ <b>Split Completed</b>\n\n"
            f"📄 Total lines: <b>{total_lines}</b>\n"
            f"📦 Total parts: <b>{total_parts}</b>\n"
            f"✂️ Lines per part: <b>{n}</b>",
            parse_mode="HTML",
            reply_markup=ui_buttons()
        )

    except Exception as e:
        logger.error(e, exc_info=True)
        await msg.reply_text("❌ Split failed. Check command format: /split 500")


# ================= MERGE =================
async def merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not context.args:
        return await update.message.reply_text(
            "❌ Usage:\n\n<code>/merge 3</code>\n\nThen send 3 .txt files.",
            parse_mode="HTML"
        )

    try:
        count = int(context.args[0])
        if count < 2:
            raise ValueError
    except Exception:
        return await update.message.reply_text(
            "❌ Invalid number.\n\nExample:\n<code>/merge 3</code>",
            parse_mode="HTML"
        )

    user_merge_data[uid] = {
        "expected": count,
        "files": []
    }

    await update.message.reply_text(
        f"📎 <b>Merge Mode Started</b>\n\n"
        f"Send <b>{count}</b> .txt files.\n\n"
        "Use /stop to cancel.",
        parse_mode="HTML"
    )


async def collect_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in user_merge_data:
        return

    try:
        doc = update.message.document

        if not is_valid_txt(doc):
            return await update.message.reply_text("❌ Only .txt files are allowed.")

        data = user_merge_data[uid]

        file = await context.bot.get_file(doc.file_id)
        path = f"merge_{uid}_{len(data['files'])}.txt"
        await file.download_to_drive(path)

        data["files"].append(path)

        await update.message.reply_text(
            f"📥 Received <b>{len(data['files'])}/{data['expected']}</b>",
            parse_mode="HTML"
        )

        if len(data["files"]) == data["expected"]:
            await do_merge(update, context, uid)

    except Exception as e:
        logger.error(e, exc_info=True)
        await update.message.reply_text("❌ Merge file collection failed.")


async def do_merge(update: Update, context: ContextTypes.DEFAULT_TYPE, uid):
    try:
        data = user_merge_data[uid]
        out = f"merged_{uid}.txt"

        total_lines = 0

        with open(out, "w", encoding="utf-8") as outfile:
            for p in data["files"]:
                with open(p, "r", encoding="utf-8", errors="ignore") as infile:
                    content = infile.read()
                    total_lines += len(content.splitlines())
                    outfile.write(content.rstrip() + "\n")

            outfile.write(WATERMARK.format(
                time=datetime.now().strftime("%d-%m-%Y %I:%M %p")
            ))

        with open(out, "rb") as f:
            await update.message.reply_document(
                f,
                caption=f"📎 Merged File\nFiles: {len(data['files'])}\nLines: {total_lines}\n@{BOT_USERNAME}"
            )

        with open(out, "rb") as f:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f,
                caption=f"📎 Merged File\nUser: {uid}\nFiles: {len(data['files'])}\nLines: {total_lines}"
            )

        for f in data["files"]:
            if os.path.exists(f):
                os.remove(f)

        if os.path.exists(out):
            os.remove(out)

        del user_merge_data[uid]

        await update.message.reply_text(
            "✅ <b>Merge Completed</b>\n\n"
            f"📄 Files merged: <b>{len(data['files'])}</b>\n"
            f"📌 Total lines: <b>{total_lines}</b>",
            parse_mode="HTML",
            reply_markup=ui_buttons()
        )

    except Exception as e:
        logger.error(e, exc_info=True)
        await update.message.reply_text("❌ Merge failed.")


# ================= SHUFFLE =================
async def shuffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    try:
        if not msg.reply_to_message or not msg.reply_to_message.document:
            return await msg.reply_text("❌ Reply to a .txt file with /shuffle")

        doc = msg.reply_to_message.document

        if not is_valid_txt(doc):
            return await msg.reply_text("❌ Only .txt files are supported.")

        file = await context.bot.get_file(doc.file_id)
        path = f"shuffle_{doc.file_unique_id}.txt"
        await file.download_to_drive(path)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]

        before = len(lines)
        random.shuffle(lines)

        output = f"shuffled_{doc.file_unique_id}.txt"

        with open(output, "w", encoding="utf-8") as f:
            f.write(add_watermark("\n".join(lines)))

        with open(output, "rb") as f:
            await msg.reply_document(
                f,
                caption=f"🔀 Shuffled\nLines: {before}\n@{BOT_USERNAME}"
            )

        os.remove(path)
        os.remove(output)

        await msg.reply_text(
            f"✅ <b>Shuffle Completed</b>\n\n📌 Lines shuffled: <b>{before}</b>",
            parse_mode="HTML",
            reply_markup=ui_buttons()
        )

    except Exception as e:
        logger.error(e, exc_info=True)
        await msg.reply_text("❌ Shuffle failed.")


# ================= CLEAN =================
async def clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    try:
        if not msg.reply_to_message:
            return await msg.reply_text(
                "❌ Reply to normal text or a .txt file with /clean"
            )

        raw_text = ""

        if msg.reply_to_message.document:
            doc = msg.reply_to_message.document

            if not is_valid_txt(doc):
                return await msg.reply_text("❌ Only .txt files are supported.")

            file = await context.bot.get_file(doc.file_id)
            path = f"clean_{doc.file_unique_id}.txt"
            await file.download_to_drive(path)

            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw_text = f.read()

            os.remove(path)

        elif msg.reply_to_message.text:
            raw_text = msg.reply_to_message.text

        else:
            return await msg.reply_text("❌ No cleanable text found.")

        cleaned = clean_normal_text(raw_text)

        if not cleaned:
            return await msg.reply_text("❌ No valid text found after cleaning.")

        before_lines = len(raw_text.splitlines())
        after_lines = len(cleaned.splitlines())

        output = "cleaned.txt"

        with open(output, "w", encoding="utf-8") as f:
            f.write(add_watermark(cleaned))

        with open(output, "rb") as f:
            await msg.reply_document(
                f,
                caption=f"🧹 Cleaned Text\nBefore: {before_lines}\nAfter: {after_lines}\n@{BOT_USERNAME}"
            )

        with open(output, "rb") as f:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=f,
                caption=f"🧹 Cleaned File\nBefore: {before_lines}\nAfter: {after_lines}"
            )

        os.remove(output)

        await msg.reply_text(
            "✅ <b>Clean Completed</b>\n\n"
            f"📄 Before lines: <b>{before_lines}</b>\n"
            f"✨ After lines: <b>{after_lines}</b>\n"
            f"🗑 Removed: <b>{before_lines - after_lines}</b>",
            parse_mode="HTML",
            reply_markup=ui_buttons()
        )

    except Exception as e:
        logger.error(e, exc_info=True)
        await msg.reply_text("❌ Clean failed.")


# ================= STOP =================
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid in user_merge_data:
        data = user_merge_data.pop(uid)

        for f in data.get("files", []):
            if os.path.exists(f):
                os.remove(f)

        await update.message.reply_text("🛑 Task cancelled.")
    else:
        await update.message.reply_text("No active task to stop.")


# ================= BROADCAST =================
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        return await update.message.reply_text("❌ You are not allowed.")

    if not context.args:
        return await update.message.reply_text(
            "Usage:\n\n<code>/broadcast your message</code>",
            parse_mode="HTML"
        )

    message = " ".join(context.args)

    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    success = 0
    failed = 0

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=f"📢 <b>Broadcast</b>\n\n{message}",
                parse_mode="HTML"
            )
            success += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        "✅ <b>Broadcast Done</b>\n\n"
        f"Success: <b>{success}</b>\n"
        f"Failed: <b>{failed}</b>",
        parse_mode="HTML"
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

    app.add_handler(CallbackQueryHandler(button_handler))

    # only collects files when user is in merge mode
    app.add_handler(MessageHandler(filters.Document.ALL, collect_files))

    app.add_error_handler(error_handler)

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
