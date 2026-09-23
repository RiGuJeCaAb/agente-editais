"""
test_streaming.py — Ler o documento aos bocados, sem mudar um píxel do que sai.

A leitura carregava todas as páginas rasterizadas de uma vez. Medido a sério,
custava ~18 MB por página, linear e sem tecto: 50 páginas pediam 903 MB e 100
pediam quase 2 GB. Num portátil de serviço isso não é lentidão, é o processo a
morrer — e morre no documento grande, que é o que ninguém quer ter de repetir.

Quem consome as páginas nunca precisou delas todas ao mesmo tempo: a ingestão faz
uma pré-visualização por página e deita a página fora; a composição junta até
três num ecrã e passa ao seguinte. A peça que torna isto possível é o tamanho de
cada página sair do PDF **sem rasterizar nada** — e é só disso que o agrupamento
por orientação precisa.

O teste que mais importa é o do fim: a composição tem de continuar idêntica ao
píxel. Esta peça é desempenho, e uma melhoria de desempenho que muda o que
aparece na televisão não é uma melhoria.
"""
from __future__ import annotations

import hashlib
import os

import pytest

import documentos as doc
import tratamento as trat

A4 = (595, 842)
DEITADO = (842, 595)


def fazer_pdf(caminho, paginas):
    """Cria um PDF com as páginas pedidas: lista de (largura, altura, texto)."""
    import fitz
    d = fitz.open()
    for larg, alt, txt in paginas:
        p = d.new_page(width=larg, height=alt)
        p.insert_text((60, 120), txt, fontsize=28)
        for i in range(18):
            p.insert_text((60, 180 + i * 16), f"linha {i + 1} do {txt}", fontsize=10)
        p.draw_rect(fitz.Rect(30, 30, larg - 30, alt - 30), width=2)
    d.save(str(caminho))
    d.close()
    return str(caminho)


@pytest.fixture
def cinco_paginas(tmp_path):
    return fazer_pdf(tmp_path / "cinco.pdf", [(*A4, f"pagina {i}") for i in range(1, 6)])


@pytest.fixture
def misto(tmp_path):
    """Verticais e uma deitada pelo meio — o caso que o agrupamento trata."""
    return fazer_pdf(tmp_path / "misto.pdf", [
        (*A4, "v1"), (*A4, "v2"), (*DEITADO, "deitada"), (*A4, "v3")])


# ---------------------------------------------------------------------------
# As dimensões saem sem rasterizar
# ---------------------------------------------------------------------------
def test_as_dimensoes_batem_com_as_da_rasterizacao(cinco_paginas, tmp_path):
    """Se divergissem um píxel, uma página quase quadrada mudava de orientação."""
    dims = doc.dimensoes_das_paginas(cinco_paginas, str(tmp_path))
    reais = [im.size for _i, im in doc.paginas_uma_a_uma(cinco_paginas, str(tmp_path))]
    assert dims == reais


def test_as_dimensoes_veem_a_orientacao_de_cada_pagina(misto, tmp_path):
    dims = doc.dimensoes_das_paginas(misto, str(tmp_path))
    assert [larg > alt for larg, alt in dims] == [False, False, True, False]


def test_uma_imagem_tem_uma_pagina(tmp_path):
    from PIL import Image
    caminho = tmp_path / "cartaz.png"
    Image.new("RGB", (1200, 800), "white").save(caminho)
    assert doc.dimensoes_das_paginas(str(caminho), str(tmp_path)) == [(1200, 800)]


# ---------------------------------------------------------------------------
# A leitura página a página
# ---------------------------------------------------------------------------
def test_as_paginas_vem_todas_e_pela_ordem(cinco_paginas, tmp_path):
    lidas = list(doc.paginas_uma_a_uma(cinco_paginas, str(tmp_path)))
    assert [i for i, _im in lidas] == [0, 1, 2, 3, 4]


def test_com_indices_rasteriza_so_essas(cinco_paginas, tmp_path):
    """É o que permite compor um ecrã sem tocar no resto do documento."""
    lidas = list(doc.paginas_uma_a_uma(cinco_paginas, str(tmp_path), indices=[1, 3]))
    assert [i for i, _im in lidas] == [1, 3]


def test_e_um_gerador_e_nao_uma_lista_disfarcada(cinco_paginas, tmp_path):
    """Se devolvesse uma lista, o ganho de memória não existia.

    Consumir uma página e parar não pode ter rasterizado as outras quatro.
    """
    import types
    g = doc.paginas_uma_a_uma(cinco_paginas, str(tmp_path))
    assert isinstance(g, types.GeneratorType)
    primeira = next(g)
    assert primeira[0] == 0
    g.close()


# ---------------------------------------------------------------------------
# Os metadados sem rasterizar
# ---------------------------------------------------------------------------
def test_os_metadados_saem_sem_paginas(cinco_paginas, tmp_path):
    info = doc.ler_metadados(cinco_paginas, str(tmp_path))
    assert info["paginas"] == 5
    assert info["ocr"] is False
    assert "pagina 1" in info["text"]


def test_o_texto_vem_de_todas_as_paginas(cinco_paginas, tmp_path):
    """O número, a data ou o assunto podem estar em qualquer página."""
    info = doc.ler_metadados(cinco_paginas, str(tmp_path))
    for i in range(1, 6):
        assert f"pagina {i}" in info["text"]


def test_o_mesmo_texto_que_o_caminho_antigo(cinco_paginas, tmp_path):
    """Os metadados extraídos não podem depender de por onde se leu."""
    info = doc.ler_metadados(cinco_paginas, str(tmp_path))
    _pags, texto = doc.to_pages_and_text(cinco_paginas, str(tmp_path))
    assert info["text"] == texto


# ---------------------------------------------------------------------------
# O agrupamento por índices
# ---------------------------------------------------------------------------
def test_agrupar_por_indices_da_o_mesmo_que_por_imagens(misto, tmp_path):
    """Uma segunda cópia da regra era o caminho certo para as duas discordarem."""
    paginas = [im for _i, im in doc.paginas_uma_a_uma(misto, str(tmp_path))]
    por_imagens = trat.agrupar_ecras(paginas)
    por_indices = trat.agrupar_indices([p.size for p in paginas])
    assert [[paginas[i] for i in b] for b in por_indices] == por_imagens


@pytest.mark.parametrize("paginas,esperado", [
    ([A4], [[0]]),
    ([A4, A4], [[0, 1]]),
    ([A4, A4, A4], [[0, 1, 2]]),
    ([A4] * 5, [[0, 1, 2], [3, 4]]),
    ([DEITADO], [[0]]),
    ([A4, DEITADO, A4], [[0], [1], [2]]),
    ([A4, A4, DEITADO, A4], [[0, 1], [2], [3]]),
])
def test_a_regra_de_agrupamento_por_dimensoes(paginas, esperado):
    assert trat.agrupar_indices(paginas) == esperado


# ---------------------------------------------------------------------------
# A garantia: nem um píxel muda
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome,paginas", [
    ("uma_vertical",   [(*A4, "p1")]),
    ("duas_verticais", [(*A4, "p1"), (*A4, "p2")]),
    ("tres_verticais", [(*A4, "p1"), (*A4, "p2"), (*A4, "p3")]),
    ("cinco_verticais", [(*A4, f"p{i}") for i in range(1, 6)]),
    ("uma_deitada",    [(*DEITADO, "deitada")]),
    ("misto",          [(*A4, "v1"), (*A4, "v2"), (*DEITADO, "h"), (*A4, "v3")]),
])
def test_a_composicao_em_streaming_e_identica_ao_bit(nome, paginas, tmp_path):
    """Esta peça é desempenho. Uma melhoria de desempenho que muda o que aparece
    na televisão não é uma melhoria — é uma regressão com um gráfico bonito.

    Compara o caminho novo (dimensões primeiro, rasterizar só o ecrã que se
    compõe) com o antigo (documento todo em memória), imagem a imagem, pelo
    resumo do PNG.
    """
    caminho = fazer_pdf(tmp_path / f"{nome}.pdf", paginas)
    fundos = str(tmp_path / "fundos")
    os.makedirs(fundos, exist_ok=True)

    # Caminho ANTIGO: tudo em memória.
    todas, _ = doc.to_pages_and_text(caminho, str(tmp_path))
    antigos = []
    for i, bloco in enumerate(trat.agrupar_ecras(todas), 1):
        comp = trat.compose_sheets(bloco, seed=3 + i, logo_im=None, cache_fundos=fundos)
        f = tmp_path / f"antigo_{i}.png"
        comp.save(f, "PNG")
        antigos.append(hashlib.sha256(f.read_bytes()).hexdigest())

    # Caminho NOVO: dimensões, agrupar, rasterizar só o ecrã.
    dims = doc.dimensoes_das_paginas(caminho, str(tmp_path))
    novos = []
    for i, bloco in enumerate(trat.agrupar_indices(dims), 1):
        pags = [im for _j, im in
                doc.paginas_uma_a_uma(caminho, str(tmp_path), indices=bloco)]
        comp = trat.compose_sheets(pags, seed=3 + i, logo_im=None, cache_fundos=fundos)
        f = tmp_path / f"novo_{i}.png"
        comp.save(f, "PNG")
        novos.append(hashlib.sha256(f.read_bytes()).hexdigest())

    assert novos == antigos, f"{nome}: a composição mudou"
