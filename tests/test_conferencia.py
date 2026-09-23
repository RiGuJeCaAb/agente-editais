"""
test_conferencia.py — Dizer o que está desalinhado, sem mexer em nada.

O registo manda e o disco tem os ficheiros, e as duas coisas separam-se: uma
pasta que alguém limpou à mão, uma migração que trouxe editais cujos originais
já não existem, um PNG que sobreviveu ao registo que o gerou.

O caso que motivou isto: depois da migração do modelo antigo ficaram rascunhos
sem data de publicação e sem ficheiro de origem. Não se conseguem validar (falta
a data) nem publicar (falta o documento). Dava para os descartar no painel — mas
primeiro era preciso adivinhar quais eram.

O teste que mais importa é o último: a conferência não apaga nada. Uma
ferramenta que arruma sozinha é uma ferramenta em que é preciso confiar
cegamente, e as decisões sobre um edital municipal são de quem responde por ele.
"""
from __future__ import annotations

import os

import pytest

import conferencia
import originais as orig
import registo as reg_mod
from conftest import META_BOA


@pytest.fixture
def posto(tmp_path):
    """Uma instalação com as pastas todas e um registo vazio."""
    cfg = {}
    for nome in ("entrada", "tratados", "saida", "previas", "originais"):
        pasta = tmp_path / nome
        pasta.mkdir(parents=True, exist_ok=True)
        cfg[nome] = str(pasta)
    cfg["registo_entrada"] = str(tmp_path / "registo_entrada.json")
    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    return {"cfg": cfg, "reg": reg, "pasta": tmp_path}


def com_original(posto, nome="edital.pdf", conteudo=b"%PDF-1.4 um edital"):
    """Cria um registo cujo original está mesmo no arquivo imutável."""
    origem = posto["pasta"] / nome
    origem.write_bytes(conteudo)
    sha256, _ = orig.arquivar(posto["cfg"]["originais"], str(origem))
    origem.unlink()
    meta = dict(META_BOA, sha256=sha256)
    return posto["reg"].criar_rascunho(ficheiro_origem=nome, hash_ficheiro=nome,
                                       num_paginas=1, meta=meta)


def sem_original(posto, nome="perdido.pdf", data="2026-09-20"):
    """Cria um registo que aponta para um documento que não existe."""
    meta = dict(META_BOA, sha256="", data_publicacao=data)
    return posto["reg"].criar_rascunho(ficheiro_origem=nome, hash_ficheiro=nome,
                                       num_paginas=1, meta=meta)


# ---------------------------------------------------------------------------
# O que a conferência tem de encontrar
# ---------------------------------------------------------------------------
def test_um_registo_com_original_nao_e_assinalado(posto):
    com_original(posto)
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["sem_original"] == []
    assert not conferencia.ha_problemas(r)


def test_encontra_o_registo_sem_original(posto):
    r0 = sem_original(posto)
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert [x["id"] for x in r["sem_original"]] == [r0["id"]]
    assert conferencia.ha_problemas(r)


def test_o_original_na_pasta_de_entrada_conta(posto):
    """Registos anteriores ao arquivo só têm o nome do ficheiro."""
    r0 = sem_original(posto)
    (posto["pasta"] / "entrada" / r0["ficheiro_origem"]).write_bytes(b"ola")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["sem_original"] == []


def test_o_original_em_tratados_tambem_conta(posto):
    """A pasta para onde os documentos passaram a ir depois de recebidos."""
    r0 = sem_original(posto)
    (posto["pasta"] / "tratados" / r0["ficheiro_origem"]).write_bytes(b"ola")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["sem_original"] == []


def test_o_rascunho_sem_saida_e_assinalado_a_parte(posto):
    """Sem data não se valida, sem original não se publica: fica preso.

    É a forma exata dos zombies que a migração deixou, e merece nome próprio no
    relatório porque a resposta é diferente — não é repor um ficheiro, é decidir
    se aquele edital ainda interessa.
    """
    preso = sem_original(posto, "preso.pdf", data=None)
    sem_original(posto, "tem_data.pdf", data="2026-09-20")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert len(r["sem_original"]) == 2
    assert [x["id"] for x in r["rascunhos_impossiveis"]] == [preso["id"]]


def test_um_descartado_sem_original_nao_e_assinalado(posto):
    """Foi posto de parte de propósito: ir chatear com ele seria ruído."""
    r0 = sem_original(posto)
    posto["reg"].mover_estado(r0["id"], reg_mod.DESCARTADO,
                              utilizador="ana", nota="sem documento")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["sem_original"] == []


# ---------------------------------------------------------------------------
# Ficheiros que ninguém reclama
# ---------------------------------------------------------------------------
def test_encontra_o_png_orfao(posto):
    (posto["pasta"] / "saida" / "202601010000_99_orfao_16x9_3d_CLD.png").write_bytes(b"x")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["png_orfaos"] == ["202601010000_99_orfao_16x9_3d_CLD.png"]


@pytest.mark.parametrize("nome", ["index.html", "slides.json", "arquivo.zip"])
def test_os_ficheiros_da_tv_nao_sao_ecras_orfaos(posto, nome):
    """A pasta de saída também tem a página, os slides e o ZIP."""
    (posto["pasta"] / "saida" / nome).write_bytes(b"x")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["png_orfaos"] == []


def test_o_png_reclamado_nao_e_orfao(posto):
    novo = com_original(posto)
    posto["reg"].definir(novo["id"], ficheiros_png=["ecra.png"])
    (posto["pasta"] / "saida" / "ecra.png").write_bytes(b"x")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["png_orfaos"] == []


def test_encontra_o_original_orfao(posto):
    """Um documento arquivado que nenhum registo aponta."""
    solto = posto["pasta"] / "solto.pdf"
    solto.write_bytes(b"%PDF ninguem me reclama")
    orig.arquivar(posto["cfg"]["originais"], str(solto))
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert len(r["originais_orfaos"]) == 1


# ---------------------------------------------------------------------------
# A garantia
# ---------------------------------------------------------------------------
def test_conferir_nao_apaga_nem_muda_nada(posto):
    """O teste que mais importa: isto é um relatório, não uma arrumação."""
    com_original(posto)
    sem_original(posto)
    (posto["pasta"] / "saida" / "orfao.png").write_bytes(b"x")
    (posto["pasta"] / "previas" / "previa_9999_01.jpg").write_bytes(b"x")

    antes_estados = [(r["id"], r["estado"]) for r in posto["reg"].todos()]
    antes_ficheiros = sorted(
        os.path.join(raiz, n)
        for raiz, _p, ns in os.walk(posto["pasta"]) for n in ns)

    conferencia.conferir(posto["cfg"], posto["reg"])

    reaberto = reg_mod.RegistoEntrada(posto["cfg"]["registo_entrada"])
    assert [(r["id"], r["estado"]) for r in reaberto.todos()] == antes_estados
    depois = sorted(os.path.join(raiz, n)
                    for raiz, _p, ns in os.walk(posto["pasta"]) for n in ns)
    assert depois == antes_ficheiros, "a conferência mexeu em ficheiros"


# ---------------------------------------------------------------------------
# Defeito apanhado na revisão do PR #6
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "slides.json.bak.1",          # cópia de uma gravação atómica
    "index.html.bak.2",
    "registo.tmp",
    "LEIAME",                     # sem extensão nenhuma
])
def test_so_os_png_contam_como_ecras_orfaos(posto, nome):
    """A lista era de exclusões, e o que lá aparecesse amanhã contava como ecrã.

    Uma cópia `.bak.1` de uma gravação atómica não acaba em `.json`, e era
    relatada como um ecrã que nenhum registo reclama — a mandar alguém procurar
    um problema que não existe. Um relatório que grita por nada deixa de ser
    lido, e aí deixa de apanhar o que interessa.
    """
    (posto["pasta"] / "saida" / nome).write_bytes(b"x")
    r = conferencia.conferir(posto["cfg"], posto["reg"])
    assert r["png_orfaos"] == []
