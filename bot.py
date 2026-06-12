import json
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Final

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN: Final = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_CREDENTIALS_JSON: Final = os.getenv("GOOGLE_CREDENTIALS_JSON")
_creds_env = os.getenv("GOOGLE_CREDENTIALS_PATH", "./credentials.json")
_creds_path = Path(_creds_env)
if not _creds_path.is_absolute():
    _creds_path = BASE_DIR / _creds_path
GOOGLE_CREDENTIALS_PATH: Final = str(_creds_path)
SPREADSHEET_ID: Final = os.getenv("SPREADSHEET_ID")
SHEET_NAME: Final = os.getenv("SHEET_NAME", "Sheet1")

SCOPES: Final = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

(
    ORG,
    AMOUNT,
    DONE,
    PAYMENT,
    EXTRA_DELIVERY,
    EXTRA_PAYMENT,
    DATE,
    CONFIRM,
) = range(8)

YES_NO_KEYBOARD = ReplyKeyboardMarkup(
    [["Да", "Нет"]], one_time_keyboard=True, resize_keyboard=True
)


def _load_credentials() -> Credentials:
    if GOOGLE_CREDENTIALS_JSON:
        info = json.loads(GOOGLE_CREDENTIALS_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)


def get_worksheet():
    creds = _load_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я бот для ввода данных по договорам в Google Таблицу.\n\n"
        "Команды:\n"
        "/new_contract — добавить новый договор\n"
        "/list — показать последние 5 договоров\n"
        "/help — справка"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 Справка:\n\n"
        "/start — приветствие\n"
        "/new_contract — добавить новый договор (пошаговый ввод)\n"
        "/list — последние 5 договоров из таблицы\n"
        "/cancel — отменить ввод договора\n"
        "/help — эта справка\n\n"
        "Колонки таблицы:\n"
        "Организация | Сумма договора | Выполнено | Оплата | "
        "Доп. по поставке | Доп. по оплате | Дата"
    )


async def new_contract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📝 Новый договор.\n\nНазвание организации?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ORG


async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["org"] = update.message.text.strip()
    await update.message.reply_text("Сумма договора?")
    return AMOUNT


async def ask_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["amount"] = update.message.text.strip()
    await update.message.reply_text("Выполнено?", reply_markup=YES_NO_KEYBOARD)
    return DONE


async def ask_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["done"] = update.message.text.strip()
    await update.message.reply_text(
        "Сумма оплаты?", reply_markup=ReplyKeyboardRemove()
    )
    return PAYMENT


async def ask_extra_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["payment"] = update.message.text.strip()
    await update.message.reply_text(
        "Доп. соглашение по поставке? (если нет — напишите «нет»)"
    )
    return EXTRA_DELIVERY


async def ask_extra_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["extra_delivery"] = update.message.text.strip()
    await update.message.reply_text(
        "Доп. соглашение по оплате? (если нет — напишите «нет»)"
    )
    return EXTRA_PAYMENT


async def ask_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["extra_payment"] = update.message.text.strip()
    today = datetime.now().strftime("%d.%m.%Y")
    await update.message.reply_text(
        f"Дата договора? (например, {today} — или напишите «сегодня»)"
    )
    return DATE


async def ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_date = update.message.text.strip()
    if raw_date.lower() in ("сегодня", "today"):
        raw_date = datetime.now().strftime("%d.%m.%Y")
    context.user_data["date"] = raw_date

    d = context.user_data
    summary = (
        "✅ Проверьте данные:\n\n"
        f"🏢 Организация: {d['org']}\n"
        f"💰 Сумма договора: {d['amount']}\n"
        f"📦 Выполнено: {d['done']}\n"
        f"💳 Оплата: {d['payment']}\n"
        f"📝 Доп. по поставке: {d['extra_delivery']}\n"
        f"📝 Доп. по оплате: {d['extra_payment']}\n"
        f"📅 Дата: {d['date']}\n\n"
        "Сохранить?"
    )
    await update.message.reply_text(summary, reply_markup=YES_NO_KEYBOARD)
    return CONFIRM


async def save_contract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = update.message.text.strip().lower()
    if answer not in ("да", "yes", "y"):
        await update.message.reply_text(
            "❌ Отменено. Данные не сохранены.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    d = context.user_data
    row = [
        d["org"],
        d["amount"],
        d["done"],
        d["payment"],
        d["extra_delivery"],
        d["extra_payment"],
        d["date"],
    ]

    try:
        worksheet = get_worksheet()
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        row_number = len(worksheet.get_all_values())
        await update.message.reply_text(
            f"✅ Сохранено в таблицу!\nНомер строки: {row_number}",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as exc:
        logger.exception("Failed to write to Google Sheets")
        detail = ""
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                detail = f"\nHTTP {response.status_code}: {response.text[:400]}"
            except Exception:
                detail = ""
        await update.message.reply_text(
            "⚠️ Ошибка при сохранении.\n"
            f"SPREADSHEET_ID={SPREADSHEET_ID}\n"
            f"SHEET_NAME={SHEET_NAME}\n"
            f"{type(exc).__name__}: {exc}{detail}",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Ввод отменён.", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def list_contracts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        worksheet = get_worksheet()
        rows = worksheet.get_all_values()
    except Exception as exc:
        logger.exception("Failed to read Google Sheets")
        await update.message.reply_text(f"⚠️ Ошибка чтения таблицы: {exc}")
        return

    if len(rows) <= 1:
        await update.message.reply_text("📭 В таблице пока нет договоров.")
        return

    data_rows = rows[1:] if len(rows) > 1 else []
    last_five = data_rows[-5:]

    lines = ["📋 Последние договоры:\n"]
    start_idx = len(rows) - len(last_five) + 1
    for i, row in enumerate(last_five, start=start_idx):
        padded = (row + [""] * 7)[:7]
        org, amount, done, payment, extra_d, extra_p, date = padded
        lines.append(
            f"#{i}  📅 {date or '—'}\n"
            f"🏢 {org or '—'}\n"
            f"💰 {amount or '—'} | 💳 {payment or '—'} | 📦 {done or '—'}\n"
        )
    await update.message.reply_text("\n".join(lines))


def build_application() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID is not set")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("new_contract", new_contract)],
        states={
            ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_done)],
            DONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payment)],
            PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_extra_delivery)],
            EXTRA_DELIVERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_extra_payment)
            ],
            EXTRA_PAYMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_date)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_confirm)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_contract)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_contracts))
    app.add_handler(conv)

    return app


def main() -> None:
    app = build_application()
    logger.info("Bot is starting...")
    logger.info("SPREADSHEET_ID = %s", SPREADSHEET_ID)
    logger.info("SHEET_NAME     = %s", SHEET_NAME)
    logger.info("CREDENTIALS    = %s", GOOGLE_CREDENTIALS_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
