import os
import re
import json
import secrets
import logging
import base64
import datetime
import mimetypes
import zipfile
import io
import sqlite3
from html import escape as html_escape

import requests
from flask import (Flask, request, render_template, jsonify, Response,
                   stream_with_context, session, send_file)
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup, Comment
from werkzeug.security import generate_password_hash, check_password_hash

from db import init_db, get_db

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', secrets.token_hex(32))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EULA_VERSION = "1.3"
PRIVACY_VERSION = "1.3"
P3_MODEL = "p3"
P3_BASE_MODEL = "gemma4:12b"
P4_FAX_MODEL = "p4-fax"
P4_FAX_BASE_MODEL = "gemma4:26b"
P4_CANDOR_MODEL = "p4-candor"
P4_CANDOR_BASE_MODEL = "gemma4:31b"
P4_RELEASE_DATE = None
MAX_MULTIMODAL_ITEM_CHARS = 24_000_000
WORKSPACE_MAX_CONTENT_BYTES = 1_000_000
WORKSPACE_EDITABLE_EXTENSIONS = {'.txt', '.md', '.html', '.htm'}

P4_MODES = (P4_FAX_MODEL, P4_CANDOR_MODEL)
MODEL_CATALOG = (
    {
        "id": "p2-2.9",
        "label": "Poinsettia 2.9",
        "mode": "p2",
        "release_date": None,
        "status": "released",
    },
    {
        "id": "p3-3.9",
        "label": "Poinsettia 3.9",
        "mode": "p3",
        "release_date": None,
        "status": "released",
    },
    {
        "id": P4_FAX_MODEL,
        "label": "Poinsettia 4.0 “Fax”",
        "mode": P4_FAX_MODEL,
        "release_date": None,
        "status": "released",
    },
    {
        "id": P4_CANDOR_MODEL,
        "label": "Poinsettia 4.0 “Candor”",
        "mode": P4_CANDOR_MODEL,
        "release_date": None,
        "status": "released",
    },
)


def p4_is_released(today=None):
    """Poinsettia 4.0 is available immediately in the current release."""
    return True


def mode_is_available(mode, today=None):
    return mode in VALID_CONVERSATION_MODES


def client_model_catalog(today=None):
    return [
        dict(
            item,
            status="released",
        )
        for item in MODEL_CATALOG
    ]

# ── Init ───────────────────────────────────────────────────────────────────────
os.makedirs('user_files', exist_ok=True)
init_db()

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; Poinsettia/3.9)'}

CATEGORY_SOURCES = {
    'news': {
        'domains': ['apnews.com', 'bbc.com', 'reuters.com', 'theguardian.com', 'npr.org', 'politico.com'],
        'wikipedia': False, 'ddg_instant': False,
    },
    'science': {
        'domains': ['ncbi.nlm.nih.gov', 'nature.com', 'wikipedia.org', 'sciencedaily.com', 'newscientist.com'],
        'wikipedia': True, 'ddg_instant': True,
    },
    'technology': {
        'domains': ['stackoverflow.com', 'developer.mozilla.org', 'wikipedia.org', 'techcrunch.com', 'arstechnica.com'],
        'wikipedia': True, 'ddg_instant': True,
    },
    'sports': {
        'domains': ['apnews.com', 'bbc.com', 'espn.com', 'reuters.com', 'cbssports.com'],
        'wikipedia': False, 'ddg_instant': False,
    },
    'finance': {
        'domains': ['reuters.com', 'apnews.com', 'investopedia.com', 'marketwatch.com', 'cnbc.com'],
        'wikipedia': False, 'ddg_instant': True,
    },
    'politics': {
        'domains': ['apnews.com', 'reuters.com', 'bbc.com', 'politico.com', '.gov'],
        'wikipedia': False, 'ddg_instant': False,
    },
    'entertainment': {
        'domains': ['wikipedia.org', 'apnews.com', 'variety.com', 'hollywoodreporter.com', 'rottentomatoes.com'],
        'wikipedia': True, 'ddg_instant': True,
    },
    'health': {
        'domains': ['ncbi.nlm.nih.gov', 'webmd.com', 'mayoclinic.org', 'healthline.com', 'cdc.gov'],
        'wikipedia': True, 'ddg_instant': True,
    },
    'general': {
        'domains': ['wikipedia.org', 'britannica.com', 'stackoverflow.com', 'reddit.com',
                    '.gov', '.edu', 'bbc.com', 'reuters.com', 'apnews.com', 'nature.com'],
        'wikipedia': True, 'ddg_instant': True,
    },
}

# ── Utilities ─────────────────────────────────────────────────────────────────

def get_logo_base64():
    try:
        with open('static/poinsettia-logo.png', 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error loading logo: {e}")
        return ""

def check_internet():
    try:
        requests.get("https://www.google.com", timeout=5, headers=HEADERS)
        return True
    except Exception:
        return False

def get_current_user():
    """Return the logged-in user dict, or None for guests."""
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    user_columns = {
        row['name'] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    optional_user_columns = {
        'privacy_agreed': '0',
        'privacy_version': 'NULL',
        'privacy_consented_at': 'NULL',
    }
    selected_optional_columns = [
        column if column in user_columns else f'{fallback} AS {column}'
        for column, fallback in optional_user_columns.items()
    ]
    row = db.execute(
        '''SELECT id, username, age_confirmed, eula_reviewed, eula_agreed,
                  eula_version, consented_at, {optional_columns}
           FROM users WHERE id = ?'''.format(
            optional_columns=', '.join(selected_optional_columns)
        ),
        (uid,)
    ).fetchone()
    db.close()
    if not row:
        return None

    user = dict(row)
    user['age_confirmed'] = bool(user['age_confirmed'])
    user['eula_reviewed'] = bool(user['eula_reviewed'])
    user['eula_agreed'] = bool(user['eula_agreed'])
    user['privacy_agreed'] = bool(user['privacy_agreed'])
    user['eula_current'] = (
        user['eula_reviewed']
        and user['eula_agreed']
        and user['eula_version'] == EULA_VERSION
    )
    # Databases created before privacy consent tracking was introduced do not
    # have enough information to require a privacy re-review. Migrated
    # databases have these columns and use the versioned check below.
    privacy_tracking_available = {
        'privacy_agreed', 'privacy_version'
    }.issubset(user_columns)
    user['privacy_current'] = (
        not privacy_tracking_available
        or (
            user['privacy_agreed']
            and user['privacy_version'] == PRIVACY_VERSION
        )
    )
    user['privacy_update_required'] = not user['privacy_current']
    # Accounts created before consent tracking have no version to compare.
    # Keep them usable for the initial agreement, but make them participate in
    # the re-acceptance flow as soon as the agreement version advances.
    legacy_initial_eula = not user['eula_version'] and EULA_VERSION == "1.0"
    user['eula_update_required'] = not user['eula_current'] and not legacy_initial_eula
    return user

def ensure_guest_key():
    """Lazily assign a stable guest key to anonymous sessions."""
    if 'guest_key' not in session:
        session['guest_key'] = secrets.token_hex(16)
    return session['guest_key']

def auth_required_response():
    return jsonify({
        'error': 'Sign in is required to use Poinsettia services.',
        'auth_required': True,
    }), 401


def eula_update_required_response():
    return jsonify({
        'error': 'Please review and accept the current EULA before using Poinsettia services.',
        'eula_update_required': True,
        'eula_version': EULA_VERSION,
    }), 403


def privacy_update_required_response():
    return jsonify({
        'error': 'Please review and accept the current Privacy Policy before using Poinsettia services.',
        'privacy_update_required': True,
        'privacy_version': PRIVACY_VERSION,
    }), 403


def require_authenticated_user():
    """Return a JSON response when a service request is not authorized."""
    user = get_current_user()
    if not user:
        return auth_required_response()
    if user['eula_update_required']:
        return eula_update_required_response()
    if user['privacy_update_required']:
        return privacy_update_required_response()
    return None


def prepare_ollama_messages(messages, allow_audio=True):
    """Validate and normalize text, image, and WAV audio chat messages.

    Ollama's current Gemma 4 API accepts visual input through ``images``.
    Gemma 4 audio is represented as a base64 WAV payload in that same field;
    the model/runtime identifies the RIFF/WAVE payload and routes it through
    its native audio path.  Accepting ``audio`` as an input alias keeps the
    server compatible with clients that use the more descriptive field name.
    """
    if not isinstance(messages, list):
        raise ValueError('Messages must be a list.')

    normalized = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        if role not in ('system', 'user', 'assistant'):
            continue
        content = message.get('content', '')
        if not isinstance(content, str):
            content = str(content or '')
        cleaned = {'role': role, 'content': content}

        image_values = message.get('images', [])
        audio_values = message.get('audio', [])
        if isinstance(image_values, str):
            image_values = [image_values]
        if isinstance(audio_values, str):
            audio_values = [audio_values]
        if not isinstance(image_values, list) or not isinstance(audio_values, list):
            raise ValueError('Multimodal attachments must be lists.')
        if not allow_audio:
            attachment_metadata = message.get('attachments', [])
            if isinstance(attachment_metadata, dict):
                attachment_metadata = [attachment_metadata]
            if any(
                isinstance(item, dict) and item.get('kind') == 'audio'
                for item in attachment_metadata
            ):
                raise ValueError('This Poinsettia 4 model supports image attachments, not audio.')

        attachments = []
        for item in list(image_values) + list(audio_values):
            if isinstance(item, dict):
                item = item.get('data')
            if not isinstance(item, str) or not item.strip():
                raise ValueError('Multimodal attachments must be base64 strings.')
            if len(item) > MAX_MULTIMODAL_ITEM_CHARS:
                raise ValueError('An image or audio attachment is too large.')
            attachments.append(item)
        if attachments:
            # Ollama/Gemma 4 uses this field for both image bytes and WAV
            # audio bytes.  Do not send UI-only attachment metadata upstream.
            cleaned['images'] = attachments
        normalized.append(cleaned)
    if not normalized:
        raise ValueError('No valid messages provided.')
    return normalized

# ── File helpers ───────────────────────────────────────────────────────────────

def _file_dir(user_id=None, guest_key=None):
    if user_id:
        d = os.path.join('user_files', str(user_id))
    else:
        d = os.path.join('user_files', f'guest_{guest_key}')
    os.makedirs(d, exist_ok=True)
    return d

def _mime_for(filename):
    mime, _ = mimetypes.guess_type(filename)
    return mime or 'application/octet-stream'


def sanitize_workspace_html(markup):
    """Keep only safe document formatting when loading or saving workspace content."""
    soup = BeautifulSoup(markup or '', 'html.parser')
    container = soup.body or soup
    for comment in container.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    forbidden_tags = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math',
                      'img', 'video', 'audio', 'source', 'form', 'input', 'button'}
    for tag in list(container.find_all(forbidden_tags)):
        tag.decompose()

    allowed_tags = {
        'a', 'b', 'blockquote', 'br', 'code', 'del', 'div', 'em', 'h1', 'h2',
        'h3', 'h4', 'h5', 'h6', 'i', 'li', 'ol', 'p', 'pre', 's', 'span',
        'strike', 'strong', 'sub', 'sup', 'u', 'ul',
    }
    for tag in list(container.find_all(True)):
        if tag.name not in allowed_tags:
            tag.unwrap()
            continue

        safe_attrs = {}
        if tag.name == 'a':
            href = str(tag.get('href', '')).strip()
            parsed = urlparse(href)
            if parsed.scheme.lower() in {'http', 'https', 'mailto'} or (
                not parsed.scheme and href.startswith(('/', '#', './', '../'))
            ):
                safe_attrs['href'] = href

        declarations = []
        alignment = str(tag.get('align', '')).lower()
        if alignment in {'left', 'center', 'right', 'justify'}:
            declarations.append(f'text-align: {alignment}')
        for declaration in str(tag.get('style', '')).split(';'):
            if ':' not in declaration:
                continue
            property_name, value = (part.strip() for part in declaration.split(':', 1))
            property_name = property_name.lower()
            value = value.strip()
            if property_name == 'font-family' and re.fullmatch(r"[A-Za-z0-9 ,_'\".-]{1,80}", value):
                declarations.append(f'font-family: {value}')
            elif property_name == 'font-size':
                match = re.fullmatch(r'(\d+(?:\.\d+)?)(px|pt|em|rem)', value)
                if match and 6 <= float(match.group(1)) <= 96:
                    declarations.append(f'font-size: {value}')
            elif property_name == 'text-align' and value.lower() in {
                'left', 'center', 'right', 'justify',
            }:
                declarations.append(f'text-align: {value.lower()}')
            elif property_name in {'color', 'background-color'} and re.fullmatch(
                r'#[0-9a-fA-F]{3,8}', value
            ):
                declarations.append(f'{property_name}: {value.lower()}')
        if declarations:
            safe_attrs['style'] = '; '.join(declarations)
        tag.attrs = safe_attrs

    return ''.join(str(child) for child in container.contents)


def save_p3_file(name, content, user_id=None, guest_key=None):
    """
    Write `content` to disk and record it in the DB.
    Returns a dict with id/name/size for the SSE event, or None on failure.
    """
    try:
        # Sanitise filename
        safe_name = re.sub(r'[^\w.\-]', '_', name.strip())[:120] or 'file.txt'
        directory = _file_dir(user_id=user_id, guest_key=guest_key)
        # Avoid collisions
        base, ext = os.path.splitext(safe_name)
        candidate = safe_name
        counter = 1
        while os.path.exists(os.path.join(directory, candidate)):
            candidate = f"{base}_{counter}{ext}"
            counter += 1
        path = os.path.join(directory, candidate)

        # If the name ends with .zip the content might itself be a zip;
        # otherwise write as text.
        if ext.lower() == '.zip':
            # Build a zip containing a single text file named after the base
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                inner_name = base + '.txt' if not os.path.splitext(base)[1] else base
                zf.writestr(inner_name, content.encode('utf-8'))
            buf.seek(0)
            with open(path, 'wb') as f:
                f.write(buf.read())
            size = os.path.getsize(path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            size = os.path.getsize(path)

        mime = _mime_for(candidate)
        db = get_db()
        cur = db.execute(
            'INSERT INTO files (user_id, session_key, name, mime_type, path, size) VALUES (?,?,?,?,?,?)',
            (user_id, guest_key, candidate, mime, path, size)
        )
        file_id = cur.lastrowid
        db.commit()
        db.close()
        return {'id': file_id, 'name': candidate, 'size': size, 'mime': mime}
    except Exception as e:
        logger.error(f"save_p3_file error: {e}")
        return None


def extract_files_from_text(text, user_id=None, guest_key=None):
    """
    Scan `text` for <<<FILE:name>>>\ncontent\n<<<ENDFILE>>> sentinels.
    Creates each file, returns (cleaned_text, [file_info_dicts]).
    """
    FILE_START_RE = re.compile(r'<<<FILE:([^>]+)>>>', re.DOTALL)
    FILE_END = '<<<ENDFILE>>>'
    file_infos = []
    result = text

    while True:
        m = FILE_START_RE.search(result)
        if not m:
            break
        name = m.group(1).strip()
        content_start = m.end()
        # Skip leading newline
        if content_start < len(result) and result[content_start] == '\n':
            content_start += 1
        end_idx = result.find(FILE_END, content_start)
        if end_idx == -1:
            # Unclosed sentinel — strip marker only
            result = result[:m.start()] + result[m.end():]
            break
        content = result[content_start:end_idx]
        # Strip trailing newline before <<<ENDFILE>>>
        if content.endswith('\n'):
            content = content[:-1]
        after = end_idx + len(FILE_END)
        # Remove sentinel block from text
        result = result[:m.start()] + result[after:]
        # Save file
        info = save_p3_file(name, content, user_id=user_id, guest_key=guest_key)
        if info:
            file_infos.append(info)

    return result.strip(), file_infos


# ── Web Scrapers ───────────────────────────────────────────────────────────────

def fetch_wikipedia(query):
    try:
        search = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={'action': 'query', 'list': 'search', 'srsearch': query,
                    'format': 'json', 'srlimit': 1},
            headers=HEADERS, timeout=8
        ).json()
        hits = search.get('query', {}).get('search', [])
        if not hits:
            return ""
        title = hits[0]['title']
        summary = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
            headers=HEADERS, timeout=8
        ).json()
        extract = summary.get('extract', '')
        if extract:
            return f"[Wikipedia — {title}]\n{extract[:1500]}"
    except Exception as e:
        logger.warning(f"Wikipedia fetch failed: {e}")
    return ""

def fetch_duckduckgo_instant(query):
    try:
        data = requests.get(
            "https://api.duckduckgo.com/",
            params={'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1},
            headers=HEADERS, timeout=8
        ).json()
        result = data.get('Answer', '') or data.get('AbstractText', '')
        source = data.get('AbstractURL', '') or 'DuckDuckGo'
        if result:
            return f"[{source}]\n{result[:1000]}"
    except Exception as e:
        logger.warning(f"DuckDuckGo instant failed: {e}")
    return ""

def scrape_url(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        return text[:1800]
    except Exception as e:
        logger.warning(f"Scrape failed for {url}: {e}")
    return ""

_JUNK_DOMAINS = {
    'pinterest.com', 'instagram.com', 'facebook.com', 'twitter.com', 'x.com',
    'tiktok.com', 'youtube.com', 'amazon.com', 'ebay.com', 'etsy.com',
    'yelp.com', 'tripadvisor.com', 'linkedin.com', 'quora.com',
}

def fetch_duckduckgo_web(query, domains=None):
    preferred = set(domains) if domains else set()
    all_urls = []
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={'q': query},
            headers=HEADERS,
            timeout=10
        )
        soup = BeautifulSoup(resp.text, 'html.parser')
        for link_tag in soup.select('.result__a'):
            href = link_tag.get('href', '')
            if 'uddg=' in href:
                try:
                    actual_url = unquote(href.split('uddg=')[-1].split('&')[0])
                except Exception:
                    continue
            elif href.startswith('http'):
                actual_url = href
            else:
                continue
            if not any(junk in actual_url for junk in _JUNK_DOMAINS):
                all_urls.append(actual_url)
            if len(all_urls) >= 6:
                break
    except Exception as e:
        logger.warning(f"DuckDuckGo HTML search failed: {e}")
        return []

    all_urls.sort(key=lambda u: 0 if any(d in u for d in preferred) else 1)

    results = []
    source_urls = []
    for url in all_urls:
        if len(results) >= 2:
            break
        content = scrape_url(url)
        if content:
            label = next((d for d in preferred if d in url), url.split('/')[2] if '://' in url else url)
            results.append(f"[{label} — {url[:80]}]\n{content}")
            source_urls.append(url)
    return results, source_urls

def classify_query(query):
    categories = list(CATEGORY_SOURCES.keys())
    prompt = (
        "Classify the user's query into exactly one of these categories: "
        f"{', '.join(categories)}.\n\n"
        "Rules:\n"
        "- Government agencies (EPA, FDA, CIA, FBI, Pentagon, NASA missions) → politics\n"
        "- Politicians, elections, laws, policy, presidents, prime ministers → politics\n"
        "- Breaking news, current events, disasters, fires, wars, attacks → news\n"
        "- Medical symptoms, drugs, diseases, public health → health\n"
        "- Scientific research, climate data, biology, physics, chemistry → science\n"
        "- Programming, software, hardware, AI tools, apps → technology\n"
        "- Stocks, crypto, interest rates, inflation, GDP → finance\n"
        "- Movies, TV shows, music, celebrities, games, books → entertainment\n"
        "- Sports scores, teams, athletes, leagues → sports\n"
        "- Anything else → general\n\n"
        "Reply with only the single category word — nothing else."
    )
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "poinsettia",
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": query}
                ],
                "stream": False,
                "options": {"num_predict": 5}
            },
            timeout=20
        ).json()
        raw = resp.get('message', {}).get('content', '').strip().lower()
        for cat in categories:
            if cat in raw:
                logger.info(f"Query classified as: {cat}")
                return cat
    except Exception as e:
        logger.warning(f"Query classification failed: {e}")
    return quick_classify(query)

def quick_classify(query):
    q = query.lower()
    if any(w in q for w in ['news','latest','breaking','wildfire','fire','flood','earthquake','hurricane','war','attack','conflict','strike','invasion','shooting','crash']):
        return 'news'
    if any(w in q for w in ['president','election','congress','senate','parliament','prime minister','governor','politician','policy','law','bill','vote','epa','fda','fbi','cia','pentagon','nato','government','administration']):
        return 'politics'
    if any(w in q for w in ['stock','bitcoin','crypto','market','price','inflation','gdp','interest rate','recession','nasdaq','dow','s&p','earnings','revenue','ipo']):
        return 'finance'
    if any(w in q for w in ['nba','nfl','mlb','nhl','fifa','score','match','game','championship','player','team','league','tournament','athlete','sport']):
        return 'sports'
    if any(w in q for w in ['movie','film','show','series','album','song','celebrity','actor','director','musician','grammy','oscar','netflix','disney','release','box office']):
        return 'entertainment'
    if any(w in q for w in ['symptom','treatment','disease','drug','vaccine','health','medicine','cancer','virus','hospital','doctor','clinical','fda approval','medication']):
        return 'health'
    if any(w in q for w in ['code','programming','software','error','bug','python','javascript','api','library','framework','developer','github','database','algorithm']):
        return 'technology'
    if any(w in q for w in ['study','research','climate','biology','physics','chemistry','astronomy','geology','experiment','journal','scientist','discovery']):
        return 'science'
    return 'general'

def search_and_scrape(query, category='general'):
    sources = CATEGORY_SOURCES.get(category, CATEGORY_SOURCES['general'])
    parts = []
    all_source_urls = []

    if sources['wikipedia']:
        wiki = fetch_wikipedia(query)
        if wiki:
            parts.append(wiki)
    if sources['ddg_instant']:
        ddg_instant = fetch_duckduckgo_instant(query)
        if ddg_instant:
            parts.append(ddg_instant)
    web_pages, urls = fetch_duckduckgo_web(query, domains=sources['domains'])
    parts.extend(web_pages)
    all_source_urls.extend(urls)
    combined = "\n\n".join(parts)

    if not combined.strip() and category != 'general':
        logger.warning(f"No context for category '{category}', retrying with general sources")
        fallback_pages, fallback_urls = fetch_duckduckgo_web(query, domains=None)
        wiki_fallback = fetch_wikipedia(query)
        fallback_parts = ([wiki_fallback] if wiki_fallback else []) + fallback_pages
        all_source_urls.extend(fallback_urls)
        combined = "\n\n".join(fallback_parts)

    return combined[:1200], all_source_urls

# ── Hidden Command Interception ────────────────────────────────────────────────

def fetch_weather(city):
    NWS_H = {'User-Agent': 'Poinsettia/3.0 (contact@poinsettia.ai)',
              'Accept': 'application/geo+json'}
    NOM_H = {'User-Agent': 'Poinsettia/3.0 (contact@poinsettia.ai)'}
    try:
        geo = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={'q': city, 'format': 'json', 'limit': 1},
            headers=NOM_H, timeout=10
        ).json()
        if not geo:
            logger.warning(f"Nominatim: no results for '{city}'")
            return None
        lat = float(geo[0]['lat'])
        lon = float(geo[0]['lon'])

        pts = requests.get(
            f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}",
            headers=NWS_H, timeout=10
        ).json()
        props = pts.get('properties', {})
        rel = props.get('relativeLocation', {}).get('properties', {})
        city_name    = rel.get('city', city)
        state        = rel.get('state', '')
        stations_url = props.get('observationStations')
        if not stations_url:
            return None

        stns       = requests.get(stations_url, headers=NWS_H, timeout=10).json()
        station_id = stns['features'][0]['properties']['stationIdentifier']

        obs = requests.get(
            f"https://api.weather.gov/stations/{station_id}/observations/latest",
            headers=NWS_H, timeout=10
        ).json().get('properties', {})

        temp_c = obs.get('temperature', {}).get('value')
        if temp_c is None:
            return None
        temp_f   = round(temp_c * 9/5 + 32)
        temp_c   = round(temp_c)
        raw_feel = (obs.get('windChill', {}).get('value')
                    or obs.get('heatIndex', {}).get('value')
                    or temp_c)
        feels_f  = round(raw_feel * 9/5 + 32)
        feels_c  = round(raw_feel)
        humidity = round(obs.get('relativeHumidity', {}).get('value') or 0)
        wind_ms  = obs.get('windSpeed', {}).get('value') or 0
        wind_mph = round(wind_ms * 2.237)
        desc     = obs.get('textDescription', 'Unknown')

        return {
            'city':        city_name,
            'country':     state,
            'temp_f':      temp_f,
            'temp_c':      temp_c,
            'feels_f':     feels_f,
            'feels_c':     feels_c,
            'humidity':    humidity,
            'wind_mph':    wind_mph,
            'description': desc,
        }
    except Exception as e:
        logger.warning(f"NWS weather fetch failed for '{city}': {e}")
        return None

_WEEKDAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
_DATE_NOISE = re.compile(
    r'\b(today|tonight|now|tomorrow|day after tomorrow|overmorrow'
    r'|in \d+ days?|next\s+\w+'
    r'|' + '|'.join(_WEEKDAYS) + r')\b',
    re.IGNORECASE
)

def parse_weather_query(text):
    t = text.lower()
    days_offset = 0

    m = re.search(r'\bin\s+(\d+)\s+days?\b', t)
    if m:
        days_offset = int(m.group(1))
    elif re.search(r'\bday after tomorrow\b|\bovermorrow\b', t):
        days_offset = 2
    elif 'tomorrow' in t:
        days_offset = 1
    else:
        today_wd = datetime.date.today().weekday()
        for i, day in enumerate(_WEEKDAYS):
            if re.search(r'\bnext\s+' + day + r'\b', t):
                diff = (i - today_wd) % 7 or 7
                days_offset = diff; break
            elif re.search(r'\b' + day + r'\b', t):
                diff = (i - today_wd) % 7 or 7
                days_offset = diff; break

    city_text = _DATE_NOISE.sub('', text).strip()
    city = _extract_city(city_text)
    return city, days_offset

def _extract_city(text):
    m = re.search(r'\bweather\s+(?:in|for|at|of)\s+([a-zA-Z][a-zA-Z\s,]{1,40}?)(?:\?|\.|\s*$)', text, re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(r'\bweather\s+([a-zA-Z][a-zA-Z\s,]{1,40}?)(?:\?|\.|\s*$)', text, re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(r'\b([a-zA-Z][a-zA-Z\s]{1,30}?)\s+weather\b', text, re.IGNORECASE)
    if m: return m.group(1).strip()
    return None

def fetch_weather_forecast(city, days_offset):
    if days_offset == 0:
        data = fetch_weather(city)
        if data:
            data.update({'forecast': False, 'period_name': 'Now', 'beyond_7': False})
        return data

    NWS_H = {'User-Agent': 'Poinsettia/3.0 (contact@poinsettia.ai)', 'Accept': 'application/geo+json'}
    NOM_H = {'User-Agent': 'Poinsettia/3.0 (contact@poinsettia.ai)'}
    beyond_7 = days_offset > 7

    try:
        geo = requests.get('https://nominatim.openstreetmap.org/search',
            params={'q': city, 'format': 'json', 'limit': 1},
            headers=NOM_H, timeout=10).json()
        if not geo: return None
        lat, lon = float(geo[0]['lat']), float(geo[0]['lon'])

        pts = requests.get(f'https://api.weather.gov/points/{lat:.4f},{lon:.4f}',
            headers=NWS_H, timeout=10).json()
        props = pts.get('properties', {})
        rel   = props.get('relativeLocation', {}).get('properties', {})
        city_name    = rel.get('city', city)
        state        = rel.get('state', '')
        forecast_url = props.get('forecast')
        if not forecast_url: return None

        periods = requests.get(forecast_url, headers=NWS_H, timeout=10).json() \
                          .get('properties', {}).get('periods', [])
        if not periods: return None

        target_date = datetime.date.today() + datetime.timedelta(days=days_offset)
        period = next(
            (p for p in periods
             if datetime.date.fromisoformat(p['startTime'][:10]) == target_date
             and p.get('isDaytime', True)),
            None
        )
        if not period:
            period = next(
                (p for p in periods
                 if datetime.date.fromisoformat(p['startTime'][:10]) == target_date),
                None
            )
        if not period:
            period = periods[-1]
            beyond_7 = True

        temp_f = period.get('temperature', 0)
        temp_c = round((temp_f - 32) * 5 / 9)
        desc   = period.get('shortForecast', 'Unknown')
        period_name = period.get('name', f'Day {days_offset}')
        wind_str    = period.get('windSpeed', '')

        return {
            'city':        city_name,
            'country':     state,
            'temp_f':      temp_f,
            'temp_c':      temp_c,
            'feels_f':     temp_f,
            'feels_c':     temp_c,
            'humidity':    0,
            'wind_mph':    0,
            'wind_str':    wind_str,
            'description': desc,
            'forecast':    True,
            'period_name': period_name,
            'beyond_7':    beyond_7,
            'days_offset': days_offset,
        }
    except Exception as e:
        logger.warning(f"NWS forecast failed for '{city}' day {days_offset}: {e}")
        return None

_SKIP_SEARCH = re.compile(
    r'^\s*('
    r'hi+|hello+|hey+|howdy|greetings|good (morning|afternoon|evening|night)|'
    r'what\'?s up|how are you(\s+doing)?|how\'?s it going|'
    r'thank(s| you)( so much| a lot)?|you\'?re welcome|np|no problem|'
    r'ok(ay)?|sure|got it|sounds good|great|cool|nice|awesome|perfect|'
    r'bye+|goodbye|see you( later)?|take care|later|'
    r'(hi|hey|hello)[,!.]?\s*(there|poinsettia|friend)?'
    r')\s*[!?.,]*\s*$'
    r'|'
    r'^\s*(hi|hey|hello)[^.!?]{0,40}how are you[^.!?]{0,30}\???\s*$'
    r'|'
    r'^\s*(write|compose|create|generate|draft|make|give me|tell me)\s+(me\s+)?(a|an|some|the)\s+'
    r'(poem|haiku|sonnet|story|short story|essay|paragraph|joke|riddle|recipe|'
    r'list|title|titles|summary|outline|letter|email|caption|lyrics|song|script)',
    re.IGNORECASE
)

def generate_commands(messages):
    last_user = next(
        (m.get('content', '') for m in reversed(messages) if m.get('role') == 'user'), ''
    )

    direct_city, days_offset = parse_weather_query(last_user)
    if direct_city:
        logger.info(f"P3 weather: '{direct_city}' day+{days_offset}")
        return [], (direct_city, days_offset)

    if _SKIP_SEARCH.search(last_user):
        logger.info(f"P3 skip search for: {last_user[:80]}")
        return [], None

    logger.info(f"P3 search triggered for: {last_user[:80]}")
    return [last_user], None

def strip_search_commands(text):
    text = re.sub(r'\[?SEARCH:\s*.+?(\]|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[?WEATHER:\s*.+?(\]|$)', '', text, flags=re.IGNORECASE)
    return text

# ── Flask Routes ───────────────────────────────────────────────────────────────

@app.before_request
def _ensure_guest_key():
    ensure_guest_key()

@app.after_request
def add_cache_control(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/")
def home():
    return render_template("home.html", logo_base64=get_logo_base64())

@app.route("/favicon.ico")
def favicon():
    return send_file(
        os.path.join(app.static_folder, "favicon.ico"),
        mimetype="image/vnd.microsoft.icon",
    )

@app.route("/chat")
def chat_page():
    return render_template(
        "index.html",
        logo_base64=get_logo_base64(),
        auth_required=get_current_user() is None,
        eula_version=EULA_VERSION,
        privacy_version=PRIVACY_VERSION,
        model_catalog=client_model_catalog(),
    )

@app.route("/documentation")
def documentation():
    license_path = os.path.join(app.static_folder, "apache-2.0.txt")
    with open(license_path, encoding="utf-8") as license_file:
        apache_license = license_file.read()
    return render_template(
        "documentation.html",
        logo_base64=get_logo_base64(),
        apache_license=apache_license,
    )

@app.route("/documentation/getting-started")
def documentation_getting_started():
    return render_template(
        "documentation-guide.html",
        logo_base64=get_logo_base64(),
        page_type="getting-started",
    )

@app.route("/documentation/free-access")
def documentation_free_access():
    return render_template(
        "documentation-guide.html",
        logo_base64=get_logo_base64(),
        page_type="free-access",
    )

@app.route("/eula")
def eula():
    return render_template(
        "eula.html",
        logo_base64=get_logo_base64(),
        eula_version=EULA_VERSION,
    )

@app.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        logo_base64=get_logo_base64(),
        privacy_version=PRIVACY_VERSION,
    )

# ── Auth routes ────────────────────────────────────────────────────────────────

@app.route('/auth/signup', methods=['POST'])
def auth_signup():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    age_confirmed = data.get('age_confirmed') is True
    eula_reviewed = data.get('eula_reviewed') is True
    eula_agreed = data.get('eula_agreed') is True
    eula_version = data.get('eula_version') or ''
    privacy_agreed = data.get('privacy_agreed') is True
    privacy_version = data.get('privacy_version') or ''
    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400
    if len(username) < 2 or len(username) > 32:
        return jsonify({'error': 'Username must be 2–32 characters.'}), 400
    if len(password) < 4:
        return jsonify({'error': 'Password must be at least 4 characters.'}), 400
    if not re.match(r'^[A-Za-z0-9_\-\.]+$', username):
        return jsonify({'error': 'Username may only contain letters, numbers, _ - .'}), 400
    if not age_confirmed:
        return jsonify({'error': 'You must confirm that you are 13 or older to create an account.'}), 400
    if not eula_reviewed:
        return jsonify({'error': 'Please review the EULA before creating your account.'}), 400
    if not eula_agreed:
        return jsonify({'error': 'You must agree to the EULA to create an account.'}), 400
    if eula_version != EULA_VERSION:
        return jsonify({'error': 'Please review the current EULA before creating your account.'}), 400
    if not privacy_agreed:
        return jsonify({'error': 'You must agree to the Privacy Policy to create an account.'}), 400
    if privacy_version != PRIVACY_VERSION:
        return jsonify({'error': 'Please review the current Privacy Policy before creating your account.'}), 400

    consented_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db = get_db()
    try:
        cursor = db.execute(
            '''INSERT INTO users
               (username, password_hash, age_confirmed, eula_reviewed,
                eula_agreed, eula_version, consented_at, privacy_agreed,
                privacy_version, privacy_consented_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                username,
                generate_password_hash(password),
                1,
                1,
                1,
                EULA_VERSION,
                consented_at,
                1,
                PRIVACY_VERSION,
                consented_at,
            )
        )
        db.commit()
    except sqlite3.IntegrityError as error:
        db.rollback()
        if 'username' in str(error).lower():
            return jsonify({'error': 'That username is already taken.'}), 409
        logger.exception('Could not create account due to a database constraint')
        return jsonify({'error': 'Unable to create your account right now. Please try again.'}), 500
    except Exception:
        db.rollback()
        logger.exception('Could not create account')
        return jsonify({'error': 'Unable to create your account right now. Please try again.'}), 500
    finally:
        db.close()

    try:
        session['user_id'] = cursor.lastrowid
        session.permanent = True
        user = get_current_user()
    except Exception:
        logger.exception('Account was created but could not be loaded into the session')
        return jsonify({
            'error': 'Your account was created, but sign-in could not be completed. Please log in again.'
        }), 500
    return jsonify({'user': user})

@app.route('/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    db = get_db()
    row = db.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,)).fetchone()
    db.close()
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify({'error': 'Incorrect username or password.'}), 401
    session['user_id'] = row['id']
    session.permanent = True
    return jsonify({'user': get_current_user()})

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})

@app.route('/auth/me')
def auth_me():
    user = get_current_user()
    if user:
        return jsonify({'user': user})
    return jsonify({'user': None})


@app.route('/auth/accept-eula', methods=['POST'])
def auth_accept_eula():
    """Record explicit acceptance of the currently published EULA."""
    user = get_current_user()
    if not user:
        return auth_required_response()

    data = request.get_json() or {}
    if data.get('eula_reviewed') is not True:
        return jsonify({'error': 'Please open and review the current EULA first.'}), 400
    if data.get('eula_agreed') is not True:
        return jsonify({'error': 'You must agree to the current EULA.'}), 400
    if data.get('eula_version') != EULA_VERSION:
        return jsonify({'error': 'The EULA has changed. Please open the current agreement and try again.'}), 400

    consented_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db = get_db()
    try:
        updated = db.execute(
            '''UPDATE users
               SET eula_reviewed = 1,
                   eula_agreed = 1,
                   eula_version = ?,
                   consented_at = ?
               WHERE id = ?''',
            (EULA_VERSION, consented_at, user['id'])
        )
        if updated.rowcount != 1:
            db.rollback()
            return jsonify({'error': 'Account not found.'}), 404
        db.commit()
    except Exception:
        db.rollback()
        logger.exception('Could not record EULA acceptance')
        return jsonify({'error': 'Unable to save your EULA acceptance. Please try again.'}), 500
    finally:
        db.close()

    return jsonify({'ok': True, 'user': get_current_user()})


@app.route('/auth/accept-privacy', methods=['POST'])
def auth_accept_privacy():
    """Record explicit acceptance of the currently published Privacy Policy."""
    user = get_current_user()
    if not user:
        return auth_required_response()

    data = request.get_json() or {}
    if data.get('privacy_reviewed') is not True:
        return jsonify({'error': 'Please open and review the current Privacy Policy first.'}), 400
    if data.get('privacy_agreed') is not True:
        return jsonify({'error': 'You must agree to the current Privacy Policy.'}), 400
    if data.get('privacy_version') != PRIVACY_VERSION:
        return jsonify({'error': 'The Privacy Policy has changed. Please open the current policy and try again.'}), 400

    consented_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db = get_db()
    try:
        updated = db.execute(
            '''UPDATE users
               SET privacy_agreed = 1,
                   privacy_version = ?,
                   privacy_consented_at = ?
               WHERE id = ?''',
            (PRIVACY_VERSION, consented_at, user['id'])
        )
        if updated.rowcount != 1:
            db.rollback()
            return jsonify({'error': 'Account not found.'}), 404
        db.commit()
    except Exception:
        db.rollback()
        logger.exception('Could not record Privacy Policy acceptance')
        return jsonify({'error': 'Unable to save your Privacy Policy acceptance. Please try again.'}), 500
    finally:
        db.close()

    return jsonify({'ok': True, 'user': get_current_user()})
# ── File routes ────────────────────────────────────────────────────────────────

@app.route('/files')
def list_files():
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    rows = db.execute(
        'SELECT id, name, mime_type, size, created_at FROM files WHERE user_id = ? ORDER BY id DESC',
        (user['id'],)
    ).fetchall()
    db.close()
    return jsonify({'files': [dict(r) for r in rows]})

@app.route('/files/<int:file_id>/download')
def download_file(file_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    row = db.execute(
        'SELECT * FROM files WHERE id = ? AND user_id = ?',
        (file_id, user['id'])
    ).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'File not found.'}), 404
    path = row['path']
    if not os.path.exists(path):
        return jsonify({'error': 'File no longer on disk.'}), 404
    return send_file(path, mimetype=row['mime_type'],
                     as_attachment=True, download_name=row['name'])


@app.route('/files/<int:file_id>/content', methods=['GET'])
def get_workspace_file_content(file_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    row = db.execute(
        'SELECT id, name, mime_type, path FROM files WHERE id = ? AND user_id = ?',
        (file_id, user['id'])
    ).fetchone()
    db.close()
    if not row:
        return jsonify({'error': 'File not found.'}), 404
    if os.path.splitext(row['name'])[1].lower() not in WORKSPACE_EDITABLE_EXTENSIONS:
        return jsonify({'error': 'This file type cannot be edited in Poinsettia Workspace.'}), 415
    if not os.path.exists(row['path']):
        return jsonify({'error': 'File no longer on disk.'}), 404

    try:
        with open(row['path'], 'r', encoding='utf-8') as document_file:
            content = document_file.read(WORKSPACE_MAX_CONTENT_BYTES + 1)
    except (OSError, UnicodeDecodeError):
        return jsonify({'error': 'This file could not be opened as a text document.'}), 415
    if len(content.encode('utf-8')) > WORKSPACE_MAX_CONTENT_BYTES:
        return jsonify({'error': 'This file is too large to edit in Poinsettia Workspace.'}), 413
    if os.path.splitext(row['name'])[1].lower() in {'.html', '.htm'}:
        content = sanitize_workspace_html(content)
    return jsonify({
        'id': row['id'],
        'name': row['name'],
        'mime_type': row['mime_type'],
        'content': content,
    })


@app.route('/files/<int:file_id>/content', methods=['PUT'])
def save_workspace_file_content(file_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True)
    content = payload.get('content') if isinstance(payload, dict) else None
    if not isinstance(content, str):
        return jsonify({'error': 'Document content must be a string.'}), 400
    try:
        content_size = len(content.encode('utf-8'))
    except UnicodeEncodeError:
        return jsonify({'error': 'Document content must be valid UTF-8 text.'}), 400
    if content_size > WORKSPACE_MAX_CONTENT_BYTES:
        return jsonify({'error': 'Documents must be 1 MB or smaller.'}), 413

    user = get_current_user()
    db = get_db()
    row = db.execute(
        'SELECT id, name, mime_type, path FROM files WHERE id = ? AND user_id = ?',
        (file_id, user['id'])
    ).fetchone()
    if not row:
        db.close()
        return jsonify({'error': 'File not found.'}), 404
    if os.path.splitext(row['name'])[1].lower() not in WORKSPACE_EDITABLE_EXTENSIONS:
        db.close()
        return jsonify({'error': 'This file type cannot be edited in Poinsettia Workspace.'}), 415
    if not os.path.exists(row['path']):
        db.close()
        return jsonify({'error': 'File no longer on disk.'}), 404

    safe_content = sanitize_workspace_html(content)
    base_name = os.path.splitext(row['name'])[0] or 'document'
    directory = os.path.dirname(row['path']) or _file_dir(user_id=user['id'])
    candidate_name = f'{base_name}.html'
    suffix = 2
    while True:
        existing = db.execute(
            'SELECT id FROM files WHERE user_id = ? AND name = ? AND id != ?',
            (user['id'], candidate_name, file_id)
        ).fetchone()
        candidate_path = os.path.join(directory, candidate_name)
        if not existing and (
            candidate_path == row['path'] or not os.path.exists(candidate_path)
        ):
            break
        candidate_name = f'{base_name}_{suffix}.html'
        suffix += 1

    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html_escape(candidate_name)}</title></head><body>{safe_content}</body></html>'
    )
    document_size = len(document.encode('utf-8'))
    if document_size > WORKSPACE_MAX_CONTENT_BYTES:
        db.close()
        return jsonify({'error': 'Documents must be 1 MB or smaller.'}), 413

    temporary_path = os.path.join(directory, f'.workspace-{secrets.token_hex(8)}.tmp')
    try:
        with open(temporary_path, 'w', encoding='utf-8') as document_file:
            document_file.write(document)
        os.replace(temporary_path, candidate_path)
        db.execute(
            '''UPDATE files
               SET name = ?, mime_type = 'text/html', path = ?, size = ?
               WHERE id = ? AND user_id = ?''',
            (candidate_name, candidate_path, document_size, file_id, user['id'])
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception('Could not save Poinsettia Workspace document')
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        db.close()
        return jsonify({'error': 'Unable to save the document. Please try again.'}), 500
    db.close()

    if row['path'] != candidate_path:
        try:
            os.remove(row['path'])
        except OSError:
            pass
    return jsonify({
        'ok': True,
        'file': {
            'id': file_id,
            'name': candidate_name,
            'mime_type': 'text/html',
            'size': document_size,
        },
        'content': safe_content,
    })


@app.route('/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    row = db.execute('SELECT * FROM files WHERE id = ? AND user_id = ?',
                     (file_id, user['id'])).fetchone()
    if not row:
        db.close()
        return jsonify({'error': 'File not found.'}), 404
    try:
        if os.path.exists(row['path']):
            os.remove(row['path'])
    except Exception:
        pass
    db.execute('DELETE FROM files WHERE id = ?', (file_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── Conversation persistence routes ───────────────────────────────────────────

VALID_CONVERSATION_MODES = ('p2', 'p3', P4_FAX_MODEL, P4_CANDOR_MODEL)
DEFAULT_CONVERSATION_TITLE = 'New chat'


def _conversation_title(value):
    """Normalize user-visible conversation titles without allowing markup."""
    title = re.sub(r'\s+', ' ', str(value or '')).strip()
    return title[:80] or DEFAULT_CONVERSATION_TITLE


def _conversation_summary(row):
    data = dict(row)
    data['pinned'] = bool(data.get('pinned', 0))
    if not data.get('title'):
        data['title'] = DEFAULT_CONVERSATION_TITLE
    return data


def _conversation_columns(db):
    return {
        row['name'] for row in db.execute("PRAGMA table_info(conversations)").fetchall()
    }


def _conversation_for_user(db, conversation_id, user_id):
    columns = _conversation_columns(db)
    optional_columns = {
        'title': "'New chat'",
        'pinned': '0',
        'created_at': 'NULL',
    }
    selected_optional_columns = [
        column if column in columns else f'{fallback} AS {column}'
        for column, fallback in optional_columns.items()
    ]
    return db.execute(
        '''SELECT id, user_id, mode, {optional_columns},
                  (SELECT m.content
                   FROM messages m
                   WHERE m.conversation_id = conversations.id
                     AND m.role = 'user'
                   ORDER BY m.id ASC LIMIT 1) AS first_message,
                  updated_at
           FROM conversations
           WHERE id = ? AND user_id = ?'''.format(
            optional_columns=', '.join(selected_optional_columns)
        ),
        (conversation_id, user_id)
    ).fetchone()


@app.route('/conversations', methods=['GET'])
def list_conversations():
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    columns = _conversation_columns(db)
    title_column = 'c.title' if 'title' in columns else "'New chat'"
    pinned_column = 'c.pinned' if 'pinned' in columns else '0'
    created_column = 'c.created_at' if 'created_at' in columns else 'NULL'
    first_message_column = (
        "(SELECT m.content FROM messages m "
        "WHERE m.conversation_id = c.id AND m.role = 'user' "
        "ORDER BY m.id ASC LIMIT 1)"
    )
    search_term = request.args.get('search', '').strip()
    where_clauses = ['c.user_id = ?']
    query_params = [user['id']]
    if search_term:
        # Treat search text as a literal substring rather than allowing SQL
        # wildcard characters to change the meaning of the query.
        escaped_search = (
            search_term.replace('!', '!!')
            .replace('%', '!%')
            .replace('_', '!_')
        )
        search_pattern = f'%{escaped_search}%'
        where_clauses.append(
            f"""(lower(COALESCE({title_column}, '')) LIKE lower(?) ESCAPE '!'
                 OR lower(COALESCE({first_message_column}, '')) LIKE lower(?) ESCAPE '!')"""
        )
        query_params.extend([search_pattern, search_pattern])
    rows = db.execute(
        '''SELECT c.id, c.mode, {title_column} AS title, {pinned_column} AS pinned,
                  {created_column} AS created_at, c.updated_at,
                  {first_message_column} AS first_message,
                  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
           FROM conversations c
           WHERE {where_clause}
           ORDER BY CASE WHEN {pinned_column} THEN 1 ELSE 0 END DESC,
                    datetime(c.updated_at) DESC, c.id DESC'''.format(
            title_column=title_column,
            pinned_column=pinned_column,
            created_column=created_column,
            first_message_column=first_message_column,
            where_clause=' AND '.join(where_clauses),
        ),
        query_params
    ).fetchall()
    db.close()
    return jsonify({'conversations': [_conversation_summary(row) for row in rows]})


@app.route('/conversations', methods=['POST'])
def create_conversation():
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'p2')
    if mode not in VALID_CONVERSATION_MODES:
        return jsonify({'error': 'Invalid mode.'}), 400

    title = _conversation_title(data.get('title'))
    db = get_db()
    if {'title', 'pinned', 'created_at'}.issubset(_conversation_columns(db)):
        cur = db.execute(
            '''INSERT INTO conversations (user_id, mode, title, pinned, created_at)
               VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)''',
            (user['id'], mode, title)
        )
    else:
        cur = db.execute(
            'INSERT INTO conversations (user_id, mode) VALUES (?, ?)',
            (user['id'], mode)
        )
    conversation_id = cur.lastrowid
    db.commit()
    row = _conversation_for_user(db, conversation_id, user['id'])
    db.close()
    return jsonify({'ok': True, 'conversation': _conversation_summary(row)}), 201


@app.route('/conversations/<int:conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    row = _conversation_for_user(db, conversation_id, user['id'])
    if not row:
        db.close()
        return jsonify({'error': 'Conversation not found.'}), 404
    messages = db.execute(
        '''SELECT role, content, created_at
           FROM messages WHERE conversation_id = ? ORDER BY id ASC''',
        (conversation_id,)
    ).fetchall()
    db.close()
    return jsonify({
        'conversation': _conversation_summary(row),
        'messages': [dict(message) for message in messages],
    })


@app.route('/conversations/<int:conversation_id>', methods=['PATCH'])
def update_conversation(conversation_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    updates = []
    values = []

    if 'title' in data:
        title = _conversation_title(data.get('title'))
        if title == DEFAULT_CONVERSATION_TITLE and not str(data.get('title') or '').strip():
            return jsonify({'error': 'A chat title is required.'}), 400
        updates.append('title = ?')
        values.append(title)
    if 'pinned' in data:
        if not isinstance(data['pinned'], bool):
            return jsonify({'error': 'Pinned must be true or false.'}), 400
        updates.append('pinned = ?')
        values.append(1 if data['pinned'] else 0)
    if not updates:
        return jsonify({'error': 'No conversation changes provided.'}), 400

    db = get_db()
    if not {'title', 'pinned'}.issubset(_conversation_columns(db)):
        db.close()
        return jsonify({'error': 'Conversation metadata migration is required.'}), 409
    row = _conversation_for_user(db, conversation_id, user['id'])
    if not row:
        db.close()
        return jsonify({'error': 'Conversation not found.'}), 404
    values.extend([conversation_id, user['id']])
    db.execute(
        'UPDATE conversations SET ' + ', '.join(updates) + ' WHERE id = ? AND user_id = ?',
        values
    )
    db.commit()
    updated = _conversation_for_user(db, conversation_id, user['id'])
    db.close()
    return jsonify({'ok': True, 'conversation': _conversation_summary(updated)})


@app.route('/conversations/<int:conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    db = get_db()
    row = _conversation_for_user(db, conversation_id, user['id'])
    if not row:
        db.close()
        return jsonify({'error': 'Conversation not found.'}), 404
    db.execute(
        'DELETE FROM conversations WHERE id = ? AND user_id = ?',
        (conversation_id, user['id'])
    )
    db.commit()
    db.close()
    return jsonify({'ok': True, 'conversation_id': conversation_id})


@app.route('/conversations/save', methods=['POST'])
def save_conversation():
    """Save a selected conversation, retaining legacy latest-thread callers."""
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    mode = data.get('mode', 'p2')
    messages = data.get('messages', [])
    conversation_id = data.get('conversation_id')
    if mode not in VALID_CONVERSATION_MODES:
        return jsonify({'error': 'Invalid mode.'}), 400
    if not isinstance(messages, list):
        return jsonify({'error': 'Messages must be a list.'}), 400

    db = get_db()
    metadata_available = {'title', 'pinned', 'created_at'}.issubset(_conversation_columns(db))
    row = None
    if conversation_id is not None:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            db.close()
            return jsonify({'error': 'Invalid conversation ID.'}), 400
        row = _conversation_for_user(db, conversation_id, user['id'])
        if not row:
            db.close()
            return jsonify({'error': 'Conversation not found.'}), 404
        if row['mode'] != mode:
            db.close()
            return jsonify({'error': 'Conversation mode does not match.'}), 400
    else:
        # Compatibility for older clients: continue updating their latest
        # conversation instead of creating a second thread unexpectedly.
        row = db.execute(
            'SELECT id FROM conversations WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT 1',
            (user['id'], mode)
        ).fetchone()
        if row:
            conversation_id = row['id']
        else:
            cur = db.execute(
                'INSERT INTO conversations (user_id, mode) VALUES (?, ?)',
                (user['id'], mode)
            )
            conversation_id = cur.lastrowid

    db.execute('DELETE FROM messages WHERE conversation_id = ?', (conversation_id,))
    first_user_content = next(
        (
            str(message.get('content') or '').strip()
            for message in messages
            if isinstance(message, dict) and message.get('role') == 'user' and message.get('content')
        ),
        ''
    )
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get('role', '')
        content = str(message.get('content') or '').strip()
        if role in ('user', 'assistant') and content:
            db.execute(
                'INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)',
                (conversation_id, role, content)
            )

    if metadata_available and first_user_content and (not row or row['id'] == conversation_id):
        current = _conversation_for_user(db, conversation_id, user['id'])
        if current and current['title'] == DEFAULT_CONVERSATION_TITLE:
            db.execute(
                'UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?',
                (_conversation_title(first_user_content), conversation_id, user['id'])
            )
    db.execute(
        'UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?',
        (conversation_id, user['id'])
    )
    db.commit()
    saved = _conversation_for_user(db, conversation_id, user['id'])
    db.close()
    return jsonify({
        'ok': True,
        'conversation_id': conversation_id,
        'conversation': _conversation_summary(saved),
    })


@app.route('/conversations/latest')
def latest_conversation():
    """Legacy endpoint retained for older clients and regression coverage."""
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    user = get_current_user()
    mode = request.args.get('mode', 'p2')
    if mode not in VALID_CONVERSATION_MODES:
        return jsonify({'error': 'Invalid mode.'}), 400
    db = get_db()
    row = db.execute(
        'SELECT id FROM conversations WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT 1',
        (user['id'], mode)
    ).fetchone()
    if not row:
        db.close()
        return jsonify({'messages': []})
    msgs = db.execute(
        'SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC',
        (row['id'],)
    ).fetchall()
    db.close()
    return jsonify({'messages': [dict(message) for message in msgs]})

# ── Chat routes ────────────────────────────────────────────────────────────────

@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    auth_error = require_authenticated_user()
    if auth_error:
        return auth_error
    try:
        data = request.get_json()
        if data is None:
            return jsonify({'error': 'Invalid JSON'}), 400
        messages = data.get('messages', [])
        if not messages:
            return jsonify({'error': 'No messages provided'}), 400
        mode = data.get('mode', 'p2')
        if mode not in VALID_CONVERSATION_MODES:
            return jsonify({'error': 'Invalid mode.'}), 400
        try:
            messages = prepare_ollama_messages(
                messages,
                allow_audio=mode not in P4_MODES,
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        if mode == 'p3':
            return stream_p3(messages, client_date=data.get('client_date'))
        if mode in P4_MODES:
            return stream_p4(mode, messages, client_date=data.get('client_date'))
        return stream_p2(messages)
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ── Streaming Helpers ──────────────────────────────────────────────────────────

def make_stream_response(generator):
    return Response(
        stream_with_context(generator),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'}
    )

def ollama_stream_generator(model, messages):
    """Stream from Ollama /api/chat, filtering hidden commands."""
    try:
        with requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": prepare_ollama_messages(messages),
                "stream": True,
                "options": {"num_ctx": 4608},
            },
            stream=True, timeout=240
        ) as resp:
            if resp.status_code != 200:
                yield f"data: {json.dumps({'error': 'Failed to connect to AI model'})}\n\n"
                return
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        if 'message' in chunk and 'content' in chunk['message']:
                            raw = chunk['message']['content']
                            clean = strip_search_commands(raw)
                            if clean:
                                yield f"data: {json.dumps({'text': clean})}\n\n"
                        if chunk.get('done', False):
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            break
                    except json.JSONDecodeError:
                        continue
    except requests.exceptions.Timeout:
        yield f"data: {json.dumps({'error': 'The model took too long to respond. Try a shorter question or ask again.'})}\n\n"
    except requests.exceptions.ConnectionError:
        yield f"data: {json.dumps({'error': 'Cannot connect to AI model. Please try again.'})}\n\n"
    except Exception as e:
        logger.error(f"Streaming error: {str(e)}")
        yield f"data: {json.dumps({'error': 'Something went wrong. Please try again.'})}\n\n"

P3_NUM_PREDICT = 1024
FILE_START_MARKER = "<<<FILE:"
FILE_END_MARKER = "<<<ENDFILE>>>"


class P3FileStreamFilter:
    """Stream normal P3 text while buffering downloadable file blocks."""

    def __init__(self, user_id=None, guest_key=None):
        self.user_id = user_id
        self.guest_key = guest_key
        self.pending = ""
        self.in_file = False

    def feed(self, text):
        self.pending += text
        visible = []
        file_infos = []

        while self.pending:
            if self.in_file:
                end_idx = self.pending.find(FILE_END_MARKER)
                if end_idx == -1:
                    break
                block_end = end_idx + len(FILE_END_MARKER)
                block = self.pending[:block_end]
                clean_block, infos = extract_files_from_text(
                    block, user_id=self.user_id, guest_key=self.guest_key
                )
                if clean_block:
                    visible.append(clean_block)
                file_infos.extend(infos)
                self.pending = self.pending[block_end:]
                self.in_file = False
                continue

            start_idx = self.pending.find(FILE_START_MARKER)
            if start_idx != -1:
                visible.append(self.pending[:start_idx])
                self.pending = self.pending[start_idx:]
                self.in_file = True
                continue

            # Keep a possible partial marker between Ollama chunks.
            safe_length = max(0, len(self.pending) - len(FILE_START_MARKER) + 1)
            if safe_length:
                visible.append(self.pending[:safe_length])
                self.pending = self.pending[safe_length:]
            break

        return "".join(visible), file_infos

    def flush(self):
        """Release trailing text and handle an incomplete file marker safely."""
        if self.in_file:
            visible, file_infos = extract_files_from_text(
                self.pending, user_id=self.user_id, guest_key=self.guest_key
            )
        else:
            visible, file_infos = self.pending, []
        self.pending = ""
        self.in_file = False
        return visible, file_infos


def ollama_p3_stream(model, messages, user_id=None, guest_key=None):
    """Yield (text, files, error) incrementally from the P3 Ollama response."""
    stream_filter = P3FileStreamFilter(user_id=user_id, guest_key=guest_key)
    try:
        with requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": prepare_ollama_messages(messages),
                "stream": True,
                "options": {"num_ctx": 4608, "num_predict": P3_NUM_PREDICT}
            },
            stream=True, timeout=240
        ) as resp:
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = resp.json().get("error", "")
                except (ValueError, requests.RequestException):
                    detail = ""
                if detail:
                    logger.error("Ollama model %s returned HTTP %s: %s", model, resp.status_code, detail)
                    yield "", [], f"AI model '{model}' is unavailable: {detail}"
                else:
                    logger.error("Ollama model %s returned HTTP %s", model, resp.status_code)
                    yield "", [], f"AI model '{model}' is unavailable. Please install it and try again."
                return
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        message = chunk.get('message') or {}
                        raw = message.get('content')
                        # /api/chat normally uses message.content. Accept
                        # response as well so an Ollama-compatible runtime
                        # cannot silently produce a blank assistant bubble.
                        if raw is None:
                            raw = chunk.get('response', '')
                        if raw:
                            clean = strip_search_commands(raw)
                            if clean:
                                text, file_infos = stream_filter.feed(clean)
                                if text or file_infos:
                                    yield text, file_infos, ""
                        if chunk.get('done', False):
                            break
                    except json.JSONDecodeError:
                        continue
            text, file_infos = stream_filter.flush()
            if text or file_infos:
                yield text, file_infos, ""
    except requests.exceptions.Timeout:
        text, file_infos = stream_filter.flush()
        yield text, file_infos, "The model took too long to respond. Try a shorter question or ask again."
    except requests.exceptions.ConnectionError:
        yield "", [], "Cannot connect to AI model. Please try again."
    except Exception as e:
        logger.error(f"ollama_p3_stream error: {e}")
        text, file_infos = stream_filter.flush()
        yield text, file_infos, "Something went wrong. Please try again."

def stream_p2(messages):
    logger.info(f"P2: {len(messages)} messages")
    return make_stream_response(ollama_stream_generator("poinsettia", messages))

def stream_research_model(model, display_name, messages, client_date=None, allow_audio=True):
    if len(messages) > 8:
        messages = messages[-8:]
    if messages and messages[0].get('role') == 'assistant':
        messages = messages[1:]
    logger.info(f"{display_name}: {len(messages)} messages")

    if not check_internet():
        def offline():
            msg = (f"{display_name} requires a working internet connection, "
                   "please check your router and Wi-Fi and try again.")
            yield f"data: {json.dumps({'text': msg, 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return make_stream_response(offline())

    searches, weather_city_raw = generate_commands(messages)

    if isinstance(weather_city_raw, tuple):
        weather_city, weather_days = weather_city_raw
    else:
        weather_city, weather_days = weather_city_raw, 0

    # Capture auth context now (before entering the generator closure)
    user = get_current_user()
    user_id = user['id'] if user else None
    guest_key = session.get('guest_key') if not user else None

    def p3_generator():
        yield f"data: {json.dumps({'heartbeat': True})}\n\n"

        today = client_date or datetime.date.today().strftime("%A, %B %-d, %Y")
        attachment_instruction = (
            "- When an image or audio attachment is present, inspect it carefully and use it as evidence for the answer.\n"
            if allow_audio
            else "- When an image attachment is present, inspect it carefully and use it as evidence for the answer. This model does not accept audio.\n"
        )
        system_parts = [
            f"You are {display_name}, a helpful multimodal AI assistant with internet access.\n"
            "Rules you must follow:\n"
            "- Answer directly and naturally, like a knowledgeable friend.\n"
            "- Never say 'as an AI', 'as a language model', 'my training data', 'my internal calendar', or any similar phrase.\n"
            "- Never introduce yourself unprompted.\n"
            + attachment_instruction
            + "- Never add unnecessary disclaimers.\n"
            + "- The application has already completed any needed web search. "
            + "Do not output SEARCH or WEATHER commands or command-like tags. "
            + "Always provide the complete final answer to the user.\n"
            + f"- If the user asks what today's date or day is, tell them it is {today}. Do not mention the date unless asked.\n"
            + "- If the user asks you to create, generate, write, or produce a file (script, text file, code, etc.) "
            + "that they want to download, output it using exactly this format (and nothing else for the file block):\n"
            + "<<<FILE:filename.ext>>>\n"
            + "file content here\n"
            + "<<<ENDFILE>>>\n"
            + "You may include explanatory text before or after the file block. "
            + "Only use this format when the user explicitly asks for a downloadable file."
        ]

        def status(msg):
            return f"data: {json.dumps({'status': msg})}\n\n"

        weather_data = None
        if weather_city:
            label = weather_city if isinstance(weather_city, str) else weather_city
            yield status(f"Fetching weather for {label}…")
            weather_data = fetch_weather_forecast(weather_city, weather_days)
            if weather_data:
                yield f"data: {json.dumps({'weather': weather_data, 'done': False})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                return
            else:
                system_parts.append(
                    f"Weather data for '{weather_city}' could not be retrieved. "
                    "Let the user know politely."
                )

        all_source_urls = []
        if searches:
            web_parts = []
            for q in searches:
                yield status('Identifying topic…')
                # Avoid a second Llama cold-start just to classify the query.
                # The deterministic classifier keeps P3's retrieval routing
                # local and lets the model handle the actual answer once.
                category = quick_classify(q)
                yield status(f'Searching {category} sources…')
                context, src_urls = search_and_scrape(q, category)
                all_source_urls.extend(src_urls)
                if context:
                    web_parts.append(f"[Search: {q}]\n{context}")
            web_context = "\n\n---\n\n".join(web_parts)
            logger.info(f"P3 web context: {len(web_context)} chars")
            if web_context:
                system_parts.append(
                    "Real-time web results:\n\n" + web_context + "\n\n"
                    "Use the above to answer accurately and naturally."
                )

        has_context = any(
            "Real-time web results" in p or "Weather data for" in p
            for p in system_parts
        )
        if not has_context:
            system_parts.append(
                "No real-time data is available for this query. "
                "Answer from your training knowledge. "
                "Do NOT say you cannot access the internet or lack real-time data — "
                "just answer the question directly and naturally."
            )

        yield status("Generating response…")
        system_message = {'role': 'system', 'content': "\n\n".join(system_parts)}
        p3_messages = [system_message] + list(messages)

        # Send sources before model output so the client can associate them
        # with the response while tokens are still arriving.
        if all_source_urls:
            yield f"data: {json.dumps({'sources': all_source_urls})}\n\n"

        model_output_seen = False
        for text, file_infos, error in ollama_p3_stream(
            model, p3_messages, user_id=user_id, guest_key=guest_key
        ):
            for fi in file_infos:
                model_output_seen = True
                yield f"data: {json.dumps({'file': fi})}\n\n"
            if text:
                model_output_seen = True
                yield f"data: {json.dumps({'text': text, 'done': False})}\n\n"
            if error and not model_output_seen:
                yield f"data: {json.dumps({'error': error})}\n\n"
                return

        if not model_output_seen:
            yield f"data: {json.dumps({'error': f'Model {model} returned an empty response. Please try again.'})}\n\n"
            return

        yield f"data: {json.dumps({'done': True})}\n\n"

    return make_stream_response(p3_generator())


def stream_p3(messages, client_date=None):
    return stream_research_model(
        P3_MODEL,
        "Poinsettia 3.9",
        messages,
        client_date=client_date,
        allow_audio=True,
    )


def stream_p4(mode, messages, client_date=None):
    model_names = {
        P4_FAX_MODEL: "Poinsettia 4.0 “Fax”",
        P4_CANDOR_MODEL: "Poinsettia 4.0 “Candor”",
    }
    return stream_research_model(
        mode,
        model_names[mode],
        messages,
        client_date=client_date,
        allow_audio=False,
    )

if __name__ == '__main__':
    print("Starting Poinsettia on port 5000...")
    print("Visit http://0.0.0.0:5000 to access Poinsettia.")
    app.run(host='0.0.0.0', port=5000, debug=False)
