"""
diario.py — Registo técnico do agente: níveis, rotação e ficheiro.

Havia 71 chamadas a print() espalhadas pelo código. Enquanto alguém está a olhar
para uma consola, funciona. Num serviço que corre sozinho num posto municipal
durante meses, não funciona: não há níveis (tudo é igualmente importante), não
há carimbo temporal (não se sabe quando aconteceu), não há rotação (ou se perde
tudo ao reiniciar, ou se enche o disco), e não há ficheiro nenhum a não ser que
alguém se tenha lembrado de redirecionar o stdout no cron.

Isto deixou de ser só higiene. O Decreto-Lei n.º 125/2025, de 4 de dezembro, que
transpôs a diretiva NIS2 e está em vigor desde 3 de abril de 2026, espera de
quem opera um serviço público a capacidade de detetar e reportar incidentes.
Sem registos datados e preservados, essa capacidade não existe — e um
`print()` para stdout que ninguém guarda não é um registo.

Convenção de nomes
------------------
Os prefixos que já existiam ([PAINEL], [ARQUIVO], [TV]...) eram bons: diziam de
que parte do sistema vinha a mensagem. Passam a ser o NOME do registador, em vez
de texto colado à frente da mensagem. Ganha-se o mesmo à leitura e mais na
utilização: `grep PAINEL`, sim, mas também filtrar por origem na configuração,
ou baixar só um deles para DEBUG sem afogar o resto.

Dois destinos, de propósito
---------------------------
Consola e ficheiro ao mesmo tempo. A consola serve quem está a correr o agente à
mão e quer ver o que se passa; o ficheiro serve o dia em que for preciso
perceber o que aconteceu na semana passada. Um sem o outro deixa sempre um dos
dois casos a descoberto.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

# Dez ficheiros de 2 MB: cerca de 20 MB no total, que num posto com dezenas de
# editais por mês guarda muitos meses de história sem que ninguém tenha de se
# lembrar de limpar nada.
TAMANHO_MAXIMO = 2 * 1024 * 1024
FICHEIROS_GUARDADOS = 10

# Na consola, sem data: quem está a ver em direto sabe que é agora, e a data
# ocuparia um terço da linha. No ficheiro, com data completa, porque é lido
# meses depois e sem ela não vale nada.
FORMATO_CONSOLA = "[%(curto)s] %(message)s"
FORMATO_FICHEIRO = "%(asctime)s %(levelname)-7s [%(curto)s] %(message)s"


class _NomeCurto(logging.Filter):
    """Acrescenta a cada linha o nome sem o prefixo da hierarquia.

    Os registadores chamam-se 'editais.PAINEL' para serem todos filhos de um só
    e se poderem configurar em bloco. Mas quem lê a linha quer ver 'PAINEL': o
    'editais.' repetido em todas as linhas é ruído que só ocupa largura.
    """

    def filter(self, registo: logging.LogRecord) -> bool:
        registo.curto = registo.name.split(".")[-1]
        return True

_configurado = False


def configurar(caminho: str | None = None, nivel: str = "INFO",
               nivel_ficheiro: str = "DEBUG") -> None:
    """Prepara o registo técnico. Chamado uma vez, no arranque.

    É idempotente: chamar duas vezes não duplica as mensagens. Parece detalhe,
    mas o painel e a vigia arrancam em threads diferentes e a segunda chamada
    acontecia mesmo — com o resultado de cada linha aparecer a dobrar.

    Args:
        caminho: ficheiro de registo. None desliga a escrita em ficheiro, que é
            o que os testes querem.
        nivel: nível mínimo mostrado na consola.
        nivel_ficheiro: nível mínimo escrito no ficheiro. Por omissão mais baixo
            do que o da consola: o que se vê é o essencial, o que fica guardado
            é tudo, e é no dia do incidente que a diferença se paga.
    """
    global _configurado
    if _configurado:
        return
    raiz = logging.getLogger("editais")
    raiz.setLevel(logging.DEBUG)
    raiz.propagate = False

    consola = logging.StreamHandler(sys.stdout)
    consola.setLevel(getattr(logging, nivel.upper(), logging.INFO))
    consola.setFormatter(logging.Formatter(FORMATO_CONSOLA))
    consola.addFilter(_NomeCurto())
    raiz.addHandler(consola)

    if caminho:
        os.makedirs(os.path.dirname(os.path.abspath(caminho)) or ".", exist_ok=True)
        ficheiro = logging.handlers.RotatingFileHandler(
            caminho, maxBytes=TAMANHO_MAXIMO, backupCount=FICHEIROS_GUARDADOS,
            encoding="utf-8")
        ficheiro.setLevel(getattr(logging, nivel_ficheiro.upper(), logging.DEBUG))
        ficheiro.setFormatter(logging.Formatter(FORMATO_FICHEIRO))
        ficheiro.addFilter(_NomeCurto())
        raiz.addHandler(ficheiro)
    _configurado = True


def obter(nome: str) -> logging.Logger:
    """Devolve o registador de uma parte do sistema.

    O nome é o que aparece entre parênteses retos na linha — 'PAINEL', 'TV',
    'ARQUIVO' — os mesmos prefixos que já se usavam, agora com significado para
    a própria biblioteca em vez de serem texto.

    Funciona antes de configurar(): as mensagens ficam retidas e nada rebenta,
    o que importa porque alguns módulos escrevem durante a importação.
    """
    return logging.getLogger(f"editais.{nome}")


def repor() -> None:
    """Desfaz a configuração. Existe para os testes não herdarem handlers uns dos outros."""
    global _configurado
    raiz = logging.getLogger("editais")
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
        h.close()
    _configurado = False
