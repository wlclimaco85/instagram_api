"""
Extrai sessao do Instagram do Chrome e salva como session.json para o instagrapi.
Uso: python exportar_sessao_browser.py

Instrucoes:
1. Rode este script
2. Uma janela do Chrome vai abrir no Instagram
3. Faca login normalmente (usuario/senha/2FA se necessario)
4. Quando estiver logado (ver o feed), pressione ENTER no terminal
5. O script salva session.json automaticamente
"""
import json
import os
import sys
import time

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except ImportError:
    print("ERRO: selenium nao instalado. Execute: pip install selenium")
    sys.exit(1)

SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")

def exportar_sessao():
    print("Abrindo Chrome no Instagram...")
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--window-size=1280,800")

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"ERRO ao abrir Chrome: {e}")
        print("Verifique se o ChromeDriver esta instalado e compativel com o Chrome.")
        sys.exit(1)

    driver.get("https://www.instagram.com/accounts/login/")
    print("\n>>> Faca login no Instagram na janela do Chrome que abriu.")
    print(">>> Quando estiver no feed (pagina principal), pressione ENTER aqui.")
    input("Pressione ENTER quando estiver logado: ")

    cookies = driver.get_cookies()
    driver.quit()

    # Extrai cookies relevantes
    cookie_map = {c["name"]: c["value"] for c in cookies}
    sessionid = cookie_map.get("sessionid", "")
    csrftoken = cookie_map.get("csrftoken", "")
    mid = cookie_map.get("mid", "")
    ds_user_id = cookie_map.get("ds_user_id", "")
    ig_did = cookie_map.get("ig_did", "")

    if not sessionid:
        print("ERRO: sessionid nao encontrado. Verifique se o login foi concluido.")
        sys.exit(1)

    # Monta session.json no formato do instagrapi
    session_data = {
        "uuids": {
            "phone_id": ig_did or "00000000-0000-0000-0000-000000000000",
            "uuid": ig_did or "00000000-0000-0000-0000-000000000000",
            "client_session_id": "00000000-0000-0000-0000-000000000000",
            "advertising_id": "00000000-0000-0000-0000-000000000000",
            "android_id": "android-0000000000000000",
            "ig_did": ig_did or "",
        },
        "cookies": {
            "sessionid": sessionid,
            "csrftoken": csrftoken,
            "mid": mid,
            "ds_user_id": ds_user_id,
            "ig_did": ig_did,
        },
        "last_login": time.time(),
        "device_settings": {
            "app_version": "301.0.0.27.109",
            "android_version": 30,
            "android_release": "11.0",
            "dpi": "420dpi",
            "resolution": "1080x2400",
            "manufacturer": "samsung",
            "device": "a52",
            "model": "SM-A525F",
            "cpu": "exynos1280",
            "version_code": "516783258",
        },
        "user_agent": "Instagram 301.0.0.27.109 Android (30/11; 420dpi; 1080x2400; samsung; SM-A525F; a52; exynos1280; en_US; 516783258)",
        "country": "BR",
        "country_code": 55,
        "locale": "pt_BR",
        "timezone_offset": -10800,
        "authorization_data": {
            "ds_user_id": ds_user_id,
            "sessionid": sessionid,
        },
    }

    with open(SESSION_FILE, "w") as f:
        json.dump(session_data, f, indent=2)

    print(f"\n=== SUCESSO ===")
    print(f"session.json salvo em: {SESSION_FILE}")
    print(f"ds_user_id: {ds_user_id}")
    print(f"sessionid: {sessionid[:20]}...")
    print("\nReinicie o servidor: python server.py")

if __name__ == "__main__":
    exportar_sessao()
