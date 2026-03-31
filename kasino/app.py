from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
import random
import time
import os
import threading
import math
import json
from werkzeug.utils import secure_filename
from datetime import datetime
from flask_socketio import SocketIO, emit, join_room, leave_room

from database import *
from pools import *
from translations import get_translation, get_all_translations

app = Flask(__name__)
app.secret_key = 'NEO_PULSE_2025_ULTIMATE_KEY'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

STATIC_DIR = 'static'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

global_wins = []

# НАСТРОЙКИ СЛОТОВ
PAYTABLE = {'🍒': 2, '🍇': 5, '🍉': 10, '🔔': 20, '🍀': 50, '7️⃣': 100, '💎': 500, '⭐': 1000}
SYMBOLS = ['🍒', '🍇', '🍉', '🔔', '🍀', '7️⃣', '💎', '⭐']

BET_VALUES = [1, 2, 3, 4, 5, 10, 15, 30, 50, 70, 100, 150, 200, 500, 1000, 1500, "1/4", "1/2", "ALL"]

# НАСТРОЙКИ ARENA
ARENA_CONFIG = {
    "ball_speed": 4,
    "balls_per_team": 2,
    "timer_seconds": 30,
    "teams_colors": [
        {"hex": "#ff8800", "name": "ORANGE"},
        {"hex": "#9900ff", "name": "PURPLE"},
        {"hex": "#ffffff", "name": "WHITE"},
        {"hex": "#ff0000", "name": "RED"},
        {"hex": "#00ff88", "name": "MINT"},
        {"hex": "#0088ff", "name": "BLUE"}
    ]
}

# СОСТОЯНИЕ РАКЕТЫ
rocket_sessions = {}
rocket_lock = threading.Lock()

# СОСТОЯНИЕ AVIATOR
aviator_sessions = {}
aviator_lock = threading.Lock()

def generate_aviator_flight(bet_amount):
    """Генерирует весь полет заранее с учетом пула игроков"""
    flight_data = {
        'events': [],
        'ships': [],
        'final_multiplier': 1.0,
        'max_distance': 0,
        'crashed': False,
        'landed': False,
        'glide_start': 1200,  # Начало планирования (ширина экрана)
        'spawn_start': 1200   # Начало спавна объектов (край экрана)
    }

    current_multiplier = 1.0

    # Генерируем корабли ТОЛЬКО после края экрана
    num_ships = random.randint(2, 4)
    ship_positions = []

    for i in range(num_ships):
        if i == 0:
            # Первый корабль после края экрана
            ship_distance = random.uniform(flight_data['spawn_start'] + 300, flight_data['spawn_start'] + 700)
        else:
            # Следующие корабли
            ship_distance = ship_positions[-1] + random.uniform(600, 1000)

        ship_positions.append(ship_distance)
        flight_data['ships'].append({
            'distance': round(ship_distance, 1),
            'width': 150
        })

    # Генерируем события ТОЛЬКО после края экрана и НЕ на низкой высоте
    max_flight_distance = ship_positions[-1] + 300
    current_pos = flight_data['spawn_start'] + 150

    while current_pos < max_flight_distance:
        current_pos += random.uniform(100, 180)

        # Рандомная высота (от 20% до 70% - не слишком низко)
        event_height = random.uniform(0.2, 0.7)

        event_type = random.choices(
            ['multiplier', 'bomb', 'none'],
            weights=[0.4, 0.2, 0.4]
        )[0]

        if event_type == 'multiplier':
            # Распределение множителей
            rand = random.random()
            if rand < 0.6:  # 60% - обычные
                bonus = random.randint(1, 3)
            elif rand < 0.85:  # 25% - средние
                bonus = random.randint(3, 5)
            else:  # 15% - редкие
                bonus = random.randint(5, 10)

            current_multiplier = round(current_multiplier * bonus, 2)

            flight_data['events'].append({
                'distance': round(current_pos, 1),
                'type': 'multiplier',
                'value': bonus,
                'multiplier': current_multiplier,
                'height': event_height,
                'engine_time': bonus / 5.0
            })
        elif event_type == 'bomb':
            current_multiplier = round(max(1.0, current_multiplier / 2), 2)

            flight_data['events'].append({
                'distance': round(current_pos, 1),
                'type': 'bomb',
                'multiplier': current_multiplier,
                'height': event_height
            })

    # Проверяем может ли пул выплатить выигрыш
    potential_win = round(bet_amount * current_multiplier, 2)
    player_pool = get_player_pool()

    if potential_win <= player_pool:
        flight_data['landed'] = True
        flight_data['max_distance'] = ship_positions[-1]
        flight_data['final_multiplier'] = current_multiplier
    else:
        flight_data['crashed'] = True
        if len(ship_positions) > 1:
            crash_point = random.uniform(ship_positions[-2] + 100, ship_positions[-1] - 100)
        else:
            crash_point = random.uniform(ship_positions[-1] - 300, ship_positions[-1] - 100)
        flight_data['max_distance'] = round(crash_point, 1)
        flight_data['final_multiplier'] = 0

    return flight_data

@app.route('/aviator/bet', methods=['POST'])
def aviator_bet():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    user_data = get_user(u)
    if not user_data:
        return jsonify({'status': 'error'})

    lang = user_data['language']

    if user_data['frozen']:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'account_frozen')})

    data = request.json
    amount_value = data.get('amount')

    amount = calculate_bet_amount(amount_value, user_data['balance'])

    if amount is None:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'min_bet_error')})

    if user_data['balance'] < amount:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})

    with aviator_lock:
        if u in aviator_sessions and aviator_sessions[u]['is_flying']:
            return jsonify({'status': 'error', 'message': 'Already in game'})

        new_balance = round(user_data['balance'] - amount, 2)
        update_user_balance(u, new_balance)

        add_bet_to_pools(amount)

        # Генерируем весь полет заранее с учетом ставки
        flight_data = generate_aviator_flight(amount)

        aviator_sessions[u] = {
            'is_flying': True,
            'start_time': time.time(),
            'bet_amount': amount,
            'flight_data': flight_data,
            'current_distance': 0,
            'current_multiplier': 1.0,
            'current_event_index': 0
        }

    return jsonify({
        'status': 'success', 
        'balance': new_balance,
        'flight_data': flight_data
    })

# СОСТОЯНИЕ ARENA
arena_state = {
    "state": "WAITING",
    "current_bets": [],
    "timer": 30,
    "winner_color": None,
    "big_wins_history": [],
    "game_active": False,
    "timer_thread": None,
    "game_thread": None,
    "next_winner": None,
    "clients_connected": {},
    "game_data": {
        "balls": [],
        "friction": 1.0,
        "game_ended": False,
        "start_time": 0
    },
    "initial_balls": []
}
arena_lock = threading.Lock()

# БЛЭКДЖЕК
bj_table = {
    "players": {},
    "dealer_hand": [],
    "status": "waiting",
    "last_activity": time.time(),
    "timer": 30,
    "min_bet": 0
}
bj_lock = threading.Lock()

def format_currency(amount):
    """Форматирует число в формат 1.234.567,89"""
    amount = round(float(amount), 2)
    # Разделяем на целую и дробную части
    integer_part = int(amount)
    decimal_part = int(round((amount - integer_part) * 100))

    # Форматируем целую часть с точками
    integer_str = f"{integer_part:,}".replace(',', '.')

    # Форматируем дробную часть
    decimal_str = f"{decimal_part:02d}"

    return f"{integer_str},{decimal_str}"

def get_card_value():
    return random.randint(1, 10)

def calculate_hand_value(hand):
    return sum(hand)

def reset_bj_table():
    global bj_table
    with bj_lock:
        bj_table = {
            "players": {},
            "dealer_hand": [],
            "status": "waiting",
            "last_activity": time.time(),
            "timer": 30,
            "min_bet": 0
        }

def bj_timer_loop():
    global bj_table
    while True:
        time.sleep(1)
        with bj_lock:
            if bj_table["status"] == "waiting":
                bj_table["timer"] -= 1
                socketio.emit('bj_timer', {'time': bj_table["timer"]}, room='blackjack')

                if bj_table["timer"] <= 0:
                    if bj_table["players"]:
                        bj_table["status"] = "playing"
                        min_bet = min([p["bet"] for p in bj_table["players"].values()])
                        bj_table["min_bet"] = min_bet
                        dealer_bet = random.randint(int(min_bet), int(min_bet * 1.23))

                        for name in bj_table["players"]:
                            bj_table["players"][name]["hand"] = [get_card_value()]
                            bj_table["players"][name]["done"] = False

                        bj_table["dealer_hand"] = [get_card_value()]
                        bj_table["dealer_bet"] = dealer_bet

                        socketio.emit('bj_game_start', {'dealer_bet': dealer_bet}, room='blackjack')
                    else:
                        bj_table["timer"] = 30

            elif bj_table["status"] == "playing":
                all_done = all(p["done"] or calculate_hand_value(p["hand"]) > 21 
                             for p in bj_table["players"].values())

                if all_done:
                    finish_bj_game()

def finish_bj_game():
    global bj_table
    bj_table["status"] = "finished"

    dealer_advantage = random.random() < 0.7

    if dealer_advantage:
        while calculate_hand_value(bj_table["dealer_hand"]) < 18:
            bj_table["dealer_hand"].append(get_card_value())
    else:
        while calculate_hand_value(bj_table["dealer_hand"]) < 17:
            bj_table["dealer_hand"].append(get_card_value())

    dealer_score = calculate_hand_value(bj_table["dealer_hand"])

    results = {}
    total_pool = bj_table["dealer_bet"]

    for name, p_data in bj_table["players"].items():
        p_score = calculate_hand_value(p_data["hand"])
        total_pool += p_data["bet"]

        if p_score > 21:
            results[name] = {"score": p_score, "result": "bust", "win": 0}
        elif dealer_score > 21:
            results[name] = {"score": p_score, "result": "win", "win": 0}
        elif p_score > dealer_score:
            results[name] = {"score": p_score, "result": "win", "win": 0}
        elif p_score == dealer_score:
            results[name] = {"score": p_score, "result": "draw", "win": 0}
        else:
            results[name] = {"score": p_score, "result": "lose", "win": 0}

    winners = [name for name, r in results.items() if r["result"] in ["win", "draw"]]

    if not winners:
        add_to_dev_pool(total_pool)
    elif len(winners) == len(results) and all(r["result"] == "draw" for r in results.values()):
        add_to_dev_pool(total_pool)
    else:
        if can_pay_from_pool(total_pool):
            win_amount = round(total_pool / len(winners), 2)

            for name in winners:
                results[name]["win"] = win_amount

                user_data = get_user(name)
                if user_data:
                    new_balance = round(user_data['balance'] + win_amount, 2)
                    update_user_balance(name, new_balance)

                    add_game_history(name, 'blackjack', bj_table["players"][name]['bet'], 
                                   win_amount, 'win' if results[name]["result"] == "win" else 'draw',
                                   f'Score: {results[name]["score"]}, Dealer: {dealer_score}')

                    if win_amount >= 100:
                        global_wins.insert(0, {
                            'user': name,
                            'amount': win_amount,
                            'time': time.strftime('%H:%M:%S'),
                            'game': 'BLACKJACK',
                            'avatar': user_data.get('avatar')
                        })
                        global_wins[:] = global_wins[:10]

            take_from_player_pool(total_pool)
        else:
            for name in winners:
                add_game_history(name, 'blackjack', bj_table["players"][name]['bet'], 
                               0, 'loss', 'Insufficient pool')

    socketio.emit('bj_game_end', {
        'dealer_hand': bj_table["dealer_hand"],
        'dealer_score': dealer_score,
        'results': results,
        'players_hands': {name: p["hand"] for name, p in bj_table["players"].items()}
    }, room='blackjack')

    threading.Timer(7.0, reset_bj_table).start()

threading.Thread(target=bj_timer_loop, daemon=True).start()

def generate_crash_point():
    r = random.random()
    if r < 0.8:
        return round(random.uniform(1.01, 1.5), 2)
    else:
        return round(random.uniform(1.5, 10.0), 2)

def calculate_bet_amount(bet_value, balance):
    """Вычисляет реальную ставку с учетом минимума 1₽"""
    if bet_value == "1/4":
        amount = balance / 4
    elif bet_value == "1/2":
        amount = balance / 2
    elif bet_value == "ALL":
        amount = balance
    else:
        amount = float(bet_value)

    if amount < 1:
        return None

    return round(amount, 2)

def generate_initial_balls():
    balls = []
    ARENA_RADIUS = 300
    total_balls = len(ARENA_CONFIG["teams_colors"]) * ARENA_CONFIG["balls_per_team"]
    angle_step = (2 * math.pi) / total_balls

    ball_index = 0
    for team in ARENA_CONFIG["teams_colors"]:
        for i in range(ARENA_CONFIG["balls_per_team"]):
            angle = ball_index * angle_step
            distance = ARENA_RADIUS - 30
            x = distance * math.cos(angle)
            y = distance * math.sin(angle)
            wall_x = ARENA_RADIUS * math.cos(angle)
            wall_y = ARENA_RADIUS * math.sin(angle)

            ball = {
                'color': team['hex'],
                'pos': {'x': x, 'y': y},
                'vel': {'x': 0, 'y': 0},
                'lines': [{'x': wall_x, 'y': wall_y}],
                'dead': False,
                'hasHitWall': True,
                'r': 11
            }
            balls.append(ball)
            ball_index += 1

    return balls

def arena_game_loop():
    global arena_state

    while True:
        with arena_lock:
            arena_state["state"] = "WAITING"
            arena_state["timer"] = ARENA_CONFIG["timer_seconds"]
            arena_state["game_active"] = False
            arena_state["game_data"] = {
                "balls": [],
                "friction": 1.0,
                "game_ended": False,
                "start_time": 0
            }
            arena_state["initial_balls"] = generate_initial_balls()
            arena_state["next_winner"] = random.choice(ARENA_CONFIG["teams_colors"])['hex']

        socketio.emit('arena_reset', {'initial_balls': arena_state["initial_balls"]}, room='arena')
        socketio.emit('arena_bets_update', {
            'bets': arena_state["current_bets"],
            'total_bets': len(arena_state["current_bets"])
        }, room='arena')

        for i in range(ARENA_CONFIG["timer_seconds"], 0, -1):
            with arena_lock:
                arena_state["timer"] = i
            socketio.emit('arena_timer', {'time': i}, room='arena')
            time.sleep(1)

        with arena_lock:
            arena_state["state"] = "RUNNING"
            arena_state["game_active"] = True
            arena_state["game_data"]["start_time"] = time.time()
            arena_state["game_data"]["game_ended"] = False

        socketio.emit('arena_start', {
            'winner_color': arena_state["next_winner"],
            'teams': ARENA_CONFIG["teams_colors"],
            'initial_balls': arena_state["initial_balls"]
        }, room='arena')

        while arena_state["state"] == "RUNNING":
            time.sleep(0.1)

def finish_arena_game(winner_color, total_lines_count):
    global arena_state

    with arena_lock:
        if arena_state["state"] != "RUNNING":
            return

        arena_state["state"] = "FINISHING"
        multiplier = round(total_lines_count / 3.0, 1)
        if multiplier < 1.0:
            multiplier = 1.0

        if arena_state["current_bets"]:
            for bet in arena_state["current_bets"]:
                user_data = get_user(bet['username'])
                if not user_data:
                    continue

                if bet['color'] == winner_color:
                    win_amount = round(bet['amount'] * multiplier, 2)

                    if can_pay_from_pool(win_amount):
                        new_balance = round(user_data['balance'] + win_amount, 2)
                        update_user_balance(bet['username'], new_balance)
                        take_from_player_pool(win_amount)

                        socketio.emit('arena_bet_result', {
                            'status': 'win',
                            'amount': win_amount,
                            'multiplier': multiplier,
                            'balance': new_balance,
                            'balance_display': format_currency(new_balance),
                            'lines_count': total_lines_count
                        }, room=bet['sid'])

                        add_game_history(bet['username'], 'arena', bet['amount'], win_amount, 'win',
                                       f'Multiplier: {multiplier}x ({total_lines_count} lines)')

                        if win_amount >= 100:
                            arena_state["big_wins_history"].insert(0, {
                                'user': bet['username'],
                                'win_usd': win_amount,
                                'avatar': user_data.get('avatar'),
                                'timestamp': time.time()
                            })
                            arena_state["big_wins_history"] = arena_state["big_wins_history"][:10]
                    else:
                        socketio.emit('arena_bet_result', {
                            'status': 'loss',
                            'amount': bet['amount']
                        }, room=bet['sid'])

                        add_game_history(bet['username'], 'arena', bet['amount'], 0, 'loss',
                                       'Insufficient pool')
                else:
                    socketio.emit('arena_bet_result', {
                        'status': 'loss',
                        'amount': bet['amount']
                    }, room=bet['sid'])

                    add_game_history(bet['username'], 'arena', bet['amount'], 0, 'loss', 'Lost')

        socketio.emit('arena_result', {
            'winner': winner_color,
            'multiplier': multiplier,
            'lines_count': total_lines_count,
            'big_wins': arena_state["big_wins_history"][:10]
        }, room='arena')

        arena_state["current_bets"] = []

    time.sleep(5)

    with arena_lock:
        arena_state["state"] = "WAITING"

# КАПЧА
CAPTCHA_IMAGES = {
    'bus': ['🚌', '🚎', '🚐', '🚍', '🚋', '🚊'],
    'car': ['🚗', '🚕', '🚙', '🚌', '🚎', '🏎️'],
    'house': ['🏠', '🏡', '🏘️', '🏚️', '🏢', '🏣'],
    'tree': ['🌲', '🌳', '🌴', '🌵', '🎄', '🎋'],
    'animal': ['🐶', '🐱', '🐭', '🐹', '🐰', '🦊'],
    'food': ['🍎', '🍌', '🍕', '🍔', '🍟', '🌭'],
    'sport': ['⚽', '🏀', '🏈', '⚾', '🎾', '🏐'],
    'tech': ['📱', '💻', '🖥️', '⌚', '🖨️', '📷']
}

CAPTCHA_TRANSLATIONS = {
    'en': {
        'bus': 'buses', 'car': 'cars', 'house': 'houses', 'tree': 'trees',
        'animal': 'animals', 'food': 'food', 'sport': 'sport equipment', 'tech': 'tech devices'
    },
    'ru': {
        'bus': 'автобусами', 'car': 'машинами', 'house': 'домами', 'tree': 'деревьями',
        'animal': 'животными', 'food': 'едой', 'sport': 'спортом', 'tech': 'техникой'
    }
}

def generate_image_captcha(lang='en'):
    category = random.choice(list(CAPTCHA_IMAGES.keys()))
    correct_images = random.sample(CAPTCHA_IMAGES[category], 3)
    other_categories = [c for c in CAPTCHA_IMAGES.keys() if c != category]
    wrong_category = random.choice(other_categories)
    wrong_images = random.sample(CAPTCHA_IMAGES[wrong_category], 3)
    all_images = correct_images + wrong_images
    random.shuffle(all_images)

    correct_positions = []
    for i, img in enumerate(all_images):
        if img in correct_images:
            correct_positions.append(i)

    if lang == 'ru':
        instruction = f'Выберите все изображения с {CAPTCHA_TRANSLATIONS["ru"][category]}'
    else:
        instruction = f'Select all images with {CAPTCHA_TRANSLATIONS["en"][category]}'

    return {
        'category': category,
        'images': all_images,
        'correct_positions': correct_positions,
        'instruction': instruction
    }

def get_user_folder(username):
    user_folder = os.path.join(STATIC_DIR, 'avatars', username)
    if not os.path.exists(user_folder):
        os.makedirs(user_folder, exist_ok=True)
    return user_folder

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.template_filter('format_datetime')
def format_datetime_filter(timestamp):
    try:
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(timestamp)

@app.template_filter('format_currency')
def format_currency_filter(amount):
    """Фильтр для шаблонов"""
    return format_currency(amount)

# МАРШРУТЫ

@app.route('/')
def index():
    if 'user' in session:
        user_data = get_user(session['user'])
        if user_data:
            return redirect(url_for('hub'))
        else:
            session.pop('user', None)

    lang = session.get('lang', 'en')
    login_captcha = generate_image_captcha(lang)
    register_captcha = generate_image_captcha(lang)
    session['login_captcha'] = login_captcha
    session['register_captcha'] = register_captcha

    return render_template('index.html',
                         login_captcha=login_captcha,
                         register_captcha=register_captcha,
                         t=get_all_translations(lang))

@app.route('/hub')
def hub():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('hub.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         t=get_all_translations(lang))

@app.route('/profile')
def profile():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('profile.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         game_history=get_game_history(u, 10),
                         current_language=lang,
                         t=get_all_translations(lang))

@app.route('/avatar/<username>')
def get_avatar(username):
    user_data = get_user(username)

    if user_data and 'avatar' in user_data and user_data['avatar']:
        avatar_path = os.path.join(STATIC_DIR, 'avatars', username, user_data['avatar'])
        if os.path.exists(avatar_path):
            return send_from_directory(os.path.join(STATIC_DIR, 'avatars', username), user_data['avatar'])

    default_path = os.path.join(STATIC_DIR, 'default_avatar.png')
    if os.path.exists(default_path):
        return send_from_directory(STATIC_DIR, 'default_avatar.png', mimetype='image/png')

    return "Not found", 404

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    if 'avatar' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file'})

    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file'})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[1].lower()
        new_filename = f"avatar_{int(time.time())}.{ext}"

        user_folder = get_user_folder(u)
        file_path = os.path.join(user_folder, new_filename)
        file.save(file_path)

        update_user_settings(u, avatar=new_filename)

        return jsonify({'status': 'success', 'filename': new_filename})

    return jsonify({'status': 'error', 'message': 'Invalid file'})

@app.route('/update_profile', methods=['POST'])
def update_profile():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    data = request.json
    user_data = get_user(u)
    lang = user_data['language']

    updates = {}

    if 'new_password' in data and data['new_password']:
        if user_data.get('password') == data.get('current_password', ''):
            updates['password'] = data['new_password']
        else:
            return jsonify({'status': 'error', 'message': get_translation(lang, 'wrong_password')})

    if 'language' in data:
        updates['language'] = data['language']
        session['lang'] = data['language']

    if updates:
        update_user_settings(u, **updates)

    return jsonify({'status': 'success'})

@app.route('/get_full_history')
def get_full_history():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error'})

    history = get_game_history(u)

    return jsonify({'status': 'success', 'history': history})

@app.route('/deposit', methods=['POST'])
def deposit():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    user_data = get_user(u)
    lang = user_data['language']

    data = request.json
    amount = float(data.get('amount', 0))

    min_deposit = 100

    if amount < min_deposit:
        return jsonify({'status': 'error', 'message': f"{get_translation(lang, 'min_deposit')}: {format_currency(min_deposit)}₽"})

    fee = round(amount * 0.02, 2)
    amount_with_fee = round(amount + fee, 2)

    add_to_dev_pool(fee)

    new_balance = round(user_data['balance'] + amount, 2)
    update_user_balance(u, new_balance)

    return jsonify({
        'status': 'success', 
        'balance': new_balance,
        'balance_display': format_currency(new_balance),
        'amount_to_pay': format_currency(amount_with_fee),
        'fee': format_currency(fee)
    })

@app.route('/withdraw', methods=['POST'])
def withdraw():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    user_data = get_user(u)
    lang = user_data['language']

    data = request.json
    amount = float(data.get('amount', 0))

    if amount < 4000:
        return jsonify({'status': 'error', 'message': f"{get_translation(lang, 'min_withdraw')}: {format_currency(4000)}₽"})

    if user_data['balance'] < amount:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})

    fee = round(amount * 0.02, 2)
    amount_to_receive = round(amount - fee, 2)

    add_to_dev_pool(fee)

    new_balance = round(user_data['balance'] - amount, 2)
    update_user_balance(u, new_balance)

    return jsonify({
        'status': 'success', 
        'balance': new_balance,
        'balance_display': format_currency(new_balance),
        'amount_to_receive': format_currency(amount_to_receive)
    })

@app.route('/spin', methods=['POST'])
def spin():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error'})

    user_data = get_user(u)
    if not user_data:
        return jsonify({'status': 'error'})

    lang = user_data['language']

    if user_data['frozen']:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'account_frozen')})

    data = request.json
    bet_value = data.get('bet')

    bet = calculate_bet_amount(bet_value, user_data['balance'])

    if bet is None:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'min_bet_error')})

    if user_data['balance'] < bet:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})

    new_balance = round(user_data['balance'] - bet, 2)
    update_user_balance(u, new_balance)

    add_bet_to_pools(bet)

    if random.random() > 0.2:
        grid = [[random.choice(SYMBOLS) for _ in range(5)] for _ in range(5)]
        add_game_history(u, 'slots', bet, 0, 'loss', 'No win')
        return jsonify({'status': 'success', 'grid': grid, 'win_amount': 0, 'win_lines': [], 'balance': new_balance})

    grid = [[random.choice(SYMBOLS) for _ in range(5)] for _ in range(5)]
    win_amount = 0
    win_lines = []
    colors = ['#ff0055', '#00f2ff', '#bc13fe', '#ffd700', '#00ff88']

    for row in range(5):
        first_sym = grid[0][row]
        count = 1
        for col in range(1, 5):
            if grid[col][row] == first_sym:
                count += 1
            else:
                break
        if count >= 3:
            line_win = round(bet * PAYTABLE.get(first_sym, 0) * (count - 2), 2)
            win_amount += line_win
            win_lines.append({
                'color': colors[row],
                'path': [[row, c] for c in range(count)],
                'symbol': first_sym,
                'multiplier': PAYTABLE.get(first_sym, 0) * (count - 2)
            })

    win_amount = round(win_amount, 2)

    if win_amount > 0 and can_pay_from_pool(win_amount):
        new_balance = round(new_balance + win_amount, 2)
        update_user_balance(u, new_balance)
        take_from_player_pool(win_amount)

        add_game_history(u, 'slots', bet, win_amount, 'win', f'Win lines: {len(win_lines)}')

        if win_amount > 0:
            avatar = user_data.get('avatar')
            global_wins.insert(0, {
                'user': u,
                'amount': win_amount,
                'time': time.strftime('%H:%M:%S'),
                'game': 'SLOTS',
                'avatar': avatar
            })
            global_wins[:] = global_wins[:10]

        return jsonify({
            'status': 'success',
            'grid': grid,
            'win_amount': win_amount,
            'win_lines': win_lines,
            'balance': new_balance
        })
    else:
        add_game_history(u, 'slots', bet, 0, 'loss', 'Insufficient pool')
        return jsonify({'status': 'success', 'grid': grid, 'win_amount': 0, 'win_lines': [], 'balance': new_balance})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    u, p = data.get('username', '').strip(), data.get('password', '').strip()
    captcha_selected = data.get('captcha_selected', [])

    lang = session.get('lang', 'en')

    if not u or not p or not captcha_selected:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'fill_all_fields')})

    if 'login_captcha' not in session:
        return jsonify({'status': 'error', 'message': 'Captcha error'})

    captcha_data = session['login_captcha']
    correct_positions = set(captcha_data['correct_positions'])
    selected_positions = set(captcha_selected)

    if selected_positions != correct_positions:
        new_captcha = generate_image_captcha(lang)
        session['login_captcha'] = new_captcha
        return jsonify({'status': 'error', 'message': get_translation(lang, 'wrong_captcha'), 'new_captcha': new_captcha})

    user_data = get_user(u)
    if not user_data:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'user_not_found')})

    if user_data.get('password') == p:
        session['user'] = u
        session['lang'] = user_data['language']
        session.pop('login_captcha', None)
        session.pop('register_captcha', None)
        return jsonify({'status': 'success'})

    return jsonify({'status': 'error', 'message': get_translation(lang, 'wrong_password')})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    u, p = data.get('username', '').strip(), data.get('password', '').strip()
    captcha_selected = data.get('captcha_selected', [])

    lang = session.get('lang', 'en')

    if not u or not p or not captcha_selected:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'fill_all_fields')})

    if 'register_captcha' not in session:
        return jsonify({'status': 'error', 'message': 'Captcha error'})

    captcha_data = session['register_captcha']
    correct_positions = set(captcha_data['correct_positions'])
    selected_positions = set(captcha_selected)

    if selected_positions != correct_positions:
        new_captcha = generate_image_captcha(lang)
        session['register_captcha'] = new_captcha
        return jsonify({'status': 'error', 'message': get_translation(lang, 'wrong_captcha'), 'new_captcha': new_captcha})

    if len(u) < 3:
        return jsonify({'status': 'error', 'message': 'Username must be at least 3 characters'})

    if len(p) < 4:
        return jsonify({'status': 'error', 'message': 'Password must be at least 4 characters'})

    if not create_user(u, p):
        return jsonify({'status': 'error', 'message': get_translation(lang, 'user_exists')})

    session['user'] = u
    session['lang'] = 'en'

    session.pop('login_captcha', None)
    session.pop('register_captcha', None)

    return jsonify({'status': 'success'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/change_lang/<lang>')
def change_lang(lang):
    if lang in ['en', 'ru']:
        session['lang'] = lang

        u = session.get('user')
        if u:
            update_user_settings(u, language=lang)

    return redirect(request.referrer or url_for('index'))

@app.route('/game/slots')
def slots_game():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('slots.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         paytable=PAYTABLE,
                         avatar=user_data.get('avatar'),
                         bet_values=BET_VALUES,
                         t=get_all_translations(lang))

@app.route('/game/rocket')
def rocket_game():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('rocket.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         bet_values=BET_VALUES,
                         t=get_all_translations(lang))

@app.route('/game/blackjack')
def blackjack_game():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('blackjack.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         bet_values=BET_VALUES,
                         t=get_all_translations(lang))

@app.route('/game/arena')
def arena_game():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('arena.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         config=ARENA_CONFIG,
                         bet_values=BET_VALUES,
                         t=get_all_translations(lang))

@app.route('/game/aviator')
def aviator_game():
    u = session.get('user')
    if not u:
        return redirect(url_for('index'))

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return redirect(url_for('index'))

    lang = user_data['language']
    balance_display = format_currency(user_data['balance'])

    return render_template('aviator.html',
                         user=u,
                         balance=user_data['balance'],
                         balance_display=balance_display,
                         avatar=user_data.get('avatar'),
                         bet_values=BET_VALUES,
                         t=get_all_translations(lang))

@app.route('/get_wins')
def get_wins():
    return jsonify(global_wins[:10])

@app.route('/get_balance')
def get_balance():
    u = session.get('user')
    if not u:
        return jsonify({
            'status': 'error',
            'message': 'Not authorized',
            'balance': 0,
            'balance_display': '0,00',
            'redirect': '/logout'
        })

    user_data = get_user(u)
    if not user_data:
        session.pop('user', None)
        return jsonify({
            'status': 'error',
            'message': 'User not found',
            'balance': 0,
            'balance_display': '0,00',
            'redirect': '/logout'
        })

    balance_display = format_currency(user_data['balance'])

    return jsonify({
        'status': 'success',
        'balance': user_data['balance'],
        'balance_display': balance_display
    })

# ROCKET
@app.route('/rocket/bet', methods=['POST'])
def rocket_bet():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    user_data = get_user(u)
    if not user_data:
        return jsonify({'status': 'error'})

    lang = user_data['language']

    if user_data['frozen']:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'account_frozen')})

    data = request.json
    amount_value = data.get('amount')

    amount = calculate_bet_amount(amount_value, user_data['balance'])

    if amount is None:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'min_bet_error')})

    if user_data['balance'] < amount:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})

    with rocket_lock:
        if u in rocket_sessions and rocket_sessions[u]['is_flying']:
            return jsonify({'status': 'error', 'message': 'Already in game'})

        new_balance = round(user_data['balance'] - amount, 2)
        update_user_balance(u, new_balance)

        add_bet_to_pools(amount)

        crash_point = generate_crash_point()
        rocket_sessions[u] = {
            'multiplier': 0.0,
            'is_flying': True,
            'crash_at': crash_point,
            'start_time': time.time(),
            'bet_amount': amount
        }

    return jsonify({'status': 'success', 'balance': new_balance, 'crash_at': crash_point})

@app.route('/rocket/status')
def rocket_status():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error'})

    with rocket_lock:
        if u not in rocket_sessions:
            return jsonify({'is_flying': False, 'multiplier': 0.0})

        session_data = rocket_sessions[u]

        if session_data['is_flying']:
            elapsed = time.time() - session_data['start_time']
            # Начинаем с 0.0 и растем
            current_mult = round(max(0.0, (pow(1.08, elapsed * 4) - 1.0) * 1.5), 2)

            if current_mult >= session_data['crash_at']:
                session_data['is_flying'] = False
                session_data['multiplier'] = session_data['crash_at']

                add_game_history(u, 'rocket', session_data['bet_amount'], 0, 'loss',
                               f'Crashed at {session_data["crash_at"]}x')

                return jsonify({
                    'is_flying': False,
                    'multiplier': session_data['crash_at'],
                    'crashed': True
                })
            else:
                session_data['multiplier'] = current_mult

                return jsonify({
                    'is_flying': True,
                    'multiplier': current_mult
                })

        return jsonify({
            'is_flying': False,
            'multiplier': session_data['multiplier']
        })

@app.route('/rocket/cashout', methods=['POST'])
def rocket_cashout():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    with rocket_lock:
        if u not in rocket_sessions or not rocket_sessions[u]['is_flying']:
            return jsonify({'status': 'error', 'message': 'No active game'})

        session_data = rocket_sessions[u]
        win_amount = round(session_data['bet_amount'] * session_data['multiplier'], 2)

        if can_pay_from_pool(win_amount):
            user_data = get_user(u)
            new_balance = round(user_data['balance'] + win_amount, 2)
            update_user_balance(u, new_balance)
            take_from_player_pool(win_amount)

            add_game_history(u, 'rocket', session_data['bet_amount'], win_amount, 'win',
                           f'Cashed out at {session_data["multiplier"]}x')

            if win_amount >= 100:
                user_avatar = user_data.get('avatar')
                global_wins.insert(0, {
                    'user': u,
                    'amount': win_amount,
                    'time': time.strftime('%H:%M:%S'),
                    'game': 'ROCKET',
                    'avatar': user_avatar
                })
                global_wins[:] = global_wins[:10]

            session_data['is_flying'] = False

            return jsonify({'status': 'success', 'balance': new_balance, 'win_amount': win_amount})
        else:
            session_data['is_flying'] = False
            add_game_history(u, 'rocket', session_data['bet_amount'], 0, 'loss', 'Insufficient pool')
            return jsonify({'status': 'error', 'message': 'Insufficient pool'})

@app.route('/aviator/status')
def aviator_status():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error'})

    with aviator_lock:
        if u not in aviator_sessions:
            return jsonify({'is_flying': False, 'distance': 0, 'multiplier': 1.0})

        session_data = aviator_sessions[u]

        if session_data['is_flying']:
            elapsed = time.time() - session_data['start_time']
            # Самолет летит с постоянной скоростью
            current_distance = round(elapsed * 50, 1)  # 50 единиц в секунду

            flight_data = session_data['flight_data']

            # Проверяем события
            current_multiplier = 1.0
            next_event = None

            for i, event in enumerate(flight_data['events']):
                if event['distance'] <= current_distance:
                    current_multiplier = event['multiplier']
                    session_data['current_event_index'] = i
                else:
                    next_event = event
                    break

            session_data['current_distance'] = current_distance
            session_data['current_multiplier'] = current_multiplier

            # Проверяем крушение
            if flight_data['crashed'] and current_distance >= flight_data['crash_distance']:
                session_data['is_flying'] = False
                add_game_history(u, 'aviator', session_data['bet_amount'], 0, 'loss',
                               f'Shot down at {current_distance}m')

                return jsonify({
                    'is_flying': False,
                    'distance': current_distance,
                    'multiplier': current_multiplier,
                    'crashed': True,
                    'crash_event': flight_data['events'][session_data['current_event_index']] if session_data['current_event_index'] < len(flight_data['events']) else None
                })

            # Проверяем достижение максимальной дистанции
            if current_distance >= flight_data['max_distance']:
                session_data['is_flying'] = False
                return jsonify({
                    'is_flying': False,
                    'distance': flight_data['max_distance'],
                    'multiplier': current_multiplier,
                    'finished': True
                })

            return jsonify({
                'is_flying': True,
                'distance': current_distance,
                'multiplier': current_multiplier,
                'next_event': next_event
            })

        return jsonify({
            'is_flying': False,
            'distance': session_data['current_distance'],
            'multiplier': session_data['current_multiplier']
        })

@app.route('/aviator/cashout', methods=['POST'])
def aviator_cashout():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error', 'message': 'Not authorized'})

    with aviator_lock:
        if u not in aviator_sessions or not aviator_sessions[u]['is_flying']:
            return jsonify({'status': 'error', 'message': 'No active game'})

        session_data = aviator_sessions[u]
        win_amount = round(session_data['bet_amount'] * session_data['current_multiplier'], 2)

        if can_pay_from_pool(win_amount):
            user_data = get_user(u)
            new_balance = round(user_data['balance'] + win_amount, 2)
            update_user_balance(u, new_balance)
            take_from_player_pool(win_amount)

            add_game_history(u, 'aviator', session_data['bet_amount'], win_amount, 'win',
                           f'Landed at {session_data["current_distance"]}m, {session_data["current_multiplier"]}x')

            if win_amount >= 100:
                user_avatar = user_data.get('avatar')
                global_wins.insert(0, {
                    'user': u,
                    'amount': win_amount,
                    'time': time.strftime('%H:%M:%S'),
                    'game': 'AVIATOR',
                    'avatar': user_avatar
                })
                global_wins[:] = global_wins[:10]

            session_data['is_flying'] = False

            return jsonify({'status': 'success', 'balance': new_balance, 'win_amount': win_amount})
        else:
            session_data['is_flying'] = False
            add_game_history(u, 'aviator', session_data['bet_amount'], 0, 'loss', 'Insufficient pool')
            return jsonify({'status': 'error', 'message': 'Insufficient pool'})

# BLACKJACK
@app.route('/blackjack/sync')
def bj_sync():
    u = session.get('user')

    with bj_lock:
        if bj_table["status"] == "finished":
            display_dealer = list(bj_table["dealer_hand"])
        else:
            display_dealer = ['?'] * len(bj_table["dealer_hand"])

        players_with_avatars = {}
        for name, data in bj_table["players"].items():
            user_data = get_user(name)
            avatar = user_data.get('avatar') if user_data else None

            if bj_table["status"] == "finished" or name == u:
                hand_display = data["hand"]
            else:
                hand_display = ['?'] * len(data["hand"])

            players_with_avatars[name] = {
                'hand': hand_display,
                'bet': data['bet'],
                'done': data['done'],
                'avatar': avatar
            }

        return jsonify({
            "players": players_with_avatars,
            "dealer": display_dealer,
            "table_status": bj_table["status"],
            "timer": bj_table["timer"],
            "dealer_bet": bj_table.get("dealer_bet", 0)
        })

@app.route('/blackjack/play', methods=['POST'])
def blackjack_play():
    u = session.get('user')
    if not u:
        return jsonify({'status': 'error'})

    user_data = get_user(u)
    if not user_data:
        return jsonify({'status': 'error'})

    lang = user_data['language']

    if user_data['frozen']:
        return jsonify({'status': 'error', 'message': get_translation(lang, 'account_frozen')})

    data = request.json
    action = data.get('action')

    with bj_lock:
        if action == 'start':
            if bj_table["status"] != "waiting":
                return jsonify({'status': 'error', 'message': 'Game already started'})

            if u in bj_table["players"]:
                return jsonify({'status': 'error', 'message': 'Already in game'})

            bet_value = data.get('bet')

            bet = calculate_bet_amount(bet_value, user_data['balance'])

            if bet is None:
                return jsonify({'status': 'error', 'message': get_translation(lang, 'min_bet_error')})

            if user_data['balance'] < bet:
                return jsonify({'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})

            new_balance = round(user_data['balance'] - bet, 2)
            update_user_balance(u, new_balance)

            add_bet_to_pools(bet)

            bj_table["players"][u] = {
                "hand": [],
                "bet": bet,
                "done": False
            }

            return jsonify({'status': 'success', 'balance': new_balance})

        elif action == 'hit':
            if bj_table["status"] != "playing":
                return jsonify({'status': 'error'})

            if u in bj_table["players"] and not bj_table["players"][u]["done"]:
                bj_table["players"][u]["hand"].append(get_card_value())

                if calculate_hand_value(bj_table["players"][u]["hand"]) >= 21:
                    bj_table["players"][u]["done"] = True

                return jsonify({'status': 'success'})

        elif action == 'stand':
            if u in bj_table["players"]:
                bj_table["players"][u]["done"] = True
                return jsonify({'status': 'success'})

    return jsonify({'status': 'error'})

# ARENA WEBSOCKET
@socketio.on('connect')
def handle_connect():
    emit('arena_connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    with arena_lock:
        if request.sid in arena_state["clients_connected"]:
            del arena_state["clients_connected"][request.sid]

@socketio.on('arena_join')
def handle_arena_join():
    u = session.get('user')
    if not u:
        emit('arena_error', {'message': 'Not authorized'})
        return

    user_data = get_user(u)
    if not user_data:
        emit('arena_error', {'message': 'User not found'})
        return

    join_room('arena')
    with arena_lock:
        arena_state["clients_connected"][request.sid] = u

    user_bet = None
    with arena_lock:
        for bet in arena_state["current_bets"]:
            if bet['username'] == u:
                user_bet = bet
                bet['sid'] = request.sid
                break

    with arena_lock:
        emit('arena_timer', {'time': arena_state["timer"]})
        emit('arena_bets_update', {
            'bets': arena_state["current_bets"],
            'total_bets': len(arena_state["current_bets"])
        })

        emit('arena_big_wins', arena_state["big_wins_history"][:10])

        if arena_state["state"] == "WAITING" and arena_state["initial_balls"]:
            emit('arena_show_initial_balls', {
                'initial_balls': arena_state["initial_balls"]
            })

        if arena_state["state"] == "RUNNING":
            emit('arena_start', {
                'winner_color': arena_state["next_winner"],
                'teams': ARENA_CONFIG["teams_colors"],
                'initial_balls': arena_state["initial_balls"]
            })

            if arena_state["game_data"]["balls"]:
                emit('arena_game_sync', {
                    'balls': arena_state["game_data"]["balls"],
                    'friction': arena_state["game_data"]["friction"],
                    'game_ended': arena_state["game_data"]["game_ended"]
                })

    balance_display = format_currency(user_data['balance'])

    emit('arena_user_data', {
        'username': u,
        'balance': balance_display,
        'avatar': user_data.get('avatar'),
        'has_bet': user_bet is not None,
        'bet_data': user_bet if user_bet else None
    })

@socketio.on('arena_place_bet')
def handle_arena_bet(data):
    u = session.get('user')
    if not u:
        emit('arena_bet_result', {'status': 'error', 'message': 'Not authorized'})
        return

    user_data = get_user(u)
    if not user_data:
        emit('arena_bet_result', {'status': 'error', 'message': 'User not found'})
        return

    lang = user_data['language']

    if user_data['frozen']:
        emit('arena_bet_result', {'status': 'error', 'message': get_translation(lang, 'account_frozen')})
        return

    with arena_lock:
        if arena_state["state"] != "WAITING":
            emit('arena_bet_result', {'status': 'error', 'message': 'Bets closed'})
            return

        amount_value = data.get('amount')
        color = data.get('color')

        amount = calculate_bet_amount(amount_value, user_data['balance'])

        if amount is None:
            emit('arena_bet_result', {'status': 'error', 'message': get_translation(lang, 'min_bet_error')})
            return

        if user_data['balance'] < amount:
            emit('arena_bet_result', {'status': 'error', 'message': get_translation(lang, 'insufficient_funds')})
            return

        user_bet_exists = False
        for bet in arena_state["current_bets"]:
            if bet['username'] == u:
                new_balance = round(user_data['balance'] + bet['amount'], 2)
                update_user_balance(u, new_balance)

                user_bet_exists = True
                bet['amount'] = amount
                bet['color'] = color
                bet['sid'] = request.sid
                break

        if not user_bet_exists:
            new_bet = {
                'username': u,
                'sid': request.sid,
                'amount': amount,
                'color': color,
                'avatar': user_data.get('avatar')
            }
            arena_state["current_bets"].append(new_bet)

        new_balance = round(user_data['balance'] - amount, 2)
        update_user_balance(u, new_balance)

        add_bet_to_pools(amount)

        balance_display = format_currency(new_balance)

        emit('arena_bet_result', {
            'status': 'success', 
            'balance': new_balance,
            'balance_display': balance_display
        })

        socketio.emit('arena_bets_update', {
            'bets': arena_state["current_bets"],
            'total_bets': len(arena_state["current_bets"])
        }, room='arena')

@socketio.on('client_ball_update')
def handle_client_ball_update(data):
    with arena_lock:
        if arena_state["state"] == "RUNNING":
            arena_state["game_data"]["balls"] = data.get('balls', [])
            arena_state["game_data"]["friction"] = data.get('friction', 1.0)
            arena_state["game_data"]["game_ended"] = data.get('game_ended', False)

@socketio.on('client_game_over')
def handle_client_game_over(data):
    finish_arena_game(data['winner'], data['lines_count'])

@socketio.on('refresh_data')
def handle_refresh_data(data):
    if data and 'username' in data:
        user_data = get_user(data['username'])
        if user_data:
            balance_display = format_currency(user_data['balance'])

            emit('arena_user_data', {
                'username': data['username'],
                'balance': balance_display,
                'avatar': user_data.get('avatar')
            })

@socketio.on('bj_join')
def handle_bj_join():
    join_room('blackjack')

@app.route('/arena/status')
def arena_status():
    with arena_lock:
        return jsonify({
            'state': arena_state["state"],
            'timer': arena_state["timer"],
            'winner_color': arena_state.get("next_winner"),
            'current_bets': arena_state["current_bets"],
            'big_wins_history': arena_state["big_wins_history"][:10],
            'initial_balls': arena_state.get("initial_balls", [])
        })

@app.route('/new_login_captcha')
def new_login_captcha():
    lang = session.get('lang', 'en')
    login_captcha = generate_image_captcha(lang)
    session['login_captcha'] = login_captcha
    return jsonify(login_captcha)

@app.route('/new_register_captcha')
def new_register_captcha():
    lang = session.get('lang', 'en')
    register_captcha = generate_image_captcha(lang)
    session['register_captcha'] = register_captcha
    return jsonify(register_captcha)

if __name__ == '__main__':
    if not os.path.exists(STATIC_DIR):
        os.makedirs(STATIC_DIR, exist_ok=True)

    avatars_dir = os.path.join(STATIC_DIR, 'avatars')
    if not os.path.exists(avatars_dir):
        os.makedirs(avatars_dir, exist_ok=True)

    default_avatar = os.path.join(STATIC_DIR, 'default_avatar.png')
    if not os.path.exists(default_avatar):
        try:
            from PIL import Image, ImageDraw

            img = Image.new('RGB', (200, 200), color='#1a0b2e')
            draw = ImageDraw.Draw(img)
            draw.ellipse([50, 50, 150, 150], fill='#bc13fe', outline='#00f2ff', width=3)

            try:
                from PIL import ImageFont
                font = ImageFont.truetype("arial.ttf", 60)
            except:
                font = ImageFont.load_default()

            draw.text((100, 100), 'N', fill='white', anchor='mm', font=font)
            img.save(default_avatar)
        except:
            pass

    # Инициализация БД и пулов
    init_db()
    init_pools()

    # Исправление пользователей с NULL frozen
    from database import fix_frozen_users
    fix_frozen_users()

    # Запуск Arena
    if not arena_state["timer_thread"]:
        arena_state["timer_thread"] = threading.Thread(target=arena_game_loop, daemon=True)
        arena_state["timer_thread"].start()

    print("\n🚀 Starting NEO-PULSE Casino Server...")
    print("📡 Server running on http://0.0.0.0:5000")
    print("🎰 Access locally: http://127.0.0.1:5000")
    print("🌐 Access from network: http://192.168.x.x:5000")
    print("\n✨ Admin panel will open in separate window\n")

    # Запуск сервера в отдельном потоке
    server_thread = threading.Thread(target=lambda: socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True), daemon=True)
    server_thread.start()

    # Даем серверу время на запуск
    time.sleep(2)

    # Запуск админ-панели в главном потоке
    try:
        from admin_panel import AdminPanel
        admin = AdminPanel()
        admin.run()
    except KeyboardInterrupt:
        print("\n❌ Server stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")