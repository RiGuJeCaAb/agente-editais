"""
test_limites_do_ecra.py — A folha encontra os limites do ecrã.

A televisão encolhia um retângulo de 3840×2160 até ele caber no ecrã, com um
`min()` dos dois rácios. Num ecrã 16:9 isso é exatamente certo. Em qualquer
outro punha o desenho inteiro — folha, logótipo e tudo — numa faixa ao meio,
com o ecrã a sobrar de ambos os lados. Medido num monitor vertical de
1080×1920: a folha ocupava 7,7% do ecrã e sobravam 37,8% acima e 37,6% abaixo,
com o logótipo a flutuar a meio do nada.

O trat.desenho_no_ecra() é a regra que faltava: amplia a caixa que envolve as
folhas até encostar ao espaço disponível, com uma escala só.

O que estes testes protegem, por ordem de gravidade:
  1. num ecrã 16:9 nada muda — é a televisão do átrio, e o que lá está é certo;
  2. nenhuma folha se deforma, em ecrã nenhum;
  3. o logótipo nunca assenta por cima de um edital.
"""
from __future__ import annotations

import pytest
from PIL import Image

import tratamento as trat

# Rácio do logótipo do município, deduzido do próprio código: a faixa reservada
# tem 576 px de largura e acaba em y=215, com a margem de cima em y=67.
RACIO_DO_LOGOTIPO = 576 / 148

A4 = Image.new("RGB", (1785, 2526))
DEITADA = Image.new("RGB", (1920, 1080))

CASOS = {"uma folha vertical": [A4],
         "duas folhas verticais": [A4, A4],
         "tres folhas verticais": [A4, A4, A4],
         "uma pagina deitada": [DEITADA]}

# Ecrãs reais, e não números redondos: o 1280×1024 é o que o Raspberry do posto
# estava a dar à televisão, e o 1080×1920 é o monitor vertical do gabinete.
ECRAS = [(3840, 2160), (1920, 1080), (1280, 1024), (1080, 1920),
         (1200, 1920), (1024, 768), (3440, 1440), (800, 480)]


def desenho(nome, largura, altura, racio=RACIO_DO_LOGOTIPO):
    """O desenho de um dos casos, já reaplicado a um ecrã."""
    caixas = trat.caixas_do_ecra(CASOS[nome])
    return caixas, trat.desenho_no_ecra(caixas, largura, altura, racio)


# ---------------------------------------------------------------------------
# 1. O ecrã 16:9 não se mexe
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", list(CASOS))
@pytest.mark.parametrize("largura,altura", [(3840, 2160), (1920, 1080), (1280, 720)])
def test_em_16_9_o_desenho_sai_tal_como_entrou(nome, largura, altura):
    """A televisão do átrio é 16:9. Esta peça não lhe pode tocar.

    Não é feliz coincidência: as três faixas que delimitam o espaço disponível
    SÃO as do palco, ditas em frações, e por isso a ampliação dá exatamente 1.
    A meia tolerância é a única diferença real — o palco centrava com divisão
    inteira (`//2`) e aqui centra-se com números reais, o que acerta melhor.
    """
    caixas, d = desenho(nome, largura, altura)
    escala = largura / trat.CANVAS_W
    esperado = [(x * escala, y * escala, w * escala, h * escala) for x, y, w, h in caixas]
    for obtida, esp in zip(esperado, d["caixas"], strict=True):
        for a, b in zip(obtida, esp, strict=True):
            assert abs(a - b) <= 0.5, f"{nome} em {largura}x{altura}: {d['caixas']}"
    assert abs(d["escala"] - escala) < 1e-9


# ---------------------------------------------------------------------------
# 2. Fora do 16:9 a folha deixa de ser uma ilha
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("largura,altura,area_antes,area_minima", [
    # O monitor vertical do gabinete, que é o caso que deu por isto.
    (1080, 1920, 7.7, 65.0),
    (1200, 1920, 8.5, 60.0),
    # O Raspberry a entregar 5:4 à televisão.
    (1280, 1024, 17.1, 30.0),
    (1024, 768, 18.2, 30.0),
])
def test_fora_do_16_9_a_folha_deixa_de_ser_uma_ilha(largura, altura, area_antes,
                                                    area_minima):
    """Os números do «antes» são os que o browser media, e medem-se aqui com a
    mesma régua: a regra antiga era uma escala só, o menor dos dois rácios."""
    caixas, d = desenho("uma folha vertical", largura, altura)
    k_antigo = min(largura / trat.CANVAS_W, altura / trat.CANVAS_H)
    antes = 100 * (trat.SHEET_W * k_antigo) * (trat.SHEET_H * k_antigo) / (largura * altura)
    assert abs(antes - area_antes) < 0.15, "a régua do «antes» mudou"
    x, y, w, h = d["caixas"][0]
    agora = 100 * w * h / (largura * altura)
    assert agora >= area_minima, f"{agora:.1f}% do ecrã, esperava-se {area_minima}%"
    assert agora > antes


# ---------------------------------------------------------------------------
# 3. Nenhuma folha se deforma
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", list(CASOS))
@pytest.mark.parametrize("largura,altura", ECRAS)
def test_nenhuma_folha_se_deforma(nome, largura, altura):
    """Uma escala só, a mesma nos dois eixos — e por isso não HÁ como deformar.

    Vale o teste mesmo assim: o defeito que o posto reportou primeiro foi
    precisamente uma folha A4 esticada até parecer um quadrado, e essa é a
    única coisa que esta peça nunca pode vir a fazer.
    """
    caixas, d = desenho(nome, largura, altura)
    for antes, agora in zip(caixas, d["caixas"], strict=True):
        assert abs(antes[2] / antes[3] - agora[2] / agora[3]) < 1e-9


@pytest.mark.parametrize("largura,altura", ECRAS)
def test_as_folhas_cabem_no_ecra(largura, altura):
    """Encostar não é transbordar."""
    for nome in CASOS:
        _, d = desenho(nome, largura, altura)
        for x, y, w, h in d["caixas"]:
            assert x >= -0.01 and y >= -0.01, f"{nome} em {largura}x{altura}"
            assert x + w <= largura + 0.01 and y + h <= altura + 0.01


# ---------------------------------------------------------------------------
# 4. O logótipo nunca assenta por cima de um edital
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("racio", [6.0, RACIO_DO_LOGOTIPO, 3.0, 2.0, 1.0, 0.5])
@pytest.mark.parametrize("largura,altura", ECRAS)
def test_o_logotipo_nunca_assenta_sobre_a_folha(racio, largura, altura):
    """O logótipo é uma fração da LARGURA e a faixa é uma fração da ALTURA.

    Num ecrã muito largo os dois afastam-se, e sem esta guarda o logótipo
    descia para cima da primeira folha. Vale a regra de sempre, que já estava
    escrita no ha_espaco_para_o_logotipo: mais vale sem logótipo do que um
    logótipo por cima do texto de um edital — só que aqui há melhor saída, que
    é a faixa crescer.
    """
    _, d = desenho("tres folhas verticais", largura, altura, racio)
    lx, ly, lw, lh = d["logotipo"]
    assert lx >= 0 and ly >= 0
    for _, y, _, _ in d["caixas"]:
        assert y >= ly + lh - 1e-9, f"racio {racio} em {largura}x{altura}"


def test_um_logotipo_tao_largo_como_o_do_municipio_nao_mexe_no_16_9():
    """A faixa só cresce quando precisa, e com este logótipo não precisa."""
    _, com = desenho("uma folha vertical", 3840, 2160, RACIO_DO_LOGOTIPO)
    _, sem = desenho("uma folha vertical", 3840, 2160, None)
    assert abs(com["caixas"][0][1] - trat.SHEET_TOP) <= 0.5
    assert com["caixas"] == sem["caixas"]


def test_um_logotipo_quadrado_empurra_a_folha_para_baixo():
    """O contrário do anterior, para o teste anterior provar alguma coisa."""
    _, quadrado = desenho("uma folha vertical", 3840, 2160, 1.0)
    assert quadrado["caixas"][0][1] > trat.SHEET_TOP + 100


# ---------------------------------------------------------------------------
# 5. Os casos de borda
# ---------------------------------------------------------------------------
def test_um_ecra_sem_folhas_nao_rebenta():
    """A televisão mostra «sem editais» e não um erro de JavaScript."""
    d = trat.desenho_no_ecra([], 1920, 1080, RACIO_DO_LOGOTIPO)
    assert d["caixas"] == [] and d["logotipo"] is None


@pytest.mark.parametrize("largura,altura", [(0, 1080), (1920, 0), (-1, -1)])
def test_um_ecra_de_medidas_impossiveis_nao_rebenta(largura, altura):
    """O innerWidth vem a zero num separador ainda escondido."""
    caixas = trat.caixas_do_ecra(CASOS["uma folha vertical"])
    assert trat.desenho_no_ecra(caixas, largura, altura)["caixas"] == []


def test_a_caixa_da_pagina_deitada_continua_centrada():
    """A página deitada tem caixa própria, e ela também tem de encostar."""
    _, d = desenho("uma pagina deitada", 1080, 1920)
    x, _, w, _ = d["caixas"][0]
    assert abs(x - (1080 - w) / 2) < 0.01
    assert w / 1080 > 0.9, "a deitada é limitada pela largura e devia encostar"
