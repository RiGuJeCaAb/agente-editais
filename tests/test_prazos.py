"""
test_prazos.py — As janelas de afixação, e o que a lei diz sobre elas.

A regra do artigo 56.º do Anexo I da Lei n.º 75/2013 é fácil de ler mal: "cinco
dos 10 dias subsequentes" não são dez dias de afixação, são CINCO dias dentro de
uma janela de dez contada a partir da deliberação. A diferença tem consequências
— afixar ao oitavo dia não cumpre por mais tempo que se deixe o edital no ecrã —
e é isso que estes testes fixam.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import prazos as pr
import pytest

DELIBERACAO = "deliberacao_orgao_autarquico"


@pytest.fixture(autouse=True)
def tabela_limpa():
    """Repõe os tipos de origem, para um teste de config não contaminar os outros."""
    pr.carregar_tipos({})
    yield
    pr.carregar_tipos({})


def test_o_tipo_principal_cita_a_norma(tabela_limpa):
    """Um prazo sem proveniência é um número que ninguém pode confirmar."""
    d = pr.tipo(DELIBERACAO)
    assert "56" in d["base_legal"] and "75/2013" in d["base_legal"]
    assert d["fonte"].startswith("https://")
    assert d["dias_minimos"] == 5 and d["dias_janela"] == 10


def test_tipo_desconhecido_recua_para_o_de_omissao():
    """Um identificador que já não existe não pode impedir um edital de abrir."""
    assert pr.tipo("um_tipo_que_nunca_existiu")["rotulo"] == pr.TIPOS[pr.TIPO_POR_OMISSAO]["rotulo"]
    assert pr.tipo(None)["rotulo"] == pr.TIPOS[pr.TIPO_POR_OMISSAO]["rotulo"]


def test_propoe_o_minimo_legal_e_nao_o_maximo():
    """A proposta é a data em que a afixação já PODE cessar, não a em que deve.

    Deixar um edital mais tempo não viola nada; tirá-lo cedo, sim.
    """
    assert pr.propor_retirada(DELIBERACAO, "2026-06-29") == "2026-07-04"


def test_propoe_pelo_sugerido_quando_nao_ha_minimo_legal():
    """Tipos sem prazo fixo têm uma sugestão, para o campo não ficar em branco."""
    assert pr.propor_retirada("aviso", "2026-06-29") == "2026-07-14"
    assert pr.propor_retirada(pr.TIPO_POR_OMISSAO, "2026-06-29") is None


def test_cumprir_o_minimo_nao_gera_avisos():
    """Cinco dias dentro da janela é o caso certo, e cala-se."""
    assert pr.verificar(DELIBERACAO, "2026-06-29", "2026-07-04", "2026-06-29") == []


def test_avisa_quando_a_afixacao_e_curta_de_mais():
    """Menos de cinco dias é incumprimento, e diz-se com a norma ao lado."""
    avisos = pr.verificar(DELIBERACAO, "2026-06-29", "2026-07-01", "2026-06-29")
    assert len(avisos) == 1 and avisos[0]["grau"] == "aviso"
    assert "2 dia(s)" in avisos[0]["texto"] and "mínimo de 5" in avisos[0]["texto"]
    assert "56" in avisos[0]["base_legal"]


def test_a_janela_de_dez_dias_e_verificada_a_parte():
    """Afixar tarde não se corrige com mais tempo — é o ponto que a redação esconde.

    Afixado ao oitavo dia, a janela legal fecha ao décimo: sobram dois dias, e
    por isso o mínimo de cinco já não cabe lá dentro, deixe-se o edital o tempo
    que se deixar.
    """
    avisos = pr.verificar(DELIBERACAO, "2026-07-07", "2026-07-20", "2026-06-29")
    textos = " ".join(a["texto"] for a in avisos)
    assert all(a["grau"] == "aviso" for a in avisos)
    assert "limite" in textos and "não se cumpre" in textos


def test_sem_data_de_retirada_e_informacao_e_nao_aviso():
    """Ficar no ecrã indefinidamente cumpre o mínimo; só convém saber-se."""
    avisos = pr.verificar(DELIBERACAO, "2026-06-29", None, "2026-06-29")
    assert len(avisos) == 1 and avisos[0]["grau"] == "informacao"


def test_retirada_anterior_a_afixacao_e_dita_a_letra():
    """Guarda a regressão: dava contagens negativas ('dura -79 dia(s)').

    Um número negativo não avisa de nada — confunde. O caso tem agora resposta
    própria, e vem antes das outras verificações para não as contaminar.
    """
    avisos = pr.verificar(DELIBERACAO, "2026-09-18", "2026-06-30", "2026-06-29")
    assert len(avisos) == 1
    assert "anterior à da afixação" in avisos[0]["texto"]
    # Nenhuma contagem negativa em lado nenhum da mensagem — era esse o defeito.
    assert not re.search(r"-\d+ dia", avisos[0]["texto"])


def test_retirada_ja_passada_avisa_antes_de_publicar():
    """Publicar com uma data de retirada vencida tira o edital no ciclo seguinte."""
    ontem = (date.today() - timedelta(days=3)).isoformat()
    avisos = pr.verificar(pr.TIPO_POR_OMISSAO, None, ontem, None)
    assert len(avisos) == 1 and "já passou" in avisos[0]["texto"]


@pytest.mark.parametrize("valor", ["30 de fevereiro", "", "2026-13-45", None, "amanhã"])
def test_datas_impossiveis_nao_rebentam(valor):
    """Um campo mal preenchido não pode levar a verificação abaixo."""
    assert pr.verificar(DELIBERACAO, valor, valor, valor) == []
    assert pr.propor_retirada(DELIBERACAO, valor) is None


def test_o_municipio_pode_acrescentar_tipos():
    """Prazos fixados em regulamento próprio não obrigam a mexer no código."""
    pr.carregar_tipos({"tipos_de_documento": {
        "postura_municipal": {"rotulo": "Postura municipal", "dias_minimos": 15,
                              "base_legal": "Regulamento municipal X, artigo 4.º"}}})
    assert pr.tipo("postura_municipal")["dias_minimos"] == 15
    assert pr.propor_retirada("postura_municipal", "2026-06-01") == "2026-06-16"


def test_o_municipio_pode_sobrepor_so_um_campo():
    """Mudar o prazo sugerido não obriga a reescrever a base legal do tipo."""
    pr.carregar_tipos({"tipos_de_documento": {"aviso": {"dias_sugeridos": 45}}})
    assert pr.tipo("aviso")["dias_sugeridos"] == 45
    assert pr.tipo("aviso")["rotulo"] == "Aviso"           # veio dos de origem


def test_config_malformado_e_ignorado_sem_rebentar():
    """Um config com lixo não pode impedir o agente de arrancar."""
    pr.carregar_tipos({"tipos_de_documento": {"mau": "isto devia ser um dicionário"}})
    assert "mau" not in pr.TIPOS
    assert pr.tipo(DELIBERACAO)["dias_minimos"] == 5


def test_tipos_para_painel_traz_o_que_o_seletor_precisa():
    """O painel precisa de id, rótulo e da norma para a mostrar ao lado."""
    tipos = pr.tipos_para_painel()
    principal = next(t for t in tipos if t["id"] == DELIBERACAO)
    assert set(principal) >= {"id", "rotulo", "nota", "base_legal", "dias_minimos"}
