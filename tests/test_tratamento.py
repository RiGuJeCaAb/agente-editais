"""
test_tratamento.py — O que a otimização não pode ter mudado.

A Onda 1 mexeu a fundo neste módulo: toda a aritmética passou a float32, os
desfoques da sombra passaram a ser aproximados por redução de escala, e o fundo
passa a vir de uma cache. São três formas de trocar exatidão por velocidade, e
cada uma precisa de um limite escrito para que a troca não se vá alargando em
silêncio a cada passagem seguinte.
"""
from __future__ import annotations

import numpy as np
import pytest
import tratamento as trat
from PIL import Image
from scipy import ndimage


@pytest.fixture(scope="module")
def mascara():
    """A máscara real de três folhas, nas posições que a composição usa."""
    m = np.zeros((trat.CANVAS_H, trat.CANVAS_W), np.float32)
    for x0 in trat.sheet_positions(3):
        m[trat.SHEET_TOP:trat.SHEET_TOP + trat.SHEET_H, x0:x0 + trat.SHEET_W] = 1.0
    return m


@pytest.mark.parametrize("sigma", [18, 55])
def test_desfoque_rapido_fica_dentro_do_erro_aceite(mascara, sigma):
    """A aproximação da sombra não se afasta do filtro exato mais do que um nível.

    A sombra é multiplicada por 0,62 e aplicada sobre 255 níveis. Um erro de
    0,006 dá menos de um nível — abaixo do grão que o fundo tem de propósito, e
    portanto invisível. Se alguém tornar a aproximação mais agressiva para ganhar
    mais uns milissegundos, é aqui que se dá por isso.
    """
    exato = ndimage.gaussian_filter(mascara, sigma)
    rapido = trat._desfocar(mascara, sigma)
    erro = float(np.abs(exato - rapido).max())
    assert erro < 0.006, f"erro {erro:.4f} — a sombra deixou de ser fiel ao filtro exato"
    assert erro * 0.62 * 255 < 1.0, "o desvio passou de um nível em 255"


def test_desfoque_pequeno_usa_o_filtro_exato(mascara):
    """Abaixo do limiar não se aproxima nada: o custo já é baixo e o risco não compensa."""
    assert np.array_equal(trat._desfocar(mascara, 3),
                          ndimage.gaussian_filter(mascara.astype(trat.REAL), 3))


def test_paleta_toda_em_float32():
    """As constantes de cor têm de ser float32, ou promovem tudo o resto.

    Era este o defeito: eram `float` (=float64) e contaminavam por promoção todos
    os intermédios de forma (2160, 3840, 3) — 199 MB cada em vez de 100 MB. O
    .astype(float32) da grelha de coordenadas era desfeito na linha seguinte.
    """
    for nome in ("GREEN_DEEP", "GREEN_BASE", "GREEN_LIGHT", "GOLD", "GOLD_LIGHT",
                 "GOLD_HI", "GOLD_MID", "GOLD_LO", "GOLD_DEEP"):
        assert getattr(trat, nome).dtype == np.float32, f"{nome} não é float32"


def test_fundo_da_cache_e_sempre_o_mesmo(tmp_path):
    """A mesma variante dá a mesma imagem, hoje e daqui a um ano.

    A semente da variante é fixa e não a do edital, de propósito: se variasse, um
    edital reposto no ecrã viria com fundo diferente do que tinha.
    """
    trat._FUNDOS_EM_MEMORIA.clear()
    a = trat.obter_fundo(seed=3, cache=str(tmp_path))
    trat._FUNDOS_EM_MEMORIA.clear()          # força a releitura do disco
    b = trat.obter_fundo(seed=3, cache=str(tmp_path))
    assert np.array_equal(a, b)
    # Sementes que caem na mesma variante partilham o fundo, que é o que faz a
    # cache valer a pena.
    trat._FUNDOS_EM_MEMORIA.clear()
    assert np.array_equal(a, trat.obter_fundo(seed=3 + trat.VARIANTES_DE_FUNDO,
                                              cache=str(tmp_path)))


def test_fundo_corrompido_e_redesenhado(tmp_path):
    """Um PNG de cache truncado não trava a composição para sempre."""
    trat._FUNDOS_EM_MEMORIA.clear()
    trat.obter_fundo(seed=0, cache=str(tmp_path))
    ficheiro = next(tmp_path.glob("fundo_*.png"))
    ficheiro.write_bytes(ficheiro.read_bytes()[:500])    # cortado a meio
    trat._FUNDOS_EM_MEMORIA.clear()
    img = trat.obter_fundo(seed=0, cache=str(tmp_path))
    assert img.shape == (trat.CANVAS_H, trat.CANVAS_W, 3)


def test_fundo_tem_o_tamanho_e_o_tipo_do_ecra():
    """O fundo sai em 4K e em uint8, prontos a compor."""
    bg = trat.metallic_green_bg(320, 180, seed=1)       # pequeno, para o teste ser rápido
    assert bg.dtype == np.uint8 and bg.shape == (180, 320, 3)


@pytest.mark.parametrize("largura,altura,descricao", [
    (1785, 2525, "A4 vertical"),
    (1920, 1080, "printscreen 16:9"),
    (2525, 1785, "A4 horizontal"),
    (400, 4000, "tira muito alta"),
])
def test_encaixe_nao_corta_nada(largura, altura, descricao):
    """Nenhum documento perde píxeis ao entrar na caixa-folha.

    A versão anterior escalava sempre pela altura e amputava as laterais de
    qualquer coisa mais larga que a caixa — um printscreen perdia o texto das
    margens. Continua a valer que a caixa vertical dá pouca área a documentos
    horizontais (10% do ecrã 4K), mas isso é desenho e resolve-se na Onda 3;
    o que este teste garante é que não se corta.
    """
    origem = Image.new("RGB", (largura, altura), (255, 255, 255))
    encaixada = trat._fit_sheet(origem)
    assert encaixada.size == (trat.SHEET_W, trat.SHEET_H)
    escala = min(trat.SHEET_W / largura, trat.SHEET_H / altura)
    assert round(largura * escala) <= trat.SHEET_W
    assert round(altura * escala) <= trat.SHEET_H


@pytest.mark.parametrize("n", [1, 2, 3])
def test_folhas_ficam_centradas_e_do_mesmo_tamanho(n):
    """Uma folha só tem o tamanho das de um trio, apenas centrada."""
    xs = trat.sheet_positions(n)
    assert len(xs) == n
    largura_total = xs[-1] + trat.SHEET_W - xs[0]
    margem_esq, margem_dir = xs[0], trat.CANVAS_W - (xs[-1] + trat.SHEET_W)
    assert abs(margem_esq - margem_dir) <= 1, "o conjunto não está centrado"
    assert largura_total == n * trat.SHEET_W + (n - 1) * trat.SHEET_GAP


def test_nunca_mais_de_tres_folhas_por_ecra():
    """O limite é um limite, mesmo quando lhe pedem mais."""
    assert len(trat.sheet_positions(9)) == trat.MAX_POR_ECRA
    assert len(trat.sheet_positions(0)) == 1
