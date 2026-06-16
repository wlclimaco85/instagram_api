"""
Mini-servidor Instagram API para o App Match.
Uso: python server.py
Porta: 8500
"""
import json
import os
import sys
import sqlite3
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    from instagrapi import Client
except ImportError:
    print("Instale instagrapi: pip install instagrapi")
    sys.exit(1)

SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")
DB_FILE = os.path.join(os.path.dirname(__file__), "timeline.db")
cl = Client()

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

def login():
    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)
        try:
            cl.get_timeline_feed()
            print("Sessao existente validada")
            return True
        except:
            pass
    
    username = os.environ.get("IG_USERNAME", "")
    password = os.environ.get("IG_PASSWORD", "")
    if not username or not password:
        print("Defina IG_USERNAME e IG_PASSWORD no ambiente")
        print("Ou faca login manualmente: python server.py --login")
        return False
    
    cl.login(username, password)
    cl.dump_settings(SESSION_FILE)
    print(f"Login OK: {username}")
    return True

class InstagramHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == "/health":
            self.send_json({"status": "ok"})
        
        elif parsed.path == "/profile":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                data = {
                    "username": user.username,
                    "full_name": user.full_name,
                    "biography": user.biography,
                    "profile_pic_url": user.profile_pic_url,
                    "followers": user.follower_count,
                    "following": user.following_count,
                    "posts": user.media_count,
                    "is_private": user.is_private,
                    "is_verified": user.is_verified,
                    "external_url": user.external_url,
                    "hd_profile_pic": user.hd_profile_pic_url_info.url if user.hd_profile_pic_url_info else None,
                }
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        
        elif parsed.path == "/posts":
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["12"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                medias = cl.user_medias(user.pk, amount=amount)
                posts = []
                for m in medias:
                    posts.append({
                        "id": str(m.pk),
                        "display_url": m.thumbnail_url.url if m.thumbnail_url else None,
                        "caption": (m.caption_text or "")[:200],
                        "likes": m.like_count or 0,
                        "comments": m.comment_count or 0,
                        "timestamp": str(m.taken_at),
                        "is_video": m.media_type == 2,
                        "video_url": m.video_url.url if m.media_type == 2 and m.video_url else None,
                    })
                self.send_json({"posts": posts, "count": len(posts)})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        
        elif parsed.path == "/likers":
            media_id = params.get("media_id", [""])[0]
            if not media_id:
                self.send_json({"error": "media_id required"}, 400)
                return
            try:
                likers = cl.media_likers(int(media_id))
                data = [{"username": l.username, "full_name": l.full_name} for l in likers]
                self.send_json({"likers": data, "count": len(data)})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        
        elif parsed.path == "/followers":
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["50"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                followers = cl.user_followers(user.pk, amount=amount)
                data = [{"username": f.username, "full_name": f.full_name} for f in followers.values()]
                self.send_json({"followers": data, "count": len(data)})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        
        elif parsed.path == "/following":
            username = params.get("username", [""])[0]
            amount = int(params.get("amount", ["50"])[0])
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                following = cl.user_following(user.pk, amount=amount)
                data = [{"username": f.username, "full_name": f.full_name} for f in following.values()]
                self.send_json({"following": data, "count": len(data)})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        
        elif parsed.path == "/comments":
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
                self.send_json({"error": str(e)}, 500)

        elif parsed.path == "/track":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            track_profile(username)
            self.send_json({"status": "tracking", "username": username})

        elif parsed.path == "/snapshot":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                track_profile(username)

                followers = cl.user_followers(user.pk, amount=100)
                follower_list = [{"username": f.username, "full_name": f.full_name}
                                 for f in followers.values()]
                save_snapshot(username, "followers", follower_list)

                following = cl.user_following(user.pk, amount=100)
                following_list = [{"username": f.username, "full_name": f.full_name}
                                  for f in following.values()]
                save_snapshot(username, "following", following_list)

                medias = cl.user_medias(user.pk, amount=12)
                post_likes = {}
                for m in medias:
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
                self.send_json({"error": str(e)}, 500)

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
                self.send_json({"error": str(e)}, 500)

        elif parsed.path == "/comments_with_timeline":
            username = params.get("username", [""])[0]
            if not username:
                self.send_json({"error": "username required"}, 400)
                return
            try:
                user = cl.user_info_by_username(username)
                medias = cl.user_medias(user.pk, amount=12)
                all_comments = []
                for m in medias:
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
                self.send_json({"error": str(e)}, 500)

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
    if "--login" in sys.argv:
        username = input("Username: ")
        password = input("Password: ")
        cl.login(username, password)
        cl.dump_settings(SESSION_FILE)
        print("Login salvo!")
        return
    
    init_db()
    
    if not login():
        print("Falha no login. Iniciando modo somente-leitura (sem login)...")
    
    server = HTTPServer(("0.0.0.0", 8500), InstagramHandler)
    print("Instagram API rodando em http://localhost:8500")
    print("Endpoints: /profile, /posts, /likers, /followers, /following, /comments, /snapshot, /timeline, /track")
    server.serve_forever()

if __name__ == "__main__":
    main()
