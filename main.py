import logging
import mysql.connector
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==========================================
# ⚙️ CONFIGURAZIONE PARAMETRI
# ==========================================
BOT_TOKEN = "8991790233:AAHu861QfeR5fqpmVNdjOwCjRcYsMVfbT_M"
ADMIN_CHAT_ID = 166967755  # Il tuo ID Telegram personale (numero)
CANALE_TELEGRAM_URL = "https://t.me/bo2italia"  # Link al tuo canale
IL_MIO_TAG_URL = "https://t.me/Myalexy"  # Link al tuo profilo Telegram

# Parametri di Connessione MySQL (XAMPP predefinito)
MYSQL_CONFIG = {
    "host": "mysql://root:rpbuTOnHanNsjljFYFjtHOgKOQCbQfUP@tokaido.proxy.rlwy.net:56537/railway",
    "user": "root",
    "password": "rpbuTOnHanNsjljFYFjtHOgKOQCbQfUP",  # Di default in XAMPP la password è vuota
    "port": 56537,
}
DB_NAME = "prenotazioni_db"


# ==========================================
# 🗄️ GESTIONE DATABASE (MySQL / XAMPP)
# ==========================================

def get_connection():
    """Restituisce una connessione attiva al database MySQL."""
    config = MYSQL_CONFIG.copy()
    config["database"] = DB_NAME
    return mysql.connector.connect(**config)


def init_db():
    """Inizializza il DB creando lo schema e le tabelle se non esistono."""
    # 1. Crea il Database se non esiste
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
    cursor.close()
    conn.close()

    # 2. Crea le Tabelle dentro il Database
    conn = get_connection()
    cursor = conn.cursor()

    # Tabella Offerte
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS offerte (
            codice VARCHAR(50) PRIMARY KEY,
            titolo VARCHAR(100) NOT NULL,
            prezzo DECIMAL(10, 2) NOT NULL,
            posti INT NOT NULL
        )
    """)

    # Tabella Prenotazioni (Nota: BIGINT per ID Telegram)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prenotazioni (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username VARCHAR(100),
            psn_id VARCHAR(100) NOT NULL,
            offerta_codice VARCHAR(50) NOT NULL,
            stato VARCHAR(50) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Inserimento delle offerte iniziali se la tabella è vuota
    cursor.execute("SELECT COUNT(*) FROM offerte")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO offerte (codice, titolo, prezzo, posti) VALUES (%s, %s, %s, %s)",
            [
                ("1h", "1 Ora = 5 EUR", 5.0, 5),
                ("2h", "2 Ore = 9 EUR", 9.0, 5),
            ]
        )
        conn.commit()

    cursor.close()
    conn.close()


def db_get_offerte():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codice, titolo, prezzo, posti FROM offerte")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def db_get_offerta(codice):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT codice, titolo, prezzo, posti FROM offerte WHERE codice = %s", (codice,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def db_crea_prenotazione(user_id, username, psn_id, offerta_codice):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO prenotazioni (user_id, username, psn_id, offerta_codice, stato)
        VALUES (%s, %s, %s, %s, 'IN_ATTESA')
    """, (user_id, username, psn_id, offerta_codice))
    prenotazione_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return prenotazione_id


def db_approva_prenotazione(prenotazione_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, offerta_codice, stato FROM prenotazioni WHERE id = %s", (prenotazione_id,))
    pren = cursor.fetchone()

    if not pren or pren[2] != 'IN_ATTESA':
        cursor.close()
        conn.close()
        return None, None, "Prenotazione non trovata o già gestita."

    user_id, offerta_codice, _ = pren

    cursor.execute("SELECT posti, titolo FROM offerte WHERE codice = %s", (offerta_codice,))
    row = cursor.fetchone()

    if not row or row[0] <= 0:
        cursor.close()
        conn.close()
        return None, None, "Posti esauriti per questa offerta."

    posti_attuali, titolo = row
    nuovi_posti = posti_attuali - 1

    # Decrementa posti e approva
    cursor.execute("UPDATE offerte SET posti = %s WHERE codice = %s", (nuovi_posti, offerta_codice))
    cursor.execute("UPDATE prenotazioni SET stato = 'APPROVATO' WHERE id = %s", (prenotazione_id,))

    conn.commit()
    cursor.close()
    conn.close()

    info_offerta = (offerta_codice, titolo, nuovi_posti)
    return user_id, info_offerta, None


def db_rifiuta_prenotazione(prenotazione_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, stato FROM prenotazioni WHERE id = %s", (prenotazione_id,))
    pren = cursor.fetchone()

    if not pren or pren[1] != 'IN_ATTESA':
        cursor.close()
        conn.close()
        return None

    user_id = pren[0]
    cursor.execute("UPDATE prenotazioni SET stato = 'RIFIUTATO' WHERE id = %s", (prenotazione_id,))

    conn.commit()
    cursor.close()
    conn.close()
    return user_id

def db_ripristina_posto(offerta_codice):
    """Aumenta di 1 i posti disponibili per l'offerta indicata."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE offerte SET posti = posti + 1 WHERE codice = %s", (offerta_codice,))
    conn.commit()
    cursor.close()
    conn.close()


# ==========================================
# 🤖 INTERFACCIA TELEGRAM (NAVIGAZIONE)
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ℹ️ Introduzione al servizio", callback_data="info")],
        [InlineKeyboardButton("🎮 Menu (Prezzi)", callback_data="menu_prezzi")],
        [InlineKeyboardButton("💳 Metodi di pagamento", callback_data="metodi_pago")],
        [InlineKeyboardButton("📢 Canale Telegram", url=CANALE_TELEGRAM_URL)],
        [InlineKeyboardButton("👤 Il mio Tag", url=IL_MIO_TAG_URL)],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "👋 Benvenuto! Seleziona un'opzione dal menu iniziale:"

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "info":
        keyboard = [[InlineKeyboardButton("🔙 Torna indietro", callback_data="main_menu")]]
        await query.edit_message_text(
            "ℹ️ **Introduzione al Servizio**\n\n"
            "Offriamo sessioni e postazioni di gioco per PlayStation.\n"
            "Seleziona l'offerta desiderata, verifica la disponibilità e invia la ricevuta di pagamento per prenotare.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "metodi_pago":
        keyboard = [[InlineKeyboardButton("🔙 Torna indietro", callback_data="main_menu")]]
        await query.edit_message_text(
            "💳 **I Metodi di Pagamento Disponibili:**\n\n"
            "• **Stripe:** negro.com\n"
            "• **PostePay / PayPal:** paypal.me/MyAlexyy\n\n"
            "• **Revolut :** https://revolut.me/alexy02\n\n"
            "⚠️ *Ricordati di salvare la ricevuta o fare uno screenshot dopo aver pagato!*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "menu_prezzi":
        offerte = db_get_offerte()
        keyboard = []

        for codice, titolo, prezzo, _ in offerte:
            keyboard.append([InlineKeyboardButton(f"📌 {titolo}", callback_data=f"select_{codice}")])

        keyboard.append([InlineKeyboardButton("🔙 Torna indietro", callback_data="main_menu")])
        await query.edit_message_text("🎮 **Seleziona la tariffa:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("select_"):
        codice_offerta = data.split("_")[1]
        offerta = db_get_offerta(codice_offerta)

        if not offerta:
            await query.edit_message_text("Offerta non trovata.")
            return

        codice, titolo, prezzo, posti = offerta

        keyboard = [
            [InlineKeyboardButton("💳 Ho pagato", callback_data=f"pay_{codice}")],
            [InlineKeyboardButton("🔙 Torna indietro", callback_data="menu_prezzi")]
        ]

        await query.edit_message_text(
            f"📊 **Disponibilità per {titolo}**\n\n"
            f"• Prezzo: **{float(prezzo):.0f} EUR**\n"
            f"• Posti rimasti: **{posti}**\n\n"
            f"Se hai completato il pagamento, clicca su **'Ho pagato'** per inviare i dettagli.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("pay_"):
        codice_offerta = data.split("_")[1]
        offerta = db_get_offerta(codice_offerta)

        if offerta[3] <= 0:
            keyboard = [[InlineKeyboardButton("🔙 Torna al menu", callback_data="menu_prezzi")]]
            await query.edit_message_text(
                "❌ **Spiacenti, i posti per questa opzione sono esauriti!**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            context.user_data["offerta_scelta"] = codice_offerta
            context.user_data["stato"] = "ATTESA_ID_PSN"
            await query.edit_message_text(
                "🎮 Inserisci il tuo **ID PlayStation** per associare la prenotazione:"
            )

    elif data == "main_menu":
        await start(update, context)


# ==========================================
# 📥 RICEZIONE ID PLAYSTATION & SCREENSHOT
# ==========================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_stato = context.user_data.get("stato")

    if user_stato == "ATTESA_ID_PSN" and update.message.text:
        psn_id = update.message.text
        context.user_data["psn_id"] = psn_id
        context.user_data["stato"] = "ATTESA_SCREENSHOT"

        await update.message.reply_text(
            f"✅ ID PlayStation registrato: `{psn_id}`\n\n"
            "📸 Adesso **invia qui in chat lo screenshot del pagamento** eseguito.",
            parse_mode="Markdown"
        )

    elif user_stato == "ATTESA_SCREENSHOT" and update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        user_id = update.effective_user.id
        username = update.effective_user.username or "Nessun Username"
        psn_id = context.user_data.get("psn_id")
        offerta_codice = context.user_data.get("offerta_scelta")

        prenotazione_id = db_crea_prenotazione(user_id, username, psn_id, offerta_codice)

        keyboard = [
            [
                InlineKeyboardButton("✅ Approva", callback_data=f"approve_{prenotazione_id}"),
                InlineKeyboardButton("❌ Rifiuta", callback_data=f"reject_{prenotazione_id}")
            ]
        ]

        caption_admin = (
            f"🚨 **NUOVA PRENOTAZIONE RICEVUTA #{prenotazione_id}**\n\n"
            f"👤 **ID Utente:** `{user_id}` (@{username})\n"
            f"🎮 **ID PlayStation:** `{psn_id}`\n"
            f"⏱ **Offerta:** {offerta_codice}\n"
        )

        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id,
            caption=caption_admin,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        await update.message.reply_text(
            "⏳ **Ricevuta ricevuta con successo!**\n\n"
            "Un amministratore verificherà il pagamento e riceverai la conferma di prenotazione direttamente qui in chat."
        )

        context.user_data["stato"] = None


# ==========================================
# 👑 AZIONI AMMINISTRATORE (APPROVA/RIFIUTA)
# ==========================================

async def admin_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    azione = data[0]
    prenotazione_id = int(data[1])

    if azione == "approve":
            target_user_id, info_offerta, errore = db_approva_prenotazione(prenotazione_id)

            if errore:
                await query.message.reply_text(f"⚠️ Errore: {errore}")
                return

            codice_offerta = info_offerta[0]

            # Imposta la durata del timer in base all'offerta acquistata
            secondi_durata = 3600  # Default 1 ora (3600 secondi)
            if codice_offerta == "2h":
                secondi_durata = 7200  # 2 ore (7200 secondi)

            # Programma il timer automatico in background
            context.job_queue.run_once(
                timer_scadenza_job,
                when=secondi_durata,
                data={"user_id": target_user_id, "offerta_codice": codice_offerta},
                name=f"timer_{prenotazione_id}"
            )

            # Notifica all'utente
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 <b>Pagamento confermato!</b> La tua prenotazione è attiva. Il tuo tempo scadrà tra {secondi_durata // 3600} ora/e.",
                parse_mode="HTML"
            )

            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n✅ <b>ESITO: APPROVATO (Timer impostato a {secondi_durata // 3600}h)</b>",
                parse_mode="HTML"
            )
    elif azione == "reject":
        target_user_id = db_rifiuta_prenotazione(prenotazione_id)

        if target_user_id:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="❌ **Spiacenti, il pagamento non è risultato valido.** Per assistenza contarta il supporto."
            )
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n❌ **ESITO: RIFIUTATO**",
                parse_mode="Markdown"
            )



async def timer_scadenza_job(context: ContextTypes.DEFAULT_TYPE):
    """Questa funzione viene eseguita automaticamente quando scade il timer."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    offerta_codice = job_data["offerta_codice"]

    # 1. Aumenta di +1 il posto nel Database
    db_ripristina_posto(offerta_codice)

    # 2. Avvisa l'utente che il tempo è finito
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="⏰ **TEMPO SCADUTO!**\n\nLa tua sessione di gioco è terminata. Se desideri continuare, effettua un'altra prenotazione dal menu!",
            parse_mode="HTML"
        )
    except Exception:
        pass  # L'utente potrebbe aver bloccato il bot nel frattempo

    # 3. Avvisa l'Admin che il posto si è liberato
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🔄 <b>SLOT RIPRISTINATO:</b> Il tempo per l'utente <code>{user_id}</code> (Offerta: {offerta_codice}) è scaduto. Il posto è di nuovo disponibile!",
        parse_mode="HTML"
    )
    
# ==========================================
# 🚀 AVVIO BOT
# ==========================================

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin_approval_handler, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_messages))

    print("Bot avviato e connesso al Database MySQL di XAMPP!")
    app.run_polling()


if __name__ == "__main__":
    main()
