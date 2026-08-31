import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict

class Database:
    def __init__(self, db_file='bot_database.db'):
        self.db_file = db_file
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Включаем WAL режим для лучшей производительности и конкурентности
            cursor.execute('PRAGMA journal_mode=WAL;')
            
            # Таблица событий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    target_value INTEGER NOT NULL,
                    target_count INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    winner_id INTEGER,
                    winner_username TEXT,
                    completed_at TEXT,
                    end_time TEXT,
                    points_config TEXT
                )
            ''')
            
            # Таблица прогресса пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_progress (
                    progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    total_hits INTEGER DEFAULT 0,
                    current_streak INTEGER DEFAULT 0,
                    last_value INTEGER,
                    last_attempt_at TEXT,
                    points INTEGER DEFAULT 0,
                    FOREIGN KEY (event_id) REFERENCES events (event_id),
                    UNIQUE(event_id, user_id)
                )
            ''')
            
            # Таблица истории попыток
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    dice_value INTEGER NOT NULL,
                    is_target INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (event_id) REFERENCES events (event_id)
                )
            ''')
            
            # Таблица подарков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS gifts (
                    gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gift_name TEXT NOT NULL,
                    gift_url TEXT NOT NULL UNIQUE,
                    is_used INTEGER DEFAULT 0,
                    used_by_user_id INTEGER,
                    used_by_username TEXT,
                    used_at TEXT,
                    event_id INTEGER
                )
            ''')
            
            conn.commit()
    
    def create_event(self, event_type: str, target_value: int, target_count: int, 
                    end_time: Optional[str] = None, points_config: Optional[str] = None) -> int:
        """Создать новое событие"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (event_type, target_value, target_count, created_at, end_time, points_config)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (event_type, target_value, target_count, datetime.now().isoformat(), end_time, points_config))
            conn.commit()
            return cursor.lastrowid
    
    def get_active_event(self) -> Optional[Dict]:
        """Получить активное событие"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM events WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def stop_event(self, event_id: int, winner_id: Optional[int] = None, winner_username: Optional[str] = None):
        """Остановить событие"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE events SET is_active = 0, winner_id = ?, winner_username = ?, completed_at = ?
                WHERE event_id = ?
            ''', (winner_id, winner_username, datetime.now().isoformat(), event_id))
            conn.commit()
    
    def get_user_progress(self, event_id: int, user_id: int) -> Optional[Dict]:
        """Получить прогресс пользователя"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM user_progress WHERE event_id = ? AND user_id = ?
            ''', (event_id, user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_user_progress(self, event_id: int, user_id: int, username: str, 
                            dice_value: int, is_target: bool, points: int = 0):
        """Обновить прогресс пользователя"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Получаем текущий прогресс
            progress = self.get_user_progress(event_id, user_id)
            
            if progress:
                # Обновляем существующий прогресс
                if is_target:
                    new_total = progress['total_hits'] + 1
                    new_streak = progress['current_streak'] + 1 if progress['last_value'] == dice_value else 1
                else:
                    new_total = progress['total_hits']
                    new_streak = 0
                
                new_points = progress['points'] + points
                
                cursor.execute('''
                    UPDATE user_progress 
                    SET total_hits = ?, current_streak = ?, last_value = ?, 
                        last_attempt_at = ?, username = ?, points = ?
                    WHERE event_id = ? AND user_id = ?
                ''', (new_total, new_streak, dice_value, datetime.now().isoformat(), 
                      username, new_points, event_id, user_id))
            else:
                # Создаем новый прогресс
                cursor.execute('''
                    INSERT INTO user_progress 
                    (event_id, user_id, username, total_hits, current_streak, last_value, last_attempt_at, points)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (event_id, user_id, username, 1 if is_target else 0, 
                      1 if is_target else 0, dice_value, datetime.now().isoformat(), points))
            
            conn.commit()
    
    def add_attempt(self, event_id: int, user_id: int, username: str, 
                    dice_value: int, is_target: bool):
        """Добавить попытку в историю"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO attempts (event_id, user_id, username, dice_value, is_target, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (event_id, user_id, username, dice_value, 1 if is_target else 0, 
                  datetime.now().isoformat()))
            conn.commit()
    
    def get_event_leaderboard(self, event_id: int, limit: int = 10, order_by: str = 'points') -> List[Dict]:
        """Получить таблицу лидеров события"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if order_by == 'points':
                order_clause = 'points DESC, total_hits DESC'
            else:
                order_clause = 'total_hits DESC, current_streak DESC'
            
            cursor.execute(f'''
                SELECT user_id, username, total_hits, current_streak, points, last_attempt_at
                FROM user_progress
                WHERE event_id = ?
                ORDER BY {order_clause}
                LIMIT ?
            ''', (event_id, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_event_stats(self, event_id: int) -> Dict:
        """Получить статистику события"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Общее количество участников
            cursor.execute('SELECT COUNT(DISTINCT user_id) FROM user_progress WHERE event_id = ?', (event_id,))
            total_participants = cursor.fetchone()[0]
            
            # Общее количество попыток
            cursor.execute('SELECT COUNT(*) FROM attempts WHERE event_id = ?', (event_id,))
            total_attempts = cursor.fetchone()[0]
            
            # Успешные попытки
            cursor.execute('SELECT COUNT(*) FROM attempts WHERE event_id = ? AND is_target = 1', (event_id,))
            successful_attempts = cursor.fetchone()[0]
            
            return {
                'total_participants': total_participants,
                'total_attempts': total_attempts,
                'successful_attempts': successful_attempts
            }

    
    def add_gift(self, gift_name: str, gift_url: str):
        """Добавить подарок в базу"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO gifts (gift_name, gift_url)
                    VALUES (?, ?)
                ''', (gift_name, gift_url))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Подарок уже существует
                return False
    
    def add_gifts_bulk(self, gifts: List[tuple]):
        """Добавить несколько подарков"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            added = 0
            for gift_name, gift_url in gifts:
                try:
                    cursor.execute('''
                        INSERT INTO gifts (gift_name, gift_url)
                        VALUES (?, ?)
                    ''', (gift_name, gift_url))
                    added += 1
                except sqlite3.IntegrityError:
                    continue
            conn.commit()
            return added
    
    def get_random_unused_gift(self) -> Optional[Dict]:
        """Получить случайный неиспользованный подарок"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM gifts WHERE is_used = 0 ORDER BY RANDOM() LIMIT 1
            ''')
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def mark_gift_as_used(self, gift_id: int, user_id: int, username: str, event_id: Optional[int] = None):
        """Пометить подарок как использованный"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE gifts 
                SET is_used = 1, used_by_user_id = ?, used_by_username = ?, 
                    used_at = ?, event_id = ?
                WHERE gift_id = ?
            ''', (user_id, username, datetime.now().isoformat(), event_id, gift_id))
            conn.commit()
    
    def get_gifts_stats(self) -> Dict:
        """Получить статистику подарков"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM gifts')
            total = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM gifts WHERE is_used = 1')
            used = cursor.fetchone()[0]
            
            return {
                'total': total,
                'used': used,
                'available': total - used
            }
    
    def get_user_gifts(self, user_id: int) -> List[Dict]:
        """Получить все подарки пользователя"""
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM gifts WHERE used_by_user_id = ? ORDER BY used_at DESC
            ''', (user_id,))
            return [dict(row) for row in cursor.fetchall()]

    
    def get_current_leader(self, event_id: int) -> Optional[Dict]:
        """Получить текущего лидера события"""
        leaders = self.get_event_leaderboard(event_id, limit=1, order_by='points')
        return leaders[0] if leaders else None
