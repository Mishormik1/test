import json
import os
from threading import Lock

POOLS_FILE = 'pools.json'
pools_lock = Lock()

def init_pools():
    """Инициализация пулов"""
    if not os.path.exists(POOLS_FILE):
        save_pools({'players': 0.0, 'developers': 0.0})
        print("✅ Pools initialized")

def load_pools():
    """Загрузить состояние пулов"""
    with pools_lock:
        if os.path.exists(POOLS_FILE):
            try:
                with open(POOLS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {'players': 0.0, 'developers': 0.0}
        return {'players': 0.0, 'developers': 0.0}

def save_pools(pools):
    """Сохранить состояние пулов"""
    with pools_lock:
        pools['players'] = round(pools['players'], 2)
        pools['developers'] = round(pools['developers'], 2)
        with open(POOLS_FILE, 'w') as f:
            json.dump(pools, f, indent=2)

def add_bet_to_pools(amount):
    """Добавляет ставку: 50% игрокам, 50% разработчикам"""
    pools = load_pools()
    players_share = round(amount * 0.5, 2)
    dev_share = round(amount * 0.5, 2)

    pools['players'] += players_share
    pools['developers'] += dev_share
    save_pools(pools)

    return players_share, dev_share

def can_pay_from_pool(amount):
    """Проверяет, достаточно ли денег в пуле игроков"""
    pools = load_pools()
    return pools['players'] >= amount

def take_from_player_pool(amount):
    """Забирает выигрыш из пула игроков"""
    pools = load_pools()

    if pools['players'] >= amount:
        pools['players'] = round(pools['players'] - amount, 2)
        save_pools(pools)
        return True
    return False

def get_player_pool():
    """Получить размер пула игроков"""
    pools = load_pools()
    return pools['players']

def add_to_dev_pool(amount):
    """Добавляет в пул разработчиков (комиссии)"""
    pools = load_pools()
    pools['developers'] = round(pools['developers'] + amount, 2)
    save_pools(pools)