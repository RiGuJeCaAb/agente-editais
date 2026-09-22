"""
test_visor_paginas.py — O painel mostra o documento todo, não a primeira folha.

O defeito: `fontePrevia()` devolvia `ficheiros_previa[0]` e mais nada. As
pré-visualizações das outras páginas eram geradas, guardadas e servidas — e o
painel ignorava-as. Não havia setas, nem contador, nem forma de lá chegar.

Não é cosmética. A vista de validação é o único ecrã onde uma pessoa confere o
que vai afixar, e mostrava-lhe a primeira página de um documento com cinco. Ao
publicar, a aplicação emite uma certidão com o nome dessa pessoa a dizer que foi
ela que afixou aquele edital. Estava-se a certificar o que não se tinha visto.

O que este ficheiro consegue e não consegue provar
--------------------------------------------------
Isto é análise estática do painel.html: garante que a forma exata do defeito não
volta — indexar a primeira página, ou um dos dois sítios de desenho ficar para
trás numa alteração futura. NÃO prova que o visor funciona no browser; isso
verifica-se a olho, e as provas ficam em docs/ quando as houver.

Vale a pena na mesma: o defeito nasceu de uma linha com `[0]`, e é exatamente
essa linha que este ficheiro não deixa voltar.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
PAINEL = (LIB / "painel.html").read_text(encoding="utf-8")


def test_nao_se_indexa_a_primeira_previa():
    """A forma literal do defeito, proibida."""
    assert "ficheiros_previa[0]" not in PAINEL
    assert "ficheiros_png[0]" not in PAINEL


def test_as_paginas_vem_todas():
    """paginasDe mapeia a lista inteira em vez de escolher uma."""
    assert re.search(r"r\.ficheiros_previa\.map\(", PAINEL), "as prévias não são mapeadas todas"
    assert re.search(r"r\.ficheiros_png\.map\(", PAINEL), "os PNG não são mapeados todos"


@pytest.mark.parametrize("peca", [
    "function paginasDe(",
    "function visorHTML(",
    "function ligarVisor(",
])
def test_o_visor_existe(peca):
    assert peca in PAINEL


def test_os_dois_sitios_usam_o_mesmo_visor():
    """Havia duas cópias do mesmo bloco de pré-visualização, e é assim que uma
    correção passa a existir num sítio e não no outro. Agora é uma função só,
    chamada na vista de foco (validar) e na de detalhe (um edital já publicado)."""
    # "const previa=visorHTML(" e não "visorHTML(" — este último apanharia
    # também a definição da função e o teste passaria a contar o que não é chamada.
    assert PAINEL.count("const previa=visorHTML(r,") == 2, \
        "os dois sítios de desenho têm de chamar visorHTML"
    assert PAINEL.count("ligarVisor(") == 3, "a definição mais as duas chamadas"


def test_ha_como_navegar_entre_paginas():
    """Botões, miniaturas e contador: o problema não era só chegar às outras
    páginas, era não se saber que existiam."""
    assert 'id="pgPrev"' in PAINEL
    assert 'id="pgNext"' in PAINEL
    assert "visor-tiras" in PAINEL
    assert "data-pagina=" in PAINEL


def test_as_setas_verticais_mudam_de_pagina():
    """Horizontal entre documentos, vertical dentro do documento."""
    assert "e.key==='ArrowDown'" in PAINEL
    assert "e.key==='ArrowUp'" in PAINEL


def test_a_dica_de_atalhos_menciona_as_paginas():
    """Um atalho que ninguém sabe que existe não existe."""
    assert "↑ ↓ página" in PAINEL


def test_o_numero_de_paginas_aparece_na_ficha():
    """Na lista, antes sequer de abrir: é a metade da descoberta."""
    assert "<span>Páginas</span>" in PAINEL
