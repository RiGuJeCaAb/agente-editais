#!/usr/bin/env python3
"""Confere que a versão subiu entre a base de uma PR e a sua cabeça.

«Cada peça leva uma versão» — o AGENTS.md. O teste do pytest confere que o
`VERSAO` e o `version` são o MESMO nos dois ficheiros; não tem como saber se
subiu, porque isso só se vê contra a revisão anterior. Apanhado pelo Sourcery
na revisão: uma PR que deixasse os dois intactos passava na regra.

Fica na integração contínua pela mesma razão que a verificação dos assuntos:
precisa do intervalo de commits, que quem corre o pytest à mão nem sempre tem.

O que NÃO faz: decidir se devia ser o segundo número ou o terceiro. A regra
diz «alteração que não muda o que a aplicação faz leva o terceiro», e saber se
uma alteração muda o que a aplicação faz não é coisa que uma máquina conclua
de um diff. Isso continua a ser de quem revê.

Uso: python ferramentas/versao_subiu.py <base> <cabeca>
"""
from __future__ import annotations

import re
import subprocess
import sys


def versao_em(revisao: str) -> tuple[int, ...] | None:
    """O VERSAO que o agente.py declarava nesta revisão, como tuplo de inteiros.

    Devolve None quando o ficheiro não existe nessa revisão ou não declara
    versão nenhuma — o que não é falha, é um repositório mais antigo do que a
    regra.
    """
    try:
        texto = subprocess.run(["git", "show", f"{revisao}:agente.py"],
                               capture_output=True, text=True,
                               check=True).stdout
    except subprocess.CalledProcessError:
        return None
    achado = re.search(r'^VERSAO\s*=\s*"(\d+)\.(\d+)\.(\d+)"', texto, re.M)
    return tuple(int(n) for n in achado.groups()) if achado else None


def main(argv: list[str]) -> int:
    """Devolve 0 se a versão subiu, 1 se ficou na mesma ou desceu."""
    if len(argv) != 3:
        print(__doc__)
        return 2
    base, cabeca = argv[1], argv[2]
    antes, agora = versao_em(base), versao_em(cabeca)
    if antes is None or agora is None:
        print(f"Não consegui ler a versão em {base} ou em {cabeca}.")
        print("Isto é falha e não passagem: sem os dois lados não se compara "
              "nada, e uma verificação que não verifica é pior do que não "
              "existir.")
        return 1

    def escrita(v: tuple[int, ...]) -> str:
        """A versão como se escreve."""
        return ".".join(str(n) for n in v)

    if agora <= antes:
        print(f"A versão não subiu: {escrita(antes)} na base e "
              f"{escrita(agora)} aqui.")
        print("«Cada peça leva uma versão» — o AGENTS.md. Alteração que não "
              "muda o que a aplicação faz leva o terceiro número; tudo o resto "
              "leva o segundo.")
        return 1
    print(f"  ok  {escrita(antes)} -> {escrita(agora)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
