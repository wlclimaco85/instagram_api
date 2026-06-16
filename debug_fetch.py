"""
Script de diagnóstico — testa cada método de fetch do Instagram.
Uso: python debug_fetch.py silvva_bia
"""
import sys
import time
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "silvva_bia"

PROXIES = None  # adicione proxy aqui se necessário

def teste_api_privada():
    print("\n=== [1] API privada (web_profile_info) ===")
    try:
        r = requests.get(
            f"https://i.instagram.com/api/v1/users/web_profile_info/?username={USERNAME}",
            headers={
                "User-Agent": "Instagram 301.0.0.27.109 Android (30/11; 420dpi; 1080x2400; samsung; SM-A525F; a52; exynos1280; en_US; 516783258)",
                "X-IG-App-ID": "936619743392459",
            },
            proxies=PROXIES,
            timeout=15,
            verify=False,
        )
        print(f"HTTP {r.status_code}")
        print(r.text[:300])
    except Exception as e:
        print(f"ERRO: {e}")

def teste_graphql():
    print("\n=== [2] GraphQL legado (?__a=1) ===")
    try:
        r = requests.get(
            f"https://www.instagram.com/{USERNAME}/?__a=1&__d=dis",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
            proxies=PROXIES,
            timeout=15,
            verify=False,
        )
        print(f"HTTP {r.status_code}")
        print(r.text[:300])
    except Exception as e:
        print(f"ERRO: {e}")

def teste_html():
    print("\n=== [3] HTML scraping (og: meta tags) ===")
    try:
        r = requests.get(
            f"https://www.instagram.com/{USERNAME}/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            proxies=PROXIES,
            timeout=20,
            verify=False,
        )
        print(f"HTTP {r.status_code}")
        # Exibe só as linhas com og:
        og_lines = [l.strip() for l in r.text.split("\n") if "og:" in l or "meta" in l.lower()]
        if og_lines:
            print("og: tags encontradas:")
            for l in og_lines[:10]:
                print(" ", l[:200])
        else:
            print("Nenhuma og: tag encontrada no HTML")
            print("Primeiros 500 chars do HTML:")
            print(r.text[:500])
    except Exception as e:
        print(f"ERRO: {e}")

def teste_oembed():
    print("\n=== [4] oEmbed público (sem auth) ===")
    try:
        r = requests.get(
            f"https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/{USERNAME}/",
            headers={"User-Agent": "Mozilla/5.0"},
            proxies=PROXIES,
            timeout=15,
            verify=False,
        )
        print(f"HTTP {r.status_code}")
        print(r.text[:300])
    except Exception as e:
        print(f"ERRO: {e}")

if __name__ == "__main__":
    print(f"Testando @{USERNAME}...")
    teste_api_privada()
    time.sleep(1)
    teste_graphql()
    time.sleep(1)
    teste_html()
    time.sleep(1)
    teste_oembed()
    print("\n=== FIM ===")
