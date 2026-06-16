# -*- coding: utf-8 -*-
"""Teste de endpoint: em 2 fotos da bia, lista quem curtiu e quem comentou (nome + comentario)."""
import json
import urllib.request

BASE = "http://127.0.0.1:8500"
USERNAME = "silvva_bia"
QTD_FOTOS = 2


def get(caminho):
    with urllib.request.urlopen(BASE + caminho, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


posts = get(f"/posts?username={USERNAME}&amount={QTD_FOTOS}").get("posts", [])
print(f"Posts retornados: {len(posts)}\n")

for indice, post in enumerate(posts[:QTD_FOTOS], start=1):
    media_id = post["id"]
    legenda = (post.get("caption") or "")[:60]
    print(f"===== FOTO {indice} (id={media_id}) =====")
    print(f"  Legenda: {legenda}")
    print(f"  Likes={post.get('likes')}  Comments={post.get('comments')}")

    likers = get(f"/likers?media_id={media_id}")
    print(f"\n  -- CURTIDAS ({likers.get('count', 0)}) --")
    for l in likers.get("likers", []):
        print(f"     @{l['username']}  ({l.get('full_name', '')})")

    comments = get(f"/comments?media_id={media_id}")
    print(f"\n  -- COMENTARIOS ({comments.get('count', 0)}) --")
    for c in comments.get("comments", []):
        print(f"     @{c['username']}: {c['text']}")
    print()
