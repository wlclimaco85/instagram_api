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
import urllib3
from datetime import datetime, timedelta
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Força UTF-8 no console: sem isto, o cp1252 do Windows quebra o print() ao logar
# mensagens de erro com '→'/emoji, mascarando a causa real do erro (charmap codec).
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Desabilita aviso de SSL não verificado (problema de CA no Windows/Python 3.14)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Patch global: força verify=False em todas as requests.Session (SSLCertVerificationError no instagrapi)
_orig_requests_send = http_requests.Session.send
def _requests_send_no_verify(self, *args, **kwargs):
    kwargs['verify'] = False
    return _orig_requests_send(self, *args, **kwargs)
http_requests.Session.send = _requests_send_no_verify

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
SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "sessions.json")
DB_FILE = os.path.join(os.path.dirname(__file__), "timeline.db")

# Pool de sessões: várias contas para o job horário rotacionar quando uma
# entra em soft-block (429/login_required) ou é invalidada pelo Instagram.
_sessoes = []      # lista de {"label": str, "cookies": {sessionid, csrftoken, ds_user_id}}
_sessao_idx = 0    # índice da sessão ativa no pool

def _novo_client():
    """Cria Client do instagrapi com SSL desabilitado (SSLCertVerificationError no Windows/Python 3.14)."""
    if not _INSTAGRAPI_OK:
        return None
    c = Client()
    c.private.verify = False
    c.public.verify = False
    return c

cl = _novo_client()
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
            verify=False,
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
            verify=False,
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
    """Fallback: raspa metatags og: da página pública do Instagram.
    Usa Googlebot UA para forçar SSR com og: tags (browser UA retorna SPA sem dados).
    """
    try:
        time.sleep(1.5)
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        r = http_requests.get(
            f'https://www.instagram.com/{username}/',
            headers=headers,
            proxies=_PROXIES,
            timeout=20,
            allow_redirects=True,
            verify=False,
        )
        print(f"[IG-HTML] @{username} → HTTP {r.status_code}")
        if r.status_code != 200:
            return None
        html = r.content.decode('utf-8', errors='replace')

        def _meta(prop):
            import re
            m = re.search('property="og:' + prop + '"[^>]*content="([^"]+)"', html)
            if not m:
                m = re.search('content="([^"]+)"[^>]*property="og:' + prop + '"', html)
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

    # Todos falharam — garante retorno de erro útil (não None)
    if erro_api is None:
        erro_api = {
            "error": "auth_required",
            "message": "Nenhum metodo de busca funcionou. Configure session.json: python server.py --setup-session",
        }
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

def _extrair_cookies(dados):
    """Extrai sessionid/csrftoken/ds_user_id de um dict de sessão (formato browser ou instagrapi)."""
    if not isinstance(dados, dict):
        return None
    cookies = dados.get("cookies", {})
    auth = dados.get("authorization_data", {})
    sessionid = cookies.get("sessionid") or auth.get("sessionid")
    if not sessionid:
        return None
    csrftoken = cookies.get("csrftoken", "")
    ds_user_id = str(cookies.get("ds_user_id", "") or auth.get("ds_user_id", ""))
    return {"sessionid": sessionid, "csrftoken": csrftoken, "ds_user_id": ds_user_id}


def _aplicar_sessao(idx):
    """Injeta os cookies da sessão idx do pool no client global e ativa o modo autenticado."""
    global LOGIN_OK, _sessao_idx
    cookies = _sessoes[idx]["cookies"]
    cl.private.cookies.update(cookies)
    cl.public.cookies.update(cookies)
    _sessao_idx = idx
    LOGIN_OK = True


def _carregar_sessao():
    """Carrega o pool de sessões e ativa a primeira.

    Prioriza sessions.json (lista de contas para rotação); se ausente, usa o
    session.json único (retrocompatível). Injeta cookies direto, sem chamada de
    verificação (evita 467/consent_required).
    """
    global _sessoes
    if not _INSTAGRAPI_OK:
        print("instagrapi nao instalado. Modo somente-leitura.")
        return

    brutas = []
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, encoding="utf-8") as f:
                conteudo = json.load(f)
            brutas = conteudo.get("sessions", []) if isinstance(conteudo, dict) else conteudo
        except Exception as e:
            print(f"Falha ao ler sessions.json: {e}")
    elif os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, encoding="utf-8") as f:
                brutas = [json.load(f)]
        except Exception as e:
            print(f"Falha ao ler session.json: {e}")

    _sessoes = []
    for i, dados in enumerate(brutas):
        cookies = _extrair_cookies(dados)
        if cookies:
            label = dados.get("label", f"sessao{i + 1}")
            _sessoes.append({"label": label, "cookies": cookies, "has_error": False})

    if not _sessoes:
        print("Nenhuma sessao valida (sessions.json/session.json). Rode: python server.py --setup-session")
        print("Modo somente-leitura ativo. Endpoints: /profile, /posts")
        return

    _aplicar_sessao(0)
    print(f"Pool de sessoes carregado: {len(_sessoes)} sessao(oes). Ativa: '{_sessoes[0]['label']}' (user_id={cl.user_id})")
    print("Modo autenticado ativo. Todos os endpoints disponiveis.")


def _rotacionar_sessao():
    """Troca para a próxima sessão do pool. Retorna False se há apenas uma sessão."""
    if len(_sessoes) <= 1:
        return False
    proximo = (_sessao_idx + 1) % len(_sessoes)
    _aplicar_sessao(proximo)
    print(f"[POOL] Rotacionando para sessao '{_sessoes[proximo]['label']}' (idx {proximo})")
    return True


def _invalidar_sessao():
    """Sessão rejeitada pelo IG nesta request (geralmente soft-block 429/login_required, transitório).

    Rotaciona para outra conta se houver. NÃO desliga o modo autenticado por um
    login_required isolado: o soft-block volta sozinho e endpoints com fallback
    GraphQL (ex.: /comments) seguem funcionando. Readonly só quando não há
    nenhuma sessão carregada no pool.
    """
    global LOGIN_OK
    if not _sessoes:
        LOGIN_OK = False
        print("Nenhuma sessao no pool. Rode: python server.py --setup-session")
        return
    _rotacionar_sessao()  # troca de conta se houver backup; mantém autenticado de qualquer forma


def chamar_autenticado(operacao):
    """Executa uma operação autenticada com rotação automática de sessão.

    Tenta com a sessão ativa; se o IG responder login_required/429/rate-limit,
    rotaciona para a próxima sessão do pool e tenta de novo, até esgotar o pool.
    Re-levanta a última exceção se todas falharem.
    """
    tentativas = max(1, len(_sessoes))
    ultima_exc = None
    for _ in range(tentativas):
        try:
            return operacao()
        except (LoginRequired, ClientLoginRequired) as e:
            ultima_exc = e
            if _sessoes:
                _sessoes[_sessao_idx]["has_error"] = True
        except Exception as e:
            msg = str(e).lower()
            if any(t in msg for t in ("429", "login_required", "rate", "max retries")):
                ultima_exc = e
                if _sessoes:
                    _sessoes[_sessao_idx]["has_error"] = True
            else:
                raise
        if not _rotacionar_sessao():
            break
    if ultima_exc:
        raise ultima_exc


def _ds_user_id_do_sessionid(sessionid):
    """Extrai o ds_user_id do início do sessionid (formato '<id>%3A<resto>' ou '<id>:<resto>')."""
    from urllib.parse import unquote
    texto = unquote(sessionid or "")
    return texto.split(":", 1)[0] if ":" in texto else ""


def salvar_sessions(entradas):
    """Normaliza e grava o pool em sessions.json. Aceita cada entrada como
    {"label","sessionid","csrftoken"} ou {"label","cookies":{...}}. O ds_user_id
    é derivado do próprio sessionid quando não informado."""
    sessoes = []
    for i, entrada in enumerate(entradas):
        cookies = entrada.get("cookies") if isinstance(entrada, dict) else None
        if not cookies:
            sessionid = (entrada.get("sessionid") or "").strip()
            if not sessionid:
                continue
            cookies = {
                "sessionid": sessionid,
                "csrftoken": (entrada.get("csrftoken") or "").strip(),
                "ds_user_id": (entrada.get("ds_user_id") or "").strip() or _ds_user_id_do_sessionid(sessionid),
            }
        label = (entrada.get("label") or f"sessao{i + 1}").strip()
        sessoes.append({"label": label, "cookies": cookies})
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"sessions": sessoes}, f, ensure_ascii=False, indent=2)
    return len(sessoes)


def _erro_auth():
    return {
        "error": "auth_required",
        "message": "Sessao expirada ou ausente. Rode: python server.py --setup-session no servidor.",
    }


def _normalizar_comentario_objeto(c):
    """Normaliza um Comment da private API (objeto instagrapi)."""
    return {
        "username": c.user.username,
        "full_name": c.user.full_name or "",
        "text": c.text,
        "timestamp": str(c.created_at),
        "likes": c.like_count or 0,
    }


def _normalizar_comentario_dict(c):
    """Normaliza um comentário cru do GraphQL público (dict). Não traz full_name."""
    usuario = c.get("user", {})
    return {
        "username": usuario.get("username", ""),
        "full_name": usuario.get("full_name", ""),
        "text": c.get("text", ""),
        "timestamp": str(c.get("created_at", "")),
        "likes": c.get("comment_like_count", 0) or 0,
    }


def coletar_comentarios(media_id, amount=50):
    """Coleta comentários de um post resiliente a soft-block.

    A private API é mais completa, mas em soft-block (429/login_required) o
    Instagram a rejeita. Nesse caso cai para o GraphQL público
    (media_comments_gql), que segue funcionando com a mesma sessão — por isso
    o LoginRequired aqui NÃO invalida a sessão, apenas troca de método.
    """
    try:
        comentarios = chamar_autenticado(lambda: cl.media_comments(media_id, amount=amount))
        if comentarios:
            return [_normalizar_comentario_objeto(c) for c in comentarios]
    except (LoginRequired, ClientLoginRequired):
        print(f"[/comments] private bloqueada (login_required) → fallback GraphQL")
    except Exception as e:
        print(f"[/comments] private falhou ({type(e).__name__}) → fallback GraphQL")

    gql = cl.media_comments_gql(media_id, amount=amount)
    return [_normalizar_comentario_dict(c) for c in gql]


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
    ig.private.verify = False
    ig.public.verify = False

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
            self.send_json({
                "login_ok": LOGIN_OK,
                "mode": "authenticated" if LOGIN_OK else "readonly",
                "username": cl.username if LOGIN_OK and cl else None,
            })

        elif parsed.path == "/sessions":
            self.send_json({
                "total": len(_sessoes),
                "ativa": _sessoes[_sessao_idx]["label"] if _sessoes else None,
                "labels": [s["label"] for s in _sessoes],
                "login_ok": LOGIN_OK,
                "sessions_list": [
                    {
                        "label": s["label"],
                        "is_active": (i == _sessao_idx),
                        "has_error": s.get("has_error", False),
                    }
                    for i, s in enumerate(_sessoes)
                ],
            })
        
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
                        "hd_profile_pic": str(user.profile_pic_url_hd) if user.profile_pic_url_hd else None,
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
                likers = chamar_autenticado(lambda: cl.media_likers(int(media_id)))
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
                user = chamar_autenticado(lambda: cl.user_info_by_username(username))
                followers = chamar_autenticado(lambda: cl.user_followers(user.pk, amount=amount))
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
                user = chamar_autenticado(lambda: cl.user_info_by_username(username))
                following = chamar_autenticado(lambda: cl.user_following(user.pk, amount=amount))
                data = [{"username": f.username, "full_name": f.full_name} for f in following.values()]
                self.send_json({"following": data, "count": len(data)})
            except Exception as e:
                _handle_cl_exception(e, self)
        
        elif parsed.path == "/comments":
            if not LOGIN_OK:
                self.send_json(_erro_auth(), 401)
                return
            media_id = params.get("media_id", [""])[0]
            amount = int(params.get("amount", ["50"])[0])
            if not media_id:
                self.send_json({"error": "media_id required"}, 400)
                return
            try:
                data = coletar_comentarios(int(media_id), amount)
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

    def do_DELETE(self):
        parsed = urlparse(self.path)
        # DELETE /sessions/<label>  — remove uma sessao do pool pelo apelido
        if parsed.path.startswith("/sessions/"):
            label = parsed.path[len("/sessions/"):]
            if not label:
                self.send_json({"error": "label required"}, 400)
                return
            global _sessoes, _sessao_idx
            antes = len(_sessoes)
            _sessoes = [s for s in _sessoes if s["label"] != label]
            if len(_sessoes) < antes:
                # Salva o pool atualizado em disco
                with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                    json.dump({"sessions": _sessoes}, f, ensure_ascii=False, indent=2)
                # Reajusta o indice ativo
                if _sessoes:
                    _sessao_idx = min(_sessao_idx, len(_sessoes) - 1)
                    _aplicar_sessao(_sessao_idx)
                else:
                    _sessao_idx = 0
                self.send_json({"status": "removed", "label": label, "total": len(_sessoes)})
            else:
                self.send_json({"error": f"sessao '{label}' nao encontrada"}, 404)
        else:
            self.send_json({"error": "endpoint not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/sessions":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body)
                entradas = payload.get("sessions", [])
                if not isinstance(entradas, list) or not entradas:
                    self.send_json({"error": "Informe ao menos uma sessao"}, 400)
                    return
                total = salvar_sessions(entradas)
                _carregar_sessao()  # recarrega o pool em runtime, sem reiniciar
                self.send_json({
                    "status": "saved",
                    "total": total,
                    "ativa": _sessoes[_sessao_idx]["label"] if _sessoes else None,
                    "login_ok": LOGIN_OK,
                })
            except Exception as e:
                self.send_json({"error": str(e)}, 400)
        else:
            self.send_json({"error": "endpoint not found"}, 404)

    def do_OPTIONS(self):
        # Preflight CORS para o POST com Content-Type application/json vindo do Flutter web.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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

    # ThreadingHTTPServer: uma request lenta (instagrapi em retries no soft-block)
    # não trava nem derruba o servidor inteiro como acontecia no HTTPServer single-thread.
    ThreadingHTTPServer.allow_reuse_address = True
    ThreadingHTTPServer.daemon_threads = True
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), InstagramHandler)
    except OSError as e:
        print(f"[ERRO] Nao foi possivel abrir a porta {port}: {e}")
        print("Provavel causa: ja existe um server.py rodando nessa porta.")
        print("Encerre o processo anterior (ou rode _kill_servers.ps1) e tente de novo.")
        return

    print(f"Instagram API rodando em http://0.0.0.0:{port}")
    print("Endpoints: /profile, /posts, /likers, /followers, /following, /comments, /snapshot, /timeline, /track, /sessions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor (Ctrl+C).")
    except Exception:
        # Sem isto, um erro fatal derrubava o processo sem deixar rastro ("caiu do nada").
        import traceback
        print("[FATAL] serve_forever encerrou por exceção:")
        traceback.print_exc()
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
