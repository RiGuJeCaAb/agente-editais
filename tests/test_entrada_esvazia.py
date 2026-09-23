"""
test_entrada_esvazia.py — A pasta de entrada deixa de ser um pântano.

Os ficheiros ficavam lá para sempre depois de recebidos. Ao fim de umas semanas
ninguém conseguia responder a olho à pergunta que interessa — «o que é que
chegou de novo?» — e essa pergunta é metade do trabalho do posto.

O que torna isto seguro é a ordem, e é ela que os testes fixam: quando o
ficheiro sai da pasta de entrada, já há uma cópia idêntica ao byte em
`originais/`, endereçada pelo SHA-256, e é dela que a composição lê. Mover e não
apagar, como em todo o resto do projeto.
"""
from __future__ import annotations

import os

import pytest

import agente
import originais as orig
import registo as reg_mod


@pytest.fixture
def posto(tmp_path):
    """Uma instalação com um PDF de uma página à espera na entrada."""
    import fitz
    cfg = {}
    for nome in ("entrada", "saida", "previas", "originais", "trabalho", "fundos"):
        (tmp_path / nome).mkdir(parents=True, exist_ok=True)
        cfg[nome] = str(tmp_path / nome)
    cfg["tratados"] = str(tmp_path / "entrada" / "tratados")
    os.makedirs(cfg["tratados"], exist_ok=True)
    cfg["registo_entrada"] = str(tmp_path / "registo_entrada.json")

    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((70, 140), "EDITAL 2026-0050", fontsize=24)
    d.save(os.path.join(cfg["entrada"], "edital.pdf"))
    d.close()

    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    return {"cfg": cfg, "reg": reg, "pasta": tmp_path}


def test_o_ficheiro_sai_da_entrada(posto):
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert "edital.pdf" not in os.listdir(posto["cfg"]["entrada"])
    assert "edital.pdf" in os.listdir(posto["cfg"]["tratados"])


def test_o_original_ja_esta_no_arquivo_quando_sai(posto):
    """A ordem é o que torna a mudança segura, e não o contrário."""
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    r = posto["reg"].todos()[0]
    assert r["sha256"]
    assert orig.procurar(posto["cfg"]["originais"], r["sha256"], ".pdf")


def test_mover_e_nao_apagar(posto):
    """Se a leitura correu mal, o ficheiro de origem continua ali ao lado."""
    antes = (posto["pasta"] / "entrada" / "edital.pdf").read_bytes()
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    depois = (posto["pasta"] / "entrada" / "tratados" / "edital.pdf").read_bytes()
    assert depois == antes


def test_a_varredura_seguinte_nao_volta_a_ler_o_que_esta_em_tratados(posto):
    """A subpasta não é varrida, e o hash já está registado de qualquer forma."""
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None) == 1
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None) == 0
    assert len(posto["reg"].todos()) == 1


def test_dois_ficheiros_com_o_mesmo_nome_nao_se_apagam(posto):
    """Dois editais podem chegar com o mesmo nome em meses diferentes."""
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    # Um segundo documento, conteúdo diferente, mesmo nome.
    import fitz
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((70, 140), "OUTRO EDITAL, MESMO NOME", fontsize=24)
    d.save(os.path.join(posto["cfg"]["entrada"], "edital.pdf"))
    d.close()
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert len(os.listdir(posto["cfg"]["tratados"])) == 2
    assert len(posto["reg"].todos()) == 2
