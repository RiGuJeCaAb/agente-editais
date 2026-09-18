"""
test_contraste.py — O painel tem de se ler, e isso é verificável.

Porquê um teste e não uma correção pontual: a Câmara é um organismo público, e o
Decreto-Lei n.º 83/2018 vincula as autarquias locais à norma EN 301 549, que é o
equivalente técnico das WCAG 2.1 nível AA. O critério 1.4.3 exige 4,5:1 para
texto normal e 3:1 para texto grande. Quatro pares do painel falhavam — e eram
justamente os carimbos de estado e o aviso "campo a confirmar", ou seja, a
informação que o funcionário mais precisa de ver.

Corrigir as quatro cores à mão resolvia hoje. O que impede a regressão amanhã é
esta lista: qualquer cor nova que não se leia faz o teste falhar antes de chegar
ao posto.

As cores são lidas do :root do painel.html, e não repetidas aqui, para o teste
não poder ficar a testar valores que já ninguém usa.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PAINEL = Path(__file__).resolve().parent.parent / "lib" / "painel.html"

# Rácio exigido por par. 4.5 é o mínimo das WCAG 2.1 AA para texto normal; 3.0
# aplica-se a texto grande (>=18.66px a negrito ou >=24px), que é o caso dos
# títulos de secção e do número grande do registo.
AA_NORMAL = 4.5
AA_GRANDE = 3.0

# Todos os pares de primeiro plano/fundo que o painel efetivamente desenha.
# (descrição, cor do texto, cor do fundo, rácio exigido)
# Os nomes entre chavetas são variáveis CSS lidas do :root; o resto são literais
# que aparecem à letra nas regras.
PARES = [
    ("corpo do texto",            "{--tinta}",        "{--papel}",        AA_NORMAL),
    ("texto secundário",          "{--tinta-suave}",  "{--papel}",        AA_NORMAL),
    ("texto secundário na ficha", "{--tinta-suave}",  "{--papel-ficha}",  AA_NORMAL),
    ("'Vazio' na coluna kanban",  "{--tinta-suave}",  "{--papel-2}",      AA_NORMAL),
    ("carimbo Rascunho",          "{--rascunho}",     "#f3efe3",          AA_NORMAL),
    ("carimbo Validado",          "{--validado}",     "#eaf6ee",          AA_NORMAL),
    ("carimbo Publicado",         "{--publicado}",    "#e7f1eb",          AA_NORMAL),
    ("carimbo Retirado",          "{--retirado}",     "#f0ede4",          AA_NORMAL),
    ("aviso 'a confirmar'",       "{--alerta}",       "{--alerta-fundo}", AA_NORMAL),
    ("nota de confiança",         "{--alerta}",       "{--papel-ficha}",  AA_NORMAL),
    ("botão Retirar (perigo)",    "{--alerta}",       "{--papel-ficha}",  AA_NORMAL),
    ("botão Validar",             "#ffffff",          "{--validado}",     AA_NORMAL),
    ("botão de ação (ouro)",      "{--verde-escuro}", "{--ouro}",         AA_NORMAL),
    ("nº do registo na ficha",    "{--ouro-escuro}",  "{--papel-ficha}",  AA_NORMAL),
    ("campo obrigatório",         "{--ouro-escuro}",  "{--papel-ficha}",  AA_NORMAL),
    ("fluxo no histórico",        "{--ouro-escuro}",  "{--papel-ficha}",  AA_NORMAL),
    ("navegação inativa",         "#cfe0d6",          "{--verde-selo}",   AA_NORMAL),
    ("rodapé da lateral",         "#a9c3b4",          "{--verde-escuro}", AA_NORMAL),
    ("subtítulo da marca",        "{--ouro-claro}",   "{--verde-selo}",   AA_NORMAL),
    ("'sem pré-visualização'",    "#9fc0af",          "{--verde-selo}",   AA_NORMAL),
    ("toast normal",              "#ffffff",          "{--verde-selo}",   AA_NORMAL),
    ("toast de erro",             "#ffffff",          "#8a3223",          AA_NORMAL),
    ("título de secção",          "{--tinta}",        "{--papel}",        AA_GRANDE),
]


def _canal(c: float) -> float:
    """Lineariza um canal sRGB de 0-255 para a escala de luminância das WCAG."""
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminancia(hexa: str) -> float:
    """Luminância relativa de uma cor #rrggbb, pela fórmula das WCAG 2.1."""
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _canal(r) + 0.7152 * _canal(g) + 0.0722 * _canal(b)


def racio(frente: str, fundo: str) -> float:
    """Rácio de contraste entre duas cores, como as WCAG 2.1 o definem (1:1 a 21:1)."""
    a, b = sorted((_luminancia(frente), _luminancia(fundo)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def variaveis_do_painel() -> dict[str, str]:
    """Lê as variáveis de cor do bloco :root do painel.html.

    Lê-se do ficheiro em vez de as repetir no teste: uma cópia no teste
    dessincroniza-se do painel em silêncio, e o teste passa a garantir uma
    paleta que já não existe.
    """
    css = PAINEL.read_text(encoding="utf-8")
    bloco = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert bloco, "não encontrei o bloco :root em painel.html"
    return {n: v for n, v in re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*;",
                                        bloco.group(1))}


def resolver(cor: str, vars_: dict[str, str]) -> str:
    """Converte '{--nome}' no valor da variável, ou devolve o literal tal como está."""
    if cor.startswith("{") and cor.endswith("}"):
        nome = cor[1:-1]
        assert nome in vars_, f"a variável {nome} já não existe no :root do painel"
        return vars_[nome]
    return cor


@pytest.mark.parametrize("descricao,frente,fundo,exigido", PARES,
                         ids=[p[0] for p in PARES])
def test_par_tem_contraste_suficiente(descricao, frente, fundo, exigido):
    """Cada par de cores do painel cumpre o mínimo das WCAG 2.1 AA (critério 1.4.3)."""
    vars_ = variaveis_do_painel()
    f, b = resolver(frente, vars_), resolver(fundo, vars_)
    r = racio(f, b)
    assert r >= exigido, (
        f"{descricao}: {f} sobre {b} dá {r:.2f}:1, abaixo do mínimo {exigido}:1 "
        f"exigido pelas WCAG 2.1 AA. Escurece a tinta mantendo o matiz."
    )


def test_a_formula_de_contraste_esta_certa():
    """Ancora a fórmula em valores conhecidos, para o teste não validar a si próprio.

    Se a implementação de racio() tiver um erro, todos os outros testes deste
    ficheiro passam a medir a coisa errada sem darem por isso. Preto sobre branco
    é 21:1 e branco sobre branco é 1:1, por definição das WCAG.
    """
    assert round(racio("#000000", "#ffffff"), 2) == 21.0
    assert round(racio("#ffffff", "#ffffff"), 2) == 1.0
    # Valor de referência publicado: #777777 sobre branco é o limiar clássico 4.48:1.
    assert 4.4 < racio("#777777", "#ffffff") < 4.6
