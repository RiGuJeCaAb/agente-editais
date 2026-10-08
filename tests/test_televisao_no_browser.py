"""
test_televisao_no_browser.py — A página da televisão aberta num browser.

A página da televisão é o produto desta aplicação, e até aqui nenhum teste a
abria: verificava-se o HTML por pesquisa de texto. Foi assim que passou o
defeito que esta peça corrige — a folha a ocupar 7,7% de um monitor vertical —
sem que uma única linha de teste ficasse vermelha.

Estes testes abrem a página num Chromium, medem o que lá está DESENHADO e
comparam-no com o trat.desenho_no_ecra(), que é onde a regra está escrita. O JS
da página é uma transcrição dessa função; isto é o que prova que a transcrição
é fiel, em vez de se confiar nela.

Marcados `navegador` porque precisam do playwright, que não é dependência de
execução do agente. Ficam de fora do `pytest` por omissão e correm no trabalho
próprio da integração contínua. Correr à mão:

    pip install playwright && playwright install chromium
    pytest -m navegador
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import socketserver
import threading

import pytest
from PIL import Image

import agente
import tratamento as trat

pytestmark = pytest.mark.navegador
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="o playwright não está instalado").sync_playwright

RACIO_DO_LOGOTIPO = 576 / 148
LOGOTIPO = (576, 148)
A4 = (1785, 2526)
DEITADA = (1920, 1080)

CASOS = [("uma folha vertical", [A4]),
         ("tres folhas verticais", [A4, A4, A4]),
         ("uma pagina deitada", [DEITADA])]

ECRAS = [(3840, 2160), (1920, 1080), (1280, 1024), (1080, 1920), (1024, 768),
         (3440, 1440)]

# Pede ao browser o que está DESENHADO, e não o que o CSS diz.
MEDIR = """(n) => {
  const s = document.getElementsByClassName('slide')[n];
  const r = el => { const b = el.getBoundingClientRect();
    return [+b.x.toFixed(3), +b.y.toFixed(3), +b.width.toFixed(3), +b.height.toFixed(3)]; };
  const m = s.getElementsByClassName('marca')[0];
  return {folhas: [...s.getElementsByClassName('folha')].map(r),
          marca: m ? r(m) : null, vp: [innerWidth, innerHeight]};
}"""


def _html():
    """O index.html que o agente publica — o mesmo, e não uma cópia da receita.

    A primeira versão repetia aqui as sete substituições. Media, portanto, uma
    página que ninguém publica: trocar dois marcadores entre si no agente
    passava-lhe ao lado, porque este lado estava certo. Apanhado na revisão da
    PR, e corrigido pela raiz — há agora uma só função que monta a página.
    """
    return agente.pagina_da_tv({"titulo_tv": "Testes", "segundos_por_ecra": 600})


@pytest.fixture(scope="module")
def expositor(tmp_path_factory):
    """Uma pasta de saída servida por HTTP, com os três casos num só slides.json.

    Servida e não aberta em file://: a página busca o slides.json por fetch, e
    um fetch a partir de file:// é recusado pelo browser — o que daria uma
    televisão vazia e um teste a falhar por razão errada.
    """
    pasta = tmp_path_factory.mktemp("expositor")
    (pasta / "index.html").write_text(_html(), encoding="utf-8")
    Image.new("RGBA", LOGOTIPO, (200, 168, 75, 255)).save(pasta / "logotipo.png")
    for nome, tam in (("a4.png", A4), ("dt.png", DEITADA)):
        Image.new("RGB", tam, "white").save(pasta / nome)

    slides = []
    for nome, tamanhos in CASOS:
        paginas = [Image.new("RGB", t) for t in tamanhos]
        caixas = trat.caixas_do_ecra(paginas)
        src = "dt.png" if tamanhos == [DEITADA] else "a4.png"
        slides.append({"assunto": nome, "pub": "2026-10-08", "ecra": {
            "folhas": [{"src": src, "x": x, "y": y, "w": w, "h": h}
                       for x, y, w, h in caixas],
            "logotipo": trat.ha_espaco_para_o_logotipo(
                caixas, Image.new("RGBA", LOGOTIPO))}})
    (pasta / "slides.json").write_text(json.dumps(
        {"versao": "1", "spe": 600, "titulo": "Testes", "v": "1", "gerado_em": "1",
         "slides": slides}), encoding="utf-8")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(pasta))
    socketserver.TCPServer.allow_reuse_address = True
    servidor = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}/index.html"
    servidor.shutdown()


@pytest.fixture(scope="module")
def browser():
    """Um Chromium só, para os testes todos: arrancar um por teste levava minutos.

    O CHROMIUM_PARA_TESTES aponta para um Chromium já instalado, para estes
    testes poderem correr onde o `playwright install` não pode ir buscar o seu.
    Sem a variável usa-se o do playwright, que é o caso da integração contínua.
    """
    executavel = os.environ.get("CHROMIUM_PARA_TESTES") or None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=executavel)
        yield b
        b.close()


def _medidas(browser, url, largura, altura):
    """Abre a televisão num ecrã destas medidas e devolve o que está desenhado."""
    pagina = browser.new_page(viewport={"width": largura, "height": altura})
    try:
        pagina.goto(url)
        # O ecrã de arranque pede um toque antes de a apresentação começar.
        pagina.click("#arranque", timeout=5000)
        pagina.wait_for_selector(".slide.ativo .folha", timeout=5000)
        # O logótipo muda a faixa de cima, e só depois de carregar.
        pagina.wait_for_function(
            "() => [...document.getElementsByClassName('marca')]"
            ".every(m => m.complete && m.naturalWidth > 0)", timeout=5000)
        return [pagina.evaluate(MEDIR, n) for n in range(len(CASOS))]
    finally:
        pagina.close()


@pytest.mark.parametrize("largura,altura", ECRAS)
def test_o_que_o_browser_desenha_e_o_que_o_python_manda(browser, expositor,
                                                        largura, altura):
    """O JS da página é uma transcrição do trat.desenho_no_ecra(). Isto prova-o.

    Até meio píxel, que é o arredondamento de layout do browser. Medido: o
    desvio real fica em dois centésimos de píxel.
    """
    for medido, (nome, tamanhos) in zip(_medidas(browser, expositor, largura, altura),
                                        CASOS, strict=True):
        assert medido["vp"] == [largura, altura], "o viewport não é o pedido"
        caixas = trat.caixas_do_ecra([Image.new("RGB", t) for t in tamanhos])
        esperado = trat.desenho_no_ecra(caixas, largura, altura, RACIO_DO_LOGOTIPO)
        for obtida, esp in zip(medido["folhas"], esperado["caixas"], strict=True):
            for a, b in zip(obtida, esp, strict=True):
                assert abs(a - b) <= 0.5, f"{nome} em {largura}x{altura}"
        if medido["marca"]:
            for a, b in zip(medido["marca"], esperado["logotipo"], strict=True):
                assert abs(a - b) <= 0.5, f"logótipo em {largura}x{altura}"


@pytest.mark.parametrize("largura,altura", [(3840, 2160), (1920, 1080)])
def test_num_ecra_16_9_a_televisao_desenha_o_palco_de_sempre(browser, expositor,
                                                             largura, altura):
    """A televisão do átrio é 16:9, e esta peça não lhe pode ter tocado.

    Compara-se com o caixas_do_ecra() — o desenho do palco — e não com a função
    nova, para o teste não ser circular.
    """
    escala = largura / trat.CANVAS_W
    for medido, (nome, tamanhos) in zip(_medidas(browser, expositor, largura, altura),
                                        CASOS, strict=True):
        caixas = trat.caixas_do_ecra([Image.new("RGB", t) for t in tamanhos])
        for desenhada, (x, y, w, h) in zip(medido["folhas"], caixas, strict=True):
            for a, b in zip(desenhada, (x * escala, y * escala,
                                        w * escala, h * escala), strict=True):
                assert abs(a - b) <= 0.5, f"{nome} em {largura}x{altura}"


@pytest.mark.parametrize("largura,altura", ECRAS)
def test_a_folha_nunca_sai_deformada(browser, expositor, largura, altura):
    """O primeiro defeito que o posto reportou foi uma A4 esticada a quadrado."""
    for medido, (nome, tamanhos) in zip(_medidas(browser, expositor, largura, altura),
                                        CASOS, strict=True):
        caixas = trat.caixas_do_ecra([Image.new("RGB", t) for t in tamanhos])
        for (_, _, w, h), caixa in zip(medido["folhas"], caixas, strict=True):
            assert abs(w / h - caixa[2] / caixa[3]) < 0.002, f"{nome} {largura}x{altura}"


@pytest.mark.parametrize("largura,altura", [(1080, 1920), (1280, 1024)])
def test_fora_do_16_9_a_folha_passa_a_usar_o_ecra(browser, expositor, largura, altura):
    """É o defeito que o posto reportou, visto do lado do browser.

    O «antes» mede-se com a mesma régua: a regra antiga era uma escala só, o
    menor dos dois rácios, aplicada ao palco inteiro.
    """
    antigo = min(largura / trat.CANVAS_W, altura / trat.CANVAS_H)
    antes = (trat.SHEET_W * antigo) * (trat.SHEET_H * antigo)
    _, _, w, h = _medidas(browser, expositor, largura, altura)[0]["folhas"][0]
    assert w * h > 2 * antes, f"{w * h / antes:.1f}x — esperava-se mais do dobro"


def test_o_logotipo_assenta_onde_o_arquivo_o_poe(browser, expositor):
    """Trinta píxeis, medidos, entre onde o logótipo se via e onde ficava provado.

    O CSS tinha `top:1.76%`, e uma percentagem de `top` resolve-se sobre a
    ALTURA do elemento que a contém; o 0,0176 do Python nasceu de multiplicar a
    margem pela LARGURA. Num ecrã 4K dava y=38 na televisão e y=67,6 na imagem
    que ficava no arquivo.

    E o arquivo mede-se MESMO, em píxeis da imagem composta, em vez de se
    recalcular das constantes. A primeira versão comparava o browser com uma
    conta feita aqui a partir do tratamento: uma regressão que mexesse no
    _paste_logo e deixasse o browser quieto passava-lhe ao lado, apesar de o
    teste se chamar «onde o arquivo o põe». Apanhado na revisão da PR.
    """
    marca = _medidas(browser, expositor, 3840, 2160)[0]["marca"]
    arquivo = _logotipo_na_composicao()
    for i, eixo in enumerate(("x", "y", "largura")):
        assert abs(marca[i] - arquivo[i]) <= 1.5, (
            f"{eixo}: a televisão põe o logótipo em {marca[i]:.1f} e o arquivo "
            f"em {arquivo[i]:.1f}")


def _logotipo_na_composicao():
    """Onde é que a composição do arquivo assenta o logótipo, medido em píxeis.

    Compõe um ecrã com um logótipo de uma cor que o fundo verde não tem e
    procura essa cor na imagem. É a posição real, não a que as constantes dizem.
    """
    import numpy as np
    ROXO = (170, 40, 200)
    logo = Image.new("RGBA", LOGOTIPO, ROXO + (255,))
    composto = trat.compose_sheets([Image.new("RGB", A4, "white")], logo_im=logo)
    a = np.array(composto.convert("RGB")).astype(int)
    dele = ((abs(a[:, :, 0] - ROXO[0]) < 12) & (abs(a[:, :, 1] - ROXO[1]) < 12)
            & (abs(a[:, :, 2] - ROXO[2]) < 12))
    assert dele.any(), "o logótipo não aparece na composição do arquivo"
    ys, xs = np.nonzero(dele)
    return (float(xs.min()), float(ys.min()), float(xs.max() - xs.min() + 1))


@pytest.mark.parametrize("largura,altura", ECRAS)
def test_o_logotipo_nunca_tapa_a_primeira_folha(browser, expositor, largura, altura):
    """Mais vale sem logótipo do que um logótipo por cima do texto de um edital."""
    for medido, (nome, _) in zip(_medidas(browser, expositor, largura, altura),
                                 CASOS, strict=True):
        if not medido["marca"]:
            continue
        _, my, _, mh = medido["marca"]
        for _, y, _, _ in medido["folhas"]:
            assert y >= my + mh - 0.5, f"{nome} em {largura}x{altura}"
