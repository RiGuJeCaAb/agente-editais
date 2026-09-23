"""
test_exportacao.py — As pastas por estado são uma vista, e sabem-no.

O posto pediu que um edital mudasse de pasta conforme o estado. A razão é boa e
é operacional: quem lá trabalha quer abrir o Explorador e ver o que está
afixado, sem depender de uma aplicação.

Mas nesse desenho a pasta onde um ficheiro está passa a ser uma segunda
afirmação sobre o estado do edital, ao lado da que está no registo — e duas
afirmações sobre a mesma coisa divergem. O registo grava de forma atómica e diz
quem fez o quê; uma pasta não faz nem uma coisa nem outra.

A saída foi esta: o registo manda, e as pastas constroem-se a pedido a partir
dele. Os testes deste ficheiro existem sobretudo para fixar essa decisão, e o
que mais interessa é o do fim — a exportação não apaga uma pasta que não tenha
sido ela a criar.
"""
from __future__ import annotations

import csv
import os

import pytest

import exportacao
import originais as orig
import registo as reg_mod
from conftest import META_BOA


@pytest.fixture
def posto(tmp_path):
    cfg = {"originais": str(tmp_path / "originais"),
           "exportacao": str(tmp_path / "exportacao"),
           "registo_entrada": str(tmp_path / "registo_entrada.json")}
    os.makedirs(cfg["originais"], exist_ok=True)
    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    return {"cfg": cfg, "reg": reg, "pasta": tmp_path}


def edital(posto, numero, assunto, estado, nome="e.pdf", conteudo=None):
    """Cria um edital com original arquivado e leva-o até ao estado pedido."""
    origem = posto["pasta"] / f"{numero}_{nome}"
    origem.write_bytes(conteudo or f"%PDF {numero}".encode())
    sha256, _ = orig.arquivar(posto["cfg"]["originais"], str(origem))
    meta = dict(META_BOA, sha256=sha256, numero=numero, assunto=assunto,
                data_publicacao="2026-09-20")
    r = posto["reg"].criar_rascunho(ficheiro_origem=origem.name, hash_ficheiro=numero,
                                    num_paginas=1, meta=meta)
    # Conferir ANTES de mover, senão um rascunho dava uma volta ao percurso todo.
    for destino in (reg_mod.VALIDADO, reg_mod.PUBLICADO, reg_mod.RETIRADO):
        if posto["reg"].por_id(r["id"])["estado"] == estado:
            break
        posto["reg"].mover_estado(r["id"], destino, utilizador="ana.silva")
    return r


def test_publicados_e_retirados_vao_para_pastas_diferentes(posto):
    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    edital(posto, "2026-0051", "DELIBERAÇÕES", reg_mod.RETIRADO)
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    assert r["publicados"] == 1
    assert r["retirados"] == 1
    raiz = posto["cfg"]["exportacao"]
    assert len(_pdfs(os.path.join(raiz, "publicados"))) == 1
    assert len(_pdfs(os.path.join(raiz, "retirados"))) == 1


def _pdfs(pasta):
    return [n for n in os.listdir(pasta) if n.endswith(".pdf")]


@pytest.mark.parametrize("estado", [reg_mod.RASCUNHO, reg_mod.VALIDADO])
def test_o_que_ainda_nao_foi_afixado_nao_se_exporta(posto, estado):
    """Um rascunho não é nada para quem consulta de fora."""
    edital(posto, "2026-0060", "AINDA NÃO", estado)
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    assert r["publicados"] == 0 and r["retirados"] == 0


def test_um_descartado_nao_se_exporta(posto):
    e = edital(posto, "2026-0061", "POSTO DE PARTE", reg_mod.RETIRADO)
    posto["reg"].mover_estado(e["id"], reg_mod.DESCARTADO,
                              utilizador="ana", nota="duplicado")
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    assert r["retirados"] == 0


def test_o_nome_comeca_pela_data_para_ordenar_sozinho(posto):
    """É como alguém procura um edital: «foi aí por junho»."""
    edital(posto, "2026-0050", "CORTE DE ÁGUA NA RUA DIREITA", reg_mod.PUBLICADO)
    exportacao.exportar(posto["cfg"], posto["reg"])
    nome = _pdfs(os.path.join(posto["cfg"]["exportacao"], "publicados"))[0]
    assert nome.startswith("2026-09-20_")
    assert "2026_0050" in nome
    assert "corte_de_agua" in nome


def test_o_indice_leva_quem_afixou(posto):
    """A pasta não sabe dizer quem publicou. O índice sabe, porque vem do registo."""
    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    with open(r["indice"], encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert len(linhas) == 1
    assert linhas[0]["afixado_por"] == "ana.silva"
    assert linhas[0]["afixado_em"]
    assert linhas[0]["estado"] == "Publicado"


def test_exportar_duas_vezes_nao_duplica(posto):
    """É um retrato do registo agora, não um histórico de si mesma."""
    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    exportacao.exportar(posto["cfg"], posto["reg"])
    exportacao.exportar(posto["cfg"], posto["reg"])
    assert len(_pdfs(os.path.join(posto["cfg"]["exportacao"], "publicados"))) == 1


def test_o_que_sai_do_registo_desaparece_da_exportacao(posto):
    """Se divergirem, volta-se a gerar e fica resolvido — é para isto que serve."""
    e = edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    exportacao.exportar(posto["cfg"], posto["reg"])
    posto["reg"].mover_estado(e["id"], reg_mod.RETIRADO, utilizador="ana")
    exportacao.exportar(posto["cfg"], posto["reg"])
    raiz = posto["cfg"]["exportacao"]
    assert _pdfs(os.path.join(raiz, "publicados")) == []
    assert len(_pdfs(os.path.join(raiz, "retirados"))) == 1


def test_um_edital_sem_original_fica_no_indice_sem_ficheiro(posto):
    """Omiti-lo seria a exportação a fingir que ele não existe."""
    meta = dict(META_BOA, sha256="", numero="2026-0070", data_publicacao="2026-09-20")
    r0 = posto["reg"].criar_rascunho(ficheiro_origem="perdido.pdf",
                                     hash_ficheiro="h", num_paginas=1, meta=meta)
    posto["reg"].mover_estado(r0["id"], reg_mod.VALIDADO, utilizador="ana")
    posto["reg"].mover_estado(r0["id"], reg_mod.PUBLICADO, utilizador="ana")
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    assert r["sem_original"] == [r0["id"]]
    assert r["publicados"] == 0
    with open(r["indice"], encoding="utf-8-sig", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    assert len(linhas) == 1
    assert linhas[0]["ficheiro_exportado"] == ""


# ---------------------------------------------------------------------------
# A garantia
# ---------------------------------------------------------------------------
def test_recusa_apagar_uma_pasta_que_nao_criou(posto):
    """O teste que mais importa: isto apaga ficheiros, e o caminho vem do config.

    Alguém pode apontar 'exportacao' para a pasta errada. Sem a marca de que a
    pasta é gerada, a exportação não lhe toca — e diz porquê, em vez de falhar
    calada ou de levar o trabalho de outra pessoa à frente.
    """
    publicados = posto["pasta"] / "exportacao" / "publicados"
    publicados.mkdir(parents=True)
    precioso = publicados / "NAO_APAGAR.pdf"
    precioso.write_bytes(b"o trabalho de alguem")

    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    with pytest.raises(RuntimeError, match=exportacao.MARCA):
        exportacao.exportar(posto["cfg"], posto["reg"])
    assert precioso.exists(), "a exportação apagou um ficheiro que não era dela"


def test_uma_pasta_vazia_sem_marca_pode_ser_usada(posto):
    """Não há nada a perder, e obrigar a criar a marca à mão seria cerimónia."""
    (posto["pasta"] / "exportacao" / "publicados").mkdir(parents=True)
    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    r = exportacao.exportar(posto["cfg"], posto["reg"])
    assert r["publicados"] == 1


def test_a_marca_avisa_que_mover_ficheiros_nao_muda_nada(posto):
    """Quem abre a pasta tem de perceber o que ela é antes de lhe mexer."""
    edital(posto, "2026-0050", "CORTE DE ÁGUA", reg_mod.PUBLICADO)
    exportacao.exportar(posto["cfg"], posto["reg"])
    marca = (posto["pasta"] / "exportacao" / "publicados" / exportacao.MARCA
             ).read_text(encoding="utf-8")
    assert "GERADA" in marca
    assert "não muda" in marca.lower() or "NÃO é aqui" in marca
    assert "painel" in marca
