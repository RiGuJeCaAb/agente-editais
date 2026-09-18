"""
originais.py — Arquivo imutável dos documentos, endereçado pelo conteúdo.

O problema que resolve: a composição das imagens relia o ficheiro da pasta
'entrada/'. Quem limpasse essa pasta — e ninguém lhe chamou "arquivo", por isso
é natural que a limpem — deixava os editais publicados sem forma de serem
recompostos. Pior do que isso: desaparecia o documento que foi afixado, e a
certidão passava a afirmar que se afixou uma coisa que já não existia em lado
nenhum. Um registo público que aponta para um ficheiro apagado não é registo.

Endereçado pelo conteúdo, e não pelo nome: o nome do ficheiro é do utilizador e
muda (renomear, "(1)", "_final_v2"), o conteúdo é do documento e não muda. Um
mesmo documento largado duas vezes com nomes diferentes ocupa espaço uma vez, e
um ficheiro adulterado deixa de corresponder ao endereço por onde é procurado —
o que faz do arquivo, de graça, um detetor de alteração.

Estrutura: originais/ab/abcdef...12.pdf, com os dois primeiros caracteres do
resumo a formar a pasta. Não é enfeite: alguns sistemas de ficheiros degradam-se
com dezenas de milhares de entradas numa só pasta, e 256 subpastas adiam esse
problema por muito mais editais do que um município produz numa década.
"""
from __future__ import annotations

import hashlib
import os
import shutil

# Blocos de 64 KB: o mesmo que o resto do projeto usa para resumir ficheiros.
BLOCO = 65536


def resumo(caminho: str) -> str:
    """Calcula o SHA-256 do conteúdo de um ficheiro.

    SHA-256 e não o SHA-1 que o agente já usava para detetar repetições: o SHA-1
    tem colisões demonstradas desde 2017 e, embora para detetar um ficheiro
    repetido isso seja irrelevante, aqui o resumo passa a ser citado numa
    certidão como identificação do documento afixado. Um identificador que
    aparece num documento oficial merece uma função sem colisões conhecidas.

    Args:
        caminho: ficheiro a resumir.

    Returns:
        str: resumo em hexadecimal.
    """
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


def caminho_no_arquivo(pasta: str, sha256: str, extensao: str) -> str:
    """Devolve o caminho onde um documento com este resumo é guardado."""
    return os.path.join(pasta, sha256[:2], sha256 + extensao.lower())


def arquivar(pasta: str, origem: str, sha256: str | None = None) -> tuple[str, str]:
    """Copia um documento para o arquivo imutável, se ainda lá não estiver.

    COPIA e não move, de propósito. Mover faria os ficheiros desaparecerem da
    pasta de entrada assim que fossem lidos, o que assusta quem os largou lá e
    ainda não viu nada acontecer no painel. A pasta de entrada continua a ser de
    quem a usa, e pode ser limpa a qualquer momento sem consequências.

    A escrita é feita para um temporário e só depois renomeada, para uma cópia
    interrompida não deixar no arquivo um ficheiro truncado com um nome que
    promete um conteúdo que ele já não tem.

    Args:
        pasta: raiz do arquivo.
        origem: ficheiro a arquivar.
        sha256: resumo já calculado, para não o repetir.

    Returns:
        tuple[str, str]: (resumo, caminho no arquivo).
    """
    sha = sha256 or resumo(origem)
    extensao = os.path.splitext(origem)[1]
    destino = caminho_no_arquivo(pasta, sha, extensao)
    if os.path.exists(destino):
        return sha, destino          # já arquivado: o conteúdo é o mesmo, por definição
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    temporario = destino + ".tmp"
    shutil.copy2(origem, temporario)
    os.replace(temporario, destino)
    return sha, destino


def procurar(pasta: str, sha256: str, extensao: str = "") -> str | None:
    """Encontra um documento no arquivo pelo seu resumo.

    A extensão é opcional porque nem sempre se sabe: um registo antigo pode ter
    o resumo mas não o nome do ficheiro. Sem ela, procura-se na subpasta o
    ficheiro que comece por aquele resumo.

    Args:
        pasta: raiz do arquivo.
        sha256: resumo do documento.
        extensao: extensão conhecida (com ponto), se houver.

    Returns:
        str | None: caminho do ficheiro, ou None se não estiver arquivado.
    """
    if not sha256:
        return None
    if extensao:
        alvo = caminho_no_arquivo(pasta, sha256, extensao)
        if os.path.exists(alvo):
            return alvo
    subpasta = os.path.join(pasta, sha256[:2])
    if not os.path.isdir(subpasta):
        return None
    for nome in os.listdir(subpasta):
        if nome.startswith(sha256) and not nome.endswith(".tmp"):
            return os.path.join(subpasta, nome)
    return None


def conferir(pasta: str, sha256: str, extensao: str = "") -> bool:
    """Verifica se o ficheiro arquivado ainda corresponde ao resumo por que é conhecido.

    É o que transforma o arquivo em prova em vez de mera cópia: se alguém
    substituir o documento no disco, o resumo deixa de bater e isto dá por isso.
    Não é chamado a cada publicação — resumir ficheiros grandes custa tempo — mas
    existe para uma verificação periódica ou a pedido de quem audita.

    Returns:
        bool: True se o ficheiro existe e o conteúdo corresponde.
    """
    caminho = procurar(pasta, sha256, extensao)
    # Escrito assim e não `bool(caminho) and resumo(caminho)`: o segundo passa a
    # None a uma função que espera str sempre que o ficheiro não existir. Hoje o
    # curto-circuito salva-o, mas é o género de linha que alguém reordena.
    if caminho is None:
        return False
    return resumo(caminho) == sha256


def estatisticas(pasta: str) -> dict:
    """Conta quantos documentos e quantos bytes o arquivo guarda."""
    total, bytes_ = 0, 0
    for raiz, _pastas, ficheiros in os.walk(pasta):
        for nome in ficheiros:
            if nome.endswith(".tmp"):
                continue
            total += 1
            try:
                bytes_ += os.path.getsize(os.path.join(raiz, nome))
            except OSError:
                pass
    return {"documentos": total, "bytes": bytes_}
