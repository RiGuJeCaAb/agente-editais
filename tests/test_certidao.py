"""
test_certidao.py — O documento que a aplicação emite para valer perante terceiros.

Uma certidão errada é pior do que nenhuma: afirma factos sobre um ato
administrativo e vai para dentro de um processo. Por isso testa-se o conteúdo,
e não só se o PDF sai sem exceção.
"""
from __future__ import annotations

import certidao as cert
import prazos as pr
import pymupdf
import pytest

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


def test_a_certidao_afirma_os_factos_todos(afixado):
    """Tudo o que identifica o ato tem de estar escrito no documento."""
    t = texto_de(cert.gerar(afixado, CFG, emitida_por="ana.abreu", nomes_completos=NOMES))
    for esperado in ("CERTIDÃO DE AFIXAÇÃO E DESAFIXAÇÃO", "2026-0017",
                     "ASSEMBLEIA MUNICIPAL", "29/06/2026", "Ana Abreu", "Rui Santos",
                     "29/06/2026 às 09:14", "06/07/2026 às 17:02", "7 dia(s)",
                     "Artigo 56.º do Anexo I da Lei n.º 75/2013",
                     CFG["local_do_expositor"]):
        assert esperado in t, f"falta na certidão: {esperado}"


def test_diz_que_nao_e_assinatura_eletronica(afixado):
    """Honestidade explícita: o selo confere, não assina.

    Sem esta frase, um selo de aspeto criptográfico convida a ser tomado por
    uma assinatura qualificada, que não é.
    """
    t = texto_de(cert.gerar(afixado, CFG, emitida_por="ana.abreu"))
    assert "Não constitui assinatura eletrónica" in t


def test_o_incumprimento_aparece_na_certidao(afixado):
    """Uma afixação curta de mais é dita, não omitida.

    Uma certidão que escondesse o que a lei pede e o que de facto aconteceu
    seria pior do que não haver certidão nenhuma.
    """
    curto = dict(afixado, desafixado_em="2026-07-01T10:00:00")
    t = texto_de(cert.gerar(curto, CFG, emitida_por="ana.abreu"))
    assert "Observação" in t and "abaixo do mínimo" in t


def test_edital_ainda_no_ecra(afixado):
    """Sem desafixação, a certidão diz que se mantém, e conta os dias decorridos."""
    t = texto_de(cert.gerar(dict(afixado, desafixado_em="", desafixado_por=""),
                            CFG, emitida_por="ana.abreu"))
    assert "Mantém-se afixado" in t and "Desafixado em" not in t


def test_anexo_distingue_disponibilidade_de_afixacao(afixado):
    """O anexo tem de dizer que NÃO substitui o instante oficial.

    É a decisão de 18/09/2026: o instante que conta é o do ato administrativo,
    e o registo do expositor é confirmação material. Confundi-los poria a
    validade de um ato a depender do uptime de uma televisão.
    """
    t = texto_de(cert.gerar(afixado, CFG, emitida_por="ana.abreu"))
    assert "ANEXO" in t and "não substitui o instante de afixação" in t


def test_sem_registo_de_disponibilidade_o_anexo_desvaloriza_se(afixado):
    """A ausência do registo material não pode parecer um defeito da afixação."""
    t = texto_de(cert.gerar(dict(afixado, disponivel_em=""), CFG, emitida_por="ana.abreu"))
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


def test_a_certidao_prefere_o_sha256_ao_hash_antigo(afixado):
    """O documento cita o endereço do original no arquivo imutável."""
    assert cert.factos(afixado)["hash_original"] == afixado["sha256"]
    antigo = {k: v for k, v in afixado.items() if k != "sha256"}
    antigo["hash"] = "sha1antigo"
    assert cert.factos(antigo)["hash_original"] == "sha1antigo"


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
