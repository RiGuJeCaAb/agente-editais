"""
test_orientacao.py — Cada documento no ecrã que lhe serve.

A caixa-folha era só uma, vertical, e tudo era encaixado nela. Um documento
horizontal — printscreen, A4 deitado, mapa — ficava numa faixa fina no meio de
muito branco: 10% da área de um ecrã 4K, contra 24% de um A4 vertical. Numa
televisão vista a seis ou dez metros, esse texto não existe.

Os testes fixam as duas metades: que o horizontal ganha o ecrã, e — tão
importante — que o vertical não mudou nada. A esmagadora maioria dos editais é
vertical, e uma melhoria que estragasse esses seria um mau negócio.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

import tratamento as t


def pagina(largura, altura):
    """Uma página de dimensões dadas, com conteúdo suficiente para não ser branca."""
    im = Image.new("RGB", (largura, altura), (252, 252, 250))
    im.paste(Image.new("RGB", (largura // 2, altura // 2), (40, 44, 50)),
             (largura // 4, altura // 4))
    return im


A4 = (1785, 2525)
PRINTSCREEN = (1920, 1080)
A4_DEITADO = (2525, 1785)


# ---------------------------------------------------------------------------
# Classificação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("dims,horizontal", [
    (A4, False),
    ((2525, 3570), False),          # A3 vertical
    (PRINTSCREEN, True),
    (A4_DEITADO, True),
    ((2560, 1080), True),           # panorama 21:9
    ((2000, 2000), True),           # quadrado: a caixa larga dá-lhe mais área
    ((2000, 2001), False),          # um píxel mais alto do que largo
])
def test_classificacao_por_orientacao(dims, horizontal):
    """Mais largo do que alto (ou igual) vai para a caixa larga."""
    assert t.e_horizontal(pagina(*dims)) is horizontal


# ---------------------------------------------------------------------------
# Agrupamento em ecrãs
# ---------------------------------------------------------------------------
def rotulos(ecras):
    """Descreve os ecrãs como 'H' (horizontal sozinho) ou 'NV' (N verticais)."""
    return ["H" if len(b) == 1 and t.e_horizontal(b[0]) else f"{len(b)}V" for b in ecras]


@pytest.mark.parametrize("dims,esperado", [
    ([A4], ["1V"]),
    ([A4] * 3, ["3V"]),
    ([A4] * 4, ["3V", "1V"]),
    ([A4] * 7, ["3V", "3V", "1V"]),
    ([PRINTSCREEN], ["H"]),
    ([PRINTSCREEN] * 2, ["H", "H"]),                     # nunca se juntam
    ([A4, PRINTSCREEN], ["1V", "H"]),
    ([PRINTSCREEN, A4], ["H", "1V"]),
    ([A4, A4, PRINTSCREEN, A4, A4, A4, A4], ["2V", "H", "3V", "1V"]),
])
def test_agrupamento(dims, esperado):
    """Verticais juntam-se até três; horizontais vão sempre sozinhos."""
    assert rotulos(t.agrupar_ecras([pagina(*d) for d in dims])) == esperado


def test_a_ordem_das_paginas_e_preservada():
    """Um documento não pode sair baralhado por causa do agrupamento."""
    paginas = [pagina(*A4), pagina(*PRINTSCREEN), pagina(*A4)]
    achatado = [p for bloco in t.agrupar_ecras(paginas) for p in bloco]
    assert [id(p) for p in achatado] == [id(p) for p in paginas]


def test_nenhuma_pagina_se_perde():
    """Todas as páginas aparecem exatamente uma vez."""
    paginas = [pagina(*A4) for _ in range(5)] + [pagina(*PRINTSCREEN)]
    achatado = [p for bloco in t.agrupar_ecras(paginas) for p in bloco]
    assert len(achatado) == len(paginas)


def test_documento_vazio():
    """Zero páginas dá zero ecrãs, e não um ecrã vazio."""
    assert t.agrupar_ecras([]) == []


# ---------------------------------------------------------------------------
# Área efetiva — o ponto todo do exercício
# ---------------------------------------------------------------------------
def area_no_ecra(dims, caixa_w, caixa_h):
    """Fração do ecrã 4K que um documento ocupa numa dada caixa, em percentagem."""
    largura, altura = dims
    escala = min(caixa_w / largura, caixa_h / altura)
    return (largura * escala) * (altura * escala) / (t.CANVAS_W * t.CANVAS_H) * 100


@pytest.mark.parametrize("dims,minimo", [
    (PRINTSCREEN, 55),
    (A4_DEITADO, 45),
    ((2560, 1080), 60),
])
def test_horizontal_ganha_area_a_serio(dims, minimo):
    """A caixa larga tem de dar bem mais do que a vertical dava.

    Os limiares não são redondos por acaso: um printscreen passa de 10% para
    60%, e este teste falha se alguém mexer na geometria e voltar a apertá-lo.
    """
    antes = area_no_ecra(dims, t.SHEET_W, t.SHEET_H)
    depois = area_no_ecra(dims, t.LARGA_W, t.LARGA_H)
    assert depois >= minimo, f"a caixa larga só dá {depois:.0f}% (era {antes:.0f}%)"
    assert depois > antes * 2


def test_a_caixa_larga_herda_as_margens_da_vertical():
    """As margens não são inventadas: vêm das que o trio de folhas já produz.

    É o que faz os dois tipos de ecrã parecerem do mesmo sistema em vez de dois
    desenhos diferentes a alternar na rotação.
    """
    assert t.MARGEM_LATERAL == t.sheet_positions(t.MAX_POR_ECRA)[0]
    assert t.LARGA_W == t.CANVAS_W - 2 * t.MARGEM_LATERAL
    assert t.LARGA_H == t.SHEET_H


def test_a_folha_larga_abraca_o_conteudo():
    """Sem barras brancas: a folha é do tamanho do que leva dentro.

    A caixa larga tem rácio 2,19:1 e um printscreen 1,78:1; a diferença são
    quase 700 píxeis que, preenchidos a branco, se leem como defeito.
    """
    x, y, largura, altura = t._caixa_justa(
        pagina(*PRINTSCREEN), t.MARGEM_LATERAL, t.SHEET_TOP, t.LARGA_W, t.LARGA_H)
    assert (largura / altura) == pytest.approx(PRINTSCREEN[0] / PRINTSCREEN[1], abs=0.01)
    assert largura <= t.LARGA_W and altura <= t.LARGA_H
    # Centrada na caixa que lhe estava destinada.
    assert x + largura // 2 == pytest.approx(t.MARGEM_LATERAL + t.LARGA_W // 2, abs=1)


def test_a_folha_larga_nao_tapa_o_logotipo():
    """O logótipo vive na faixa verde de cima, e a folha larga começa abaixo dela.

    Se a folha subisse, o _paste_logo deixaria de o colar (verifica se o canto
    está livre) e os ecrãs horizontais ficavam sem marca — sem erro nenhum,
    apenas em falta.
    """
    _x, y, _w, _h = t._caixa_justa(pagina(*PRINTSCREEN), t.MARGEM_LATERAL,
                                   t.SHEET_TOP, t.LARGA_W, t.LARGA_H)
    logo = t.build_logo("assets/sym_ok.png", "assets/txt_ok.png", out_h=160)
    largura_logo = int(t.CANVAS_W * 0.150)
    altura_logo = round(logo.size[1] * largura_logo / logo.size[0])
    topo_logo = int(t.CANVAS_W * 0.032 * 0.55)
    assert topo_logo + altura_logo < y, "a folha larga sobe até ao logótipo"


# ---------------------------------------------------------------------------
# Composição
# ---------------------------------------------------------------------------
def test_compor_horizontal_usa_a_caixa_larga(tmp_path):
    """Uma página horizontal sozinha ocupa mais do que a largura de uma folha.

    Mede-se o que ficou desenhado: procura-se a coluna mais à esquerda e mais à
    direita que não sejam fundo verde.
    """
    img = t.compose_sheets([pagina(*PRINTSCREEN)], seed=1, cache_fundos=str(tmp_path))
    a = np.asarray(img)
    # Uma folha é clara; o fundo é verde escuro.
    claro = a.min(axis=2) > 180
    colunas = np.where(claro.any(axis=0))[0]
    assert (colunas.max() - colunas.min()) > t.SHEET_W * 1.8


def test_compor_verticais_nao_mudou(tmp_path):
    """Uma folha vertical continua a ocupar exatamente a caixa de sempre.

    Guarda a promessa que o módulo faz desde o início: 1, 2 ou 3 folhas saem
    todas do mesmo tamanho, para a rotação no ecrã não parecer saltar.
    """
    img = t.compose_sheets([pagina(*A4)], seed=1, cache_fundos=str(tmp_path))
    a = np.asarray(img)
    claro = a.min(axis=2) > 180
    colunas = np.where(claro.any(axis=0))[0]
    linhas = np.where(claro.any(axis=1))[0]
    assert (colunas.max() - colunas.min() + 1) == pytest.approx(t.SHEET_W, abs=2)
    assert (linhas.max() - linhas.min() + 1) == pytest.approx(t.SHEET_H, abs=2)
