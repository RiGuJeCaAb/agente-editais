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


def pagina(largura, altura, cor=None):
    """Uma página de dimensões dadas, com conteúdo suficiente para não ser branca.

    Com `cor`, sai uma página de cor sólida — serve para seguir onde é que ela
    foi parar na composição sem depender do que lá está desenhado.
    """
    if cor is not None:
        return Image.new("RGB", (largura, altura), cor)
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


# ---------------------------------------------------------------------------
# O desenho do ecrã: uma regra só, para dois caminhos
#
# Desde a peça 4 há dois consumidores das mesmas coordenadas: a composição 4K
# em Python, que vai para o arquivo, e o browser da televisão, que posiciona as
# folhas soltas. Se discordassem, o que ficava no arquivo deixava de ser o que
# esteve no ecrã — e o arquivo existe precisamente para provar que foi aquilo.
# ---------------------------------------------------------------------------
def test_a_folha_ajustada_tem_o_tamanho_exacto_da_sua_caixa():
    """É isto que torna a caixa o desenho: quem recebe não tem contas a fazer."""
    paginas = [pagina(1785, 2526) for _ in range(3)]
    for (_x, _y, w, h), folha in t.folhas_do_ecra(paginas):
        assert folha.size == (w, h)


def test_a_composicao_assenta_as_folhas_onde_as_caixas_dizem(tmp_path):
    """Compõe com páginas de cor sólida e confere onde a cor aterrou.

    Fixa a RELAÇÃO entre as duas coisas, e não um resumo do ficheiro: um resumo
    preso a uma versão do Pillow parte na integração contínua sem nada ter
    mudado, e isso ensina a ignorar o teste.
    """
    import numpy as np
    vermelho = pagina(1785, 2526, cor=(255, 0, 0))
    paginas = [vermelho, vermelho, vermelho]
    comp = np.array(t.compose_sheets(paginas, seed=3, logo_im=None,
                                     cache_fundos=str(tmp_path)))
    for x, y, w, h in t.caixas_do_ecra(paginas):
        # O centro da caixa tem de ser vermelho puro...
        r, g, b = comp[y + h // 2, x + w // 2]
        assert (int(r), int(g), int(b)) == (255, 0, 0), f"caixa ({x},{y}) vazia"
        # ...e logo ao lado da caixa já não pode haver folha nenhuma.
        if x > 8:
            assert tuple(comp[y + h // 2, x - 8]) != (255, 0, 0)


def test_uma_deitada_sozinha_recebe_a_caixa_larga():
    caixas = t.caixas_do_ecra([pagina(2526, 1785)])
    assert len(caixas) == 1
    assert caixas[0][2] > t.SHEET_W, "a deitada devia ficar mais larga que a grelha"


# ---------------------------------------------------------------------------
# O logótipo, sem olhar para píxeis
# ---------------------------------------------------------------------------
@pytest.fixture
def logotipo():
    import os
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return t.build_logo(os.path.join(raiz, "assets", "sym_ok.png"),
                        os.path.join(raiz, "assets", "txt_ok.png"))


def test_sem_logotipo_nao_ha_espaco_para_logotipo_nenhum():
    assert t.ha_espaco_para_o_logotipo([(0, 0, 10, 10)], None) is False


@pytest.mark.parametrize("nome,paginas_f", [
    ("uma vertical", lambda: [pagina(1785, 2526)]),
    ("duas verticais", lambda: [pagina(1785, 2526)] * 2),
    ("três verticais", lambda: [pagina(1785, 2526)] * 3),
    ("uma deitada", lambda: [pagina(2526, 1785)]),
])
def test_a_geometria_responde_como_os_pixeis(nome, paginas_f, logotipo, tmp_path):
    """A composição em Python decide olhando para os píxeis da imagem feita; o
    browser não tem imagem para olhar e decide pela geometria. As duas respostas
    têm de bater certo, ou o arquivo fica com logótipo e o ecrã sem ele."""
    import numpy as np
    paginas = paginas_f()
    img = t.compose_sheets(paginas, seed=5, logo_im=None, cache_fundos=str(tmp_path))
    lw, lh = logotipo.size
    tw = int(img.size[0] * 0.150)
    th = int(round(lh * tw / lw))
    mx = int(img.size[0] * 0.032)
    my = int(img.size[0] * 0.032 * 0.55)
    a = np.array(img).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    e_fundo = (g >= r) & (g >= b) & (g - np.minimum(r, b) > 6) & (a.max(axis=2) < 175)
    faixa = e_fundo[my:my + th, mx:mx + tw]
    por_pixeis = not (faixa.size == 0 or faixa.mean() < 0.85)
    assert t.ha_espaco_para_o_logotipo(t.caixas_do_ecra(paginas), logotipo) is por_pixeis


def test_a_guarda_do_logotipo_recusa_quando_a_faixa_esta_tapada(logotipo):
    """Com as medidas de hoje a faixa nunca é tapada — acaba em y=215 e as
    folhas começam em 248 — por isso o caso negativo não se alcança pela porta
    da frente. Exercita-se com caixas inventadas, senão metade da função fica
    por provar e ninguém dá por isso até alguém baixar o SHEET_TOP."""
    assert t.ha_espaco_para_o_logotipo([(0, 0, t.CANVAS_W, t.CANVAS_H)], logotipo) is False
    assert t.ha_espaco_para_o_logotipo([(122, 67, 288, 148)], logotipo) is False
    assert t.ha_espaco_para_o_logotipo([(2000, 600, 1200, 1600)], logotipo) is True


def test_a_faixa_do_logotipo_fica_mesmo_acima_das_folhas(logotipo):
    """O facto que faz a guarda nunca disparar. Se um dia deixar de ser verdade,
    este teste avisa antes de o logótipo aparecer por cima de um edital."""
    lw, lh = logotipo.size
    tw = int(t.CANVAS_W * 0.150)
    fim_da_faixa = int(t.CANVAS_W * 0.032 * 0.55) + int(round(lh * tw / lw))
    assert fim_da_faixa < t.SHEET_TOP
