# Полная таблица соответствия значений dice и символов на колёсах
# Источник: https://gist.github.com/SevaShpun/8cff6d045caa1c763935510eaac23df6

SLOT_COMBINATIONS = {
    1: ("bar", "bar", "bar"),
    2: ("grape", "bar", "bar"),
    3: ("lemon", "bar", "bar"),
    4: ("seven", "bar", "bar"),
    5: ("bar", "grape", "bar"),
    6: ("grape", "grape", "bar"),
    7: ("lemon", "grape", "bar"),
    8: ("seven", "grape", "bar"),
    9: ("bar", "lemon", "bar"),
    10: ("grape", "lemon", "bar"),
    11: ("lemon", "lemon", "bar"),
    12: ("seven", "lemon", "bar"),
    13: ("bar", "seven", "bar"),
    14: ("grape", "seven", "bar"),
    15: ("lemon", "seven", "bar"),
    16: ("seven", "seven", "bar"),
    17: ("bar", "bar", "grape"),
    18: ("grape", "bar", "grape"),
    19: ("lemon", "bar", "grape"),
    20: ("seven", "bar", "grape"),
    21: ("bar", "grape", "grape"),
    22: ("grape", "grape", "grape"),
    23: ("lemon", "grape", "grape"),
    24: ("seven", "grape", "grape"),
    25: ("bar", "lemon", "grape"),
    26: ("grape", "lemon", "grape"),
    27: ("lemon", "lemon", "grape"),
    28: ("seven", "lemon", "grape"),
    29: ("bar", "seven", "grape"),
    30: ("grape", "seven", "grape"),
    31: ("lemon", "seven", "grape"),
    32: ("seven", "seven", "grape"),
    33: ("bar", "bar", "lemon"),
    34: ("grape", "bar", "lemon"),
    35: ("lemon", "bar", "lemon"),
    36: ("seven", "bar", "lemon"),
    37: ("bar", "grape", "lemon"),
    38: ("grape", "grape", "lemon"),
    39: ("lemon", "grape", "lemon"),
    40: ("seven", "grape", "lemon"),
    41: ("bar", "lemon", "lemon"),
    42: ("grape", "lemon", "lemon"),
    43: ("lemon", "lemon", "lemon"),
    44: ("seven", "lemon", "lemon"),
    45: ("bar", "seven", "lemon"),
    46: ("grape", "seven", "lemon"),
    47: ("lemon", "seven", "lemon"),
    48: ("seven", "seven", "lemon"),
    49: ("bar", "bar", "seven"),
    50: ("grape", "bar", "seven"),
    51: ("lemon", "bar", "seven"),
    52: ("seven", "bar", "seven"),
    53: ("bar", "grape", "seven"),
    54: ("grape", "grape", "seven"),
    55: ("lemon", "grape", "seven"),
    56: ("seven", "grape", "seven"),
    57: ("bar", "lemon", "seven"),
    58: ("grape", "lemon", "seven"),
    59: ("lemon", "lemon", "seven"),
    60: ("seven", "lemon", "seven"),
    61: ("bar", "seven", "seven"),
    62: ("grape", "seven", "seven"),
    63: ("lemon", "seven", "seven"),
    64: ("seven", "seven", "seven"),
}

# Словарь для отображения символов
SYMBOL_EMOJI = {
    "bar": "🎰",
    "grape": "🍇",
    "lemon": "🍋",
    "seven": "7️⃣"
}

# Доступные символы для выбора
SYMBOLS = ["bar", "grape", "lemon", "seven"]
SYMBOL_NAMES = {
    "bar": "BAR 🎰",
    "grape": "Виноград 🍇",
    "lemon": "Лимон 🍋",
    "seven": "Семёрка 7️⃣"
}


def find_value_by_combination(first, second, third):
    """Найти значение dice по комбинации символов"""
    for value, combo in SLOT_COMBINATIONS.items():
        if combo == (first, second, third):
            return value
    return None


def format_combination(combo):
    """Форматировать комбинацию для отображения"""
    return " ".join([SYMBOL_EMOJI[symbol] for symbol in combo])


# Кастомные эмодзи ID для каждого символа
CUSTOM_EMOJI_IDS = {
    "seven": "5913646886819991524",  # 777
    "lemon": "5915560994830028266",  # Лимон
    "grape": "5915967083987864750",  # Виноград
    "bar": "5915589848420322417",     # BAR
    "custom": "5380082455392845502"   # Кастомная комбинация
}


def format_custom_emoji(emoji_id: str) -> str:
    """Форматировать кастомный эмодзи для HTML"""
    return f'<tg-emoji emoji-id="{emoji_id}">🎰</tg-emoji>'


def format_winning_message(combo: tuple, is_custom: bool = False) -> str:
    """
    Форматировать сообщение о победе с кастомными эмодзи
    
    Args:
        combo: Кортеж символов (first, second, third)
        is_custom: Флаг кастомной комбинации
    
    Returns:
        HTML-строка с кастомными эмодзи
    """
    if is_custom:
        # Три одинаковых кастомных эмодзи
        emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["custom"])
        return f"{emoji} {emoji} {emoji}"
    
    # Проверяем на тройки одинаковых
    if combo[0] == combo[1] == combo[2]:
        symbol = combo[0]
        
        if symbol == "seven":
            # Три семёрки
            emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["seven"])
            return f"{emoji} {emoji} {emoji}"
        
        elif symbol == "lemon":
            # Три лимона
            emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["lemon"])
            return f"{emoji} {emoji} {emoji}"
        
        elif symbol == "grape":
            # Три винограда
            emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["grape"])
            return f"{emoji} {emoji} {emoji}"
        
        elif symbol == "bar":
            # Три BAR
            emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["bar"])
            return f"{emoji} {emoji} {emoji}"
    
    # Для не-тройных комбинаций используем кастомный эмодзи
    emoji = format_custom_emoji(CUSTOM_EMOJI_IDS["custom"])
    return f"{emoji} {emoji} {emoji}"


def is_preset_combo(value: int) -> bool:
    """Проверка, является ли комбинация одной из готовых (777, BAR, виноград, лимон)"""
    return value in [1, 22, 43, 64]
