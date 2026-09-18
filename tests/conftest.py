"""Peças partilhadas pelos testes."""
from __future__ import annotations

import pytest
import registo as reg_mod

META_BOA = {
    "assunto": "DELIBERAÇÕES DA ASSEMBLEIA MUNICIPAL COM EFICÁCIA EXTERNA",
    "numero": "2026-0017",
    "entidade": "ASSEMBLEIA MUNICIPAL",
    "data_publicacao": "2026-06-29",
    "confianca": {"assunto": 0.9, "numero": 0.95, "data_publicacao": 0.9},
}


@pytest.fixture
def registo(tmp_path):
    """Um registo de entrada vazio, em pasta temporária e descartável."""
    return reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))


@pytest.fixture
def rascunho(registo):
    """Um edital acabado de entrar, em estado rascunho."""
    return registo.criar_rascunho(ficheiro_origem="edital_17.pdf", hash_ficheiro="abc123",
                                  num_paginas=2, meta=dict(META_BOA))


@pytest.fixture
def publicado(registo, rascunho):
    """Um edital que já percorreu o fluxo todo e está no ecrã."""
    registo.mover_estado(rascunho["id"], reg_mod.VALIDADO, utilizador="ana.abreu")
    registo.mover_estado(rascunho["id"], reg_mod.PUBLICADO, utilizador="ana.abreu")
    return registo.por_id(rascunho["id"])
