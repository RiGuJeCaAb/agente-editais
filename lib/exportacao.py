"""
exportacao.py — As pastas por estado, construídas a partir do registo.

Vieram de um pedido do posto, e de uma discussão que vale a pena deixar escrita
porque a resposta não foi a óbvia.

O pedido: que um edital mudasse de pasta conforme o estado — de `entrada/` para
`publicados/`, e daí para `retirados/`. A razão é boa e é operacional: quem
trabalha no serviço quer poder abrir o Explorador e ver o que está afixado, sem
depender de uma aplicação.

A objeção: nesse desenho, a pasta onde um ficheiro está passa a ser uma segunda
afirmação sobre o estado do edital, ao lado da que está no registo. E duas
afirmações sobre a mesma coisa divergem — não é «se», é «quando»: alguém arrasta
um ficheiro, o antivírus põe outro em quarentena, uma mudança falha a meio. A
partir daí, qual manda? O registo grava de forma atómica e regista quem fez o
quê; uma mudança de pasta não faz nem uma coisa nem outra, e não sabe dizer
**quem** publicou — que é a pergunta a que esta aplicação existe para responder.

A saída: o registo manda, e as pastas são uma **exportação**. Constroem-se a
pedido, são inteiramente reconstrutíveis, e ninguém lhes pergunta nada — se
divergirem, volta-se a gerá-las e fica resolvido. O posto tem a vista que
queria, e o sistema continua a ter uma só verdade.

O que se exporta é o **documento original**, que é o edital. Os PNG compostos
ficam em `saida/`, onde a televisão os lê: duplicá-los aqui gastaria o dobro do
disco para mostrar a mesma coisa. Vão nomeados no índice, para quem os quiser ir
buscar.
"""
from __future__ import annotations

import csv
import os
import shutil
from typing import Any

import diario
import documentos as doc
import originais as orig
import registo as reg_mod

_log = diario.obter("EXPORTAR")

# Estado do registo → subpasta da exportação. Só estes: um rascunho ou um
# validado ainda não são nada para quem consulta de fora, e um descartado foi
# posto de parte de propósito.
PASTAS = {
    reg_mod.PUBLICADO: "publicados",
    reg_mod.RETIRADO: "retirados",
}

# Marca que a pasta é gerada e pode ser deitada fora sem perda. A exportação
# recusa-se a limpar uma pasta que não a tenha: é a diferença entre apagar o que
# ela própria escreveu e apagar o que alguém lá pôs.
MARCA = "_GERADO_PELO_AGENTE.txt"

_TEXTO_DA_MARCA = (
    "Esta pasta é GERADA a partir do registo de editais.\n"
    "\n"
    "É uma vista, não o original. Pode ser apagada sem perda: volta a nascer\n"
    "com `python agente.py --exportar-pastas`.\n"
    "\n"
    "NÃO é aqui que se muda o estado de um edital. Mover um ficheiro daqui para\n"
    "outra pasta não retira nem publica nada — a verdade está no registo, e\n"
    "muda-se pelo painel, onde fica documentado quem o fez e quando.\n"
)


# Nome legível e ordenável para o ficheiro exportado.
def nome_exportado(r: dict, extensao: str) -> str:
    """Constrói o nome com que um edital aparece na pasta exportada.

    Formato: `AAAA-MM-DD_numero_assunto.ext`, com a data de publicação à cabeça
    para o gestor de ficheiros os ordenar cronologicamente sozinho — que é como
    alguém procura um edital: «foi aí por junho».

    Args:
        r: registo do edital.
        extensao: extensão do ficheiro original, com ponto.

    Returns:
        str: nome do ficheiro.
    """
    data = (r.get("data_publicacao") or "sem-data")[:10]
    numero = doc.slugify(r.get("numero") or "") or f"reg{r['id']:04d}"
    assunto = doc.slugify(r.get("assunto") or "")[:60] or "sem-assunto"
    return f"{data}_{numero}_{assunto}{extensao}"


# Garante que um nome não pisa outro já escrito na mesma pasta.
def _nome_livre(nome: str, r: dict, usados: set[str]) -> str:
    """Desambigua um nome já ocupado acrescentando-lhe o número do registo.

    Dois editais podem ter o mesmo número, a mesma data e o mesmo assunto — o
    mesmo edital registado duas vezes com ficheiros diferentes, que acontece. Sem
    isto, o segundo escrevia por cima do primeiro: a exportação dizia «2
    publicados», ficava um ficheiro em disco, e o índice apontava as duas linhas
    para ele. Perder um documento em silêncio é o pior que uma exportação pode
    fazer, porque quem a lê julga que está a ver tudo.

    O número do registo só entra quando é preciso: o caso comum fica com o nome
    legível, e a desambiguação é visível quando existe.

    Args:
        nome: nome proposto.
        r: registo, para o número de desempate.
        usados: nomes já escritos nesta pasta.

    Returns:
        str: um nome que ainda não está em uso.
    """
    if nome not in usados:
        return nome
    raiz, ext = os.path.splitext(nome)
    candidato = f"{raiz}_reg{r['id']:04d}{ext}"
    # Cinto e suspensórios: dois registos não partilham id, mas se um dia
    # partilharem, é preferível um nome feio a um documento a menos.
    n = 2
    while candidato in usados:
        candidato = f"{raiz}_reg{r['id']:04d}_{n}{ext}"
        n += 1
    return candidato


# Esvazia uma subpasta da exportação, e só se ela for mesmo da exportação.
def _conferir_se_e_nossa(pasta: str) -> None:
    """Recusa-se a deixar limpar uma pasta que não foi esta ferramenta a criar.

    Não é cerimónia: a exportação apaga ficheiros, e o caminho vem da
    configuração, que alguém pode ter apontado para o sítio errado. Sem a marca,
    não se toca — e diz-se porquê, em vez de falhar calado ou de levar à frente
    o trabalho de outra pessoa.

    Uma pasta vazia sem marca passa: não há nada a perder, e obrigar a criar a
    marca à mão seria cerimónia a sério.

    Args:
        pasta: subpasta a verificar.

    Raises:
        RuntimeError: se a pasta tiver ficheiros e não tiver a marca.
    """
    if not os.path.isdir(pasta):
        return
    if os.path.exists(os.path.join(pasta, MARCA)):
        return
    if os.listdir(pasta):
        raise RuntimeError(
            f"'{pasta}' tem ficheiros e não foi gerada por aqui (falta o "
            f"{MARCA}). A exportação não lhe toca. Escolha outra pasta em "
            f"'exportacao' no config.json, ou esvazie essa à mão.")


def _limpar(pasta: str) -> None:
    """Esvazia uma subpasta da exportação. Conferir primeiro com _conferir_se_e_nossa."""
    os.makedirs(pasta, exist_ok=True)
    for nome in os.listdir(pasta):
        alvo = os.path.join(pasta, nome)
        if os.path.isfile(alvo):
            os.remove(alvo)


def exportar(cfg: dict, registo) -> dict[str, Any]:
    """Reconstrói as pastas por estado a partir do registo.

    Apaga e refaz o conteúdo das subpastas que gere, para a exportação ser
    sempre um retrato do registo neste momento e nunca um histórico de si mesma.

    Args:
        cfg: configuração do agente (usa `exportacao` e `originais`).
        registo: o RegistoEntrada de onde sai tudo.

    Returns:
        dict: {"publicados": n, "retirados": n, "sem_original": [ids], "raiz": str}
    """
    raiz = cfg.get("exportacao", "")
    if not raiz:
        raise RuntimeError("falta a chave 'exportacao' na configuração")
    os.makedirs(raiz, exist_ok=True)

    contagem = {nome: 0 for nome in PASTAS.values()}
    sem_original: list[int] = []
    linhas: list[dict] = []

    # Conferir as duas pastas ANTES de tocar em qualquer uma. Validar à medida
    # que se limpa deixava a exportação a meio quando a segunda era recusada:
    # uma pasta com o retrato de agora, a outra com o de ontem, e uma mensagem
    # de erro a explicar só metade.
    for sub in PASTAS.values():
        _conferir_se_e_nossa(os.path.join(raiz, sub))

    for estado, sub in PASTAS.items():
        pasta = os.path.join(raiz, sub)
        _limpar(pasta)
        with open(os.path.join(pasta, MARCA), "w", encoding="utf-8") as f:
            f.write(_TEXTO_DA_MARCA)
        usados: set[str] = {MARCA}

        for r in registo.por_estado(estado):
            extensao = os.path.splitext(r.get("ficheiro_origem") or "")[1] or ".pdf"
            origem = orig.procurar(cfg.get("originais", ""), r.get("sha256", ""), extensao)
            destino = ""
            if origem:
                destino = _nome_livre(nome_exportado(r, extensao), r, usados)
                usados.add(destino)
                try:
                    shutil.copy2(origem, os.path.join(pasta, destino))
                    contagem[sub] += 1
                except OSError as ex:
                    _log.warning(f"registo #{r['id']} não foi copiado: {ex}")
                    destino = ""
            else:
                # Sem original arquivado não há o que exportar. O edital aparece
                # no índice à mesma, porque omiti-lo seria a exportação a fingir
                # que ele não existe.
                sem_original.append(r["id"])
            linhas.append({
                "id": r["id"], "estado": reg_mod.ESTADO_LABEL[estado],
                "numero": r.get("numero") or "", "assunto": r.get("assunto") or "",
                "entidade": r.get("entidade") or "",
                "data_publicacao": r.get("data_publicacao") or "",
                "data_retirada": r.get("data_retirada") or "",
                "afixado_em": r.get("afixado_em") or "",
                "afixado_por": r.get("afixado_por") or "",
                "desafixado_em": r.get("desafixado_em") or "",
                "desafixado_por": r.get("desafixado_por") or "",
                "sha256": r.get("sha256") or "",
                "ficheiro_exportado": os.path.join(sub, destino) if destino else "",
                "ecras_na_tv": " ".join(r.get("ficheiros_png") or []),
            })

    linhas.sort(key=lambda x: (x["data_publicacao"], x["id"]))
    caminho_indice = os.path.join(raiz, "INDICE.csv")
    # utf-8-sig: o Excel em português abre CSV em UTF-8 sem BOM com os acentos
    # partidos, e o índice existe precisamente para ser aberto no Excel.
    with open(caminho_indice, "w", encoding="utf-8-sig", newline="") as f:
        campos = list(linhas[0].keys()) if linhas else ["id"]
        escritor = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)

    _log.info(f"exportadas {contagem['publicados']} publicadas e "
              f"{contagem['retirados']} retiradas para '{raiz}'")
    return {"raiz": raiz, "indice": caminho_indice,
            "publicados": contagem["publicados"], "retirados": contagem["retirados"],
            "sem_original": sem_original}
