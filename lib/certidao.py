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

import diario
import extenso as ext
import prazos as pr
import registo as reg_mod

_log = diario.obter("CERTIDAO")

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
# Margens generosas, que é o que distingue um documento de um impresso. A caixa
# de texto fica com 451 pt, cerca de setenta e cinco caracteres em Times a 11 —
# a medida a que um parágrafo se lê sem o olho se perder ao mudar de linha.
MARGEM_X = 72
MARGEM_TOPO = 56
# A faixa de baixo é do rodapé, e o texto não entra nela. Sem esta reserva, a
# última linha de uma página escrevia-se por cima da morada do município.
MARGEM_BAIXO = 66

# As três medidas da faixa do rodapé, que estavam espalhadas pelo rodape() como
# números soltos. Ficam aqui porque é delas que sai quantas linhas lá cabem, e
# essa conta tinha-se feito de cabeça: estava escrito «duas» e duas é o que cabe
# a 7 pt. A 5 pt cabem três, e a diferença era texto configurado a desaparecer.
RODAPE_DESCIDA = 26        # quanto a última linha desce abaixo da margem do corpo
RODAPE_ACIMA_DA_REGUA = 12  # distância da régua à primeira linha
RODAPE_ENTRELINHA = 2       # acrescento à altura da letra

# Tipos de letra base do PDF. São os embutidos no formato (não precisam de ser
# incorporados no ficheiro) e cobrem os acentos e o cedilha por WinAnsi, que é
# o que o português precisa. Times por ser o registo de um documento oficial.
SERIF = "tiro"
SERIF_NEGRITO = "tibo"
SERIF_ITALICO = "tiit"

PRETO = (0.12, 0.13, 0.10)
CINZA = (0.42, 0.44, 0.40)
VERDE = (0.05, 0.30, 0.20)

# A moldura são duas réguas concêntricas, como as dos livros de termos, e estes
# são os afastamentos à borda do papel. A de DENTRO tem de ficar fora de tudo o
# que se escreve: o folio assenta em 802 pt e desce aos 804,5 com os
# descendentes, e a régua está em 810. Encostá-la mais riscava o número da folha.
MOLDURA_FORA = 26
MOLDURA_DENTRO = 32

# Altura a que o monograma e o logótipo de texto se compõem no timbre. Os dois
# ficheiros têm proporções diferentes — 134x118 e 375x96 — e é a altura comum
# que os alinha; escalá-los pela largura dava o monograma do tamanho de um selo.
ALTURA_DO_TIMBRE = 36
INTERVALO_DO_TIMBRE = 12

# O lugar do selo branco, à esquerda da assinatura. Não é decoração: é onde se
# carimba o exemplar impresso, e é por isso que vai a tracejado e não a cheio.
RAIO_DO_SELO = 28


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
        # A referência interna NÃO entra aqui, e imprime-se na folha à mesma.
        # Duas razões, e a segunda é a que decide. A primeira: é uma etiqueta
        # nossa, não um facto da afixação -- o selo atesta o que esteve afixado,
        # quando e por quem, e pôr a etiqueta debaixo dele dava-lhe a dignidade
        # de um facto que ela não tem. A segunda: a referência deriva do
        # `criado_em`, que o selo não cobre, e um facto derivado de um campo não
        # selado faz o selo mudar sem que nenhum facto selado tenha mudado.
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


# Quantas linhas de rodapé cabem na faixa reservada, a este tamanho de letra.
def _linhas_de_rodape(tamanho):
    """Devolve o número de linhas que a faixa do rodapé comporta.

    Sai da geometria e não de um número escolhido: a última linha assenta
    RODAPE_DESCIDA abaixo da margem do corpo, a régua fica
    RODAPE_ACIMA_DA_REGUA acima da primeira, e a régua não pode subir acima da
    margem do corpo sob pena de a faixa invadir o texto. Daí
    (n - 1) * (tamanho + entrelinha) <= descida - acima.

    Dá duas linhas a 7 pt — que era o valor escrito à mão — e três a 5 pt.
    """
    folga = RODAPE_DESCIDA - RODAPE_ACIMA_DA_REGUA
    return 1 + int(folga // (tamanho + RODAPE_ENTRELINHA))


class _Folha:
    """Escritor sequencial de uma página, que sabe onde vai o cursor.

    Escrever um documento de texto com a API do PyMuPDF é posicionar cada linha
    à mão. Esta classe existe só para isso não contaminar a lógica da certidão
    com aritmética de coordenadas — quem lê gerar() vê a estrutura do documento,
    não contas de pontos.

    CONTA as páginas em vez de as guardar. O rodapé só se pode desenhar no fim
    — leva «fl. 1 de 3», e o total não se sabe enquanto o texto não acabar — mas
    um objeto Page do PyMuPDF deixa de servir assim que se acrescenta outra
    página ao documento: guardá-los numa lista rebentava com AttributeError na
    primeira certidão que passasse de uma folha, e rebentou.
    """

    def __init__(self, doc):
        self.doc = doc
        self.pagina = doc.new_page(width=LARGURA, height=ALTURA)
        self.n_paginas = 1
        self.y = MARGEM_TOPO

    def _nova_pagina_se_preciso(self, altura):
        """Muda de página quando o que vem a seguir já não cabe.

        O limite é MARGEM_BAIXO e não MARGEM_TOPO: a faixa de baixo está
        reservada ao rodapé, e escrever lá por cima dele seria sobrepor a morada
        do município ao texto da certidão.
        """
        if self.y + altura > ALTURA - MARGEM_BAIXO:
            self.pagina = self.doc.new_page(width=LARGURA, height=ALTURA)
            self.n_paginas += 1
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

    def centrado(self, texto, *, tamanho=10.5, fonte=SERIF, cor=PRETO,
                 espaco_antes=0, espaco_depois=4):
        """Escreve uma linha centrada na caixa de texto."""
        self.y += espaco_antes
        largura_util = LARGURA - 2 * MARGEM_X
        for pedaco in _quebrar(texto, largura_util, tamanho, fonte):
            self._nova_pagina_se_preciso(tamanho + espaco_depois)
            x = (LARGURA - _largura(pedaco, fonte, tamanho)) / 2
            self.pagina.insert_text((x, self.y), pedaco, fontname=fonte,
                                    fontsize=tamanho, color=cor)
            self.y += tamanho + 2
        self.y += espaco_depois

    def espacado(self, texto, *, tamanho=16, fonte=SERIF_NEGRITO, cor=PRETO,
                 espaco_antes=0, espaco_depois=6):
        """Escreve uma linha centrada com as letras afastadas.

        É o tratamento que os títulos das certidões antigas levavam — C E R T I
        D Ã O — e faz-se com espaços e não com uma propriedade do tipo de letra
        porque os tipos base do PDF não têm uma. Fica também melhor na extração
        de texto: quem procurar «CERTIDÃO» num PDF destes não a encontraria, por
        isso o título por extenso aparece igualmente no título do documento.

        Entre PALAVRAS vai quatro vezes o espaço que vai entre letras. Com o
        espaço simples que o join dá, «MUNICÍPIO DE MOIMENTA» lia-se como uma
        palavra só de vinte letras: afastar as letras só resulta se o
        afastamento entre palavras continuar a ser maior do que esse.
        """
        aberto = "    ".join(" ".join(palavra) for palavra in texto.split())
        # NÃO passa pelo centrado(): esse quebra o texto com _quebrar(), que faz
        # split() e normaliza os espaços múltiplos — apagava exatamente a folga
        # que esta linha acabou de pôr entre as palavras.
        self.y += espaco_antes
        while tamanho > 6 and _largura(aberto, fonte, tamanho) > LARGURA - 2 * MARGEM_X:
            tamanho -= 0.5
        self._nova_pagina_se_preciso(tamanho + espaco_depois)
        x = (LARGURA - _largura(aberto, fonte, tamanho)) / 2
        self.pagina.insert_text((x, self.y), aberto, fontname=fonte,
                                fontsize=tamanho, color=cor)
        self.y += tamanho + 2 + espaco_depois

    def paragrafo(self, texto, *, tamanho=11, fonte=SERIF, cor=PRETO,
                  recuo_primeira=28, espaco_antes=0, espaco_depois=9,
                  entrelinha=5.0, realces=(), fonte_realce=SERIF_NEGRITO):
        """Escreve um parágrafo de prosa, justificado às duas margens.

        A justificação é o que separa visualmente um documento de um formulário,
        e é por isso que está aqui: a certidão deixou de ser uma lista de pares
        rótulo/valor e passou a ser texto corrido, como as que se passavam nos
        livros de notas.

        A última linha de cada parágrafo NÃO se justifica — espalhar quatro
        palavras por toda a largura é o erro clássico de quem justifica à mão. E
        uma linha cujos intervalos tivessem de crescer mais do que ESTICAO_MAXIMO
        também não: mais do que isso lê-se como buraco e não como alinhamento.
        """
        self.y += espaco_antes
        largura_util = LARGURA - 2 * MARGEM_X
        # Menos um ponto do que a caixa: a última palavra de uma linha
        # justificada acaba exatamente no limite, e o teste das margens compara
        # com a medição do próprio PyMuPDF, que arredonda de outra maneira.
        alvo = largura_util - 1
        linhas = _quebrar_em_palavras(
            _marcar(texto, realces, fonte, fonte_realce),
            largura_util - recuo_primeira, largura_util, tamanho)
        for i, palavras in enumerate(linhas):
            self._nova_pagina_se_preciso(tamanho + entrelinha)
            x = MARGEM_X + (recuo_primeira if i == 0 else 0)
            limite = alvo - (recuo_primeira if i == 0 else 0)
            ultima = i == len(linhas) - 1
            self._escrever_palavras(palavras, x, limite, tamanho, cor,
                                    justificar=not ultima)
            self.y += tamanho + entrelinha
        self.y += espaco_depois

    # Quanto pode um intervalo entre palavras crescer, em pontos, antes de a
    # linha ficar pior justificada do que alinhada à esquerda.
    ESTICAO_MAXIMO = 7.0

    def _escrever_palavras(self, palavras, x, limite, tamanho, cor, *,
                           justificar):
        """Escreve as palavras de uma linha, esticando os intervalos ou não.

        Cada palavra traz o seu próprio tipo de letra, porque numa linha podem
        conviver redondo e negrito. O intervalo a seguir a uma palavra mede-se
        no tipo DESSA palavra: o espaço do negrito é mais largo que o do
        redondo, e medi-los todos pelo redondo encolhia a linha o suficiente
        para a justificação encostar a última palavra à seguinte.
        """
        if not palavras:
            return
        larguras = [_largura(p, f, tamanho) for p, f in palavras]
        espacos = [_largura(" ", f, tamanho) for _, f in palavras]
        intervalos = len(palavras) - 1
        esticao = 0.0
        if justificar and intervalos:
            folga = limite - sum(larguras) - sum(espacos[:intervalos])
            candidato = folga / intervalos
            if 0 < candidato <= self.ESTICAO_MAXIMO:
                esticao = candidato
        cursor = x
        for i, ((palavra, fonte), larg) in enumerate(
                zip(palavras, larguras, strict=True)):
            self.pagina.insert_text((cursor, self.y), palavra, fontname=fonte,
                                    fontsize=tamanho, color=cor)
            cursor += larg + espacos[i] + esticao

    def altura_de(self, texto, *, tamanho=11, fonte=SERIF, recuo_primeira=28,
                  entrelinha=5.0, espaco_antes=0, espaco_depois=9,
                  realces=(), fonte_realce=SERIF_NEGRITO):
        """Diz quanto espaço um parágrafo vai ocupar, sem o escrever.

        Serve para reservar um bloco inteiro antes de o começar. A nota de
        conferência saía partida entre duas páginas e deixava a segunda com uma
        linha só — pior do que duas páginas cheias, porque parece defeito.
        """
        largura_util = LARGURA - 2 * MARGEM_X
        # Os realces entram na conta: o negrito é mais largo que o redondo e
        # uma linha a mais é uma linha a mais. Medir sem eles reservava espaço
        # a menos e a caixa da nota de conferência fechava a meio do texto.
        linhas = _quebrar_em_palavras(
            _marcar(texto, realces, fonte, fonte_realce),
            largura_util - recuo_primeira, largura_util, tamanho)
        return espaco_antes + len(linhas) * (tamanho + entrelinha) + espaco_depois

    def reservar(self, altura):
        """Muda de página se o bloco seguinte não couber inteiro nesta."""
        self._nova_pagina_se_preciso(altura)

    def ancorar_no_fundo(self, altura):
        """Empurra o cursor para um bloco de dada altura acabar junto ao rodapé.

        A nota de conferência não é continuação do texto: é o painel por onde a
        certidão se confere, e o sítio de um painel desses é o pé da folha.
        Corrida logo a seguir à assinatura, ficava a flutuar a meio da página
        com um palmo de branco por baixo — que se lê como texto que faltou.

        Se o bloco NÃO couber no que resta, não se empurra nada: muda de página
        e fica no alto da seguinte, como o reservar() já fazia. Um painel no
        alto de uma folha lê-se; um painel por cima do rodapé, não.
        """
        fundo = ALTURA - MARGEM_BAIXO
        if self.y + altura <= fundo:
            self.y = fundo - altura
        else:
            self._nova_pagina_se_preciso(altura)

    def _centrado_em(self, texto, x0, largura, *, tamanho=10.5, fonte=SERIF,
                     cor=PRETO, espaco_depois=2):
        """Centra um texto dentro de uma caixa que não é a largura da página.

        O centrado() centra na folha. Isto centra numa coluna — debaixo do traço
        da assinatura, que desde 09/10/2026 está encostado à direita e já não
        coincide com o meio da página.
        """
        for pedaco in _quebrar(texto, largura, tamanho, fonte):
            self._nova_pagina_se_preciso(tamanho + espaco_depois)
            x = x0 + (largura - _largura(pedaco, fonte, tamanho)) / 2
            self.pagina.insert_text((x, self.y), pedaco, fontname=fonte,
                                    fontsize=tamanho, color=cor)
            self.y += tamanho + 2
        self.y += espaco_depois

    def assinatura(self, nome, cargo="", *, alinhamento="centro"):
        """Deixa o traço por onde a certidão se assina, com o nome por baixo.

        Uma certidão passa a valer quando alguém a assina, e era assim que as
        antigas acabavam. O traço não é decoração: é o sítio onde isso acontece,
        e a sua ausência é que faria deste PDF um documento que afirma ser uma
        certidão sem o ser.

        Encostado à DIREITA, deixa livre a metade esquerda para o lugar do selo
        — que é a disposição de um documento que se assina e se carimba, e não a
        de um certificado com o nome ao meio.
        """
        largura_traco = 230
        self._nova_pagina_se_preciso(78)
        self.y += 20
        x0 = (LARGURA - MARGEM_X - largura_traco if alinhamento == "direita"
              else (LARGURA - largura_traco) / 2)
        self.pagina.draw_line((x0, self.y), (x0 + largura_traco, self.y),
                              color=PRETO, width=0.8)
        self.y += 15
        self._centrado_em(nome, x0, largura_traco, tamanho=10.5)
        if cargo:
            self._centrado_em(cargo, x0, largura_traco, tamanho=9.5,
                              fonte=SERIF_ITALICO, cor=CINZA)

    def lugar_do_selo(self, linhas, *, centro, raio=RAIO_DO_SELO, nota=""):
        """Desenha, a tracejado, o lugar onde se carimba o exemplar impresso.

        A TRACEJADO e com a legenda por baixo, porque é o que é: um lugar. Este
        PDF não leva selo nenhum, e um círculo a cheio num documento oficial
        lê-se como selo aposto — seria o desenho a afirmar o que o texto não
        afirma, que é a forma mais silenciosa de um documento mentir.

        Não mexe no cursor: desenha em coordenadas absolutas, ao lado do bloco
        da assinatura, e quem chama é que reservou o espaço dos dois.
        """
        x, y = centro
        self.pagina.draw_circle((x, y), raio, color=VERDE, width=0.7,
                                dashes="[2.2 2.2] 0")
        # A largura disponível dentro de um círculo ENCOLHE à medida que se sobe
        # ou desce do meio: a corda a uma distância d do centro mede
        # 2·raiz(r²−d²). Medir pelo diâmetro punha as linhas de cima e de baixo
        # a sair pelo arco fora, que é o erro de quem trata um círculo como caixa.
        def cabe(tamanho):
            passo = tamanho + 2
            topo = -(len(linhas) - 1) * passo / 2
            for i, texto in enumerate(linhas):
                d = abs(topo + i * passo) + tamanho / 2
                corda = 2 * (max(raio * raio - d * d, 0.0) ** 0.5)
                if _largura(texto, SERIF, tamanho) > corda * 0.92:
                    return False
            return True
        tamanho = 6.0
        while tamanho > 3.5 and not cabe(tamanho):
            tamanho -= 0.25
        passo = tamanho + 2
        topo = y - (len(linhas) - 1) * passo / 2 + tamanho / 3
        for i, texto in enumerate(linhas):
            largura = _largura(texto, SERIF, tamanho)
            self.pagina.insert_text((x - largura / 2, topo + i * passo), texto,
                                    fontname=SERIF, fontsize=tamanho, color=VERDE)
        if nota:
            # A legenda é mais larga do que o círculo, e centrada nele saía pela
            # margem esquerda fora — a 41 pt, quase em cima da moldura. Encosta
            # à margem do texto quando não cabe centrada, que é o alinhamento
            # que o resto da folha já tem.
            largura = _largura(nota, SERIF_ITALICO, 6)
            self.pagina.insert_text((max(MARGEM_X, x - largura / 2),
                                     y + raio + 11), nota,
                                    fontname=SERIF_ITALICO, fontsize=6, color=CINZA)

    def caixa(self, topo, fundo, *, folga=10, cor=VERDE, largura_traco=0.6):
        """Encerra numa caixa um bloco já escrito, da margem do texto para fora.

        A caixa cresce para FORA da margem, e não para dentro: assim o texto
        mantém a medida que tem no resto do documento e não há um parágrafo com
        setenta caracteres por linha a seguir a outro com sessenta.
        """
        self.pagina.draw_rect(
            fitz.Rect(MARGEM_X - folga, topo, LARGURA - MARGEM_X + folga, fundo),
            color=cor, width=largura_traco)

    def moldura(self):
        """Traça a moldura dupla em TODAS as páginas, depois de tudo escrito.

        Como o rodapé, só se pode desenhar no fim: enquanto o texto não acabar,
        há páginas que ainda não existem. Os afastamentos vivem em MOLDURA_FORA
        e MOLDURA_DENTRO, e a régua de dentro passa por fora de tudo o que se
        escreve — incluindo o folio, que desce aos 794,5 pt.
        """
        for pagina in self.doc:
            for recuo, traco in ((MOLDURA_FORA, 1.1), (MOLDURA_DENTRO, 0.5)):
                pagina.draw_rect(
                    fitz.Rect(recuo, recuo, LARGURA - recuo, ALTURA - recuo),
                    color=VERDE, width=traco)

    def imagem(self, caminho, *, largura_desejada=120, espaco_depois=10):
        """Assenta uma imagem centrada no topo, se o ficheiro existir.

        Falhar a abrir o logótipo não pode impedir a emissão de uma certidão: o
        documento vale pelo que afirma, não pelo brasão. Sem o ficheiro, a
        certidão sai sem ele e o resto fica igual.
        """
        if not caminho:
            return
        try:
            with fitz.open(caminho) as img:
                prop = img[0].rect.height / img[0].rect.width
        except Exception:
            return
        alt = largura_desejada * prop
        self._nova_pagina_se_preciso(alt + espaco_depois)
        x0 = (LARGURA - largura_desejada) / 2
        self.pagina.insert_image(
            fitz.Rect(x0, self.y, x0 + largura_desejada, self.y + alt),
            filename=caminho, keep_proportion=True)
        self.y += alt + espaco_depois

    def par_de_imagens(self, caminhos, *, altura=ALTURA_DO_TIMBRE,
                       intervalo=INTERVALO_DO_TIMBRE, espaco_depois=10):
        """Assenta as peças do timbre lado a lado, à mesma altura e centradas.

        O timbre da Câmara são DUAS peças — o monograma e o logótipo de texto —
        e é assim que aparecem nos editais e no expositor. Compô-las aqui, em vez
        de guardar um terceiro ficheiro já junto, evita ter um logótipo a mais
        para manter quando a Câmara mudar o seu.

        Alinham-se pela ALTURA e não pela largura: os dois ficheiros têm
        proporções muito diferentes — 134x118 e 375x96 — e escalá-los pela
        largura dava o monograma do tamanho de um selo ao lado de um letreiro.

        Uma peça que falte salta-se, e sem nenhuma a certidão sai sem timbre.
        Era já a regra do imagem(): o documento vale pelo que afirma.
        """
        pecas = []
        for caminho in caminhos:
            if not caminho:
                continue
            try:
                with fitz.open(caminho) as img:
                    rect = img[0].rect
                    pecas.append((caminho, altura * rect.width / rect.height))
            except Exception:
                _log.warning("peça do timbre ilegível, sai sem ela: %r", caminho)
        if not pecas:
            return
        total = sum(larg for _, larg in pecas) + intervalo * (len(pecas) - 1)
        self._nova_pagina_se_preciso(altura + espaco_depois)
        x = (LARGURA - total) / 2
        for caminho, larg in pecas:
            self.pagina.insert_image(fitz.Rect(x, self.y, x + larg, self.y + altura),
                                     filename=caminho, keep_proportion=True)
            x += larg + intervalo
        self.y += altura + espaco_depois

    def risco(self, *, espaco_antes=6, espaco_depois=12, cor=(0.85, 0.83, 0.77),
              largura_traco=0.7, encolher=0):
        """Traça uma linha horizontal separadora."""
        self.y += espaco_antes
        self._nova_pagina_se_preciso(espaco_depois)
        self.pagina.draw_line((MARGEM_X + encolher, self.y),
                              (LARGURA - MARGEM_X - encolher, self.y),
                              color=cor, width=largura_traco)
        self.y += espaco_depois

    def rodape(self, texto, direita_por_pagina=None):
        """Escreve o rodapé em TODAS as páginas, no fim de tudo.

        Só aqui se sabe quantas páginas há, e é por isso que esta chamada é a
        última de gerar(): «fl. 2 de 3» não se pode escrever antes de se saber
        que são três.

        O texto QUEBRA-SE à largura que sobra depois do folio. A primeira versão
        escrevia-o de uma assentada na mesma linha de base: medido com uma morada
        realista — «Largo do Tabolado e Praceta das Oliveiras, n.º 123, 3620-324
        Moimenta da Beira, Viseu, Portugal» — dava 484,7 pt para 426,1 pt de
        espaço, ou seja passava por cima do número de folha e saía da página.
        Quem configura a morada não tem como adivinhar o limite, por isso o
        limite trata de si próprio: o texto quebra, a letra encolhe até 5 pt, e
        o número de linhas que cabem sai da geometria da faixa — duas a 7 pt,
        três a 5 pt. Se nem assim couber, corta-se e DIZ-SE no registo, em vez
        de desaparecer morada configurada sem ninguém dar por isso.
        """
        total = self.n_paginas
        base = ALTURA - MARGEM_BAIXO + 26
        folio_largo = max(_largura(f"fl. {i} de {total}", SERIF, 7)
                          for i in range(1, total + 1))
        # 14 pt de intervalo entre o texto e o folio, para não se tocarem.
        disponivel = LARGURA - 2 * MARGEM_X - folio_largo - 14
        linhas = _quebrar(texto, disponivel, 7, SERIF) if texto else []
        # Duas linhas é o que a faixa de baixo comporta sem invadir o corpo. Se
        # nem assim couber, encolhe-se a letra: um rodapé pequeno lê-se, um
        # rodapé cortado a meio da morada não.
        tamanho = 7.0
        while len(linhas) > _linhas_de_rodape(tamanho) and tamanho > 5.0:
            tamanho -= 0.5
            linhas = _quebrar(texto, disponivel, tamanho, SERIF)
        cabem = _linhas_de_rodape(tamanho)
        if len(linhas) > cabem:
            # Chegados aqui, a letra já está no mínimo e o texto continua a não
            # caber na faixa. Corta-se — mas DIZ-SE: a primeira versão cortava
            # em silêncio, e o que se perdia era morada, telefone ou sítio de um
            # município num documento que entra num processo.
            _log.warning(
                "rodapé da certidão cortado: %d linhas configuradas, %d cabem a "
                "%.1f pt. Perde-se: %r", len(linhas), cabem, tamanho,
                " ".join(linhas[cabem:]))
            linhas = linhas[:cabem]
        for i in range(1, total + 1):
            pagina = self.doc[i - 1]
            topo = base - (len(linhas) - 1) * (tamanho + 2) if linhas else base
            pagina.draw_line((MARGEM_X, topo - 12), (LARGURA - MARGEM_X, topo - 12),
                             color=(0.82, 0.80, 0.74), width=0.6)
            for n, linha in enumerate(linhas):
                pagina.insert_text((MARGEM_X, topo + n * (tamanho + 2)), linha,
                                   fontname=SERIF, fontsize=tamanho, color=CINZA)
            folha = f"fl. {i} de {total}"
            pagina.insert_text(
                (LARGURA - MARGEM_X - _largura(folha, SERIF, 7), base), folha,
                fontname=SERIF, fontsize=7, color=CINZA)
            if direita_por_pagina:
                pagina.insert_text(
                    (LARGURA - MARGEM_X - _largura(direita_por_pagina, SERIF, 7),
                     base + 9), direita_por_pagina,
                    fontname=SERIF, fontsize=7, color=CINZA)



# Larguras de cada carácter, por (tipo de letra, tamanho). O _largura() mede
# carácter a carácter e é chamado muitas vezes por linha ao justificar; sem esta
# cache, uma certidão de duas folhas fazia dezenas de milhar de chamadas ao
# PyMuPDF para medir as mesmas trinta letras.
_LARGURA_DE_CARACTER: dict = {}


def _largura(texto, fonte, tamanho):
    """Mede a largura de um texto, contornando um defeito do PyMuPDF.

    O fitz.get_text_length() erra a conta de qualquer texto que leve um
    carácter fora do ASCII. Mediu-se assim, e é reprodutível:

        'DELIBERACOES'    devolve 82,50 e desenha 82,50
        '«DELIBERACOES'   devolve 80,06 e desenha 88,00
        '«a'              devolve  5,50 e desenha 10,38

    Repare-se na última: acrescentar uma letra ao texto não aumentou a medida
    nenhuma. A função deixa de contar a partir do carácter que não sabe ler.

    A versão anterior media o texto com os ACENTOS retirados, e acertava — mas
    só nos acentos. Nas aspas angulares «» não acertava, e a certidão passou a
    citar o assunto entre angulares: o resultado foi a primeira palavra do
    assunto desenhada por cima da segunda, à vista de quem lesse.

    A correção é somar a largura de cada carácter, um a um. Nos tipos base do
    PDF o avanço de uma cadeia é a soma dos avanços dos seus caracteres — não há
    ligaduras nem kerning — e a medição confirma-o nos três casos acima, ao
    centésimo. Deixa de haver tabela de equivalências a manter, e deixa de haver
    uma classe inteira de caracteres por onde a régua possa voltar a falhar.
    """
    cache = _LARGURA_DE_CARACTER.setdefault((fonte, tamanho), {})
    total = 0.0
    for caracter in str(texto):
        largura = cache.get(caracter)
        if largura is None:
            largura = fitz.get_text_length(caracter, fontname=fonte,
                                           fontsize=tamanho)
            cache[caracter] = largura
        total += largura
    return total


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


def _marcar(texto, realces, fonte, fonte_realce):
    """Reparte um texto em palavras, dizendo com que tipo cada uma se escreve.

    O realce é A PALAVRA INTEIRA e não o trecho exato. Se o trecho começar ou
    acabar a meio de uma palavra, a palavra vai inteira em negrito. É uma
    limitação deliberada: mudar de tipo a meio de uma palavra obrigava a tratar
    cada palavra como uma lista de pedaços em toda a aritmética de quebra de
    linha e de justificação, e o que se ganhava era pôr «Beira» em negrito e a
    vírgula a seguir em redondo — distinção que ninguém faz a ler.

    Um realce que NÃO apareça no texto não impede a emissão: fica registado e o
    parágrafo sai sem ele. Os realces saem de dados do registo — um nome, um
    número, uma referência — e uma certidão sem negrito continua a certificar
    exatamente os mesmos factos. Rebentar aqui seria trocar um documento por
    uma falha de aspeto.

    Returns:
        list[tuple[str, str]]: cada palavra e o tipo de letra com que se escreve.
    """
    limpo = " ".join(str(texto).split())
    marca = [False] * len(limpo)
    for trecho in realces:
        alvo = " ".join(str(trecho).split())
        if not alvo:
            continue
        # TODAS as ocorrências, e não só a primeira. Uma certidão de um edital
        # afixado e retirado no mesmo dia cita a mesma data por extenso duas
        # vezes: marcar só a primeira dava a afixação em negrito e a retirada
        # em redondo, que se lê como distinção e não é nenhuma.
        inicio = limpo.find(alvo)
        if inicio < 0:
            _log.warning("realce %r não consta do parágrafo; sai sem negrito", alvo)
            continue
        while inicio >= 0:
            for i in range(inicio, inicio + len(alvo)):
                marca[i] = True
            inicio = limpo.find(alvo, inicio + len(alvo))
    palavras, posicao = [], 0
    for palavra in limpo.split(" "):
        if palavra:
            realcada = any(marca[posicao:posicao + len(palavra)])
            palavras.append((palavra, fonte_realce if realcada else fonte))
        posicao += len(palavra) + 1
    return palavras


def _largura_da_linha(palavras, tamanho):
    """Mede uma linha cujas palavras podem não estar todas no mesmo tipo.

    Não se pode medir o " ".join() da linha de uma assentada, como se fazia
    quando o tipo era um só: o negrito e o redondo têm larguras diferentes para
    a mesma letra, e o resultado seria a medida de uma linha que não é esta.
    """
    if not palavras:
        return 0.0
    total = sum(_largura(p, f, tamanho) for p, f in palavras)
    # O intervalo entre duas palavras escreve-se no tipo da que fica à esquerda.
    return total + sum(_largura(" ", f, tamanho) for _, f in palavras[:-1])


def _quebrar_em_palavras(palavras, largura_primeira, largura, tamanho):
    """Parte palavras já marcadas nas linhas que cabem, devolvendo-as separadas.

    O _quebrar() devolve as linhas já juntas com espaços, o que serve para quem
    só as vai escrever. Para justificar é preciso o contrário: ter as palavras
    separadas, porque é entre elas que o espaço se estica — e cada uma leva o
    seu tipo de letra, que o _marcar() já lhe atribuiu.

    A primeira linha leva uma largura própria por causa do recuo do parágrafo —
    tem menos espaço que as outras, e medi-la com a largura das outras punha-lhe
    uma palavra a mais, que ia parar à margem.

    Args:
        palavras (list[tuple[str, str]]): cada palavra e o seu tipo de letra.

    Returns:
        list[list[tuple[str, str]]]: as palavras de cada linha, pela ordem do texto.
    """
    # A primeira palavra parte-se pela largura da PRIMEIRA linha, não pela da
    # caixa. Medido: uma palavra de 90 letras mede 439,6 pt — cabe na caixa de
    # 451 e não cabe nos 423 que sobram depois do recuo do parágrafo, e ficava
    # inteira a transbordar 16,6 pt para lá da margem. Apanhado em revisão.
    partidas = []
    for i, (palavra, fonte) in enumerate(palavras):
        limite = largura_primeira if i == 0 else largura
        partidas.extend((pedaco, fonte) for pedaco
                        in _partir_palavra(palavra, limite, tamanho, fonte))
    if not partidas:
        return [[]]
    linhas, atual = [], [partidas[0]]
    for par in partidas[1:]:
        disponivel = largura_primeira if not linhas else largura
        if _largura_da_linha(atual + [par], tamanho) <= disponivel:
            atual.append(par)
        else:
            linhas.append(atual)
            atual = [par]
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


def _identificacao(f: dict, d: dict, referencia: str) -> tuple[str, list[str]]:
    """Lista os elementos que identificam o documento, sem introdução nenhuma.

    Separada das frases que a usam porque o documento é o mesmo esteja ele
    afixado ou não — e porque a primeira versão disto montava a frase do caso
    «nunca afixado» com um replace() sobre a frase do caso normal, o que deu
    «O documento é o que se destinava a ser afixado (...) o seguinte documento».

    Montar por concatenação condicional, e não por um molde fixo com buracos, é
    o que evita a certidão dizer «da autoria de» seguido de nada: um edital pode
    não ter número, pode não ter entidade conhecida e pode ter uma folha ou sete.

    Devolve TAMBÉM os trechos a pôr em negrito, e não os deixa a quem chama. São
    os mesmos moldes — «n.º X», «"assunto"» — e tê-los escritos duas vezes em
    sítios diferentes acabaria com um molde alterado num só e o negrito a
    desaparecer sem ninguém reparar.

    Returns:
        tuple[str, list[str]]: a enumeração, e os trechos a realçar.
    """
    partes = [d["rotulo"].lower()]
    realces = []
    if f["numero"]:
        partes.append(f"com o n.º {f['numero']}")
        # Com o «n.º » à frente, e não o número sozinho: um edital numerado «5»
        # punha em negrito o primeiro «5» que aparecesse na frase, que podia ser
        # o de uma data. Os realces procuram-se por texto, logo levam contexto.
        realces.append(f"n.º {f['numero']}")
    else:
        partes.append("a que não foi atribuído número")
    if f["entidade"]:
        partes.append(f"da autoria de {f['entidade']}")
        realces.append(f["entidade"])
    if f["data_publicacao"]:
        partes.append(f"com data de {ext.data(f['data_publicacao'])}")
    if f["assunto"]:
        partes.append(f"cujo assunto é «{f['assunto']}»")
        realces.append(f"«{f['assunto']}»")
    if f["num_paginas"]:
        partes.append(f"composto de {ext.folhas(f['num_paginas'])}")
    partes.append("a que corresponde nesta aplicação a referência interna "
                  f"{referencia}")
    realces.append(referencia)
    return ", ".join(partes), realces


def _frase_do_documento(f: dict, d: dict, referencia: str,
                        local: str) -> tuple[str, list[str]]:
    """A frase que certifica a afixação e identifica o que foi afixado."""
    # «no local designado por «X»» e não «no X»: o artigo tinha de concordar com
    # um valor que vem da configuração e pode ser de qualquer género e número.
    # Com «no» fixo e a inicial minusculizada, um município que escrevesse
    # «Receção» ou «Paços do Concelho» obtinha «no receção» e «no Paços». Assim
    # o valor sai tal e qual foi escrito, entre angulares, e não concorda com
    # nada — que é o que o torna correto para todos os casos de uma vez.
    enumeracao, realces = _identificacao(f, d, referencia)
    return (f"que, para os devidos efeitos, foi afixado por este Município, no "
            f"local designado por «{local}», o seguinte documento: "
            f"{enumeracao}."), [f"«{local}»"] + realces


def _frase_da_afixacao(f: dict, nomes: dict) -> tuple[str, list[str]]:
    """Compõe a frase do ato: quando foi afixado, por quem, e até quando.

    Realça as DATAS e os NOMES, que são o que alguém procura ao abrir esta
    certidão. O «quem então servia» fica em redondo de propósito: é a admissão
    de que o registo não guardou o nome, e pô-la em negrito dava-lhe o peso de
    um facto apurado.

    Returns:
        tuple[str, list[str]]: a frase, e os trechos a realçar.
    """
    quem = nomes.get(f["afixado_por"], f["afixado_por"]) or "quem então servia"
    realces = [ext.aos(f["afixado_em"])]
    if nomes.get(f["afixado_por"], f["afixado_por"]):
        realces.append(quem)
    inicio = (f"Mais certifico que a afixação teve lugar "
              f"{ext.aos(f['afixado_em'])}, {ext.hora(f['afixado_em'])}, "
              f"por {quem}")
    dias = dias_de_afixacao(f) or 0
    if f["desafixado_em"]:
        tirou = nomes.get(f["desafixado_por"], f["desafixado_por"]) or "quem então servia"
        realces.append(ext.aos(f["desafixado_em"]))
        if nomes.get(f["desafixado_por"], f["desafixado_por"]):
            realces.append(tirou)
        return (f"{inicio}, e que foi retirado "
                f"{ext.aos(f['desafixado_em'])}, {ext.hora(f['desafixado_em'])}, "
                f"por {tirou}, tendo permanecido afixado {ext.dias(dias)}."), realces
    fim = (f"{inicio}, e que à data de hoje se mantém afixado, decorridos "
           f"{ext.dias(dias)} sobre a afixação")
    if f["data_retirada"]:
        fim += f", estando a sua retirada prevista para {ext.data(f['data_retirada'])}"
        realces.append(ext.data(f["data_retirada"]))
    return fim + ".", realces


def _pecas_do_timbre(cfg: dict) -> list[str]:
    """As imagens do cabeçalho, por ordem de colocação.

    O `logo_certidao` existe para quem tenha um timbre próprio já composto num
    ficheiro, e sobrepõe-se a tudo. Sem ele, usam-se as DUAS peças do logótipo
    que a aplicação já tem para o expositor — o monograma e o letreiro — que
    são as mesmas que vão nos editais em papel. A ordem é a do logótipo da
    Câmara: o símbolo à esquerda, o texto à direita.

    Até 09/10/2026 o recurso era o `logo_txt` sozinho, e a certidão saía com
    meio timbre: o letreiro sem o monograma, que não é o cabeçalho de lado
    nenhum.
    """
    proprio = cfg.get("logo_certidao")
    if proprio:
        return [proprio]
    return [c for c in (cfg.get("logo_sym"), cfg.get("logo_txt")) if c]


def _linha_do_rodape(cfg: dict) -> str:
    """Junta a morada, o sítio e o telefone, saltando o que não estiver posto.

    O desenho vem do rodapé dos próprios editais do Município — rótulos
    separados por barras. Os VALORES não vêm daí: ficam na configuração, porque
    ler um código postal de uma fotografia de um ecrã e escrevê-lo no código
    seria inventar a morada de uma câmara municipal.
    """
    partes = []
    for rotulo, chave in (("Morada", "morada"), ("Sítio", "sitio"),
                          ("Telefone", "telefone")):
        if cfg.get(chave):
            partes.append(f"{rotulo}: {cfg[chave]}")
    return "   |   ".join(partes)


def gerar(reg: dict, cfg: dict, *, emitida_por: str, nome_de_quem_emite: str = "",
          nomes_completos: dict | None = None) -> bytes:
    """Produz a certidão de afixação e desafixação de um edital, em PDF.

    A certidão é PROSA e não um formulário, e a mudança foi pedida a 07/10/2026
    com as certidões de oitocentos como modelo. Não é gosto: um documento que
    afirma factos sobre um ato administrativo lê-se melhor em frases, e as
    datas por extenso existem porque um algarismo se altera com um traço de
    caneta e «vinte e nove» não. Era por isso que os livros de notas se
    escreviam assim.

    O que NÃO mudou: os factos que o selo cobre. O factos() está igual e o
    FORMATO continua em 2, pelo que as certidões já emitidas continuam a
    conferir — esta é uma alteração de aspeto, e a regra do FORMATO diz
    expressamente que ele sobe pelos factos e nunca pelo aspeto.

    Args:
        reg (dict): o registo do edital.
        cfg (dict): configuração (município, serviço, local do expositor, e as
            chaves opcionais do timbre: cargo_de_quem_certifica, logo_certidao,
            morada, sitio, telefone).
        emitida_por (str): conta que pediu a certidão.
        nome_de_quem_emite (str): nome completo dessa pessoa, para a assinatura.
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
    # A configuração de campo tem «Moimenta da Beira», sem o «Município de» —
    # e a prosa diria «do Moimenta da Beira». O formulário antigo nunca esbarrou
    # nisto porque punha o nome sozinho num cabeçalho, onde não concorda com nada.
    municipio = cfg.get("municipio", "Moimenta da Beira")
    if not municipio.lower().startswith(("município", "municipio")):
        municipio = f"Município de {municipio}"
    emitente = nome_de_quem_emite or nomes.get(emitida_por, emitida_por)
    cargo = cfg.get("cargo_de_quem_certifica", "")
    # O `or` e não um `.get(chave, omissao)`: o load_config faz
    # cfg.update(json.loads(...)), portanto um "local_do_expositor": "" escrito
    # no config.json SOBREPÕE-SE ao valor por omissão e chega aqui vazio. A
    # versão anterior fazia local[0] a seguir e rebentava com IndexError — no
    # caminho de emissão de uma certidão, que é o pior sítio para rebentar.
    local = (cfg.get("local_do_expositor") or "").strip() or \
        "Expositor eletrónico do Município"

    # ---- timbre ----------------------------------------------------------
    # O cabeçalho é o da Câmara e não meio: o monograma E o logótipo de texto,
    # lado a lado, como estão nos editais e no expositor. Até 09/10/2026 saía só
    # o logótipo de texto, e foi a primeira coisa que se notou ao pôr a certidão
    # ao lado de um ofício do Município. O logo_certidao continua a sobrepor-se
    # aos dois, para quem tenha um timbre próprio já composto num ficheiro.
    folha.par_de_imagens(_pecas_do_timbre(cfg), espaco_depois=18)
    estado = " · ".join(p for p in ("REPÚBLICA PORTUGUESA",
                                    (cfg.get("distrito") or "").upper()) if p)
    folha.centrado(estado, tamanho=7, cor=CINZA, espaco_depois=7)
    folha.espacado(municipio.upper(), tamanho=11, espaco_depois=3)
    if cfg.get("servico"):
        folha.centrado(cfg["servico"], tamanho=9.5, fonte=SERIF_ITALICO,
                       cor=CINZA, espaco_depois=2)
    # Duas réguas e não uma, a grossa por cima da fina: é o remate do timbre dos
    # editais, e repete à largura do texto o que a moldura faz à do papel.
    folha.risco(espaco_antes=9, espaco_depois=5, cor=VERDE, largura_traco=1.3)
    folha.risco(espaco_antes=0, espaco_depois=22, cor=VERDE, largura_traco=0.4)

    # ---- título ----------------------------------------------------------
    # Entre duas réguas curtas, como os títulos das certidões antigas: o título
    # fica num compartimento seu e não encostado ao timbre nem ao corpo.
    # O espaço DEPOIS da régua tem de dar para a altura das maiúsculas do
    # título, que assentam na linha de base: com os 15 pt da primeira tentativa,
    # a régua passava a meio do «CERTIDÃO».
    folha.risco(espaco_antes=0, espaco_depois=26, encolher=200, cor=VERDE,
                largura_traco=0.9)
    folha.espacado("CERTIDÃO", tamanho=19, espaco_depois=7)
    folha.centrado("de afixação e desafixação de edital", tamanho=11,
                   fonte=SERIF_ITALICO, cor=CINZA, espaco_depois=4)
    folha.risco(espaco_antes=2, espaco_depois=18, encolher=200, cor=VERDE,
                largura_traco=0.9)

    # ---- quem certifica --------------------------------------------------
    apresentacao = emitente.upper()
    if cargo:
        apresentacao += f", {cargo}"
    folha.paragrafo(f"{apresentacao}, do {municipio}:", recuo_primeira=0,
                    espaco_depois=12)
    folha.espacado("CERTIFICA", tamanho=13, espaco_depois=11)

    # ---- o que certifica -------------------------------------------------
    if f["afixado_em"]:
        texto, realces = _frase_do_documento(f, d, reg_mod.referencia(reg), local)
        folha.paragrafo(texto, realces=realces)
        texto, realces = _frase_da_afixacao(f, nomes)
        folha.paragrafo(texto, realces=realces)
    else:
        # Uma certidão de um edital que nunca foi afixado continua a ser uma
        # certidão: certifica que o documento existe no registo e que a
        # afixação não chegou a acontecer. Calar-se seria pior.
        folha.paragrafo(
            "que o documento adiante identificado consta do registo de editais "
            "deste Município e NÃO chegou a ser afixado.")
        enumeracao, realces = _identificacao(f, d, reg_mod.referencia(reg))
        folha.paragrafo("O documento é o seguinte: " + enumeracao + ".",
                        realces=realces)

    if d.get("base_legal"):
        texto = f"O prazo de afixação é o fixado no {d['base_legal']}."
        if d.get("nota"):
            texto += f" {d['nota']}"
        folha.paragrafo(texto)

    # ---- ressalvas -------------------------------------------------------
    # Um incumprimento ou um palpite por confirmar não se omitem de uma
    # certidão. Uma certidão que escondesse o que a lei pede e o que de facto
    # aconteceu seria pior do que não haver certidão nenhuma.
    #
    # São DOIS tipos e não um. As minhas são meias-frases, feitas à medida de
    # «Ressalva-se que ...». As do prazos.py são frases completas, às vezes
    # DUAS — «Sem data de retirada: fica no ecrã indefinidamente. O mínimo legal
    # é 5 dias de afixação.» — e metê-las no mesmo molde dava «Ressalva-se que
    # sem data de retirada: fica no ecrã...», que não é português. Citam-se tal
    # e qual, que é o que se faz a um texto de outra autoria.
    minhas, legais = [], []
    if f["campos_por_confirmar"]:
        quais = ", ".join(ROTULOS_DOS_CAMPOS.get(c, c)
                          for c in f["campos_por_confirmar"])
        minhas.append(
            f"os seguintes elementos foram lidos automaticamente do documento e "
            f"não chegaram a ser confirmados por quem o afixou: {quais}")
    if d.get("base_legal") and f["afixado_em"]:
        for aviso in pr.verificar(f["tipo"], f["afixado_em"][:10] or None,
                                  (f["desafixado_em"] or "")[:10] or None,
                                  f["data_publicacao"] or None):
            if aviso["grau"] == "aviso":
                legais.append(aviso["texto"].strip())
    escritas = 0
    for frase in minhas:
        folha.paragrafo(("Ressalva-se que " if not escritas
                         else "Ressalva-se ainda que ") + frase + ".",
                        fonte=SERIF_ITALICO)
        escritas += 1
    for aviso in legais:
        # Sem rstrip nem minusculização: o aviso já é uma frase (ou duas) e já
        # acaba em ponto. Juntar outro imprimia «...deste tipo de documento..».
        folha.paragrafo(("Ressalva-se o seguinte: " if not escritas
                         else "Ressalva-se ainda: ") + aviso,
                        fonte=SERIF_ITALICO)
        escritas += 1

    # ---- fecho e assinatura ---------------------------------------------
    folha.paragrafo("Por ser verdade e me ter sido pedida, mandei passar a "
                    "presente certidão, que vai por mim assinada.",
                    espaco_antes=4)
    hoje = datetime.now()
    folha.paragrafo(f"{municipio}, {ext.aos(hoje)}.", recuo_primeira=0,
                    espaco_depois=2)
    # O bloco do fecho é UM só: o selo à esquerda e a assinatura à direita, à
    # mesma altura. Reserva-se inteiro antes de começar, senão a assinatura
    # mudava de página e o selo ficava desenhado na anterior, sozinho — o
    # lugar_do_selo() desenha em coordenadas absolutas e não sabe de páginas.
    folha.reservar(2 * RAIO_DO_SELO + 22)
    topo_do_fecho = folha.y
    folha.assinatura(emitente, cargo, alinhamento="direita")
    folha.lugar_do_selo(
        ["MUNICÍPIO DE", municipio.upper().replace("MUNICÍPIO DE ", ""),
         "LOCUS SIGILLI"],
        centro=(MARGEM_X + RAIO_DO_SELO + 6, topo_do_fecho + RAIO_DO_SELO + 6),
        nota="lugar do selo branco, a apor no exemplar impresso")
    # A assinatura é mais curta do que o selo e deixava o cursor a meio dele: o
    # que viesse a seguir escrevia-se por cima do círculo. O cursor desce ao
    # mais baixo dos dois, que é sempre a legenda do selo.
    folha.y = max(folha.y, topo_do_fecho + 2 * RAIO_DO_SELO + 20)

    # ---- nota de conferência --------------------------------------------
    # O aparato técnico vive aqui, depois da assinatura e em corpo pequeno, e
    # não misturado com o que a certidão afirma. É a divisão que as certidões
    # antigas já faziam entre o texto e as anotações de registo: em cima o que
    # se certifica, em baixo como se confere.
    # Rótulo e valor separados, e não já juntos numa cadeia: os rótulos vão a
    # negrito, e o realce procura-se por texto. Tê-los escritos aqui é a única
    # forma de a lista a realçar não poder divergir da lista impressa.
    conferencia = [("Registo n.º", str(f["id"])),
                   ("referência interna", reg_mod.referencia(reg))]
    if f["hash_original"]:
        conferencia.append(("resumo do original", agrupar(f["hash_original"])))
    conferencia.append(("ficheiro de origem", f["ficheiro_origem"]))
    conferencia.append(("selo de conferência", f"{selo(f)} (formato {FORMATO})"))
    identificadores = " · ".join(f"{r} {v}" for r, v in conferencia) + "."
    rotulos = [r for r, _ in conferencia]
    if f["disponivel_em"]:
        anexo = (f"O documento entrou na rotação do expositor em "
                 f"{_pt(f['disponivel_em'])}. Este registo confirma a "
                 f"disponibilização material e não substitui o instante de "
                 f"afixação certificado acima, que é o do ato administrativo.")
    else:
        anexo = ("Sem registo de entrada na rotação do expositor. A ausência "
                 "deste registo não afeta a afixação certificada acima: "
                 "respeita apenas à confirmação material do funcionamento do "
                 "equipamento.")
    emissao = (f"Certidão emitida em {_pt(hoje.isoformat(timespec='seconds'))} "
               f"por {emitente} ({emitida_por}), a partir do registo de editais. "
               f"O selo de conferência permite confirmar, junto do serviço "
               f"emissor, que esta certidão corresponde ao registo. Não "
               f"constitui assinatura eletrónica.")

    # A nota vai inteira ou não vai: partida entre duas páginas, deixava a
    # segunda com uma linha solta, que se lê como defeito de impressão e não
    # como documento. O miudinho de uma certidão fica junto do seu título.
    pequeno = dict(tamanho=7.5, recuo_primeira=0, entrelinha=2.5)
    acima_da_caixa = 8        # ar entre o fecho e o cimo da caixa
    folga_de_dentro = 8       # entre a régua da caixa e o que lá vai escrito
    altura_do_titulo = 18     # «NOTA DE CONFERÊNCIA» e o espaço que leva
    bloco = acima_da_caixa + 2 * folga_de_dentro + altura_do_titulo + sum(
        folha.altura_de(t, espaco_depois=e, realces=r, **pequeno)
        for t, e, r in ((identificadores, 4, rotulos), (anexo, 4, ()),
                        (emissao, 0, ())))
    folha.ancorar_no_fundo(bloco)

    folha.y += acima_da_caixa
    topo_da_nota = folha.y
    folha.y += folga_de_dentro
    folha.centrado("NOTA DE CONFERÊNCIA", tamanho=8, fonte=SERIF_NEGRITO,
                   cor=CINZA, espaco_depois=8)
    folha.paragrafo(identificadores, cor=CINZA, espaco_depois=4,
                    realces=rotulos, **pequeno)
    folha.paragrafo(anexo, cor=CINZA, espaco_depois=4, **pequeno)
    folha.paragrafo(emissao, cor=CINZA, espaco_depois=0, **pequeno)
    # A caixa fecha-se DEPOIS de escrita: só aqui se sabe onde o texto acabou.
    # Substitui a régua solta que havia antes — uma régua separa, uma caixa diz
    # «isto é outra coisa», que é o que o miudinho de conferência é.
    folha.caixa(topo_da_nota, folha.y + folga_de_dentro - 3)

    folha.rodape(_linha_do_rodape(cfg))
    # Por último de tudo, que é quando se sabe quantas páginas há.
    folha.moldura()

    doc.set_metadata({
        "title": f"Certidão de afixação e desafixação — registo {f['id']}",
        "author": municipio,
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
