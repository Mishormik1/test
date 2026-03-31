from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import json
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'baikal_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

def process_text(text: str) -> str:
    if not isinstance(text, str): return text
    # Ссылки
    url_pattern = re.compile(r'(https?://[^\s<]+)', re.IGNORECASE)
    text = url_pattern.sub(r'<a href="\1" target="_blank" class="auto-link">\1</a>', text)
    # Цвета
    color_map = {'%g': '#4caf50', '%r': '#f44336', '%b': '#38bdf8', '%w': '#ffffff'}
    text = text.replace('%0', '</span>')
    for code, color in color_map.items():
        text = text.replace(code, f'<span style="color: {color};">')
    return text

def process_config(config: dict) -> dict:
    res = config.copy()
    res['title'] = process_text(res.get('title', ''))
    for card in res.get('cards', []):
        card['title'] = process_text(card.get('title', ''))
        card['description'] = process_text(card.get('description', ''))
        for d in card.get('details', []):
            d['title'] = process_text(d.get('title', ''))
            d['text'] = process_text(d.get('text', ''))
    return res

@app.route('/')
def index():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            config = process_config(data)
    except Exception as e:
        config = {"title": "Ошибка", "cards": [], "categories": []}
    return render_template('index.html', config=config)

@app.route('/admin')
def admin_panel():
    return render_template('admin_chat.html')

# Логика чата
@socketio.on('message_to_server')
def handle_message(data):
    # data['sender'] может быть 'user' или 'admin'
    emit('message_to_client', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')