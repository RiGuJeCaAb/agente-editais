"""
test_paragem.py — Parar o agente sem deixar um documento a meio (issue #29).

O agente morria onde estivesse a um `systemctl stop`. Receber um documento são
vários passos, e uma paragem entre eles deixava o jornal de auditoria com um id
que o registo não tinha, ou o ficheiro preso na entrada para sempre. Estes
testes fixam a ordem nova: o que começou acaba, o que não começou não começa, e
o servidor só pára depois.

Nenhum envia sinais ao processo do pytest. O tratador é chamado à mão, que é o
que o Python faz quando o sinal chega.
"""
from __future__ import annotations

import os
import signal
import threading

import pytest

import agente
import paragem as par
import registo as reg_mod


def _pdf(caminho, texto):
    import fitz
    d = fitz.open()
    d.new_page(width=595, height=842).insert_text((70, 140), texto, fontsize=24)
    d.save(caminho)
    d.close()


@pytest.fixture
def posto(tmp_path):
    """Uma instalação com dois PDFs diferentes à espera na entrada."""
    cfg = {}
    for nome in ("entrada", "saida", "previas", "originais", "trabalho", "fundos"):
        (tmp_path / nome).mkdir()
        cfg[nome] = str(tmp_path / nome)
    cfg["tratados"] = str(tmp_path / "entrada" / "tratados")
    os.makedirs(cfg["tratados"])
    cfg["registo_entrada"] = str(tmp_path / "registo_entrada.json")
    _pdf(os.path.join(cfg["entrada"], "a.pdf"), "EDITAL 2026-0001")
    _pdf(os.path.join(cfg["entrada"], "b.pdf"), "EDITAL 2026-0002")
    return {"cfg": cfg, "reg": reg_mod.RegistoEntrada(cfg["registo_entrada"])}


# --- o porteiro --------------------------------------------------------------

def test_pedida_a_paragem_nao_entra_mais_trabalho():
    p = par.Paragem()
    assert p.entrar()
    p.sair()
    assert p.pedir_e_esperar(1)
    assert not p.entrar()


def test_a_paragem_espera_pela_peca_em_curso():
    """Quem pede a paragem só volta quando a peça que está dentro sair."""
    p = par.Paragem()
    assert p.entrar()
    resultado = []
    t = threading.Thread(target=lambda: resultado.append(p.pedir_e_esperar(5)))
    t.start()
    t.join(0.3)
    assert t.is_alive(), "voltou com a peça ainda a meio"
    p.sair()
    t.join(2)
    assert resultado == [True]


def test_passado_o_limite_a_paragem_diz_que_ficou_trabalho_a_meio():
    p = par.Paragem()
    assert p.entrar()
    assert p.pedir_e_esperar(0.1) is False


# --- a vigia -----------------------------------------------------------------

def test_com_a_paragem_pedida_a_vigia_nao_comeca_nenhum_documento(posto):
    p = par.Paragem()
    p.pedir_e_esperar(1)
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None, paragem=p) == 0
    assert posto["reg"].todos() == []
    assert sorted(f for f in os.listdir(posto["cfg"]["entrada"]) if f.endswith(".pdf")) \
        == ["a.pdf", "b.pdf"]


def test_o_documento_a_meio_acaba_e_o_seguinte_fica_para_depois(posto, monkeypatch):
    """O caso da issue: a paragem chega com um documento a ser lido.

    Esse acaba inteiro — rascunho criado e ficheiro fora da entrada — e só
    depois a paragem volta. O documento seguinte não começa. Contra o código
    anterior falha logo, porque a vigia não aceitava a paragem.
    """
    a_ler = threading.Event()
    pode_continuar = threading.Event()
    ler = agente.doc.ler_metadados

    def ler_devagar(*args, **kwargs):
        a_ler.set()
        assert pode_continuar.wait(5)
        return ler(*args, **kwargs)

    monkeypatch.setattr(agente.doc, "ler_metadados", ler_devagar)
    p = par.Paragem()
    vigia = threading.Thread(
        target=agente.varrer_para_registo,
        args=(posto["cfg"], posto["reg"], None), kwargs={"paragem": p})
    vigia.start()
    assert a_ler.wait(5)

    resultado = []
    quem_para = threading.Thread(target=lambda: resultado.append(p.pedir_e_esperar(5)))
    quem_para.start()
    quem_para.join(0.3)
    assert quem_para.is_alive(), "a paragem não esperou pelo documento a meio"

    pode_continuar.set()
    quem_para.join(5)
    vigia.join(5)
    assert resultado == [True]
    rascunhos = posto["reg"].todos()
    assert [r["ficheiro_origem"] for r in rascunhos] == ["a.pdf"]
    entrada = os.listdir(posto["cfg"]["entrada"])
    assert "a.pdf" not in entrada, "o documento acabado ficou na entrada"
    assert "b.pdf" in entrada, "o documento seguinte começou depois do pedido"


# --- o registo ---------------------------------------------------------------

def test_o_registo_fechado_nao_deixa_gravar_metade(posto):
    """Depois de fechado, uma escrita de outra thread fica à espera e não grava.

    É o que segura uma ação do painel que chegue durante a paragem: o jornal e
    o registo gravam-se em dois passos, e o processo sai a seguir.
    """
    reg = posto["reg"]
    caminho = posto["cfg"]["registo_entrada"]
    antes = open(caminho, encoding="utf-8").read() if os.path.exists(caminho) else None
    reg.fechar()
    escritor = threading.Thread(
        target=reg.criar_rascunho, daemon=True,
        kwargs={"ficheiro_origem": "x.pdf", "hash_ficheiro": "abc",
                "num_paginas": 1, "meta": {}})
    escritor.start()
    escritor.join(0.3)
    assert escritor.is_alive(), "a escrita passou com o registo fechado"
    depois = open(caminho, encoding="utf-8").read() if os.path.exists(caminho) else None
    assert depois == antes
    assert not reg.jornal.ler_tudo()


# --- o sinal -----------------------------------------------------------------

class _Testemunha:
    """Faz de registo e de servidor, e aponta a ordem por que lhe mexem."""

    def __init__(self):
        self.ordem = []
        self.parado = threading.Event()

    def fechar(self, limite=None):
        self.ordem.append("registo fechado")
        return True

    def parar(self):
        self.ordem.append("servidor parado")
        self.parado.set()


def test_o_sinal_acaba_o_trabalho_fecha_o_registo_e_so_depois_para_o_servidor(monkeypatch):
    instalados = {}
    monkeypatch.setattr(signal, "signal", lambda num, f: instalados.__setitem__(num, f))
    p = par.Paragem()
    testemunha = _Testemunha()
    assert p.entrar()

    tratador = agente._instalar_paragem(p, testemunha, testemunha, 5)
    assert instalados == {signal.SIGTERM: tratador, signal.SIGINT: tratador}

    tratador(signal.SIGTERM, None)
    assert not testemunha.parado.wait(0.3), "parou o servidor com trabalho a meio"
    assert testemunha.ordem == []

    testemunha.ordem.append("trabalho acabado")
    p.sair()
    assert testemunha.parado.wait(5)
    assert testemunha.ordem == ["trabalho acabado", "registo fechado", "servidor parado"]


def test_um_segundo_sinal_durante_a_paragem_nao_a_repete(monkeypatch):
    monkeypatch.setattr(signal, "signal", lambda num, f: None)
    testemunha = _Testemunha()
    tratador = agente._instalar_paragem(par.Paragem(), testemunha, testemunha, 5)
    tratador(signal.SIGTERM, None)
    assert testemunha.parado.wait(5)
    tratador(signal.SIGINT, None)
    testemunha.parado.clear()
    assert not testemunha.parado.wait(0.3)
    assert testemunha.ordem == ["registo fechado", "servidor parado"]


def test_fora_da_thread_principal_nao_instala_nada(monkeypatch):
    """O Python só deixa instalar tratadores na thread principal; fora dela, o
    painel arranca na mesma, sem a paragem com ordem, em vez de rebentar."""
    monkeypatch.setattr(signal, "signal", lambda num, f: pytest.fail("instalou"))
    resultado = []
    t = threading.Thread(target=lambda: resultado.append(
        agente._instalar_paragem(par.Paragem(), None, None, 1)))
    t.start()
    t.join(2)
    assert resultado == [None]


def test_o_painel_repoe_os_sinais_quando_volta(monkeypatch):
    """Quem chama o painel no mesmo processo recebe os sinais como estavam.

    Os testes do arranque correm o painel com um servidor falso que volta logo,
    e deixavam os tratadores do agente no processo do pytest: um kill ao pytest
    passava a ser ignorado. Foi assim que se deu por isto.
    """
    antes = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    with agente._sinais_de_paragem(par.Paragem(), _Testemunha(), _Testemunha(), 1):
        assert signal.getsignal(signal.SIGTERM) is not antes[signal.SIGTERM]
    assert {s: signal.getsignal(s) for s in antes} == antes


def test_uma_paragem_pedida_antes_de_o_servidor_existir_nao_se_perde(tmp_path):
    """O sinal pode chegar entre a instalação dos tratadores e o servidor abrir.

    O parar() não tinha servidor para parar, e o iniciar() abria-o a seguir e
    ficava a servir até o systemd o matar, cinco minutos depois.
    """
    import painel as painel_mod
    import utilizadores as utl

    contas = utl.Utilizadores(str(tmp_path / "utilizadores.json"))
    contas.criar("ana", "senha-com-tamanho")
    servidor = painel_mod.PainelServer(
        reg_mod.RegistoEntrada(str(tmp_path / "registo.json")), {}, contas=contas)
    servidor.parar()
    voltou = []
    t = threading.Thread(target=lambda: voltou.append(
        servidor.iniciar(host="127.0.0.1", porta=0, bloquear=True)), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "o servidor abriu e ficou a servir depois da paragem"
    assert voltou


def test_o_servidor_para_mesmo_que_fechar_o_registo_rebente():
    """Se o fechar() levantasse, o servidor ficava a servir até o systemd matar
    o processo, cinco minutos depois, e os sinais seguintes eram ignorados."""

    class RegistoQueRebenta:
        def fechar(self, limite=None):
            raise OSError("disco")

    testemunha = _Testemunha()
    with pytest.raises(OSError):
        agente._parar_com_ordem(par.Paragem(), RegistoQueRebenta(), testemunha, 1)
    assert testemunha.ordem == ["servidor parado"]


def test_o_registo_encravado_nao_impede_o_servidor_de_parar(posto, monkeypatch):
    """Uma escrita presa num disco que não responde segurava o lock para sempre,
    e o servidor nunca chegava a parar. Com limite, a paragem segue."""
    reg = posto["reg"]
    preso = threading.Event()
    solta = threading.Event()

    def escrita_encravada():
        with reg._lock:
            preso.set()
            solta.wait(5)

    threading.Thread(target=escrita_encravada, daemon=True).start()
    assert preso.wait(5)
    assert reg.fechar(0.1) is False
    testemunha = _Testemunha()
    monkeypatch.setattr(agente, "ESPERA_PELO_REGISTO", 0.1)
    try:
        agente._parar_com_ordem(par.Paragem(), reg, testemunha, 1)
    finally:
        solta.set()
    assert testemunha.ordem == ["servidor parado"]


# --- o painel ----------------------------------------------------------------

class _Pedido:
    """Faz de pedido HTTP: guarda a resposta que o painel daria."""

    def _json(self, obj, code=200):
        self.resposta = (code, obj)
        return self.resposta


def _validado(reg):
    r = reg.criar_rascunho(ficheiro_origem="a.pdf", hash_ficheiro="h1", num_paginas=1,
                           meta={"assunto": "Obras", "data_publicacao": "2026-10-26"})
    assert reg.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana")["ok"]
    return r["id"]


def test_com_o_agente_a_parar_o_painel_recusa_publicar_e_nao_grava_nada(posto):
    """O defeito que a revisão marcou a vermelho: a mudança de estado contava, a
    publicação era recusada, e o edital ficava publicado no registo — com
    certidão — e fora da televisão. Recusa-se a mudança inteira, e diz-se."""
    import painel as painel_mod

    reg = posto["reg"]
    rid = _validado(reg)
    p = par.Paragem()
    p.pedir_e_esperar(1)
    publicou = []
    servidor = painel_mod.PainelServer(reg, posto["cfg"], paragem=p,
                                       republicar_callback=lambda: publicou.append(1))
    codigo, corpo = servidor._mudar_estado(
        _Pedido(), {"id": rid, "estado": reg_mod.PUBLICADO}, {"nome": "ana"})
    assert codigo == 503 and not corpo["ok"]
    assert reg.por_id(rid)["estado"] == reg_mod.VALIDADO
    assert publicou == []


def test_a_publicacao_pedida_no_painel_acaba_mesmo_que_a_paragem_chegue_a_meio(posto):
    """Publicar no painel é mudar o estado e recompor a TV, e a paragem espera
    pelas duas: um pedido de paragem a meio não deixa a segunda por fazer."""
    import painel as painel_mod

    reg = posto["reg"]
    rid = _validado(reg)
    p = par.Paragem()
    a_publicar = threading.Event()
    pode_acabar = threading.Event()
    publicou = []

    def publicar_devagar():
        a_publicar.set()
        assert pode_acabar.wait(5)
        publicou.append(1)

    servidor = painel_mod.PainelServer(reg, posto["cfg"], paragem=p,
                                       republicar_callback=publicar_devagar)
    pedido = threading.Thread(target=servidor._mudar_estado, args=(
        _Pedido(), {"id": rid, "estado": reg_mod.PUBLICADO}, {"nome": "ana"}))
    pedido.start()
    assert a_publicar.wait(5)
    resultado = []
    quem_para = threading.Thread(target=lambda: resultado.append(p.pedir_e_esperar(5)))
    quem_para.start()
    quem_para.join(0.3)
    assert quem_para.is_alive(), "a paragem não esperou pela publicação"
    pode_acabar.set()
    quem_para.join(5)
    pedido.join(5)
    assert resultado == [True] and publicou == [1]
    assert reg.por_id(rid)["estado"] == reg_mod.PUBLICADO
