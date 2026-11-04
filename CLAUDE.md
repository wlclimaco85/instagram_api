# CLAUDE.md — instagram_api (Servidor Python do Monitor de Instagram)

> Regras globais da workspace estão em `C:\App_Academia\CLAUDE.md`. Em conflito, o pai prevalece.

## Project

**Mini-servidor HTTP em Python que alimenta o "Monitor de Instagram" dos apps Flutter.**

`server.py` sobe um `HTTPServer` na **porta 8500** e expõe endpoints JSON que o Flutter consome
(`InstagramService` aponta para `http://127.0.0.1:8500`). Busca perfil, posts, seguidores, seguindo,
curtidas e comentários de perfis públicos/monitorados e guarda snapshots para montar timeline.

**Core Value:** trazer dados do Instagram de forma resiliente, caindo entre vários métodos quando um
falha, e funcionando mesmo com o IP da máquina bloqueado para login de API.

## Stack

- **Python 3** (há 3.12 e 3.14 na máquina). `http.server` puro + `requests` + `sqlite3` (`timeline.db`).
- **instagrapi** para endpoints autenticados; fallbacks sem auth com `requests`.
- Sem framework web, sem build. Rodar: `python server.py` (ou `--setup-session`).

## Endpoints

`/health`, `/login_status`, `/profile`, `/posts` (funcionam sem login) · `/followers`, `/following`,
`/likers`, `/comments`, `/comments_with_timeline`, `/snapshot`, `/timeline`, `/track`, `/tracked`
(exigem sessão autenticada, `LOGIN_OK`).

## Autenticação (session.json) — pontos que já custaram caro

- O **IP desta máquina está na blacklist** do Instagram para login via API (instagrapi `login()` →
  BadPassword/challenge). **Login pelo browser NÃO é bloqueado.**
- `session.json` é montado a partir dos **cookies do browser** (`sessionid`, `csrftoken`,
  `ds_user_id`). O `sessionid` é `HttpOnly` — pega-se no DevTools → Application → Cookies, não por JS.
- `_carregar_sessao()` **injeta os cookies direto** no `instagrapi.Client` (`cl.private.cookies`/
  `cl.public.cookies` + `cl.user_id`), **sem** `login_by_sessionid()` — a verificação da API Android
  com cookie web retorna **HTTP 467** e derruba o login. `user_id` é property read-only (sem setter).
- **SSL no Windows/Python 3.14:** `SSLCertVerificationError`. Correção: monkey-patch global
  `requests.Session.send` forçando `verify=False` (no topo do `server.py`, antes de importar instagrapi);
  `c.private.verify=False` sozinho NÃO resolve. `urllib3.disable_warnings()` também.
- Fallbacks de perfil (sem auth): API privada `web_profile_info` → GraphQL `?__a=1` → scraping HTML
  com **User-Agent Googlebot** (browser UA devolve SPA sem dados). Campo correto do instagrapi é
  `user.profile_pic_url_hd` (não `hd_profile_pic_url_info`).

## Segurança

- **Credenciais NUNCA no git.** Ficam em `.env` (gitignored). Não commitar `session.json` nem `.env`.
- Não repetir valores de cookie/senha em respostas/logs.

## Testes & Code Review

- Sem suíte formal: validar com requests reais aos endpoints (ex.: `/profile?username=...` deve vir do
  instagrapi autenticado, sem `"_source":"html"`, quando `LOGIN_OK`).
- **Push para `main` → code review OBRIGATÓRIO.** Encoding UTF-8 (arquivos `.py`).
