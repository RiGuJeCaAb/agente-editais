"""
certidao.py — A certidão de afixação e desafixação, em PDF.

É a funcionalidade que muda o que esta aplicação É. Até aqui geria um ecrã: os
editais entravam, apareciam, saíam, e ficava um histórico legível por quem
abrisse o JSON. O que não existia era o documento — o papel que se junta a um
processo, se entrega a um tribunal ou se mostra a uma auditoria a dizer que
aquele edital esteve afixado, de quando a quando, por ordem de quem.

Sem isto, a pergunta "provam que foi afixado?" respondia-se com uma captura de
ecrã do painel. Com isto, responde-se com uma certidão.

O instante que conta
--------------------
Decidido a 18/09/2026, e é uma escolha com consequências: o instante OFICIAL de
afixação é o da publicação no painel, isto é, o momento em que uma pessoa com
competência para o fazer carregou em publicar. Não é o momento em que a imagem
entrou no slides.json, nem aquele em que a televisão a mostrou.

A razão é que a afixação é um ato administrativo, não um evento de
infraestrutura. Se o expositor estiver avariado, a deliberação foi afixada à
mesma e o que falhou foi o meio de a mostrar — e o meio repara-se sem que o ato
tenha de se repetir. Confundir as duas coisas poria a validade de um ato
administrativo a depender do uptime de uma televisão.

Dito isto, a outra pergunta também aparece: "e esteve mesmo lá?". Por isso a
certidão leva em ANEXO o registo de disponibilidade no expositor, quando ele
existe. Instante oficial no corpo, confirmação material no anexo, e as duas
coisas distinguidas em vez de misturadas.

Selo de conferência
-------------------
Cada certidão leva um resumo criptográfico dos factos que afirma. Não é
assinatura digital — não o é nem finge ser, e isso está escrito no próprio
documento. O que faz é permitir, mais tarde, confirmar que uma certidão em
papel corresponde ao que o registo diz: recalcula-se o resumo a partir do
registo e compara-se. Uma certidão adulterada deixa de bater certo.

Usa PyMuPDF, que já era dependência do projeto para ler PDFs. Zero
dependências novas — a mesma regra de sempre.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

# O módulo passou a chamar-se 'pymupdf'; 'fitz' continua a funcionar mas avisa a
# cada importação. Tentar o nome novo primeiro tira o ruído dos registos sem
# exigir uma versão mínima mais recente do que a que o projeto já pede.
try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF anterior a 1.24
    import fitz  # type: ignore[no-redef]

import prazos as pr

# Geometria da página A4 em pontos, e as margens do corpo.
LARGURA, ALTURA = 595, 842

# Versão do formato da certidão. Sobe sempre que mudar o CONJUNTO DE FACTOS que
# o selo cobre — nunca por uma mudança de aspeto. Vai impressa no rodapé, para
# quem confere um papel antigo saber sobre que factos refazer a conta.
#   1 — formato inicial.
#   2 — passa a incluir o número de páginas, a data prevista de retirada e a
#       lista de campos que nenhuma pessoa confirmou.
FORMATO = 2

# Como se chamam, em português de certidão, os campos que o registo guarda com
# nome técnico. Sem isto a certidão diria «data_publicacao» a quem a lê.
ROTULOS_DOS_CAMPOS = {
    "assunto": "o assunto",
    "numero": "o número",
    "data_publicacao": "a data do documento",
    "entidade": "a entidade emissora",
    "tipo": "o tipo de documento",
}
MARGEM_X = 62
MARGEM_TOPO = 68

# Tipos de letra base do PDF. São os embutidos no formato (não precisam de ser
# incorporados no ficheiro) e cobrem os acentos e o cedilha por WinAnsi, que é
# o que o português precisa. Times por ser o registo de um documento oficial.
SERIF = "tiro"
SERIF_NEGRITO = "tibo"
SERIF_ITALICO = "tiit"

PRETO = (0.12, 0.13, 0.10)
CINZA = (0.42, 0.44, 0.40)
VERDE = (0.05, 0.30, 0.20)


def _pt(instante: str | None) -> str:
    """Formata um instante ISO como se escreve num documento português."""
    if not instante:
        return "—"
    try:
        d = datetime.fromisoformat(instante)
    except ValueError:
        return str(instante)
    return d.strftime("%d/%m/%Y às %H:%M")


def _pt_data(valor: str | None) -> str:
    """Formata uma data ISO como DD/MM/AAAA."""
    if not valor:
        return "—"
    try:
        return date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(valor)


# Comprimentos, em dígitos hexadecimais, dos resumos que o projeto produz: o
# SHA-256 do arquivo imutável e o SHA-1 que o caminho de entrada usa para
# deduplicação. Qualquer outra coisa no campo não é um resumo de ficheiro.
_COMPRIMENTOS_DE_RESUMO = (64, 40)


# Devolve o resumo do original que a certidão pode citar, ou nada.
def _resumo_citavel(reg: dict) -> str:
    """Escolhe o que a certidão imprime em «Resumo do original».

    Prefere o SHA-256, que é o endereço do documento no arquivo imutável, e
    aceita o SHA-1 antigo para os editais anteriores ao arquivo.

    Recusa tudo o resto, e é para isso que existe. Um edital migrado do modelo
    automático pode não ter resumo nenhum — se o original já não estava na
    pasta à data da migração, não havia por onde o calcular. Nesse caso o
    campo `hash` leva uma chave sintética (`migrado:numero+assunto`), que serve
    para o registo não colidir consigo próprio e não serve para mais nada.
    Imprimi-la debaixo de «Resumo do original» era a certidão afirmar que
    conferiu um documento que nunca viu.
    """
    for valor in (reg.get("sha256"), reg.get("hash")):
        candidato = (valor or "").strip().lower()
        if len(candidato) in _COMPRIMENTOS_DE_RESUMO and all(
                c in "0123456789abcdef" for c in candidato):
            return candidato
    return ""


def factos(reg: dict) -> dict:
    """Extrai do registo o conjunto exato de factos que a certidão afirma.

    Existe como função própria, e não embutida na escrita do PDF, por duas
    razões: é sobre este dicionário que o selo de conferência é calculado (logo,
    tem de ser reproduzível fora da geração do documento), e é o que permite
    testar o conteúdo da certidão sem ter de reabrir e ler um PDF.

    Args:
        reg (dict): registo do edital.

    Returns:
        dict: factos, com as chaves ordenadas de forma estável.
    """
    return {
        # Versão do formato. O selo é calculado sobre este dicionário, por isso
        # acrescentar um facto muda o selo do MESMO registo — e uma certidão
        # emitida antes deixaria de conferir, o que se parece com uma falsificação
        # em vez de com uma actualização. Com a versão à vista (vai no rodapé),
        # quem confere sabe que conta refazer. Certidões sem versão impressa são
        # do formato 1.
        "formato": FORMATO,
        "id": reg.get("id"),
        "numero": reg.get("numero") or "",
        "assunto": reg.get("assunto") or "",
        "entidade": reg.get("entidade") or "",
        "tipo": reg.get("tipo") or pr.TIPO_POR_OMISSAO,
        "data_publicacao": reg.get("data_publicacao") or "",
        "ficheiro_origem": reg.get("ficheiro_origem") or "",
        # SHA-256 quando existe (é o endereço do documento no arquivo imutável),
        # e o SHA-1 antigo como recurso para os editais anteriores ao arquivo.
        # Passa por _resumo_citavel: o campo `hash` nem sempre é um resumo.
        "hash_original": _resumo_citavel(reg),
        "afixado_em": reg.get("afixado_em") or "",
        "afixado_por": reg.get("afixado_por") or "",
        "desafixado_em": reg.get("desafixado_em") or "",
        "desafixado_por": reg.get("desafixado_por") or "",
        "disponivel_em": reg.get("disponivel_em") or "",
        # Quantas folhas foram afixadas. A certidão identificava o documento pelo
        # nome, pela data e pelo resumo, e nunca dizia o tamanho dele — e se
        # amanhã alguém discutir o que esteve no expositor, o número de páginas
        # faz parte da identidade daquilo que lá esteve.
        "num_paginas": reg.get("num_paginas") or 0,
        "data_retirada": reg.get("data_retirada") or "",
        # Campos que a leitura automática propôs e que NENHUMA pessoa confirmou.
        # O registo limpa esta lista quando alguém corrige o campo, por isso o
        # que aqui ficar é mesmo por confirmar. Uma certidão que imprime um
        # palpite da máquina com o mesmo ar de um facto verificado transforma-o
        # em facto oficial — foi assim que o timbre da câmara virou o assunto de
        # um documento afixado.
        "campos_por_confirmar": sorted(reg.get("campos_duvidosos") or []),
    }


def selo(factos_: dict) -> str:
    """Calcula o resumo de conferência dos factos de uma certidão.

    sort_keys garante que a mesma informação dá sempre o mesmo resumo,
    independentemente da ordem em que os campos apareçam no registo — sem isso,
    reordenar um dicionário mudaria o selo sem mudar um único facto.

    Returns:
        str: os primeiros 16 caracteres do SHA-256, em grupos de quatro. É o
        que cabe numa linha e continua a ser impraticável de forjar à mão.
    """
    bruto = json.dumps(factos_, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return agrupar(hashlib.sha256(bruto).hexdigest()[:16].upper(), por=4)


def agrupar(resumo_: str, por: int = 8) -> str:
    """Escreve um resumo criptográfico em grupos, para se poder ler e conferir.

    Sessenta e quatro caracteres seguidos são ilegíveis a olho e impossíveis de
    comparar com outro sem perder a conta — e comparar é exatamente o que alguém
    faz com este valor. Em grupos, lê-se em blocos e confere-se em blocos.

    Ganha-se ainda uma coisa por acidente feliz: os espaços dão à quebra de
    linha sítios naturais onde partir. Sem eles, o resumo é uma palavra só, mais
    larga do que a caixa, e a certidão ficava com um carácter órfão na linha
    seguinte.
    """
    return " ".join(resumo_[i:i + por] for i in range(0, len(resumo_), por))


# Escreve um número de dias em português, com a concordância certa.
def dias_por_extenso(n: int) -> str:
    """Põe um número de dias em palavras de gente.

    A certidão dizia «0 dia(s)», que é duas coisas más ao mesmo tempo: o
    parêntesis do plural, que não se escreve num documento que vai para um
    processo, e o zero, que em português não é uma duração — um documento
    afixado esta manhã não esteve afixado zero dias, esteve afixado hoje.

    Args:
        n (int): número de dias decorridos.

    Returns:
        str: «Menos de um dia», «1 dia» ou «N dias».
    """
    if n <= 0:
        return "Menos de um dia"
    return "1 dia" if n == 1 else f"{n} dias"


def dias_de_afixacao(factos_: dict) -> int | None:
    """Conta os dias entre a afixação e a desafixação (ou até hoje).

    Returns:
        int | None: número de dias, ou None se nem sequer houve afixação.
    """
    if not factos_["afixado_em"]:
        return None
    try:
        inicio = datetime.fromisoformat(factos_["afixado_em"]).date()
    except ValueError:
        return None
    if factos_["desafixado_em"]:
        try:
            fim = datetime.fromisoformat(factos_["desafixado_em"]).date()
        except ValueError:
            return None
    else:
        fim = date.today()
    # max(0, ...) porque uma desafixação anterior à afixação (data introduzida ao
    # contrário, ou retirada automática por uma data já passada) daria um número
    # negativo. A certidão diz zero dias, que é o que de facto durou, e o
    # problema aparece nas observações do ponto 4, onde faz sentido.
    return max(0, (fim - inicio).days)


class _Folha:
    """Escritor sequencial de uma página, que sabe onde vai o cursor.

    Escrever um documento de texto com a API do PyMuPDF é posicionar cada linha
    à mão. Esta classe existe só para isso não contaminar a lógica da certidão
    com aritmética de coordenadas — quem lê gerar() vê a estrutura do documento,
    não contas de pontos.
    """

    def __init__(self, doc):
        self.pagina = doc.new_page(width=LARGURA, height=ALTURA)
        self.y = MARGEM_TOPO
        self.doc = doc

    def _nova_pagina_se_preciso(self, altura):
        """Muda de página quando o que vem a seguir já não cabe."""
        if self.y + altura > ALTURA - MARGEM_TOPO:
            self.pagina = self.doc.new_page(width=LARGURA, height=ALTURA)
            self.y = MARGEM_TOPO

    def linha(self, texto, *, tamanho=10.5, fonte=SERIF, cor=PRETO,
              recuo=0, espaco_antes=0, espaco_depois=4):
        """Escreve uma linha, partindo-a por palavras se não couber à largura."""
        self.y += espaco_antes
        largura_util = LARGURA - 2 * MARGEM_X - recuo
        for pedaco in _quebrar(texto, largura_util, tamanho, fonte):
            self._nova_pagina_se_preciso(tamanho + espaco_depois)
            self.pagina.insert_text((MARGEM_X + recuo, self.y), pedaco,
                                    fontname=fonte, fontsize=tamanho, color=cor)
            self.y += tamanho + 2
        self.y += espaco_depois

    def campo(self, rotulo, valor, *, tamanho=10.5):
        """Escreve um par rótulo/valor alinhado, como num formulário oficial."""
        self._nova_pagina_se_preciso(tamanho + 6)
        self.pagina.insert_text((MARGEM_X, self.y), rotulo, fontname=SERIF,
                                fontsize=tamanho, color=CINZA)
        largura_rotulo = 142
        for i, pedaco in enumerate(_quebrar(str(valor), LARGURA - 2 * MARGEM_X - largura_rotulo,
                                            tamanho, SERIF_NEGRITO)):
            if i:
                self.y += tamanho + 2
                self._nova_pagina_se_preciso(tamanho + 6)
            self.pagina.insert_text((MARGEM_X + largura_rotulo, self.y), pedaco,
                                    fontname=SERIF_NEGRITO, fontsize=tamanho, color=PRETO)
        self.y += tamanho + 6

    def risco(self, *, espaco_antes=6, espaco_depois=12, cor=(0.85, 0.83, 0.77)):
        """Traça uma linha horizontal separadora."""
        self.y += espaco_antes
        self._nova_pagina_se_preciso(espaco_depois)
        self.pagina.draw_line((MARGEM_X, self.y), (LARGURA - MARGEM_X, self.y),
                              color=cor, width=0.7)
        self.y += espaco_depois


# Equivalências para a MEDIÇÃO de largura, não para o texto que se escreve.
# Ver _largura() para a razão de isto existir.
_SEM_ACENTO = str.maketrans(
    "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ",
    "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN")


def _largura(texto, fonte, tamanho):
    """Mede a largura de um texto, contornando um defeito do PyMuPDF com acentos.

    O fitz.get_text_length() mede os caracteres acentuados dos tipos de letra
    base do PDF como se não ocupassem largura nenhuma. Medido: 'AÇÃO' devolve
    23,3 pt e desenha 30,9 pt; uma linha de 56 caracteres com acentos devolve
    325,5 pt e desenha 348,8 pt. O erro é sistemático e cresce com o número de
    acentos — ou seja, numa certidão em português, cresce em quase todas as
    linhas. A primeira versão desta certidão transbordava a margem direita em
    19,8 pt, e é dessa forma que se percebeu.

    A correção mede uma versão do texto com os acentos retirados. Não é um
    truque: nos tipos de letra proporcionais, o glifo acentuado tem o mesmo
    avanço horizontal que a letra de base — o acento cresce para cima, não para
    o lado. Confirmado na medição: 'ACAO' dá 30,9 pt, exatamente a largura real
    de 'AÇÃO'. O texto ESCRITO continua a ser o original, com acentos; só a
    régua é que muda.
    """
    return fitz.get_text_length(str(texto).translate(_SEM_ACENTO),
                                fontname=fonte, fontsize=tamanho)


def _quebrar(texto, largura, tamanho, fonte):
    """Parte um texto nas linhas que cabem numa dada largura.

    Mede com a métrica real do tipo de letra e não por contagem de caracteres:
    num tipo proporcional, 'iii' e 'MMM' têm o mesmo número de letras e larguras
    muito diferentes, e contar caracteres dá linhas a transbordar.
    """
    palavras = []
    for palavra in str(texto).split():
        palavras.extend(_partir_palavra(palavra, largura, tamanho, fonte))
    if not palavras:
        return [""]
    linhas, atual = [], palavras[0]
    for palavra in palavras[1:]:
        tentativa = f"{atual} {palavra}"
        if _largura(tentativa, fonte, tamanho) <= largura:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    return linhas


def _partir_palavra(palavra, largura, tamanho, fonte):
    """Parte uma palavra que não cabe na largura, carácter a carácter.

    Uma quebra por espaços não resolve o caso de uma palavra ser, ela própria,
    mais larga do que a caixa — e há uma que é sempre: o resumo SHA-256 do
    original, 64 caracteres sem um único espaço, que a certidão cita para
    identificar o documento afixado. Medido em Times a 10,5 pt, um SHA-256 ocupa
    336 pt numa caixa de 329.

    Isto passou despercebido ao teste que verifica as margens porque o resumo da
    fixture calhou ser mais estreito do que o de um documento real: em tipo
    proporcional, '1' e 'f' não têm a mesma largura, e um resumo cabia enquanto
    outro não. O teste passa agora com o pior caso possível.

    Devolve a palavra intacta quando ela cabe, que é o caso de quase todas.
    """
    if _largura(palavra, fonte, tamanho) <= largura:
        return [palavra]
    pedacos, atual = [], ""
    for caracter in palavra:
        if atual and _largura(atual + caracter, fonte, tamanho) > largura:
            pedacos.append(atual)
            atual = caracter
        else:
            atual += caracter
    if atual:
        pedacos.append(atual)
    return pedacos


def gerar(reg: dict, cfg: dict, *, emitida_por: str, nome_de_quem_emite: str = "",
          nomes_completos: dict | None = None) -> bytes:
    """Produz a certidão de afixação e desafixação de um edital, em PDF.

    Args:
        reg (dict): o registo do edital.
        cfg (dict): configuração (município, serviço, local do expositor).
        emitida_por (str): conta que pediu a certidão.
        nome_de_quem_emite (str): nome completo dessa pessoa, para o rodapé.
        nomes_completos (dict|None): mapa conta→nome completo, para a certidão
            citar "Ana Abreu" e não "ana.abreu" ao nomear quem afixou.

    Returns:
        bytes: o PDF.
    """
    f = factos(reg)
    nomes = nomes_completos or {}
    d = pr.tipo(f["tipo"])
    doc = fitz.open()
    folha = _Folha(doc)

    # ---- cabeçalho ----
    folha.linha(cfg.get("municipio", "MUNICÍPIO DE MOIMENTA DA BEIRA").upper(),
                tamanho=11, fonte=SERIF_NEGRITO, cor=VERDE, espaco_depois=1)
    if cfg.get("servico"):
        folha.linha(cfg["servico"], tamanho=9.5, cor=CINZA, espaco_depois=2)
    folha.risco(espaco_antes=8, espaco_depois=22)

    folha.linha("CERTIDÃO DE AFIXAÇÃO E DESAFIXAÇÃO", tamanho=15,
                fonte=SERIF_NEGRITO, espaco_depois=4)
    folha.linha(f"Registo n.º {f['id']} · Selo de conferência {selo(f)}",
                tamanho=9, cor=CINZA, espaco_depois=20)

    # ---- identificação do documento ----
    folha.linha("1. DOCUMENTO AFIXADO", tamanho=10, fonte=SERIF_NEGRITO,
                cor=VERDE, espaco_depois=9)
    folha.campo("Tipo", d["rotulo"])
    # O número imprime-se SEMPRE, mesmo em falta. Só aparecia quando existia, e
    # um campo que desaparece em silêncio não se distingue de um campo perdido:
    # quem lê a certidão não sabia se o documento não tinha número ou se o
    # sistema o tinha deixado cair.
    folha.campo("Número", f["numero"] or "(não atribuído)")
    folha.campo("Assunto", f["assunto"] or "(sem assunto registado)")
    if f["entidade"]:
        folha.campo("Entidade emissora", f["entidade"])
    folha.campo("Data do documento", _pt_data(f["data_publicacao"]))
    folha.campo("Ficheiro de origem", f["ficheiro_origem"])
    if f["num_paginas"]:
        folha.campo("Páginas", "1 página" if f["num_paginas"] == 1
                    else f"{f['num_paginas']} páginas")
    if f["hash_original"]:
        folha.campo("Resumo do original", agrupar(f["hash_original"]))
    # O que a máquina propôs e ninguém confirmou diz-se aqui, ao lado dos campos
    # a que respeita, e não numa observação no fim que já ninguém liga ao sítio.
    if f["campos_por_confirmar"]:
        quais = ", ".join(ROTULOS_DOS_CAMPOS.get(c, c)
                          for c in f["campos_por_confirmar"])
        folha.linha(
            f"Os seguintes elementos foram lidos automaticamente do documento e "
            f"não chegaram a ser confirmados por quem o afixou: {quais}.",
            tamanho=9.5, fonte=SERIF_ITALICO, cor=CINZA, espaco_depois=4)
    folha.risco()

    # ---- afixação ----
    folha.linha("2. AFIXAÇÃO", tamanho=10, fonte=SERIF_NEGRITO, cor=VERDE,
                espaco_depois=9)
    if f["afixado_em"]:
        quem = nomes.get(f["afixado_por"], f["afixado_por"])
        folha.campo("Afixado em", _pt(f["afixado_em"]))
        folha.campo("Por", f"{quem} ({f['afixado_por']})")
        folha.campo("Local", cfg.get("local_do_expositor",
                                     "Expositor eletrónico do Município"))
    else:
        folha.linha("Este documento não chegou a ser afixado.", tamanho=10.5,
                    fonte=SERIF_ITALICO, espaco_depois=8)
    folha.risco()

    # ---- desafixação ----
    folha.linha("3. DESAFIXAÇÃO", tamanho=10, fonte=SERIF_NEGRITO, cor=VERDE,
                espaco_depois=9)
    dias = dias_de_afixacao(f)
    if f["desafixado_em"]:
        quem = nomes.get(f["desafixado_por"], f["desafixado_por"])
        folha.campo("Desafixado em", _pt(f["desafixado_em"]))
        folha.campo("Por", f"{quem} ({f['desafixado_por']})")
        folha.campo("Duração da afixação", dias_por_extenso(dias or 0))
    elif f["afixado_em"]:
        folha.campo("Situação", "Mantém-se afixado nesta data")
        folha.campo("Decorridos", f"{dias_por_extenso(dias or 0)} desde a afixação")
        # Dizer «mantém-se afixado» sem dizer até quando deixa a pergunta mais
        # útil da certidão por responder, e é a data que a lei fixa.
        if f["data_retirada"]:
            folha.campo("Retirada prevista", _pt_data(f["data_retirada"]))
    else:
        folha.linha("Não aplicável.", tamanho=10.5, fonte=SERIF_ITALICO,
                    espaco_depois=8)
    folha.risco()

    # ---- base legal ----
    if d.get("base_legal"):
        folha.linha("4. BASE LEGAL", tamanho=10, fonte=SERIF_NEGRITO, cor=VERDE,
                    espaco_depois=9)
        folha.linha(d["base_legal"], tamanho=10.5, fonte=SERIF_NEGRITO, espaco_depois=5)
        if d.get("nota"):
            folha.linha(d["nota"], tamanho=10, cor=CINZA, espaco_depois=4)
        avisos = pr.verificar(f["tipo"], f["afixado_em"][:10] or None,
                              (f["desafixado_em"] or "")[:10] or None,
                              f["data_publicacao"] or None)
        for aviso in avisos:
            if aviso["grau"] == "aviso":
                # Um incumprimento não se omite da certidão. Uma certidão que
                # escondesse o que a lei pede e o que de facto aconteceu seria
                # pior do que não haver certidão nenhuma.
                folha.linha(f"Observação: {aviso['texto']}", tamanho=10,
                            fonte=SERIF_ITALICO, espaco_depois=4)
        folha.risco()

    # ---- anexo: disponibilidade material ----
    folha.linha("ANEXO · REGISTO DE DISPONIBILIDADE NO EXPOSITOR", tamanho=9.5,
                fonte=SERIF_NEGRITO, cor=CINZA, espaco_depois=8)
    if f["disponivel_em"]:
        folha.linha(
            f"O documento entrou na rotação do expositor em {_pt(f['disponivel_em'])}. "
            f"Este registo confirma a disponibilização material e não substitui o "
            f"instante de afixação certificado no ponto 2, que é o do ato "
            f"administrativo de afixação.",
            tamanho=9.5, cor=CINZA, espaco_depois=6)
    else:
        folha.linha(
            "Sem registo de entrada na rotação do expositor. A ausência deste "
            "registo não afeta a afixação certificada no ponto 2: respeita "
            "apenas à confirmação material do funcionamento do equipamento.",
            tamanho=9.5, cor=CINZA, espaco_depois=6)

    # ---- rodapé ----
    folha.risco(espaco_antes=14, espaco_depois=12)
    emitente = nome_de_quem_emite or nomes.get(emitida_por, emitida_por)
    folha.linha(f"Certidão emitida em {_pt(datetime.now().isoformat(timespec='seconds'))} "
                f"por {emitente} ({emitida_por}).", tamanho=9.5, cor=CINZA,
                espaco_depois=4)
    folha.linha(
        "Documento gerado automaticamente a partir do registo de editais. O selo "
        "de conferência permite confirmar, junto do serviço emissor, que esta "
        f"certidão corresponde ao registo (formato {FORMATO}). Não constitui "
        "assinatura eletrónica.",
        tamanho=8.5, cor=CINZA, espaco_depois=0)

    doc.set_metadata({
        "title": f"Certidão de afixação — registo {f['id']}",
        "author": cfg.get("municipio", "Município de Moimenta da Beira"),
        "subject": f["assunto"][:120],
        "creator": "Agente de Editais",
    })
    dados = doc.tobytes()
    doc.close()
    return dados


def nome_do_ficheiro(reg: dict) -> str:
    """Nome do PDF da certidão, seguindo a convenção de nomes do projeto."""
    carimbo = datetime.now().strftime("%Y%m%d%H%M")
    numero = (reg.get("numero") or f"reg{reg.get('id')}").replace("/", "-")
    return f"{carimbo}_certidao_afixacao_{numero}_CLD.pdf"
