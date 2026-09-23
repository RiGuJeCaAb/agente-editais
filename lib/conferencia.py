"""
conferencia.py — Diz o que está desalinhado entre o registo e o disco.

O registo de entrada manda: é ele que tem os estados, as datas, quem afixou e o
rasto de auditoria. Mas o disco tem os ficheiros, e as duas coisas separam-se —
uma pasta que alguém limpou à mão, uma migração que trouxe editais cujos
originais já não existem, um PNG que sobreviveu a um registo.

Este módulo vai ver e **conta**. Não apaga nada, não move nada, não corrige
nada. É deliberado: as decisões sobre o que fazer a um edital municipal são de
quem responde por ele, e uma ferramenta que arruma sozinha é uma ferramenta em
que é preciso confiar cegamente. Esta só tem de ser lida.

Nasceu do caso concreto: depois da migração do modelo antigo ficaram rascunhos
sem data de publicação e sem ficheiro de origem — que não se conseguem validar
nem publicar. Dava para os descartar um a um no painel, mas primeiro era preciso
adivinhar quais eram. Agora pergunta-se.
"""
from __future__ import annotations

import os
from typing import Any

import diario
import originais as orig
import registo as reg_mod

_log = diario.obter("CONFERIR")

# Um ecrã de edital é um PNG. A pasta de saída tem mais coisas — a página da
# TV, o slides.json, os ZIP de arquivo — e o que lá aparecer amanhã não se sabe:
# uma cópia .bak.1 de uma gravação atómica, por exemplo, não acaba em .json e
# seria contada como ecrã órfão se a lista fosse de exclusões. Listar o que
# CONTA em vez do que não conta é a inversão que torna isto estável.
_EXTENSAO_DE_ECRA = ".png"


# Diz se o original de um registo existe em algum sítio de onde se possa ler.
def _onde_esta_o_original(cfg: dict, r: dict) -> str | None:
    """Procura o original de um registo, pela mesma ordem que a composição usa.

    Primeiro o arquivo imutável, endereçado pelo SHA-256; depois, por recurso, a
    pasta de entrada e a de tratados, pelo nome. É esta a ordem que interessa
    reproduzir: se a composição não o encontra, o edital não vai ao ecrã, e é
    isso que a conferência tem de saber dizer.

    Args:
        cfg: configuração do agente.
        r: registo.

    Returns:
        str | None: caminho do ficheiro, ou None se não estiver em lado nenhum.
    """
    nome = r.get("ficheiro_origem") or ""
    extensao = os.path.splitext(nome)[1]
    caminho = orig.procurar(cfg.get("originais", ""), r.get("sha256", ""), extensao)
    if caminho:
        return caminho
    if not nome:
        return None
    for chave in ("entrada", "tratados"):
        pasta = cfg.get(chave, "")
        if pasta:
            alternativa = os.path.join(pasta, nome)
            if os.path.isfile(alternativa):
                return alternativa
    return None


# Lista os ficheiros de uma pasta, sem entrar em subpastas.
def _ficheiros(pasta: str) -> set[str]:
    """Nomes dos ficheiros à cabeça de uma pasta (subpastas não contam)."""
    if not pasta or not os.path.isdir(pasta):
        return set()
    return {n for n in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, n))}


def conferir(cfg: dict, registo) -> dict[str, Any]:
    """Compara o registo com o disco e devolve o que não bate certo.

    Args:
        cfg: configuração do agente.
        registo: o RegistoEntrada a conferir.

    Returns:
        dict: com as chaves
            - `registos`: quantos registos existem, por estado;
            - `sem_original`: registos cujo documento não está em lado nenhum;
            - `rascunhos_impossiveis`: subconjunto dos anteriores que também não
              têm data de publicação, e que portanto não se conseguem validar
              nem publicar — ficam na fila para sempre;
            - `png_orfaos`, `previas_orfas`: ficheiros que nenhum registo reclama;
            - `originais_orfaos`: documentos arquivados que nenhum registo aponta;
            - `arquivo`: contagem e tamanho do arquivo imutável.
    """
    todos = registo.todos()
    por_estado: dict[str, int] = {}
    for e in reg_mod.ESTADOS:
        por_estado[e] = len(registo.por_estado(e))

    sem_original, impossiveis = [], []
    png_reclamados: set[str] = set()
    previas_reclamadas: set[str] = set()
    resumos_reclamados: set[str] = set()

    for r in todos:
        png_reclamados.update(r.get("ficheiros_png") or [])
        previas_reclamadas.update(r.get("ficheiros_previa") or [])
        if r.get("sha256"):
            resumos_reclamados.add(r["sha256"])
        # Um descartado sem original não é um problema: foi posto de parte de
        # propósito, e ir chatear com ele seria ruído por cima de uma decisão
        # que já foi tomada.
        if r["estado"] == reg_mod.DESCARTADO:
            continue
        if _onde_esta_o_original(cfg, r) is None:
            resumo = {"id": r["id"], "estado": r["estado"],
                      "numero": r.get("numero") or "", "assunto": (r.get("assunto") or "")[:70],
                      "ficheiro_origem": r.get("ficheiro_origem") or "",
                      "tem_data": bool(r.get("data_publicacao"))}
            sem_original.append(resumo)
            if r["estado"] == reg_mod.RASCUNHO and not r.get("data_publicacao"):
                impossiveis.append(resumo)

    png_no_disco = {n for n in _ficheiros(cfg.get("saida", ""))
                    if n.lower().endswith(_EXTENSAO_DE_ECRA)}
    previas_no_disco = _ficheiros(cfg.get("previas", ""))

    originais_orfaos = []
    pasta_arquivo = cfg.get("originais", "")
    if pasta_arquivo and os.path.isdir(pasta_arquivo):
        for raiz, _p, ficheiros in os.walk(pasta_arquivo):
            for nome in ficheiros:
                if nome.endswith(".tmp"):
                    continue
                resumo = os.path.splitext(nome)[0]
                if resumo not in resumos_reclamados:
                    originais_orfaos.append(os.path.relpath(
                        os.path.join(raiz, nome), pasta_arquivo))

    return {
        "registos": {"total": len(todos), "por_estado": por_estado},
        "sem_original": sem_original,
        "rascunhos_impossiveis": impossiveis,
        "png_orfaos": sorted(png_no_disco - png_reclamados),
        "previas_orfas": sorted(previas_no_disco - previas_reclamadas),
        "originais_orfaos": sorted(originais_orfaos),
        "arquivo": orig.estatisticas(pasta_arquivo) if pasta_arquivo else
                   {"documentos": 0, "bytes": 0},
    }


def ha_problemas(r: dict) -> bool:
    """Diz se a conferência encontrou alguma coisa que mereça atenção."""
    return bool(r["sem_original"] or r["png_orfaos"] or
                r["previas_orfas"] or r["originais_orfaos"])
