"""
tratamento.py — Tratamento visual dos editais para o expositor da CMMB.

Este módulo é o "atelier" do agente: pega nas páginas já rasterizadas e produz a
imagem final 16:9 (4K) com a identidade "Força do Interior" do Município:

  1. fundo verde metalizado #0D4D33 (Pantone 3500U) com laivos e pontos dourados;
  2. as folhas/cartazes a "pairar" sobre o fundo, com sombra projetada;
  3. o logótipo dourado com efeito de gravação (relevo 3D) no canto superior esq.

Funciona tanto para folhas brancas (editais) como para cartazes coloridos, e
compõe 1, 2 ou 3 folhas lado a lado — SEMPRE ao mesmo tamanho — para aproveitar
o formato 16:9 sem esticar nada.

Dependências: numpy, pillow, scipy.

Nota sobre a abordagem: quase tudo aqui é feito com operações vetorizadas de
NumPy sobre matrizes de píxeis. É a razão de o código parecer "matemático" — mas
é o que permite tratar imagens 4K em segundos em vez de percorrer píxel a píxel.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image
from scipy import ndimage

# Toda a aritmética de imagem corre em float32, não em float64. Não é
# micro-otimização: as constantes da paleta eram `float` (= float64) e, por
# promoção do NumPy, contaminavam TODOS os intermédios de forma (2160, 3840, 3)
# — 199 MB cada em vez de 100 MB, com vários vivos ao mesmo tempo. O
# `.astype(np.float32)` que existia na grelha de coordenadas era desfeito na
# linha seguinte pela primeira multiplicação com a paleta. Medido: 1325 MB de
# pico só para gerar um fundo.
REAL = np.float32

# ---------------------------------------------------------------------------
# Paleta de marca CMMB. Guardadas como vetores NumPy (R,G,B em float) para poder
# interpolá-las diretamente nas contas de cor mais abaixo.
# ---------------------------------------------------------------------------
GREEN_DEEP  = np.array([5, 38, 24],   REAL)   # verde quase-preto (profundidade)
GREEN_BASE  = np.array([13, 77, 51],  REAL)   # #0D4D33 — a cor de marca
GREEN_LIGHT = np.array([46, 130, 88], REAL)   # verde iluminado (brilho especular)
GOLD        = np.array([200, 168, 75], REAL)  # #C8A84B — o dourado de marca
GOLD_LIGHT  = np.array([235, 210, 140], REAL) # dourado claro (realces/pontos)

# Paleta específica do relevo do logótipo (gravação): do brilho ao sulco escuro.
GOLD_HI   = np.array([252, 234, 178], REAL)   # face mais iluminada do relevo
GOLD_MID  = np.array([200, 166, 75],  REAL)   # tom médio (corpo do metal)
GOLD_LO   = np.array([138, 104, 40],  REAL)   # zona em sombra
GOLD_DEEP = np.array([70, 50, 18],    REAL)   # fundo do sulco gravado

# Dimensões do ecrã final (16:9 em 4K).
CANVAS_W, CANVAS_H = 3840, 2160

# ---------------------------------------------------------------------------
# Geometria UNIFORME da folha.
# Estes números não são arbitrários: foram medidos nas composições originais de
# 3 folhas (as DDN por freguesia), para que 1, 2 ou 3 folhas fiquem exatamente
# do mesmo tamanho e alinhadas, dando consistência visual à rotação no ecrã.
# ---------------------------------------------------------------------------
SHEET_W, SHEET_H = 1201, 1678   # largura/altura de cada folha no canvas
SHEET_TOP = 248                 # topo das folhas (deixa faixa verde p/ o logótipo)
SHEET_GAP = 37                  # intervalo horizontal entre folhas
MAX_POR_ECRA = 3                # nunca mais de 3 folhas VERTICAIS por ecrã

# ---------------------------------------------------------------------------
# Caixa dos documentos horizontais.
# ---------------------------------------------------------------------------
# A caixa-folha acima é vertical, e era a única que havia. Um documento
# horizontal — um printscreen, um A4 deitado, um mapa — era encaixado nela e
# sobrava-lhe uma faixa fina no meio de muito branco. Medido num ecrã 4K: um
# printscreen Full HD ocupava 10% da área, contra 24% de um A4 vertical. Numa
# televisão vista a seis ou dez metros, esse texto não existe.
#
# A correção é dar-lhe o ecrã inteiro. As margens NÃO são inventadas: herdam-se
# das que o trio de folhas verticais já produz, para os dois tipos de ecrã
# parecerem do mesmo sistema em vez de dois desenhos a alternar.
MARGEM_LATERAL = (CANVAS_W - (MAX_POR_ECRA * SHEET_W
                              + (MAX_POR_ECRA - 1) * SHEET_GAP)) // 2
LARGA_W = CANVAS_W - 2 * MARGEM_LATERAL    # 3678
LARGA_H = SHEET_H                          # 1678, a mesma altura das verticais

# Acima deste rácio largura/altura o documento vai sozinho para a caixa larga.
# 1.0 — isto é, mais largo do que alto — e não um valor mais exigente: mesmo um
# documento quase quadrado ganha o dobro da área na caixa larga, porque na
# vertical é a largura que o limita e na larga é a altura.
RACIO_HORIZONTAL = 1.0


def e_horizontal(pagina) -> bool:
    """Indica se uma página deve ir sozinha para a caixa larga.

    Args:
        pagina (PIL.Image.Image): página já rasterizada.

    Returns:
        bool: True se for mais larga do que alta.
    """
    largura, altura = pagina.size
    return altura > 0 and (largura / altura) >= RACIO_HORIZONTAL


def agrupar_ecras(paginas):
    """Distribui as páginas por ecrãs, respeitando a orientação de cada uma.

    Substitui a divisão cega em blocos de três. As regras:

      - páginas VERTICAIS juntam-se, até três por ecrã, como sempre;
      - uma página HORIZONTAL leva um ecrã só para si, porque é isso que lhe dá
        a área de que precisa para se ler ao longe;
      - a ordem das páginas é preservada, para um documento não sair baralhado.

    Um documento misto — um ofício com um mapa deitado no meio, que acontece —
    fica com os verticais agrupados e o horizontal isolado, na sua vez.

    Args:
        paginas (list[PIL.Image.Image]): páginas na ordem do documento.

    Returns:
        list[list[PIL.Image.Image]]: um bloco por ecrã.
    """
    blocos = agrupar_indices([p.size for p in paginas])
    return [[paginas[i] for i in bloco] for bloco in blocos]


def agrupar_indices(dimensoes):
    """Distribui páginas por ecrãs conhecendo apenas as dimensões de cada uma.

    É a mesma regra de `agrupar_ecras`, a trabalhar sobre (largura, altura) em
    vez de imagens. Existe porque as dimensões de um PDF lêem-se sem rasterizar
    nada: decide-se primeiro o que vai com o quê, e só depois se rasteriza — e só
    as páginas do ecrã que se está a compor. É o que permite tratar um documento
    de cem páginas com três em memória em vez de cem.

    `agrupar_ecras` passou a delegar aqui, para a regra viver num sítio só. Uma
    segunda cópia da regra era o caminho certo para o agrupamento em streaming e
    o agrupamento normal discordarem um dia, e para o ecrã da televisão ficar
    diferente do que o painel mostrou.

    Args:
        dimensoes (list[tuple[int, int]]): (largura, altura) de cada página.

    Returns:
        list[list[int]]: um bloco de índices por ecrã.
    """
    ecras, atual = [], []
    for i, (largura, altura) in enumerate(dimensoes):
        if altura > 0 and (largura / altura) >= RACIO_HORIZONTAL:
            if atual:
                ecras.append(atual)
                atual = []
            ecras.append([i])               # ecrã só para ela
            continue
        atual.append(i)
        if len(atual) == MAX_POR_ECRA:
            ecras.append(atual)
            atual = []
    if atual:
        ecras.append(atual)
    return ecras


def sheet_positions(n):
    """Calcula as posições X (borda esquerda) de n folhas centradas no canvas.

    Mantém a largura e o intervalo uniformes e centra o conjunto, quer haja 1,
    2 ou 3 folhas — é isto que faz uma folha isolada aparecer com o mesmo tamanho
    das de um trio, apenas centrada.

    Args:
        n (int): número de folhas (1..MAX_POR_ECRA); valores fora são limitados.

    Returns:
        list[int]: coordenadas X da borda esquerda de cada folha.
    """
    n = max(1, min(n, MAX_POR_ECRA))
    total = n * SHEET_W + (n - 1) * SHEET_GAP   # largura ocupada pelo conjunto
    x0 = (CANVAS_W - total) // 2                 # margem para centrar
    return [x0 + i * (SHEET_W + SHEET_GAP) for i in range(n)]


# ===========================================================================
# 1) Fundo verde metalizado
# ===========================================================================
def metallic_green_bg(w=CANVAS_W, h=CANVAS_H, seed=7):
    """Gera o fundo verde metálico com laivos e pontos dourados.

    O efeito "metálico" nasce da soma de várias camadas: um gradiente diagonal
    (dá profundidade), um brilho especular deslocado (o reflexo de metal polido),
    umas riscas finíssimas (o "brushed metal"), vetas douradas em diagonal e uns
    pontinhos de brilho (a "poeira" dourada). O 'seed' torna o padrão determinístico
    mas variável entre editais, para não parecerem todos clonados.

    Args:
        w (int), h (int): dimensões do fundo.
        seed (int): semente do gerador aleatório (padrão reproduzível por edital).

    Returns:
        numpy.ndarray: imagem RGB uint8 de forma (h, w, 3).
    """
    rng = np.random.default_rng(seed)
    # Grelhas de coordenadas normalizadas [0,1]: nx/ny servem de base a todos os
    # gradientes seguintes sem termos de escrever ciclos sobre píxeis.
    yy, xx = np.mgrid[0:h, 0:w].astype(REAL)
    nx, ny = xx / (w - 1), yy / (h - 1)

    # (a) Gradiente diagonal: mistura do verde profundo para o verde de marca ao
    # longo da diagonal. É o que dá a sensação de superfície e não de cor chapada.
    diag = np.clip(nx * 0.55 + ny * 0.45, 0, 1)
    base = (GREEN_DEEP[None, None, :] * (1 - diag[..., None]) +
            GREEN_BASE[None, None, :] * diag[..., None])

    # (b) Brilho especular: um "foco" de luz posicionado em cima-à-esquerda. A
    # distância a esse ponto (d) elevada a uma potência concentra o brilho, como
    # a reflexão numa chapa de metal. Guardamos 'spec' porque é reutilizado para
    # fazer o ouro reluzir mais onde há mais luz.
    cx, cy = 0.34, 0.26
    d = np.sqrt(((nx - cx) * 1.05) ** 2 + (ny - cy) ** 2)
    spec = np.clip(1 - d * 1.4, 0, 1) ** 2.0
    base = base + (GREEN_LIGHT - GREEN_BASE)[None, None, :] * spec[..., None] * 1.15

    # (c) "Brushed metal": ondulação horizontal de amplitude mínima. Quase não se
    # vê conscientemente, mas quebra a lisura e lê-se como metal escovado.
    brush = np.sin(ny * np.pi * 300 + np.sin(nx * 5) * 1.5)
    base = base + brush[..., None] * 4.0

    # (d) Vinheta suave: escurece ligeiramente as bordas para o olhar cair no
    # centro (onde ficam as folhas).
    vig = np.clip(1 - (((nx - 0.5) ** 2 + (ny - 0.5) ** 2) * 0.85), 0.7, 1.0)
    base = base * vig[..., None]

    # (e) Laivos dourados: 42 "vetas" diagonais finas, cada uma um traço levemente
    # ondulado. Desenhamo-las primeiro num mapa a preto-e-branco (veins) e só
    # depois as convertemos em cor, para poder dar-lhes núcleo nítido + halo difuso.
    veins = np.zeros((h, w), REAL)
    for _ in range(42):
        x0 = rng.uniform(-0.2, 1.05); y0 = rng.uniform(-0.05, 1.05)
        ang = rng.uniform(-0.95, -0.25)          # ângulo (sempre diagonal ascendente)
        length = rng.uniform(0.35, 1.05)         # comprimento da veta
        amp = rng.uniform(0.6, 1.15)             # intensidade
        wob_f = rng.uniform(5, 13); wob_a = rng.uniform(0.006, 0.014)  # ondulação
        # Traça a veta amostrando 900 pontos ao longo do seu comprimento.
        t = np.linspace(0, length, 900)
        px = x0 + np.cos(ang) * t + np.sin(t * wob_f) * wob_a
        py = y0 + np.sin(ang) * t + np.cos(t * wob_f * 0.8) * wob_a * 0.7
        px = (px * (w - 1)).astype(int); py = (py * (h - 1)).astype(int)
        # Mantém só os pontos dentro da imagem e marca-os no mapa de vetas.
        ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        veins[py[ok], px[ok]] = np.maximum(veins[py[ok], px[ok]], amp)
    # Núcleo nítido (sigma pequeno) + halo suave (sigma grande) = veta com brilho.
    core = ndimage.gaussian_filter(veins, sigma=0.8)
    halo = ndimage.gaussian_filter(veins, sigma=4.5) * 0.7
    veins = np.clip(core + halo, 0, 1.5)
    # As vetas reluzem mais onde há brilho especular (fator 'spec'), como ouro real.
    vfac = veins * (0.65 + spec * 1.0)
    gold_col = (GOLD[None, None, :] * (1 - spec[..., None] * 0.5) +
                GOLD_LIGHT[None, None, :] * spec[..., None] * 0.5)
    base = (base * (1 - np.clip(vfac[..., None], 0, 1) * 0.95) +
            gold_col * np.clip(vfac[..., None], 0, 1) * 1.18)

    # (f) Pontos dourados ("poeira"): píxeis esparsos e aleatórios, ligeiramente
    # desfocados, que cintilam sobretudo nas zonas iluminadas.
    # O sorteio fica em float64 e só o resultado é convertido. Não é descuido: o
    # gerador do NumPy produz uma SEQUÊNCIA DIFERENTE conforme o dtype pedido, e
    # sortear em float32 mudava as posições da poeira dourada. A estrutura do
    # fundo ficava igual, mas um edital recomposto deixava de sair idêntico ao
    # PNG que está guardado no arquivo — e o arquivo é prova do que foi afixado.
    # O custo de o manter em float64 é um temporário (h, w), não os de (h, w, 3).
    glint = rng.random((h, w)) > 0.9991          # ~0.09% dos píxeis
    glint = ndimage.gaussian_filter(glint.astype(REAL), 0.8)
    base = base + GOLD_LIGHT[None, None, :] * glint[..., None] * 1.05 * (0.45 + spec[..., None])

    # (g) Grão fino: ruído gaussiano leve, para evitar bandas de cor lisas
    # (banding) e dar textura fotográfica.
    base = base + rng.normal(0, 1.8, (h, w, 1)).astype(REAL)

    # Recorta ao intervalo válido [0,255] e converte para o tipo de imagem final.
    return np.clip(base, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Cache de fundos em disco.
# ---------------------------------------------------------------------------
# O fundo era regenerado do zero em cada ecrã — 7,9 segundos e 1,3 GB — só para
# variar uma semente e os editais não parecerem clonados. Mas o fundo não depende
# do CONTEÚDO: um punhado de variantes pré-desenhadas dá exatamente a mesma
# impressão de variedade, porque ninguém vê dois ecrãs ao mesmo tempo e ninguém
# repara que o 1.º e o 9.º partilham o padrão.
#
# Guarda-se em PNG por ser sem perdas: o fundo tem grão fino de propósito, e o
# JPEG trataria esse grão como ruído a deitar fora, deixando bandas visíveis nas
# zonas de gradiente suave — logo nas margens verdes, que são o que se vê.
VARIANTES_DE_FUNDO = 8

# Fundos já descodificados, guardados em memória entre composições. Uma
# publicação compõe vários ecrãs seguidos e reencontra as mesmas variantes;
# descodificar o PNG de 3840x2160 custava 0,6 s de cada vez. Limita-se a três
# entradas (~75 MB) para não trocar tempo por memória sem limite.
_FUNDOS_EM_MEMORIA: dict[int, np.ndarray] = {}
_MAX_FUNDOS_EM_MEMORIA = 3


def _desfocar(m, sigma, sigma_minimo=4.0):
    """Desfoca uma máscara com qualidade suficiente para sombra, muito mais depressa.

    Os dois gaussian_filter da sombra eram 3,1 s dos 5,2 s de uma composição —
    o verdadeiro estrangulamento, e não a geração do fundo, como se supôs à
    primeira. Um filtro gaussiano de sigma 55 sobre 8,3 milhões de píxeis são
    umas 440 amostras por eixo e por píxel.

    A saída para isto é conhecida e explora uma propriedade do próprio problema:
    uma desfocagem larga destrói, por construção, o detalhe fino. Reduz-se a
    máscara, desfoca-se com sigma proporcionalmente menor, e reamplia-se. O fator
    é escolhido para o sigma efetivo nunca descer abaixo de 'sigma_minimo', que é
    onde o núcleo ainda tem amostras que cheguem para não serrilhar.

    Medido contra o filtro exato, com a máscara real de três folhas: erro máximo
    de 0,005, que depois de multiplicado pela opacidade da sombra (0,62) dá menos
    de UM nível em 255. O grão que o fundo tem de propósito é maior do que isso.

    Args:
        m (numpy.ndarray): máscara float32 (h, w) em [0,1].
        sigma (float): desvio-padrão pretendido, em píxeis da imagem final.
        sigma_minimo (float): sigma efetivo mínimo depois da redução.

    Returns:
        numpy.ndarray: máscara desfocada (h, w) em float32.
    """
    fator = max(1, int(sigma // sigma_minimo))
    if fator == 1:
        return ndimage.gaussian_filter(m.astype(REAL), sigma)
    h, w = m.shape
    peq = np.asarray(Image.fromarray(m.astype(REAL)).resize(
        (max(1, w // fator), max(1, h // fator)), Image.BILINEAR), REAL)
    peq = ndimage.gaussian_filter(peq, sigma / fator)
    return np.asarray(Image.fromarray(peq).resize((w, h), Image.BILINEAR), REAL)

# Sobe quando a aparência do fundo mudar, para a cache antiga ser ignorada em vez
# de continuar a servir imagens desenhadas por uma versão anterior do código.
VERSAO_DO_FUNDO = 1


def obter_fundo(seed=7, cache=None, variantes=VARIANTES_DE_FUNDO):
    """Devolve um fundo metálico, servindo-o da cache em disco quando existe.

    A semente deixa de escolher um fundo único e passa a escolher uma de
    'variantes' pré-desenhadas. É o que transforma a composição de ~9 s em menos
    de 1 s a partir do segundo ecrã: gera-se cada variante uma vez na vida e daí
    em diante lê-se do disco.

    Args:
        seed (int): semente do edital; decide qual das variantes lhe cabe.
        cache (str|None): pasta da cache. Sem ela, gera sempre (comportamento
            antigo) — é o que os testes usam para não tocar no disco.
        variantes (int): quantos fundos distintos existem no total.

    Returns:
        numpy.ndarray: imagem RGB uint8 (CANVAS_H, CANVAS_W, 3).
    """
    if not cache:
        return metallic_green_bg(CANVAS_W, CANVAS_H, seed=seed)
    i = int(seed) % max(1, variantes)
    os.makedirs(cache, exist_ok=True)
    nome = f"fundo_{CANVAS_W}x{CANVAS_H}_v{VERSAO_DO_FUNDO}_{i:02d}.png"
    caminho = os.path.join(cache, nome)
    if i in _FUNDOS_EM_MEMORIA:
        return _FUNDOS_EM_MEMORIA[i]
    if os.path.exists(caminho):
        try:
            img = np.array(Image.open(caminho).convert("RGB"))
            _guardar_em_memoria(i, img)
            return img
        except OSError:
            # Ficheiro truncado por uma escrita interrompida: apaga e redesenha,
            # em vez de deixar a composição a falhar para sempre.
            try:
                os.remove(caminho)
            except OSError:
                pass
    # A semente da variante é fixa (e não a do edital), para a variante i ser
    # sempre a mesma imagem, hoje e daqui a um ano.
    img = metallic_green_bg(CANVAS_W, CANVAS_H, seed=1000 + i)
    tmp = caminho + ".tmp"
    Image.fromarray(img).save(tmp, "PNG", compress_level=6)
    os.replace(tmp, caminho)
    _guardar_em_memoria(i, img)
    return img


def _guardar_em_memoria(i, img):
    """Guarda um fundo descodificado, deitando fora o mais antigo se já houver três."""
    if len(_FUNDOS_EM_MEMORIA) >= _MAX_FUNDOS_EM_MEMORIA:
        _FUNDOS_EM_MEMORIA.pop(next(iter(_FUNDOS_EM_MEMORIA)))
    _FUNDOS_EM_MEMORIA[i] = img


# ===========================================================================
# 2) Deteção da(s) folha(s) — usada quando recompomos imagens já montadas
# ===========================================================================
def extract_sheet_mask(a):
    """Deteta a(s) peça(s) central(is) (folha branca OU cartaz colorido) numa imagem.

    Ideia central: a peça é "tudo o que NÃO é o fundo verde texturado". Em vez de
    procurar branco (falharia com cartazes coloridos), procuramos onde o fundo
    verde NÃO domina e tratamos cada mancha resultante como um retângulo sólido —
    porque folhas e cartazes são retângulos, e assim logótipos verdes no interior
    (que "furariam" a máscara) não abrem buracos.

    Args:
        a (numpy.ndarray): imagem RGB (int) de forma (h, w, 3).

    Returns:
        numpy.ndarray: máscara booleana (h, w) — True onde há folha/cartaz.
    """
    h, w = a.shape[:2]
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mn = a.min(axis=2); mx = a.max(axis=2); sat = mx - mn

    # "É fundo?" = verde domina (g é o maior canal com margem) e é escuro.
    green_dom = (g >= r) & (g >= b) & (g - np.minimum(r, b) > 8)
    dark = mx < 170
    is_bg = green_dom & dark
    # Densidade local de fundo: uniform_filter faz a média numa janela 35x35, o que
    # transforma "este píxel é fundo?" em "esta VIZINHANÇA é fundo?". As folhas dão
    # zonas de baixa densidade de fundo; as riscas finas do verde dão densidade alta.
    bg_dens = ndimage.uniform_filter(is_bg.astype(np.float32), size=35)
    fg = bg_dens < 0.35
    # Morfologia: fechar tapa pequenos buracos internos, abrir remove salpicos
    # soltos, e fill_holes garante manchas cheias antes de as etiquetar.
    fg = ndimage.binary_closing(fg, structure=np.ones((9, 9)), iterations=2)
    fg = ndimage.binary_opening(fg, structure=np.ones((9, 9)), iterations=1)
    fg = ndimage.binary_fill_holes(fg)

    # Etiqueta as manchas separadas (cada folha é uma "ilha").
    lbl, n = ndimage.label(fg)
    if n == 0:
        return fg
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    total = h * w
    # Mantém só as manchas com área relevante (>=6% do ecrã): descarta ruído e
    # aceita várias folhas (algumas imagens antigas têm 2 ou 3 lado a lado).
    keep = [i + 1 for i, s in enumerate(sizes) if s / total >= 0.06]
    if not keep:
        keep = [int(np.argmax(sizes)) + 1]
    main = np.isin(lbl, keep)

    # Rede de segurança: se a deteção por "não-fundo" falhou (mancha demasiado
    # pequena), tenta o método clássico de folha branca (alta luminância + baixa
    # saturação). Cobre casos-limite de digitalizações muito claras.
    if main.mean() < 0.10:
        white = ((mn > 200) & (sat < 30)).astype(np.float32)
        dens = ndimage.uniform_filter(white, size=25)
        solid = ndimage.binary_fill_holes(dens > 0.6)
        lbl2, n2 = ndimage.label(solid)
        if n2 > 0:
            s2 = ndimage.sum(np.ones_like(lbl2), lbl2, range(1, n2 + 1))
            keep2 = [i + 1 for i, s in enumerate(s2) if s / total >= 0.06]
            if keep2:
                main = np.isin(lbl2, keep2)

    # Converte cada mancha no seu retângulo delimitador cheio: as folhas são
    # retangulares, e assim elementos internos (logótipos verdes) não abrem buracos.
    filled = np.zeros_like(main)
    l3, n3 = ndimage.label(main)
    for i in range(1, n3 + 1):
        comp = l3 == i
        ys, xs = np.where(comp)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        bh, bw = y1 - y0 + 1, x1 - x0 + 1
        if bh * bw < 0.04 * h * w:      # ignora retângulos minúsculos
            continue
        # Se a mancha preenche bem a sua caixa (>55%), é mesmo um retângulo →
        # preenche a caixa toda. Senão, mantém a forma original (fill_holes).
        if comp.sum() / (bh * bw) > 0.55:
            filled[y0:y1 + 1, x0:x1 + 1] = True
        else:
            filled |= ndimage.binary_fill_holes(comp)
    return filled


# ===========================================================================
# 3) Logótipo dourado com gravação (relevo 3D)
# ===========================================================================
def _alpha_from(path):
    """Extrai o canal de opacidade (alfa) do logótipo a partir de um PNG do símbolo.

    O símbolo vem como tinta escura sobre fundo branco. Convertendo a luminância,
    quanto mais escuro o píxel (tinta), maior o alfa (1 = tinta cheia; 0 = fundo).

    Args:
        path (str): caminho do PNG do símbolo ou do texto.

    Returns:
        numpy.ndarray: matriz float (h, w) com valores de alfa em [0,1].
    """
    a = np.array(Image.open(path).convert('RGB')).astype(float)
    lum = a.mean(axis=2)
    al = np.clip((235 - lum) / 180, 0, 1)   # escuro→1, claro→0
    al[lum > 226] = 0                        # branco puro = totalmente transparente
    return ndimage.gaussian_filter(al, 0.4)  # leve suavização anti-serrilhado


def _scale_to_h(al, H):
    """Redimensiona uma matriz de alfa para uma altura-alvo, mantendo o rácio.

    Args:
        al (numpy.ndarray): matriz de alfa (h, w).
        H (int): altura desejada em píxeis.

    Returns:
        numpy.ndarray: alfa redimensionado (H, w') em [0,1].
    """
    h, w = al.shape
    s = H / h
    im = Image.fromarray((np.clip(al, 0, 1) * 255).astype(np.uint8)).resize(
        (max(1, int(w * s)), H), Image.LANCZOS)
    return np.array(im).astype(float) / 255.0


def _assemble(sym_path, txt_path, sym_h, gap):
    """Monta símbolo + texto ("Moimenta da Beira / Município") lado a lado num só alfa.

    O símbolo e o texto vêm de PNGs separados (para poderem ter tamanhos relativos
    diferentes); aqui alinham-se verticalmente ao centro e juntam-se com um intervalo.

    Args:
        sym_path (str): PNG do símbolo (monograma).
        txt_path (str): PNG do texto.
        sym_h (int): altura do símbolo em píxeis (o texto vai a 62% disto).
        gap (int): intervalo horizontal entre símbolo e texto.

    Returns:
        numpy.ndarray: matriz de alfa combinada (H, W) do logótipo completo.
    """
    sa = _scale_to_h(_alpha_from(sym_path), sym_h)
    ta = _scale_to_h(_alpha_from(txt_path), int(sym_h * 0.62))
    H = max(sa.shape[0], ta.shape[0])
    W = sa.shape[1] + gap + ta.shape[1]
    c = np.zeros((H, W), float)
    # Símbolo à esquerda, centrado na vertical.
    ys = (H - sa.shape[0]) // 2
    c[ys:ys + sa.shape[0], 0:sa.shape[1]] = sa
    # Texto à direita do intervalo, também centrado na vertical.
    xt = sa.shape[1] + gap; yt = (H - ta.shape[0]) // 2
    c[yt:yt + ta.shape[0], xt:xt + ta.shape[1]] = ta
    return c


def _engrave(mask):
    """Dá a um alfa plano o aspeto de metal dourado gravado (relevo 3D).

    Esta é a parte mais "gráfica" do módulo. A técnica é iluminação por normais:
      1. do alfa cria-se um "mapa de altura" (bevel) — as bordas do traço descem,
         o interior fica alto, como se o metal fosse esculpido;
      2. desse mapa calcula-se, em cada píxel, a direção da superfície (a normal);
      3. ilumina-se a superfície com uma luz direcional fixa (difusa + especular),
         de modo que as faces viradas à luz brilham e as opostas ficam em sombra —
         é isso que o olho lê como relevo.
    Um sulco escuro no contorno reforça a ideia de "cavado" na chapa.

    Args:
        mask (numpy.ndarray): alfa do logótipo (H, W) em [0,1].

    Returns:
        tuple[numpy.ndarray, numpy.ndarray]: (RGB float (H,W,3), alfa final (H,W)).
        O alfa é devolvido porque engrossámos o traço e a máscara mudou.
    """
    solid = mask > 0.45
    # Engrossa ligeiramente o traço: o logótipo original é fino e, reduzido no
    # ecrã, o relevo perder-se-ia; dar-lhe corpo fá-lo "aguentar" a gravação.
    solid = ndimage.binary_dilation(solid, iterations=2)
    mask = np.maximum(mask, solid.astype(float))

    # Mapa de altura via transformada de distância: cada píxel recebe a distância
    # à borda mais próxima. Limitando a 12 e elevando a 0.65 obtém-se um chanfro
    # (bevel) curto e de ombro arredondado, não uma cúpula exagerada.
    dist = ndimage.distance_transform_edt(solid)
    height = np.power(np.clip(dist / 12.0, 0, 1), 0.65)
    height = ndimage.gaussian_filter(height, 1.3)   # suaviza o relevo

    # Normais da superfície: o gradiente do mapa de altura dá a inclinação em x e y;
    # com z fixo obtemos o vetor perpendicular à superfície em cada píxel. É este
    # vetor que, comparado com a direção da luz, decide o brilho.
    gy, gx = np.gradient(height)
    s = 7.0                                   # "força" do relevo (exagera a inclinação)
    nx, ny = -gx * s, -gy * s
    nz = np.ones_like(height)
    nrm = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6   # normaliza (evita /0)
    nx, ny, nz = nx / nrm, ny / nrm, nz / nrm

    # Luz direcional vinda de cima-à-esquerda (coerente com o brilho do fundo).
    L = np.array([-0.55, -0.62, 0.56]); L /= np.linalg.norm(L)
    # Componente difusa: quanto a superfície "encara" a luz (produto escalar).
    diff = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    # Componente especular (Blinn-Phong simplificado): brilho concentrado onde a
    # normal se alinha com o vetor intermédio entre luz e observador (H).
    V = np.array([0, 0, 1.0]); Hh = (L + V); Hh /= np.linalg.norm(Hh)
    spec = np.clip(nx * Hh[0] + ny * Hh[1] + nz * Hh[2], 0, 1) ** 20

    # Cor base: interpola do tom em sombra (LO) ao médio (MID) segundo a altura,
    # aplica a iluminação difusa (com um mínimo ambiente de 0.30 p/ não ficar preto)
    # e soma o realce especular claro por cima.
    shade = 0.30 + 0.98 * diff
    base = (GOLD_LO[None, None, :] * (1 - height[..., None]) +
            GOLD_MID[None, None, :] * height[..., None])
    rgb = base * shade[..., None]
    rgb = rgb + (GOLD_HI - GOLD_MID)[None, None, :] * spec[..., None] * 1.05

    # Sulco no contorno: a orla externa (diferença entre a forma e a sua erosão)
    # é escurecida para GOLD_DEEP, dando a leitura de "gravado" em vez de "colado".
    rim = solid.astype(float) - ndimage.binary_erosion(solid, iterations=2).astype(float)
    rim = ndimage.gaussian_filter(rim, 1.0)
    rgb = rgb * (1 - rim[..., None] * 0.5) + GOLD_DEEP[None, None, :] * rim[..., None] * 0.5

    return np.clip(rgb, 0, 255), mask


def build_logo(sym_path, txt_path, out_h=160, gap_ratio=0.34, ss=4):
    """Constrói o logótipo dourado gravado como imagem RGBA pronta a colar.

    Renderiza a uma resolução 'ss' vezes maior e reduz no fim (supersampling):
    é o truque para o relevo e as bordas saírem nítidos em vez de serrilhados,
    já que os traços são finos.

    Args:
        sym_path (str): PNG do símbolo (monograma MMB).
        txt_path (str): PNG do texto "Moimenta da Beira / Município".
        out_h (int): altura final do logótipo em píxeis.
        gap_ratio (float): intervalo símbolo–texto, como fração da altura.
        ss (int): fator de supersampling (4 = renderiza a 4x e reduz).

    Returns:
        PIL.Image.Image: logótipo em modo RGBA (com transparência), altura out_h.
    """
    sym_h_hi = int(out_h * ss)
    gap_hi = int(sym_h_hi * gap_ratio)
    mask = _assemble(sym_path, txt_path, sym_h_hi, gap_hi)
    rgb, mask = _engrave(mask)
    # Junta cor + alfa num RGBA e reduz para a resolução final (LANCZOS = nítido).
    rgba = np.dstack([rgb, np.clip(mask, 0, 1) * 255]).astype(np.uint8)
    im = Image.fromarray(rgba, 'RGBA').resize(
        (rgba.shape[1] // ss, rgba.shape[0] // ss), Image.LANCZOS)
    return im


# ===========================================================================
# 4) Composição final
# ===========================================================================
def _fit_sheet(page_img, target_w=SHEET_W, target_h=SHEET_H):
    """Encaixa uma página na caixa-folha uniforme SEM cortar nada.

    Usa a estratégia "fit" (a página cabe inteira), não "cover" (que cortava). O
    fator de escala é o MENOR entre ajustar-pela-largura e ajustar-pela-altura, o
    que garante que a imagem toda cabe na caixa; o espaço restante é preenchido a
    branco e a imagem fica centrada.

    Porquê esta mudança: a versão anterior escalava sempre pela altura e cortava as
    laterais quando a imagem ficava mais larga que a caixa. Para uma folha A4
    (vertical) isso era inofensivo, mas para um PRINTSCREEN (horizontal, 16:9) a
    largura escalada disparava e o corte amputava o texto das margens esquerda e
    direita. Com "fit", um A4 continua a encaixar praticamente igual, e um
    printscreen largo aparece como uma faixa centrada com margens brancas em cima e
    em baixo — mas sem perder um único pixel de conteúdo.

    Args:
        page_img (PIL.Image.Image): página a encaixar.
        target_w (int), target_h (int): dimensões da caixa-folha.

    Returns:
        PIL.Image.Image: página encaixada, tamanho exato (target_w, target_h),
        com o conteúdo inteiro visível.
    """
    w, h = page_img.size
    # Escala que faz caber pela largura vs. pela altura; usamos a menor para que
    # NENHUMA dimensão ultrapasse a caixa (logo, nada é cortado).
    escala = min(target_w / w, target_h / h)
    nw = max(1, int(round(w * escala)))
    nh = max(1, int(round(h * escala)))
    img = page_img.convert("RGB").resize((nw, nh), Image.LANCZOS)
    # Tela branca do tamanho exato da caixa; a imagem encaixada é centrada nela.
    canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    canvas.paste(img, ((target_w - nw) // 2, (target_h - nh) // 2))
    return canvas


def _caixa_justa(pagina, x, y, caixa_w, caixa_h):
    """Encolhe uma caixa ao tamanho exato da página encaixada, e recentra-a.

    A caixa-folha vertical é de tamanho FIXO de propósito: uma folha sozinha tem
    de ter o mesmo tamanho das de um trio, senão a rotação no ecrã parece saltar.
    A folha A4 enche-a quase toda (0,707 contra 0,716 de rácio), por isso o
    branco que sobra não se vê.

    Na caixa larga isso deixa de valer. Ela tem rácio 2,19:1 e um printscreen
    tem 1,78:1, pelo que sobravam quase 700 píxeis de branco repartidos pelos
    lados — e uma folha mais larga do que o seu conteúdo lê-se como defeito, não
    como desenho. Aqui não há trio com que manter consistência: é sempre uma
    página só. Então a folha passa a ser do tamanho do que leva dentro, e o
    verde do fundo aparece dos lados, que é o que se quer ver.

    Args:
        pagina (PIL.Image.Image): página a encaixar.
        x (int), y (int): canto superior esquerdo da caixa disponível.
        caixa_w (int), caixa_h (int): dimensões da caixa disponível.

    Returns:
        tuple[int, int, int, int]: (x, y, largura, altura) já ajustados.
    """
    largura, altura = pagina.size
    escala = min(caixa_w / largura, caixa_h / altura)
    nova_w = max(1, round(largura * escala))
    nova_h = max(1, round(altura * escala))
    return (x + (caixa_w - nova_w) // 2, y + (caixa_h - nova_h) // 2, nova_w, nova_h)


def compose_sheets(pages, seed=7, logo_im=None,
                   logo_width_frac=0.150, logo_margin_frac=0.032, cache_fundos=None):
    """Compõe 1..3 páginas lado a lado, ao mesmo tamanho, sobre o fundo metálico.

    É a função central do módulo. Gera o fundo, coloca as folhas nas posições
    uniformes, projeta-lhes uma sombra de duplo nível (para "pairarem") e, se
    houver espaço verde no canto, aplica o logótipo gravado.

    Uma página horizontal sozinha recebe a caixa larga (ver LARGA_W/LARGA_H);
    tudo o resto usa a grelha vertical de sempre.

    Args:
        pages (list[PIL.Image.Image]): 1 a 3 páginas (excedente é ignorado).
        seed (int): semente do fundo (varia o padrão dourado por ecrã).
        logo_im (PIL.Image.Image | None): logótipo RGBA já construído, ou None.
        logo_width_frac (float): largura do logótipo como fração do ecrã.
        logo_margin_frac (float): margem do logótipo ao canto, fração da largura.
        cache_fundos (str|None): pasta da cache de fundos. Com ela, o fundo vem
            do disco em vez de ser redesenhado — ver obter_fundo.

    Returns:
        PIL.Image.Image: composição final RGB (CANVAS_W × CANVAS_H).
    """
    pages = pages[:MAX_POR_ECRA]
    bg = obter_fundo(seed, cache_fundos).astype(REAL)

    # Uma página horizontal sozinha usa a caixa larga; tudo o resto usa a grelha
    # vertical de sempre. A decisão fica aqui, e não em quem chama, para que
    # mesmo uma chamada avulsa — um teste, um script de recurso — faça a coisa
    # certa sem ter de saber destas regras.
    if len(pages) == 1 and e_horizontal(pages[0]):
        caixas = [_caixa_justa(pages[0], MARGEM_LATERAL, SHEET_TOP, LARGA_W, LARGA_H)]
    else:
        caixas = [(x, SHEET_TOP, SHEET_W, SHEET_H)
                  for x in sheet_positions(len(pages))]

    # Máscara conjunta de todas as folhas: é a partir dela que se calcula a sombra.
    m = np.zeros((CANVAS_H, CANVAS_W), REAL)
    fitted = []
    # strict=True: as caixas são geradas a partir de len(pages), portanto os
    # comprimentos batem por construção. Se um dia deixarem de bater, é melhor
    # saber-se aqui.
    for (x0, y0, cw, ch), pg in zip(caixas, pages, strict=True):
        sheet = _fit_sheet(pg, cw, ch)
        fitted.append((x0, y0, sheet))
        m[y0:y0 + ch, x0:x0 + cw] = 1.0

    # Sombra de duplo nível para dar a ilusão de "flutuar":
    #  - sombra próxima (sigma 18, deslocada pouco): contacto suave sob a folha;
    #  - sombra distante (sigma 55, deslocada muito): difusa, indica altura.
    # Multiplica-se por (1 - m) para a sombra só existir FORA das folhas, e por
    # 0.62 para não ficar demasiado escura.
    sh_near = np.roll(np.roll(_desfocar(m, 18), 14, 0), 10, 1)
    sh_far = np.roll(np.roll(_desfocar(m, 55), 60, 0), 42, 1)
    shadow = np.clip(sh_near * 0.55 + sh_far * 0.45, 0, 1) * (1 - m) * 0.62
    out = bg * (1 - shadow[..., None])
    del bg, sh_near, sh_far, shadow   # libertar já: são ~100 MB cada

    # Assenta cada folha por cima da sombra.
    for x0, y0, sheet in fitted:
        largura, altura = sheet.size
        out[y0:y0 + altura, x0:x0 + largura, :] = np.array(sheet, dtype=REAL)

    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    _paste_logo(img, m, logo_im, logo_width_frac, logo_margin_frac)
    return img


def compose_from_image(src_img, seed=7, logo_im=None,
                       logo_width_frac=0.150, logo_margin_frac=0.032):
    """Recompõe uma imagem 16:9 JÁ montada (deteta as folhas e troca o fundo).

    Serve para reaproveitar exportações antigas do expositor: extrai as folhas
    existentes, gera um fundo metálico novo e volta a assentá-las com sombra.

    Args:
        src_img (PIL.Image.Image): imagem 16:9 com folha(s) embebida(s).
        seed (int): semente do novo fundo.
        logo_im (PIL.Image.Image | None): logótipo RGBA ou None.
        logo_width_frac (float), logo_margin_frac (float): dimensão/margem do logo.

    Returns:
        PIL.Image.Image: composição refeita com o fundo e o tratamento atuais.
    """
    a = np.array(src_img.convert('RGB')).astype(int)
    H, W = a.shape[:2]
    bg = metallic_green_bg(W, H, seed=seed)
    m = extract_sheet_mask(a)
    out = _place_sheets_from_existing(a, m.astype(float), bg)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    _paste_logo(img, m, logo_im, logo_width_frac, logo_margin_frac)
    return img


def _place_sheets_from_existing(a, m, bg):
    """Reassenta folhas já presentes numa imagem sobre um fundo novo, com sombra.

    Args:
        a (numpy.ndarray): imagem original RGB (int).
        m (numpy.ndarray): máscara float (h,w) das folhas.
        bg (numpy.ndarray): fundo novo RGB (uint8).

    Returns:
        numpy.ndarray: composição float (h,w,3) pronta a converter em imagem.
    """
    sh_near = np.roll(np.roll(_desfocar(m, 18), 14, 0), 10, 1)
    sh_far = np.roll(np.roll(_desfocar(m, 55), 60, 0), 42, 1)
    shadow = np.clip(sh_near * 0.55 + sh_far * 0.45, 0, 1) * (1 - m) * 0.62
    out = bg.astype(float) * (1 - shadow[..., None])
    # 'soft' é a máscara ligeiramente desfocada, usada como fator de mistura para
    # as bordas da folha não ficarem serrilhadas contra o fundo.
    soft = ndimage.gaussian_filter(m, 0.8)[..., None]
    out = out * (1 - soft) + a.astype(float) * soft
    return out


def _paste_logo(img, mask, logo_im, width_frac, margin_frac):
    """Cola o logótipo no canto superior esquerdo — mas só se houver espaço verde.

    Verifica se a faixa onde o logótipo iria assentar é maioritariamente fundo
    (não uma folha). Se a folha ocupa o canto, o logótipo é omitido para não
    ficar por cima do conteúdo. Esta decisão é deliberada: mais vale sem logótipo
    do que um logótipo sobreposto ao texto do edital.

    Args:
        img (PIL.Image.Image): composição onde colar (alterada no lugar).
        mask (numpy.ndarray): máscara das folhas (para saber onde há conteúdo).
        logo_im (PIL.Image.Image | None): logótipo RGBA; se None, não faz nada.
        width_frac (float): largura do logótipo como fração do ecrã.
        margin_frac (float): margem ao canto, como fração da largura do ecrã.

    Returns:
        None. (Modifica 'img' diretamente.)
    """
    if logo_im is None:
        return
    W, H = img.size
    LW, LH = logo_im.size
    tw = int(W * width_frac); th = int(round(LH * tw / LW))   # tamanho-alvo do logo
    mx = int(W * margin_frac); my = int(W * margin_frac * 0.55)  # posição (x,y)

    # Testa se a faixa do logótipo é fundo verde livre. Recalcula "é fundo?" na
    # composição final (e não na máscara) porque queremos o verde real por baixo.
    a = np.array(img).astype(int)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    is_bg = (g >= r) & (g >= b) & (g - np.minimum(r, b) > 6) & (a.max(axis=2) < 175)
    band = is_bg[my:my + th, mx:mx + tw]
    if band.size == 0 or band.mean() < 0.85:   # <85% de fundo → canto ocupado
        return
    lg = logo_im.resize((tw, th), Image.LANCZOS)
    img.paste(lg, (mx, my), lg)                 # o 3.º arg (lg) é a máscara alfa
