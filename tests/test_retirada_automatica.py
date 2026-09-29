"""A data de retirada proposta pelo tipo do documento.

O prazo já se sabia calcular (prazos.propor_retirada) e já se sabia aplicar
(registo.aplicar_retiradas_automaticas). Faltava o meio: nada preenchia a data,
e a retirada automática só olha para quem tem data. Num posto real isso deu
oito editais publicados e ZERO retirados, com documentos de junho ainda no ecrã
em setembro.

Estes testes exercitam o elo, e os limites que ele tem de respeitar.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import pytest  # noqa: E402

import painel as pnl  # noqa: E402
import prazos as pr  # noqa: E402
import registo as reg_mod  # noqa: E402
from conftest import META_BOA  # noqa: E402

DELIBERACAO = "deliberacao_orgao_autarquico"    # 5 dias mínimos, Lei 75/2013
AVISO = "aviso"                                 # sem mínimo legal, 15 sugeridos


def _publicar(registo, tipo=None, retirada=None, afixado_em=None):
    """Leva um edital novo até publicado, pelo caminho legítimo."""
    r = registo.criar_rascunho(ficheiro_origem="edital.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=dict(META_BOA))
    campos = {}
    if tipo is not None:
        campos["tipo"] = tipo
    if retirada is not None:
        campos["data_retirada"] = retirada
    if campos:
        registo.editar(r["id"], campos, utilizador="ana")
    registo.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana")
    if afixado_em is not None:
        # Antedatar a afixação: o bloco da publicação só carimba quando está
        # vazia, por isso isto sobrevive à transição e serve de base à proposta.
        registo.por_id(r["id"])["afixado_em"] = afixado_em
    registo.mover_estado(r["id"], reg_mod.PUBLICADO, utilizador="ana")
    return registo.por_id(r["id"])


def test_publicar_um_tipo_com_prazo_preenche_a_data(registo):
    """Publicar uma deliberação sem data de saída dá-lhe os 5 dias da lei."""
    r = _publicar(registo, tipo=DELIBERACAO, afixado_em="2026-06-29T10:00:00")
    assert r["data_retirada"] == "2026-07-04"


def test_prazo_sugerido_tambem_conta(registo):
    """Um tipo sem mínimo legal mas com prazo sugerido também propõe."""
    r = _publicar(registo, tipo=AVISO, afixado_em="2026-06-29T10:00:00")
    assert r["data_retirada"] == "2026-07-14"


def test_o_historico_diz_que_a_data_veio_do_tipo(registo):
    """Quem audita tem de distinguir um prazo decidido de um prazo calculado."""
    r = _publicar(registo, tipo=DELIBERACAO, afixado_em="2026-06-29T10:00:00")
    ultima = r["historico"][-1]["nota"]
    assert "2026-07-04" in ultima
    assert "proposta pelo tipo" in ultima


def test_o_ciclo_fecha_ate_a_retirada(registo):
    """O elo todo: publicar sem data, a data nascer do tipo, e a retirada dar-se.

    É o teste que justifica a peça. Antes dele, cada metade funcionava e o
    edital ficava afixado para sempre na mesma.
    """
    ontem = (date.today() - timedelta(days=30)).isoformat()
    r = _publicar(registo, tipo=DELIBERACAO, afixado_em=f"{ontem}T10:00:00")
    assert r["data_retirada"], "a publicação devia ter proposto uma data"
    assert registo.aplicar_retiradas_automaticas() == [r["id"]]
    assert registo.por_id(r["id"])["estado"] == reg_mod.RETIRADO


def test_o_painel_recebe_a_proposta_antes_de_publicar(registo):
    """O painel mostra a data proposta ANTES de alguém publicar, para a poder mudar."""
    r = registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=dict(META_BOA))
    registo.editar(r["id"], {"tipo": DELIBERACAO}, utilizador="ana")
    vista = pnl._com_proposta(registo.todos())
    # META_BOA publica-se a 2026-06-29; cinco dias depois é 4 de julho.
    assert vista[0]["retirada_proposta"] == "2026-07-04"


def test_o_painel_nao_propoe_o_que_ja_esta_decidido(registo):
    """Havendo data escrita, não há proposta nenhuma a fazer."""
    r = registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=dict(META_BOA))
    registo.editar(r["id"], {"tipo": DELIBERACAO, "data_retirada": "2026-08-01"},
                   utilizador="ana")
    assert pnl._com_proposta(registo.todos())[0]["retirada_proposta"] is None


# --- os dois que fixam o que NÃO pode mudar --------------------------------
# Passam contra o código anterior de propósito: não provam o que se acrescentou,
# provam que o que se acrescentou não passou por cima de nada.

def test_nao_pisa_a_data_que_uma_pessoa_escreveu(registo):
    """A decisão do posto manda sobre a tabela, sempre."""
    r = _publicar(registo, tipo=DELIBERACAO, retirada="2026-12-31",
                  afixado_em="2026-06-29T10:00:00")
    assert r["data_retirada"] == "2026-12-31"


def test_tipo_sem_prazo_declarado_nao_ganha_data(registo):
    """Sem tipo declarado não há prazo, e a aplicação não inventa nenhum."""
    r = _publicar(registo, tipo=pr.TIPO_POR_OMISSAO,
                  afixado_em="2026-06-29T10:00:00")
    assert r["data_retirada"] is None


# --- os dois achados da revisão automática sobre esta própria peça ----------

def test_o_painel_nao_enche_o_campo_com_a_proposta():
    """A proposta mostra-se; não se escreve no campo por ela.

    A primeira versão desta peça pré-preenchia o campo da retirada com a data
    proposta. Parecia cómodo e era um defeito: quem abrisse o registo para
    corrigir o assunto e carregasse em Guardar enviava a proposta como se a
    tivesse escrito. A partir daí a publicação já não a recalculava da afixação
    real — e se a data de publicação declarada fosse anterior à afixação, o
    edital saía do ecrã antes do prazo legal.

    Agora o campo fica vazio e há um botão que o enche. Encher passa a ser um
    ato de quem está ao teclado, que é o que distingue uma decisão de um efeito
    secundário.
    """
    html = (Path(__file__).resolve().parents[1] / "lib" / "painel.html").read_text(
        encoding="utf-8")
    assert "r.data_retirada||r.retirada_proposta" not in html, (
        "o campo da retirada voltou a vir pré-preenchido com a proposta")
    assert "btn-proposta" in html, "sumiu o botão que aceita a proposta"


def test_prazo_mal_escrito_nao_deixa_a_afixacao_carimbada(registo):
    """Se o cálculo do prazo rebentar, a transição não deixa rasto nenhum.

    Um município pode escrever o prazo por extenso no config.json. O `int(dias)`
    rebenta, e se o carimbo da afixação já estivesse posto a tentativa falhada
    deixava lá uma data — que a repetição seguinte reutilizava como relógio
    legal, porque o carimbo só se põe quando está vazio.
    """
    pr.carregar_tipos({"tipos_de_documento": {
        "estragado": {"rotulo": "Prazo por extenso", "dias_minimos": "cinco"}}})
    try:
        r = registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                                   num_paginas=1, meta=dict(META_BOA))
        registo.editar(r["id"], {"tipo": "estragado"}, utilizador="ana")
        registo.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana")
        with pytest.raises(ValueError):
            registo.mover_estado(r["id"], reg_mod.PUBLICADO, utilizador="ana")
        depois = registo.por_id(r["id"])
        assert depois["afixado_em"] is None, "ficou o carimbo de uma tentativa falhada"
        assert depois["estado"] == reg_mod.VALIDADO
    finally:
        # TIPOS é global do módulo: repõe-se, senão contamina os testes seguintes.
        pr.carregar_tipos({})
