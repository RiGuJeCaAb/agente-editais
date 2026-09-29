"""A referência interna: uma etiqueta nossa, que não é o número do edital.

O número do edital vem do Gestiona, é oficial, e a aplicação nunca lho atribui.
Isto é outra coisa — serve para se poder dizer «o AE-20260929-0021» em vez de
«aquele aviso da escola, salvo erro».
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import painel as pnl  # noqa: E402
import registo as reg_mod  # noqa: E402
from conftest import META_BOA  # noqa: E402


def test_a_referencia_sai_da_data_de_criacao_e_do_id():
    """Formato AE-AAAAMMDD-NNNN, legível e ditável ao telefone."""
    assert reg_mod.referencia(
        {"criado_em": "2026-09-29T10:14:02", "id": 21}) == "AE-20260929-0021"


def test_dois_registos_do_mesmo_minuto_nao_colidem():
    """Num minuto entram vários ficheiros de uma vez, e já entraram.

    É por isto que a referência leva o id e não a hora: a hora não garante nada,
    o id garante. Uma referência que pode colidir é pior do que não existir.
    """
    instante = "2026-09-29T10:14:02"
    a = reg_mod.referencia({"criado_em": instante, "id": 7})
    b = reg_mod.referencia({"criado_em": instante, "id": 8})
    assert a != b


def test_sem_data_de_criacao_ainda_ha_referencia():
    """Um registo sem data não fica sem etiqueta — fica com uma mais curta."""
    assert reg_mod.referencia({"id": 3}) == "AE-0003"


def test_o_painel_recebe_a_referencia(registo):
    """O painel mostra-a, e recebe-a feita do servidor como os outros derivados."""
    registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                           num_paginas=1, meta=dict(META_BOA))
    vista = pnl._derivados(registo.todos())
    assert vista[0]["referencia"].startswith("AE-")


# --- os dois que fixam recusas ------------------------------------------------
# Passam contra o código anterior de propósito: não provam o que se acrescentou,
# provam que o que se acrescentou não passou por cima de nada.

def test_a_referencia_nao_e_guardada_no_registo(registo):
    """É derivada. Guardá-la abria a porta a divergir do que a produziu."""
    r = registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=dict(META_BOA))
    assert "referencia" not in registo.por_id(r["id"])


def test_a_referencia_nunca_toca_no_numero_do_edital(registo):
    """O número é do Gestiona. A aplicação não o inventa nem o preenche.

    Este é o teste que interessa: fixa a recusa. Se um dia alguém achar cómodo
    pôr a referência no campo do número «só para não ficar vazio», falha aqui —
    e o que está em causa é uma designação que sai impressa numa certidão de
    afixação.
    """
    r = registo.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=dict(META_BOA, numero=""))
    registo.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana")
    registo.mover_estado(r["id"], reg_mod.PUBLICADO, utilizador="ana")
    assert registo.por_id(r["id"])["numero"] == "", "a aplicação atribuiu um número"


# --- a etiqueta no ecrã -------------------------------------------------------
# A certidão imprime «Referência interna» por uma razão escrita num teste ali:
# uma etiqueta nossa ao lado de um número oficial, sem nada a distingui-los, é
# pior do que não a mostrar. O painel saiu sem a etiqueta, e isso valia para lá
# na mesma. Apanhado em revisão, não por mim.
#
# Isto é análise estática do painel.html: prova que a forma exata do defeito não
# volta -- e sobretudo que não volta em METADE dos sítios, que é como ele nasceu.
# Não prova que o painel desenha bem no browser; isso vê-se a olho.

PAINEL = (Path(__file__).resolve().parents[1] / "lib" / "painel.html").read_text(
    encoding="utf-8")


def test_a_referencia_aparece_rotulada_nas_duas_vistas():
    """Duas vistas desenham a ficha, e as duas têm de dizer o que ali está.

    São dois sítios no mesmo ficheiro. Uma alteração futura que só mexa num
    deixa o outro a mostrar um AE-... cru por baixo do número do Gestiona.
    """
    linhas = [linha for linha in PAINEL.splitlines() if 'class="ref"' in linha]
    assert len(linhas) == 2, f"esperava dois sítios de desenho, encontrei {len(linhas)}"
    for linha in linhas:
        assert "Referência interna" in linha, linha.strip()
