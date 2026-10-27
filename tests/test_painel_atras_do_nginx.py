"""
test_painel_atras_do_nginx.py — O painel servido pelo nginx em HTTPS (Fase 2).

Com o nginx à frente, todos os pedidos chegam ao painel de 127.0.0.1. O
bloqueio de tentativas de entrada falhadas conta por endereço, e uma pessoa a
errar a senha trancava a Câmara inteira. O endereço verdadeiro vem no
X-Real-IP que o nginx põe, e o painel só acredita nele quando lhe dizem que
está atrás do nginx e o pedido vem da própria máquina.

O cookie de sessão passa a levar Secure, para nunca atravessar a rede em claro.
"""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest
from test_painel_seguranca import SENHA, Cliente

import painel as painel_mod
import registo as reg_mod
import utilizadores as utl


def _arrancar(tmp_path, atras_de_proxy):
    contas = utl.Utilizadores(str(tmp_path / "utilizadores.json"))
    contas.criar("ana.abreu", SENHA, nome_completo="Ana Abreu", papel=utl.ADMINISTRADOR)
    reg = reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))
    cfg = {"saida": str(tmp_path), "previas": str(tmp_path), "arquivo": str(tmp_path),
           "municipio": "Município de Teste", "intervalo_watch": 30,
           "painel_atras_de_proxy": atras_de_proxy}
    srv = painel_mod.PainelServer(reg, cfg, republicar_callback=lambda: None,
                                  painel_html_path=None, contas=contas,
                                  saude_callback=lambda: {"ok": True})
    porta = srv.iniciar(host="127.0.0.1", porta=0, bloquear=False)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/saude", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            pass
    return srv, Cliente(base)


@pytest.fixture
def atras(tmp_path):
    """O painel como fica na VM da Fase 2: atrás do nginx."""
    srv, cliente = _arrancar(tmp_path, True)
    yield cliente
    srv.parar()


@pytest.fixture
def direto(tmp_path):
    """O painel sem nginx, como sempre foi: a opção desligada."""
    srv, cliente = _arrancar(tmp_path, False)
    yield cliente
    srv.parar()


def _falhar_de(cliente, endereco):
    for _ in range(painel_mod.TENTATIVAS_ANTES_DE_BLOQUEAR + 1):
        cliente.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": "errada-mas-longa"},
                     cabecalhos={"X-Real-IP": endereco})


def test_atras_do_nginx_quem_erra_a_senha_nao_tranca_os_outros(atras):
    """Uma pessoa a errar a senha fica de castigo; uma colega noutro posto entra.

    Contra o código anterior falha: os dois chegavam como 127.0.0.1, e a
    colega levava o castigo de quem errou.
    """
    _falhar_de(atras, "10.0.0.21")
    codigo, _, _ = atras.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": SENHA},
                              cabecalhos={"X-Real-IP": "10.0.0.21"})
    assert codigo == 429, "quem errou não ficou de castigo"
    codigo, _, _ = atras.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": SENHA},
                              cabecalhos={"X-Real-IP": "10.0.0.22"})
    assert codigo == 200, "a colega noutro posto ficou trancada pelo erro de outra pessoa"


def test_sem_nginx_o_cabecalho_nao_serve_para_fugir_ao_castigo(direto):
    """Com a opção desligada, quem escreve o X-Real-IP não escolhe o endereço.

    De outra forma bastava mudar o cabeçalho a cada tentativa para nunca ficar
    de castigo. Passa dos dois lados de propósito: fixa o que não pode mudar.
    """
    for i in range(painel_mod.TENTATIVAS_ANTES_DE_BLOQUEAR + 1):
        direto.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": "errada-mas-longa"},
                    cabecalhos={"X-Real-IP": f"10.9.9.{i}"})
    codigo, _, _ = direto.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": SENHA},
                               cabecalhos={"X-Real-IP": "10.9.9.250"})
    assert codigo == 429


def test_atras_do_nginx_o_cookie_nunca_viaja_em_claro(atras):
    """A entrada e a saída mandam o cookie com Secure. Falha contra o anterior."""
    _, _, cab = atras.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": SENHA},
                           cabecalhos={"X-Real-IP": "10.0.0.21"})
    assert "Secure" in cab["Set-Cookie"].split("; ")
    # O /sair responde com um reencaminhamento, que o urllib seguiria e com
    # ele o cabeçalho se perdia: lê-se a resposta tal como vem.
    import http.client
    ligacao = http.client.HTTPConnection(atras.base.split("//")[1])
    ligacao.request("GET", "/sair")
    resposta = ligacao.getresponse()
    assert resposta.status == 303
    assert "Secure" in resposta.getheader("Set-Cookie").split("; ")
    ligacao.close()


def test_sem_nginx_o_cookie_fica_sem_secure(direto):
    """Por HTTP simples, um cookie com Secure nunca era guardado e ninguém
    entrava. Passa dos dois lados de propósito."""
    _, _, cab = direto.pede("/api/entrar", {"utilizador": "ana.abreu", "senha": SENHA})
    assert "Secure" not in cab["Set-Cookie"].split("; ")


@pytest.mark.parametrize("valor", ["false", "true", 1, "sim"])
def test_so_o_true_do_json_liga_a_opcao(tmp_path, valor):
    """Um «"false"» entre aspas é um texto não vazio, e ligava a opção que
    dizia desligar. Só o true do JSON conta; o resto fica desligado, e o diário
    avisa de que a chave não vale o que parece."""
    import agente
    import diario

    srv = painel_mod.PainelServer(
        reg_mod.RegistoEntrada(str(tmp_path / "registo.json")),
        {"painel_atras_de_proxy": valor})
    assert srv._atras_de_proxy() is False
    assert srv._seguro() == ""

    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    try:
        agente._avisar_proxy_mal_escrito({"painel_atras_de_proxy": valor})
        assert "painel_atras_de_proxy" in ficheiro.read_text(encoding="utf-8")
    finally:
        diario.repor()


def test_true_e_false_nao_fazem_barulho(tmp_path):
    """Fixa que os dois valores certos não enchem o diário de avisos a cada
    arranque. Não prova uma correção; contra o código anterior só falha porque
    a função não existia."""
    import agente
    import diario

    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    try:
        agente._avisar_proxy_mal_escrito({"painel_atras_de_proxy": True})
        agente._avisar_proxy_mal_escrito({"painel_atras_de_proxy": False})
        assert "painel_atras_de_proxy" not in ficheiro.read_text(encoding="utf-8")
    finally:
        diario.repor()


def test_duas_publicacoes_ao_mesmo_tempo_correm_uma_de_cada_vez(monkeypatch):
    """Com várias pessoas no painel, duas publicações podem cruzar-se.

    Cada uma lê o registo ao começar e escreve a página da TV ao acabar: a mais
    lenta, que leu primeiro, escrevia por último, e apagava da televisão o
    edital que a outra acabara de publicar. Em fila, a última a correr lê o
    registo mais recente. Apanhado pelo Sourcery no #31.
    """
    import threading
    import time

    import agente

    dentro = []
    maximo = []

    def publicar_devagar(cfg, reg, logo_im):
        dentro.append(1)
        maximo.append(len(dentro))
        time.sleep(0.2)
        dentro.pop()
        return 0

    monkeypatch.setattr(agente, "_publicar_registos", publicar_devagar)
    fios = [threading.Thread(target=agente.publicar_registos, args=({}, None, None))
            for _ in range(3)]
    for f in fios:
        f.start()
    for f in fios:
        f.join(5)
    assert len(maximo) == 3
    assert max(maximo) == 1, "duas publicações correram ao mesmo tempo"
