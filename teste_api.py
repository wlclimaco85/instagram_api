"""
Teste sistematico da RapidAPI instagram-scraper-stable-api para
coletar followers/following de @hednaidealves.

Endpoint unico:
    POST https://instagram-scraper-stable-api.p.rapidapi.com/get_ig_user_followers_v2.php
    campos: username_or_url, data (followers|following), amount, pagination_token

Uso:
    python teste_api.py

Chaves: lidas de chaves_teste.txt (uma por linha) + .env (RAPIDAPI_KEY, RAPIDAPI_KEY_2...).
Resultados: teste_resultados/<nome>.json
"""

import json
import os
import re
import sys
import time
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Patch SSL (mesmo do server.py)
_orig = requests.Session.send
def _no_verify(self, *a, **kw):
    kw['verify'] = False
    return _orig(self, *a, **kw)
requests.Session.send = _no_verify

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── Constantes ───────────────────────────────────────────────────────────────

USUARIO          = "hednaidealves"
URL_PERFIL       = f"https://www.instagram.com/{USUARIO}/"
EXPECT_FOLLOWERS = 503
EXPECT_FOLLOWING = 717

HOST     = "instagram-scraper-stable-api.p.rapidapi.com"
ENDPOINT = f"https://{HOST}/get_ig_user_followers_v2.php"

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "..", "scripts")
OUTPUT_DIR  = os.path.join(BASE_DIR, "teste_resultados")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Chaves ───────────────────────────────────────────────────────────────────

def _carregar_chaves():
    # .env
    env = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env):
        with open(env) as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith("#") and "=" in linha:
                    k, _, v = linha.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    chaves = []
    for i in range(1, 11):
        nome = "RAPIDAPI_KEY" if i == 1 else f"RAPIDAPI_KEY_{i}"
        v = os.environ.get(nome, "").strip()
        if v:
            chaves.append((f"env_k{i}", v))

    # chaves_teste.txt (prioridade: entra na frente)
    txt = os.path.join(BASE_DIR, "chaves_teste.txt")
    extras = []
    if os.path.exists(txt):
        with open(txt) as f:
            for linha in f:
                c = linha.strip()
                if c and not c.startswith("#") and not any(c == v for _, v in chaves):
                    extras.append((f"txt_k{len(extras)+1}", c))
        chaves = extras + chaves  # chaves_teste.txt na frente

    return chaves

CHAVES = _carregar_chaves()

# ─── Lista manual de referência ───────────────────────────────────────────────

_USERNAME_RE = re.compile(r'^[a-z0-9._]+$')
_EXCLUIR = {
    'arteclarice','steff','mariaperpetuaribeiro','dudurezende','joao',
    'carla','farhad','.','rafhael','ferreira','beemdizer_','andre',
}

def _ler_manual(path):
    usuarios = {}
    try:
        with open(path, encoding="utf-8") as f:
            linhas = [l.rstrip('\n').strip() for l in f if l.strip()]
        i = 0
        while i < len(linhas):
            atual = linhas[i]
            if not _USERNAME_RE.match(atual) or atual in _EXCLUIR:
                i += 1; continue
            nome = ""
            if i + 1 < len(linhas) and not _USERNAME_RE.match(linhas[i + 1]):
                nome = linhas[i + 1]; i += 2
            else:
                i += 1
            if atual not in usuarios:
                usuarios[atual] = nome
    except FileNotFoundError:
        print(f"  [AVISO] não encontrado: {path}")
    return usuarios

MANUAL_FOLLOWERS = _ler_manual(os.path.join(SCRIPTS_DIR, "followers_hednaide.txt"))
MANUAL_FOLLOWING = _ler_manual(os.path.join(SCRIPTS_DIR, "following_hednaide.txt"))

print(f"\n=== Referência manual ===")
print(f"  followers : {len(MANUAL_FOLLOWERS)} (esperado {EXPECT_FOLLOWERS})")
print(f"  following : {len(MANUAL_FOLLOWING)} (esperado {EXPECT_FOLLOWING})")
print(f"\n=== Chaves disponíveis: {len(CHAVES)} ===")
for nome, chave in CHAVES:
    print(f"  {nome}: ...{chave[-8:]}")

# ─── Utilitários ──────────────────────────────────────────────────────────────

def _salvar(nome, dados):
    path = os.path.join(OUTPUT_DIR, f"{nome}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    print(f"    → salvo: {path}")

def _comparar(label, coletados, ref_manual, esperado):
    col_lower = {u.lower() for u in coletados}
    man_lower = set(ref_manual.keys())
    ausentes  = sorted(man_lower - col_lower)
    extras    = sorted(col_lower - man_lower)
    pct = len(col_lower) / esperado * 100 if esperado else 0
    print(f"\n  ┌─ {label}")
    print(f"  │  API coletou  : {len(col_lower)} / {esperado} ({pct:.1f}%)")
    print(f"  │  Ausentes     : {len(ausentes)} (estão no manual, não vieram da API)")
    print(f"  │  Extras       : {len(extras)} (vieram da API, não estão no manual)")
    if ausentes:
        print(f"  │  Amostra aus  : {ausentes[:6]}")
    print(f"  └──────────────────────────────────────")
    return {
        "coletados": len(col_lower),
        "esperado": esperado,
        "cobertura_pct": round(pct, 1),
        "ausentes_qtd": len(ausentes),
        "extras_qtd": len(extras),
        "ausentes": ausentes,
    }

_MAX_RETRY = 4  # tentativas para erro transiente ("try again later", 5xx)

def _post(chave, tipo, username_or_url, amount, token=""):
    """
    POST ao endpoint com retry/backoff para erros transientes.
    Retorna (payload, status_code, erro_str).
    Erro permanente (429) não é retentado.
    """
    for tentativa in range(1, _MAX_RETRY + 1):
        try:
            r = requests.post(
                ENDPOINT,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "x-rapidapi-key": chave,
                    "x-rapidapi-host": HOST,
                },
                data={
                    "username_or_url": username_or_url,
                    "data": tipo,
                    "amount": amount,
                    "pagination_token": token,
                },
                timeout=40,
            )
            try:
                p = r.json()
            except Exception:
                return None, r.status_code, f"JSON inválido: {r.text[:100]}"

            erro = str(p.get("error", "") or "") if isinstance(p, dict) else ""

            # Sucesso real
            if r.status_code == 200 and not erro:
                return p, r.status_code, ""

            # Erro permanente: 429 rate limit — desiste imediatamente
            if r.status_code == 429:
                return p, r.status_code, erro or "429 rate limit"

            # Erro transiente: "try again later" ou 5xx
            transiente = (
                r.status_code in (500, 502, 503, 504)
                or "try again" in erro.lower()
                or "temporarily" in erro.lower()
            )
            if transiente and tentativa < _MAX_RETRY:
                espera = 3 * tentativa  # 3s, 6s, 9s
                print(f"    [retry {tentativa}/{_MAX_RETRY-1}] HTTP {r.status_code} '{erro[:60]}' — aguardando {espera}s")
                time.sleep(espera)
                continue

            return p, r.status_code, erro
        except Exception as e:
            if tentativa < _MAX_RETRY:
                time.sleep(3 * tentativa)
                continue
            return None, 0, str(e)
    return None, 0, "max retries"

def _extrair_usuarios(payload, tipo):
    """Extrai lista de usuários do payload tentando todos os campos conhecidos."""
    if not isinstance(payload, dict):
        return []
    for campo in ("users", tipo, "followers", "following", "data", "items"):
        v = payload.get(campo)
        if isinstance(v, list):
            return v
    return []

def _extrair_token(payload):
    """Extrai token de próxima página."""
    if not isinstance(payload, dict):
        return ""
    return (
        payload.get("pagination_token") or payload.get("next_max_id") or
        payload.get("next_page_token") or payload.get("next_cursor") or
        payload.get("end_cursor") or
        (payload.get("page_info") or {}).get("end_cursor") or
        (payload.get("page_info") or {}).get("next_max_id") or ""
    )

def _paginar(label, chave, tipo, username_or_url, page_size, max_pag=80, delay=2.0):
    """
    Pagina até esgotar tokens. Retorna (lista_usuarios, historico_paginas).
    """
    todos   = []
    vistos  = set()
    token   = ""
    hist    = []
    parou_por = "?"

    print(f"\n  [{label}]")
    print(f"    tipo={tipo} page={page_size} url={username_or_url} chave=...{chave[-8:]}")

    for pag in range(1, max_pag + 1):
        p, status, erro = _post(chave, tipo, username_or_url, page_size, token)

        if status != 200 or erro:
            parou_por = f"HTTP {status} erro={erro or '-'}"
            print(f"    pag {pag}: {parou_por} — parando")
            hist.append({"pag": pag, "status": status, "erro": erro})
            break

        if pag == 1:
            print(f"    pag 1: keys do payload = {list(p.keys())}")

        usuarios = _extrair_usuarios(p, tipo)
        if not usuarios:
            parou_por = "lista vazia"
            print(f"    pag {pag}: lista vazia (keys={list(p.keys())}) — parando")
            hist.append({"pag": pag, "keys": list(p.keys()), "lista_vazia": True})
            break

        lote = [
            {"username": u.get("username", ""), "full_name": u.get("full_name", u.get("name", ""))}
            for u in usuarios
            if u.get("username") and u.get("username").lower() not in vistos
        ]
        vistos.update(u["username"].lower() for u in lote)
        todos.extend(lote)

        novo_token = _extrair_token(p)
        repetiu   = len(lote) == 0 and len(usuarios) > 0

        print(f"    pag {pag}: recv={len(usuarios)} novos={len(lote)} total={len(todos)} "
              f"tok={'S' if novo_token else 'N'}{' [REPETICAO]' if repetiu else ''}")

        hist.append({
            "pag": pag, "recv": len(usuarios), "novos": len(lote),
            "total": len(todos), "token": bool(novo_token),
            "token_prefix": novo_token[:30] if novo_token else "",
        })

        if not novo_token:
            parou_por = "sem token (fim da lista)"
            print(f"    → {parou_por}")
            break
        if repetiu:
            parou_por = "repetição sem avanço"
            print(f"    → {parou_por}")
            break

        token = novo_token
        time.sleep(delay)

    print(f"    TOTAL: {len(todos)} usuários | parou: {parou_por}")
    return todos, hist, parou_por

# ─── FASE 1: Diagnóstico rápido ───────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"FASE 1 — Diagnóstico das chaves (1 req de 5 registros cada)")
print(f"{'='*62}")

chaves_ok = []
diag = {}

for nome, chave in CHAVES:
    p, status, erro = _post(chave, "followers", URL_PERFIL, 5)
    ok  = status == 200 and not erro
    qtd = len(_extrair_usuarios(p, "followers")) if ok and p else 0
    diag[nome] = {"status": status, "erro": erro, "ok": ok, "amostra": qtd}
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {nome} ...{chave[-8:]}: HTTP {status} "
          f"erro={erro or '-':30s} amostra={qtd}")
    if ok:
        chaves_ok.append((nome, chave))
    time.sleep(1)

print(f"\n  Chaves OK: {len(chaves_ok)}/{len(CHAVES)}")
_salvar("01_diagnostico_chaves", diag)

if not chaves_ok:
    print("\n  NENHUMA chave funcionando. Adicione chaves em chaves_teste.txt")
    sys.exit(1)

# ─── FASE 2: Inspeção do payload ──────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"FASE 2 — Inspeção do payload completo (page_size=10)")
print(f"{'='*62}")

nome0, chave0 = chaves_ok[0]

for tipo in ("followers", "following"):
    for url_format in (URL_PERFIL, USUARIO):
        p, status, erro = _post(chave0, tipo, url_format, 10)
        label = f"tipo={tipo} url={url_format[:30]}"
        if status == 200 and not erro:
            usuarios = _extrair_usuarios(p, tipo)
            token    = _extrair_token(p)
            print(f"\n  [{label}]")
            print(f"    keys: {list(p.keys())}")
            print(f"    usuarios encontrados: {len(usuarios)}")
            if usuarios:
                print(f"    campos do user[0]: {list(usuarios[0].keys()) if isinstance(usuarios[0], dict) else type(usuarios[0])}")
            print(f"    token paginação: {token[:50] if token else 'NENHUM'}")
            _salvar(f"02_payload_{tipo}_{('url' if '/' in str(url_format) else 'user')}", p)
        else:
            print(f"\n  [{label}] FALHOU HTTP {status} erro={erro}")
        time.sleep(2)

# ─── FASE 3: Estratégias de paginação ─────────────────────────────────────────

print(f"\n{'='*62}")
print(f"FASE 3 — Estratégias de paginação")
print(f"{'='*62}")

# Cada estratégia: (label, page_size, url_format, delay)
ESTRATEGIAS = [
    ("A_pg200_url",  200, URL_PERFIL, 2.5),   # page=200, URL completa
    ("B_pg200_user", 200, USUARIO,    2.5),   # page=200, só username
    ("C_pg50_url",    50, URL_PERFIL, 2.0),   # page=50, URL completa
    ("D_pg10_url",    10, URL_PERFIL, 1.5),   # page=10, muitas páginas
]

resultados = {}

for est_label, page_size, url_fmt, delay in ESTRATEGIAS:
    for tipo, esperado, ref in [
        ("followers", EXPECT_FOLLOWERS, MANUAL_FOLLOWERS),
        ("following", EXPECT_FOLLOWING, MANUAL_FOLLOWING),
    ]:
        chk = f"{est_label}_{tipo}"
        print(f"\n{'─'*62}")
        print(f"  Estratégia: {chk}")

        todos   = []
        vistos  = set()
        hist_ck = {}

        for nome_c, chave_c in chaves_ok:
            lista, hist, parou = _paginar(
                f"{chk}/{nome_c}", chave_c, tipo, url_fmt, page_size, delay=delay)
            novos = [u for u in lista if u["username"].lower() not in vistos]
            vistos.update(u["username"].lower() for u in novos)
            todos.extend(novos)
            hist_ck[nome_c] = {"coletados": len(lista), "novos_unicos": len(novos), "parou": parou}
            print(f"    {nome_c}: {len(lista)} col. / {len(novos)} novos | acum={len(todos)}")
            time.sleep(3)

        comp = _comparar(chk, [u["username"] for u in todos], ref, esperado)
        reg  = {
            "estrategia": {"page_size": page_size, "url_format": url_fmt},
            "tipo": tipo, "usuarios": todos,
            "por_chave": hist_ck, "comparativo": comp,
        }
        resultados[chk] = reg
        _salvar(f"03_{chk}", reg)

# ─── FASE 4: Combinar todas as chaves com melhor estratégia ───────────────────

if len(chaves_ok) > 1:
    print(f"\n{'='*62}")
    print(f"FASE 4 — Todas as {len(chaves_ok)} chaves, page=200, URL completa")
    print(f"{'='*62}")

    for tipo, esperado, ref in [
        ("followers", EXPECT_FOLLOWERS, MANUAL_FOLLOWERS),
        ("following", EXPECT_FOLLOWING, MANUAL_FOLLOWING),
    ]:
        chk = f"E_todas_chaves_{tipo}"
        todos  = []
        vistos = set()
        hist_ck = {}

        for nome_c, chave_c in chaves_ok:
            lista, hist, parou = _paginar(
                f"{chk}/{nome_c}", chave_c, tipo, URL_PERFIL, 200, delay=2.5)
            novos = [u for u in lista if u["username"].lower() not in vistos]
            vistos.update(u["username"].lower() for u in novos)
            todos.extend(novos)
            hist_ck[nome_c] = {"coletados": len(lista), "novos_unicos": len(novos), "parou": parou}
            print(f"    {nome_c}: {len(lista)} col. / {len(novos)} novos | acum={len(todos)}")
            time.sleep(3)

        comp = _comparar(chk, [u["username"] for u in todos], ref, esperado)
        reg  = {
            "estrategia": "todas_chaves_pg200",
            "tipo": tipo, "usuarios": todos,
            "por_chave": hist_ck, "comparativo": comp,
        }
        resultados[chk] = reg
        _salvar(f"04_{chk}", reg)

# ─── Relatório Final ──────────────────────────────────────────────────────────

print(f"\n{'='*62}")
print(f"RELATÓRIO FINAL")
print(f"{'='*62}")

melhor = {
    "followers": {"coletados": 0, "label": "-"},
    "following": {"coletados": 0, "label": "-"},
}

for label, dados in resultados.items():
    tipo = dados["tipo"]
    c    = dados["comparativo"]
    print(f"  {label:50s} → {c['coletados']:4d} ({c['cobertura_pct']:.1f}%)")
    if c["coletados"] > melhor[tipo]["coletados"]:
        melhor[tipo] = {"coletados": c["coletados"], "label": label, "pct": c["cobertura_pct"]}

print(f"\n  Melhor FOLLOWERS : {melhor['followers']}")
print(f"  Melhor FOLLOWING : {melhor['following']}")

_salvar("ZZ_relatorio_final", {
    "timestamp": datetime.now().isoformat(),
    "usuario": USUARIO,
    "chaves_ok": len(chaves_ok),
    "melhor": melhor,
    "todos": {k: v["comparativo"] for k, v in resultados.items()},
})

print(f"\nResultados em: {OUTPUT_DIR}")
print(f"Concluído: {datetime.now().strftime('%H:%M:%S')}")
