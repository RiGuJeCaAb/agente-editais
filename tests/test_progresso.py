"""
test_progresso.py — O painel passa a dizer o que está a fazer.

Compor os ecrãs de um edital demora. Um documento de vinte páginas leva dezenas
de segundos entre carregar em «Publicar» e a imagem aparecer na televisão, e
durante esse tempo o painel não dizia nada. Quem estava ao teclado tinha duas
hipóteses igualmente más: esperar sem saber se alguma coisa estava a acontecer,
ou carregar outra vez — que é o que as pessoas fazem, e com razão.
"""
from __future__ import annotations

import threading

import pytest

import progresso


@pytest.fixture(autouse=True)
def limpo():
    progresso.parado()
    yield
    progresso.parado()


def test_em_repouso_nao_ha_frase():
    """Uma faixa que está sempre visível deixa de querer dizer alguma coisa."""
    assert progresso.frase() == ""
    assert progresso.actual()["fase"] == progresso.NADA


def test_a_ler_diz_o_ficheiro_e_a_pagina():
    progresso.a_ler("edital_2026-0050.pdf", 3, 12)
    f = progresso.frase()
    assert "edital_2026-0050.pdf" in f
    assert "3 de 12" in f


def test_a_compor_diz_o_ecra():
    progresso.a_compor(7, "edital.pdf", 2, 4)
    assert "2 de 4" in progresso.frase()
    assert progresso.actual()["registo"] == 7


def test_a_publicar_fala_da_televisao():
    progresso.a_publicar(5, 9)
    assert "televisão" in progresso.frase()
    assert "5 de 9" in progresso.frase()


def test_sem_total_nao_se_inventa_uma_contagem():
    """No arranque da leitura ainda não se sabe quantas páginas há."""
    progresso.a_ler("edital.pdf", 0, 0)
    assert "de 0" not in progresso.frase()
    assert "edital.pdf" in progresso.frase()


def test_substitui_em_vez_de_acumular():
    """O que interessa é o agora; o histórico está no jornal de auditoria."""
    progresso.a_ler("a.pdf", 1, 2)
    progresso.a_compor(1, "b.pdf", 1, 1)
    e = progresso.actual()
    assert e["fase"] == progresso.A_COMPOR
    assert "ficheiro" in e and e["ficheiro"] == "b.pdf"
    assert "a.pdf" not in progresso.frase()


def test_actual_devolve_uma_copia():
    """O painel serializa isto enquanto a thread de trabalho lhe pode mexer.

    Ler e escrever a mesma estrutura em threads diferentes sem lock é a forma de
    ter um erro que só aparece em produção. Já aconteceu neste projeto, com a
    lista de registos.
    """
    progresso.a_ler("edital.pdf", 1, 3)
    copia = progresso.actual()
    copia["ficheiro"] = "mexido"
    assert progresso.actual()["ficheiro"] == "edital.pdf"


def test_aguenta_threads_a_escrever_e_a_ler():
    """Não prova ausência de corridas — nenhum teste prova. Apanha o óbvio."""
    erros = []

    def escrever():
        for i in range(200):
            progresso.a_ler("edital.pdf", i, 200)

    def ler():
        try:
            for _ in range(200):
                progresso.frase()
                progresso.actual()
        except Exception as ex:      # noqa: BLE001 - queremos qualquer falha
            erros.append(ex)

    ts = [threading.Thread(target=escrever), threading.Thread(target=ler),
          threading.Thread(target=escrever), threading.Thread(target=ler)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert erros == []
