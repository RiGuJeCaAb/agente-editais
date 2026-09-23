"""
progresso.py — O que o agente está a fazer neste momento, à vista de quem espera.

Compor os ecrãs de um edital demora. Um documento de vinte páginas leva dezenas
de segundos entre carregar em «Publicar» e a imagem aparecer na televisão, e
durante esse tempo o painel não dizia nada: nem que estava a trabalhar, nem em
que ia. Quem estava ao teclado tinha duas hipóteses igualmente más — esperar sem
saber se alguma coisa estava a acontecer, ou carregar outra vez.

Isto é um quadro único, partilhado entre a thread que trabalha e a que serve o
painel. Não é uma fila de tarefas a sério, e não finge sê-lo: o agente faz uma
coisa de cada vez, e o que falta responder é «está a fazer o quê, e em que
ponto». Uma fila com prioridades e cancelamento resolveria um problema que este
posto não tem.

Thread-safe por um lock e por serem leituras e escritas de um dicionário
pequeno. O painel lê; só a thread de trabalho escreve.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

# Fases, pela ordem por que acontecem. O painel usa-as para escolher a frase.
NADA       = "nada"
A_LER      = "a_ler"        # a rasterizar páginas e a gerar pré-visualizações
A_COMPOR   = "a_compor"     # a desenhar os ecrãs 4K de um edital publicado
A_PUBLICAR = "a_publicar"   # a reconstruir a página da TV

_lock = threading.Lock()
_estado: dict[str, Any] = {"fase": NADA}


# Grava o que se está a fazer, substituindo o que lá estava.
def _pousar(fase: str, **campos: Any) -> None:
    """Regista a tarefa em curso.

    Substitui em vez de acumular: o que interessa é o agora. O histórico do que
    já aconteceu está no jornal de auditoria e no registo técnico, que são os
    sítios onde alguém o vai procurar daqui a uma semana.
    """
    with _lock:
        _estado.clear()
        _estado.update({"fase": fase, "desde": datetime.now().isoformat(timespec="seconds")})
        _estado.update(campos)


def a_ler(ficheiro: str, pagina: int, total: int) -> None:
    """A rasterizar a página `pagina` de `total` do documento `ficheiro`."""
    _pousar(A_LER, ficheiro=ficheiro, feito=pagina, total=total)


def a_compor(rid: int, ficheiro: str, ecra: int, total: int) -> None:
    """A compor o ecrã `ecra` de `total` do registo `rid`."""
    _pousar(A_COMPOR, registo=rid, ficheiro=ficheiro, feito=ecra, total=total)


def a_publicar(feito: int, total: int) -> None:
    """A reconstruir a televisão: `feito` de `total` editais tratados."""
    _pousar(A_PUBLICAR, feito=feito, total=total)


def parado() -> None:
    """Não há nada em curso."""
    _pousar(NADA)


def actual() -> dict[str, Any]:
    """Devolve uma CÓPIA do estado em curso.

    Cópia e não a referência viva: o painel serializa isto para JSON enquanto a
    thread de trabalho lhe pode estar a mexer, e ler e escrever a mesma
    estrutura em threads diferentes sem lock é a forma de ter um erro que só
    aparece em produção e nunca num teste. Já aconteceu neste projeto, com a
    lista de registos.
    """
    with _lock:
        return dict(_estado)


def frase() -> str:
    """Uma linha em português a descrever o que se está a fazer.

    Vive aqui e não no painel porque quem escreve o estado é quem sabe descrevê-lo,
    e porque o `/saude` também a serve — a mesma frase para quem olha para o
    browser e para quem sonda o serviço.
    """
    e = actual()
    fase = e.get("fase", NADA)
    if fase == NADA:
        return ""
    feito, total = e.get("feito", 0), e.get("total", 0)
    de_quantos = f" ({feito} de {total})" if total else ""
    if fase == A_LER:
        return f"A ler «{e.get('ficheiro', '')}»{de_quantos}"
    if fase == A_COMPOR:
        return f"A compor os ecrãs de «{e.get('ficheiro', '')}»{de_quantos}"
    if fase == A_PUBLICAR:
        return f"A actualizar a televisão{de_quantos}"
    return ""
