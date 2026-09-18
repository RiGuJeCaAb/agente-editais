# -*- coding: utf-8 -*-
"""
registo.py — Registo de entrada dos editais, com fluxo de estados e auditoria.

Este módulo é a mudança de paradigma pedida: o agente deixa de "processar e
publicar" às cegas e passa a "receber → registar → o humano valida → publicar".

Cada documento que entra torna-se um REGISTO com um ciclo de vida de 4 estados:

    RASCUNHO   → o agente leu o documento e propôs os metadados (assunto, número,
                 datas) com um grau de CONFIANÇA. Ainda NÃO está no ecrã.
    VALIDADO   → um utilizador reviu/corrigiu os dados e aprovou. Pronto a publicar,
                 mas ainda não visível na TV.
    PUBLICADO  → está a ser mostrado no expositor.
    RETIRADO   → saiu do ecrã (por data de retirada atingida ou retirada manual).
                 Fica no arquivo — nunca se apaga, para haver histórico.

Transições permitidas (máquina de estados simples e defensiva):

    RASCUNHO  → VALIDADO   (validar)        VALIDADO  → RASCUNHO  (devolver p/ correção)
    VALIDADO  → PUBLICADO  (publicar)       PUBLICADO → RETIRADO  (retirar)
    RETIRADO  → PUBLICADO   (repor)

Cada transição fica no trilho de AUDITORIA (quem, quando, de/para) — é o que
permite responder, num organismo público, a "quem afixou isto e quando?".

Persistência: um único JSON ('registo_entrada.json'). É deliberadamente um
ficheiro de texto legível — auditável à mão e fácil de salvaguardar.

Nota importante sobre concorrência: o painel pode ter vários utilizadores. As
escritas passam todas por save(), que reescreve o ficheiro inteiro sob um lock
em memória do processo. Para o volume de um município (dezenas de editais/mês)
isto chega e sobra; não se justifica uma base de dados.
"""
from __future__ import annotations
import copy
import os, json, threading
from datetime import datetime, date

import armazenamento as arm

# Os quatro estados do ciclo de vida. Usar constantes (e não strings soltas pelo
# código) evita gralhas silenciosas do tipo "Publicado" vs "publicado".
RASCUNHO  = "rascunho"
VALIDADO  = "validado"
PUBLICADO = "publicado"
RETIRADO  = "retirado"

ESTADOS = (RASCUNHO, VALIDADO, PUBLICADO, RETIRADO)

# Rótulos legíveis para o painel (PT-PT), separados dos valores internos.
ESTADO_LABEL = {
    RASCUNHO:  "Rascunho",
    VALIDADO:  "Validado",
    PUBLICADO: "Publicado",
    RETIRADO:  "Retirado",
}

# Transições autorizadas: de que estado se pode ir para que estados. Qualquer
# tentativa fora deste mapa é rejeitada por mover_estado() — a máquina de estados
# é a rede de segurança contra fluxos inválidos (ex.: publicar sem validar).
TRANSICOES = {
    RASCUNHO:  {VALIDADO},
    VALIDADO:  {PUBLICADO, RASCUNHO},
    PUBLICADO: {RETIRADO},
    RETIRADO:  {PUBLICADO},
}

# Limiar abaixo do qual um campo lido automaticamente é considerado "duvidoso" e
# o painel o assinala a pedir verificação. 0.6 é o ponto onde uma heurística de
# recurso (confiança 0.5) cai do lado do "confirma isto" e a leitura normal
# (0.9) fica tranquila.
CONFIANCA_MINIMA = 0.6


class RegistoEntrada:
    """Gestor do registo de entrada: carrega, guarda e faz evoluir os editais.

    Encapsula toda a leitura/escrita do JSON e as regras de transição de estado,
    para o resto do sistema (agente e painel) nunca mexer no ficheiro diretamente.
    """

    def __init__(self, path):
        """Abre (ou cria) o registo no caminho indicado.

        Args:
            path (str): caminho do ficheiro JSON de persistência.
        """
        self.path = path
        # Lock de processo: serializa as escritas quando várias ações do painel
        # chegam quase ao mesmo tempo. Não protege contra vários PROCESSOS a
        # escrever o mesmo ficheiro — mas o desenho é haver um só processo-agente.
        self._lock = threading.RLock()
        # Jornal apenas-acrescento, ao lado do registo. Duplica de propósito o
        # histórico que vive dentro de cada edital: aquele é reescrito por inteiro
        # a cada gravação (e portanto vulnerável a uma escrita interrompida), este
        # só cresce. É o que se entrega a quem audita.
        raiz = os.path.splitext(path)[0]
        self.jornal = arm.JornalAuditoria(raiz.replace("registo_entrada", "registo") + "_auditoria.jsonl")
        self._dados = self._carregar()

    # ---- persistência -----------------------------------------------------
    def _carregar(self):
        """Lê o JSON do disco, ou devolve uma estrutura vazia se ainda não existe.

        Returns:
            dict: {"editais": [...], "seq": int} — 'seq' é o contador de IDs.
        """
        return arm.ler_json(self.path, {"editais": [], "seq": 0})

    def _guardar(self):
        """Escreve o registo no disco de forma atómica, com gerações de recurso.

        Chamado internamente após cada mutação. Delega em armazenamento.gravar_json,
        que escreve para temporário, força ao disco e só então troca — a versão
        anterior deste método usava `open(path, "w")` direto, e uma interrupção
        entre o truncar e o escrever deixava o registo ilegível e o agente sem
        arrancar. Está reproduzido no teste test_armazenamento.py.
        """
        arm.gravar_json(self.path, self._dados)

    def _anotar(self, reg, utilizador, de, para, nota):
        """Acrescenta um evento ao histórico do edital E ao jornal de auditoria.

        Único ponto por onde se escreve auditoria, para não haver caminho que
        alimente um dos dois e esqueça o outro. O jornal leva o id e o assunto
        além do evento, porque é lido fora de contexto — quem audita abre o
        .jsonl sozinho, sem o registo ao lado.
        """
        ev = _evento(utilizador, de, para, nota)
        reg.setdefault("historico", []).append(ev)
        self.jornal.registar({**ev, "id": reg.get("id"),
                              "numero": reg.get("numero", ""),
                              "assunto": reg.get("assunto", ""),
                              "ficheiro_origem": reg.get("ficheiro_origem", "")})
        return ev

    # ---- criação ----------------------------------------------------------
    def criar_rascunho(self, *, ficheiro_origem, hash_ficheiro, num_paginas,
                       meta, utilizador="sistema"):
        """Cria um novo registo em estado RASCUNHO a partir da leitura do agente.

        É aqui que um documento entra no fluxo. Guarda os metadados propostos e a
        confiança, marca os campos duvidosos e regista o evento de auditoria.

        Args:
            ficheiro_origem (str): nome do ficheiro original.
            hash_ficheiro (str): SHA-1 do conteúdo (para deteção de duplicados).
            num_paginas (int): nº de páginas do documento.
            meta (dict): saída de documentos.extract_metadata (com "confianca").
            utilizador (str): quem/o quê originou (por omissão "sistema").

        Returns:
            dict: o registo criado.
        """
        with self._lock:
            self._dados["seq"] += 1
            rid = self._dados["seq"]
            conf = meta.get("confianca", {})
            registo = {
                "id": rid,
                "estado": RASCUNHO,
                "ficheiro_origem": ficheiro_origem,
                "hash": hash_ficheiro,
                "num_paginas": num_paginas,
                # Campos editáveis pelo utilizador no painel:
                "assunto": meta.get("assunto", ""),
                "numero": meta.get("numero", ""),
                "entidade": meta.get("entidade", ""),
                "data_publicacao": meta.get("data_publicacao"),
                "data_retirada": None,          # definida na validação/publicação
                # Metadados de apoio à decisão:
                "confianca": conf,
                "campos_duvidosos": self._campos_duvidosos(conf),
                "ficheiros_png": [],            # preenchidos quando publica
                "ficheiros_previa": [],         # pré-visualizações leves p/ o painel
                # Auditoria:
                "criado_em": _agora(),
                "historico": [],
            }
            self._anotar(registo, utilizador, None, RASCUNHO, "Documento recebido e lido")
            self._dados["editais"].append(registo)
            self._guardar()
            return copy.deepcopy(registo)

    @staticmethod
    def _campos_duvidosos(conf):
        """Lista os campos cuja confiança fica abaixo do limiar.

        Args:
            conf (dict): confiança por campo (0.0-1.0).

        Returns:
            list[str]: nomes dos campos a assinalar para verificação.
        """
        return [campo for campo, valor in (conf or {}).items()
                if valor < CONFIANCA_MINIMA]

    # ---- consultas --------------------------------------------------------
    def todos(self):
        """Devolve uma CÓPIA de todos os registos, em ordem de criação.

        Era uma referência viva à lista interna. O painel entregava-a ao
        serializador JSON enquanto a thread de vigia lhe fazia append e o próprio
        painel mutava dicionários lá dentro — ler e escrever a mesma estrutura em
        threads diferentes sem lock. Não se conseguiu fazer rebentar numa passagem
        curta (o GIL é indulgente), mas a correção custa uma cópia de umas dezenas
        de registos e remove a classe de problema inteira.

        Returns:
            list[dict]: cópia profunda dos editais, em ordem de criação.
        """
        with self._lock:
            return copy.deepcopy(self._dados["editais"])

    def por_id(self, rid):
        """Procura um registo pelo seu id.

        Args:
            rid (int): identificador do registo.

        Returns:
            dict | None: o registo, ou None se não existir.
        """
        for e in self._dados["editais"]:
            if e["id"] == int(rid):
                return e
        return None

    # Nota: por_id devolve a referência INTERNA de propósito — é usada dentro dos
    # métodos que mutam sob lock. Quem serve dados ao exterior usa todos(), que
    # devolve cópia.

    def por_estado(self, estado):
        """Filtra registos por estado.

        Args:
            estado (str): um dos ESTADOS.

        Returns:
            list[dict]: registos nesse estado.
        """
        with self._lock:
            return copy.deepcopy([e for e in self._dados["editais"] if e["estado"] == estado])

    def hash_existe(self, hash_ficheiro):
        """Indica se já existe um registo com o mesmo conteúdo (mesmo hash).

        Serve para o agente não criar rascunhos duplicados do mesmo ficheiro.

        Args:
            hash_ficheiro (str): SHA-1 a procurar.

        Returns:
            bool: True se já existe.
        """
        with self._lock:
            return any(e["hash"] == hash_ficheiro for e in self._dados["editais"])

    def definir_previas(self, rid, nomes):
        """Regista os nomes das pré-visualizações leves de um registo.

        Método interno (não passa pela lista branca de editar), usado pelo agente
        logo após gerar as pré-visualizações do documento.

        Args:
            rid (int): id do registo.
            nomes (list[str]): nomes dos ficheiros de pré-visualização.
        """
        with self._lock:
            reg = self.por_id(rid)
            if reg is not None:
                reg["ficheiros_previa"] = nomes
                self._guardar()

    def definir_pngs(self, rid, nomes):
        """Regista os nomes dos PNG compostos de um edital.

        Irmão de definir_previas, e pela mesma razão: são dados que o agente
        produz, não campos que o utilizador edita, por isso não passam pela lista
        branca de editar() nem geram evento de auditoria.

        Passou a ser indispensável quando por_estado() deixou de devolver
        referências vivas: o agente escrevia `r["ficheiros_png"] = ...` no
        resultado e chamava _guardar(), o que a partir daí gravaria o estado
        interno inalterado — os nomes perdiam-se e a imagem 4K era recomposta a
        cada ciclo. O teste test_registo.py::test_definir_pngs_persiste cobre-o.

        Args:
            rid (int): id do registo.
            nomes (list[str]): nomes dos PNG na pasta de saída.
        """
        with self._lock:
            reg = self.por_id(rid)
            if reg is not None:
                reg["ficheiros_png"] = list(nomes)
                self._guardar()

    # ---- edição de campos -------------------------------------------------
    def editar(self, rid, campos, utilizador="painel"):
        """Atualiza campos editáveis de um registo (feito pelo utilizador no painel).

        Só permite mexer numa lista branca de campos — nunca no id, estado, hash ou
        histórico por esta via. Corrigir um campo duvidoso remove-o da lista de
        dúvidas (o humano resolveu-a).

        Args:
            rid (int): id do registo.
            campos (dict): pares campo→valor a atualizar.
            utilizador (str): quem editou (para auditoria).

        Returns:
            dict | None: o registo atualizado, ou None se não existir.
        """
        editaveis = {"assunto", "numero", "entidade",
                     "data_publicacao", "data_retirada"}
        with self._lock:
            reg = self.por_id(rid)
            if not reg:
                return None
            alterados = []
            for campo, valor in campos.items():
                if campo in editaveis and reg.get(campo) != valor:
                    reg[campo] = valor
                    alterados.append(campo)
                    # Se o utilizador corrigiu um campo duvidoso, deixa de o ser.
                    if campo in reg.get("campos_duvidosos", []):
                        reg["campos_duvidosos"].remove(campo)
            if alterados:
                self._anotar(reg, utilizador, reg["estado"], reg["estado"],
                             "Editado: " + ", ".join(alterados))
                self._guardar()
            return copy.deepcopy(reg)

    # ---- transições de estado --------------------------------------------
    def mover_estado(self, rid, novo_estado, utilizador="painel", nota=""):
        """Move um registo para outro estado, se a transição for permitida.

        É o único ponto por onde o estado muda. Valida contra o mapa TRANSICOES e
        regista sempre o evento de auditoria (quem, quando, de→para, nota).

        Args:
            rid (int): id do registo.
            novo_estado (str): estado de destino (um dos ESTADOS).
            utilizador (str): quem fez a ação.
            nota (str): observação opcional (ex.: motivo da retirada).

        Returns:
            dict: {"ok": bool, "erro": str|None, "registo": dict|None}
        """
        with self._lock:
            reg = self.por_id(rid)
            if not reg:
                return {"ok": False, "erro": "Registo não encontrado", "registo": None}
            atual = reg["estado"]
            if novo_estado not in ESTADOS:
                return {"ok": False, "erro": f"Estado inválido: {novo_estado}",
                        "registo": reg}
            # A regra de ouro: só se pode transitar pelos caminhos autorizados.
            if novo_estado not in TRANSICOES.get(atual, set()):
                return {"ok": False,
                        "erro": f"Transição não permitida: "
                                f"{ESTADO_LABEL[atual]} → {ESTADO_LABEL[novo_estado]}",
                        "registo": reg}
            # Regra de negócio: a data de publicação é obrigatória para validar
            # (o rodapé da TV mostra-a sempre). Bloqueia aqui, não mais à frente.
            if novo_estado == VALIDADO and not reg.get("data_publicacao"):
                return {"ok": False,
                        "erro": "Falta a data de publicação (obrigatória).",
                        "registo": reg}
            reg["estado"] = novo_estado
            self._anotar(reg, utilizador, atual, novo_estado, nota or "Mudança de estado")
            self._guardar()
            return {"ok": True, "erro": None, "registo": copy.deepcopy(reg)}

    # ---- retirada automática por data ------------------------------------
    def aplicar_retiradas_automaticas(self, utilizador="sistema"):
        """Retira automaticamente os editais PUBLICADOS cuja data de saída passou.

        Chamado periodicamente pelo agente. Não toca em nada que não esteja
        publicado, e regista cada retirada no histórico.

        Args:
            utilizador (str): autor da ação (por omissão "sistema").

        Returns:
            list[int]: ids dos registos que foram retirados nesta passagem.
        """
        hoje = date.today()
        retirados = []
        with self._lock:
            for reg in self._dados["editais"]:
                if reg["estado"] != PUBLICADO:
                    continue
                dr = reg.get("data_retirada")
                if not dr:
                    continue
                try:
                    if date.fromisoformat(dr) < hoje:
                        reg["estado"] = RETIRADO
                        self._anotar(reg, utilizador, PUBLICADO, RETIRADO,
                                     f"Retirada automática (data {dr})")
                        retirados.append(reg["id"])
                except ValueError:
                    # Data mal formada não deve rebentar o ciclo; ignora-se.
                    pass
            if retirados:
                self._guardar()
        return retirados


# ---------------------------------------------------------------------------
# Auxiliares de módulo
# ---------------------------------------------------------------------------
def _agora():
    """Devolve o instante atual em ISO, ao segundo (para carimbos de auditoria)."""
    return datetime.now().isoformat(timespec="seconds")

def _evento(utilizador, de, para, nota):
    """Constrói uma entrada de histórico/auditoria.

    Args:
        utilizador (str): quem realizou a ação.
        de (str|None): estado de origem (None na criação).
        para (str): estado de destino.
        nota (str): descrição do evento.

    Returns:
        dict: entrada de auditoria com carimbo temporal.
    """
    return {"em": _agora(), "utilizador": utilizador,
            "de": de, "para": para, "nota": nota}
