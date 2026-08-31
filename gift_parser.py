"""
Парсер коллекции подарков Telegram

Автоматически получает список подарков из коллекции через Bot API
"""

import re
import aiohttp
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# URL коллекции
COLLECTION_URL = "https://t.me/emperort1me/c/2"


async def fetch_gifts_from_collection(bot_token: str) -> List[Tuple[str, str]]:
    """
    Получить список подарков из коллекции через Telegram Bot API
    
    Возвращает список кортежей (gift_name, gift_url)
    """
    # Извлекаем username и collection_id из URL
    # t.me/emperort1me/c/2 -> emperort1me, 2
    match = re.search(r't\.me/([^/]+)/c/(\d+)', COLLECTION_URL)
    if not match:
        logger.error(f"Не удалось распарсить URL коллекции: {COLLECTION_URL}")
        return []
    
    username = match.group(1)
    collection_id = match.group(2)
    
    # Формируем список примерных подарков
    # В реальности Telegram Bot API не предоставляет прямой метод для получения списка NFT
    # Поэтому используем альтернативный подход
    
    logger.info(f"Попытка получить подарки из коллекции {username}/c/{collection_id}")
    
    # Возвращаем пустой список, так как Bot API не поддерживает получение NFT коллекций
    return []


async def scrape_collection_web(collection_url: str = COLLECTION_URL) -> List[Tuple[str, str]]:
    """
    Парсинг коллекции через веб-страницу с headers
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        # Пробуем несколько вариантов URL
        urls_to_try = [
            collection_url,
            collection_url.replace('t.me', 'telegram.me'),
        ]
        
        async with aiohttp.ClientSession() as session:
            for url in urls_to_try:
                logger.info(f"Пытаюсь получить: {url}")
                
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status != 200:
                            logger.warning(f"HTTP {response.status} для {url}")
                            continue
                        
                        html = await response.text()
                        logger.info(f"Получено {len(html)} байт HTML")
                        
                        # Ищем ссылки на подарки в HTML
                        # Пробуем разные паттерны
                        patterns = [
                            r'https://t\.me/nft/([a-zA-Z0-9_-]+)',
                            r'https://telegram\.me/nft/([a-zA-Z0-9_-]+)',
                            r'/nft/([a-zA-Z0-9_-]+)',
                            r'data-gift-id="([^"]+)"',
                            r'gift[_-]?id["\s:]+([a-zA-Z0-9_-]+)',
                        ]
                        
                        all_matches = []
                        for pattern in patterns:
                            matches = re.findall(pattern, html, re.IGNORECASE)
                            all_matches.extend(matches)
                        
                        if all_matches:
                            gifts = []
                            seen = set()
                            for gift_name in all_matches:
                                if gift_name not in seen and len(gift_name) > 3:  # Фильтруем короткие
                                    gift_url = f"https://t.me/nft/{gift_name}"
                                    gifts.append((gift_name, gift_url))
                                    seen.add(gift_name)
                            
                            if gifts:
                                logger.info(f"Найдено {len(gifts)} подарков")
                                return gifts
                        
                except Exception as e:
                    logger.error(f"Ошибка при запросе {url}: {e}")
                    continue
        
        # Если ничего не нашли
        logger.warning("Не удалось найти подарки автоматически")
        return []
                
    except Exception as e:
        logger.error(f"Общая ошибка при парсинге коллекции: {e}")
        return []


def parse_gift_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Парсит URL подарка и возвращает название и полный URL
    
    Пример:
    https://t.me/nft/LunarSnake-182713
    -> ("LunarSnake-182713", "https://t.me/nft/LunarSnake-182713")
    """
    # Извлекаем имя подарка из URL
    match = re.search(r'/nft/([^/?]+)', url)
    if match:
        gift_name = match.group(1)
        # Очищаем URL от лишних параметров
        clean_url = url.split('?')[0].strip()
        return (gift_name, clean_url)
    return None


def load_gifts_from_file(filename: str = 'gifts.txt') -> List[Tuple[str, str]]:
    """
    Загружает подарки из текстового файла
    
    Формат файла:
    https://t.me/nft/LunarSnake-182713
    https://t.me/nft/AnotherGift-123456
    ...
    """
    gifts = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and line.startswith('http'):
                    parsed = parse_gift_url(line)
                    if parsed:
                        gifts.append(parsed)
    except FileNotFoundError:
        pass
    
    return gifts


def validate_gift_url(url: str) -> bool:
    """Проверяет валидность URL подарка"""
    pattern = r'^https://t\.me/nft/[a-zA-Z0-9_-]+$'
    return bool(re.match(pattern, url))


# Примеры подарков для тестирования
EXAMPLE_GIFTS = [
    ("LunarSnake-182713", "https://t.me/nft/LunarSnake-182713"),
    ("Example-Gift-001", "https://t.me/nft/Example-Gift-001"),
    ("Example-Gift-002", "https://t.me/nft/Example-Gift-002"),
]
