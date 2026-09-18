"""
test_armazenamento.py — A durabilidade que o registo público exige.

O cenário que estes testes reproduzem aconteceu de verdade na versão anterior:
truncar o registo a meio (corte de energia durante a gravação) deixava-o
ilegível, e o agente deixava de arrancar. Perdia-se o histórico de quem afixou o
quê — que é precisamente o que um organismo público tem de conseguir mostrar.
"""
from __future__ import annotations

import json
import logging
import os

import armazenamento as arm
import pytest
import registo as reg_mod
from conftest import META_BOA


def test_gravar_e_ler_ida_e_volta(tmp_path):
    """O básico: o que se grava é o que se lê, com acentos intactos."""
    alvo = str(tmp_path / "dados.json")
    dados = {"assunto": "Deliberações com eficácia externa", "n": 17, "lista": [1, 2, 3]}
    arm.gravar_json(alvo, dados)
    assert arm.ler_json(alvo) == dados


def test_nao_deixa_temporarios_para_tras(tmp_path):
    """Depois de gravar, só fica o ficheiro pedido e as suas gerações."""
    alvo = str(tmp_path / "dados.json")
    for i in range(4):
        arm.gravar_json(alvo, {"passagem": i})
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]


def test_guarda_as_geracoes_anteriores(tmp_path):
    """Cada gravação empurra a anterior para .bak.1, .bak.2, .bak.3."""
    alvo = str(tmp_path / "dados.json")
    for i in range(5):
        arm.gravar_json(alvo, {"passagem": i}, geracoes=3)
    assert arm.ler_json(alvo) == {"passagem": 4}
    assert json.loads(open(f"{alvo}.bak.1", encoding="utf-8").read()) == {"passagem": 3}
    assert json.loads(open(f"{alvo}.bak.2", encoding="utf-8").read()) == {"passagem": 2}
    # A quarta geração não existe: o limite é para ser um limite.
    assert not os.path.exists(f"{alvo}.bak.4")


def test_recupera_de_um_ficheiro_truncado(tmp_path, caplog):
    """Um principal cortado a meio faz recuar para a cópia, e avisa.

    Esta é a reprodução exata da falha original. O aviso é verificado no registo
    técnico e já não na consola: desde a Onda 2 o agente usa logging, e um aviso
    que não chegasse ao ficheiro seria um aviso que ninguém leria no dia em que
    fizesse falta.
    """
    alvo = str(tmp_path / "registo.json")
    arm.gravar_json(alvo, {"editais": ["bom"], "seq": 1})
    arm.gravar_json(alvo, {"editais": ["bom", "melhor"], "seq": 2})
    # Corte de energia a meio da gravação seguinte:
    with open(alvo, "r+", encoding="utf-8") as f:
        f.truncate(os.path.getsize(alvo) // 2)

    with pytest.raises(json.JSONDecodeError):
        json.load(open(alvo, encoding="utf-8"))      # a leitura ingénua rebenta
    with caplog.at_level(logging.WARNING, logger="editais.ARMAZEM"):
        assert arm.ler_json(alvo, {}) == {"editais": ["bom"], "seq": 1}   # a nossa, não
    assert any("ilegível" in r.message for r in caplog.records)


def test_ficheiro_ausente_devolve_a_omissao(tmp_path):
    """Primeira execução: sem ficheiro, devolve-se o valor por omissão."""
    assert arm.ler_json(str(tmp_path / "nunca-existiu.json"), {"editais": []}) == {"editais": []}


def test_o_registo_sobrevive_a_gravacao_interrompida(tmp_path):
    """O RegistoEntrada arranca mesmo com o ficheiro principal partido.

    O teste anterior prova o módulo; este prova que o registo o usa. Antes, o
    __init__ rebentava e o agente não subia de todo.
    """
    caminho = str(tmp_path / "registo_entrada.json")
    r1 = reg_mod.RegistoEntrada(caminho)
    r1.criar_rascunho(ficheiro_origem="a.pdf", hash_ficheiro="h1",
                      num_paginas=1, meta=dict(META_BOA))
    r1.criar_rascunho(ficheiro_origem="b.pdf", hash_ficheiro="h2",
                      num_paginas=1, meta=dict(META_BOA))
    with open(caminho, "r+", encoding="utf-8") as f:
        f.truncate(os.path.getsize(caminho) // 2)

    r2 = reg_mod.RegistoEntrada(caminho)     # não pode levantar exceção
    assert len(r2.todos()) >= 1
    assert r2.todos()[0]["ficheiro_origem"] == "a.pdf"


def test_jornal_acrescenta_e_nunca_reescreve(tmp_path):
    """O jornal só cresce: cada evento é uma linha nova, as anteriores ficam."""
    j = arm.JornalAuditoria(str(tmp_path / "auditoria.jsonl"))
    for i in range(3):
        j.registar({"em": f"2026-09-18T10:0{i}:00", "para": "publicado", "n": i})
    assert [e["n"] for e in j.ler_tudo()] == [0, 1, 2]
    assert len(open(j.caminho, encoding="utf-8").read().strip().splitlines()) == 3


def test_jornal_tolera_a_ultima_linha_cortada(tmp_path):
    """Uma linha truncada custa um evento, não o jornal inteiro.

    É a vantagem do formato linha-a-linha sobre um documento JSON único: o pior
    caso de um corte de energia é perder o último evento.
    """
    j = arm.JornalAuditoria(str(tmp_path / "auditoria.jsonl"))
    for i in range(3):
        j.registar({"n": i})
    with open(j.caminho, "a", encoding="utf-8") as f:
        f.write('{"n": 3, "utilizad')     # a máquina morreu aqui
    assert [e["n"] for e in j.ler_tudo()] == [0, 1, 2]


def test_jornal_ausente_le_como_vazio(tmp_path):
    """Antes do primeiro evento, o jornal é uma lista vazia e não um erro."""
    assert arm.JornalAuditoria(str(tmp_path / "ainda-nada.jsonl")).ler_tudo() == []
