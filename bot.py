import os
import re
import html
import sqlite3
import csv
import io
import threading
import random
from datetime import datetime

import telebot
from telebot import types

# --- CONFIGURATION ---
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
DB_NAME = os.getenv("DB_NAME", "school_bot.db")

if not API_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var. Put it in your environment (or .env) before running.")
if not ADMIN_IDS:
    raise RuntimeError("Missing ADMIN_IDS env var (comma-separated Telegram user IDs).")

bot = telebot.TeleBot(API_TOKEN)

# Global dictionaries for sessions and states
testing_sessions = {}
registration_cache = {}

def get_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Minimal user profile: only what the bot needs to function
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 hemis_id TEXT UNIQUE,
                 full_name TEXT,
                 group_name TEXT,
                 joined_at TEXT,
                 last_active TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS tests (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 test_name TEXT UNIQUE,
                 status TEXT DEFAULT 'new',
                 date_added TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS questions (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 test_id INTEGER,
                 question_text TEXT,
                 opt_a TEXT, opt_b TEXT, opt_c TEXT, opt_d TEXT,
                 correct_answer TEXT,
                 FOREIGN KEY(test_id) REFERENCES tests(id) ON DELETE CASCADE)""")

    c.execute("""CREATE TABLE IF NOT EXISTS results (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER,
                 test_id INTEGER,
                 score INTEGER,
                 max_score INTEGER,
                 timestamp TEXT,
                 FOREIGN KEY(user_id) REFERENCES users(user_id),
                 FOREIGN KEY(test_id) REFERENCES tests(id))""")

    conn.commit()
    conn.close()

def upgrade_db_best_effort():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE tests ADD COLUMN status TEXT DEFAULT 'new'")
    except:
        pass
    conn.commit()
    conn.close()

init_db()
upgrade_db_best_effort()

def update_last_active(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (get_now(), user_id))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def check_student_csv(hemis_id: str):
    """Lookup Student ID in students.csv.
    Expected columns (minimum):
      0: hemis_id
      1: full_name
      3: group_name
    """
    if not os.path.exists("students.csv"):
        return None
    with open("students.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 4 and row[0].strip() == hemis_id.strip():
                return {"name": row[1].strip(), "group": row[3].strip()}
    return None

def main_menu_keyboard(user_id: int):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if user_id in ADMIN_IDS:
        markup.add("➕ Add New", "📂 Manage", "📉 Reports")
    else:
        markup.add("🟢 Active", "🧠 Practice", "📊 Stats")
    return markup

def admin_manage_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🆕 Active", "🗄 Archived", "🔙")
    return markup

def admin_reports_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🏆 Overall Rankings", "📝 Test Reports", "🔙")
    return markup

@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id

    if user_id in ADMIN_IDS:
        bot.send_message(user_id, "Welcome Admin! Access granted.", reply_markup=main_menu_keyboard(user_id))
        return

    user = get_user(user_id)

    if user:
        update_last_active(user_id)
        name_parts = (user[2] or "").split()
        first_name = name_parts[1] if len(name_parts) > 1 else (name_parts[0] if name_parts else "there")
        bot.send_message(user_id, f"Welcome back, {html.escape(first_name)}!", reply_markup=main_menu_keyboard(user_id))
    else:
        registration_cache[user_id] = {"step": "hemis"}
        bot.send_message(user_id, "Welcome! To use this bot, please enter your <b>Student ID</b>:", parse_mode="HTML")

@bot.message_handler(content_types=["text"], func=lambda m: m.from_user.id in registration_cache)
def handle_registration(message):
    user_id = message.from_user.id
    hemis_id = (message.text or "").strip()

    if not hemis_id:
        bot.send_message(user_id, "❌ Please type your Student ID as text.")
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE hemis_id = ?", (hemis_id,))
    existing_user = c.fetchone()
    conn.close()

    if existing_user:
        bot.send_message(user_id, "❌ This Student ID is already registered to another user.")
        return

    student_data = check_student_csv(hemis_id)
    if not student_data:
        bot.send_message(user_id, "❌ Invalid Student ID. Try again:")
        return

    full_name = student_data["name"]
    group_name = student_data["group"]
    now_str = get_now()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT INTO users (user_id, hemis_id, full_name, group_name, joined_at, last_active) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, hemis_id, full_name, group_name, now_str, now_str),
    )
    conn.commit()
    conn.close()

    del registration_cache[user_id]
    name_parts = full_name.split()
    first_name = name_parts[1] if len(name_parts) > 1 else name_parts[0]
    bot.send_message(user_id, f"✅ Registration complete! Welcome, {html.escape(first_name)}.", reply_markup=main_menu_keyboard(user_id))

@bot.message_handler(func=lambda m: m.text == "➕ Add New" and m.from_user.id in ADMIN_IDS)
def ask_upload_csv(message):
    bot.send_message(
        message.chat.id,
        "Please upload the <b>CSV file</b> with questions.\nThe file name will be used as the Test Name.",
        parse_mode="HTML",
    )

@bot.message_handler(content_types=["document"], func=lambda m: m.from_user.id in ADMIN_IDS)
def handle_csv_upload(message):
    try:
        file_name = message.document.file_name
        if not file_name.lower().endswith(".csv"):
            bot.send_message(message.chat.id, "❌ Please upload a .csv file.")
            return

        test_name = file_name.rsplit(".", 1)[0]

        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        csv_content = downloaded_file.decode("utf-8", errors="replace").splitlines()
        csv_reader = csv.reader(csv_content)

        next(csv_reader, None)  # skip header (if any)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO tests (test_name, status, date_added) VALUES (?, 'new', ?)", (test_name, get_now()))
        test_id = c.lastrowid

        count = 0
        for row in csv_reader:
            if len(row) >= 6:
                c.execute(
                    "INSERT INTO questions (test_id, question_text, opt_a, opt_b, opt_c, opt_d, correct_answer) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (test_id, row[0], row[1], row[2], row[3], row[4], row[5].strip().upper()),
                )
                count += 1

        conn.commit()
        conn.close()

        bot.send_message(
            message.chat.id,
            f"✅ Test '{html.escape(test_name)}' uploaded successfully with {count} questions. It is now in 'New Tests'.",
            reply_markup=main_menu_keyboard(message.from_user.id),
            parse_mode="HTML",
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error processing file: {e}")

@bot.message_handler(func=lambda m: m.text == "📂 Manage" and m.from_user.id in ADMIN_IDS)
def admin_manage_tests(message):
    bot.send_message(message.chat.id, "Select Category:", reply_markup=admin_manage_keyboard())

@bot.message_handler(func=lambda m: m.text in ["🆕 Active", "🗄 Archived"] and m.from_user.id in ADMIN_IDS)
def list_manage_tests(message):
    mode = "new_active" if "Active" in message.text else "archived"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if mode == "new_active":
        c.execute("SELECT id, test_name, status FROM tests WHERE status IN ('new', 'active')")
    else:
        c.execute("SELECT id, test_name, status FROM tests WHERE status = 'archived'")
    tests = c.fetchall()
    conn.close()

    if not tests:
        bot.send_message(message.chat.id, "No tests found in this category.")
        return

    markup = types.InlineKeyboardMarkup()
    for t_id, t_name, status in tests:
        icon = "▶️" if status == "active" else "🆕" if status == "new" else "🗄"
        markup.add(types.InlineKeyboardButton(f"{icon} {t_name}", callback_data=f"admtest_{t_id}"))

    bot.send_message(message.chat.id, "Select a test to manage:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("admtest_") and call.from_user.id in ADMIN_IDS)
def admin_test_options(call):
    test_id = call.data.split("_")[1]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT test_name, status FROM tests WHERE id = ?", (test_id,))
    test = c.fetchone()
    conn.close()

    if not test:
        try:
            bot.answer_callback_query(call.id, "Test not found.")
        except:
            pass
        return

    t_name, status = test
    markup = types.InlineKeyboardMarkup(row_width=2)

    if status == "new":
        markup.add(types.InlineKeyboardButton("▶️ Start", callback_data=f"tstact_{test_id}"))
    elif status == "active":
        markup.add(types.InlineKeyboardButton("⏸ Stop", callback_data=f"tstnew_{test_id}"))

    if status in ["new", "active"]:
        markup.add(types.InlineKeyboardButton("🗄 Move to Archive", callback_data=f"tstarc_{test_id}"))

    if status == "archived":
        markup.add(types.InlineKeyboardButton("📊 Get Results", callback_data=f"tstrep_{test_id}"))

    markup.add(types.InlineKeyboardButton("🗑 Remove", callback_data=f"tstdel_{test_id}"))

    bot.edit_message_text(
        f"Options for: <b>{html.escape(t_name)}</b>\nCurrent Status: {status.upper()}",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML",
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("tst") and call.from_user.id in ADMIN_IDS)
def handle_test_state_change(call):
    action = call.data[:6]
    test_id = call.data.split("_")[1]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if action == "tstact":
        c.execute("UPDATE tests SET status = 'active' WHERE id = ?", (test_id,))
        msg = "Test is now ACTIVE (visible to students)."
    elif action == "tstnew":
        c.execute("UPDATE tests SET status = 'new' WHERE id = ?", (test_id,))
        msg = "Test is stopped and set to NEW."
    elif action == "tstarc":
        c.execute("UPDATE tests SET status = 'archived' WHERE id = ?", (test_id,))
        msg = "Test is now ARCHIVED (practice mode only)."
    elif action == "tstdel":
        c.execute("DELETE FROM questions WHERE test_id = ?", (test_id,))
        c.execute("DELETE FROM results WHERE test_id = ?", (test_id,))
        c.execute("DELETE FROM tests WHERE id = ?", (test_id,))
        msg = "Test and all related results removed."
    elif action == "tstrep":
        c.execute(
            """SELECT u.group_name, u.full_name, r.score
               FROM results r
               JOIN users u ON r.user_id = u.user_id
               WHERE r.test_id = ?
               ORDER BY r.score DESC""",
            (test_id,),
        )
        rows = c.fetchall()
        c.execute("SELECT test_name FROM tests WHERE id=?", (test_id,))
        t_name = c.fetchone()[0]
        conn.close()

        s_io = io.StringIO()
        writer = csv.writer(s_io)
        writer.writerow(["Group", "Name", "Correct Answers"])
        for row in rows:
            writer.writerow(row)
        s_io.seek(0)

        safe_t_name = re.sub(r"[^A-Za-z0-9_.-]", "_", t_name)
        bot.send_document(call.message.chat.id, io.BytesIO(s_io.getvalue().encode()), visible_file_name=f"{safe_t_name}_results.csv")
        return

    conn.commit()
    conn.close()
    bot.edit_message_text(msg, chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.message_handler(func=lambda m: m.text == "📉 Reports" and m.from_user.id in ADMIN_IDS)
def admin_reports_menu(message):
    bot.send_message(message.chat.id, "Select Report Type:", reply_markup=admin_reports_keyboard())

@bot.message_handler(func=lambda m: m.text == "🏆 Overall Rankings" and m.from_user.id in ADMIN_IDS)
def overall_rankings(message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        """SELECT u.full_name, u.group_name, COALESCE(SUM(r.score), 0) as total_score
           FROM users u
           LEFT JOIN results r ON u.user_id = r.user_id
           GROUP BY u.user_id
           ORDER BY total_score DESC"""
    )
    rows = c.fetchall()
    conn.close()

    s_io = io.StringIO()
    writer = csv.writer(s_io)
    writer.writerow(["Name", "Group", "Rank", "All Points"])
    for rank, row in enumerate(rows, 1):
        writer.writerow([row[0], row[1], rank, row[2] or 0])
    s_io.seek(0)
    bot.send_document(message.chat.id, io.BytesIO(s_io.getvalue().encode()), visible_file_name="overall_rankings.csv")

@bot.message_handler(func=lambda m: m.text == "📝 Test Reports" and m.from_user.id in ADMIN_IDS)
def list_test_reports(message):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, test_name FROM tests WHERE status IN ('active', 'archived')")
    tests = c.fetchall()
    conn.close()

    if not tests:
        bot.send_message(message.chat.id, "No active or archived tests available.")
        return

    markup = types.InlineKeyboardMarkup()
    for t_id, t_name in tests:
        markup.add(types.InlineKeyboardButton(f"📄 {t_name}", callback_data=f"tstrep_{t_id}"))
    bot.send_message(message.chat.id, "Select a test to get its results:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text and m.text.strip() == "🔙")
def go_back(message):
    bot.send_message(message.chat.id, "Main Menu", reply_markup=main_menu_keyboard(message.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📊 Stats")
def my_stats(message):
    user_id = message.from_user.id
    update_last_active(user_id)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, SUM(score) as total FROM results GROUP BY user_id ORDER BY total DESC")
    rankings = c.fetchall()

    my_rank, total_score = "N/A", 0
    for idx, row in enumerate(rankings, 1):
        if row[0] == user_id:
            my_rank, total_score = idx, row[1] or 0
            break

    c.execute(
        """SELECT t.test_name, r.score, r.max_score
           FROM results r
           JOIN tests t ON r.test_id = t.id
           WHERE r.user_id = ?""",
        (user_id,),
    )
    results = c.fetchall()
    conn.close()

    details = "".join([f"\n📚 {html.escape(r[0].replace('_', ' '))}: {r[1]}/{r[2]}" for r in results])
    text = f"👤 <b>Your Stats</b>\n\n🏅 Rank: {my_rank}\n✅ Total Points: {total_score}\n------------------{details}"
    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🟢 Active")
def list_active_tests(message):
    user_id = message.from_user.id
    update_last_active(user_id)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, test_name FROM tests WHERE status = 'active'")
    active_tests = c.fetchall()
    c.execute("SELECT test_id FROM results WHERE user_id = ?", (user_id,))
    solved_ids = [row[0] for row in c.fetchall()]
    conn.close()

    if not active_tests:
        bot.send_message(message.chat.id, "There are no active tests right now.")
        return

    markup = types.InlineKeyboardMarkup()
    for t_id, t_name in active_tests:
        status_icon = "✅" if t_id in solved_ids else "🆕"
        markup.add(types.InlineKeyboardButton(f"{status_icon} {t_name}", callback_data=f"act_{t_id}"))

    bot.send_message(message.chat.id, "🟢 <b>Active Tests</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text == "🧠 Practice")
def list_practice_tests(message):
    user_id = message.from_user.id
    update_last_active(user_id)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, test_name FROM tests WHERE status = 'archived'")
    practice_tests = c.fetchall()
    conn.close()

    if not practice_tests:
        bot.send_message(message.chat.id, "No tests available for practice yet.")
        return

    markup = types.InlineKeyboardMarkup()
    for t_id, t_name in practice_tests:
        markup.add(types.InlineKeyboardButton(f"🧠 {t_name}", callback_data=f"prac_{t_id}"))

    bot.send_message(
        message.chat.id,
        "🧠 <b>Practice Mode</b>\n(Unlimited attempts, answers shown, no points)",
        reply_markup=markup,
        parse_mode="HTML",
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("act_") or call.data.startswith("prac_"))
def init_test_session(call):
    mode = "active" if call.data.startswith("act_") else "practice"
    test_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if mode == "active":
        c.execute("SELECT 1 FROM results WHERE user_id=? AND test_id=?", (user_id, test_id))
        if c.fetchone():
            try:
                bot.answer_callback_query(
                    call.id,
                    "You have already solved this test! It will appear in Practice mode once the admin archives it.",
                    show_alert=True,
                )
            except:
                pass
            conn.close()
            return

    c.execute("SELECT * FROM questions WHERE test_id = ?", (test_id,))
    questions = c.fetchall()

    if not questions:
        try:
            bot.answer_callback_query(call.id, "This test has no questions!")
        except:
            pass
        conn.close()
        return

    random.shuffle(questions)

    if mode == "active":
        c.execute(
            "INSERT INTO results (user_id, test_id, score, max_score, timestamp) VALUES (?, ?, 0, ?, ?)",
            (user_id, test_id, len(questions), get_now()),
        )
        conn.commit()

    conn.close()

    testing_sessions[user_id] = {
        "mode": mode,
        "test_id": test_id,
        "questions": questions,
        "current_index": 0,
        "score": 0,
        "timer": None,
        "processing": False,
    }

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

    send_next_question(user_id, call.message.chat.id)

def send_next_question(user_id, chat_id, message_id=None):
    session = testing_sessions.get(user_id)
    if not session:
        return

    idx = session["current_index"]
    if idx >= len(session["questions"]):
        finish_test(user_id, chat_id, message_id)
        return

    q = session["questions"][idx]
    is_active = session["mode"] == "active"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("A", callback_data="ans_A"),
        types.InlineKeyboardButton("B", callback_data="ans_B"),
        types.InlineKeyboardButton("C", callback_data="ans_C"),
        types.InlineKeyboardButton("D", callback_data="ans_D"),
    )

    header = f"Question {idx+1}/{len(session['questions'])}\n"
    header += "⏱ 15 seconds\n" if is_active else "🧠 Practice Mode\n"

    msg_text = f"{header}\n{q[2]}\n\nA) {q[3]}\nB) {q[4]}\nC) {q[5]}\nD) {q[6]}"

    try:
        if message_id and not is_active:
            bot.edit_message_text(msg_text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
        else:
            msg = bot.send_message(chat_id, msg_text, reply_markup=markup)
            message_id = msg.message_id

        if is_active:
            timer = threading.Timer(15.0, on_timeout, [user_id, chat_id, message_id, idx])
            session["timer"] = timer
            timer.start()
    except Exception as e:
        print(f"Error sending question: {e}")
        finish_test(user_id, chat_id)

def on_timeout(user_id, chat_id, message_id, q_index):
    session = testing_sessions.get(user_id)
    if not session or session["current_index"] != q_index:
        return

    if session.get("processing"):
        return

    session["processing"] = True
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

    bot.send_message(chat_id, "⏳ Time's up!")
    session["current_index"] += 1
    session["processing"] = False
    send_next_question(user_id, chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ans_"))
def handle_answer(call):
    user_id = call.from_user.id
    session = testing_sessions.get(user_id)

    if not session:
        try:
            bot.answer_callback_query(call.id, "Session expired.")
        except:
            pass
        return

    if session.get("processing"):
        return
    session["processing"] = True

    try:
        if session["timer"]:
            session["timer"].cancel()

        selected_option = call.data.split("_")[1]
        current_q = session["questions"][session["current_index"]]
        correct_ans = current_q[7]

        is_correct = selected_option == correct_ans
        if is_correct:
            session["score"] += 1

        if session["mode"] == "active":
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute(
                "UPDATE results SET score = ? WHERE user_id = ? AND test_id = ?",
                (session["score"], user_id, session["test_id"]),
            )
            conn.commit()
            conn.close()

            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass

            session["current_index"] += 1
            session["processing"] = False
            send_next_question(user_id, call.message.chat.id)
        else:
            feedback = (
                f"✅ Correct! The answer was {correct_ans}."
                if is_correct
                else f"❌ Incorrect. You chose {selected_option},\nCorrect answer is {correct_ans}."
            )
            new_text = f"{call.message.text}\n\n{feedback}"

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Next ➡️", callback_data="pracnext"))
            try:
                bot.edit_message_text(
                    new_text,
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=markup,
                )
            except:
                pass

            session["processing"] = False

    except Exception as e:
        session["processing"] = False
        print(f"Error handling answer: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "pracnext")
def next_practice_q(call):
    user_id = call.from_user.id
    session = testing_sessions.get(user_id)
    if not session:
        return
    if session.get("processing"):
        return

    session["processing"] = True
    session["current_index"] += 1
    session["processing"] = False
    send_next_question(user_id, call.message.chat.id, call.message.message_id)

def finish_test(user_id, chat_id, message_id=None):
    session = testing_sessions.pop(user_id, None)
    if not session:
        return

    score = session["score"]
    total = len(session["questions"])
    mode = session["mode"]

    if mode == "active":
        msg = f"🎉 <b>Test Finished!</b>\n\nYou got {score} out of {total} correct."
        bot.send_message(chat_id, msg, parse_mode="HTML")
    else:
        msg = f"🧠 <b>Practice Finished!</b>\n\nYou got {score} out of {total} correct."
        try:
            bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, parse_mode="HTML")
        except:
            bot.send_message(chat_id, msg, parse_mode="HTML")

print("Bot is running...")
bot.infinity_polling(skip_pending=True)
