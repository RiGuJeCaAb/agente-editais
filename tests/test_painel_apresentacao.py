"""Guardas de apresentação do painel, lidas do próprio painel.html.

Não substituem olhar para o ecrã. Fixam defeitos que já aconteceram e que uma
pessoa a correr a aplicação pode não notar à primeira — e que nenhum teste de
comportamento apanha, porque o comportamento está certo e o que falha é o que
se vê.
"""
from pathlib import Path

PAINEL = Path(__file__).resolve().parents[1] / "lib" / "painel.html"


def test_o_bloco_de_afixacao_tem_estilo_no_formulario_de_edicao():
    """As linhas da afixação são flex também dentro do formulário de edição.

    As regras do `.meta` estavam escritas só para `.ficha`, e o formulário de
    edição é `.ficha-edicao` — que em CSS é um nome diferente, não um prefixo.
    Sem o `display:flex`, o rótulo colava-se ao valor e via-se assim no ecrã:

        Afixado em2026-09-29 às 11:38
        Afixado porricardo.abreu

    O comportamento estava certo. Só a apresentação é que não, e por isso nenhum
    teste de estado o apanhava.
    """
    css = PAINEL.read_text(encoding="utf-8")
    for regra in (".ficha-edicao .meta{", ".ficha-edicao .meta .l{",
                  ".ficha-edicao .meta b{"):
        assert regra in css, f"falta a regra «{regra}» — a afixação volta a colar-se"
