"""
test_diario.py — O registo técnico, que é o que resta quando ninguém estava a ver.

Havia 71 print(). Num serviço que corre sozinho num posto municipal durante
meses, um print() para stdout que ninguém guarda não é registo nenhum — e o
Decreto-Lei n.º 125/2025 (NIS2), em vigor desde 3 de abril de 2026, espera de
quem opera um serviço público a capacidade de reconstituir o que aconteceu.
"""
from __future__ import annotations

import logging

import diario
import pytest


@pytest.fixture(autouse=True)
def limpo():
    """Cada teste começa sem handlers herdados do anterior."""
    diario.repor()
    yield
    diario.repor()


def test_escreve_na_consola_e_no_ficheiro(tmp_path, capsys):
    """Dois destinos: quem está a ver agora, e quem vai ler daqui a três meses."""
    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    diario.obter("PAINEL").info("ana.abreu entrou")
    assert "[PAINEL] ana.abreu entrou" in capsys.readouterr().out
    assert "ana.abreu entrou" in ficheiro.read_text(encoding="utf-8")


def test_o_ficheiro_leva_data_e_nivel_e_a_consola_nao(tmp_path, capsys):
    """Formatos diferentes de propósito, porque os leitores são diferentes.

    Na consola a data ocuparia um terço da linha para dizer 'agora'; no
    ficheiro, sem ela, a linha não vale nada.
    """
    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    diario.obter("TV").warning("sem ligação ao expositor")
    consola = capsys.readouterr().out
    gravado = ficheiro.read_text(encoding="utf-8")
    assert consola.strip() == "[TV] sem ligação ao expositor"
    assert "WARNING" in gravado and gravado[:4].isdigit()


def test_o_ficheiro_guarda_mais_do_que_a_consola_mostra(tmp_path, capsys):
    """DEBUG fica gravado sem poluir o ecrã. É no dia do incidente que se paga."""
    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro), nivel="INFO", nivel_ficheiro="DEBUG")
    diario.obter("AGENTE").debug("detalhe de diagnóstico")
    assert "detalhe" not in capsys.readouterr().out
    assert "detalhe de diagnóstico" in ficheiro.read_text(encoding="utf-8")


def test_configurar_duas_vezes_nao_duplica(tmp_path, capsys):
    """O painel e a vigia arrancam em threads diferentes e ambos configuravam.

    Sem a guarda, cada linha aparecia a dobrar — e apareceu mesmo.
    """
    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    diario.configurar(str(ficheiro))
    diario.obter("AGENTE").info("uma linha só")
    assert capsys.readouterr().out.count("uma linha só") == 1
    assert ficheiro.read_text(encoding="utf-8").count("uma linha só") == 1


def test_funciona_sem_ficheiro(capsys):
    """Sem caminho, escreve só na consola — é o que os testes querem."""
    diario.configurar(None)
    diario.obter("AGENTE").info("sem ficheiro")
    assert "sem ficheiro" in capsys.readouterr().out


def test_escreve_antes_de_configurar():
    """Alguns módulos registam durante a importação; isso não pode rebentar."""
    diario.obter("ARMAZEM").warning("antes de configurar")   # não levanta


def test_o_nome_curto_aparece_e_a_hierarquia_mantem_se(tmp_path, capsys):
    """Lê-se [PAINEL] e não [editais.PAINEL], mas continuam todos sob um pai.

    O pai é o que permite configurar todos em bloco; o nome curto é o que
    poupa largura em cada linha.
    """
    diario.configurar(None)
    registador = diario.obter("PAINEL")
    assert registador.name == "editais.PAINEL"
    registador.info("linha")
    assert "[PAINEL] linha" in capsys.readouterr().out
    assert logging.getLogger("editais.PAINEL").parent.name == "editais"


def test_rotacao_configurada(tmp_path):
    """Dez ficheiros de 2 MB: história suficiente sem ninguém ter de limpar nada."""
    ficheiro = tmp_path / "agente.log"
    diario.configurar(str(ficheiro))
    rotativo = next(h for h in logging.getLogger("editais").handlers
                    if hasattr(h, "maxBytes"))
    assert rotativo.maxBytes == diario.TAMANHO_MAXIMO
    assert rotativo.backupCount == diario.FICHEIROS_GUARDADOS


def test_nao_contamina_o_registo_da_raiz(tmp_path, capsys):
    """As mensagens do agente não sobem para o logger raiz.

    Sem propagate=False, qualquer biblioteca que configure o root veria (e
    possivelmente reescreveria) as linhas do agente.
    """
    diario.configurar(None)
    assert logging.getLogger("editais").propagate is False
