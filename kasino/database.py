import sqlite3
import json
from datetime import datetime
import os
from threading import Lock

DB_FILE = 'casino.db'
db_lock = Lock()

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        balance REAL DEFAULT 0.00,
        avatar TEXT,
        language TEXT DEFAULT 'en',
        frozen INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS game_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        game TEXT,
        bet REAL,
        win REAL,
        result TEXT,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    conn.commit()
    conn.close()
    print("✅ Database initialized")

def get_user(username):
    """Получить данные пользователя"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = c.fetchone()
            conn.close()

            if user:
                return {
                    'id': user[0],
                    'username': user[1],
                    'password': user[2],
                    'balance': round(user[3], 2),
                    'avatar': user[4],
                    'language': user[5] or 'en',
                    'frozen': int(user[6]) if user[6] is not None else 0,  # Исправлено: явное преобразование
                    'created_at': user[7]
                }
            return None
        except Exception as e:
            print(f"❌ Error getting user: {e}")
            return None

def create_user(username, password):
    """Создать нового пользователя с балансом 0"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('INSERT INTO users (username, password, balance, frozen) VALUES (?, ?, ?, ?)',
                      (username, password, 0.00, 0))  # Исправлено: явно указываем frozen = 0
            conn.commit()
            conn.close()
            print(f"✅ User created: {username} with balance 0₽ (frozen: 0)")
            return True
        except sqlite3.IntegrityError:
            print(f"❌ User already exists: {username}")
            return False
        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return False

def update_user_balance(username, new_balance):
    """Обновить баланс пользователя"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('UPDATE users SET balance = ? WHERE username = ?', 
                      (round(new_balance, 2), username))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error updating balance: {e}")

def update_user_settings(username, **kwargs):
    """Обновить настройки пользователя"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            for key, value in kwargs.items():
                if key in ['password', 'avatar', 'language', 'frozen', 'balance']:
                    # Для frozen явно преобразуем в int
                    if key == 'frozen':
                        value = int(value)
                    c.execute(f'UPDATE users SET {key} = ? WHERE username = ?', (value, username))

            conn.commit()
            conn.close()
            print(f"✅ User {username} settings updated: {kwargs}")
        except Exception as e:
            print(f"❌ Error updating user settings: {e}")

def add_game_history(username, game, bet, win, result, details):
    """Добавить запись в историю игр"""
    user = get_user(username)
    if not user:
        return

    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('''INSERT INTO game_history (user_id, game, bet, win, result, details)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (user['id'], game, round(bet, 2), round(win, 2), result, details))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error adding game history: {e}")

def get_game_history(username, limit=None):
    """Получить историю игр пользователя"""
    user = get_user(username)
    if not user:
        return []

    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            if limit:
                c.execute('''SELECT game, bet, win, result, details, timestamp 
                             FROM game_history WHERE user_id = ? 
                             ORDER BY timestamp DESC LIMIT ?''', (user['id'], limit))
            else:
                c.execute('''SELECT game, bet, win, result, details, timestamp 
                             FROM game_history WHERE user_id = ? 
                             ORDER BY timestamp DESC''', (user['id'],))

            history = c.fetchall()
            conn.close()

            return [{
                'game': h[0],
                'bet': h[1],
                'win': h[2],
                'result': h[3],
                'details': h[4],
                'timestamp': h[5]
            } for h in history]
        except Exception as e:
            print(f"❌ Error getting game history: {e}")
            return []

def get_all_users():
    """Получить список всех пользователей"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT username, balance, frozen FROM users')
            users = c.fetchall()
            conn.close()
            return users
        except Exception as e:
            print(f"❌ Error getting all users: {e}")
            return []

def fix_frozen_users():
    """Исправить все NULL значения frozen на 0"""
    with db_lock:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('UPDATE users SET frozen = 0 WHERE frozen IS NULL')
            affected = c.rowcount
            conn.commit()
            conn.close()
            if affected > 0:
                print(f"✅ Fixed {affected} users with NULL frozen status")
            return affected
        except Exception as e:
            print(f"❌ Error fixing frozen users: {e}")
            return 0