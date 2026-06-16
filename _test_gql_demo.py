# -*- coding: utf-8 -*-
"""Demonstra: comentarios via GraphQL publico (funciona em soft-block) e tentativa de likers."""
import requests as http_requests
import urllib3
urllib3.disable_warnings()
_orig = http_requests.Session.send
def _no_ssl(self, *a, **kw):
    kw['verify'] = False
    return _orig(self, *a, **kw)
http_requests.Session.send = _no_ssl

import json
from instagrapi import Client

with open('session.json') as f:
    s = json.load(f)
c = s['cookies']
cl = Client()
for alvo in (cl.private, cl.public):
    alvo.cookies.update({'sessionid': c['sessionid'], 'csrftoken': c['csrftoken'], 'ds_user_id': str(c['ds_user_id'])})

mid = 3918726773265025717

print(f"===== FOTO id={mid} =====\n")

# COMENTARIOS via GraphQL publico
print("-- COMENTARIOS (via media_comments_gql) --")
try:
    comentarios = cl.media_comments_gql(mid, amount=30)
    print(f"Total: {len(comentarios)}\n")
    for cm in comentarios:
        print(f"  @{cm.user.username}: {cm.text}")
except Exception as e:
    print(f"ERRO: {type(e).__name__} - {str(e)[:200]}")

# LIKERS (quem curtiu) — so private API autenticada
print("\n-- LIKERS (quem curtiu) --")
try:
    likers = cl.media_likers(mid)
    print(f"Total: {len(likers)}")
    for l in likers:
        print(f"  @{l.username} ({l.full_name})")
except Exception as e:
    print(f"ERRO: {type(e).__name__} - {str(e)[:200]}")
