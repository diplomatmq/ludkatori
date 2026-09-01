import asyncio
import logging
import os
import json
import sqlite3
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
db = Database()


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
    
    # Получаем список подарков
    with sqlite3.connect(db.db_file) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT gift_name, gift_url, is_used, used_by_username 
            FROM gifts 
            ORDER BY is_used ASC, gift_name ASC 
            LIMIT 100
        ''')
        gifts = [dict(row) for row in cursor.fetchall()]
    
    if not gifts:
        await message.answer("📦 База подарков пуста!\n\nДобавь подарки через /admin → 🎁 Управление подарками")
        return
    
    # Кастомные эмодзи
    emoji_database = '<tg-emoji emoji-id="5440824464168223114">📦</tg-emoji>'
    emoji_stats = '<tg-emoji emoji-id="4958506272551863292">📊</tg-emoji>'
    emoji_available = '<tg-emoji emoji-id="5206607081334906820">✅</tg-emoji>'
    emoji_used = '<tg-emoji emoji-id="5409008750893734809">❌</tg-emoji>'
    
    # Формируем сообщение
    text = f"{emoji_database} <b>База подарков</b>\n\n"
    text += f"{emoji_stats} <b>Статистика:</b>\n"
    text += f"Доступно: {stats['available']}\n"
    
    if stats['available'] > 0:
        text += f"{emoji_available} <b>Доступные подарки:</b>\n"
        
        # Формируем список доступных подарков для цитирования
        available_list = ""
        for gift in gifts:
            if not gift['is_used']:
                available_list += f"• <a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>\n"
        
        # Оборачиваем в expandable blockquote (сворачиваемая цитата)
        text += f"<blockquote expandable>{available_list}</blockquote>\n"
    
    if stats['used'] > 0:
        text += f"\n{emoji_used} <b>Выбитые подарки:</b>\n"
        
        # Формируем список использованных подарков для цитирования
        used_list = ""
        for gift in gifts:
            if gift['is_used']:
                username = gift['used_by_username'] or 'неизвестно'
                used_list += f"• {gift['gift_name']} → @{username}\n"
        
        # Оборачиваем в expandable blockquote (сворачиваемая цитата)
        text += f"<blockquote expandable>{used_list}</blockquote>"
    
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
        [InlineKeyboardButton(text="📋 Список подарков", callback_data="gifts_list")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
    ])
    
    await callback.message.edit_text(
        f"{emoji_database} <b>Управление подарками</b>\n\n"
        f"{emoji_stats} <b>Статистика:</b>\n"
        f"Всего: {stats['total']}\n"
        f"Использовано: {stats['used']}\n"
        f"Доступно: {stats['available']}",
        reply_markup=keyboard
    )


@dp.callback_query(F.data == "gifts_load_file")
async def gifts_load_from_file(callback: CallbackQuery):
    """Загрузить подарки из файла"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    gifts = load_gifts_from_file('gifts.txt')
    
    if not gifts:
        await callback.answer("Файл gifts.txt не найден или пуст!", show_alert=True)
        return
    
    added = db.add_gifts_bulk(gifts)
    
    await callback.message.edit_text(
        f"✅ Загружено подарков: {added} из {len(gifts)}\n\n"
        f"(Дубликаты были пропущены)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "gifts_sync_collection")
async def gifts_sync_collection(callback: CallbackQuery):
    """Синхронизировать подарки с коллекцией"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🔄 Синхронизация с коллекцией...\n\n"
        f"Коллекция: {COLLECTION_URL}\n\n"
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
    
    added = db.add_gifts_bulk(gifts)
    
    await callback.message.edit_text(
        f"✅ Синхронизация завершена!\n\n"
        f"Найдено в коллекции: {len(gifts)}\n"
        f"Добавлено новых: {added}\n"
        f"Дубликаты: {len(gifts) - added}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_gifts")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "gifts_add_manual")
async def gifts_add_manual_prompt(callback: CallbackQuery, state: FSMContext):
    """Запрос на добавление подарка вручную"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ У вас нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "➕ Добавление подарков\n\n"
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
    await state.set_state("waiting_for_gifts")
    await callback.answer()


@dp.message(F.text.startswith("https://t.me/nft/"))
async def process_gift_url(message: Message, state: FSMContext):
    """Обработка URL подарка от админа"""
    if message.from_user.id != ADMIN_ID:
        return
    
    text = message.text.strip()
    lines = text.split('\n')
    
    added_count = 0
    failed_count = 0
    duplicate_count = 0
    
    for line in lines:
        line = line.strip()
        if not line or not line.startswith('http'):
            continue
        
        if not validate_gift_url(line):
            failed_count += 1
            continue
        
        parsed = parse_gift_url(line)
        if not parsed:
            failed_count += 1
            continue
        
        gift_name, gift_url = parsed
        success = db.add_gift(gift_name, gift_url)
        
        if success:
            added_count += 1
        else:
            duplicate_count += 1
    
    # Формируем ответ
    result_text = f"📊 Результат:\n\n"
    result_text += f"✅ Добавлено: {added_count}\n"
    if duplicate_count > 0:
        result_text += f"⚠️ Дубликаты: {duplicate_count}\n"
    if failed_count > 0:
        result_text += f"❌ Ошибки: {failed_count}\n"
    
    await message.reply(result_text)
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


@dp.message(F.dice)
async def dice_handler(message: Message):
    """Обработчик сообщений с игровым автоматом"""
    
    dice = message.dice
    
    if dice and dice.emoji == "🎰":
        chat_id = message.chat.id
        
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
                            gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>"
                        
                        # Кастомные эмодзи
                        emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                        emoji_link = '<tg-emoji emoji-id="5415758949129404605">🔗</tg-emoji>'
                        emoji_bank = '<tg-emoji emoji-id="5307728856503844559">🏦</tg-emoji>'
                        
                        await message.reply(
                            f"{emoji_victory} <b>ПОБЕДИТЕЛЬ СОБЫТИЯ!</b>\n\n"
                            f"@{username} первым выбил {custom_emoji_text} {event['target_count']} раз!\n\n"
                            f"Всего попаданий: {progress['total_hits']}\n"
                            f"Событие завершено!{gift_text}\n\n"
                            f"{emoji_bank} <a href=\"https://t.me/toriw9/c/6\">Банк NFT</a>\n"
                            f"{emoji_link} <a href=\"https://t.me/torionnft\">Наш канал</a>\n"
                            f"{emoji_link} <a href=\"https://t.me/toristarsbot\">Дешевые звезды</a>"
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
                            gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>"
                        
                        # Кастомные эмодзи
                        emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                        emoji_link = '<tg-emoji emoji-id="5415758949129404605">🔗</tg-emoji>'
                        emoji_bank = '<tg-emoji emoji-id="5307728856503844559">🏦</tg-emoji>'
                        
                        await message.reply(
                            f"{emoji_victory} <b>ПОБЕДИТЕЛЬ СОБЫТИЯ!</b>\n\n"
                            f"@{username} выбил {custom_emoji_text} {event['target_count']} раз подряд!\n\n"
                            f"Серия: {progress['current_streak']}\n"
                            f"Событие завершено!{gift_text}\n\n"
                            f"{emoji_bank} <a href=\"https://t.me/toriw9/c/6\">Банк NFT</a>\n"
                            f"{emoji_link} <a href=\"https://t.me/torionnft\">Наш канал</a>\n"
                            f"{emoji_link} <a href=\"https://t.me/toristarsbot\">Дешевые звезды</a>"
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
        if not event and config.get("winning_value"):
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
                
                gift = db.get_random_unused_gift()
                gift_text = ""
                emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
                if gift:
                    db.mark_gift_as_used(gift['gift_id'], user_id, username, None)
                    gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>"
                
                # Кастомные эмодзи для сообщения
                emoji_victory = '<tg-emoji emoji-id="5271803701340706125">🎉</tg-emoji>'
                emoji_link = '<tg-emoji emoji-id="5415758949129404605">🔗</tg-emoji>'
                emoji_bank = '<tg-emoji emoji-id="5307728856503844559">🏦</tg-emoji>'
                
                result_text = (
                    f"{emoji_victory} <b>ПОБЕДА! Выпало</b> {combo_text}{gift_text}\n\n"
                    f"{emoji_bank} <a href=\"https://t.me/toriw9/c/6\">Банк NFT</a>\n"
                    f"{emoji_link} <a href=\"https://t.me/torionnft\">Наш канал</a>\n"
                    f"{emoji_link} <a href=\"https://t.me/toristarsbot\">Дешевые звезды</a>"
                )
                
                await message.reply(result_text)


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
            emoji_link = '<tg-emoji emoji-id="5415758949129404605">🔗</tg-emoji>'
            emoji_bank = '<tg-emoji emoji-id="5307728856503844559">🏦</tg-emoji>'
            
            # Выдаем подарок победителю
            gift = db.get_random_unused_gift()
            gift_text = ""
            emoji_gift = '<tg-emoji emoji-id="5440824464168223114">🎁</tg-emoji>'
            if gift:
                db.mark_gift_as_used(gift['gift_id'], winner['user_id'], winner['username'], event['event_id'])
                gift_text = f"\n\n{emoji_gift} <b>Твой подарок:</b>\n<a href=\"{gift['gift_url']}\">{gift['gift_name']}</a>"
            
            await message.answer(
                f"⏰ <b>Время события истекло!</b>\n\n"
                f"{emoji_victory} <b>Победитель:</b> @{winner['username']}\n"
                f"💰 Баллов: {winner['points']}{gift_text}\n\n"
                f"{emoji_bank} <a href=\"https://t.me/toriw9/c/6\">Банк NFT</a>\n"
                f"{emoji_link} <a href=\"https://t.me/torionnft\">Наш канал</a>\n"
                f"{emoji_link} <a href=\"https://t.me/toristarsbot\">Дешевые звезды</a>"
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

