from unittest.mock import patch, MagicMock
import json
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server


def _make_handler(path="/followers?username=teste&amount=10"):
    handler = server.InstagramHandler.__new__(server.InstagramHandler)
    handler.command = "GET"
    handler.path = path
    handler.headers = {"Host": "localhost"}
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.send_response = lambda code: setattr(handler, "_status", code)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    handler.close_connection = False
    handler._status = None
    return handler


class TestFollowersVaziaSemFonte:
    def setup_method(self):
        self._rapidapi_orig = server._RAPIDAPI_KEYS[:]
        self._login_orig = server.LOGIN_OK

    def teardown_method(self):
        server._RAPIDAPI_KEYS = self._rapidapi_orig[:]
        server.LOGIN_OK = self._login_orig

    def test_followers_vazia_quando_sem_chave_e_sem_sessao(self):
        server._RAPIDAPI_KEYS = []
        server.LOGIN_OK = False

        with patch("server._fetch_lista_rapidapi", return_value=[]):
            handler = _make_handler("/followers?username=teste&amount=100")
            handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert data["followers"] == []
        assert data["count"] == 0
        assert data["status"] == "VAZIA"
        assert data["source"] == "none"
        assert data["expectedCount"] == 100

    def test_following_vazia_quando_sem_chave_e_sem_sessao(self):
        server._RAPIDAPI_KEYS = []
        server.LOGIN_OK = False

        with patch("server._fetch_lista_rapidapi", return_value=[]):
            handler = _make_handler("/following?username=teste&amount=100")
            handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert data["following"] == []
        assert data["count"] == 0
        assert data["status"] == "VAZIA"
        assert data["source"] == "none"
        assert data["expectedCount"] == 100

    def test_followers_completa_quando_dados_suficientes(self):
        server._RAPIDAPI_KEYS = ["chave_teste"]
        server.LOGIN_OK = False
        dados_mock = [{"username": f"user_{i}", "full_name": f"User {i}"} for i in range(50)]

        with patch("server._fetch_lista_rapidapi", return_value=dados_mock):
            handler = _make_handler("/followers?username=teste&amount=50")
            handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert len(data["followers"]) == 50
        assert data["status"] == "COMPLETA"
        assert data["source"] == "rapidapi"

    def test_followers_truncada_quando_dados_insuficientes(self):
        server._RAPIDAPI_KEYS = ["chave_teste"]
        server.LOGIN_OK = False
        dados_mock = [{"username": f"user_{i}", "full_name": f"User {i}"} for i in range(30)]

        with patch("server._fetch_lista_rapidapi", return_value=dados_mock):
            handler = _make_handler("/followers?username=teste&amount=100")
            handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert len(data["followers"]) == 30
        assert data["status"] == "TRUNCADA"
        assert data["source"] == "rapidapi"
        assert data["reason"] == "ok"
        assert data["expectedCount"] == 100

    def test_source_status_reflete_estado_atual(self):
        server._RAPIDAPI_KEYS = ["chave_abc", "chave_def"]
        server.LOGIN_OK = False
        server._sessoes = []
        server._sessao_idx = 0

        handler = _make_handler("/source_status")
        handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert data["rapidapi"]["configured"] is True
        assert data["rapidapi"]["total_chaves"] == 2
        assert data["session"]["login_ok"] is False
        assert data["session"]["total_sessions"] == 0

    def test_source_status_com_sessao_ativa(self):
        server._RAPIDAPI_KEYS = []
        server._sessoes = [{"label": "conta_principal", "cookies": {}, "has_error": False}]
        server._sessao_idx = 0
        server.LOGIN_OK = True
        mock_cl = MagicMock()
        mock_cl.username = "test_user"
        server.cl = mock_cl

        handler = _make_handler("/source_status")
        handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert data["rapidapi"]["configured"] is False
        assert data["session"]["login_ok"] is True
        assert data["session"]["total_sessions"] == 1
        assert data["session"]["active_session"] == "conta_principal"
        assert data["session"]["sessions"][0]["has_error"] is False

    def test_followers_username_required(self):
        handler = _make_handler("/followers")
        handler.do_GET()

        data = json.loads(handler.wfile.getvalue())
        assert "error" in data
