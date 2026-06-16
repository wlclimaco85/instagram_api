"""
Extrai sessao do Instagram do Chrome e salva como session.json.
Usa o perfil existente do Chrome (sem precisar fazer login de novo).
Uso: python exportar_sessao_browser.py
"""
import json
import os
import shutil
import sys
import time
import tempfile

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    print("ERRO: selenium nao instalado. Execute: pip install selenium")
    sys.exit(1)

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "session.json")

# Caminho do perfil do Chrome no Windows
CHROME_PROFILE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Google", "Chrome", "User Data"
)

def exportar_via_perfil_existente():
    """Abre Chrome com perfil existente (ja logado no Instagram)."""
    print(f"Usando perfil Chrome: {CHROME_PROFILE}")

    if not os.path.exists(CHROME_PROFILE):
        print("Perfil do Chrome nao encontrado. Tentando modo padrao...")
        return False

    # Copia o perfil para temp (Chrome nao abre se ja estiver em uso)
    temp_dir = tempfile.mkdtemp(prefix="chrome_ig_")
    default_src = os.path.join(CHROME_PROFILE, "Default")
    default_dst = os.path.join(temp_dir, "Default")

    print("Copiando perfil para pasta temporaria...")
    try:
        shutil.copytree(default_src, default_dst, ignore=shutil.ignore_patterns(
            "Cache", "Code Cache", "GPUCache", "ShaderCache", "*.log"
        ))
    except Exception as e:
        print(f"Aviso na copia: {e}")

    opts = Options()
    opts.add_argument(f"--user-data-dir={temp_dir}")
    opts.add_argument("--profile-directory=Default")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"ERRO ao abrir Chrome: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False

    print("Abrindo Instagram...")
    driver.get("https://www.instagram.com/")
    time.sleep(4)

    cookies = driver.get_cookies()
    cookie_map = {c["name"]: c["value"] for c in cookies}

    if not cookie_map.get("sessionid"):
        print("Nao logado no perfil copiado. Aguardando login (3 min)...")
        try:
            WebDriverWait(driver, timeout=180, poll_frequency=2).until(
                lambda d: any(c["name"] == "sessionid" for c in d.get_cookies())
            )
            cookies = driver.get_cookies()
            cookie_map = {c["name"]: c["value"] for c in cookies}
        except Exception:
            driver.quit()
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    driver.quit()
    shutil.rmtree(temp_dir, ignore_errors=True)

    return cookie_map

def salvar_session_json(cookie_map):
    sessionid  = cookie_map.get("sessionid", "")
    csrftoken  = cookie_map.get("csrftoken", "")
    mid        = cookie_map.get("mid", "")
    ds_user_id = cookie_map.get("ds_user_id", "")
    ig_did     = cookie_map.get("ig_did", "")

    if not sessionid:
        print("ERRO: sessionid nao encontrado nos cookies.")
        return False

    session_data = {
        "uuids": {
            "phone_id":         ig_did or "00000000-0000-0000-0000-000000000000",
            "uuid":             ig_did or "00000000-0000-0000-0000-000000000000",
            "client_session_id":"00000000-0000-0000-0000-000000000000",
            "advertising_id":   "00000000-0000-0000-0000-000000000000",
            "android_id":       "android-0000000000000000",
            "ig_did":           ig_did or "",
        },
        "cookies": {
            "sessionid":  sessionid,
            "csrftoken":  csrftoken,
            "mid":        mid,
            "ds_user_id": ds_user_id,
            "ig_did":     ig_did,
        },
        "last_login": time.time(),
        "device_settings": {
            "app_version":    "301.0.0.27.109",
            "android_version": 30,
            "android_release": "11.0",
            "dpi":            "420dpi",
            "resolution":     "1080x2400",
            "manufacturer":   "samsung",
            "device":         "a52",
            "model":          "SM-A525F",
            "cpu":            "exynos1280",
            "version_code":   "516783258",
        },
        "user_agent": "Instagram 301.0.0.27.109 Android (30/11; 420dpi; 1080x2400; samsung; SM-A525F; a52; exynos1280; en_US; 516783258)",
        "country":        "BR",
        "country_code":   55,
        "locale":         "pt_BR",
        "timezone_offset": -10800,
        "authorization_data": {
            "ds_user_id": ds_user_id,
            "sessionid":  sessionid,
        },
    }

    with open(SESSION_FILE, "w") as f:
        json.dump(session_data, f, indent=2)

    print(f"\n=== SUCESSO ===")
    print(f"session.json salvo em: {SESSION_FILE}")
    print(f"ds_user_id : {ds_user_id}")
    print(f"sessionid  : {sessionid[:20]}...")
    print("\nReinicie o servidor: python server.py")
    return True

if __name__ == "__main__":
    cookie_map = exportar_via_perfil_existente()
    if cookie_map:
        salvar_session_json(cookie_map)
    else:
        print("FALHOU — nao foi possivel extrair cookies.")
        sys.exit(1)
