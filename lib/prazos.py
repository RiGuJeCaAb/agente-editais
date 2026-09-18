"""
prazos.py — Tipos de documento e as janelas de afixação que a lei lhes impõe.

Até aqui a data de retirada era um campo em branco que alguém preenchia de
cabeça. Funciona enquanto quem preenche souber o prazo de cor — e falha em
silêncio quando não sabe, quando é outra pessoa, ou quando o tipo de documento
muda. O erro não dá erro nenhum: o edital sai do ecrã cedo de mais ou tarde de
mais, e só se descobre se alguém reclamar.

O que este módulo faz é PROPOR o prazo e AVISAR quando o que está escrito fica
aquém do mínimo legal. O que NÃO faz é decidir: a data de retirada continua a
ser do posto, e o valor proposto é sobreposto sem cerimónia. A aplicação sabe
contar dias; não sabe se aquele documento é mesmo uma deliberação, nem se há
uma circunstância que justifique outra coisa. Essa é a razão de isto avisar em
vez de impor.

Base legal do tipo principal
----------------------------
Artigo 56.º do Anexo I da Lei n.º 75/2013, de 12 de setembro (regime jurídico
das autarquias locais): as deliberações dos órgãos autárquicos destinadas a ter
eficácia externa são publicadas em edital afixado nos lugares de estilo durante
CINCO dos 10 DIAS SUBSEQUENTES à tomada da deliberação, e divulgadas no sítio da
internet da autarquia.

Duas coisas a reter daí, porque a redação engana:
  - o mínimo de afixação é 5 dias, não 10;
  - os 10 dias são a JANELA dentro da qual esses cinco têm de caber, contada
    desde a deliberação. Afixar ao oitavo dia e retirar ao décimo terceiro dá
    cinco dias de afixação e mesmo assim não cumpre.

Os restantes tipos têm prazos próprios, que variam com a matéria e com o
regulamento de cada município. Vêm aqui com valores de partida e alteram-se em
config.json, sem tocar no código — ver carregar_tipos().
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Uma definição de tipo é configuração heterogénea: rótulos e normas em texto,
# prazos em número, e campos que só alguns tipos têm. Declarar o valor como
# Any é dizer isso à letra, em vez de inventar um tipo rígido que a primeira
# entrada do config.json contrariaria.
Definicao = dict[str, Any]

# Identificador do tipo que se usa quando nada foi escolhido. Existe para os
# editais anteriores a esta onda continuarem a abrir sem migração destrutiva.
TIPO_POR_OMISSAO = "outro"

# Os tipos que vêm de origem. Cada um declara a sua base legal e a fonte, porque
# um prazo sem proveniência é um número que ninguém pode confirmar nem contestar.
#
#   dias_minimos : dias de afixação que a lei exige, ou None se não houver regra
#                  fixa (caso em que só se propõe, sem avisar de incumprimento).
#   dias_janela  : prazo, contado da data do documento, dentro do qual a
#                  afixação tem de caber por inteiro. None = sem janela.
TIPOS_DE_ORIGEM: dict[str, Definicao] = {
    "deliberacao_orgao_autarquico": {
        "rotulo": "Deliberação de órgão autárquico",
        "dias_minimos": 5,
        "dias_janela": 10,
        "base_legal": "Artigo 56.º do Anexo I da Lei n.º 75/2013, de 12 de setembro",
        "fonte": "https://diariodarepublica.pt/dr/legislacao-consolidada/lei/2013-56366098",
        "nota": ("Afixado nos lugares de estilo durante cinco dos 10 dias "
                 "subsequentes à deliberação, e divulgado no sítio da internet."),
    },
    "edital_generico": {
        "rotulo": "Edital",
        "dias_minimos": None,
        "dias_janela": None,
        "base_legal": "",
        "fonte": "",
        "nota": ("Sem prazo fixo no sistema: o prazo consta do próprio edital ou "
                 "do ato que o determinou. Confirme e escreva a data de retirada."),
        "dias_sugeridos": 30,
    },
    "aviso": {
        "rotulo": "Aviso",
        "dias_minimos": None,
        "dias_janela": None,
        "base_legal": "",
        "fonte": "",
        "nota": "Prazo definido pelo ato que determinou o aviso.",
        "dias_sugeridos": 15,
    },
    "anuncio_de_procedimento": {
        "rotulo": "Anúncio de procedimento",
        "dias_minimos": None,
        "dias_janela": None,
        "base_legal": "",
        "fonte": "",
        "nota": ("O prazo acompanha o do procedimento (apresentação de "
                 "propostas, candidaturas ou reclamações). Confirme na peça."),
        "dias_sugeridos": 30,
    },
    TIPO_POR_OMISSAO: {
        "rotulo": "Outro documento",
        "dias_minimos": None,
        "dias_janela": None,
        "base_legal": "",
        "fonte": "",
        "nota": "Sem prazo conhecido pelo sistema. A data de retirada é livre.",
        "dias_sugeridos": None,
    },
}

# Preenchido por carregar_tipos(). Começa igual aos de origem, para o módulo ser
# utilizável sem configuração nenhuma (que é o caso dos testes).
TIPOS: dict[str, Definicao] = {k: dict(v) for k, v in TIPOS_DE_ORIGEM.items()}


def carregar_tipos(cfg: dict | None = None) -> dict[str, Definicao]:
    """Funde os tipos de origem com os que o município definiu em config.json.

    Um município pode ter prazos próprios fixados em regulamento, e não faz
    sentido obrigar a mexer no código para os declarar. Um tipo do config com o
    mesmo identificador de um de origem SOBREPÕE apenas os campos que traz — o
    que permite, por exemplo, mudar só o prazo sugerido de um edital genérico
    sem reescrever a base legal.

    Args:
        cfg: configuração do agente. A chave lida é "tipos_de_documento".

    Returns:
        dict: a tabela efetiva, que fica também em TIPOS.
    """
    tabela: dict[str, Definicao] = {k: dict(v) for k, v in TIPOS_DE_ORIGEM.items()}
    for ident, definicao in ((cfg or {}).get("tipos_de_documento") or {}).items():
        if not isinstance(definicao, dict):
            continue
        base = dict(tabela.get(ident, TIPOS_DE_ORIGEM[TIPO_POR_OMISSAO]))
        base.update(definicao)
        base.setdefault("rotulo", ident)
        tabela[ident] = base
    TIPOS.clear()
    TIPOS.update(tabela)
    return TIPOS


def tipo(ident: str | None) -> Definicao:
    """Devolve a definição de um tipo, recuando para o tipo por omissão.

    Nunca levanta exceção: um identificador desconhecido (vindo de um registo
    antigo, ou de um config entretanto alterado) não pode impedir um edital de
    abrir no painel.
    """
    return TIPOS.get(ident or TIPO_POR_OMISSAO, TIPOS[TIPO_POR_OMISSAO])


def tipos_para_painel() -> list[dict]:
    """Lista os tipos numa forma pronta a preencher um seletor no painel."""
    return [{"id": ident, "rotulo": d["rotulo"], "nota": d.get("nota", ""),
             "base_legal": d.get("base_legal", ""), "fonte": d.get("fonte", ""),
             "dias_minimos": d.get("dias_minimos")}
            for ident, d in TIPOS.items()]


def propor_retirada(ident: str | None, afixacao: date | str | None) -> str | None:
    """Propõe a data de retirada de um documento afixado numa dada data.

    A proposta é a data em que a afixação passa a poder cessar sem incumprimento
    — o mínimo legal, não o máximo. Quem quiser deixar mais tempo escreve outra
    data, e ninguém se queixa: manter um edital além do prazo não viola nada.

    Args:
        ident: identificador do tipo de documento.
        afixacao: data de afixação (date ou ISO).

    Returns:
        str | None: data em ISO, ou None se o tipo não tiver regra nem sugestão.
    """
    inicio = _como_data(afixacao)
    if inicio is None:
        return None
    d = tipo(ident)
    dias = d.get("dias_minimos") or d.get("dias_sugeridos")
    return (inicio + timedelta(days=int(dias))).isoformat() if dias else None


def verificar(ident: str | None, afixacao: date | str | None,
              retirada: date | str | None,
              data_do_documento: date | str | None = None) -> list[dict]:
    """Confere um par afixação/retirada contra a regra do tipo, e devolve avisos.

    Devolve avisos e não erros, de propósito: o sistema não bloqueia uma decisão
    do posto. O que faz é garantir que, se a decisão ficar aquém do que a lei
    pede, ninguém pode dizer que não foi avisado — e o aviso vem com a norma ao
    lado, para ser verificável em vez de ter de se acreditar nele.

    Args:
        ident: tipo de documento.
        afixacao: data em que foi (ou vai ser) afixado.
        retirada: data prevista de retirada; None = sem data marcada.
        data_do_documento: data da deliberação ou do documento, de onde se conta
            a janela legal. Sem ela, a janela não é verificada.

    Returns:
        list[dict]: avisos, cada um com 'grau' (aviso|informacao), 'texto' e,
        quando existe, 'base_legal'.
    """
    d = tipo(ident)
    avisos: list[dict] = []
    inicio, fim = _como_data(afixacao), _como_data(retirada)
    documento = _como_data(data_do_documento)

    # Retirada anterior à afixação. Vale para qualquer tipo, tenha ou não prazo
    # legal, e diz-se antes de tudo o resto: enquanto isto estiver assim, os
    # outros avisos sairiam com contas negativas, que confundem em vez de
    # avisarem. Foi assim que este caso se descobriu — um teste mostrou "a
    # afixação dura -79 dia(s)".
    if inicio and fim and fim < inicio:
        return [{
            "grau": "aviso",
            "texto": (f"A data de retirada ({fim.isoformat()}) é anterior à da "
                      f"afixação ({inicio.isoformat()}): o edital sai do ecrã "
                      f"assim que for publicado."),
            "base_legal": d.get("base_legal", ""),
        }]

    # Retirada já passada, com afixação ainda por acontecer. O edital seria
    # publicado e retirado no mesmo ciclo do agente, sem ninguém perceber porquê.
    if fim and not inicio and fim < date.today():
        return [{
            "grau": "aviso",
            "texto": (f"A data de retirada ({fim.isoformat()}) já passou: "
                      f"publicado agora, o edital sai do ecrã no ciclo seguinte."),
            "base_legal": d.get("base_legal", ""),
        }]

    minimos = d.get("dias_minimos")
    if minimos and inicio:
        if fim is None:
            avisos.append({
                "grau": "informacao",
                "texto": (f"Sem data de retirada: fica no ecrã indefinidamente. "
                          f"O mínimo legal é {minimos} dias de afixação."),
                "base_legal": d.get("base_legal", ""),
            })
        else:
            dias = (fim - inicio).days
            if dias < minimos:
                avisos.append({
                    "grau": "aviso",
                    "texto": (f"A afixação dura {dias} dia(s), abaixo do mínimo "
                              f"de {minimos} exigido para este tipo de documento."),
                    "base_legal": d.get("base_legal", ""),
                })

    janela = d.get("dias_janela")
    if janela and documento:
        limite = documento + timedelta(days=int(janela))
        if fim and fim > limite:
            avisos.append({
                "grau": "aviso",
                "texto": (f"A afixação termina a {fim.isoformat()}, depois do "
                          f"limite de {limite.isoformat()} — {janela} dias após "
                          f"a data do documento ({documento.isoformat()}). Os "
                          f"dias fora da janela não contam para o mínimo."),
                "base_legal": d.get("base_legal", ""),
            })
        if inicio and inicio > limite:
            avisos.append({
                "grau": "aviso",
                "texto": (f"A afixação começa a {inicio.isoformat()}, já depois "
                          f"de fechada a janela de {janela} dias que terminou a "
                          f"{limite.isoformat()}."),
                "base_legal": d.get("base_legal", ""),
            })
        elif inicio and minimos and (limite - inicio).days < minimos:
            avisos.append({
                "grau": "aviso",
                "texto": (f"Da afixação até ao fim da janela legal "
                          f"({limite.isoformat()}) vão {(limite - inicio).days} "
                          f"dia(s), menos do que os {minimos} exigidos: mesmo "
                          f"deixando o edital mais tempo, o prazo não se cumpre."),
                "base_legal": d.get("base_legal", ""),
            })
    return avisos


def _como_data(valor: date | str | None) -> date | None:
    """Aceita date, texto ISO ou None, e devolve date ou None.

    Tolerante por desenho: uma data mal escrita num campo de formulário não pode
    rebentar a verificação de prazos e levar a página abaixo.
    """
    if valor is None or isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None
