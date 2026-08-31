"""
Скрипт для получения списка подарков из коллекции Telegram

Запуск: python get_collection_gifts.py

ВНИМАНИЕ: 
Telegram Bot API не предоставляет метод для получения NFT коллекций.
Этот скрипт показывает как вручную собрать список подарков.

Инструкция:
1. Открой коллекцию в браузере: https://t.me/emperort1me/c/2
2. Пролистай всю коллекцию до конца (чтобы все подарки загрузились)
3. Открой Developer Tools (F12)
4. Вставь в консоль следующий код:

// Получить все ссылки на подарки
const links = Array.from(document.querySelectorAll('a[href*="/nft/"]'))
    .map(a => a.href)
    .filter((v, i, a) => a.indexOf(v) === i); // Уникальные
console.log(links.join('\\n'));

5. Скопируй результат
6. Вставь в файл gifts.txt (по одной ссылке на строку)
7. Загрузи в бота через "📥 Загрузить из файла"

АЛЬТЕРНАТИВА:
Если коллекция публичная, можно:
1. Скопировать ссылки вручную по одной
2. Или использовать Telegram Desktop и экспортировать чат
"""

import asyncio
import aiohttp
import re


async def try_fetch_collection():
    """
    Попытка получить подарки через веб-запрос
    
    ВАЖНО: Этот метод может не работать из-за защиты Telegram
    """
    collection_url = "https://t.me/emperort1me/c/2"
    
    print(f"Попытка получить коллекцию: {collection_url}")
    print("⚠️  Telegram может заблокировать этот запрос\n")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(collection_url) as response:
                if response.status != 200:
                    print(f"❌ Ошибка: HTTP {response.status}")
                    return
                
                html = await response.text()
                
                # Ищем ссылки на подарки
                pattern = r'https://t\.me/nft/([a-zA-Z0-9_-]+)'
                matches = re.findall(pattern, html)
                
                if matches:
                    unique_gifts = list(set(matches))
                    print(f"✅ Найдено подарков: {len(unique_gifts)}\n")
                    
                    # Сохраняем в файл
                    with open('gifts.txt', 'w', encoding='utf-8') as f:
                        for gift_name in unique_gifts:
                            f.write(f"https://t.me/nft/{gift_name}\n")
                    
                    print("✅ Подарки сохранены в gifts.txt")
                    print("\nПервые 5 подарков:")
                    for gift_name in unique_gifts[:5]:
                        print(f"  - https://t.me/nft/{gift_name}")
                else:
                    print("❌ Подарки не найдены в HTML")
                    
    except Exception as e:
        print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Получение подарков из коллекции Telegram")
    print("=" * 60)
    print()
    
    print("📝 ИНСТРУКЦИЯ ПО РУЧНОМУ СБОРУ:")
    print()
    print("1. Открой в браузере: https://t.me/emperort1me/c/2")
    print("2. Пролистай коллекцию до конца")
    print("3. Открой Developer Tools (F12)")
    print("4. Вставь в консоль:")
    print()
    print("   Array.from(document.querySelectorAll('a[href*=\"/nft/\"]'))")
    print("       .map(a => a.href)")
    print("       .filter((v, i, a) => a.indexOf(v) === i)")
    print("       .join('\\n')")
    print()
    print("5. Скопируй результат и вставь в gifts.txt")
    print("6. В боте: /admin → 🎁 Управление подарками → 📥 Загрузить")
    print()
    print("=" * 60)
    print()
    
    choice = input("Попробовать автоматический парсинг? (y/n): ")
    if choice.lower() == 'y':
        asyncio.run(try_fetch_collection())
    else:
        print("\n✅ Следуй инструкции выше для ручного сбора")
