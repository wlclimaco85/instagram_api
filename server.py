"""
Mini-servidor Instagram API para o App Match.
Uso: python server.py
Porta: 8500
"""
import json
import os
import random
import sqlite3
import sys
import time
import requests as http_requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired, ClientLoginRequired, ChallengeRequired,
        BadPassword, TwoFactorRequired,
    )
    _INSTAGRAPI_OK = True
except ImportError:
    _INSTAGRAPI_OK = False

# Carrega .env local se existir (credenciais nunca devem ir para o git)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _linha in _f:
            _linha = _linha.strip()
            if _linha and not _linha.startswith("#") and "=" in _linha:
                _chave, _, _valor = _linha.partition("=")
                os.environ.setdefault(_chave.strip(), _valor.strip())

SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")
DB_FILE = os.path.join(os.path.dirname(__file__), "timeline.db")

cl = Client() if _INSTAGRAPI_OK else None
LOGIN_OK = False

# --- TTL Cache simples -------------------------------------------------------

class TtlCache:
    """Cache em memória com TTL por chave (padrão: 1800 segundos = 30 min)."""

    def __init__(self, ttl: int = 1800):
        self._ttl = ttl
        self._store: dict = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        valor, expira_em = entry
        if time.monotonic() > expira_em:
            del self._store[key]
            return None
        return valor

    def set(self, key: str, value) -> None:
        self._store[key] = (value, time.monotonic() + self._ttl)


_cache_perfil = TtlCache(ttl=1800)
_cache_posts = TtlCache(ttl=1800)

# --- Proxy via env var -------------------------------------------------------

PROXY_URL = os.environ.get("PROXY_URL", "").strip()
_PROXIES = {"https": PROXY_URL, "http": PROXY_URL} if PROXY_URL else None

# --- Rotação de User-Agent ---------------------------------------------------

_USER_AGENTS = [
    'Instagram 301.0.0.27.109 Android (30/11; 420dpi; 1080x2400; samsung; SM-A525F; a52; exynos1280; en_US; 516783258)',
    'Instagram 302.1.0.36.119 Android (31/12; 440dpi; 1080x2340; xiaomi; M2101K6G; apollo; qcom; en_US; 519038674)',
    'Instagram 303.0.0.42.101 Android (33/13; 480dpi; 1440x3200; google; Pixel 7; panther; tensor; en_US; 521204892)',
]


def _headers_aleatorios() -> dict:
    """Retorna headers com User-Agent sorteado a cada chamada."""
    return {
        'User-Agent': random.choice(_USER_AGENTS),
        'X-IG-App-ID': '936619743392459',
        'X-IG-Client-ID': 'IGSB',
        'Accept-Language': 'en-US',
    }

def _fetch_profile_via_graphql(username):
    """Tenta buscar perfil via endpoint GraphQL legado (?__a=1). Sem auth, funciona para perfis públicos."""
    try:
        time.sleep(0.5)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        }
        r = http_requests.get(
            f'https://www.instagram.com/{username}/?__a=1&__d=dis',
            headers=headers,
            proxies=_PROXIES,
            timeout=15,
        )
        print(f"[IG-GQL] @{username} → HTTP {r.status_code}")
        if r.status_code != 200:
            return None
        data = r.json()
        user = data.get('graphql', {}).get('user') or data.get('data', {}).get('user')
        if not user:
            return None
        return {
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "biography": user.get("biography"),
            "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
            "followers": user.get("edge_followed_by", {}).get("count", 0),
            "following": user.get("edge_follow", {}).get("count", 0),
            "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
            "is_private": user.get("is_private", False),
            "is_verified": user.get("is_verified", False),
            "external_url": user.get("external_url"),
            "hd_profile_pic": user.get("profile_pic_url_hd"),
            "_raw_media": user.get("edge_owner_to_timeline_media", {}),
            "_source": "graphql",
        }
    except Exception as e:
        print(f"[IG-GQL] erro: {e}")
    return None


def _fetch_profile_via_api(username):
    """Tenta buscar perfil pela API privada do Instagram (exige sessão/IP limpo)."""
    try:
        time.sleep(1.0)
        r = http_requests.get(
            f'https://i.instagram.com/api/v1/users/web_profile_info/?username={username}',
            headers=_headers_aleatorios(),
            proxies=_PROXIES,
            timeout=15,
        )
        print(f"[IG-API] @{username} → HTTP {r.status_code}")
        if r.status_code == 429:
            return {"error": "rate_limited", "retry_after": 60}
        if r.status_code in (401, 302, 403):
            return {"error": "auth_required", "http_status": r.status_code}
        if r.status_code == 200:
            user = r.json().get('data', {}).get('user')
            if user:
                return {
                    "username": user.get("username"),
                    "full_name": user.get("full_name"),
                    "biography": user.get("biography"),
                    "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
                    "followers": user.get("edge_followed_by", {}).get("count", 0),
                    "following": user.get("edge_follow", {}).get("count", 0),
                    "posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                    "is_private": user.get("is_private", False),
                    "is_verified": user.get("is_verified", False),
                    "external_url": user.get("external_url"),
                    "hd_profile_pic": user.get("profile_pic_url_hd"),
                    "_raw_media": user.get("edge_owner_to_timeline_media", {}),
                }
    except Exception as e:
        print(f"[IG-API] erro: {e}")
    return None


def _fetch_profile_via_html(username):
    """Fallback: raspa metatags og: da página pública do Instagram."""
    try:
        time.sleep(1.5)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        r = http_requests.get(
            f'https://www.instagram.com/{username}/',
            headers=headers,
            proxies=_PROXIES,
            timeout=20,
            allow_redirects=True,
        )
        print(f"[IG-HTML] @{username} → HTTP {r.status_code}")
        if r.status_code != 200:
            return None
        html = r.text

        def _meta(prop):
            import re
            m = re.search(rf'<meta\s+property=["\']og:{prop}["\']\s+content=["\'](.*?)["\']', html)
            if not m:
                m = re.search(rf'<meta\s+content=["\'](.*?)["\']\s+property=["\']og:{prop}["\']', html)
            return m.group(1) if m else None

        title = _meta('title') or ''
        description = _meta('description') or ''
        image = _meta('image') or ''

        # og:title formato: "Nome do Usuário (@handle) • Instagram"
        full_name = title.split('(')[0].strip() if '(' in title else title.replace('• Instagram', '').strip()

        # og:description formato: "X Followers, Y Following, Z Posts – Bio aqui"
        followers = 0
        following = 0
        posts = 0
        biography = ''
        import re
        m = re.match(r'([\d,KMk]+)\s+Followers?,\s*([\d,KMk]+)\s+Following,\s*([\d,KMk]+)\s+Posts?\s*[-–]?\s*(.*)', description)
        if m:
            def _parse_num(s):
                s = s.replace(',', '').strip()
                if s.endswith('K') or s.endswith('k'):
                    return int(float(s[:-1]) * 1000)
                if s.endswith('M') or s.endswith('m'):
                    return int(float(s[:-1]) * 1_000_000)
                return int(s) if s.isdigit() else 0
            followers = _parse_num(m.group(1))
            following = _parse_num(m.group(2))
            posts     = _parse_num(m.group(3))
            biography = m.group(4).strip()

        if not full_name and not image:
            return None

        return {
            "username": username,
            "full_name": full_name,
            "biography": biography,
            "profile_pic_url": image,
            "followers": followers,
            "following": following,
            "posts": posts,
            "is_private": False,
            "is_verified": False,
            "external_url": None,
            "hd_profile_pic": image,
            "_raw_media": {},
            "_source": "html",
        }
    except Exception as e:
        print(f"[IG-HTML] erro: {e}")
    return None


def fetch_profile_public(username):
    cached = _cache_perfil.get(username)
    if cached is not None:
        return cached

    # 1ª tentativa: API privada (precisa de IP limpo ou sessão)
    resultado = _fetch_profile_via_api(username)
    if resultado and not resultado.get("error"):
        _cache_perfil.set(username, resultado)
        return resultado

    erro_api = resultado

    # 2ª tentativa: GraphQL legado (funciona sem auth em alguns IPs)
    print(f"[FALLBACK] API falhou para @{username}, tentando GraphQL...")
    resultado = _fetch_profile_via_graphql(username)
    if resultado and not resultado.get("error"):
        _cache_perfil.set(username, resultado)
        return resultado

    # 3ª tentativa: raspar metatags og: da página HTML
    print(f"[FALLBACK] GraphQL falhou para @{username}, tentando HTML...")
    resultado = _fetch_profile_via_html(username)
    if resultado and not resultado.get("error"):
        _cache_perfil.set(username, resultado)
        return resultado

    # Todos falharam — devolve o erro original da API
    return erro_api

def fetch_posts_public(username, amount=12):
    cache_key = f"{username}:{amount}"
    cached = _cache_posts.get(cache_key)
    if cached is not None:
        return cached

    try:
        profile = fetch_profile_public(username)
        if not profile or profile.get("error"):
            return []
        media = profile.get("_raw_media", {})
        edges = media.get("edges", [])
        posts = []
        for e in edges[:amount]:
            n = e.get("node", {})
            caption_edges = n.get("edge_media_to_caption", {}).get("edges", [])
            caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""
            timestamp = n.get("taken_at_timestamp", 0)
            posts.append({
                "id": str(n.get("id", "")),
                "display_url": n.get("display_url"),
                "caption": caption[:200],
                "likes": n.get("edge_liked_by", {}).get("count", 0),
                "comments": n.get("edge_media_to_comment", {}).get("count", 0),
                "timestamp": str(datetime.fromtimestamp(timestamp)) if timestamp else "",
                "is_video": n.get("is_video", False),
                "video_url": None,
            })
        _cache_posts.set(cache_key, posts)
        return posts
    except Exception as e:
        print(f"fetch_posts_public error: {e}")
        return []

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        snapshot_type TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tracked_profiles (
        username TEXT PRIMARY KEY,
        active INTEGER DEFAULT 1,
        last_snapshot TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def save_snapshot(username, snapshot_type, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO snapshots (username, snapshot_type, data) VALUES (?, ?, ?)',
              (username, snapshot_type, json.dumps(data, ensure_ascii=False)))
    c.execute('UPDATE tracked_profiles SET last_snapshot = CURRENT_TIMESTAMP WHERE username = ?',
              (username,))
    conn.commit()
    conn.close()

def get_last_snapshots(username, snapshot_type, limit=2):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT data, created_at FROM snapshots
                 WHERE username = ? AND snapshot_type = ?
                 ORDER BY created_at DESC LIMIT ?''',
              (username, snapshot_type, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def track_profile(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO tracked_profiles (username) VALUES (?)', (username,))
    conn.commit()
    conn.close()

def _carregar_sessao():
    """Carrega session.json sem chamar login() — zero request ao Instagram na subida."""
    global LOGIN_OK
    if not _INSTAGRAPI_OK:
        print("instagrapi nao instalado. Modo somente-leitura.")
        return
    if not os.path.exists(SESSION_FILE):
        print("session.json nao encontrado. Rode: python server.py --setup-session")
        print("Modo somente-leitura ativo. Endpoints: /profile, /posts")
        return
    try:
        cl.load_settings(SESSION_FILE)
        if not cl.user_id:
            raise ValueError("session.json invalido (user_id ausente)")
        LOGIN_OK = True
        print(f"Sessao carregada: user_id={cl.user_id}")
        print("Modo autenticado ativo. Todos os endpoints disponiveis.")
    except Exception as e:
        print(f"Falha ao carregar session.json: {e}")
        print("Rode: python server.py --setup-session para renovar a sessao.")
        print("Modo somente-leitura ativo. Endpoints: /profile, /posts")


def _invalidar_sessao():
    """Marca sessao como expirada — chamado quando request retorna erro de auth."""
    global LOGIN_OK
    LOGIN_OK = False
    print("Sessao expirada detectada. Rode: python server.py --setup-session")


def _erro_auth():
    return {
        "error": "auth_required",
        "message": "Sessao expirada ou ausente. Rode: python server.py --setup-session no servidor.",
    }


def _handle_cl_exception(e, handler_self):
    """Trata excecoes do instagrapi e decide se invalida sessao ou retorna 500."""
    err = str(e)
    if any(t in type(e).__name__ for t in ("LoginRequired", "ClientLoginRequired")):
        _invalidar_sessao()
        handler_self.send_json(_erro_auth(), 401)
    elif "401" in err or "login" in err.lower():
        _invalidar_sessao()
        handler_self.send_json(_erro_auth(), 401)
    else:
        handler_self.send_json({"error": err}, 500)


def setup_session_interativo():
    """Modo interativo para login com suporte a challenge (email/SMS/2FA)."""
    if not _INSTAGRAPI_OK:
        print("ERRO: instagrapi nao instalado. Execute: pip install instagrapi")
        sys.exit(1)

    username = os.environ.get("IG_USERNAME") or input("Instagram username: ").strip()
    password = os.environ.get("IG_PASSWORD") or input("Instagram password: ").strip()

    ig = Client()

    def _challenge_handler(u, choice):
        print(f"\nInstagram enviou um codigo para: {choice.name}")
        return input("Digite o codigo recebido: ").strip()

    ig.challenge_code_handler = _challenge_handler

    try:
        ig.login(username, password)
    except TwoFactorRequired:
        code = input("Codigo 2FA: ").strip()
        ig.login(username, password, verification_code=code)
    except ChallengeRequired:
        print("Challenge necessario — verifique e-mail ou SMS do Instagram.")
        raise

    ig.dump_settings(SESSION_FILE)
    print(f"\nSessao salva em: {SESSION_FILE}")
    print("Reinicie o servidor. A partir de agora ele carrega a sessao sem fazer login.")

class InstagramHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == "/health":
            self.send_json({"status": "ok"})
        
        elif parsed.path == "/login_status":
            self.send_json({"login_ok": False, "mode": "readonly"})
        
        elif parsed.path == "/profile":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            data = None
            if LOGIN_OK:
                try:
                    user = cl.user_info_by_username(username)
                    data = {
                        "username": user.username,
                        "full_name": user.full_name,
                        "biography": user.biography,
                        "profile_pic_url": str(user.profile_pic_url) if user.profile_pic_url else None,
                        "followers": user.follower_count,
                        "following": user.following_count,
                        "posts": user.media_count,
                        "is_private": user.is_private,
                        "is_verified": user.is_verified,
                        "external_url": str(user.external_url) if user.external_url else None,
                        "hd_profile_pic": str(user.hd_profile_pic_url_info.url) if user.hd_profile_pic_url_info else None,
                    }
                except (LoginRequired, ClientLoginRequired):
                    _invalidar_sessao()
                except Exception as e:
                    print(f"instagrapi profile error: {e}")
            if data is None:
                data = fetch_profile_public(username)
            if data and data.get("error") == "rate_limited":
                self.send_json(data, 429)
            elif data and data.get("error") == "auth_required":
                self.send_json({"error": "auth_required",
                                "message": "Instagram exige login. Configure IG_USERNAME e IG_PASSWORD e reinicie o servidor.",
                                "http_status": data.get("http_status")}, 401)
            elif data:
                data.pop("_raw_media", None)
                self.send_json(data)
            else:
                self.send_json({"error": "not_found", "message": "Perfil nao encontrado ou privado"}, 404)
        
        elif parsed.path == "/posts":
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["12"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            posts = []
            if LOGIN_OK:
                try:
                    user = cl.user_info_by_username(username)
                    medias = cl.user_medias(user.pk, amount=amount)
                    for m in medias:
                        posts.append({
                            "id": str(m.pk),
                            "display_url": str(m.thumbnail_url) if m.thumbnail_url else None,
                            "caption": (m.caption_text or "")[:200],
                            "likes": m.like_count or 0,
                            "comments": m.comment_count or 0,
                            "timestamp": str(m.taken_at),
                            "is_video": m.media_type == 2,
                            "video_url": str(m.video_url) if m.media_type == 2 and m.video_url else None,
                        })
                except (LoginRequired, ClientLoginRequired):
                    _invalidar_sessao()
                except Exception as e:
                    print(f"instagrapi posts error: {e}")
            if not posts:
                posts = fetch_posts_public(username, amount)
            self.send_json({"posts": posts, "count": len(posts)})
        
        elif parsed.path == "/likers":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            media_id = params.get("media_id", [""])[0]
            if not media_id:
                self.send_json({"error": "media_id required"}, 400)
                return
            try:
                likers = cl.media_likers(int(media_id))
                data = [{"username": l.username, "full_name": l.full_name} for l in likers]
                self.send_json({"likers": data, "count": len(data)})
            except Exception as e:
                _handle_cl_exception(e, self)
        
        elif parsed.path == "/followers":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["200"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                followers = cl.user_followers(user.pk, amount=amount)
                data = [{"username": f.username, "full_name": f.full_name} for f in followers.values()]
                self.send_json({"followers": data, "count": len(data)})
            except Exception as e:
                _handle_cl_exception(e, self)
        
        elif parsed.path == "/following":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["200"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                following = cl.user_following(user.pk, amount=amount)
                data = [{"username": f.username, "full_name": f.full_name} for f in following.values()]
                self.send_json({"following": data, "count": len(data)})
            except Exception as e:
                _handle_cl_exception(e, self)
        
        elif parsed.path == "/comments":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            media_id = params.get("media_id", [""])[0]
            if not media_id:
                self.send_json({"error": "media_id required"}, 400)
                return
            try:
                comments = cl.media_comments(int(media_id))
                data = [{
                    "username": c.user.username,
                    "full_name": c.user.full_name,
                    "text": c.text,
                    "timestamp": str(c.created_at),
                    "likes": c.like_count or 0,
                } for c in comments]
                self.send_json({"comments": data, "count": len(data)})
            except Exception as e:
                _handle_cl_exception(e, self)

        elif parsed.path == "/track":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            track_profile(username)
            self.send_json({"status": "tracking", "username": username})

        elif parsed.path == "/snapshot":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                track_profile(username)

                followers = cl.user_followers(user.pk, amount=200)
                follower_list = [{"username": f.username, "full_name": f.full_name}
                                 for f in followers.values()]
                save_snapshot(username, "followers", follower_list)

                time.sleep(2.0)
                following = cl.user_following(user.pk, amount=200)
                following_list = [{"username": f.username, "full_name": f.full_name}
                                  for f in following.values()]
                save_snapshot(username, "following", following_list)

                time.sleep(2.0)
                medias = cl.user_medias(user.pk, amount=12)
                post_likes = {}
                for m in medias:
                    time.sleep(2.0)
                    likers = cl.media_likers(m.pk)
                    post_likes[str(m.pk)] = [{"username": l.username, "full_name": l.full_name}
                                              for l in likers]
                save_snapshot(username, "post_likes", post_likes)

                self.send_json({
                    "status": "snapshot_saved",
                    "username": username,
                    "followers": len(follower_list),
                    "following": len(following_list),
                    "posts_liked": len(post_likes),
                })
            except Exception as e:
                _handle_cl_exception(e, self)

        elif parsed.path == "/timeline":
            username = params.get("username", [""])[0]
            days = int(params.get("days", ["30"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                events = []

                follower_snaps = get_last_snapshots(username, "followers", 2)
                if len(follower_snaps) >= 2:
                    current = {u["username"] for u in json.loads(follower_snaps[0][0])}
                    previous = {u["username"] for u in json.loads(follower_snaps[1][0])}
                    for u in json.loads(follower_snaps[1][0]):
                        if u["username"] not in current:
                            events.append({
                                "type": "unfollowed",
                                "username": u["username"],
                                "full_name": u["full_name"],
                                "date": follower_snaps[0][1],
                            })
                    for u in json.loads(follower_snaps[0][0]):
                        if u["username"] not in previous:
                            events.append({
                                "type": "new_follower",
                                "username": u["username"],
                                "full_name": u["full_name"],
                                "date": follower_snaps[0][1],
                            })

                following_snaps = get_last_snapshots(username, "following", 2)
                if len(following_snaps) >= 2:
                    current = {u["username"] for u in json.loads(following_snaps[0][0])}
                    previous = {u["username"] for u in json.loads(following_snaps[1][0])}
                    for u in json.loads(following_snaps[1][0]):
                        if u["username"] not in current:
                            events.append({
                                "type": "unfollowed_by_you",
                                "username": u["username"],
                                "full_name": u["full_name"],
                                "date": following_snaps[0][1],
                            })
                    for u in json.loads(following_snaps[0][0]):
                        if u["username"] not in previous:
                            events.append({
                                "type": "you_followed",
                                "username": u["username"],
                                "full_name": u["full_name"],
                                "date": following_snaps[0][1],
                            })

                likes_snaps = get_last_snapshots(username, "post_likes", 2)
                if len(likes_snaps) >= 2:
                    current_all = json.loads(likes_snaps[0][0])
                    previous_all = json.loads(likes_snaps[1][0])
                    for post_id, current_likers in current_all.items():
                        prev_likers = previous_all.get(post_id, [])
                        curr_usernames = {l["username"] for l in current_likers}
                        prev_usernames = {l["username"] for l in prev_likers}
                        for l in prev_likers:
                            if l["username"] not in curr_usernames:
                                events.append({
                                    "type": "unliked_post",
                                    "username": l["username"],
                                    "full_name": l["full_name"],
                                    "post_id": post_id,
                                    "date": likes_snaps[0][1],
                                })
                        for l in current_likers:
                            if l["username"] not in prev_usernames:
                                events.append({
                                    "type": "liked_post",
                                    "username": l["username"],
                                    "full_name": l["full_name"],
                                    "post_id": post_id,
                                    "date": likes_snaps[0][1],
                                })

                events.sort(key=lambda e: e.get("date", ""), reverse=True)
                self.send_json({"events": events, "count": len(events)})
            except Exception as e:
                err = str(e)
                if "login" in err.lower() or "401" in err:
                    self.send_json({"error": "Login obrigatorio para timeline", "detail": err}, 401)
                else:
                    self.send_json({"error": err}, 500)

        elif parsed.path == "/comments_with_timeline":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                medias = cl.user_medias(user.pk, amount=12)
                all_comments = []
                for m in medias:
                    time.sleep(1.5)
                    comments = cl.media_comments(m.pk)
                    for c in comments:
                        all_comments.append({
                            "type": "comment",
                            "username": c.user.username,
                            "full_name": c.user.full_name,
                            "text": c.text,
                            "post_id": str(m.pk),
                            "likes": c.like_count or 0,
                            "date": str(c.created_at),
                        })
                all_comments.sort(key=lambda e: e.get("date", ""), reverse=True)
                self.send_json({"comments": all_comments, "count": len(all_comments)})
            except Exception as e:
                _handle_cl_exception(e, self)

        elif parsed.path == "/tracked":
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute('SELECT username, active, last_snapshot FROM tracked_profiles')
            rows = [{"username": r[0], "active": bool(r[1]), "last_snapshot": r[2]}
                    for r in c.fetchall()]
            conn.close()
            self.send_json({"profiles": rows})
        
        else:
            self.send_json({"error": "endpoint not found"}, 404)
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

def main():
    if "--setup-session" in sys.argv:
        setup_session_interativo()
        return

    init_db()

    if PROXY_URL:
        print(f"Proxy configurado: {PROXY_URL}")

    _carregar_sessao()
    
    port = int(os.environ.get("PORT", 8500))
    server = HTTPServer(("0.0.0.0", port), InstagramHandler)
    print(f"Instagram API rodando em http://0.0.0.0:{port}")
    print("Endpoints: /profile, /posts, /likers, /followers, /following, /comments, /snapshot, /timeline, /track")
    server.serve_forever()

if __name__ == "__main__":
    main()
