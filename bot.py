import asyncio
import logging
import os
import json
import sqlite3
import random
import shutil
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from slot_data import (
    SLOT_COMBINATIONS, 
    SYMBOL_EMOJI, 
    SYMBOLS, 
    SYMBOL_NAMES,
    find_value_by_combination,
    format_combination,
    format_winning_message,
    is_preset_combo
)
from database import Database

from gift_parser import (
    load_gifts_from_file, 
    parse_gift_url, 
    validate_gift_url,
    scrape_collection_web,
    COLLECTION_URL
)

from points_event_handlers import (
    handle_points_777,
    handle_points_bar,
    handle_points_grape,
    handle_points_lemon,
    handle_duration,
    calculate_points_for_value
)

load_dotenv()


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен и admin ID из переменных окружения
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "793216884"))
ALLOWED_CHAT_ID = int(os.getenv("ALLOWED_CHAT_ID", "-1004290474956"))

if not TOKEN:
    raise ValueError("❌ Токен бота не найден! Создай .env файл и добавь туда BOT_TOKEN")

if ALLOWED_CHAT_ID == 0:
    logger.warning("⚠️ ALLOWED_CHAT_ID не установлен! Бот будет работать во всех чатах.")

# Файл для хранения настроек
CONFIG_FILE = "config.json"

# Создаём бота и диспетчер с хранилищем состояний
storage = MemoryStorage()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)


@dp.update()
async def check_allowed_chat(update):
    """Middleware для проверки чата"""
    # Если ALLOWED_CHAT_ID не установлен (0), пропускаем все
    if ALLOWED_CHAT_ID == 0:
        return True
    
    # Проверяем сообщения
    if hasattr(update, 'message') and update.message:
        chat_id = update.message.chat.id
        if chat_id != ALLOWED_CHAT_ID:
            logger.info(f"Игнорируем сообщение из чата: {chat_id} (разрешен только: {ALLOWED_CHAT_ID})")
            return False
    
    # Проверяем callback queries
    if hasattr(update, 'callback_query') and update.callback_query:
        chat_id = update.callback_query.message.chat.id
        if chat_id != ALLOWED_CHAT_ID:
            logger.info(f"Игнорируем callback из чата: {chat_id} (разрешен только: {ALLOWED_CHAT_ID})")
            return False
    
    return True

# Состояния для FSM
class CustomCombo(StatesGroup):
    wheel1 = State()
    wheel2 = State()
    wheel3 = State()


class CreateEvent(StatesGroup):
    select_type = State()
    select_combo = State()
    select_count = State()
    wheel1 = State()
    wheel2 = State()
    wheel3 = State()
    # Для режима очков
    points_777 = State()
    points_bar = State()
    points_grape = State()
    points_lemon = State()
    duration = State()
    target_points = State()


class AddGifts(StatesGroup):
    select_level = State()
    enter_urls = State()


def load_config():
    """Загружаем конфигурацию из файла"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"winning_value": 64}

def save_config(config):
    """Сохраняем конфигурацию в файл"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# Загружаем конфигурацию при старте
config = load_config()

# Инициализируем базу данных
database_file = os.getenv("DATABASE_FILE", os.path.join("data", "bot_database.db"))
legacy_database_file = "bot_database.db"
if (
    os.path.abspath(database_file) != os.path.abspath(legacy_database_file)
    and not os.path.exists(database_file)
    and os.path.exists(legacy_database_file)
):
    os.makedirs(os.path.dirname(os.path.abspath(database_file)), exist_ok=True)
    shutil.copy2(legacy_database_file, database_file)
    for suffix in ("-wal", "-shm"):
        legacy_sidecar = f"{legacy_database_file}{suffix}"
        if os.path.exists(legacy_sidecar):
            shutil.copy2(legacy_sidecar, f"{database_file}{suffix}")

db = Database(database_file)

# Хранилище активных сессий гифтов (в памяти)
# Ключ: session_id, Значение: { user_id, username, current_level, current_gift, claimed, upgrade_message_id }
active_gift_sessions = {}
gift_session_counter = 0
free_spin_sessions = {}
free_spin_session_counter = 0

# Хранилище ожидания выбора числа для кубика 3->4
# Ключ: session_id, Значение: { expected_number }
dice_number_sessions = {}


def generate_session_id():
    """Генерация уникального ID сессии"""
    global gift_session_counter
    gift_session_counter += 1
    return gift_session_counter


def generate_free_spin_session_id():
    """Генерация ID сессии выбора фри-спина"""
    global free_spin_session_counter
    free_spin_session_counter += 1
    return free_spin_session_counter


def get_message_link(message: Message) -> str:
    """Сформировать ссылку на сообщение в публичном или приватном чате."""
    chat = message.chat
    if chat.username:
        return f"https://t.me/{chat.username}/{message.message_id}"

    chat_id = str(chat.id)
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message.message_id}"

    return ""


def get_free_spin_keyboard(session_id, selected_index=None, result=None, bear_index=None):
    """Три кнопки выбора ячейки для фри-спина"""
    button_emoji = "5359628193336669414"
    bear_emoji = "5346209096301310711"
    miss_emoji = "5210952531676504517"
    buttons = []

    for index in range(3):
        emoji_id = button_emoji
        style = None
        if result is not None:
            emoji_id = bear_emoji if index == bear_index else miss_emoji
        if index == selected_index:
            style = "success"
        buttons.append(InlineKeyboardButton(
            text=" ",
            icon_custom_emoji_id=emoji_id,
            style=style,
            callback_data=f"free_spin_{session_id}_{index}"
        ))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def get_claim_upgrade_keyboard(session_id, show_upgrade=True):
    """Клавиатура с кнопками Забрать/Апгрейд"""
    buttons = [[
        InlineKeyboardButton(
            text="Забрать",
            icon_custom_emoji_id="5465262274031659421",
            callback_data=f"claim_gift_{session_id}"
        )
    ]]
    if show_upgrade:
        buttons[0].append(InlineKeyboardButton(
            text="Апгрейд",
            icon_custom_emoji_id="5463122435425448565",
            callback_data=f"upgrade_gift_{session_id}"
        ))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_dice_number_keyboard(session_id):
    """Клавиатура с кнопками 1-6 для выбора числа на кубике"""
    buttons = []
    row = []
    for num in range(1, 7):
        row.append(InlineKeyboardButton(text=str(num), callback_data=f"picknum_{session_id}_{num}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


LEVEL_BANK_LINKS = {
    1: "https://t.me/toriw9/c/6",
    2: "https://t.me/toriw9/c/9",
    3: "https://t.me/toriw9/c/10",
    4: "https://t.me/toriw9/c/11"
}

LEVEL_BANK_NAMES = {
    1: "Обычный банк",
    2: "Major Bank",
    3: "Premium Bank",
    4: "Elite Bank"
}

LEVEL_BANK_CUSTOM_EMOJI = {
    2: '<tg-emoji emoji-id="5188296252772613374">🏦</tg-emoji>',
    3: '<tg-emoji emoji-id="5348360333750727947">🏦</tg-emoji>',
    4: '<tg-emoji emoji-id="5346209096301310711">🏦</tg-emoji>'
}

FINAL_PRIZE_CUSTOM_EMOJI = '<tg-emoji emoji-id="5199615755045344644">🎁</tg-emoji>'


def get_admin_keyboard():
    """Клавиатура админ-панели"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Выбрать победную комбинацию", callback_data="admin_select_combo")],
        [InlineKeyboardButton(text="🎉 Создать событие", callback_data="admin_create_event")],
        [InlineKeyboardButton(text="📊 Текущее событие", callback_data="admin_current_event")],
        [InlineKeyboardButton(text="🛑 Остановить событие", callback_data="admin_stop_event")],
        [InlineKeyboardButton(text="🎁 Управление подарками", callback_data="admin_gifts")],
        [InlineKeyboardButton(text="ℹ️ Текущие настройки", callback_data="admin_current_settings")],
    ])
    return keyboard


def get_combo_keyboard():
    """Клавиатура выбора комбинации"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Все джекпоты (4 комбинации)", callback_data="combo_all")],
        [InlineKeyboardButton(text="7️⃣ 7️⃣ 7️⃣ (777)", callback_data="combo_64")],
        [InlineKeyboardButton(text="🎰 🎰 🎰 (BAR BAR BAR)", callback_data="combo_1")],
        [InlineKeyboardButton(text="🍇 🍇 🍇 (Виноград)", callback_data="combo_22")],
        [InlineKeyboardButton(text="🍋 🍋 🍋 (Лимон)", callback_data="combo_43")],
        [InlineKeyboardButton(text="✏️ Кастомная комбинация", callback_data="combo_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    return keyboard


def get_symbol_keyboard():
    """Клавиатура выбора символа"""
    buttons = [[InlineKeyboardButton(text=SYMBOL_NAMES[symbol], callback_data=f"symbol_{symbol}")] 
               for symbol in SYMBOLS]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


def get_event_type_keyboard():
    """Клавиатура выбора типа события"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Первый кто выбьет N раз", callback_data="event_type_first")],
        [InlineKeyboardButton(text="🔥 Подряд N раз", callback_data="event_type_streak")],
        [InlineKeyboardButton(text="⭐ Режим очков", callback_data="event_type_points")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    return keyboard


def get_event_combo_keyboard():
    """Клавиатура выбора комбинации для события"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7️⃣ 7️⃣ 7️⃣ (777)", callback_data="event_combo_64")],
        [InlineKeyboardButton(text="🎰 🎰 🎰 (BAR BAR BAR)", callback_data="event_combo_1")],
        [InlineKeyboardButton(text="🍇 🍇 🍇 (Виноград)", callback_data="event_combo_22")],
        [InlineKeyboardButton(text="🍋 🍋 🍋 (Лимон)", callback_data="event_combo_43")],
        [InlineKeyboardButton(text="✏️ Кастомная комбинация", callback_data="event_combo_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    return keyboard


def get_count_keyboard():
    """Клавиатура выбора количества"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3️⃣", callback_data="count_3"),
         InlineKeyboardButton(text="5️⃣", callback_data="count_5"),
         InlineKeyboardButton(text="🔟", callback_data="count_10")],
        [InlineKeyboardButton(text="2️⃣0️⃣", callback_data="count_20"),
         InlineKeyboardButton(text="5️⃣0️⃣", callback_data="count_50")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    return keyboard


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "👋 Привет, владелец! У тебя есть доступ к настройкам бота.\n\n"
            "Отправь мне игровой автомат 🎰 и я проверю результат!",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "👋 Привет! Отправь мне игровой автомат 🎰 и я проверю результат!"
        )


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    """Команда для админ-панели"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде!")
        return
    
    await message.answer(
        "⚙️ Админ-панель\n\n"
        "Здесь ты можешь настроить победную комбинацию.",
        reply_markup=get_admin_keyboard()
    )


@dp.message(Command("gifts"))
async def cmd_gifts(message: Message):
    """Команда для просмотра всех подарков"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде!")
        return
    
    stats = db.get_gifts_stats()
    
    # Кастомные эмодзи
    emoji_database = '<tg-emoji emoji-id="5440824464168223114">📦</tg-emoji>'
    emoji_stats = '<tg-emoji emoji-id="4958506272551863292">📊</tg-emoji>'
    emoji_available = '<tg-emoji emoji-id="5206607081334906820">✅</tg-emoji>'
    emoji_used = '<tg-emoji emoji-id="5409008750893734809">❌</tg-emoji>'
    
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    # Формируем сообщение
    text = f"{emoji_database} <b>База подарков</b>\n\n"
    text += f"{emoji_stats} <b>Статистика:</b>\n"
    text += f"Всего: {stats['total']}\n"
    text += f"Доступно: {stats['available']}\n\n"
    
    for level in range(1, 5):
        ls = stats['levels'].get(level, {'total': 0, 'used': 0, 'available': 0})
        if ls['available'] > 0 or ls['used'] > 0:
            available_gifts = db.get_unused_gifts_list(level=level)
            if available_gifts:
                text += f"{emoji_available} <b>{level} lvl - {level_names[level]} ({ls['available']}):</b>\n"
                available_list = ""
                for gift in available_gifts:
                    available_list += f"• <a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n"
                text += f"<blockquote expandable>{available_list}</blockquote>\n"
    
    # Получаем последние 5 использованных подарков
    recent_used_gifts = db.get_recent_used_gifts(limit=5)
    
    if recent_used_gifts:
        text += f"\n{emoji_used} <b>Последние выбитые подарки:</b>\n"
        
        used_list = ""
        for gift in recent_used_gifts:
            username = gift['used_by_username'] or 'неизвестно'
            used_list += f"• {gift['gift_name']} (lvl {gift.get('level', '?')}) → @{username}\n"
        
        text += f"<blockquote expandable>{used_list}</blockquote>"
    
    if stats['available'] == 0 and not recent_used_gifts:
        await message.answer("📦 База подарков пуста!\n\nДобавь подарки через /admin → 🎁 Управление подарками")
        return
    
    await message.answer(text)


@dp.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    """Возврат в админ-меню"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "⚙️ Админ-панель\n\n"
        "Здесь ты можешь настроить победную комбинацию.",
        reply_markup=get_admin_keyboard()
    )


@dp.callback_query(F.data == "admin_select_combo")
async def select_combo(callback: CallbackQuery):
    """Выбор победной комбинации"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎰 Выбери победную комбинацию:\n\n"
        "Бот будет отвечать только когда выпадет выбранная комбинация.",
        reply_markup=get_combo_keyboard()
    )


@dp.callback_query(F.data == "admin_current_settings")
async def current_settings(callback: CallbackQuery):
    """Показать текущие настройки"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    if config.get("winning_value"):
        winning_value = config["winning_value"]
        
        # Проверяем, является ли это списком (все джекпоты)
        if isinstance(winning_value, list):
            combo_text = "🎰 Все джекпоты:\n"
            combo_text += "  • 🎰 🎰 🎰 (BAR BAR BAR)\n"
            combo_text += "  • 🍇 🍇 🍇 (Виноград)\n"
            combo_text += "  • 🍋 🍋 🍋 (Лимон)\n"
            combo_text += "  • 7️⃣ 7️⃣ 7️⃣ (777)"
        else:
            combo = SLOT_COMBINATIONS.get(winning_value)
            combo_text = format_combination(combo) if combo else f"Значение: {winning_value}"
    else:
        combo_text = "не установлена"
    
    await callback.message.edit_text(
        f"ℹ️ Текущие настройки:\n\n"
        f"Победная комбинация: {combo_text}\n\n"
        f"Бот отвечает только на эту комбинацию!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )


@dp.callback_query(F.data.startswith("combo_"))
async def set_combo(callback: CallbackQuery, state: FSMContext):
    """Установка победной комбинации"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    combo_type = callback.data.split("_")[1]
    
    if combo_type == "custom":
        await callback.message.edit_text(
            "✏️ Кастомная комбинация\n\n"
            "Выбери символ для первого колеса:",
            reply_markup=get_symbol_keyboard()
        )
        await state.set_state(CustomCombo.wheel1)
    elif combo_type == "all":
        # Устанавливаем все 4 джекпота одновременно
        config["winning_value"] = [1, 22, 43, 64]  # BAR, виноград, лимон, 777
        save_config(config)
        
        await callback.message.edit_text(
            "✅ Победные комбинации установлены:\n\n"
            "🎰 🎰 🎰 (BAR BAR BAR)\n"
            "🍇 🍇 🍇 (Виноград)\n"
            "🍋 🍋 🍋 (Лимон)\n"
            "7️⃣ 7️⃣ 7️⃣ (777)\n\n"
            "Теперь бот будет отвечать на ВСЕ 4 джекпота!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
            ])
        )
    else:
        value = int(combo_type)
        config["winning_value"] = value
        save_config(config)
        
        combo = SLOT_COMBINATIONS[value]
        combo_text = format_combination(combo)
        
        await callback.message.edit_text(
            f"✅ Победная комбинация установлена: {combo_text}\n\n"
            f"Теперь бот будет отвечать только на эту комбинацию!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
            ])
        )
    
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CustomCombo.wheel1)
async def set_wheel1(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для первого колеса"""
    symbol = callback.data.split("_", 1)[1]
    await state.update_data(wheel1=symbol)
    
    await callback.message.edit_text(
        f"✏️ Кастомная комбинация\n\n"
        f"Первое колесо: {SYMBOL_EMOJI[symbol]}\n\n"
        f"Выбери символ для второго колеса:",
        reply_markup=get_symbol_keyboard()
    )
    await state.set_state(CustomCombo.wheel2)
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CustomCombo.wheel2)
async def set_wheel2(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для второго колеса"""
    symbol = callback.data.split("_", 1)[1]
    await state.update_data(wheel2=symbol)
    
    data = await state.get_data()
    await callback.message.edit_text(
        f"✏️ Кастомная комбинация\n\n"
        f"Первое колесо: {SYMBOL_EMOJI[data['wheel1']]}\n"
        f"Второе колесо: {SYMBOL_EMOJI[symbol]}\n\n"
        f"Выбери символ для третьего колеса:",
        reply_markup=get_symbol_keyboard()
    )
    await state.set_state(CustomCombo.wheel3)
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CustomCombo.wheel3)
async def set_wheel3(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для третьего колеса"""
    symbol = callback.data.split("_", 1)[1]
    
    data = await state.get_data()
    first = data['wheel1']
    second = data['wheel2']
    third = symbol
    
    # Находим соответствующее значение dice
    value = find_value_by_combination(first, second, third)
    
    if value:
        config["winning_value"] = value
        save_config(config)
        
        combo_str = f"{SYMBOL_EMOJI[first]} {SYMBOL_EMOJI[second]} {SYMBOL_EMOJI[third]}"
        await callback.message.edit_text(
            f"✅ Кастомная комбинация установлена: {combo_str}\n\n"
            f"Значение: {value}\n\n"
            f"Теперь бот будет отвечать только на эту комбинацию!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
            ])
        )
    else:
        await callback.message.edit_text(
            f"❌ Ошибка: не удалось найти комбинацию {first} {second} {third}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
            ])
        )
    
    await state.clear()
    await callback.answer()


# ==================== ОБРАБОТЧИКИ СОБЫТИЙ ====================

@dp.callback_query(F.data == "admin_create_event")
async def create_event_start(callback: CallbackQuery, state: FSMContext):
    """Начало создания события"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎉 Создание нового события\n\n"
        "Выбери тип события:",
        reply_markup=get_event_type_keyboard()
    )
    await state.set_state(CreateEvent.select_type)


@dp.callback_query(F.data.startswith("event_type_"), CreateEvent.select_type)
async def set_event_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа события"""
    event_type = callback.data.split("_")[2]
    await state.update_data(event_type=event_type)
    
    if event_type == "points":
        # Режим очков - сразу переходим к настройке баллов
        await callback.message.edit_text(
            "⭐ <b>Режим очков</b>\n\n"
            "Настрой баллы за каждую комбинацию:\n\n"
            "Сколько баллов за 7️⃣ 7️⃣ 7️⃣ (777)?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="10", callback_data="pts_777_10"),
                 InlineKeyboardButton(text="25", callback_data="pts_777_25"),
                 InlineKeyboardButton(text="50", callback_data="pts_777_50")],
                [InlineKeyboardButton(text="100", callback_data="pts_777_100"),
                 InlineKeyboardButton(text="200", callback_data="pts_777_200")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
            ])
        )
        await state.set_state(CreateEvent.points_777)
    else:
        type_name = "Первый кто выбьет N раз" if event_type == "first" else "Подряд N раз"
        
        await callback.message.edit_text(
            f"🎉 Тип события: {type_name}\n\n"
            f"Теперь выбери целевую комбинацию:",
            reply_markup=get_event_combo_keyboard()
        )
        await state.set_state(CreateEvent.select_combo)
    
    await callback.answer()


@dp.callback_query(F.data.startswith("event_combo_"), CreateEvent.select_combo)
async def set_event_combo(callback: CallbackQuery, state: FSMContext):
    """Выбор комбинации для события"""
    combo_part = callback.data.split("_")[2]
    
    if combo_part == "custom":
        await callback.message.edit_text(
            "✏️ Кастомная комбинация\n\n"
            "Выбери символ для первого колеса:",
            reply_markup=get_symbol_keyboard()
        )
        await state.set_state(CreateEvent.wheel1)
    else:
        value = int(combo_part)
        await state.update_data(target_value=value)
        
        combo = SLOT_COMBINATIONS[value]
        combo_text = format_combination(combo)
        
        await callback.message.edit_text(
            f"🎯 Целевая комбинация: {combo_text}\n\n"
            f"Теперь выбери сколько раз нужно выбить:",
            reply_markup=get_count_keyboard()
        )
        await state.set_state(CreateEvent.select_count)
    
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CreateEvent.wheel1)
async def set_event_wheel1(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для первого колеса (событие)"""
    symbol = callback.data.split("_", 1)[1]
    await state.update_data(wheel1=symbol)
    
    await callback.message.edit_text(
        f"✏️ Кастомная комбинация\n\n"
        f"Первое колесо: {SYMBOL_EMOJI[symbol]}\n\n"
        f"Выбери символ для второго колеса:",
        reply_markup=get_symbol_keyboard()
    )
    await state.set_state(CreateEvent.wheel2)
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CreateEvent.wheel2)
async def set_event_wheel2(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для второго колеса (событие)"""
    symbol = callback.data.split("_", 1)[1]
    await state.update_data(wheel2=symbol)
    
    data = await state.get_data()
    await callback.message.edit_text(
        f"✏️ Кастомная комбинация\n\n"
        f"Первое колесо: {SYMBOL_EMOJI[data['wheel1']]}\n"
        f"Второе колесо: {SYMBOL_EMOJI[symbol]}\n\n"
        f"Выбери символ для третьего колеса:",
        reply_markup=get_symbol_keyboard()
    )
    await state.set_state(CreateEvent.wheel3)
    await callback.answer()


@dp.callback_query(F.data.startswith("symbol_"), CreateEvent.wheel3)
async def set_event_wheel3(callback: CallbackQuery, state: FSMContext):
    """Выбор символа для третьего колеса (событие)"""
    symbol = callback.data.split("_", 1)[1]
    
    data = await state.get_data()
    first = data['wheel1']
    second = data['wheel2']
    third = symbol
    
    value = find_value_by_combination(first, second, third)
    
    if value:
        await state.update_data(target_value=value)
        combo_str = f"{SYMBOL_EMOJI[first]} {SYMBOL_EMOJI[second]} {SYMBOL_EMOJI[third]}"
        
        await callback.message.edit_text(
            f"🎯 Целевая комбинация: {combo_str}\n\n"
            f"Теперь выбери сколько раз нужно выбить:",
            reply_markup=get_count_keyboard()
        )
        await state.set_state(CreateEvent.select_count)
    else:
        await callback.message.edit_text(
            f"❌ Ошибка: не удалось найти комбинацию",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
            ])
        )
        await state.clear()
    
    await callback.answer()


@dp.callback_query(F.data.startswith("count_"), CreateEvent.select_count)
async def set_event_count(callback: CallbackQuery, state: FSMContext):
    """Выбор количества для события"""
    count = int(callback.data.split("_")[1])
    
    data = await state.get_data()
    event_type = data['event_type']
    target_value = data['target_value']
    
    # Создаем событие в БД
    event_id = db.create_event(event_type, target_value, count)
    
    combo = SLOT_COMBINATIONS[target_value]
    combo_text = format_combination(combo)
    type_name = "Первый кто выбьет" if event_type == "first" else "Подряд"
    
    await callback.message.edit_text(
        f"✅ Событие создано!\n\n"
        f"🎯 Тип: {type_name} {count} раз\n"
        f"🎰 Комбинация: {combo_text}\n"
        f"🆔 ID события: {event_id}\n\n"
        f"Событие активно! Пользователи могут участвовать.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
        ])
    )
    
    await state.clear()
    await callback.answer()


# ==================== ОБРАБОТЧИКИ РЕЖИМА ОЧКОВ ====================

@dp.callback_query(F.data.startswith("pts_777_"), CreateEvent.points_777)
async def set_points_777(callback: CallbackQuery, state: FSMContext):
    """Установка баллов за 777"""
    await handle_points_777(callback, state, CreateEvent)


@dp.callback_query(F.data.startswith("pts_bar_"), CreateEvent.points_bar)
async def set_points_bar(callback: CallbackQuery, state: FSMContext):
    """Установка баллов за BAR"""
    await handle_points_bar(callback, state, CreateEvent)


@dp.callback_query(F.data.startswith("pts_grape_"), CreateEvent.points_grape)
async def set_points_grape(callback: CallbackQuery, state: FSMContext):
    """Установка баллов за виноград"""
    await handle_points_grape(callback, state, CreateEvent)


@dp.callback_query(F.data.startswith("pts_lemon_"), CreateEvent.points_lemon)
async def set_points_lemon(callback: CallbackQuery, state: FSMContext):
    """Установка баллов за лимон"""
    await handle_points_lemon(callback, state, CreateEvent)


@dp.callback_query(F.data.startswith("dur_"), CreateEvent.duration)
async def set_duration(callback: CallbackQuery, state: FSMContext):
    """Установка длительности"""
    await handle_duration(callback, state, CreateEvent, db)


@dp.callback_query(F.data == "admin_current_event")
async def show_current_event(callback: CallbackQuery):
    """Показать текущее событие"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    event = db.get_active_event()
    
    if not event:
        await callback.message.edit_text(
            "📊 Нет активных событий",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
            ])
        )
        return
    
    combo = SLOT_COMBINATIONS.get(event['target_value'])
    combo_text = format_combination(combo) if combo else "неизвестно"
    type_name = "Первый кто выбьет" if event['event_type'] == "first" else "Подряд"
    
    stats = db.get_event_stats(event['event_id'])
    leaderboard = db.get_event_leaderboard(event['event_id'], 5)
    
    leaders_text = "\n".join([
        f"{i+1}. @{l['username'] or 'unknown'}: {l['total_hits']} попаданий (серия: {l['current_streak']})"
        for i, l in enumerate(leaderboard)
    ]) if leaderboard else "Пока нет участников"
    
    await callback.message.edit_text(
        f"📊 Текущее событие #{event['event_id']}\n\n"
        f"🎯 Тип: {type_name} {event['target_count']} раз\n"
        f"🎰 Комбинация: {combo_text}\n\n"
        f"👥 Участников: {stats['total_participants']}\n"
        f"🎲 Попыток: {stats['total_attempts']}\n"
        f"✅ Успешных: {stats['successful_attempts']}\n\n"
        f"🏆 Топ-5:\n{leaders_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )


@dp.callback_query(F.data == "admin_stop_event")
async def stop_event(callback: CallbackQuery):
    """Остановить текущее событие"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    event = db.get_active_event()
    
    if not event:
        await callback.answer("Нет активных событий!", show_alert=True)
        return
    
    db.stop_event(event['event_id'])
    
    await callback.message.edit_text(
        f"🛑 Событие #{event['event_id']} остановлено!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
        ])
    )
    await callback.answer()


# ==================== УПРАВЛЕНИЕ ПОДАРКАМИ ====================

@dp.callback_query(F.data == "admin_gifts")
async def gifts_menu(callback: CallbackQuery):
    """Меню управления подарками"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    stats = db.get_gifts_stats()
    
    # Кастомные эмодзи
    emoji_database = '<tg-emoji emoji-id="5440824464168223114">📦</tg-emoji>'
    emoji_stats = '<tg-emoji emoji-id="4958506272551863292">📊</tg-emoji>'
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Синхронизировать с коллекцией", callback_data="gifts_sync_collection")],
        [InlineKeyboardButton(text="📥 Загрузить из файла", callback_data="gifts_load_file")],
        [InlineKeyboardButton(text="➕ Добавить вручную", callback_data="gifts_add_manual")],
        [InlineKeyboardButton(text="🗑️ Удалить подарок", callback_data="gifts_delete")],
        [InlineKeyboardButton(text="📋 Список подарков", callback_data="gifts_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    stats_text = f"{emoji_stats} <b>Статистика:</b>\n"
    stats_text += f"Всего: {stats['total']}\n"
    stats_text += f"Использовано: {stats['used']}\n"
    stats_text += f"Доступно: {stats['available']}\n\n"
    stats_text += f"<b>По уровням:</b>\n"
    for level in range(1, 5):
        ls = stats['levels'].get(level, {'total': 0, 'used': 0, 'available': 0})
        stats_text += f"  {level} lvl ({level_names[level]}): {ls['available']} доступно\n"
    
    await callback.message.edit_text(
        f"{emoji_database} <b>Управление подарками</b>\n\n"
        f"{stats_text}",
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "gifts_load_file")
async def gifts_load_from_file(callback: CallbackQuery, state: FSMContext):
    """Загрузить подарки из файла - выбор уровня"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 lvl - {level_names[1]}", callback_data="loadfile_level_1")],
        [InlineKeyboardButton(text=f"2 lvl - {level_names[2]}", callback_data="loadfile_level_2")],
        [InlineKeyboardButton(text=f"3 lvl - {level_names[3]}", callback_data="loadfile_level_3")],
        [InlineKeyboardButton(text=f"4 lvl - {level_names[4]}", callback_data="loadfile_level_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")],
    ])
    
    await callback.message.edit_text(
        "📥 <b>Загрузка из файла</b>\n\n"
        "Выбери уровень банка, в который загрузить подарки из gifts.txt:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("loadfile_level_"))
async def gifts_load_file_level(callback: CallbackQuery):
    """Загрузить подарки из файла в выбранный уровень"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    level = int(callback.data.split("_")[-1])
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    gifts = load_gifts_from_file('gifts.txt')
    
    if not gifts:
        await callback.message.edit_text(
            "❌ Файл gifts.txt не найден или пуст!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
            ])
        )
        return
    
    added = db.add_gifts_bulk(gifts, level=level)
    
    await callback.message.edit_text(
        f"✅ Загружено подарков: {added} из {len(gifts)}\n\n"
        f"Уровень: {level} ({level_names[level]})\n"
        f"(Дубликаты были пропущены)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "gifts_sync_collection")
async def gifts_sync_collection(callback: CallbackQuery, state: FSMContext):
    """Синхронизировать подарки с коллекцией - выбор уровня"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 lvl - {level_names[1]}", callback_data="sync_level_1")],
        [InlineKeyboardButton(text=f"2 lvl - {level_names[2]}", callback_data="sync_level_2")],
        [InlineKeyboardButton(text=f"3 lvl - {level_names[3]}", callback_data="sync_level_3")],
        [InlineKeyboardButton(text=f"4 lvl - {level_names[4]}", callback_data="sync_level_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")],
    ])
    
    await callback.message.edit_text(
        "🔄 <b>Синхронизация с коллекцией</b>\n\n"
        "Выбери уровень банка, в который загрузить подарки из коллекции:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("sync_level_"))
async def gifts_sync_level(callback: CallbackQuery):
    """Синхронизировать подарки с коллекцией в выбранный уровень"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    level = int(callback.data.split("_")[-1])
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    await callback.message.edit_text(
        "🔄 Синхронизация с коллекцией...\n\n"
        f"Коллекция: {COLLECTION_URL}\n"
        f"Уровень: {level} ({level_names[level]})\n\n"
        "Это может занять некоторое время...",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )
    
    # Получаем подарки из коллекции
    gifts = await scrape_collection_web()
    
    if not gifts:
        await callback.message.edit_text(
            "❌ Автоматическая синхронизация не удалась!\n\n"
            "<b>Telegram блокирует автоматический парсинг.</b>\n\n"
            "📝 <b>Используй ручной способ:</b>\n\n"
            "1️⃣ Открой коллекцию в браузере\n"
            "2️⃣ Скопируй ссылки на подарки\n"
            "3️⃣ Отправь их боту через '➕ Добавить вручную'\n\n"
            "Или используй '📥 Загрузить из файла' (gifts.txt)\n\n"
            "Подробная инструкция в файле:\n"
            "<code>КАК_ДОБАВИТЬ_ПОДАРКИ.txt</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить вручную", callback_data="gifts_add_manual")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
            ])
        )
        await callback.answer()
        return
    
    added = db.add_gifts_bulk(gifts, level=level)
    
    await callback.message.edit_text(
        f"✅ Синхронизация завершена!\n\n"
        f"Уровень: {level} ({level_names[level]})\n"
        f"Найдено в коллекции: {len(gifts)}\n"
        f"Добавлено новых: {added}\n"
        f"Дубликаты: {len(gifts) - added}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "gifts_add_manual")
async def gifts_add_manual_level(callback: CallbackQuery, state: FSMContext):
    """Выбор уровня для ручного добавления подарков"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 lvl - {level_names[1]}", callback_data="manual_level_1")],
        [InlineKeyboardButton(text=f"2 lvl - {level_names[2]}", callback_data="manual_level_2")],
        [InlineKeyboardButton(text=f"3 lvl - {level_names[3]}", callback_data="manual_level_3")],
        [InlineKeyboardButton(text=f"4 lvl - {level_names[4]}", callback_data="manual_level_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")],
    ])
    
    await callback.message.edit_text(
        "➕ <b>Добавление подарков вручную</b>\n\n"
        "Выбери уровень банка, в который добавить подарки:",
        reply_markup=keyboard
    )
    await state.set_state(AddGifts.select_level)
    await callback.answer()


@dp.callback_query(F.data.startswith("manual_level_"), AddGifts.select_level)
async def gifts_add_manual_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрос на добавление подарка вручную"""
    level = int(callback.data.split("_")[-1])
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    await state.update_data(level=level)
    
    await callback.message.edit_text(
        f"➕ <b>Добавление подарков</b>\n\n"
        f"<b>Уровень:</b> {level} ({level_names[level]})\n\n"
        "<b>Вариант 1:</b> Отправь один URL:\n"
        "<code>https://t.me/nft/GiftName-123456</code>\n\n"
        "<b>Вариант 2:</b> Отправь несколько URL (каждый с новой строки):\n"
        "<code>https://t.me/nft/Gift1\n"
        "https://t.me/nft/Gift2\n"
        "https://t.me/nft/Gift3</code>\n\n"
        "Или отправь /cancel для отмены",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_gifts")]
        ])
    )
    await state.set_state(AddGifts.enter_urls)
    await callback.answer()


@dp.message(F.text)
async def process_gift_url(message: Message, state: FSMContext):
    """Обработка URL подарка от админа"""
    if message.from_user.id != ADMIN_ID:
        return
    
    current_state = await state.get_state()
    if current_state != AddGifts.enter_urls:
        return
    
    data = await state.get_data()
    level = data.get("level", 1)
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    
    text = message.text.strip()
    lines = text.split('\n')
    
    added_count = 0
    failed_count = 0
    duplicate_count = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Добавляем https:// если нет протокола
        if not line.startswith('http'):
            line = 'https://' + line
        
        if not validate_gift_url(line):
            failed_count += 1
            continue
        
        parsed = parse_gift_url(line)
        if not parsed:
            failed_count += 1
            continue
        
        gift_name, gift_url = parsed
        success = db.add_gift(gift_name, gift_url, level=level)
        
        if success:
            added_count += 1
        else:
            duplicate_count += 1
    
    # Формируем ответ
    result_text = f"📊 <b>Результат:</b>\n\n"
    result_text += f"Уровень: {level} ({level_names[level]})\n"
    result_text += f"✅ Добавлено: {added_count}\n"
    if duplicate_count > 0:
        result_text += f"⚠️ Дубликаты: {duplicate_count}\n"
    if failed_count > 0:
        result_text += f"❌ Ошибки: {failed_count}\n"
    
    await message.reply(result_text, reply_markup=get_admin_keyboard())
    await state.clear()


@dp.callback_query(F.data == "gifts_list")
async def gifts_show_list(callback: CallbackQuery):
    """Показать список подарков"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    stats = db.get_gifts_stats()
    
    await callback.message.edit_text(
        f"📋 Статистика подарков\n\n"
        f"Всего: {stats['total']}\n"
        f"Использовано: {stats['used']}\n"
        f"Доступно: {stats['available']}\n\n"
        f"Используй /gifts для просмотра всех подарков",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )


@dp.callback_query(F.data == "gifts_delete")
async def gifts_delete_prompt(callback: CallbackQuery, state: FSMContext):
    """Выбор уровня банка для удаления подарков"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return

    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 lvl - {level_names[1]}", callback_data="delete_level_1")],
        [InlineKeyboardButton(text=f"2 lvl - {level_names[2]}", callback_data="delete_level_2")],
        [InlineKeyboardButton(text=f"3 lvl - {level_names[3]}", callback_data="delete_level_3")],
        [InlineKeyboardButton(text=f"4 lvl - {level_names[4]}", callback_data="delete_level_4")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")],
    ])

    await callback.message.edit_text(
        "🗑 <b>Удаление подарков</b>\n\n"
        "Выбери уровень банка:",
        reply_markup=keyboard
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_level_"))
async def gifts_delete_level(callback: CallbackQuery, state: FSMContext):
    """Показать доступные подарки выбранного уровня для удаления"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return

    level = int(callback.data.split("_")[-1])
    level_names = {1: "Обычный банк", 2: "Major Bank", 3: "Premium Bank", 4: "Elite Bank"}
    gifts = db.get_unused_gifts_list(level=level)
    
    if not gifts:
        await callback.message.edit_text(
            f"❌ В банке {level} уровня нет доступных подарков для удаления!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
            ])
        )
        await callback.answer()
        return
    
    # Формируем нумерованный список
    gifts_list = ""
    for i, gift in enumerate(gifts, 1):
        gifts_list += f"{i}) {gift['gift_name']}\n"
    
    await callback.message.edit_text(
        f"🗑 <b>Удаление подарков</b>\n\n"
        f"<b>Уровень:</b> {level} ({level_names[level]})\n\n"
        f"<b>Доступные подарки:</b>\n\n"
        f"{gifts_list}\n"
        f"<b>Введи номера подарков для удаления через пробел:</b>\n"
        f"<code>Пример: 1 3 5</code>\n\n"
        f"Или отправь /cancel для отмены",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_gifts")]
        ])
    )
    await state.set_state("waiting_for_gift_deletion")
    await state.update_data(gifts=gifts, level=level)
    await callback.answer()


@dp.message(F.text, lambda message: message.from_user.id == ADMIN_ID)
async def handle_gift_deletion(message: Message, state: FSMContext):
    """Обработка ввода номеров подарков для удаления"""
    current_state = await state.get_state()
    
    if current_state != "waiting_for_gift_deletion":
        return
    
    text = message.text.strip()
    
    if text == "/cancel":
        await state.clear()
        await message.answer("❌ Удаление отменено")
        return
    
    data = await state.get_data()
    gifts = data.get('gifts', [])
    
    if not gifts:
        await state.clear()
        await message.answer("❌ Ошибка: список подарков не найден")
        return
    
    # Парсим номера
    try:
        numbers = [int(num.strip()) for num in text.split()]
    except ValueError:
        await message.answer("❌ Неверный формат! Введи номера через пробел, например: <code>1 3 5</code>")
        return
    
    # Проверяем валидность номеров
    invalid_numbers = [num for num in numbers if num < 1 or num > len(gifts)]
    if invalid_numbers:
        await message.answer(f"❌ Неверные номера: {', '.join(map(str, invalid_numbers))}\nДоступные номера: 1-{len(gifts)}")
        return
    
    # Удаляем подарки
    deleted_count = 0
    deleted_names = []
    for num in numbers:
        gift = gifts[num - 1]  # индекс с 0
        success = db.delete_gift(gift['gift_id'])
        if success:
            deleted_count += 1
            deleted_names.append(gift['gift_name'])
    
    await state.clear()
    
    if deleted_count > 0:
        await message.answer(
            f"✅ Удалено подарков: {deleted_count}\n\n"
            f"Удаленные:\n" + "\n".join(f"• {name}" for name in deleted_names),
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer("❌ Не удалось удалить подарки")


@dp.callback_query(F.data.startswith("free_spin_"))
async def free_spin_choice_handler(callback: CallbackQuery):
    """Обработчик выбора одной из трех ячеек фри-спина"""
    parts = callback.data.split("_")
    session_id = int(parts[2])
    selected_index = int(parts[3])
    session = free_spin_sessions.get(session_id)

    if not session:
        await callback.answer("Выбор уже сделан или сессия истекла.", show_alert=True)
        return

    if session['user_id'] != callback.from_user.id:
        await callback.answer("Это не твой выбор!", show_alert=True)
        return

    if session['chat_id'] != callback.message.chat.id:
        await callback.answer("Выбор доступен только в исходном чате.", show_alert=True)
        return

    result = "bear" if selected_index == session['bear_index'] else "miss"
    await callback.message.edit_reply_markup(
        reply_markup=get_free_spin_keyboard(
            session_id,
            selected_index,
            result,
            session['bear_index']
        )
    )

    if result == "bear":
        username = callback.from_user.username or callback.from_user.first_name
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🐻 <b>Медведь забран!</b>\n\n"
                f"Пользователь: @{username} (ID: {callback.from_user.id})\n"
                f"Сообщение: <a href=\"{get_message_link(callback.message)}\">открыть</a>"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа о забранном медведе: {e}")

    free_spin_sessions.pop(session_id, None)
    await callback.answer()


@dp.message(F.dice)
async def dice_handler(message: Message):
    """Обработчик сообщений с игровым автоматом и всеми dice-эмодзи"""
    
    dice = message.dice
    if not dice:
        return
    
    # Игнорируем ЛЮБЫЕ пересланные dice сообщения (🎰 🎳 🎯 🎲 и т.д.)
    if message.forward_from or message.forward_from_chat:
        logger.info(f"Игнорируем пересланное dice-сообщение (эмодзи: {dice.emoji})")
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    chat_id = message.chat.id
    
    # 🎰 = основная игра (слот) — обрабатываем как раньше
    if dice.emoji == "🎰":
        value = dice.value
        
        # Проверяем, что сообщение из разрешенного чата (не из лички и не из другого чата)
        # Игровой автомат работает ТОЛЬКО в указанном ALLOWED_CHAT_ID
        if ALLOWED_CHAT_ID != 0 and chat_id != ALLOWED_CHAT_ID:
            logger.info(f"Игнорируем игровой автомат из чата: {chat_id} (разрешен только: {ALLOWED_CHAT_ID})")
            return
        
        value = dice.value
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        
        logger.info(f"Получен игровой автомат со значением: {value} от пользователя {user_id} в чате {chat_id}")
        
        # Проверяем активное событие
        event = db.get_active_event()
        
        if event:
            # Проверяем не истекло ли время события
            if event.get('end_time'):
                from datetime import datetime
                end_time = datetime.fromisoformat(event['end_time'])
                if datetime.now() > end_time:
                    # Событие истекло - завершаем его
                    await finish_event(event, message)
                    event = None  # Продолжаем как обычный режим
        
        if event:
            event_type = event['event_type']
            
            # РЕЖИМ ОЧКОВ
            if event_type == 'points':
                import json
                points_config = json.loads(event['points_config']) if event['points_config'] else {}
                earned_points = calculate_points_for_value(value, event['points_config'])
                
                # Записываем попытку
                is_target = earned_points > 0
                db.add_attempt(event['event_id'], user_id, username, value, is_target)
                
                # Запоминаем старого лидера
                old_leader = db.get_current_leader(event['event_id'])
                old_leader_id = old_leader['user_id'] if old_leader else None
                
                # Обновляем прогресс с очками
                db.update_user_progress(event['event_id'], user_id, username, value, is_target, earned_points)
                
                if earned_points > 0:
                    progress = db.get_user_progress(event['event_id'], user_id)
                    combo = SLOT_COMBINATIONS.get(value)
                    is_custom = not is_preset_combo(value)
                    custom_emoji_text = format_winning_message(combo, is_custom) if combo else "комбинация"
                    
                    await message.reply(
                        f"⭐ Выпало {custom_emoji_text}\n"
                        f"+{earned_points} баллов!\n\n"
                        f"💰 Всего баллов: {progress['points']}"
                    )
                    
                    # Проверяем смену лидера
                    new_leader = db.get_current_leader(event['event_id'])
                    if new_leader and new_leader['user_id'] != old_leader_id:
                        # Лидер изменился! Показываем топ-5
                        await show_leaderboard(event['event_id'], message)
            
            # РЕЖИМ "ПЕРВЫЙ КТО ВЫБЬЕТ N РАЗ"
            elif event_type == 'first':
                is_target = (value == event['target_value'])
                
                db.add_attempt(event['event_id'], user_id, username, value, is_target)
                db.update_user_progress(event['event_id'], user_id, username, value, is_target, 0)
                
                if is_target:
                    progress = db.get_user_progress(event['event_id'], user_id)
                    combo = SLOT_COMBINATIONS.get(value)
                    is_custom = not is_preset_combo(value)
                    custom_emoji_text = format_winning_message(combo, is_custom) if combo else "комбинация"

                    
                    if progress['total_hits'] >= event['target_count']:
                        # ПОБЕДА!
                        db.stop_event(event['event_id'], user_id, username)
                        
                        gift = db.get_random_unused_gift()
                        gift_text = ""
                        emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                        if gift:
                            db.mark_gift_as_used(gift['gift_id'], user_id, username, event['event_id'])
                            gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n\n"
                        
                        # Кастомные эмодзи
                        emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                        emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                        emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                        emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                        
                        await message.reply(
                            f"<b>{emoji_victory} ПОБЕДИТЕЛЬ СОБЫТИЯ!</b>\n\n"
                            f"<b>@{username} первым выбил {custom_emoji_text} {event['target_count']} раз!</b>\n\n"
                            f"<b>Всего попаданий: {progress['total_hits']}</b>\n"
                            f"<b>Событие завершено!</b>{gift_text}\n\n"
                            f"{emoji_bank} <b><a href=\"https://t.me/toriw9/c/6\">Банк NFT</a></b>\n"
                            f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                            f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                        )
                        
                        # Показываем финальную таблицу
                        await show_final_leaderboard(event, message)
                        
                        # Переключаемся на обычный режим
                        config['event_mode'] = False
                        save_config(config)
                    else:
                        # Промежуточное попадание - только счётчик
                        await message.reply(
                            f"🎯 Попадание! Выпало {custom_emoji_text}!\n\n"
                            f"Прогресс: {progress['total_hits']}/{event['target_count']}"
                        )
            
            # РЕЖИМ "ПОДРЯД N РАЗ"
            elif event_type == 'streak':
                is_target = (value == event['target_value'])
                
                db.add_attempt(event['event_id'], user_id, username, value, is_target)
                db.update_user_progress(event['event_id'], user_id, username, value, is_target, 0)
                
                progress = db.get_user_progress(event['event_id'], user_id)
                
                if is_target:
                    combo = SLOT_COMBINATIONS.get(value)
                    is_custom = not is_preset_combo(value)
                    custom_emoji_text = format_winning_message(combo, is_custom) if combo else "комбинация"
                    
                    if progress['current_streak'] >= event['target_count']:
                        # ПОБЕДА!
                        db.stop_event(event['event_id'], user_id, username)
                        
                        gift = db.get_random_unused_gift()
                        gift_text = ""
                        emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                        if gift:
                            db.mark_gift_as_used(gift['gift_id'], user_id, username, event['event_id'])
                            gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n\n"
                        
                        # Кастомные эмодзи
                        emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                        emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                        emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                        emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                        
                        await message.reply(
                            f"<b>{emoji_victory} ПОБЕДИТЕЛЬ СОБЫТИЯ!</b>\n\n"
                            f"<b>@{username} выбил {custom_emoji_text} {event['target_count']} раз подряд!</b>\n\n"
                            f"<b>Серия: {progress['current_streak']}</b>\n"
                            f"<b>Событие завершено!</b>{gift_text}\n\n"
                            f"{emoji_bank} <b><a href=\"https://t.me/toriw9/c/6\">Банк NFT</a></b>\n"
                            f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                            f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                        )
                        
                        # Показываем финальную таблицу
                        await show_final_leaderboard(event, message)
                        
                        # Переключаемся на обычный режим
                        config['event_mode'] = False
                        save_config(config)
                    else:
                        # Промежуточное попадание в серии - только счётчик
                        await message.reply(
                            f"🔥 Серия! Выпало {custom_emoji_text}!\n\n"
                            f"Подряд: {progress['current_streak']}/{event['target_count']}"
                        )
                else:
                    # Промах - серия сброшена
                    if progress and progress['current_streak'] > 0:
                        combo = SLOT_COMBINATIONS.get(event['target_value'])
                        is_custom = not is_preset_combo(event['target_value'])
                        combo_text = format_winning_message(combo, is_custom) if combo else "нужную комбинацию"
                        await message.reply(
                            f"💔 Серия сброшена!\n\n"
                            f"Нужна: {combo_text}\n"
                            f"Серия была: {progress['current_streak']}"
                        )
        
        # Обычный режим (если нет события)
        if not event:
            if value in (1, 22, 43):
                combo_names = {
                    1: "бара",
                    22: "винограда",
                    43: "лимона"
                }
                free_spin_session_id = generate_free_spin_session_id()
                free_spin_sessions[free_spin_session_id] = {
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'bear_index': random.randrange(3)
                }
                free_spin_text = (
                    f'<tg-emoji emoji-id="5348181139125203826">🎰</tg-emoji> '
                    f"@{username} выбил три {combo_names[value]}\n\n"
                    '<blockquote><tg-emoji emoji-id="5346209096301310711">🎁</tg-emoji> '
                    'Выпал шанс на фри спин '
                    '<tg-emoji emoji-id="5346209096301310711">🎁</tg-emoji></blockquote>\n\n'
                    "В одной из ячеек спрятан медведь"
                )
                await message.reply(
                    free_spin_text,
                    reply_markup=get_free_spin_keyboard(free_spin_session_id)
                )
                return

            if not config.get("winning_value"):
                return

            winning_value = config["winning_value"]
            
            # Проверяем, является ли winning_value списком (все джекпоты)
            if isinstance(winning_value, list):
                is_winning = value in winning_value
            else:
                is_winning = (value == winning_value)
            
            if is_winning:
                # Определяем, какая комбинация выпала
                if isinstance(winning_value, list):
                    # Для списка берем текущее значение value
                    combo = SLOT_COMBINATIONS.get(value)
                    is_custom = not is_preset_combo(value)
                else:
                    combo = SLOT_COMBINATIONS.get(winning_value)
                    is_custom = not is_preset_combo(winning_value)
                
                combo_text = format_winning_message(combo, is_custom) if combo else "выбранная комбинация"

                # Кастомные эмодзи для сообщения
                emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                
                # Особая логика только для 777 (value == 64)
                if value == 64:
                    # Выбираем случайный гифт 1 уровня НЕ помечая как использованный
                    gift = db.get_random_unused_gift(level=1)
                    gift_text = ""
                    keyboard = None
                    session_id = None
                    
                    if gift:
                        # Создаем сессию
                        session_id = generate_session_id()
                        active_gift_sessions[session_id] = {
                            'user_id': user_id,
                            'username': username,
                            'current_level': 1,
                            'current_gift': gift,
                            'claimed': False,
                            'chat_id': chat_id
                        }
                        gift_text = (
                            f"\n\n{emoji_gift} <b>Твой подарок:</b>\n"
                            f"<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n\n"
                            "Хочешь улучшить свой подарок в два раза и забрать приз с "
                            f"<a href=\"{LEVEL_BANK_LINKS[2]}\">Major Bank</a>?"
                            f"{LEVEL_BANK_CUSTOM_EMOJI[2]}\n"
                            "<blockquote>Тебе предстоит сыграть в боулинг и выбить страйк, "
                            "в противном случае приз сгорает🎳</blockquote>\n"
                        )
                        keyboard = get_claim_upgrade_keyboard(session_id, show_upgrade=True)
                    
                    result_text = (
                        f"<b>{emoji_victory} ПОБЕДА! Выпало {combo_text}</b>{gift_text}"
                        f"{emoji_bank} <b><a href=\"{LEVEL_BANK_LINKS[1]}\">Банк NFT</a></b>\n"
                        f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                        f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                    )
                    
                    await message.reply(result_text, reply_markup=keyboard)
                    return
                
                # Для всех остальных комбинаций - старая логика (сразу помечаем использованным)
                gift = db.get_random_unused_gift(level=1)
                gift_text = ""
                if gift:
                    db.mark_gift_as_used(gift['gift_id'], user_id, username, None)
                    gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n\n"
                
                result_text = (
                    f"<b>{emoji_victory} ПОБЕДА! Выпало {combo_text}</b>{gift_text}\n\n"
                    f"{emoji_bank} <b><a href=\"{LEVEL_BANK_LINKS[1]}\">Банк NFT</a></b>\n"
                    f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                    f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                )
                
                await message.reply(result_text)
        return
    
    # ОСТАЛЬНЫЕ dice-эмодзи: 🎳 🎯 🎲 = апгрейды по сессиям
    # Ищем сессию, которая ждёт бросок именно от ЭТОГО пользователя с ЭТИМ эмодзи
    if dice.emoji in ("🎳", "🎯", "🎲"):
        target_session_id = None
        for sid, sess in active_gift_sessions.items():
            if (
                sess.get('chat_id') == chat_id
                and sess.get('user_id') == user_id
                and sess.get('awaiting_dice') == dice.emoji
                and not sess.get('claimed')
            ):
                target_session_id = sid
                break
        
        if target_session_id is None:
            # Ни одна сессия не ждёт этот бросок → молча игнорируем
            return
        
        session = active_gift_sessions[target_session_id]
        # Снимаем флаг ожидания — больше этот бросок не засчитать (ловим ПЕРВЫЙ)
        session['awaiting_dice'] = None
        active_gift_sessions[target_session_id] = session
        
        dice_value = dice.value
        
        # Ждём завершения анимации стикера
        await asyncio.sleep(3.5)
        
        # Делегируем в универсальный обработчик по типу апгрейда
        await resolve_upgrade_dice_roll(target_session_id, dice.emoji, dice_value, message)


async def resolve_upgrade_dice_roll(session_id: int, emoji: str, dice_value: int, message: Message):
    """Универсальная обработка результата броска стикера пользователем"""
    session = active_gift_sessions.get(session_id)
    if not session:
        return
    
    user_id = session['user_id']
    username = session['username']
    current_level = session['current_level']
    message_link = get_message_link(message)
    message_link_text = (
        f"\nСообщение: <a href=\"{message_link}\">открыть</a>"
        if message_link else ""
    )
    
    # ========== АПГРЕЙД 1 -> 2 (боулинг 🎳) ==========
    if current_level == 1 and emoji == "🎳":
        if dice_value == 6:
            new_gift = db.get_random_unused_gift(level=2)
            if not new_gift:
                # Определяем эмодзи
                emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                
                session['claimed'] = True
                db.mark_gift_as_used(session['current_gift']['gift_id'], user_id, username, None)
                try:
                    await bot.send_message(ADMIN_ID,
                        f"🎁 <b>Гифт забран (апгрейд не удался - банк пуст)</b>\n\n"
                        f"Пользователь: @{username} (ID: {user_id})\n"
                        f"Гифт: <a href=\"{session['current_gift']['gift_url']}\">{session['current_gift']['gift_name']}</a>"
                        f"{message_link_text}")
                except Exception:
                    pass
                
                major_empty_text = (
                    "❌ К сожалению, в Major Bank закончились гифты!\n"
                    "Ты забираешь текущий приз.\n\n"
                    f"{emoji_bank} <b><a href=\"{LEVEL_BANK_LINKS[1]}\">Банк NFT</a></b>\n"
                    f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                    f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                )
                await message.reply(major_empty_text)
                active_gift_sessions.pop(session_id, None)
                return
            
            session['current_level'] = 2
            session['current_gift'] = new_gift
            session['upgrading'] = False
            active_gift_sessions[session_id] = session
            
            success_text = (
                "<b>Поздравляем! Ты выбил страйк "
                "<tg-emoji emoji-id=\"5251211295956434177\">🎳</tg-emoji></b>\n\n"
                "<tg-emoji emoji-id=\"5440824464168223114\">🎁</tg-emoji> <b>Твой подарок:</b>\n"
                f"<b><a href=\"{new_gift['gift_url']}\">{new_gift['gift_name']}</a></b>\n\n"
                "<b>Хочешь улучшить свой подарок в два раза и забрать приз с "
                f"<a href=\"{LEVEL_BANK_LINKS[3]}\">Premium Bank</a>?"
                f"{LEVEL_BANK_CUSTOM_EMOJI[3]}</b>\n"
                "<blockquote><b>Тебе предстоит попасть в центр мишени, "
                "в противном случае приз сгорает🎯</b></blockquote>"
            )
            new_keyboard = get_claim_upgrade_keyboard(session_id, show_upgrade=True)
            await message.reply(success_text, reply_markup=new_keyboard)
        else:
            session['claimed'] = True
            fail_text = (
                '<tg-emoji emoji-id="5278392881252435465">💥</tg-emoji> <b>Не повезло!</b>\n\n'
                '<tg-emoji emoji-id="6028419897711663859">🕯</tg-emoji> Приз сгорел...'
            )
            await message.reply(fail_text)
            active_gift_sessions.pop(session_id, None)
        return
    
    # ========== АПГРЕЙД 2 -> 3 (дартс 🎯) ==========
    if current_level == 2 and emoji == "🎯":
        if dice_value == 6:
            new_gift = db.get_random_unused_gift(level=3)
            if not new_gift:
                # Определяем эмодзи
                emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                
                session['claimed'] = True
                db.mark_gift_as_used(session['current_gift']['gift_id'], user_id, username, None)
                try:
                    await bot.send_message(ADMIN_ID,
                        f"🎁 <b>Гифт забран (апгрейд не удался - банк пуст)</b>\n\n"
                        f"Пользователь: @{username} (ID: {user_id})\n"
                        f"Гифт: <a href=\"{session['current_gift']['gift_url']}\">{session['current_gift']['gift_name']}</a>"
                        f"{message_link_text}")
                except Exception:
                    pass
                
                premium_empty_text = (
                    "❌ К сожалению, в Premium Bank закончились гифты!\n"
                    "Ты забираешь текущий приз.\n\n"
                    f"{emoji_bank} <b><a href=\"{LEVEL_BANK_LINKS[2]}\">Банк NFT</a></b>\n"
                    f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                    f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                )
                await message.reply(premium_empty_text)
                active_gift_sessions.pop(session_id, None)
                return
            
            session['current_level'] = 3
            session['current_gift'] = new_gift
            session['upgrading'] = False
            active_gift_sessions[session_id] = session
            
            success_text = (
                "<b>Занос! Ты ограбил нас "
                "<tg-emoji emoji-id=\"5271880418046549922\">😵</tg-emoji></b>\n\n"
                "<tg-emoji emoji-id=\"5440824464168223114\">🎁</tg-emoji> <b>Твой подарок:</b>\n"
                f"<b><a href=\"{new_gift['gift_url']}\">{new_gift['gift_name']}</a></b>\n\n"
                "<b>Хочешь улучшить свой подарок в два раза и забрать приз с "
                f"<a href=\"{LEVEL_BANK_LINKS[4]}\">Elite Bank</a>?"
                f"{LEVEL_BANK_CUSTOM_EMOJI[4]}</b>\n"
                "<blockquote><b>Тебе предстоит выбрать число, которое должно выпасть на твоем кубике, "
                "в противном случае приз сгорает🎲</b></blockquote>"
            )
            new_keyboard = get_claim_upgrade_keyboard(session_id, show_upgrade=True)
            await message.reply(success_text, reply_markup=new_keyboard)
        else:
            session['claimed'] = True
            fail_text = (
                '<tg-emoji emoji-id="5278392881252435465">💥</tg-emoji> <b>Не повезло!</b>\n\n'
                '<tg-emoji emoji-id="6028419897711663859">🕯</tg-emoji> Приз сгорел...'
            )
            await message.reply(fail_text)
            active_gift_sessions.pop(session_id, None)
        return
    
    # ========== АПГРЕЙД 3 -> 4 (кубик 🎲) ==========
    if current_level == 3 and emoji == "🎲":
        expected_number = session.get('expected_dice_number')
        if expected_number is None:
            # Не выбрано число — такое не должно происходить, но на всякий случай
            await message.reply("❌ Сначала нужно было выбрать число! Сессия сброшена.")
            active_gift_sessions.pop(session_id, None)
            return
        
        if dice_value == expected_number:
            new_gift = db.get_random_unused_gift(level=4)
            if not new_gift:
                # Определяем эмодзи
                emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
                emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
                emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
                
                session['claimed'] = True
                db.mark_gift_as_used(session['current_gift']['gift_id'], user_id, username, None)
                try:
                    await bot.send_message(ADMIN_ID,
                        f"🎁 <b>Гифт забран!</b>\n\n"
                        f"Пользователь: @{username} (ID: {user_id})\n"
                        f"Уровень: 3 (Elite Bank пуст)\n"
                        f"Гифт: <a href=\"{session['current_gift']['gift_url']}\">{session['current_gift']['gift_name']}</a>"
                        f"{message_link_text}")
                except Exception:
                    pass
                
                elite_empty_text = (
                    "❌ В Elite Bank закончились гифты!\n"
                    "Но ты все равно выиграл - забираешь приз с Premium Bank!\n\n"
                    f"{emoji_bank} <b><a href=\"{LEVEL_BANK_LINKS[3]}\">Банк NFT</a></b>\n"
                    f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                    f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
                )
                await message.reply(elite_empty_text)
                active_gift_sessions.pop(session_id, None)
                return
            
            db.mark_gift_as_used(new_gift['gift_id'], user_id, username, None)
            session['claimed'] = True
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"👑 <b>МАКСИМАЛЬНЫЙ ПРИЗ!</b>\n\n"
                    f"Пользователь: @{username} (ID: {user_id})\n"
                    f"Уровень: 4 (Elite Bank - МАКСИМУМ)\n"
                    f"Гифт: <a href=\"{new_gift['gift_url']}\">{new_gift['gift_name']}</a>"
                    f"{message_link_text}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить админу: {e}")
            
            # Определяем эмодзи
            emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
            emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
            emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
            emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
            
            final_text = (
                "<b><tg-emoji emoji-id=\"5857435656225038831\">👏</tg-emoji> "
                "Наши аплодисменты! Ты самый главный лудик этого чата "
                "<tg-emoji emoji-id=\"5390858914885568318\">👑</tg-emoji></b>\n\n"
                f"{emoji_gift} <b>Твой подарок:</b>\n"
                f"<b><a href=\"{new_gift['gift_url']}\">{new_gift['gift_name']}</a></b>\n\n"
                f"<b>Твой приз уже в пути {FINAL_PRIZE_CUSTOM_EMOJI}</b>\n\n"
                f"{LEVEL_BANK_CUSTOM_EMOJI[4]} <b><a href=\"{LEVEL_BANK_LINKS[4]}\">Elite Bank</a></b>\n"
                f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
            )
            await message.reply(final_text, reply_markup=None)
            active_gift_sessions.pop(session_id, None)
        else:
            session['claimed'] = True
            fail_text = (
                '<tg-emoji emoji-id="5278392881252435465">💥</tg-emoji> <b>Не повезло!</b>\n\n'
                '<tg-emoji emoji-id="6028419897711663859">🕯</tg-emoji> Приз сгорел...'
            )
            await message.reply(fail_text)
            active_gift_sessions.pop(session_id, None)
        return


# ==================== ОБРАБОТЧИКИ КНОПОК ГИФТОВ И АПГРЕЙДОВ ====================

@dp.callback_query(F.data.startswith("claim_gift_"))
async def claim_gift_handler(callback: CallbackQuery):
    """Обработчик кнопки 'Забрать гифт'"""
    session_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    
    session = active_gift_sessions.get(session_id)
    if not session:
        await callback.answer("❌ Сессия истекла или не найдена!", show_alert=True)
        return
    
    if session['user_id'] != user_id:
        await callback.answer("❌ Это не твой гифт!", show_alert=True)
        return
    
    if session.get('claimed', False):
        await callback.answer("❌ Гифт уже забран!", show_alert=True)
        return
    
    if session.get('upgrading', False):
        await callback.answer("❌ Апгрейд уже в процессе, забрать нельзя!", show_alert=True)
        return
    
    # Сразу блокируем обе кнопки, чтобы не было двойных нажатий
    session['claimed'] = True
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    
    current_gift = session['current_gift']
    current_level = session['current_level']
    
    # Помечаем гифт как использованный в БД
    db.mark_gift_as_used(current_gift['gift_id'], user_id, username, None)
    
    # Уведомляем админа в личку
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🎁 <b>Гифт забран!</b>\n\n"
            f"Пользователь: @{username} (ID: {user_id})\n"
            f"Уровень: {current_level} ({LEVEL_BANK_NAMES[current_level]})\n"
            f"Гифт: <a href=\"{current_gift['gift_url']}\">{current_gift['gift_name']}</a>\n"
            f"Сообщение: <a href=\"{get_message_link(callback.message)}\">открыть</a>"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}")
    
    emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
    emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
    emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
    emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
    emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
    
    final_text = (
        f"<b>{emoji_victory} ПОБЕДА! Приз забран</b>\n\n"
        f"{emoji_gift} <b>Твой подарок:</b>\n"
        f"<a href=\"{current_gift['gift_url']}\">{current_gift['gift_name']}</a>\n\n"
        f"<b>Твой приз уже в пути {FINAL_PRIZE_CUSTOM_EMOJI}</b>\n"
        '<blockquote>Админ уведомлен 📨</blockquote>\n'
        '<tg-emoji emoji-id="5251324597193709038">📨</tg-emoji>\n\n'
        f"{LEVEL_BANK_CUSTOM_EMOJI.get(current_level, emoji_bank)} <b><a href=\"{LEVEL_BANK_LINKS.get(current_level, LEVEL_BANK_LINKS[1])}\">{LEVEL_BANK_NAMES.get(current_level, 'Банк NFT')}</a></b>\n"
        f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
        f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
    )
    
    await callback.message.edit_text(final_text, reply_markup=None)
    await callback.answer("✅ Гифт забран! Админ уведомлен.", show_alert=True)
    active_gift_sessions.pop(session_id, None)


@dp.callback_query(F.data.startswith("upgrade_gift_"))
async def upgrade_gift_handler(callback: CallbackQuery):
    """Обработчик кнопки 'Апгрейд'"""
    session_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    
    session = active_gift_sessions.get(session_id)
    if not session:
        await callback.answer("❌ Сессия истекла или не найдена!", show_alert=True)
        return
    
    if session['user_id'] != user_id:
        await callback.answer("❌ Это не твой гифт!", show_alert=True)
        return
    
    if session.get('claimed', False):
        await callback.answer("❌ Гифт уже забран, апгрейд недоступен!", show_alert=True)
        return
    
    if session.get('upgrading', False):
        await callback.answer("❌ Апгрейд уже в процессе!", show_alert=True)
        return
    
    # Блокируем повторную обработку через состояние сессии, не изменяя исходное сообщение
    session['upgrading'] = True
    
    current_level = session['current_level']
    chat_id = session['chat_id']
    
    # Апгрейд 1 -> 2: Боулинг 🎳
    if current_level == 1:
        upgrade_text = (
            f"@{username}, кинь эмодзи 🎳"
        )
        
        await callback.message.answer(upgrade_text)
        await callback.answer()
        
        # Устанавливаем флаг ожидания броска от пользователя
        session['awaiting_dice'] = "🎳"
        active_gift_sessions[session_id] = session
    
    # Апгрейд 2 -> 3: Дартс 🎯
    elif current_level == 2:
        upgrade_text = (
            f"@{username}, кинь эмодзи 🎯"
        )
        
        await callback.message.answer(upgrade_text)
        await callback.answer()
        
        # Устанавливаем флаг ожидания броска от пользователя
        session['awaiting_dice'] = "🎯"
        active_gift_sessions[session_id] = session
    
    # Апгрейд 3 -> 4: Кубик 🎲 с выбором числа
    elif current_level == 3:
        upgrade_text = (
            "Выбери число от 1 до 6"
        )
        
        number_keyboard = get_dice_number_keyboard(session_id)
        session['upgrading'] = False  # Разблокируем, т.к. дальше нужно ждать выбора числа
        await callback.message.answer(upgrade_text, reply_markup=number_keyboard)
        active_gift_sessions[session_id] = session
        await callback.answer()
    
    # 4 уровня - финальный, апгрейда больше нет
    elif current_level == 4:
        await callback.answer("❌ Это финальный уровень, апгрейд больше нет!", show_alert=True)


@dp.callback_query(F.data.startswith("picknum_"))
async def pick_dice_number_handler(callback: CallbackQuery):
    """Обработчик выбора числа для кубика (апгрейд 3->4)"""
    parts = callback.data.split("_")
    session_id = int(parts[1])
    chosen_number = int(parts[2])
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    
    session = active_gift_sessions.get(session_id)
    if not session:
        await callback.answer("❌ Сессия истекла!", show_alert=True)
        return
    
    if session['user_id'] != user_id:
        await callback.answer("❌ Это не твой гифт!", show_alert=True)
        return
    
    if session.get('claimed', False):
        await callback.answer("❌ Гифт уже забран!", show_alert=True)
        return
    
    if session.get('upgrading', False):
        await callback.answer("❌ Кинутый кубик уже в полете!", show_alert=True)
        return
    
    # Блокируем, чтобы не было двойного выбора
    session['upgrading'] = True
    active_gift_sessions[session_id] = session
    # Сохраняем выбранное число и устанавливаем ожидание броска от пользователя
    session['expected_dice_number'] = chosen_number
    session['awaiting_dice'] = "🎲"
    active_gift_sessions[session_id] = session
    
    # Сообщаем пользователю, что он выбрал число
    chosen_text = (
        f"🎲 <b>@{username} выбрал цифру: {chosen_number}</b>\n\n"
        "Теперь кинь кубик 🎲 и проверь, выпадет ли загаданное число!"
    )
    await callback.message.answer(chosen_text)
    await callback.answer()


async def show_leaderboard(event_id: int, message: Message):
    """Показать топ-5 лидеров"""
    leaderboard = db.get_event_leaderboard(event_id, limit=5, order_by='points')
    
    if not leaderboard:
        return
    
    text = "🏆 <b>ТОП-5 ЛИДЕРОВ</b> 🏆\n\n"
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, leader in enumerate(leaderboard):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        username = leader['username'] or 'неизвестно'
        text += f"{medal} @{username}: {leader['points']} баллов\n"
    
    await message.answer(text)


async def show_final_leaderboard(event: dict, message: Message):
    """Показать финальную таблицу результатов"""
    leaderboard = db.get_event_leaderboard(event['event_id'], limit=10, order_by='points' if event['event_type'] == 'points' else 'total_hits')
    
    if not leaderboard:
        return
    
    text = "🎊 <b>ФИНАЛЬНЫЕ РЕЗУЛЬТАТЫ</b> 🎊\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, leader in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"{i+1}."
        username = leader['username'] or 'неизвестно'
        
        if event['event_type'] == 'points':
            text += f"{medal} @{username}: {leader['points']} баллов\n"
        else:
            text += f"{medal} @{username}: {leader['total_hits']} попаданий (серия: {leader['current_streak']})\n"
    
    await message.answer(text)


async def finish_event(event: dict, message: Message):
    """Завершить событие по истечении времени"""
    db.stop_event(event['event_id'])
    
    # Определяем победителя
    if event['event_type'] == 'points':
        winner = db.get_current_leader(event['event_id'])
        if winner:
            # Кастомные эмодзи
            emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
            emoji_bank = '<tg-emoji emoji-id="5308031922281154159">🏦</tg-emoji>'
            emoji_ludka = '<tg-emoji emoji-id="5307728856503844559">⭐</tg-emoji>'
            emoji_stars = '<tg-emoji emoji-id="5307707218458605938">💎</tg-emoji>'
            
            # Выдаем подарок победителю
            gift = db.get_random_unused_gift()
            gift_text = ""
            emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
            if gift:
                db.mark_gift_as_used(gift['gift_id'], winner['user_id'], winner['username'], event['event_id'])
                gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n\n"
            
            await message.answer(
                f"<b>⏰ Время события истекло!</b>\n\n"
                f"<b>{emoji_victory} Победитель: @{winner['username']}</b>\n"
                f"<b>💰 Баллов: {winner['points']}</b>{gift_text}\n\n"
                f"{emoji_bank} <b><a href=\"https://t.me/toriw9/c/6\">Банк NFT</a></b>\n"
                f"{emoji_ludka} <b><a href=\"https://t.me/ludka1star\">Лудка за 1 звезду</a></b>\n"
                f"{emoji_stars} <b><a href=\"https://t.me/toristarsbot\">Дешевые звезды</a></b>"
            )
            
            # Показываем финальную таблицу
            await show_final_leaderboard(event, message)
    else:
        await message.answer("⏰ <b>Время события истекло!</b>\n\nСобытие завершено.")
    
    # Переключаемся на обычный режим
    config['event_mode'] = False
    save_config(config)


async def main():
    """Запуск бота"""
    logger.info("Бот запущен!")
    logger.info(f"Admin ID: {ADMIN_ID}")
    
    # Запускаем polling
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())

