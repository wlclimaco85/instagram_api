# -*- coding: utf-8 -*-
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
cl.private.cookies.update({'sessionid': c['sessionid'], 'csrftoken': c['csrftoken'], 'ds_user_id': str(c['ds_user_id'])})
cl.public.cookies.update({'sessionid': c['sessionid'], 'csrftoken': c['csrftoken'], 'ds_user_id': str(c['ds_user_id'])})

mid = 3918726773265025717

# Tenta via metodo v1 (private)
try:
    cms = cl.media_comments(mid, amount=10)
    print("media_comments OK:", len(cms))
except Exception as e:
    print("media_comments ERRO:", type(e).__name__, "-", str(e)[:200])

# Tenta forcar via GraphQL publico
try:
    cms2 = cl.media_comments_gql(mid, amount=10) if hasattr(cl, 'media_comments_gql') else None
    print("media_comments_gql:", len(cms2) if cms2 else "metodo ausente")
except Exception as e:
    print("media_comments_gql ERRO:", type(e).__name__, "-", str(e)[:200])
