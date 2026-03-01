# Quizzor Bot

A Telegram bot for running multiple-choice tests for students, with admin controls for uploading tests, starting/stopping them, and exporting results.

This repo is **privacy-sanitized**:
- no phone-number guest registration
- no “confidential users export” command
- stores only the minimum user data needed to run tests (student id, name, group)

## Features

### Students
- `/start` registration using a **Student ID** from `students.csv`
- **Active tests** (timed, one attempt, points counted)
- **Practice mode** (unlimited attempts, answers shown, no points)
- **Stats** (rank + per-test scores)

### Admins
- upload tests as a questions CSV
- start/stop/archive/remove tests
- overall rankings CSV
- per-test results CSV

## Quick start

### 1) Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure environment
Copy `.env.example` to `.env` and fill it:
```bash
cp .env.example .env
```

Set:
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_IDS` (comma-separated Telegram user IDs)
- (optional) `DB_NAME`

Load `.env` (bash):
```bash
set -a
source .env
set +a
```

### 3) Add students list
Create `students.csv` (or copy the sample):
```bash
cp students.sample.csv students.csv
```

Expected columns (minimum):
- column 0: `hemis_id` (Student ID)
- column 1: `full_name`
- column 3: `group_name`

### 4) Run
```bash
python bot.py
```

## CSV formats

### `students.csv`
Example (`students.sample.csv`):
```csv
hemis_id,full_name,unused,group_name
12345,Ali Valiyev,,SE-101
67890,Aziza Karimova,,SE-102
```

### Questions CSV (upload to bot)
The bot expects a CSV with **6 columns**:
1. question_text
2. option_a
3. option_b
4. option_c
5. option_d
6. correct_answer (A/B/C/D)

Example (`questions.sample.csv`):
```csv
question,opt_a,opt_b,opt_c,opt_d,correct
2+2=?,3,4,5,22,B
capital of uzbekistan?,samarkand,tashkent,bukhara,khiva,B
```

## Commands and menus

- Students: `/start` then use buttons: **Active**, **Practice**, **Stats**
- Admins: `/start` then buttons: **Add New**, **Manage**, **Reports**



## Deployment tips

- Use a separate Linux user + systemd service
- Back up `school_bot.db`
- Keep your `.env` out of git (already in `.gitignore`)

## License
MIT (see `LICENSE`).
