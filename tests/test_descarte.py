"""
test_descarte.py — A máquina de estados passa a ter saída.

Até à 0.14 o mapa de transições não tinha nenhuma: o que entrava no registo
ficava lá para sempre. Descobriu-se em produção, e pela pior via — a migração do
modelo antigo criou rascunhos de editais sem data de publicação e sem ficheiro
de origem, que não se conseguem validar (falta a data) nem publicar (falta o
documento), e que ficavam eternamente na fila «Por validar» a tapar o trabalho
a sério. Não havia maneira de os tirar de lá.

Descartar não é apagar, e os testes que interessam são os que provam a diferença:
a linha fica, o motivo fica, o rasto de auditoria fica, e volta-se atrás.

A regra que mais importa está no fim: um edital PUBLICADO não se descarta. Sai
do ecrã por RETIRADO, que é o que carimba a desafixação e o que a certidão cita.
Descartá-lo fá-lo-ia desaparecer do expositor sem ficar registado quem o
desafixou — exatamente o buraco que a Onda 2 existiu para tapar.
"""
from __future__ import annotations

import pytest

import registo as reg_mod
from conftest import META_BOA


@pytest.fixture
def registo(tmp_path):
    """Um registo com um rascunho pronto a ser maltratado."""
    return reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))


@pytest.fixture
def rascunho(registo):
    r = registo.criar_rascunho(ficheiro_origem="edital.pdf", hash_ficheiro="a" * 40,
                               num_paginas=2, meta=dict(META_BOA))
    return r["id"]


def publicado(registo, rid):
    """Leva um rascunho até PUBLICADO pelo caminho legítimo."""
    registo.mover_estado(rid, reg_mod.VALIDADO, utilizador="ana")
    registo.mover_estado(rid, reg_mod.PUBLICADO, utilizador="ana")
    return rid


# ---------------------------------------------------------------------------
# O caso que motivou tudo
# ---------------------------------------------------------------------------
def test_um_rascunho_pode_sair_da_fila(registo, rascunho):
    """O zombie da migração tem de ter para onde ir."""
    res = registo.mover_estado(rascunho, reg_mod.DESCARTADO,
                               utilizador="ana", nota="Sem original e sem data")
    assert res["ok"], res["erro"]
    assert registo.por_id(rascunho)["estado"] == reg_mod.DESCARTADO


def test_o_descartado_sai_da_fila_de_trabalho(registo, rascunho):
    """Por validar deixa de o contar — era esse o sintoma."""
    assert len(registo.por_estado(reg_mod.RASCUNHO)) == 1
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota="lixo")
    assert registo.por_estado(reg_mod.RASCUNHO) == []
    assert len(registo.por_estado(reg_mod.DESCARTADO)) == 1


# ---------------------------------------------------------------------------
# Descartar não é apagar
# ---------------------------------------------------------------------------
def test_a_linha_nao_desaparece(registo, rascunho):
    """O registo continua lá, com todos os seus dados."""
    antes = registo.por_id(rascunho)
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota="engano")
    depois = registo.por_id(rascunho)
    assert depois is not None
    assert len(registo.todos()) == 1
    for campo in ("id", "ficheiro_origem", "hash", "assunto", "numero", "criado_em"):
        assert depois[campo] == antes[campo], f"{campo} mudou ao descartar"


def test_volta_a_fila_com_um_clique(registo, rascunho):
    """Reversível, porque um engano ao descartar não pode custar o documento."""
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota="engano")
    res = registo.mover_estado(rascunho, reg_mod.RASCUNHO, utilizador="ana",
                               nota="afinal era bom")
    assert res["ok"], res["erro"]
    assert registo.por_id(rascunho)["estado"] == reg_mod.RASCUNHO


# ---------------------------------------------------------------------------
# O motivo
# ---------------------------------------------------------------------------
def test_descartar_sem_motivo_e_recusado(registo, rascunho):
    """Guardar a linha e perder a razão seria guardar a parte que não interessa."""
    res = registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana")
    assert not res["ok"]
    assert "motivo" in res["erro"].lower()
    assert registo.por_id(rascunho)["estado"] == reg_mod.RASCUNHO


@pytest.mark.parametrize("nota", ["", "   ", "\t", "\n  \n"])
def test_motivo_em_branco_nao_serve(registo, rascunho, nota):
    """Espaços não são um motivo."""
    res = registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota=nota)
    assert not res["ok"]


def test_o_motivo_fica_no_historico(registo, rascunho):
    """É o que alguém vai ler daqui a seis meses."""
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana",
                         nota="Duplicado do registo #3")
    evs = [h for h in registo.por_id(rascunho)["historico"]
           if h["para"] == reg_mod.DESCARTADO]
    assert len(evs) == 1
    assert evs[0]["nota"] == "Duplicado do registo #3"
    assert evs[0]["utilizador"] == "ana"


def test_o_descarte_vai_ao_jornal_de_auditoria(registo, rascunho):
    """O jornal é apenas-acrescento e é ele que prova o que aconteceu."""
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota="duplicado")
    eventos = registo.jornal.ler_tudo()
    descartes = [e for e in eventos if e.get("para") == reg_mod.DESCARTADO]
    assert len(descartes) == 1
    assert descartes[0]["nota"] == "duplicado"
    assert descartes[0]["id"] == rascunho


# ---------------------------------------------------------------------------
# A regra que protege a certidão
# ---------------------------------------------------------------------------
def test_um_publicado_nao_se_descarta(registo, rascunho):
    """Sai do ecrã por RETIRADO, que carimba a desafixação. Sem exceções.

    Se se pudesse descartar um publicado, ele saía do expositor sem `desafixado_em`
    e sem quem — e a certidão de desafixação passava a não ter o que certificar.
    """
    publicado(registo, rascunho)
    res = registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana",
                               nota="quero tirar isto daqui")
    assert not res["ok"]
    assert registo.por_id(rascunho)["estado"] == reg_mod.PUBLICADO


def test_um_retirado_ja_se_descarta(registo, rascunho):
    """Depois de retirado em condições, pode ir para o lado."""
    publicado(registo, rascunho)
    registo.mover_estado(rascunho, reg_mod.RETIRADO, utilizador="ana")
    res = registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana",
                               nota="arrumação do arquivo")
    assert res["ok"], res["erro"]
    # A desafixação continua registada: descartar não apaga o que já se provou.
    r = registo.por_id(rascunho)
    assert r["desafixado_em"]
    assert r["afixado_em"]


def test_um_descartado_nao_salta_direto_para_publicado(registo, rascunho):
    """Voltar é para a fila, e daí segue o percurso normal."""
    registo.mover_estado(rascunho, reg_mod.DESCARTADO, utilizador="ana", nota="x")
    res = registo.mover_estado(rascunho, reg_mod.PUBLICADO, utilizador="ana")
    assert not res["ok"]


def test_descartado_e_um_estado_conhecido(registo):
    """Está em ESTADOS e tem rótulo — senão o painel mostrava a chave crua."""
    assert reg_mod.DESCARTADO in reg_mod.ESTADOS
    assert reg_mod.ESTADO_LABEL[reg_mod.DESCARTADO] == "Descartado"
