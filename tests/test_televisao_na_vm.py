"""
test_televisao_na_vm.py — O nginx da VM consegue ler o que a televisão pede.

Na VM a página da televisão é servida pelo nginx, que corre com outro
utilizador que não o do agente. O index.html e o slides.json gravam-se por
temporário e troca, e o mkstemp cria o temporário em 0600: a televisão recebia
403 a cada pedido, e o expositor ficava sem editais sem que o agente desse por
nada. Num posto Windows, com o http.server do mesmo utilizador, não se via.
"""
from __future__ import annotations

import os
import stat

import pytest

import agente
import armazenamento as arm

pytestmark = pytest.mark.skipif(os.name == "nt", reason="permissões POSIX")


def _modo(caminho):
    return stat.S_IMODE(os.stat(caminho).st_mode)


def test_a_pagina_e_os_slides_ficam_legiveis_por_outro_utilizador(tmp_path):
    cfg = dict(agente.CONFIG, saida=str(tmp_path))
    agente._escrever_pagina_tv(cfg, [])
    for nome in ("index.html", "slides.json"):
        assert _modo(tmp_path / nome) & 0o044 == 0o044, f"{nome} não é legível pelo nginx"


def test_o_registo_continua_so_do_agente(tmp_path):
    """Fixa o que não pode mudar: o modo é só para a televisão, e o registo e as
    contas continuam no 0600 do mkstemp. Passa dos dois lados de propósito."""
    caminho = tmp_path / "registo.json"
    arm.gravar_json(str(caminho), {"a": 1}, geracoes=0)
    assert _modo(caminho) == 0o600
