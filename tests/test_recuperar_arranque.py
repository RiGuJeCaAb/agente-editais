"""
test_recuperar_arranque.py — O que um corte sem aviso deixa a meio, o arranque acaba.

A paragem com ordem (0.26.1) trata do `systemctl stop`. Não chega a correr
quando a luz falha, quando a VM é desligada à força, quando a paragem esgota o
tempo ou quando a receção rebenta a meio. Ficavam dois estados partidos (issue
#29):

- o jornal com um id que o registo não tem, e o rascunho seguinte a reutilizá-lo;
- o ficheiro na entrada com o rascunho já criado, saltado em todas as voltas.

Os cortes simulam-se com uma exceção que não é Exception, como um processo
morto: o except da receção não a apanha, e nada do que vinha a seguir corre.
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

import agente
import armazenamento as arm
import registo as reg_mod
from conftest import META_BOA


class _Morte(BaseException):
    """O processo morreu aqui."""


def _rascunho(reg, n):
    return reg.criar_rascunho(ficheiro_origem=f"edital-{n}.pdf", hash_ficheiro=f"h{n}",
                              num_paginas=1, meta=META_BOA)


def _morrer_entre_o_jornal_e_o_registo(reg, monkeypatch, n):
    """Cria um rascunho que chega ao jornal e não chega ao registo."""
    def morre():
        raise _Morte
    monkeypatch.setattr(reg, "_guardar", morre)
    with pytest.raises(_Morte):
        _rascunho(reg, n)
    monkeypatch.undo()


def test_o_id_que_so_o_jornal_conhece_nao_se_reutiliza(tmp_path, monkeypatch):
    """Contra o código anterior falha: o rascunho seguinte voltava a ser o #2."""
    caminho = str(tmp_path / "registo_entrada.json")
    reg = reg_mod.RegistoEntrada(caminho)
    _rascunho(reg, 1)
    _morrer_entre_o_jornal_e_o_registo(reg, monkeypatch, 2)

    reg = reg_mod.RegistoEntrada(caminho)
    assert _rascunho(reg, 3)["id"] == 3
    recebidos = [ev["id"] for ev in reg.jornal.ler_tudo()
                 if ev.get("nota") == "Documento recebido e lido"]
    assert len(recebidos) == len(set(recebidos)), "dois documentos com o mesmo id no jornal"


def test_o_id_que_fica_por_usar_tem_a_razao_no_jornal(tmp_path, monkeypatch):
    """Quem audita vê o #2 recebido e nunca mais referido: o jornal diz porquê."""
    caminho = str(tmp_path / "registo_entrada.json")
    reg = reg_mod.RegistoEntrada(caminho)
    _rascunho(reg, 1)
    _morrer_entre_o_jornal_e_o_registo(reg, monkeypatch, 2)

    reg = reg_mod.RegistoEntrada(caminho)
    ultimo = reg.jornal.ler_tudo()[-1]
    assert ultimo["id"] == 2
    assert "fica por usar" in ultimo["nota"]


def test_um_registo_reposto_de_uma_copia_antiga_nao_reutiliza_ids(tmp_path):
    """O jornal não vai na mesma cópia que o registo: pode estar mais à frente."""
    caminho = tmp_path / "registo_entrada.json"
    reg = reg_mod.RegistoEntrada(str(caminho))
    _rascunho(reg, 1)
    copia = caminho.read_bytes()
    _rascunho(reg, 2)
    _rascunho(reg, 3)
    caminho.write_bytes(copia)

    reg = reg_mod.RegistoEntrada(str(caminho))
    assert _rascunho(reg, 4)["id"] == 4


def test_um_arranque_normal_nao_escreve_nada(tmp_path):
    """Fixa que o alinhamento não acrescenta eventos a cada arranque. Passa dos
    dois lados de propósito."""
    caminho = str(tmp_path / "registo_entrada.json")
    reg = reg_mod.RegistoEntrada(caminho)
    _rascunho(reg, 1)
    antes = len(reg.jornal.ler_tudo())
    reg = reg_mod.RegistoEntrada(caminho)
    assert len(reg.jornal.ler_tudo()) == antes


def test_um_evento_depois_de_uma_linha_cortada_nao_se_perde(tmp_path):
    """O corte custa a linha que apanhou, e não a seguinte.

    Contra o código anterior falha: o evento novo colava-se ao pedaço, e a
    linha que os dois faziam não se lia.
    """
    j = arm.JornalAuditoria(str(tmp_path / "auditoria.jsonl"))
    j.registar({"n": 0})
    with open(j.caminho, "a", encoding="utf-8") as f:
        f.write('{"n": 1, "utilizad')     # a máquina morreu aqui
    j.registar({"n": 2})
    assert [e["n"] for e in j.ler_tudo()] == [0, 2]


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
    return cfg


def _acabou_bem(cfg, reg):
    assert "edital.pdf" not in os.listdir(cfg["entrada"])
    assert "edital.pdf" in os.listdir(cfg["tratados"])
    r, = reg.todos()
    assert r["id"] == 1
    assert r["rececao_concluida"] is True
    assert r["ficheiros_previa"]
    for nome in r["ficheiros_previa"]:
        assert os.path.isfile(os.path.join(cfg["previas"], nome))


def test_o_documento_que_ficou_a_meio_acaba_no_arranque_seguinte(posto, monkeypatch):
    """Morto depois do rascunho e antes de o ficheiro sair da entrada.

    Contra o código anterior falha: o ficheiro ficava na entrada para sempre,
    saltado por o resumo já estar no registo, e o rascunho sem pré-visualizações.
    """
    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])

    def morre(*args, **kwargs):
        raise _Morte
    monkeypatch.setattr(agente, "_gerar_previas", morre)
    with pytest.raises(_Morte):
        agente.varrer_para_registo(posto, reg, None)
    monkeypatch.undo()
    assert "edital.pdf" in os.listdir(posto["entrada"])

    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])
    assert agente.varrer_para_registo(posto, reg, None) == 0, "não é um documento novo"
    _acabou_bem(posto, reg)


def test_uma_falha_a_meio_da_rececao_acaba_na_volta_seguinte(posto, monkeypatch):
    """Sem paragem nenhuma: uma exceção depois do rascunho. Levantado pelo
    Sourcery no #30. Contra o código anterior falha como o de cima."""
    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])
    original = agente._gerar_previas
    chamadas = []

    def falha_a_primeira(*args, **kwargs):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise OSError("disco cheio")
        return original(*args, **kwargs)
    monkeypatch.setattr(agente, "_gerar_previas", falha_a_primeira)

    agente.varrer_para_registo(posto, reg, None)
    assert "edital.pdf" in os.listdir(posto["entrada"])
    agente.varrer_para_registo(posto, reg, None)
    _acabou_bem(posto, reg)


def test_o_mesmo_documento_carregado_outra_vez_continua_duplicado(posto):
    """Quem volta a pôr na entrada um documento já recebido não o vê sair de lá.

    É o que sempre aconteceu, e o que separa este caso de uma receção a meio.
    Passa dos dois lados de propósito: fixa o que a recuperação não pode mudar.
    """
    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])
    agente.varrer_para_registo(posto, reg, None)
    shutil.copy(os.path.join(posto["tratados"], "edital.pdf"),
                os.path.join(posto["entrada"], "edital.pdf"))

    assert agente.varrer_para_registo(posto, reg, None) == 0
    assert "edital.pdf" in os.listdir(posto["entrada"])
    assert os.listdir(posto["tratados"]) == ["edital.pdf"]
    assert len(reg.todos()) == 1


def test_um_registo_de_antes_conta_como_recebido_por_inteiro(posto):
    """Um rascunho gravado por uma versão anterior não se distingue de um
    duplicado, e fica como estava. Contra o código anterior falha: o campo não
    existia."""
    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])
    agente.varrer_para_registo(posto, reg, None)
    with open(posto["registo_entrada"], encoding="utf-8") as f:
        dados = json.load(f)
    del dados["editais"][0]["rececao_concluida"]
    with open(posto["registo_entrada"], "w", encoding="utf-8") as f:
        json.dump(dados, f)
    shutil.copy(os.path.join(posto["tratados"], "edital.pdf"),
                os.path.join(posto["entrada"], "edital.pdf"))

    reg = reg_mod.RegistoEntrada(posto["registo_entrada"])
    assert reg.todos()[0]["rececao_concluida"] is True
    agente.varrer_para_registo(posto, reg, None)
    assert "edital.pdf" in os.listdir(posto["entrada"])
