import logging
import gspread
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from google.oauth2.service_account import Credentials

# ── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8766677797:AAEVB_pe6Mwvn30dGBeilZaVmCQgrOphWDo"
SERVICE_ACCOUNT_FILE = "lux-housing-16e13a90a968.json"
SPREADSHEET_ID = "1mEhFrYu8spwJJGJcUUoQsF8XGQOc7PcHTZErhQhkEio"
SHEET_GID = 928985318
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
ALLOWED_USERNAME = "adevonaev"

cache: dict[str, dict] = {}


def load_sheet() -> None:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    # find worksheet by gid
    worksheet = next(
        ws for ws in spreadsheet.worksheets() if ws.id == SHEET_GID
    )

    rows = worksheet.get_all_records()  # list of dicts, first row = headers
    cache.clear()
    for row in rows:
        row_id = str(row.get("id_post", "")).strip()
        if row_id:
            cache[row_id] = row

    log.info("Sheet loaded: %d records cached", len(cache))


FIELD_LABELS = {
    "id_post": "🏠 ID",
    "phone_number (whatsapp)": "📞 Contact",
    "name": "👤 Name",
    "channel_link": "🔗 Post",
    "type": "🏷️ Type",
    "location": "📍 Location",
    "price": "💰 Price",
    "created_at": "📅 Date",
}

GET_FIELDS = ["id_post", "phone_number (whatsapp)", "name", "price", "channel_link"]

def format_row(row: dict, fields: list[str] | None = None) -> str:
    lines = []
    items = [(k, row[k]) for k in fields if k in row] if fields else row.items()
    for key, value in items:
        if str(value).strip():
            label = FIELD_LABELS.get(key, key)
            if key == "channel_link":
                lines.append(f"<b>{label}:</b> <a href=\"{value}\">View Post</a>")
            else:
                lines.append(f"<b>{label}:</b> {value}")
    return "\n".join(lines)


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.username == ALLOWED_USERNAME


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not is_allowed(update):
        return
    await update.message.reply_text("Send /get <id> to look up a listing.")


async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /get <id> [id2 id3 ...]")
        return

    ids = " ".join(context.args).replace(",", " ").split()
    for lookup_id in ids:
        lookup_id = lookup_id.strip()
        row = cache.get(lookup_id)
        if row is None:
            await update.message.reply_text(f"ID <code>{lookup_id}</code> not found.", parse_mode="HTML")
        else:
            await update.message.reply_text(format_row(row, GET_FIELDS), parse_mode="HTML")


LISTING_TYPES = {"room", "studio", "apartment"}

def search_cache(tokens: list[str]) -> list[dict]:
    max_price = None
    listing_type = None
    location_parts = []

    for token in tokens:
        lower = token.lower().strip(",")
        if lower.isdigit():
            max_price = int(lower)
        elif lower in LISTING_TYPES:
            listing_type = lower
        else:
            location_parts.append(lower)

    location = " ".join(location_parts)

    results = []
    for row in cache.values():
        if listing_type and str(row.get("type", "")).lower() != listing_type:
            continue
        if location and location not in str(row.get("location", "")).lower():
            continue
        if max_price is not None:
            try:
                if float(str(row.get("price", "")).replace("€", "").replace(",", "").strip()) > max_price:
                    continue
            except ValueError:
                continue
        results.append(row)

    try:
        from datetime import datetime
        results.sort(key=lambda r: datetime.strptime(str(r.get("created_at", "")), "%Y-%m-%d"), reverse=True)
    except Exception:
        pass

    return results[:10]


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage examples:\n"
            "/search room Kirchberg 1200\n"
            "/search studio Gare\n"
            "/search Bonnevoie 1500\n"
            "/search room",
            parse_mode="HTML"
        )
        return

    results = search_cache(context.args)
    if not results:
        await update.message.reply_text("No matching listings found.")
        return

    for row in results:
        await update.message.reply_text(format_row(row), parse_mode="HTML")


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    try:
        load_sheet()
        await update.message.reply_text(f"Cache refreshed: {len(cache)} records.")
    except Exception as e:
        log.exception("Reload failed")
        await update.message.reply_text(f"Reload failed: {e}")


def main() -> None:
    load_sheet()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("get", cmd_get))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("reload", cmd_reload))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
