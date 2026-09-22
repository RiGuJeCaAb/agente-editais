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
import os
import threading
from datetime import date, datetime

import armazenamento as arm
import prazos as pr

# Os estados do ciclo de vida. Usar constantes (e não strings soltas pelo
# código) evita gralhas silenciosas do tipo "Publicado" vs "publicado".
RASCUNHO   = "rascunho"
VALIDADO   = "validado"
PUBLICADO  = "publicado"
RETIRADO   = "retirado"
DESCARTADO = "descartado"

ESTADOS = (RASCUNHO, VALIDADO, PUBLICADO, RETIRADO, DESCARTADO)

# Rótulos legíveis para o painel (PT-PT), separados dos valores internos.
ESTADO_LABEL = {
    RASCUNHO:   "Rascunho",
    VALIDADO:   "Validado",
    PUBLICADO:  "Publicado",
    RETIRADO:   "Retirado",
    DESCARTADO: "Descartado",
}

# Transições autorizadas: de que estado se pode ir para que estados. Qualquer
# tentativa fora deste mapa é rejeitada por mover_estado() — a máquina de estados
# é a rede de segurança contra fluxos inválidos (ex.: publicar sem validar).
#
# DESCARTADO entrou porque a máquina não tinha saída nenhuma: o que entrava
# ficava para sempre, e um registo que só cresce enche-se de lixo. A migração do
# modelo antigo trouxe o caso concreto — editais sem data de publicação e sem
# ficheiro de origem, que não se conseguem validar nem publicar, e que ficavam
# eternamente na fila «Por validar» a tapar o trabalho a sério.
#
# Descartar NÃO é apagar, de propósito: a linha fica no registo, com o motivo e
# no jornal de auditoria, e volta atrás com um clique. Um registo de editais
# municipais não deve perder linhas — deve marcá-las.
#
# PUBLICADO não descarta, e esta é a regra que interessa: um edital que está no
# expositor sai de lá por RETIRADO, que é o que carimba `desafixado_em` e o que
# a certidão de desafixação cita. Descartá-lo fá-lo-ia desaparecer do ecrã sem
# que ficasse registado quem o desafixou nem quando — exatamente o buraco que a
# Onda 2 existiu para tapar. Quem quiser descartar um publicado, retira-o
# primeiro, e o ato fica documentado.
TRANSICOES = {
    RASCUNHO:   {VALIDADO, DESCARTADO},
    VALIDADO:   {PUBLICADO, RASCUNHO, DESCARTADO},
    PUBLICADO:  {RETIRADO},
    RETIRADO:   {PUBLICADO, DESCARTADO},
    DESCARTADO: {RASCUNHO},
}

# Estados que a fila de trabalho e o expositor ignoram por completo.
ESTADOS_INATIVOS = (DESCARTADO,)

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
        raiz = os.path.splitext(path)[0].replace("registo_entrada", "registo")
        self.jornal = arm.JornalAuditoria(raiz + "_auditoria.jsonl")
        self._dados = self._carregar()
        self._migrar()

    # ---- persistência -----------------------------------------------------
    def _migrar(self):
        """Dá aos registos antigos os campos que esta onda introduziu.

        Corre uma vez, na abertura, e só grava se alguma coisa faltava — para
        não reescrever o ficheiro a cada arranque sem motivo.

        A afixação dos editais que já estavam publicados é reconstruída a partir
        do histórico, que sempre registou a transição para 'publicado'. Não é
        invenção: é ler o que já lá estava e pô-lo num campo próprio. Onde o
        histórico não chegar, o campo fica a None e a certidão di-lo em vez de
        adivinhar.
        """
        mudou = False
        for reg in self._dados.get("editais", []):
            for campo, valor in (("tipo", pr.TIPO_POR_OMISSAO), ("sha256", ""),
                                 ("afixado_em", None),
                                 ("afixado_por", None), ("desafixado_em", None),
                                 ("desafixado_por", None), ("disponivel_em", None)):
                if campo not in reg:
                    reg[campo] = valor
                    mudou = True
            for ev in reg.get("historico", []):
                if ev.get("para") == PUBLICADO and not reg.get("afixado_em"):
                    reg["afixado_em"], reg["afixado_por"] = ev["em"], ev["utilizador"]
                    mudou = True
                if ev.get("para") == RETIRADO:
                    reg["desafixado_em"], reg["desafixado_por"] = ev["em"], ev["utilizador"]
                    mudou = True
        if mudou:
            self._guardar()

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
                # Endereço do documento no arquivo imutável. É o que a certidão
                # cita para identificar o que foi afixado, e o que permite
                # recompor a imagem sem depender da pasta de entrada.
                "sha256": meta.get("sha256", ""),
                "num_paginas": num_paginas,
                # Campos editáveis pelo utilizador no painel:
                "assunto": meta.get("assunto", ""),
                "numero": meta.get("numero", ""),
                "entidade": meta.get("entidade", ""),
                "data_publicacao": meta.get("data_publicacao"),
                "data_retirada": None,          # definida na validação/publicação
                # Tipo de documento: decide o prazo proposto e a norma citada na
                # certidão. Começa no tipo por omissão porque a leitura
                # automática não o sabe adivinhar — quem valida é que o escolhe.
                "tipo": meta.get("tipo") or pr.TIPO_POR_OMISSAO,
                # Instantes de afixação e desafixação, com o seu autor. São o
                # cerne da certidão, e por isso NÃO são editáveis: gravam-se
                # quando a transição de estado acontece e mais ninguém lhes toca.
                "afixado_em": None, "afixado_por": None,
                "desafixado_em": None, "desafixado_por": None,
                # Instante em que o edital apareceu pela primeira vez no
                # slides.json, isto é, em que ficou disponível no expositor. Vai
                # para a certidão como anexo — o instante OFICIAL é o da
                # publicação no painel, esta é a confirmação material.
                "disponivel_em": None,
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

    # Campos que o AGENTE produz, por oposição aos que o utilizador edita. Não
    # passam por editar() (que tem a sua própria lista branca e gera evento de
    # auditoria) porque não são decisões de ninguém: são resultados do
    # processamento. Ter a lista explícita evita que uma chamada distraída a
    # definir() escreva no estado ou no histórico por esta porta.
    CAMPOS_DE_SISTEMA = {"ficheiros_previa", "ficheiros_png", "sha256"}

    def definir(self, rid, **campos):
        """Grava campos produzidos pelo agente num registo.

        Substitui os três métodos quase iguais que havia (previas, pngs, e o
        sha256 que esta onda trouxe). A razão de existirem de todo é que
        por_estado() e todos() devolvem CÓPIAS desde a Onda 1: escrever no
        dicionário devolvido não chega ao registo, e o defeito que isso causa é
        silencioso — nada falha, apenas o trabalho é refeito a cada ciclo.

        Args:
            rid (int): id do registo.
            **campos: pares campo→valor, restritos a CAMPOS_DE_SISTEMA.

        Raises:
            KeyError: se algum campo não for de sistema. É erro de programação,
                não do utilizador, por isso levanta em vez de ignorar.
        """
        de_fora = set(campos) - self.CAMPOS_DE_SISTEMA
        if de_fora:
            raise KeyError(f"Não são campos de sistema: {sorted(de_fora)}")
        with self._lock:
            reg = self.por_id(rid)
            if reg is None:
                return
            reg.update(campos)
            self._guardar()

    def definir_previas(self, rid, nomes):
        """Atalho legível para gravar os nomes das pré-visualizações."""
        self.definir(rid, ficheiros_previa=list(nomes))

    def definir_instante_de_afixacao(self, rid, instante, utilizador):
        """Corrige o instante de afixação para um que aconteceu no passado.

        Existe só para a migração dos editais do modelo antigo. Esses estiveram
        meses no expositor, e mover_estado() carimba a afixação com a hora em
        que a transição corre — o que daria a todos a mesma hora, a da migração.
        A certidão diria então que um edital de junho foi afixado em setembro.

        NÃO é para uso corrente, e por isso não está na lista branca de editar()
        nem em CAMPOS_DE_SISTEMA: um instante de afixação que se possa reescrever
        a pedido deixa de certificar seja o que for. O evento fica no histórico,
        com quem o corrigiu e o valor anterior, para a correção ser ela própria
        auditável.

        Args:
            rid (int): id do registo.
            instante (str): instante em ISO.
            utilizador (str): quem está a corrigir (na prática, 'migracao').
        """
        with self._lock:
            reg = self.por_id(rid)
            if reg is None:
                return
            anterior = reg.get("afixado_em")
            reg["afixado_em"] = instante
            reg["afixado_por"] = utilizador
            self._anotar(reg, utilizador, reg["estado"], reg["estado"],
                         f"Instante de afixação corrigido para {instante} "
                         f"(estava {anterior or 'por preencher'})")
            self._guardar()

    def definir_pngs(self, rid, nomes):
        """Atalho legível para gravar os nomes dos PNG compostos."""
        self.definir(rid, ficheiros_png=list(nomes))

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
                     "data_publicacao", "data_retirada", "tipo"}
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
            # Descartar exige motivo escrito. Não apagar só vale a pena se daqui
            # a seis meses alguém conseguir saber porque é que aquele edital saiu
            # da fila; sem motivo, o registo guarda a linha e perde a razão, que
            # é a parte que interessa.
            if novo_estado == DESCARTADO and not (nota or "").strip():
                return {"ok": False,
                        "erro": "Descartar exige um motivo.",
                        "registo": reg}
            # Carimbar os instantes que a certidão vai citar. A primeira
            # publicação é a afixação; as reposições seguintes não a reescrevem,
            # porque o que a lei conta é quando o edital foi afixado, e um
            # edital reposto depois de uma retirada indevida não passou a ser
            # afixado de novo. A desafixação, essa, é sempre a última.
            if novo_estado == PUBLICADO and not reg.get("afixado_em"):
                reg["afixado_em"] = _agora()
                reg["afixado_por"] = utilizador
            if novo_estado == RETIRADO:
                reg["desafixado_em"] = _agora()
                reg["desafixado_por"] = utilizador
            reg["estado"] = novo_estado
            self._anotar(reg, utilizador, atual, novo_estado, nota or "Mudança de estado")
            self._guardar()
            return {"ok": True, "erro": None, "registo": copy.deepcopy(reg)}

    def marcar_disponivel(self, rid, instante=None):
        """Regista que o edital apareceu no expositor (entrou no slides.json).

        É o «registo de disponibilidade» que acompanha a certidão em anexo. Não
        substitui o instante oficial de afixação — esse é o da publicação no
        painel, que é o ato administrativo — mas responde à outra pergunta, a
        material: e esteve mesmo lá?

        Só se grava a PRIMEIRA vez. As republicações seguintes do slides.json
        não movem a data, senão o anexo passaria a dizer a hora do último ciclo
        do agente em vez da hora em que o edital ficou visível.

        Args:
            rid (int): id do registo.
            instante (str|None): ISO; por omissão, agora.
        """
        with self._lock:
            reg = self.por_id(rid)
            if reg is not None and not reg.get("disponivel_em"):
                reg["disponivel_em"] = instante or _agora()
                self._guardar()
                return True
        return False

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
                        reg["desafixado_em"] = _agora()
                        reg["desafixado_por"] = utilizador
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
