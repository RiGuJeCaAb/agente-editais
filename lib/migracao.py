"""
migracao.py — Traz para o registo de entrada os editais do modelo antigo.

Até à versão 0.13 o agente tinha DOIS caminhos de publicação a viver lado a lado:

  - o antigo, automático: lia a pasta, compunha as imagens e punha-as no ecrã
    sem ninguém ver, guardando tudo em `editais.json` mais um `retiradas.txt`
    editado à mão;
  - o novo, com validação: os documentos entram como rascunho e só vão ao ecrã
    depois de uma pessoa os aprovar, com tudo em `registo_entrada.json`.

O antigo sai agora, e não é por gosto de limpar. Desde a Onda 2 a aplicação
emite uma certidão que diz QUEM afixou cada edital. Um caminho que publica sem
ninguém não tem essa resposta — e mantê-lo era garantir que, mais cedo ou mais
tarde, alguém pediria a certidão de um edital afixado por ninguém.

Este módulo existe para que quem tenha dados no modelo antigo não os perca. É
código com prazo: quando não houver instalações por migrar, apaga-se.

O que se consegue reconstruir, e o que não
------------------------------------------
O `editais.json` guardava um registo por ECRÃ, não por edital — um edital de
cinco folhas aparecia lá três vezes, com `parte` e `total_partes`. A migração
reagrupa-os no edital a que pertencem.

O que NÃO existe no modelo antigo, e que por isso se assume com honestidade:

  - **quem** afixou. Não havia contas. Fica `migracao`, e a certidão de um
    edital migrado di-lo em vez de inventar um nome.
  - a **hora** exata da afixação. Usa-se o `processado_em` do primeiro ecrã, que
    é quando a imagem foi composta — o mais próximo que os dados permitem.
  - o **tipo de documento**. Fica o tipo por omissão, e o prazo não é verificado
    até alguém o escolher no painel.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

import armazenamento as arm
import diario
import prazos as pr

_log = diario.obter("MIGRACAO")

# Quem aparece como autor nos registos migrados. Não é um utilizador real e não
# se finge que é: quem ler a certidão de um edital migrado vê isto e percebe que
# o ato é anterior às contas nominais.
AUTOR = "migracao"

# Sufixo dado aos ficheiros do modelo antigo depois de migrados. Renomear e não
# apagar: se a migração tiver interpretado alguma coisa mal, os dados de origem
# continuam lá para se poder conferir.
SUFIXO_MIGRADO = ".migrado"


def _norm(texto: str) -> str:
    """Normaliza uma chave para comparação: minúsculas, só letras e dígitos.

    Cópia deliberada da função homónima do agente antigo. Está aqui e não
    importada de lá porque o agente antigo está a ser apagado, e uma migração
    que dependesse do código que ela substitui não sobreviveria à sua própria
    razão de existir.
    """
    return "".join(ch for ch in (texto or "").lower() if ch.isalnum())


def _data(texto: str) -> date | None:
    """Interpreta uma data em ISO, DD/MM/AAAA ou DD-MM-AAAA, ou devolve None."""
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime((texto or "").strip(), formato).date()
        except ValueError:
            continue
    return None


def ler_retiradas(caminho: str) -> dict[str, date]:
    """Lê o retiradas.txt antigo e devolve {chave_normalizada: data}.

    Tolerante como o original era: ignora linhas em branco e comentários, aceita
    '=' ou ';' como separador, e salta datas mal escritas em vez de rebentar.
    """
    mapa: dict[str, date] = {}
    if not os.path.exists(caminho):
        return mapa
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            separador = "=" if "=" in linha else (";" if ";" in linha else None)
            if not separador:
                continue
            chave, _, valor = linha.partition(separador)
            data = _data(valor)
            if data:
                mapa[_norm(chave)] = data
    return mapa


def _retirada_de(edital: dict, mapa: dict[str, date]) -> date | None:
    """Descobre a data de retirada de um edital, por número ou por assunto.

    Mesma ordem do original: primeiro o número, que é fiável; só depois a
    correspondência parcial pelo assunto, para quem preferiu escrever texto.
    """
    numero = _norm(edital.get("numero", ""))
    if numero and numero in mapa:
        return mapa[numero]
    assunto = _norm(edital.get("assunto", ""))[:40]
    for chave, data in mapa.items():
        if chave and (chave in assunto or assunto in chave):
            return data
    return None


def agrupar_por_edital(editais: list[dict]) -> list[list[dict]]:
    """Reagrupa os ecrãs do modelo antigo nos editais a que pertencem.

    O editais.json guardava um registo por ECRÃ: um edital de cinco folhas
    aparecia lá três vezes, com parte 1, 2 e 3. Aqui voltam a ser um.

    A chave é o número quando existe, o assunto quando não. Preserva-se a ordem
    de chegada, e dentro de cada edital a ordem das partes.
    """
    ordem: list[str] = []
    grupos: dict[str, list[dict]] = {}
    for entrada in editais:
        chave = _norm(entrada.get("numero") or entrada.get("assunto") or
                      entrada.get("ficheiro_origem") or str(entrada.get("indice")))
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(entrada)
    for chave in grupos:
        grupos[chave].sort(key=lambda e: (e.get("parte") or 0, e.get("indice") or 0))
    return [grupos[chave] for chave in ordem]


def _hash_do_ficheiro(estado: dict, nome_origem: str) -> str:
    """Recupera do estado.json antigo o SHA-1 de um ficheiro de origem.

    Serve para o registo migrado manter a impressão digital que impede o
    documento de ser reingerido como novo se voltar a aparecer na pasta.
    """
    for h, info in (estado.get("processados") or {}).items():
        if info.get("ficheiro") == nome_origem:
            return h
    return ""


def precisa_de_migrar(cfg: dict) -> bool:
    """Indica se há dados no modelo antigo à espera de serem trazidos."""
    caminho = cfg.get("registo_antigo", "")
    if not caminho or not os.path.exists(caminho):
        return False
    return bool((arm.ler_json(caminho, {}) or {}).get("editais"))


def migrar(cfg: dict, registo) -> int:
    """Traz os editais do modelo antigo para o registo de entrada.

    Corre uma vez, no arranque, e só se houver o que migrar. Os registos entram
    já em estado PUBLICADO ou RETIRADO conforme a data de retirada — não faria
    sentido pôr em rascunho editais que estiveram meses no ecrã e pedir a alguém
    que os validasse agora.

    Args:
        cfg: configuração do agente.
        registo: o RegistoEntrada de destino.

    Returns:
        int: quantos editais foram migrados.
    """
    import registo as reg_mod

    caminho_antigo = cfg.get("registo_antigo", "")
    antigo = arm.ler_json(caminho_antigo, {"editais": []}) or {"editais": []}
    entradas = antigo.get("editais") or []
    if not entradas:
        return 0

    estado = arm.ler_json(cfg.get("estado_antigo", ""), {"processados": {}}) or {}
    retiradas = ler_retiradas(cfg.get("retiradas_antigo", ""))
    hoje = date.today()
    migrados = 0

    for grupo in agrupar_por_edital(entradas):
        cabeca = grupo[0]
        hash_ficheiro = _hash_do_ficheiro(estado, cabeca.get("ficheiro_origem", ""))
        # Sem hash conhecido, inventa-se um identificador estável a partir do
        # que há. Não serve para detetar o mesmo ficheiro outra vez, mas serve
        # para o registo não ficar com o campo vazio e para não colidir.
        if not hash_ficheiro:
            hash_ficheiro = "migrado:" + _norm(
                (cabeca.get("numero") or "") + (cabeca.get("assunto") or ""))[:40]
        if registo.hash_existe(hash_ficheiro):
            continue

        meta: dict[str, Any] = {
            "assunto": cabeca.get("assunto", ""),
            "numero": cabeca.get("numero", ""),
            "entidade": cabeca.get("entidade", ""),
            "data_publicacao": cabeca.get("data_publicacao"),
            "tipo": pr.TIPO_POR_OMISSAO,
            "confianca": {},
        }
        novo = registo.criar_rascunho(
            ficheiro_origem=cabeca.get("ficheiro_origem", ""),
            hash_ficheiro=hash_ficheiro,
            num_paginas=sum(e.get("folhas_neste_ecra", 1) for e in grupo),
            meta=meta, utilizador=AUTOR)

        registo.definir(novo["id"],
                        ficheiros_png=[e["ficheiro_png"] for e in grupo
                                       if e.get("ficheiro_png")])

        retirada = _retirada_de(cabeca, retiradas)
        if retirada:
            registo.editar(novo["id"], {"data_retirada": retirada.isoformat()},
                           utilizador=AUTOR)

        # O percurso de estados é reconstruído pelo caminho legítimo, para o
        # histórico e o jornal de auditoria ficarem coerentes com os de um
        # edital normal — e não com um estado pousado à força.
        registo.mover_estado(novo["id"], reg_mod.VALIDADO, utilizador=AUTOR,
                             nota="Migrado do modelo automático anterior")
        registo.mover_estado(novo["id"], reg_mod.PUBLICADO, utilizador=AUTOR,
                             nota="Já estava no expositor à data da migração")
        if retirada and retirada < hoje:
            registo.mover_estado(novo["id"], reg_mod.RETIRADO, utilizador=AUTOR,
                                 nota=f"Retirada já vencida à data da migração ({retirada})")

        # O instante de afixação é o do primeiro ecrã composto: é o mais próximo
        # que os dados antigos permitem. Sobrepõe-se ao que mover_estado acabou
        # de carimbar (que seria agora), porque a afixação aconteceu no passado.
        carimbos = [e["processado_em"] for e in grupo if e.get("processado_em")]
        processado = min(carimbos) if carimbos else None
        if processado:
            registo.definir_instante_de_afixacao(novo["id"], processado, AUTOR)

        migrados += 1
        _log.info(f"edital '{cabeca.get('numero') or cabeca.get('assunto', '')[:40]}' "
                  f"migrado como registo #{novo['id']} ({len(grupo)} ecrã(s))")

    if migrados:
        for chave in ("registo_antigo", "estado_antigo", "retiradas_antigo"):
            arquivar(cfg.get(chave, ""))
        _log.info(f"{migrados} edital(is) migrados. Os ficheiros do modelo antigo "
                  f"foram renomeados para '{SUFIXO_MIGRADO}' e podem ser conferidos.")
    return migrados


def arquivar(caminho: str) -> None:
    """Renomeia um ficheiro do modelo antigo, para a migração não repetir.

    Renomeia em vez de apagar: se a migração tiver interpretado alguma coisa
    mal, os dados de origem continuam lá para se poder conferir — e é mais
    barato deixá-los do que explicar porque desapareceram.
    """
    if not caminho or not os.path.exists(caminho):
        return
    destino = caminho + SUFIXO_MIGRADO
    if os.path.exists(destino):
        destino = f"{caminho}.{datetime.now():%Y%m%d%H%M%S}{SUFIXO_MIGRADO}"
    try:
        os.replace(caminho, destino)
    except OSError as e:
        _log.warning(f"não foi possível renomear {caminho}: {e}")
