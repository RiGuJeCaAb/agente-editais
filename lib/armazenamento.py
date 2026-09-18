# -*- coding: utf-8 -*-
"""
armazenamento.py — Gravação durável de ficheiros de estado e trilho de auditoria.

Porque existe este módulo: o agente guardava o registo com um `open(path, "w")`
seguido de `json.dump`. Entre o truncar e o escrever há uma janela em que o
ficheiro está a meio. Um corte de energia, um `kill -9` ou um disco cheio nessa
janela deixam o registo ilegível — e, como o `RegistoEntrada.__init__` não tinha
recuperação, o agente deixava de arrancar de todo. Foi reproduzido: truncar o
ficheiro a meio dá `JSONDecodeError: Unterminated string` no arranque seguinte.

Num organismo público isto é o pior modo de falha possível, porque o ficheiro
perdido é justamente o que responde a "quem afixou este edital, e quando".

O módulo resolve-o em três camadas, e não numa só:

  1. ESCRITA ATÓMICA — escreve-se para um temporário na MESMA pasta, força-se ao
     disco (fsync) e só então se troca pelo definitivo com os.replace(), que é
     atómico em POSIX e em Windows. O leitor nunca vê um ficheiro a meio: vê o
     anterior ou o novo.
  2. GERAÇÕES — antes de trocar, a versão atual passa a .bak.1, a .bak.1 a .bak.2,
     etc. Se um defeito nosso gravar lixo bem-formado, há para onde recuar.
  3. JORNAL APENAS-ACRESCENTO — a auditoria deixa de viver só dentro do documento
     que se reescreve por inteiro. Cada evento é também acrescentado a um .jsonl,
     uma linha por evento, com fsync. Um ficheiro que só cresce não pode ser
     corrompido por uma reescrita, e uma linha truncada no fim custa um evento,
     não o histórico todo.

Sem dependências novas: tudo biblioteca padrão, como o resto do projeto.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

# Quantas gerações anteriores se guardam ao lado do ficheiro (ficheiro.bak.1, .2, ...).
# Três chega: cobre o erro que se nota no próprio dia e o que só se nota no seguinte,
# sem encher a pasta de cópias que ninguém vai ler.
GERACOES_POR_OMISSAO = 3


def _forcar_ao_disco(f) -> None:
    """Garante que o que foi escrito chegou mesmo ao disco, e não só ao buffer do SO.

    Sem isto, o os.replace() pode trocar um ficheiro cujo conteúdo ainda está em
    cache do sistema: a troca é atómica, mas o que lá fica depois de um corte de
    energia pode ser um ficheiro de zeros. O flush esvazia o buffer do Python; o
    fsync obriga o sistema operativo a confirmar a escrita física.
    """
    f.flush()
    os.fsync(f.fileno())


def _forcar_pasta(caminho: str) -> None:
    """Força ao disco a própria entrada de diretório, para o rename sobreviver.

    Em POSIX, o os.replace() só está garantido depois de a pasta ser sincronizada.
    Em Windows não há descritor de pasta para abrir — daí o except, que aqui é
    ausência de necessidade e não um erro escondido.
    """
    try:
        fd = os.open(os.path.dirname(os.path.abspath(caminho)) or ".", os.O_RDONLY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _rodar_geracoes(caminho: str, geracoes: int) -> None:
    """Desloca as cópias de segurança uma posição, deixando o .bak.1 livre.

    Percorre-se de trás para a frente (.2 -> .3 antes de .1 -> .2) porque a ordem
    inversa sobrescreveria a cópia que ainda não tinha sido deslocada.
    """
    if geracoes <= 0 or not os.path.exists(caminho):
        return
    for i in range(geracoes - 1, 0, -1):
        origem, destino = f"{caminho}.bak.{i}", f"{caminho}.bak.{i + 1}"
        if os.path.exists(origem):
            try:
                os.replace(origem, destino)
            except OSError:
                pass
    try:
        # A geração 1 é uma CÓPIA, não um move: mover deixaria o ficheiro principal
        # ausente entre o move e o replace, e é precisamente essa janela que se quer
        # eliminar. Copiar custa um pouco mais e não abre buraco nenhum.
        with open(caminho, "rb") as orig, open(f"{caminho}.bak.1", "wb") as cop:
            cop.write(orig.read())
            _forcar_ao_disco(cop)
    except OSError:
        pass


def gravar_json(caminho: str, dados: Any, geracoes: int = GERACOES_POR_OMISSAO) -> None:
    """Grava 'dados' como JSON de forma atómica, rodando as gerações anteriores.

    Substitui o `open(caminho, "w") + json.dump` que estava espalhado pelo projeto.
    Depois desta chamada, ou o ficheiro tem o conteúdo novo inteiro, ou tem o
    anterior inteiro — nunca metade de cada.

    Args:
        caminho: destino final.
        dados: estrutura serializável em JSON.
        geracoes: quantas cópias anteriores manter (0 desliga as cópias).
    """
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    _rodar_geracoes(caminho, geracoes)

    # O temporário tem de nascer na MESMA pasta: os.replace() só é atómico dentro
    # do mesmo sistema de ficheiros, e /tmp pode estar noutro.
    fd, tmp = tempfile.mkstemp(dir=pasta, prefix=os.path.basename(caminho) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            _forcar_ao_disco(f)
        os.replace(tmp, caminho)
        _forcar_pasta(caminho)
    except BaseException:
        # Falhou a meio: o temporário não serve para nada e não deve ficar a sujar
        # a pasta. O ficheiro definitivo continua intacto, que é o que importa.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ler_json(caminho: str, omissao: Any = None) -> Any:
    """Lê um JSON, recuando para as cópias de segurança se o principal estiver partido.

    É a outra metade da durabilidade: de nada serve gravar bem se, perante um
    ficheiro corrompido por uma versão antiga do agente (ou por um disco com
    defeito), o arranque rebentar na mesma. Aqui, um principal ilegível faz-se
    anunciar em voz alta e tenta-se a geração seguinte.

    Args:
        caminho: ficheiro a ler.
        omissao: valor a devolver se não existir nada legível.

    Returns:
        O conteúdo do JSON mais recente que esteja legível, ou 'omissao'.
    """
    candidatos = [caminho] + [f"{caminho}.bak.{i}" for i in range(1, GERACOES_POR_OMISSAO + 1)]
    for i, alvo in enumerate(candidatos):
        if not os.path.exists(alvo):
            continue
        try:
            with open(alvo, encoding="utf-8") as f:
                dados = json.load(f)
            if i > 0:
                print(f"[ARMAZEM] AVISO: '{os.path.basename(caminho)}' estava ilegível; "
                      f"recuperado da cópia .bak.{i}. Verifique o que se perdeu entretanto.")
            return dados
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            print(f"[ARMAZEM] '{os.path.basename(alvo)}' não é JSON válido ({e}). "
                  f"A tentar a cópia seguinte.")
    return omissao


class JornalAuditoria:
    """Trilho de auditoria apenas-acrescento, uma linha JSON por evento.

    Existe a par do histórico dentro do registo, e não em vez dele. A razão é de
    natureza diferente: o registo é um documento que se reescreve por inteiro a
    cada gravação e serve para a aplicação trabalhar; o jornal só cresce, nunca é
    reescrito, e serve para responder a uma auditoria. Um ficheiro que nunca é
    reaberto em modo de escrita destrutiva não pode ser truncado por um corte de
    energia a meio de uma gravação — no pior caso perde-se a última linha.

    Formato JSONL (uma linha = um objeto JSON) de propósito: lê-se com `tail`,
    filtra-se com `grep`, e uma linha corrompida não invalida as outras.
    """

    def __init__(self, caminho: str):
        """
        Args:
            caminho: ficheiro .jsonl do jornal (criado à primeira escrita).
        """
        self.caminho = caminho
        os.makedirs(os.path.dirname(os.path.abspath(caminho)) or ".", exist_ok=True)

    def registar(self, evento: dict) -> None:
        """Acrescenta um evento ao jornal e força-o ao disco.

        O fsync por evento é deliberado e é o ponto todo do exercício: um evento
        de auditoria que ainda está em buffer quando a máquina morre é um evento
        que nunca existiu. Ao volume deste sistema (dezenas de editais por mês)
        o custo é irrelevante.
        """
        linha = json.dumps(evento, ensure_ascii=False, sort_keys=True)
        with open(self.caminho, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
            _forcar_ao_disco(f)

    def ler_tudo(self) -> list[dict]:
        """Devolve todos os eventos legíveis do jornal, pela ordem em que ocorreram.

        Linhas ilegíveis (o caso da última linha cortada por um corte de energia)
        são ignoradas em silêncio: perder o último evento é aceitável, recusar o
        jornal inteiro por causa dele não é.
        """
        if not os.path.exists(self.caminho):
            return []
        eventos = []
        with open(self.caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    eventos.append(json.loads(linha))
                except json.JSONDecodeError:
                    continue
        return eventos
