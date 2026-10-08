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

import extenso as ext
import prazos as pr
import registo as reg_mod

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
MARGEM_TOPO = 64
# A faixa de baixo é do rodapé, e o texto não entra nela. Sem esta reserva, a
# última linha de uma página escrevia-se por cima da morada do município.
MARGEM_BAIXO = 76

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
                  recuo_primeira=28, espaco_antes=0, espaco_depois=10,
                  entrelinha=5.5):
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
        linhas = _quebrar_em_palavras(texto, largura_util - recuo_primeira,
                                      largura_util, tamanho, fonte)
        for i, palavras in enumerate(linhas):
            self._nova_pagina_se_preciso(tamanho + entrelinha)
            x = MARGEM_X + (recuo_primeira if i == 0 else 0)
            limite = alvo - (recuo_primeira if i == 0 else 0)
            ultima = i == len(linhas) - 1
            self._escrever_palavras(palavras, x, limite, tamanho, fonte, cor,
                                    justificar=not ultima)
            self.y += tamanho + entrelinha
        self.y += espaco_depois

    # Quanto pode um intervalo entre palavras crescer, em pontos, antes de a
    # linha ficar pior justificada do que alinhada à esquerda.
    ESTICAO_MAXIMO = 7.0

    def _escrever_palavras(self, palavras, x, limite, tamanho, fonte, cor, *,
                           justificar):
        """Escreve as palavras de uma linha, esticando os intervalos ou não."""
        if not palavras:
            return
        larguras = [_largura(p, fonte, tamanho) for p in palavras]
        espaco_normal = _largura(" ", fonte, tamanho)
        intervalos = len(palavras) - 1
        espaco = espaco_normal
        if justificar and intervalos:
            folga = limite - sum(larguras) - intervalos * espaco_normal
            esticao = folga / intervalos
            if 0 < esticao <= self.ESTICAO_MAXIMO:
                espaco = espaco_normal + esticao
        cursor = x
        for palavra, larg in zip(palavras, larguras, strict=True):
            self.pagina.insert_text((cursor, self.y), palavra, fontname=fonte,
                                    fontsize=tamanho, color=cor)
            cursor += larg + espaco

    def altura_de(self, texto, *, tamanho=11, fonte=SERIF, recuo_primeira=28,
                  entrelinha=5.5, espaco_antes=0, espaco_depois=10):
        """Diz quanto espaço um parágrafo vai ocupar, sem o escrever.

        Serve para reservar um bloco inteiro antes de o começar. A nota de
        conferência saía partida entre duas páginas e deixava a segunda com uma
        linha só — pior do que duas páginas cheias, porque parece defeito.
        """
        largura_util = LARGURA - 2 * MARGEM_X
        linhas = _quebrar_em_palavras(texto, largura_util - recuo_primeira,
                                      largura_util, tamanho, fonte)
        return espaco_antes + len(linhas) * (tamanho + entrelinha) + espaco_depois

    def reservar(self, altura):
        """Muda de página se o bloco seguinte não couber inteiro nesta."""
        self._nova_pagina_se_preciso(altura)

    def assinatura(self, nome, cargo=""):
        """Deixa o traço por onde a certidão se assina, com o nome por baixo.

        Uma certidão passa a valer quando alguém a assina, e era assim que as
        antigas acabavam. O traço não é decoração: é o sítio onde isso acontece,
        e a sua ausência é que faria deste PDF um documento que afirma ser uma
        certidão sem o ser.
        """
        largura_traco = 230
        self._nova_pagina_se_preciso(78)
        self.y += 26
        x0 = (LARGURA - largura_traco) / 2
        self.pagina.draw_line((x0, self.y), (x0 + largura_traco, self.y),
                              color=PRETO, width=0.8)
        self.y += 15
        self.centrado(nome, tamanho=10.5, espaco_depois=2)
        if cargo:
            self.centrado(cargo, tamanho=9.5, fonte=SERIF_ITALICO, cor=CINZA,
                          espaco_depois=2)

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
        limite trata de si próprio.
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
        while len(linhas) > 2 and tamanho > 5.0:
            tamanho -= 0.5
            linhas = _quebrar(texto, disponivel, tamanho, SERIF)
        linhas = linhas[:2]
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


def _quebrar_em_palavras(texto, largura_primeira, largura, tamanho, fonte):
    """Parte um texto em linhas, devolvendo as PALAVRAS de cada uma.

    O _quebrar() devolve as linhas já juntas com espaços, o que serve para quem
    só as vai escrever. Para justificar é preciso o contrário: ter as palavras
    separadas, porque é entre elas que o espaço se estica.

    A primeira linha leva uma largura própria por causa do recuo do parágrafo —
    tem menos espaço que as outras, e medi-la com a largura das outras punha-lhe
    uma palavra a mais, que ia parar à margem.

    Returns:
        list[list[str]]: as palavras de cada linha, pela ordem do texto.
    """
    # A primeira palavra parte-se pela largura da PRIMEIRA linha, não pela da
    # caixa. Medido: uma palavra de 90 letras mede 439,6 pt — cabe na caixa de
    # 451 e não cabe nos 423 que sobram depois do recuo do parágrafo, e ficava
    # inteira a transbordar 16,6 pt para lá da margem. Apanhado em revisão.
    palavras = []
    for i, palavra in enumerate(str(texto).split()):
        limite = largura_primeira if i == 0 else largura
        palavras.extend(_partir_palavra(palavra, limite, tamanho, fonte))
    if not palavras:
        return [[]]
    linhas, atual = [], [palavras[0]]
    for palavra in palavras[1:]:
        disponivel = largura_primeira if not linhas else largura
        tentativa = " ".join(atual + [palavra])
        if _largura(tentativa, fonte, tamanho) <= disponivel:
            atual.append(palavra)
        else:
            linhas.append(atual)
            atual = [palavra]
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


def _identificacao(f: dict, d: dict, referencia: str) -> str:
    """Lista os elementos que identificam o documento, sem introdução nenhuma.

    Separada das frases que a usam porque o documento é o mesmo esteja ele
    afixado ou não — e porque a primeira versão disto montava a frase do caso
    «nunca afixado» com um replace() sobre a frase do caso normal, o que deu
    «O documento é o que se destinava a ser afixado (...) o seguinte documento».

    Montar por concatenação condicional, e não por um molde fixo com buracos, é
    o que evita a certidão dizer «da autoria de» seguido de nada: um edital pode
    não ter número, pode não ter entidade conhecida e pode ter uma folha ou sete.
    """
    partes = [d["rotulo"].lower()]
    partes.append(f"com o n.º {f['numero']}" if f["numero"]
                  else "a que não foi atribuído número")
    if f["entidade"]:
        partes.append(f"da autoria de {f['entidade']}")
    if f["data_publicacao"]:
        partes.append(f"com data de {ext.data(f['data_publicacao'])}")
    if f["assunto"]:
        partes.append(f"cujo assunto é «{f['assunto']}»")
    if f["num_paginas"]:
        partes.append(f"composto de {ext.folhas(f['num_paginas'])}")
    partes.append("a que corresponde nesta aplicação a referência interna "
                  f"{referencia}")
    return ", ".join(partes)


def _frase_do_documento(f: dict, d: dict, referencia: str, local: str) -> str:
    """A frase que certifica a afixação e identifica o que foi afixado."""
    # «no local designado por «X»» e não «no X»: o artigo tinha de concordar com
    # um valor que vem da configuração e pode ser de qualquer género e número.
    # Com «no» fixo e a inicial minusculizada, um município que escrevesse
    # «Receção» ou «Paços do Concelho» obtinha «no receção» e «no Paços». Assim
    # o valor sai tal e qual foi escrito, entre angulares, e não concorda com
    # nada — que é o que o torna correto para todos os casos de uma vez.
    return (f"que, para os devidos efeitos, foi afixado por este Município, no "
            f"local designado por «{local}», o seguinte documento: "
            f"{_identificacao(f, d, referencia)}.")


def _frase_da_afixacao(f: dict, nomes: dict) -> str:
    """Compõe a frase do ato: quando foi afixado, por quem, e até quando."""
    quem = nomes.get(f["afixado_por"], f["afixado_por"]) or "quem então servia"
    inicio = (f"Mais certifico que a afixação teve lugar "
              f"{ext.aos(f['afixado_em'])}, {ext.hora(f['afixado_em'])}, "
              f"por {quem}")
    dias = dias_de_afixacao(f) or 0
    if f["desafixado_em"]:
        tirou = nomes.get(f["desafixado_por"], f["desafixado_por"]) or "quem então servia"
        return (f"{inicio}, e que foi retirado "
                f"{ext.aos(f['desafixado_em'])}, {ext.hora(f['desafixado_em'])}, "
                f"por {tirou}, tendo permanecido afixado {ext.dias(dias)}.")
    fim = (f"{inicio}, e que à data de hoje se mantém afixado, decorridos "
           f"{ext.dias(dias)} sobre a afixação")
    if f["data_retirada"]:
        fim += f", estando a sua retirada prevista para {ext.data(f['data_retirada'])}"
    return fim + "."


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
    folha.imagem(cfg.get("logo_certidao") or cfg.get("logo_txt") or "",
                 largura_desejada=96, espaco_depois=12)
    folha.espacado(municipio.upper(), tamanho=11, espaco_depois=3)
    if cfg.get("servico"):
        folha.centrado(cfg["servico"], tamanho=9.5, fonte=SERIF_ITALICO,
                       cor=CINZA, espaco_depois=2)
    folha.risco(espaco_antes=9, espaco_depois=30, cor=VERDE, largura_traco=1.1)

    # ---- título ----------------------------------------------------------
    folha.espacado("CERTIDÃO", tamanho=20, espaco_depois=8)
    folha.centrado("de afixação e desafixação de edital", tamanho=11,
                   fonte=SERIF_ITALICO, cor=CINZA, espaco_depois=6)
    # Regra curta e centrada, como as que fechavam os títulos das certidões
    # antigas: separa o título do corpo sem cortar a página ao meio.
    folha.risco(espaco_antes=2, espaco_depois=20, encolher=165, cor=VERDE,
                largura_traco=0.9)

    # ---- quem certifica --------------------------------------------------
    apresentacao = emitente.upper()
    if cargo:
        apresentacao += f", {cargo}"
    folha.paragrafo(f"{apresentacao}, do {municipio}:", recuo_primeira=0,
                    espaco_depois=14)
    folha.espacado("CERTIFICA", tamanho=13, espaco_depois=13)

    # ---- o que certifica -------------------------------------------------
    if f["afixado_em"]:
        folha.paragrafo(_frase_do_documento(f, d, reg_mod.referencia(reg), local))
        folha.paragrafo(_frase_da_afixacao(f, nomes))
    else:
        # Uma certidão de um edital que nunca foi afixado continua a ser uma
        # certidão: certifica que o documento existe no registo e que a
        # afixação não chegou a acontecer. Calar-se seria pior.
        folha.paragrafo(
            "que o documento adiante identificado consta do registo de editais "
            "deste Município e NÃO chegou a ser afixado.")
        folha.paragrafo("O documento é o seguinte: "
                        + _identificacao(f, d, reg_mod.referencia(reg)) + ".")

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
                    espaco_antes=6)
    hoje = datetime.now()
    folha.paragrafo(f"{municipio}, {ext.aos(hoje)}.", recuo_primeira=0,
                    espaco_depois=2)
    folha.assinatura(emitente, cargo)

    # ---- nota de conferência --------------------------------------------
    # O aparato técnico vive aqui, depois da assinatura e em corpo pequeno, e
    # não misturado com o que a certidão afirma. É a divisão que as certidões
    # antigas já faziam entre o texto e as anotações de registo: em cima o que
    # se certifica, em baixo como se confere.
    conferencia = [f"Registo n.º {f['id']}",
                   f"referência interna {reg_mod.referencia(reg)}"]
    if f["hash_original"]:
        conferencia.append(f"resumo do original {agrupar(f['hash_original'])}")
    conferencia.append(f"ficheiro de origem {f['ficheiro_origem']}")
    conferencia.append(f"selo de conferência {selo(f)} (formato {FORMATO})")
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
    pequeno = dict(tamanho=8, recuo_primeira=0, entrelinha=3)
    bloco = 18 + 10 + 18 + sum(
        folha.altura_de(t, espaco_depois=e, **pequeno)
        for t, e in ((" · ".join(conferencia) + ".", 6), (anexo, 6), (emissao, 0)))
    folha.reservar(bloco)

    folha.risco(espaco_antes=18, espaco_depois=10, encolher=0)
    folha.centrado("NOTA DE CONFERÊNCIA", tamanho=8, fonte=SERIF_NEGRITO,
                   cor=CINZA, espaco_depois=8)
    folha.paragrafo(" · ".join(conferencia) + ".", cor=CINZA, espaco_depois=6,
                    **pequeno)
    folha.paragrafo(anexo, cor=CINZA, espaco_depois=6, **pequeno)
    folha.paragrafo(emissao, cor=CINZA, espaco_depois=0, **pequeno)

    folha.rodape(_linha_do_rodape(cfg))

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
