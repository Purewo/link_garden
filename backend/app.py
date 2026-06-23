from pathlib import Path
import json
import re
from datetime import datetime
from flask import Flask, jsonify, abort, request
from flask_cors import CORS
import markdown

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / 'data' / 'cards.json'
CONTENT_DIR = BASE_DIR / 'content'
NOTES_DIR = CONTENT_DIR / 'notes'

app = Flask(__name__)
CORS(app)


def load_cards():
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_cards(cards):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r'\s+', '-', text)
    text = re.sub(r'[^a-z0-9\-\u4e00-\u9fff]', '', text)
    text = text.strip('-')
    return text or f'article-{int(datetime.utcnow().timestamp())}'


def build_detail(card):
    detail = dict(card)
    if card.get('category') == 'local':
        md_path = CONTENT_DIR / card['markdown']
        if not md_path.exists():
            abort(404, description='Markdown file not found')
        raw_md = md_path.read_text(encoding='utf-8')
        detail['content'] = raw_md
        lines = raw_md.splitlines()
        if lines and lines[0].startswith('# '):
            raw_md = '\n'.join(lines[1:]).lstrip()
        detail['content_html'] = markdown.markdown(raw_md, extensions=['fenced_code', 'tables'])
    return detail


@app.get('/api/health')
def health():
    return jsonify({'ok': True})


@app.get('/api/cards')
def get_cards():
    include_archived = request.args.get('include_archived', '').lower() in {'1', 'true', 'yes'}
    cards = load_cards()
    if not include_archived:
        cards = [card for card in cards if not card.get('archived', False)]
    return jsonify(cards)


@app.get('/api/cards/<card_id>')
def get_card_detail(card_id):
    cards = load_cards()
    card = next((c for c in cards if c['id'] == card_id), None)
    if not card:
        abort(404, description='Card not found')
    return jsonify(build_detail(card))


@app.get('/api/tags')
def get_tags():
    cards = load_cards()
    tags = sorted({tag for card in cards for tag in card.get('tags', [])})
    return jsonify(tags)


@app.post('/api/publish')
def publish_article():
    data = request.get_json(silent=True) or {}
    category = (data.get('category') or '').strip()
    title = (data.get('title') or '').strip()
    summary = (data.get('summary') or '').strip()
    tags = data.get('tags') or []
    cover = (data.get('cover') or '').strip()

    if category not in {'external', 'local'}:
        return jsonify({'ok': False, 'error': 'category must be external or local'}), 400
    if not title:
        return jsonify({'ok': False, 'error': 'title is required'}), 400
    if not isinstance(tags, list):
        return jsonify({'ok': False, 'error': 'tags must be a list'}), 400

    cards = load_cards()
    card_id = slugify(data.get('id') or title)
    existing_ids = {card['id'] for card in cards}
    original_id = card_id
    idx = 2
    while card_id in existing_ids:
        card_id = f'{original_id}-{idx}'
        idx += 1

    card = {
        'id': card_id,
        'title': title,
        'category': category,
        'summary': summary,
        'tags': tags,
        'cover': cover,
        'created_at': datetime.utcnow().strftime('%Y-%m-%d'),
        'archived': False,
    }

    if category == 'external':
        url = (data.get('url') or '').strip()
        if not url:
            return jsonify({'ok': False, 'error': 'url is required for external article'}), 400
        card['url'] = url
    else:
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'ok': False, 'error': 'content is required for local article'}), 400
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        md_rel_path = f'notes/{card_id}.md'
        md_path = CONTENT_DIR / md_rel_path
        md_path.write_text(content, encoding='utf-8')
        card['markdown'] = md_rel_path

    cards.insert(0, card)
    save_cards(cards)
    return jsonify({'ok': True, 'card': card})


@app.put('/api/cards/<card_id>')
def update_article(card_id):
    data = request.get_json(silent=True) or {}
    cards = load_cards()
    idx = next((i for i, c in enumerate(cards) if c['id'] == card_id), None)
    if idx is None:
        return jsonify({'ok': False, 'error': 'card not found'}), 404

    card = cards[idx]
    card['title'] = (data.get('title') or card.get('title') or '').strip()
    card['summary'] = (data.get('summary') or '').strip()
    card['cover'] = (data.get('cover') or '').strip()
    tags = data.get('tags')
    if isinstance(tags, list):
        card['tags'] = tags

    category = (data.get('category') or card.get('category') or '').strip()
    if category not in {'external', 'local'}:
        return jsonify({'ok': False, 'error': 'category must be external or local'}), 400
    card['category'] = category

    if category == 'external':
        url = (data.get('url') or '').strip()
        if not url:
            return jsonify({'ok': False, 'error': 'url is required for external article'}), 400
        card['url'] = url
        if 'markdown' in card:
            md_path = CONTENT_DIR / card['markdown']
            if md_path.exists():
                md_path.unlink()
            card.pop('markdown', None)
    else:
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'ok': False, 'error': 'content is required for local article'}), 400
        md_rel_path = card.get('markdown') or f'notes/{card_id}.md'
        md_path = CONTENT_DIR / md_rel_path
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(content, encoding='utf-8')
        card['markdown'] = md_rel_path
        card.pop('url', None)

    cards[idx] = card
    save_cards(cards)
    return jsonify({'ok': True, 'card': card})


@app.patch('/api/cards/<card_id>/archive')
def archive_article(card_id):
    data = request.get_json(silent=True) or {}
    archived = data.get('archived', True)
    cards = load_cards()
    idx = next((i for i, c in enumerate(cards) if c['id'] == card_id), None)
    if idx is None:
        return jsonify({'ok': False, 'error': 'card not found'}), 404

    card = cards[idx]
    card['archived'] = bool(archived)
    cards[idx] = card
    save_cards(cards)
    return jsonify({'ok': True, 'card': card})


@app.delete('/api/cards/<card_id>')
def delete_article(card_id):
    cards = load_cards()
    idx = next((i for i, c in enumerate(cards) if c['id'] == card_id), None)
    if idx is None:
        return jsonify({'ok': False, 'error': 'card not found'}), 404
    card = cards.pop(idx)
    if card.get('category') == 'local' and card.get('markdown'):
        md_path = CONTENT_DIR / card['markdown']
        if md_path.exists():
            md_path.unlink()
    save_cards(cards)
    return jsonify({'ok': True})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
