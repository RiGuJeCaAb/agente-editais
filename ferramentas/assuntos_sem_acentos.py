#!/usr/bin/env python3
"""Confere que os assuntos dos commits de uma PR não levam acentos.

«Os assuntos dos commits escrevem-se sem acentos, por hábito de consola» — o
AGENTS.md. O corpo leva acentuação normal: é só a primeira linha.

Vive na integração contínua e não no pytest de propósito. Um teste precisaria
do `origin/main` para saber que commits são desta PR, e quem corre o pytest à
mão nem sempre o tem — o teste passaria em silêncio por não ter o que ver, que
é a pior espécie de verificação. Aqui, sem o intervalo, isto FALHA.

Uso: python ferramentas/assuntos_sem_acentos.py <base> <cabeca>
"""
from __future__ import annotations

import subprocess
import sys
import unicodedata


def tem_acento(texto: str) -> bool:
    """Diz se o texto leva alguma letra com diacrítico.

    Pela decomposição e não por uma lista de letras: assim apanha o «ç», o «ã»
    e o «ü» sem os enumerar, e não se engana com as aspas angulares nem com o
    travessão, que não são letras acentuadas e são bem-vindos.
    """
    return any(unicodedata.combining(c)
               for c in unicodedata.normalize("NFD", texto))


def main(argv: list[str]) -> int:
    """Devolve 0 se todos os assuntos estiverem limpos, 1 se algum não estiver."""
    if len(argv) != 3:
        print(__doc__)
        return 2
    base, cabeca = argv[1], argv[2]
    try:
        saida = subprocess.run(["git", "log", "--format=%s", f"{base}..{cabeca}"],
                               capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as erro:
        print(f"O git não soube resolver {base}..{cabeca}: {erro.stderr.strip()}")
        return 1
    assuntos = [linha for linha in saida.splitlines() if linha.strip()]
    if not assuntos:
        print(f"Nenhum commit entre {base} e {cabeca}.")
        print("Isto é falha e não passagem: sem o intervalo certo não se "
              "verifica nada, e uma verificação que não verifica é pior do "
              "que não existir.")
        return 1

    maus = [a for a in assuntos if tem_acento(a)]
    for assunto in assuntos:
        print(f"  {'ACENTO' if assunto in maus else '    ok'}  {assunto}")
    if maus:
        print(f"\n{len(maus)} assunto(s) com acentos. O AGENTS.md pede-os sem, "
              "por hábito de consola; o corpo do commit leva acentuação normal.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
