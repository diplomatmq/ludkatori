"""
Обработчики для режима очков в событиях
"""

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import json


# Обработчики для настройки баллов
async def handle_points_777(callback: CallbackQuery, state: FSMContext, CreateEvent):
    """Установка баллов за 777"""
    points = int(callback.data.split("_")[2])
    await state.update_data(points_777=points)
    
    await callback.message.edit_text(
        f"⭐ <b>Режим очков</b>\n\n"
        f"7️⃣ 7️⃣ 7️⃣ = {points} баллов ✅\n\n"
        f"Сколько баллов за 🎰 🎰 🎰 (BAR)?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="5", callback_data="pts_bar_5"),
             InlineKeyboardButton(text="10", callback_data="pts_bar_10"),
             InlineKeyboardButton(text="15", callback_data="pts_bar_15")],
            [InlineKeyboardButton(text="25", callback_data="pts_bar_25"),
             InlineKeyboardButton(text="50", callback_data="pts_bar_50")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )
    await state.set_state(CreateEvent.points_bar)
    await callback.answer()


async def handle_points_bar(callback: CallbackQuery, state: FSMContext, CreateEvent):
    """Установка баллов за BAR"""
    points = int(callback.data.split("_")[2])
    await state.update_data(points_bar=points)
    
    data = await state.get_data()
    
    await callback.message.edit_text(
        f"⭐ <b>Режим очков</b>\n\n"
        f"7️⃣ 7️⃣ 7️⃣ = {data['points_777']} баллов ✅\n"
        f"🎰 🎰 🎰 = {points} баллов ✅\n\n"
        f"Сколько баллов за 🍇 🍇 🍇 (Виноград)?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="3", callback_data="pts_grape_3"),
             InlineKeyboardButton(text="5", callback_data="pts_grape_5"),
             InlineKeyboardButton(text="10", callback_data="pts_grape_10")],
            [InlineKeyboardButton(text="15", callback_data="pts_grape_15"),
             InlineKeyboardButton(text="20", callback_data="pts_grape_20")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )
    await state.set_state(CreateEvent.points_grape)
    await callback.answer()


async def handle_points_grape(callback: CallbackQuery, state: FSMContext, CreateEvent):
    """Установка баллов за виноград"""
    points = int(callback.data.split("_")[2])
    await state.update_data(points_grape=points)
    
    data = await state.get_data()
    
    await callback.message.edit_text(
        f"⭐ <b>Режим очков</b>\n\n"
        f"7️⃣ 7️⃣ 7️⃣ = {data['points_777']} баллов ✅\n"
        f"🎰 🎰 🎰 = {data['points_bar']} баллов ✅\n"
        f"🍇 🍇 🍇 = {points} баллов ✅\n\n"
        f"Сколько баллов за 🍋 🍋 🍋 (Лимон)?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="3", callback_data="pts_lemon_3"),
             InlineKeyboardButton(text="5", callback_data="pts_lemon_5"),
             InlineKeyboardButton(text="10", callback_data="pts_lemon_10")],
            [InlineKeyboardButton(text="15", callback_data="pts_lemon_15"),
             InlineKeyboardButton(text="20", callback_data="pts_lemon_20")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )
    await state.set_state(CreateEvent.points_lemon)
    await callback.answer()


async def handle_points_lemon(callback: CallbackQuery, state: FSMContext, CreateEvent):
    """Установка баллов за лимон"""
    points = int(callback.data.split("_")[2])
    await state.update_data(points_lemon=points)
    
    data = await state.get_data()
    
    await callback.message.edit_text(
        f"⭐ <b>Режим очков</b>\n\n"
        f"7️⃣ 7️⃣ 7️⃣ = {data['points_777']} баллов ✅\n"
        f"🎰 🎰 🎰 = {data['points_bar']} баллов ✅\n"
        f"🍇 🍇 🍇 = {data['points_grape']} баллов ✅\n"
        f"🍋 🍋 🍋 = {points} баллов ✅\n\n"
        f"Выбери длительность события:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="30 минут", callback_data="dur_30"),
             InlineKeyboardButton(text="1 час", callback_data="dur_60")],
            [InlineKeyboardButton(text="2 часа", callback_data="dur_120"),
             InlineKeyboardButton(text="6 часов", callback_data="dur_360")],
            [InlineKeyboardButton(text="12 часов", callback_data="dur_720"),
             InlineKeyboardButton(text="24 часа", callback_data="dur_1440")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")]
        ])
    )
    await state.set_state(CreateEvent.duration)
    await callback.answer()


async def handle_duration(callback: CallbackQuery, state: FSMContext, CreateEvent, db):
    """Установка длительности и создание события"""
    duration_minutes = int(callback.data.split("_")[1])
    
    data = await state.get_data()
    
    # Создаем конфиг баллов
    points_config = json.dumps({
        "64": data['points_777'],   # 777
        "1": data['points_bar'],    # BAR
        "22": data['points_grape'], # Виноград
        "43": data['points_lemon']  # Лимон
    })
    
    # Вычисляем время окончания
    end_time = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
    
    # Создаем событие (target_value=0, target_count=0 для режима очков)
    event_id = db.create_event("points", 0, 0, end_time, points_config)
    
    duration_text = f"{duration_minutes} минут" if duration_minutes < 60 else f"{duration_minutes // 60} час(ов)"
    
    await callback.message.edit_text(
        f"✅ <b>Событие создано!</b>\n\n"
        f"🎯 Режим: Очки\n"
        f"⏰ Длительность: {duration_text}\n"
        f"🆔 ID события: {event_id}\n\n"
        f"<b>Баллы за комбинации:</b>\n"
        f"7️⃣ 7️⃣ 7️⃣ = {data['points_777']} баллов\n"
        f"🎰 🎰 🎰 = {data['points_bar']} баллов\n"
        f"🍇 🍇 🍇 = {data['points_grape']} баллов\n"
        f"🍋 🍋 🍋 = {data['points_lemon']} баллов\n\n"
        f"Событие запущено! Пользователи могут участвовать.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin_menu")]
        ])
    )
    
    await state.clear()
    await callback.answer()


def calculate_points_for_value(value: int, points_config_json: str) -> int:
    """Вычислить баллы за выпавшее значение"""
    try:
        points_config = json.loads(points_config_json)
        return points_config.get(str(value), 0)
    except:
        return 0
