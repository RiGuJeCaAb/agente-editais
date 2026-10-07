"""
test_certidao.py — O documento que a aplicação emite para valer perante terceiros.

Uma certidão errada é pior do que nenhuma: afirma factos sobre um ato
administrativo e vai para dentro de um processo. Por isso testa-se o conteúdo,
e não só se o PDF sai sem exceção.
"""
from __future__ import annotations

import pymupdf
import pytest

import certidao as cert
import extenso as ext
import prazos as pr

CFG = {
    "municipio": "Município de Moimenta da Beira",
    "servico": "Divisão Administrativa e Financeira",
    "local_do_expositor": "Expositor eletrónico do átrio dos Paços do Concelho",
}
NOMES = {"ana.abreu": "Ana Abreu", "rui.santos": "Rui Santos"}


@pytest.fixture(autouse=True)
def tabela_limpa():
    pr.carregar_tipos({})


@pytest.fixture
def afixado():
    """Um edital com o percurso completo: afixado e desafixado dentro do prazo."""
    return {
        "id": 17, "numero": "2026-0017",
        "assunto": "DELIBERAÇÕES PROFERIDAS PELA ASSEMBLEIA MUNICIPAL COM "
                   "EFICÁCIA EXTERNA, NA SESSÃO ORDINÁRIA DE 29 DE JUNHO",
        "entidade": "ASSEMBLEIA MUNICIPAL", "tipo": "deliberacao_orgao_autarquico",
        "data_publicacao": "2026-06-29", "ficheiro_origem": "edital_am_17.pdf",
        # Resumo com os dígitos hexadecimais MAIS LARGOS em Times, de propósito.
        # Um resumo com muitos '1' é estreito e cabia na caixa; um resumo real
        # pode não caber, e foi assim que a primeira versão transbordou apesar
        # de este teste passar. O pior caso não deixa o teste passar por sorte.
        "sha256": "d" * 64,
        "afixado_em": "2026-06-29T09:14:00", "afixado_por": "ana.abreu",
        "desafixado_em": "2026-07-06T17:02:00", "desafixado_por": "rui.santos",
        "disponivel_em": "2026-06-29T09:14:31",
    }


def texto_de(pdf: bytes) -> str:
    """Devolve o texto de todas as páginas de um PDF."""
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        return "\n".join(p.get_text() for p in d)


def corrido(pdf: bytes) -> str:
    """O mesmo texto, com os espaços todos reduzidos a um.

    A certidão é prosa justificada: cada linha é desenhada à parte e a extração
    devolve-a com a quebra lá dentro. Procurar «não chegaram a ser confirmados»
    no texto cru falha quando a frase calha partir-se ao meio — e o que esses
    testes defendem é que a frase LÁ ESTÁ, não onde o parágrafo quebra.
    """
    return " ".join(texto_de(pdf).split())


def test_a_certidao_afirma_os_factos_todos(afixado):
    """Tudo o que identifica o ato tem de estar escrito no documento."""
    t = corrido(cert.gerar(afixado, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    for esperado in ("C E R T I D Ã O", "de afixação e desafixação de edital",
                     "C E R T I F I C A", "2026-0017",
                     "ASSEMBLEIA MUNICIPAL", "Ana Abreu", "Rui Santos",
                     # As datas e as horas por extenso, que é o que muda tudo:
                     # um algarismo altera-se com um traço de caneta, «vinte e
                     # nove» não. Era por isso que os livros de notas se
                     # escreviam assim, e é a razão de esta certidão voltar lá.
                     "vinte e nove dias do mês de junho de 2026",
                     "pelas nove horas e catorze minutos",
                     "seis dias do mês de julho de 2026",
                     "pelas dezassete horas e dois minutos",
                     "permanecido afixado sete dias",
                     "Artigo 56.º do Anexo I da Lei n.º 75/2013",
                     # O local sai TAL E QUAL foi configurado, entre angulares:
                     # não há artigo a concordar com ele, e por isso não há como
                     # errar o género nem o número.
                     f"no local designado por «{CFG['local_do_expositor']}»",
                     "Por ser verdade e me ter sido pedida"):
        assert esperado in t, f"falta na certidão: {esperado}"


def test_diz_que_nao_e_assinatura_eletronica(afixado):
    """Honestidade explícita: o selo confere, não assina.

    Sem esta frase, um selo de aspeto criptográfico convida a ser tomado por
    uma assinatura qualificada, que não é.
    """
    t = corrido(cert.gerar(afixado, CFG, emitida_por="ana.abreu"))
    assert "Não constitui assinatura eletrónica" in t


def test_o_incumprimento_aparece_na_certidao(afixado):
    """Uma afixação curta de mais é dita, não omitida.

    Uma certidão que escondesse o que a lei pede e o que de facto aconteceu
    seria pior do que não haver certidão nenhuma.
    """
    curto = dict(afixado, desafixado_em="2026-07-01T10:00:00")
    t = corrido(cert.gerar(curto, CFG, emitida_por="ana.abreu"))
    assert "Ressalva-se" in t and "abaixo do mínimo" in t


def test_edital_ainda_no_ecra(afixado):
    """Sem desafixação, a certidão diz que se mantém, e conta os dias decorridos."""
    t = corrido(cert.gerar(dict(afixado, desafixado_em="", desafixado_por=""),
                            CFG, emitida_por="ana.abreu"))
    assert "se mantém afixado" in t and "foi retirado aos" not in t


def test_anexo_distingue_disponibilidade_de_afixacao(afixado):
    """O anexo tem de dizer que NÃO substitui o instante oficial.

    É a decisão de 18/09/2026: o instante que conta é o do ato administrativo,
    e o registo do expositor é confirmação material. Confundi-los poria a
    validade de um ato a depender do uptime de uma televisão.
    """
    t = corrido(cert.gerar(afixado, CFG, emitida_por="ana.abreu"))
    assert "NOTA DE CONFERÊNCIA" in t
    assert "não substitui o instante de afixação" in t


def test_sem_registo_de_disponibilidade_o_anexo_desvaloriza_se(afixado):
    """A ausência do registo material não pode parecer um defeito da afixação."""
    t = corrido(cert.gerar(dict(afixado, disponivel_em=""), CFG, emitida_por="ana.abreu"))
    assert "não afeta a afixação certificada" in t


def test_nada_transborda_a_margem(afixado):
    """Nenhum texto passa a margem direita da página.

    Guarda a regressão que deu origem a _largura(): o get_text_length do PyMuPDF
    mede os caracteres acentuados dos tipos base como se não ocupassem largura
    ('AÇÃO' devolve 23,3 pt e desenha 30,9 pt), e a primeira versão desta
    certidão transbordava 19,8 pt — logo nas palavras com acento, que numa
    certidão em português são quase todas.
    """
    pdf = cert.gerar(afixado, CFG, emitida_por="ana.abreu", nomes_completos=NOMES)
    limite = cert.LARGURA - cert.MARGEM_X
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        extremos = [s["bbox"][2] for p in d for b in p.get_text("dict")["blocks"]
                    for linha in b["lines"] for s in linha["spans"]]
    assert max(extremos) <= limite, f"transborda {max(extremos) - limite:.1f} pt"


def test_uma_palavra_maior_que_a_caixa_e_partida(afixado):
    """Um resumo SHA-256 não tem espaços e é mais largo do que a caixa.

    Medido: 336 pt numa caixa de 329. A quebra por espaços não o resolve, e o
    resultado era a certidão a transbordar a margem — logo na linha que
    identifica o documento afixado.
    """
    largura = 329
    pedacos = cert._quebrar("d" * 64, largura, 10.5, cert.SERIF_NEGRITO)
    assert len(pedacos) > 1
    assert "".join(pedacos) == "d" * 64          # não se perde um carácter
    for pedaco in pedacos:
        assert cert._largura(pedaco, cert.SERIF_NEGRITO, 10.5) <= largura


def test_o_resumo_e_escrito_em_grupos():
    """Sessenta e quatro caracteres seguidos não se leem nem se comparam.

    E comparar é exatamente o que alguém faz com este valor. Os grupos dão ainda
    à quebra de linha sítios naturais onde partir, o que evita o carácter órfão
    que a versão anterior deixava na linha seguinte.
    """
    assert cert.agrupar("abcd" * 16) == " ".join(["abcdabcd"] * 8)
    assert cert.agrupar("ABCD1234", por=4) == "ABCD 1234"
    # Agrupar não pode perder nem inventar caracteres.
    assert cert.agrupar("d" * 64).replace(" ", "") == "d" * 64


def test_palavra_que_cabe_nao_e_partida():
    """A quebra por carácter é último recurso, não comportamento normal."""
    assert cert._quebrar("assunto normal", 329, 10.5, cert.SERIF) == ["assunto normal"]


def test_a_medicao_de_largura_conta_os_acentos(afixado):
    """A régua trata 'AÇÃO' e 'ACAO' como tendo a mesma largura, que é a verdade."""
    assert cert._largura("AÇÃO", cert.SERIF, 10.5) == cert._largura("ACAO", cert.SERIF, 10.5)
    assert cert._largura("AÇÃO", cert.SERIF, 10.5) > 0


def test_o_selo_muda_com_qualquer_facto(afixado):
    """Alterar um facto altera o selo — é o que o torna útil para conferir."""
    base = cert.selo(cert.factos(afixado))
    for campo, valor in [("afixado_por", "outra.pessoa"),
                         ("desafixado_em", "2026-07-20T17:02:00"),
                         ("numero", "2026-0018"), ("assunto", "Outro assunto")]:
        assert cert.selo(cert.factos(dict(afixado, **{campo: valor}))) != base


def test_o_selo_e_estavel_e_nao_depende_da_ordem_dos_campos(afixado):
    """A mesma informação dá sempre o mesmo selo, em qualquer ordem.

    Sem sort_keys, reordenar um dicionário mudaria o selo sem mudar um facto —
    e uma certidão legítima passaria a não conferir.
    """
    baralhado = dict(reversed(list(afixado.items())))
    assert cert.selo(cert.factos(afixado)) == cert.selo(cert.factos(baralhado))
    assert cert.selo(cert.factos(afixado)) == cert.selo(cert.factos(afixado))


# Um SHA-1 a sério (40 dígitos hexadecimais), como o caminho de entrada o
# escreve. O marcador "sha1antigo" que aqui estava antes era mais legível e não
# era um resumo — e a certidão passou a distinguir uma coisa da outra.
SHA1_ANTIGO = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"


def test_a_certidao_prefere_o_sha256_ao_hash_antigo(afixado):
    """O documento cita o endereço do original no arquivo imutável."""
    assert cert.factos(afixado)["hash_original"] == afixado["sha256"]
    antigo = {k: v for k, v in afixado.items() if k != "sha256"}
    antigo["hash"] = SHA1_ANTIGO
    assert cert.factos(antigo)["hash_original"] == SHA1_ANTIGO


@pytest.mark.parametrize("valor", [
    "migrado:20260017deliberacoes",   # chave sintética de um edital migrado
    "sha1antigo",                     # um marcador qualquer
    "",
    "zzzz" * 16,                      # comprimento certo, não hexadecimal
    "a1b2c3",                         # hexadecimal, comprimento nenhum
])
def test_a_certidao_cala_se_quando_o_campo_nao_e_um_resumo(afixado, valor):
    """Um resumo que não é um resumo não entra num documento com fé pública.

    O campo `hash` nem sempre traz um resumo de ficheiro: um edital migrado do
    modelo automático cujo original já não estava na pasta leva lá uma chave
    sintética, que serve para o registo não colidir consigo próprio e para mais
    nada. Imprimi-la debaixo de «Resumo do original» era a certidão afirmar que
    conferiu um documento que nunca viu.
    """
    reg = {k: v for k, v in afixado.items() if k != "sha256"}
    reg["hash"] = valor
    assert cert.factos(reg)["hash_original"] == ""


@pytest.mark.parametrize("afixacao,desafixacao,esperado", [
    ("2026-06-29T09:00:00", "2026-07-06T09:00:00", 7),
    ("2026-06-29T09:00:00", "2026-06-29T18:00:00", 0),
    ("2026-09-18T10:00:00", "2026-07-01T10:00:00", 0),   # ao contrário
    (None, None, None),
])
def test_contagem_de_dias(afixacao, desafixacao, esperado):
    """A duração nunca é negativa: datas ao contrário dão zero, não um absurdo."""
    assert cert.dias_de_afixacao({"afixado_em": afixacao or "",
                                  "desafixado_em": desafixacao or ""}) == esperado


def test_nome_do_ficheiro_segue_a_convencao(afixado):
    """Carimbo temporal à cabeça e o sufixo _CLD, como o resto do projeto."""
    nome = cert.nome_do_ficheiro(afixado)
    assert nome.endswith("_CLD.pdf") and "certidao_afixacao" in nome
    assert nome[:12].isdigit()


def test_assunto_muito_comprido_nao_rebenta():
    """Um assunto de meio quilómetro é partido por linhas, não truncado a meio."""
    pdf = cert.gerar({"id": 1, "assunto": "PALAVRA MUITO COMPRIDA " * 40,
                      "tipo": "outro", "afixado_em": "2026-06-29T09:00:00",
                      "afixado_por": "ana.abreu"}, CFG, emitida_por="ana.abreu")
    assert pdf[:5] == b"%PDF-"
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        assert len(d) >= 1


# ---------------------------------------------------------------------------
# Correções a partir de uma certidão real (registo 19)
#
# Saiu uma certidão do município cujo ASSUNTO era «MUNICÍPIO DE MOIMENTA DA
# BEIRA» — o nome da câmara impresso duas vezes, uma como timbre e outra como
# matéria daquilo que ela própria tinha afixado. A partir daí vieram as outras:
# o número que desaparecia em silêncio, o tamanho do documento que não constava,
# o «0 dia(s)», e o palpite da máquina impresso com ar de facto verificado.
# ---------------------------------------------------------------------------
@pytest.fixture
def ficha(afixado):
    """O registo 19: um documento que não é edital, ainda afixado, sem número."""
    return dict(afixado, id=19, numero="", assunto="FICHA DE PROJETO",
                entidade="MUNICÍPIO DE MOIMENTA DA BEIRA", tipo="outro",
                ficheiro_origem="escola secundaria_ficha de projeto.pdf",
                num_paginas=5, data_retirada="2026-10-20",
                desafixado_em="", desafixado_por="",
                campos_duvidosos=["assunto", "numero"])


def test_o_numero_em_falta_diz_se_em_vez_de_desaparecer(ficha):
    """Um campo que some não se distingue de um campo perdido.

    Só se imprimia quando existia, e quem lia a certidão não sabia se o
    documento não tinha número ou se o sistema o tinha deixado cair.
    """
    t = corrido(cert.gerar(ficha, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "a que não foi atribuído número" in t


def test_a_certidao_diz_quantas_folhas_foram_afixadas(ficha):
    """Identificava o documento pelo nome, data e resumo — nunca pelo tamanho.

    Se amanhã alguém discutir o que esteve no expositor, o número de páginas
    faz parte da identidade daquilo que lá esteve.
    """
    t = corrido(cert.gerar(ficha, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "composto de cinco folhas" in t


def test_uma_pagina_nao_leva_plural(afixado):
    t = corrido(cert.gerar(dict(afixado, num_paginas=1), CFG,
                            emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "composto de uma folha" in t
    assert "uma folhas" not in t


def test_um_documento_ainda_afixado_diz_ate_quando(ficha):
    """Dizer «mantém-se afixado» sem dizer até quando deixa por responder a
    pergunta mais útil da certidão — e é a data que a lei fixa."""
    t = corrido(cert.gerar(ficha, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "retirada prevista para vinte dias do mês de outubro de 2026" in t


@pytest.mark.parametrize("dias,esperado", [
    (0, "menos de um dia"), (1, "um dia"), (2, "dois dias"), (30, "trinta dias"),
])
def test_os_dias_escrevem_se_com_concordancia(dias, esperado):
    """«0 dia(s)» era duas coisas más de uma vez: o parêntesis do plural, que
    não se escreve num documento que vai para um processo, e o zero, que em
    português não é uma duração.

    A conta mudou de casa para o extenso.py quando a certidão passou a prosa:
    numa frase corrida, «2 dias» desafina ao lado de «vinte e nove dias do mês
    de junho»."""
    assert ext.dias(dias) == esperado


def test_a_certidao_nao_tem_o_parentesis_do_plural(ficha):
    t = corrido(cert.gerar(ficha, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "dia(s)" not in t


def test_a_certidao_declara_o_que_ninguem_confirmou(ficha):
    """Um palpite da máquina impresso com o mesmo ar de um facto verificado
    passa a facto oficial. Foi assim que o timbre da câmara virou o assunto de
    um documento afixado."""
    t = corrido(cert.gerar(ficha, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "não chegaram a ser confirmados" in t
    assert "o assunto" in t
    assert "o número" in t


def test_sem_duvidas_a_certidao_cala_se(afixado):
    """A ressalva só aparece quando há alguma coisa a ressalvar. Uma nota que
    está sempre lá deixa de ser lida."""
    t = corrido(cert.gerar(dict(afixado, campos_duvidosos=[]), CFG,
                            emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "não chegaram a ser confirmados" not in t


def test_a_certidao_diz_o_formato_a_que_o_selo_pertence(afixado):
    """O selo é calculado sobre os factos: acrescentar um facto muda o selo do
    mesmo registo, e uma certidão antiga deixaria de conferir — o que se parece
    com uma falsificação em vez de com uma actualização. Com o formato impresso,
    quem confere sabe que conta refazer."""
    t = corrido(cert.gerar(afixado, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    assert f"formato {cert.FORMATO}" in t


def test_o_selo_cobre_os_factos_novos(afixado):
    """De nada serve imprimir as páginas se o selo não as cobrir: bastava
    alterar o número no papel para a conferência continuar a bater certo."""
    base = cert.selo(cert.factos(afixado))
    for campo, valor in [("num_paginas", 99), ("data_retirada", "2026-12-31"),
                         ("campos_duvidosos", ["assunto"])]:
        assert cert.selo(cert.factos(dict(afixado, **{campo: valor}))) != base, campo


# --- a referência interna, e a fronteira do selo ------------------------------
# Estes três nasceram de um defeito desta mesma peça, apanhado em revisão: a
# referência tinha entrado em factos(), e o selo é calculado sobre esse
# dicionário. O selo do MESMO registo passou a ser outro com o rodapé a dizer
# «formato 2» na mesma, e as certidões já emitidas deixavam de conferir.

def test_a_referencia_nao_e_um_facto_selado(afixado):
    """O selo atesta o que esteve afixado, quando e por quem. A referência é
    uma etiqueta nossa, e dar-lhe o selo era dar-lhe uma dignidade que não tem.
    """
    assert "referencia" not in cert.factos(afixado)


def test_o_selo_nao_se_mexe_por_causa_de_um_campo_que_nao_cobre(afixado):
    """A regra geral, e não só o caso desta peça.

    O `criado_em` não está nos factos selados. Se um campo derivado dele entrar
    no selo, o selo passa a mudar sem que nenhum facto selado tenha mudado — e
    quem confere um papel legítimo vê uma discrepância que ninguém consegue
    explicar. Vale para a referência e para o que lá quiserem pôr a seguir.
    """
    base = cert.selo(cert.factos(dict(afixado, criado_em="2026-06-28T08:00:00")))
    outro = cert.selo(cert.factos(dict(afixado, criado_em="2026-01-02T23:59:59")))
    assert base == outro


def test_a_referencia_imprime_se_na_folha_a_seguir_ao_numero(afixado):
    """Sair do selo não é sair da certidão: imprime-se, só não se atesta.

    E imprime-se rotulada, porque uma etiqueta interna ao lado de um número
    oficial sem nada a distingui-los é pior do que não a imprimir de todo.
    """
    t = corrido(cert.gerar(dict(afixado, criado_em="2026-06-28T08:00:00"), CFG,
                            emitida_por="ana.abreu", nomes_completos=NOMES))
    assert "referência interna AE-20260628-0017" in t
    assert t.index("com o n.º") < t.index("referência interna")


# --- o que a mudança para prosa não podia mexer ------------------------------
# A certidão mudou de forma por inteiro. Estes guardam o que tinha de ficar
# exatamente igual, e dois deles guardam defeitos que a mudança destapou.
#
# DOIS PASSAM DOS DOIS LADOS DE PROPÓSITO, e está dito aqui porque a casa obriga
# a dizê-lo: o do selo e o da sobreposição de palavras. Não provam o que se
# acrescentou — provam que o que se acrescentou não passou por cima de nada.
#
#   - o do selo fixa um valor que TEM de ser o mesmo antes e depois: é a prova
#     de que a reescrita não tocou num facto. Falhar aqui é a certidão de um
#     registo antigo deixar de conferir, que é o pior defeito deste projeto.
#   - o da sobreposição passava antes porque não havia justificação nenhuma e
#     portanto não havia como duas palavras colidirem. Falhou — e foi assim que
#     se apanhou — contra a versão intermédia desta mesma peça, com a régua
#     ainda errada nas aspas angulares.
#
# Os outros dois falham contra o código anterior, confirmado com git stash.

def test_o_selo_de_um_registo_conhecido_nao_mudou(afixado):
    """O selo deste registo tem de continuar a ser este, dígito a dígito.

    É a regra do FORMATO ao contrário: ele sobe quando muda o CONJUNTO DE
    FACTOS e nunca quando muda o aspeto. Esta peça mudou o aspeto todo — de
    formulário para prosa — e não podia tocar num facto. Se este valor mudar,
    as certidões já emitidas deixam de conferir com o rodapé a dizer o mesmo
    formato, que é o aspeto exato de uma falsificação.

    Quando um dia houver mesmo um facto novo, sobe-se o FORMATO e atualiza-se
    este número — e aí a mudança é deliberada, que é todo o ponto.
    """
    assert cert.FORMATO == 2
    assert cert.selo(cert.factos(afixado)) == "0129 7FA6 7E5E B66C"
    # As 17 chaves que o selo cobre, nem mais nem menos. Uma chave a mais muda
    # o selo de todos os registos de uma vez.
    assert len(cert.factos(afixado)) == 17


def test_a_regua_mede_as_aspas_angulares(afixado):
    """O get_text_length do PyMuPDF para de contar no primeiro carácter que não
    sabe ler, e as aspas angulares são um deles.

    Medido: '«a' devolvia 5,50 e desenha 10,38 — acrescentar uma letra não
    aumentava a medida nenhuma. A régua anterior media o texto com os ACENTOS
    retirados e acertava só neles; a certidão passou a citar o assunto entre
    «angulares» e a primeira palavra do assunto saía desenhada por cima da
    segunda.
    """
    for texto in ("«a", "«DELIBERAÇÕES", "AÇÃO»", "«assunto qualquer»"):
        medido = cert._largura(texto, cert.SERIF, 11)
        soma = sum(cert._largura(c, cert.SERIF, 11) for c in texto)
        assert abs(medido - soma) < 0.01, texto
        assert medido > cert._largura(texto[1:], cert.SERIF, 11)


def test_nenhuma_palavra_se_desenha_por_cima_da_seguinte(afixado):
    """A justificação coloca cada palavra pela conta da régua, uma a uma.

    Uma régua que meça a menos não dá uma linha torta: dá palavras sobrepostas,
    ilegíveis, num documento que vai para um processo. Este teste olha para as
    palavras realmente desenhadas e exige que cada uma acabe antes de a
    seguinte começar.
    """
    pdf = cert.gerar(afixado, CFG, emitida_por="ana.abreu", nomes_completos=NOMES)
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        for pagina in d:
            # (x0, y0, x1, y1, palavra, bloco, linha, n.º da palavra)
            por_linha: dict = {}
            for p in pagina.get_text("words"):
                por_linha.setdefault((p[5], p[6]), []).append(p)
            for palavras in por_linha.values():
                palavras.sort(key=lambda p: p[0])
                for antes, depois in zip(palavras, palavras[1:], strict=False):
                    assert antes[2] <= depois[0] + 0.5, \
                        f"«{antes[4]}» sobrepõe-se a «{depois[4]}»"


def test_o_nome_do_municipio_concorda_na_frase():
    """A configuração de campo tem «Moimenta da Beira», sem o «Município de».

    Numa certidão em prosa isso dá «do Moimenta da Beira». O formulário antigo
    nunca esbarrou nisto porque punha o nome sozinho num cabeçalho, onde não
    concorda com nada — foi a mudança para prosa que o destapou.
    """
    reg = {"id": 1, "numero": "1", "assunto": "A", "entidade": "", "tipo": "outro",
           "data_publicacao": "2026-06-29", "ficheiro_origem": "e.pdf",
           "criado_em": "2026-06-28T08:00:00", "num_paginas": 1,
           "afixado_em": "2026-06-29T09:00:00", "afixado_por": "ana.abreu"}
    t = corrido(cert.gerar(reg, {"municipio": "Moimenta da Beira"},
                           emitida_por="ana.abreu"))
    assert "do Município de Moimenta da Beira" in t
    assert "do Moimenta da Beira" not in t
    # E quem já escreveu o nome por extenso não leva o prefixo duas vezes.
    t2 = corrido(cert.gerar(reg, {"municipio": "Município de Moimenta da Beira"},
                            emitida_por="ana.abreu"))
    assert "Município de Município" not in t2


def test_um_local_do_expositor_em_branco_nao_impede_a_certidao():
    """Um «"local_do_expositor": ""» no config.json rebentava com IndexError.

    O load_config() faz cfg.update(json.loads(...)): a chave presente com valor
    vazio SOBREPÕE-SE ao valor por omissão e chega cá como "". O .get(chave,
    omissao) só protege a chave em FALTA, e a seguir fazia-se local[0].

    Antes da reescrita isto imprimia um campo vazio; depois dela deixava de
    emitir a certidão — e este é o caminho do pedido de certidão, onde não se
    rebenta. Apanhado em revisão, e reproduzido antes de se lhe tocar.
    """
    reg = {"id": 1, "numero": "1", "assunto": "A", "entidade": "", "tipo": "outro",
           "data_publicacao": "2026-06-29", "ficheiro_origem": "e.pdf",
           "criado_em": "2026-06-28T08:00:00", "num_paginas": 1,
           "afixado_em": "2026-06-29T09:00:00", "afixado_por": "ana.abreu"}
    t = corrido(cert.gerar(reg, {"municipio": "Moimenta da Beira",
                                 "local_do_expositor": ""},
                           emitida_por="ana.abreu"))
    assert "Expositor eletrónico do Município" in t


@pytest.mark.parametrize("local", [
    "Átrio do edifício dos Paços do Concelho",   # masculino singular
    "Receção do edifício dos Paços do Concelho",  # feminino
    "Paços do Concelho",                          # plural
    "Vitrina exterior",                           # feminino singular
])
def test_o_local_nao_tem_de_concordar_com_artigo_nenhum(local):
    """A frase dizia «foi afixado no {local}», com o artigo fixo e a inicial
    minusculizada à força. Para «Receção» dava «no receção»; para «Paços do
    Concelho», «no Paços».

    O valor vem da configuração de cada município e pode ser de qualquer género
    e número — não há artigo que sirva a todos. A frase passa a citá-lo entre
    angulares, onde não concorda com nada, e o valor sai tal e qual foi escrito.
    """
    reg = {"id": 1, "numero": "1", "assunto": "A", "entidade": "", "tipo": "outro",
           "data_publicacao": "2026-06-29", "ficheiro_origem": "e.pdf",
           "criado_em": "2026-06-28T08:00:00", "num_paginas": 1,
           "afixado_em": "2026-06-29T09:00:00", "afixado_por": "ana.abreu"}
    t = corrido(cert.gerar(reg, {"municipio": "Moimenta da Beira",
                                 "local_do_expositor": local},
                           emitida_por="ana.abreu"))
    assert f"«{local}»" in t, "o local tem de sair tal e qual foi configurado"
    assert f"no {local[0].lower()}{local[1:]}" not in t
