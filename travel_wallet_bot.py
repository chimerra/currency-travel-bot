import os
import sqlite3
from contextlib import closing
from typing import Dict, Any, Optional

import telebot
from telebot import types
from dotenv import load_dotenv

from current_api import get_rate


load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не найден в .env")


DB_PATH = os.path.join(os.path.dirname(__file__), "travel_wallet.db")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    print("Initializing database...")  # Добавлено для отладки
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                active_trip_id INTEGER,
                FOREIGN KEY(active_trip_id) REFERENCES trips(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                home_country TEXT NOT NULL,
                home_currency TEXT NOT NULL,
                dest_country TEXT NOT NULL,
                dest_currency TEXT NOT NULL,
                rate REAL NOT NULL,
                home_balance REAL NOT NULL,
                dest_balance REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id INTEGER NOT NULL,
                amount_dest REAL NOT NULL,
                amount_home REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(trip_id) REFERENCES trips(id)
            )
            """
        )
    print("Database initialized.")  # Добавлено для отладки


# Простейшее соответствие страна -> валюта для популярных направлений.
COUNTRY_TO_CURRENCY = {
    "россия": "RUB",
    "рф": "RUB",
    "russia": "RUB",
    "сша": "USD",
    "usa": "USD",
    "united states": "USD",
    "европа": "EUR",
    "europe": "EUR",
    "франция": "EUR",
    "germany": "EUR",
    "германия": "EUR",
    "италия": "EUR",
    "китай": "CNY",
    "china": "CNY",
    "япония": "JPY",
    "japan": "JPY",
    "великобритания": "GBP",
    "uk": "GBP",
    "united kingdom": "GBP",
    "турция": "TRY",
    "turkey": "TRY",
}


def detect_currency(country_name: str) -> Optional[str]:
    key = country_name.strip().lower()
    return COUNTRY_TO_CURRENCY.get(key)


bot = telebot.TeleBot(TELEGRAM_TOKEN)


def get_or_create_user(telegram_id: int) -> int:
    try:
        with closing(get_db_connection()) as conn:
            cur = conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            row = cur.fetchone()
            if row:
                print(f"User {telegram_id} found with id {row['id']}")  # Добавлено для отладки
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO users (telegram_id) VALUES (?)",
                (telegram_id,),
            )
            user_id = int(cur.lastrowid)
            print(f"User {telegram_id} created with id {user_id}")  # Добавлено для отладки
            return user_id
    except Exception as e:
        print(f"Error in get_or_create_user: {e}")
        raise


def set_active_trip(telegram_id: int, trip_id: Optional[int]) -> None:
    print(f"Setting active trip for user {telegram_id} to {trip_id}")  # Добавлено для отладки
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            UPDATE users
            SET active_trip_id = ?
            WHERE telegram_id = ?
            """,
            (trip_id, telegram_id),
        )
        conn.commit()  # Добавлен commit для сохранения изменений


def get_active_trip(telegram_id: int) -> Optional[sqlite3.Row]:
    with closing(get_db_connection()) as conn:
        cur = conn.execute(
            """
            SELECT t.*
            FROM users u
            JOIN trips t ON t.id = u.active_trip_id
            WHERE u.telegram_id = ?
            """,
            (telegram_id,),
        )
        return cur.fetchone()


def list_trips(telegram_id: int):
    with closing(get_db_connection()) as conn:
        user_id = get_or_create_user(telegram_id)
        cur = conn.execute(
            """
            SELECT id, name, home_currency, dest_currency, home_balance, dest_balance
            FROM trips
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


def create_trip(
    telegram_id: int,
    name: str,
    home_country: str,
    home_currency: str,
    dest_country: str,
    dest_currency: str,
    rate: float,
    home_start_amount: float,
) -> int:
    try:
        dest_start_amount = home_start_amount * rate
        user_id = get_or_create_user(telegram_id)
        print(f"Creating trip for user {user_id}")  # Добавлено для отладки
        with closing(get_db_connection()) as conn:
            cur = conn.execute(
                """
                INSERT INTO trips (
                    user_id, name,
                    home_country, home_currency,
                    dest_country, dest_currency,
                    rate, home_balance, dest_balance
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    name,
                    home_country,
                    home_currency,
                    dest_country,
                    dest_currency,
                    rate,
                    home_start_amount,
                    dest_start_amount,
                ),
            )
            trip_id = int(cur.lastrowid)
            conn.execute(
                """
                UPDATE users
                SET active_trip_id = ?
                WHERE telegram_id = ?
                """,
                (trip_id, telegram_id),
            )
            conn.commit()  # Явный commit
            print(f"Trip created with id {trip_id} for user {user_id}")  # Добавлено для отладки
            return trip_id
    except Exception as e:
        print(f"Error in create_trip: {e}")
        raise


def add_expense(trip_id: int, amount_dest: float, rate: float) -> None:
    print(f"Adding expense: trip_id={trip_id}, amount_dest={amount_dest}, rate={rate}")  # Добавлено для отладки
    amount_home = amount_dest / rate
    print(f"Calculated amount_home={amount_home}")  # Добавлено для отладки
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            INSERT INTO expenses (trip_id, amount_dest, amount_home)
            VALUES (?, ?, ?)
            """,
            (trip_id, amount_dest, amount_home),
        )
        conn.execute(
            """
            UPDATE trips
            SET dest_balance = dest_balance - ?,
                home_balance = home_balance - ?
            WHERE id = ?
            """,
            (amount_dest, amount_home, trip_id),
        )
        conn.commit()  # Явный commit
        print(f"Expense added to trip {trip_id}")  # Добавлено для отладки
def get_expenses(trip_id: int, limit: int = 20):
    with closing(get_db_connection()) as conn:
        cur = conn.execute(
            """
            SELECT amount_dest, amount_home, created_at
            FROM expenses
            WHERE trip_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (trip_id, limit),
        )
        return cur.fetchall()


def format_balance(trip: sqlite3.Row) -> str:
    return (
        f"Остаток: "
        f"{trip['dest_balance']:.2f} {trip['dest_currency']} = "
        f"{trip['home_balance']:.2f} {trip['home_currency']}"
    )


def main_menu_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton(
            text="🧳 Создать путешествие", callback_data="menu_create_trip"
        ),
        types.InlineKeyboardButton(
            text="🌍 Мои путешествия", callback_data="menu_my_trips"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            text="💰 Баланс", callback_data="menu_balance"
        ),
        types.InlineKeyboardButton(
            text="📊 История расходов", callback_data="menu_history"
        ),
    )
    kb.add(
        types.InlineKeyboardButton(
            text="⚙️ Изменить курс", callback_data="menu_change_rate"
        )
    )
    return kb


# Простейшая in-memory FSM: user_id -> state
user_states: Dict[int, Dict[str, Any]] = {}


def set_state(user_id: int, state: Optional[str], **kwargs: Any) -> None:
    if state is None:
        user_states.pop(user_id, None)
        return
    data = user_states.get(user_id, {})
    data["state"] = state
    data.update(kwargs)
    user_states[user_id] = data


def get_state(user_id: int) -> Dict[str, Any]:
    return user_states.get(user_id, {})


def parse_number(text: str) -> Optional[float]:
    cleaned = text.replace(",", ".").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def ask_home_country(chat_id: int, user_id: int) -> None:
    set_state(user_id, "creating_home_country")
    bot.send_message(
        chat_id,
        "Давайте создадим новое путешествие.\n"
        "Введите страну отправления (например, Россия).",
    )


def ask_dest_country(
    chat_id: int, user_id: int, home_country: str, home_currency: str
):
    set_state(
        user_id,
        "creating_dest_country",
        home_country=home_country,
        home_currency=home_currency,
    )
    bot.send_message(
        chat_id,
        f"Страна отправления: {home_country} ({home_currency}).\n"
        "Теперь введите страну назначения (например, Китай).",
    )


def ask_rate_confirmation(
    chat_id: int,
    user_id: int,
    home_country: str,
    home_currency: str,
    dest_country: str,
    dest_currency: str,
):
    rate = get_rate(home_currency, dest_currency)
    if rate is None:
        set_state(
            user_id,
            "creating_custom_rate",
            home_country=home_country,
            home_currency=home_currency,
            dest_country=dest_country,
            dest_currency=dest_currency,
        )
        bot.send_message(
            chat_id,
            "Не удалось получить курс из API.\n"
            "Пожалуйста, введите курс вручную "
            f"(сколько {dest_currency} за 1 {home_currency}).",
        )
        return

    set_state(
        user_id,
        "confirm_rate",
        home_country=home_country,
        home_currency=home_currency,
        dest_country=dest_country,
        dest_currency=dest_currency,
        rate=rate,
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Подходит", callback_data="rate_ok"),
        types.InlineKeyboardButton("❌ Ввести свой", callback_data="rate_custom"),
    )
    bot.send_message(
        chat_id,
        f"Текущий курс по данным API:\n"
        f"1 {home_currency} = {rate:.4f} {dest_currency}.\n"
        "Подходит такой курс?",
        reply_markup=kb,
    )


def ask_initial_amount(chat_id: int, user_id: int, context: Dict[str, Any]):
    # В контексте уже есть ключ "state", его нельзя передавать вторым разом.
    clean_context = {k: v for k, v in context.items() if k != "state"}
    set_state(user_id, "creating_initial_amount", **clean_context)
    bot.send_message(
        chat_id,
        f"Введите начальную сумму в домашней валюте "
        f"({context['home_currency']}) для этого путешествия.",
    )


@bot.message_handler(commands=["start"])
def handle_start(message: types.Message):
    get_or_create_user(message.from_user.id)
    text = (
        "Привет! Я ваш личный помощник для учёта расходов в путешествиях.\n\n"
        "Создайте новое путешествие, чтобы начать отслеживать расходы."
    )
    bot.send_message(message.chat.id, text, reply_markup=main_menu_keyboard())


@bot.message_handler(commands=["newtrip"])
def handle_newtrip(message: types.Message):
    ask_home_country(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["switch"])
def handle_switch(message: types.Message):
    show_trips_for_switch(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["balance"])
def handle_balance(message: types.Message):
    show_balance(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["history"])
def handle_history(message: types.Message):
    show_history(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["setrate"])
def handle_setrate(message: types.Message):
    start_change_rate_flow(message.chat.id, message.from_user.id)


def show_trips_for_switch(chat_id: int, user_id: int):
    print(f"show_trips_for_switch called for user {user_id}")  # Добавлено для отладки
    trips = list_trips(user_id)
    print(f"Found {len(trips)} trips")  # Добавлено для отладки
    if not trips:
        bot.send_message(
            chat_id,
            "У вас ещё нет путешествий. Нажмите «🧳 Создать путешествие».",
            reply_markup=main_menu_keyboard(),
        )
        return

    active_trip = get_active_trip(user_id)
    active_id = active_trip['id'] if active_trip else None

    kb = types.InlineKeyboardMarkup()
    for t in trips:
        status = " (активное)" if t['id'] == active_id else ""
        title = f"{t['name']} ({t['home_currency']}→{t['dest_currency']}){status}"
        kb.add(
            types.InlineKeyboardButton(
                title, callback_data=f"switch_trip:{t['id']}"
            )
        )
    bot.send_message(chat_id, "Выберите активное путешествие:", reply_markup=kb)


def show_balance(chat_id: int, user_id: int):
    print(f"show_balance called for user {user_id}")  # Добавлено для отладки
    trip = get_active_trip(user_id)
    print(f"Active trip: {trip}")  # Добавлено для отладки
    if not trip:
        bot.send_message(
            chat_id,
            "Активное путешествие не выбрано.\n"
            "Создайте новое или выберите из списка.",
            reply_markup=main_menu_keyboard(),
        )
        return
    bot.send_message(
        chat_id,
        f"Текущее путешествие: {trip['name']}\n{format_balance(trip)}",
        reply_markup=main_menu_keyboard(),
    )


def show_history(chat_id: int, user_id: int):
    print(f"show_history called for user {user_id}")  # Добавлено для отладки
    trip = get_active_trip(user_id)
    print(f"Trip for history: {trip}")  # Добавлено для отладки
    if not trip:
        bot.send_message(
            chat_id,
            "Активное путешествие не выбрано.",
            reply_markup=main_menu_keyboard(),
        )
        return
    expenses = get_expenses(trip["id"])
    print(f"Expenses: {expenses}")  # Добавлено для отладки
    if not expenses:
        bot.send_message(
            chat_id,
            "История расходов пока пуста.",
            reply_markup=main_menu_keyboard(),
        )
        return
    lines = []
    for e in expenses:
        lines.append(
            f"- {e['amount_dest']:.2f} {trip['dest_currency']} = "
            f"{e['amount_home']:.2f} {trip['home_currency']} "
            f"({e['created_at']})"
        )
    bot.send_message(
        chat_id,
        "Последние расходы:\n" + "\n".join(lines),
        reply_markup=main_menu_keyboard(),
    )


def start_change_rate_flow(chat_id: int, user_id: int):
    trip = get_active_trip(user_id)
    if not trip:
        bot.send_message(
            chat_id,
            "Сначала создайте путешествие.",
            reply_markup=main_menu_keyboard(),
        )
        return
    set_state(
        user_id,
        "change_rate",
        trip_id=trip["id"],
        home_currency=trip["home_currency"],
        dest_currency=trip["dest_currency"],
    )
    bot.send_message(
        chat_id,
        "Введите новый курс вручную:\n"
        f"сколько {trip['dest_currency']} за 1 {trip['home_currency']}?",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_main_menu_callbacks(call: types.CallbackQuery):
    try:
        print(f"Handling menu callback: {call.data}")  # Добавлено для отладки
        data = call.data
        user_id = call.from_user.id

        if data == "menu_create_trip":
            ask_home_country(call.message.chat.id, user_id)
        elif data == "menu_my_trips":
            show_trips_for_switch(call.message.chat.id, user_id)
        elif data == "menu_balance":
            show_balance(call.message.chat.id, user_id)
        elif data == "menu_history":
            show_history(call.message.chat.id, user_id)
        elif data == "menu_change_rate":
            start_change_rate_flow(call.message.chat.id, user_id)

        bot.answer_callback_query(call.id)
        print(f"Callback {call.data} handled successfully")  # Добавлено для отладки
    except Exception as e:
        print(f"Error in handle_main_menu_callbacks: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("switch_trip:"))
def handle_switch_trip(call: types.CallbackQuery):
    print(f"Handling switch trip callback: {call.data}")  # Добавлено для отладки
    _, trip_id_str = call.data.split(":", 1)
    trip_id = int(trip_id_str)
    set_active_trip(call.from_user.id, trip_id)
    print(f"Switched to trip {trip_id}, now calling show_balance")  # Добавлено для отладки
    bot.answer_callback_query(call.id, "Путешествие переключено.")
    show_balance(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda call: call.data in ("rate_ok", "rate_custom"))
def handle_rate_choice(call: types.CallbackQuery):
    print(f"Handling rate choice callback: {call.data}")  # Добавлено для отладки
    state = get_state(call.from_user.id)
    if state.get("state") != "confirm_rate":
        bot.answer_callback_query(call.id)
        return

    if call.data == "rate_ok":
        ask_initial_amount(call.message.chat.id, call.from_user.id, state)
    else:
        set_state(
            call.from_user.id,
            "creating_custom_rate",
            home_country=state["home_country"],
            home_currency=state["home_currency"],
            dest_country=state["dest_country"],
            dest_currency=state["dest_currency"],
        )
        bot.send_message(
            call.message.chat.id,
            "Введите курс вручную:\n"
            f"сколько {state['dest_currency']} за 1 {state['home_currency']}?",
        )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("confirm_expense:")
)
def handle_confirm_expense(call: types.CallbackQuery):
    print(f"Handling confirm expense callback: {call.data}")  # Добавлено для отладки
    _, amount_str = call.data.split(":", 1)
    amount_dest = float(amount_str)
    trip = get_active_trip(call.from_user.id)
    print(f"Confirming expense for trip: {trip}")  # Добавлено для отладки
    if not trip:
        bot.answer_callback_query(call.id, "Нет активного путешествия.")
        return
    add_expense(trip["id"], amount_dest, trip["rate"])
    bot.answer_callback_query(call.id, "Расход учтён.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, None)
    bot.send_message(
        call.message.chat.id,
        f"Расход добавлен.\n{format_balance(get_active_trip(call.from_user.id))}",
        reply_markup=main_menu_keyboard(),
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("cancel_expense:")
)
def handle_cancel_expense(call: types.CallbackQuery):
    print(f"Handling cancel expense callback: {call.data}")  # Добавлено для отладки
    bot.answer_callback_query(call.id, "Расход не сохранён.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, None)
    bot.send_message(
        call.message.chat.id,
        "Расход не учтён.",
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_all_text(message: types.Message):
    try:
        print(f"Handling text message: {message.text}")  # Добавлено для отладки
        user_id = message.from_user.id
        text = message.text.strip()
        state = get_state(user_id)
        current_state = state.get("state")

        if current_state == "creating_home_country":
            home_country = text
            currency = detect_currency(home_country)
            if not currency:
                set_state(user_id, "creating_home_currency", home_country=home_country)
                bot.send_message(
                    message.chat.id,
                    "Я не знаю валюту этой страны.\n"
                    "Введите код валюты (например, RUB, USD, EUR).",
                )
            else:
                ask_dest_country(message.chat.id, user_id, home_country, currency)
            return

        if current_state == "creating_home_currency":
            home_country = state["home_country"]
            currency = text.upper()
            ask_dest_country(message.chat.id, user_id, home_country, currency)
            return

        if current_state == "creating_dest_country":
            dest_country = text
            dest_currency = detect_currency(dest_country)
            if not dest_currency:
                set_state(
                    user_id,
                    "creating_dest_currency",
                    home_country=state["home_country"],
                    home_currency=state["home_currency"],
                    dest_country=dest_country,
                )
                bot.send_message(
                    message.chat.id,
                    "Я не знаю валюту этой страны.\n"
                    "Введите код валюты (например, CNY, EUR, USD).",
                )
            else:
                ask_rate_confirmation(
                    message.chat.id,
                    user_id,
                    state["home_country"],
                    state["home_currency"],
                    dest_country,
                    dest_currency,
                )
            return

        if current_state == "creating_dest_currency":
            dest_currency = text.upper()
            ask_rate_confirmation(
                message.chat.id,
                user_id,
                state["home_country"],
                state["home_currency"],
                state["dest_country"],
                dest_currency,
            )
            return

        if current_state == "creating_custom_rate":
            rate = parse_number(text)
            if rate is None or rate <= 0:
                bot.send_message(
                    message.chat.id,
                    "Курс должен быть положительным числом. Попробуйте ещё раз.",
                )
                return
            state.update(rate=rate)
            ask_initial_amount(message.chat.id, user_id, state)
            return

        if current_state == "creating_initial_amount":
            amount = parse_number(text)
            if amount is None or amount <= 0:
                bot.send_message(
                    message.chat.id,
                    "Введите положительное число для начальной суммы.",
                )
                return
            trip_name = (
                f"{state['home_country']} → {state['dest_country']}"
            )
            trip_id = create_trip(
                user_id,
                trip_name,
                state["home_country"],
                state["home_currency"],
                state["dest_country"],
                state["dest_currency"],
                float(state["rate"]),
                amount,
            )
            set_state(user_id, None)
            trip = get_active_trip(user_id)
            bot.send_message(
                message.chat.id,
                "Путешествие создано!\n"
                f"Название: {trip_name}\n"
                f"{format_balance(trip)}",
                reply_markup=main_menu_keyboard(),
            )
            return

        if current_state == "change_rate":
            new_rate = parse_number(text)
            if new_rate is None or new_rate <= 0:
                bot.send_message(
                    message.chat.id,
                    "Курс должен быть положительным числом. Попробуйте ещё раз.",
                )
            else:
                with closing(get_db_connection()) as conn:
                    # Получить текущий home_balance
                    cur = conn.execute("SELECT home_balance FROM trips WHERE id = ?", (state["trip_id"],))
                    row = cur.fetchone()
                    home_balance = row["home_balance"]
                    new_dest_balance = home_balance * new_rate
                    conn.execute(
                        "UPDATE trips SET rate = ?, dest_balance = ? WHERE id = ?",
                        (new_rate, new_dest_balance, state["trip_id"]),
                    )
                    conn.commit()  # Явный commit
                set_state(user_id, None)
                bot.send_message(
                    message.chat.id,
                    "Курс обновлён.",
                    reply_markup=main_menu_keyboard(),
                )
            return

        # Если пользователь не в состоянии создания/изменения — пробуем воспринять сообщение как расход.
        amount = parse_number(text)
        if amount is None:
            bot.send_message(
                message.chat.id,
                "Я ожидаю число (сумму расхода) или используйте кнопки меню.",
                reply_markup=main_menu_keyboard(),
            )
            return

        trip = get_active_trip(user_id)
        if not trip:
            bot.send_message(
                message.chat.id,
                "Сначала создайте путешествие, чтобы учитывать расходы.",
                reply_markup=main_menu_keyboard(),
            )
            return

        amount_home = amount / trip["rate"]
        kb = types.InlineKeyboardMarkup()
        kb.add(
            types.InlineKeyboardButton(
                "✅ Да", callback_data=f"confirm_expense:{amount}"
            ),
            types.InlineKeyboardButton(
                "❌ Нет", callback_data=f"cancel_expense:{amount}"
            ),
        )
        bot.send_message(
            message.chat.id,
            f"{amount:.2f} {trip['dest_currency']} = "
            f"{amount_home:.2f} {trip['home_currency']}\n"
            "Учесть как расход?",
            reply_markup=kb,
        )
    except Exception as e:
        print(f"Error in handle_all_text: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обработке сообщения.")


def main() -> None:
    init_db()
    print("Бот запущен и начинает polling...")  # Добавлено для отладки
    bot.infinity_polling()


if __name__ == "__main__":
    main()

