"""
test_painel_seguranca.py — As portas que se fecharam, e que têm de ficar fechadas.

O CSRF do painel foi reproduzido antes de ser corrigido: com as credenciais Basic
em cache no browser, um POST nascido noutro sítio retirava um edital do ecrã.
Estes testes montam o servidor a sério e repetem o ataque; se alguém afrouxar
alguma das três barreiras, falham aqui e não no posto.
"""
from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request

import painel as painel_mod
import pytest
import registo as reg_mod
from conftest import META_BOA

SENHA = "senha-de-teste-com-cedilha-ç"
_porta = [8950]


@pytest.fixture
def servidor(tmp_path):
    """Painel a correr numa porta livre, com um edital publicado à espera."""
    reg = reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))
    r = reg.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                           num_paginas=1, meta=dict(META_BOA))
    reg.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana")
    reg.mover_estado(r["id"], reg_mod.PUBLICADO, utilizador="ana")

    _porta[0] += 1
    porta = _porta[0]
    cfg = {"painel_senha": SENHA, "saida": str(tmp_path), "previas": str(tmp_path),
           "arquivo": str(tmp_path)}
    srv = painel_mod.PainelServer(reg, cfg, republicar_callback=lambda: None,
                                  painel_html_path=None)
    srv.iniciar(host="127.0.0.1", porta=porta, bloquear=False)
    pronto = threading.Event()
    pronto.wait(0.4)
    yield {"reg": reg, "porta": porta, "rid": r["id"],
           "url": f"http://127.0.0.1:{porta}"}
    srv._httpd.shutdown()


def _auth(utilizador="ana.abreu", senha=SENHA):
    return "Basic " + base64.b64encode(f"{utilizador}:{senha}".encode()).decode()


def _post(url, cabecalhos, corpo='{"id":1,"estado":"retirado"}'):
    """Faz um POST cru e devolve (código, corpo), sem levantar exceção em 4xx."""
    req = urllib.request.Request(url + "/api/estado", data=corpo.encode(),
                                 method="POST", headers=cabecalhos)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# Tudo o que uma página de terceiros consegue montar com as credenciais em cache.
# Cada uma falhava antes da correção; o corpo é JSON válido em todas.
ATAQUES = [
    ("formulário text/plain",
     {"Content-Type": "text/plain", "Origin": "https://mau.example"}),
    ("formulário urlencoded",
     {"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://mau.example"}),
    ("formulário multipart",
     {"Content-Type": "multipart/form-data", "Origin": "https://mau.example"}),
    ("json sem o cabeçalho próprio",
     {"Content-Type": "application/json", "Origin": "https://mau.example"}),
    ("json e cabeçalho, mas origem de fora",
     {"Content-Type": "application/json", "X-Painel-Pedido": "1",
      "Origin": "https://mau.example"}),
]


@pytest.mark.parametrize("nome,cabs", ATAQUES, ids=[a[0] for a in ATAQUES])
def test_pedido_de_outro_sitio_e_recusado(servidor, nome, cabs):
    """Nenhuma variante de CSRF muda o estado de um edital."""
    codigo, _ = _post(servidor["url"], {**cabs, "Authorization": _auth()})
    assert codigo == 403
    assert servidor["reg"].por_id(servidor["rid"])["estado"] == reg_mod.PUBLICADO


def test_o_proprio_painel_continua_a_funcionar(servidor):
    """A correção não pode fechar a porta a quem tem de entrar por ela."""
    anfitriao = f"127.0.0.1:{servidor['porta']}"
    codigo, corpo = _post(servidor["url"], {
        "Content-Type": "application/json", "X-Painel-Pedido": "1",
        "Origin": f"http://{anfitriao}", "Host": anfitriao,
        "Authorization": _auth()},
        corpo=json.dumps({"id": servidor["rid"], "estado": reg_mod.RETIRADO}))
    assert codigo == 200 and json.loads(corpo)["ok"]
    assert servidor["reg"].por_id(servidor["rid"])["estado"] == reg_mod.RETIRADO


def test_sem_credenciais_pede_senha(servidor):
    """Sem Authorization, responde-se 401 com o pedido de credenciais."""
    req = urllib.request.Request(servidor["url"] + "/api/registos")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 401
    assert "Basic" in e.value.headers.get("WWW-Authenticate", "")


def test_senha_com_acentos_funciona(servidor):
    """Uma senha com cedilha entra.

    Guarda esta regressão: hmac.compare_digest levanta TypeError com strings que
    tenham caracteres fora de ASCII, o que trancaria fora toda a gente com uma
    senha em português. A comparação é feita sobre bytes.
    """
    req = urllib.request.Request(servidor["url"] + "/api/registos",
                                 headers={"Authorization": _auth()})
    with urllib.request.urlopen(req) as r:
        assert r.status == 200


def test_senha_errada_nao_entra(servidor):
    """O óbvio, dito à mesma: senha errada é 401."""
    req = urllib.request.Request(servidor["url"] + "/api/registos",
                                 headers={"Authorization": _auth(senha="outra")})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 401


def test_cabecalhos_de_seguranca_presentes(servidor):
    """Todas as respostas levam os cabeçalhos de segurança. Não havia nenhum."""
    req = urllib.request.Request(servidor["url"] + "/api/registos",
                                 headers={"Authorization": _auth()})
    with urllib.request.urlopen(req) as r:
        h = r.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "no-referrer"
    assert h.get("Cache-Control") == "no-store"
    assert "frame-ancestors 'none'" in h.get("Content-Security-Policy", "")


def test_tentativas_repetidas_bloqueiam_o_endereco(servidor):
    """Ao fim de N senhas erradas, o endereço fica de castigo — mesmo com a certa.

    Uma senha partilhada exposta na rede e sem limite de tentativas é uma senha
    que se descobre. Bloquear o endereço e não a conta é deliberado: com uma
    senha só, bloquear 'a conta' fecharia o painel a toda a gente.
    """
    for _ in range(painel_mod.TENTATIVAS_ANTES_DE_BLOQUEAR + 1):
        try:
            urllib.request.urlopen(urllib.request.Request(
                servidor["url"] + "/api/registos",
                headers={"Authorization": _auth(senha="errada")}))
        except urllib.error.HTTPError:
            pass
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(urllib.request.Request(
            servidor["url"] + "/api/registos", headers={"Authorization": _auth()}))
    assert e.value.code == 429


def test_painel_recusa_arrancar_sem_senha(tmp_path):
    """Sem senha configurada, o painel não sobe — não fica aberto por esquecimento."""
    reg = reg_mod.RegistoEntrada(str(tmp_path / "r.json"))
    srv = painel_mod.PainelServer(reg, {"painel_senha": ""}, painel_html_path=None)
    with pytest.raises(RuntimeError, match="senha"):
        srv.iniciar(host="127.0.0.1", porta=8999, bloquear=False)


@pytest.mark.parametrize("nome", [
    "../../../etc/passwd", "..\\..\\config.json", "....//....//etc/shadow",
    "%2e%2e%2fconfig.json", "/etc/passwd",
])
def test_travessia_de_diretorios_nao_sai_da_pasta(tmp_path, nome):
    """Nenhuma forma de '..' consegue apontar para fora da pasta autorizada."""
    caminho = painel_mod._dentro_de(str(tmp_path), nome)
    assert caminho is None or caminho.startswith(str(tmp_path.resolve()))


def test_pasta_vizinha_com_o_mesmo_prefixo_nao_passa(tmp_path):
    """'/dados/saida_antiga' não é '/dados/saida'.

    Era este o defeito do padrão anterior, que comparava prefixos de texto:
    uma pasta vizinha cujo nome começasse igual passava a barreira.
    """
    (tmp_path / "saida").mkdir()
    (tmp_path / "saida_antiga").mkdir()
    (tmp_path / "saida_antiga" / "segredo.png").write_bytes(b"x")
    assert painel_mod._dentro_de(str(tmp_path / "saida"),
                                 "../saida_antiga/segredo.png") is None
