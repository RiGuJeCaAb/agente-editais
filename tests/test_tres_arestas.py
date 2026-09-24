"""
test_tres_arestas.py — Três coisas que se viam e ninguém corrigia.

Ficaram assinaladas ao longo da Onda 3, sempre fora do âmbito da peça que
estava em cima da mesa. Nenhuma impedia a aplicação de funcionar; as três
apareciam no pior momento — a instalar, ao fim de um ano, ou a correr a bateria
duas vezes ao mesmo tempo.

  1. `--criar-utilizador` sem terminal rebentava com um traceback em cru.
  2. A pasta de trabalho crescia sem fim.
  3. Os testes do painel disputavam uma porta fixa.
"""
from __future__ import annotations

import os
import time

import pytest

import documentos as doc


# ---------------------------------------------------------------------------
# 1. Criar a primeira conta sem um terminal
#
# É o primeiro comando que alguém corre numa instalação nova. Sem terminal,
# respondia com sete linhas de traceback a dizer «EOF when reading a line» —
# e quando o stdin trazia texto era pior: criava a conta com a senha à vista,
# depois de um aviso em inglês do getpass, numa aplicação toda em português.
# A razão de o getpass ali estar é precisamente a senha não ficar à vista.
# ---------------------------------------------------------------------------
@pytest.fixture
def posto(tmp_path):
    import agente
    cfg = dict(agente.CONFIG)
    cfg["utilizadores"] = str(tmp_path / "utilizadores.json")
    return cfg


class _Entrada:
    """Um stdin de mentira, que diz se é ou não um terminal."""

    def __init__(self, terminal):
        self._terminal = terminal

    def isatty(self):
        return self._terminal


def test_sem_terminal_recusa_e_nao_cria_nada(posto, monkeypatch):
    import agente
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=False))
    codigo = agente.comando_criar_utilizador(posto, "ana", administrador=True)
    assert codigo == 1
    assert not os.path.exists(posto["utilizadores"]), "não podia ter criado nada"


def test_sem_terminal_diz_o_que_fazer_e_em_portugues(posto, monkeypatch, caplog):
    """Um traceback não diz a ninguém o que fazer a seguir.

    A mensagem sai pelo registo técnico, e não por stdout — é por lá que saem
    todos os erros do agente, para ficarem também no diário de quem instalou.
    """
    import agente
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=False))
    with caplog.at_level("ERROR"):
        agente.comando_criar_utilizador(posto, "ana", administrador=True)
    texto = caplog.text
    assert "terminal" in texto
    assert "--criar-utilizador ana --administrador" in texto, "falta o comando a repetir"
    assert "Traceback" not in texto
    assert "EOF when reading a line" not in texto


def test_sem_terminal_nunca_chega_a_pedir_a_senha(posto, monkeypatch):
    """Recusa-se ANTES de perguntar. Perguntar e só depois desistir dava a
    senha ao ecrã na mesma, que é exatamente o que se quer evitar."""
    import getpass

    import agente
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=False))

    def nao_devia(*_a, **_k):
        raise AssertionError("pediu a senha sem terminal")

    monkeypatch.setattr(getpass, "getpass", nao_devia)
    monkeypatch.setattr("builtins.input", nao_devia)
    assert agente.comando_criar_utilizador(posto, "ana") == 1


@pytest.mark.parametrize("nome,stdin_partido", [
    # No Windows, um programa aberto com o pythonw — o que acontece a um duplo
    # clique num .py — corre com sys.stdin a None. Era o caso mais provável de
    # alguém a instalar isto num posto, e a verificação que existe para não
    # haver traceback nenhum produzia ela própria um AttributeError.
    ("None, como no pythonw do Windows", lambda: None),
    ("um stdin já fechado", lambda: _fechado()),
    ("um objeto sem isatty nenhum", lambda: object()),
])
def test_um_stdin_partido_nao_rebenta(posto, monkeypatch, nome, stdin_partido):
    """Descoberto na revisão à mão desta mesma correção. O Linux dá sempre um
    stdin, e por aqui nunca se via."""
    import agente
    monkeypatch.setattr("sys.stdin", stdin_partido())
    assert agente.comando_criar_utilizador(posto, "ana") == 1
    assert not os.path.exists(posto["utilizadores"])


def _fechado():
    import io as _io
    f = _io.StringIO()
    f.close()
    return f


def test_com_terminal_continua_a_criar_a_conta(posto, monkeypatch):
    """A correção não pode fechar a porta a quem tem de entrar por ela."""
    import getpass

    import agente
    import utilizadores as utl
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=True))
    monkeypatch.setattr("builtins.input", lambda _p="": "Ana Abreu")
    monkeypatch.setattr(getpass, "getpass", lambda _p="": "senha-mesmo-comprida")

    assert agente.comando_criar_utilizador(posto, "ana", administrador=True) == 0
    contas = utl.Utilizadores(posto["utilizadores"])
    assert contas.autenticar("ana", "senha-mesmo-comprida")
    assert contas.listar()[0]["nome_completo"] == "Ana Abreu"


def test_desistir_a_meio_nao_rebenta(posto, monkeypatch):
    """Ctrl-D a meio das perguntas é uma desistência, não uma avaria."""
    import agente
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=True))

    def desiste(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", desiste)
    assert agente.comando_criar_utilizador(posto, "ana") == 1
    assert not os.path.exists(posto["utilizadores"])


def test_senhas_diferentes_continuam_a_ser_recusadas(posto, monkeypatch):
    import getpass

    import agente
    monkeypatch.setattr("sys.stdin", _Entrada(terminal=True))
    monkeypatch.setattr("builtins.input", lambda _p="": "Ana")
    senhas = iter(["senha-comprida-um", "senha-comprida-dois"])
    monkeypatch.setattr(getpass, "getpass", lambda _p="": next(senhas))
    assert agente.comando_criar_utilizador(posto, "ana") == 1
    assert not os.path.exists(posto["utilizadores"])


# ---------------------------------------------------------------------------
# 2. A pasta de trabalho, que crescia sem fim
#
# Guarda o PDF de cada .docx convertido, para não se pagar um arranque do
# LibreOffice de cada vez que se volta ao mesmo documento. Medido: duzentos
# editais em Word deixavam lá duzentos ficheiros, e um documento editado cinco
# vezes deixava cinco cópias. Não é muito por ano — é que não tinha fim.
# ---------------------------------------------------------------------------
@pytest.fixture
def conversoes(tmp_path):
    """Uma pasta de trabalho com três conversões guardadas."""
    for i in range(3):
        (tmp_path / f"edital_{i}-abc123def456.pdf").write_bytes(b"%PDF-1.4 falso")
    return tmp_path


def test_nada_recente_e_apagado(conversoes):
    assert doc.limpar_conversoes(str(conversoes)) == 0
    assert len(os.listdir(conversoes)) == 3


def test_o_que_ninguem_usa_ha_muito_tempo_sai(conversoes):
    daqui_a_um_ano = time.time() + 365 * 86400
    assert doc.limpar_conversoes(str(conversoes), agora=daqui_a_um_ano) == 3
    assert os.listdir(conversoes) == []


def test_o_que_nao_e_nosso_fica_onde_esta(conversoes):
    """Uma pasta chamada «trabalho» convida a lá pôr coisas, e uma limpeza que
    apaga o que não conhece é uma armadilha à espera."""
    for nome in ("notas-do-funcionario.pdf", "edital.pdf", "rascunho.docx",
                 "edital-NAOEHEXADECIMAL.pdf", "edital-abc123.pdf"):
        (conversoes / nome).write_bytes(b"nao mexas")
    doc.limpar_conversoes(str(conversoes), agora=time.time() + 365 * 86400)
    sobreviveram = sorted(os.listdir(conversoes))
    assert sobreviveram == ["edital-NAOEHEXADECIMAL.pdf", "edital-abc123.pdf",
                            "edital.pdf", "notas-do-funcionario.pdf",
                            "rascunho.docx"]


def test_usar_uma_conversao_adia_a_sua_morte(tmp_path, monkeypatch):
    """Apaga-se por DESUSO, não por idade. Sem isto, um documento reconvertido
    todas as semanas era apagado na mesma ao fim de um mês, e a conversão
    seguinte pagava outro arranque do LibreOffice sem razão nenhuma."""
    import shutil as sh
    fonte = tmp_path / "fonte.pdf"
    fonte.write_bytes(b"%PDF-1.4 falso")
    monkeypatch.setattr(doc.shutil, "which", lambda _n: "/usr/bin/soffice")

    def converte(cmd, **_k):
        saida = cmd[cmd.index("--outdir") + 1]
        base = os.path.splitext(os.path.basename(cmd[-1]))[0]
        sh.copy(fonte, os.path.join(saida, base + ".pdf"))

    monkeypatch.setattr(doc.subprocess, "run", converte)

    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    word = tmp_path / "edital.docx"
    word.write_bytes(b"PK\x03\x04")
    guardada = doc._word_to_pdf(str(word), str(trabalho))

    # Envelhece o ficheiro para bem antes do limite.
    velho = time.time() - 400 * 86400
    os.utime(guardada, (velho, velho))
    # Usá-la outra vez marca-a como usada...
    doc._word_to_pdf(str(word), str(trabalho))
    # ...e por isso a limpeza já não lhe toca.
    assert doc.limpar_conversoes(str(trabalho)) == 0
    assert os.path.exists(guardada)


def test_uma_pasta_que_nao_existe_nao_rebenta(tmp_path):
    assert doc.limpar_conversoes(str(tmp_path / "nao-existe")) == 0
    assert doc.limpar_conversoes("") == 0


def test_o_ciclo_de_publicacao_arruma_a_pasta_de_trabalho(tmp_path, monkeypatch):
    """A limpeza só serve se alguém a chamar. Esta é a parte que se esquece."""
    import agente
    import registo as reg_mod
    cfg = dict(agente.CONFIG)
    for chave, valor in agente.CONFIG.items():
        if isinstance(valor, str) and valor.startswith(agente.BASE):
            cfg[chave] = str(tmp_path / os.path.relpath(valor, agente.BASE))
    for nome in ("entrada", "saida", "previas", "originais", "trabalho",
                 "fundos", "arquivo", "exportacao"):
        os.makedirs(cfg[nome], exist_ok=True)

    velha = os.path.join(cfg["trabalho"], "edital-0123456789ab.pdf")
    open(velha, "wb").write(b"%PDF-1.4 falso")
    ha_muito = time.time() - 400 * 86400
    os.utime(velha, (ha_muito, ha_muito))

    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    agente.publicar_registos(cfg, reg, None)
    assert not os.path.exists(velha), "o ciclo devia ter arrumado a pasta"
