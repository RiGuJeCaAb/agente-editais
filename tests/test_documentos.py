"""
test_documentos.py — A leitura dos editais, que é heurística e tem de o assumir.

As expressões regulares estão calibradas para o layout da CMMB. Não são garantias,
e a confiança que cada campo devolve é o que diz ao painel o que assinalar para
confirmação. Estes testes fixam o comportamento nos dois lados: o que se lê bem,
e o que se admite não saber.
"""
from __future__ import annotations

import datetime as dt

import pytest

import documentos as doc

# Um edital da CMMB, no formato em que o texto sai do PDF.
EDITAL = """
MUNICÍPIO DE MOIMENTA DA BEIRA
ASSEMBLEIA MUNICIPAL

EDITAL
AM / 2026
DELIBERAÇÕES PROFERIDAS PELA ASSEMBLEIA MUNICIPAL COM EFICÁCIA EXTERNA
--------------------------------------------------------------------
Número: 2026-0017
Data: 29/06/2026
"""


def test_le_um_edital_completo():
    """O caso normal: número, data e assunto saem todos, com confiança alta."""
    m = doc.extract_metadata(EDITAL, fallback_name="edital.pdf")
    assert m["numero"] == "2026-0017"
    assert m["data_publicacao"] == "2026-06-29"
    assert m["assunto"].startswith("DELIBERAÇÕES PROFERIDAS")
    assert m["entidade"] == "ASSEMBLEIA MUNICIPAL"
    assert all(v >= 0.9 for v in m["confianca"].values())


def test_data_guardada_sempre_em_iso():
    """Internamente a data é ISO, para não haver ambiguidade entre dia e mês.

    O documento traz 29/06/2026. Guardado como 2026-06-29, nunca 2026-29-06 nem
    o inverso — a formatação portuguesa faz-se só na apresentação.
    """
    m = doc.extract_metadata(EDITAL)
    assert m["data_publicacao"] == "2026-06-29"
    assert dt.date.fromisoformat(m["data_publicacao"]).day == 29


def test_sem_texto_recorre_ao_nome_e_assume_a_pouca_confianca():
    """Uma imagem sem OCR não tem conteúdo: o assunto vem do nome, e diz-se."""
    m = doc.extract_metadata("", fallback_name="cartaz_feira_do_livro.png")
    assert m["assunto"] == "Cartaz Feira Do Livro"
    assert m["confianca"]["assunto"] <= 0.2
    assert m["numero"] == "" and m["data_publicacao"] is None


def test_texto_sem_marcador_cai_na_heuristica_de_recurso():
    """Sem 'EDITAL', aceita-se a primeira linha com corpo — e baixa-se a confiança."""
    m = doc.extract_metadata("Aviso aos munícipes sobre a recolha de resíduos verdes",
                             fallback_name="aviso.pdf")
    assert "munícipes" in m["assunto"]
    assert m["confianca"]["assunto"] == 0.5


def test_ocr_poe_teto_na_confianca():
    """Texto vindo de OCR nunca passa por leitura exata.

    O teto 0,75 é deliberado: fica acima do limiar de dúvida (0,6), portanto não
    marca o campo como duvidoso quando a leitura foi boa, mas fica abaixo do que
    uma extração direta obtém, para se distinguirem no painel.
    """
    direto = doc.extract_metadata(EDITAL, fonte_ocr=False)
    lido = doc.extract_metadata(EDITAL, fonte_ocr=True)
    assert max(lido["confianca"].values()) <= 0.75
    assert max(direto["confianca"].values()) > 0.75


@pytest.mark.parametrize("texto,esperado", [
    ("29/06/2026", dt.date(2026, 6, 29)),
    ("29-06-2026", dt.date(2026, 6, 29)),
    ("2026-06-29", dt.date(2026, 6, 29)),
    ("  29/06/2026  ", dt.date(2026, 6, 29)),
    ("30/02/2026", None),      # não existe
    ("junho de 2026", None),
    ("", None),
])
def test_leitura_de_datas(texto, esperado):
    """Aceitam-se os formatos correntes em Portugal; o resto devolve None."""
    assert doc._parse_date(texto) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("DELIBERAÇÕES COM EFICÁCIA EXTERNA", "deliberacoes_com_eficacia_externa"),
    ("Ação Social — Ano 2026", "acao_social_ano_2026"),
    ("  espaços  a  mais  ", "espacos_a_mais"),
    ("//////", ""),
])
def test_slug_seguro_para_nome_de_ficheiro(entrada, esperado):
    """O slug perde acentos e pontuação: é para ir num nome de ficheiro."""
    assert doc.slugify(entrada) == esperado


def test_slug_respeita_o_comprimento_maximo():
    """Um assunto comprido não gera um nome de ficheiro impossível."""
    assert len(doc.slugify("palavra " * 40, maxlen=60)) <= 60


def test_assunto_perde_o_tracejado_de_preenchimento():
    """Os editais usam longas cadeias de traços como enchimento visual."""
    assert doc._clean_subject("ASSUNTO IMPORTANTE ------------------") == "ASSUNTO IMPORTANTE"


def test_formato_desconhecido_e_recusado_com_clareza(tmp_path):
    """Uma extensão que não se sabe ler diz-se, em vez de falhar mais à frente."""
    with pytest.raises(ValueError, match="não suportado"):
        doc.to_pages_and_text(str(tmp_path / "folha.xlsx"), str(tmp_path))


def test_ocr_ausente_nao_derruba_nada(monkeypatch):
    """Sem Tesseract instalado, o OCR devolve vazio — não levanta exceção.

    É a promessa que o README faz e que mantém o agente instalável num posto onde
    ninguém consegue instalar pacotes de sistema.
    """
    import builtins
    real = builtins.__import__

    def sem_pytesseract(nome, *a, **k):
        if nome == "pytesseract":
            raise ImportError("não instalado")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_pytesseract)
    from PIL import Image
    assert doc._ocr_imagem(Image.new("RGB", (10, 10))) == ""


# ---------------------------------------------------------------------------
# O timbre não é o assunto
#
# Saiu uma certidão do município cujo ASSUNTO era «MUNICÍPIO DE MOIMENTA DA
# BEIRA»: o nome da câmara impresso duas vezes, uma como timbre e outra como
# matéria daquilo que ela própria afixou. A heurística de recurso aceitava a
# primeira linha com letras que chegassem, e numa folha timbrada a primeira
# linha é sempre o timbre. Pior: a entidade emissora era procurada numa lista
# fechada de quatro nomes onde «MUNICÍPIO DE ...» não estava, por isso nem
# sequer era reconhecida como entidade — e nada a impedia de virar assunto.
# ---------------------------------------------------------------------------
FOLHA_TIMBRADA = """MUNICÍPIO DE MOIMENTA DA BEIRA
Divisão de Obras e Urbanismo

FICHA DE PROJETO
Escola Secundária de Moimenta da Beira
Data: 18/09/2026
"""


def test_o_timbre_nao_vira_assunto():
    m = doc.extract_metadata(FOLHA_TIMBRADA,
                             fallback_name="escola secundaria_ficha de projeto.pdf")
    assert m["assunto"] == "FICHA DE PROJETO"


def test_o_timbre_e_reconhecido_como_entidade():
    m = doc.extract_metadata(FOLHA_TIMBRADA, fallback_name="x.pdf")
    assert m["entidade"] == "MUNICÍPIO DE MOIMENTA DA BEIRA"


@pytest.mark.parametrize("linha", [
    "MUNICÍPIO DE MOIMENTA DA BEIRA",
    "Município de Moimenta da Beira",
    "CÂMARA MUNICIPAL DE MOIMENTA DA BEIRA",
    "ASSEMBLEIA MUNICIPAL DE MOIMENTA DA BEIRA",
    "JUNTA DE FREGUESIA DE LEOMIL",
    "União das Freguesias de Moimenta e Ariz",
    "REPÚBLICA PORTUGUESA",
])
def test_a_instituicao_e_timbre_esteja_onde_estiver(linha):
    """O nome da instituição nunca é o assunto de coisa nenhuma."""
    assert doc.e_cabecalho(linha) is True
    assert doc.e_cabecalho(linha, no_topo=True) is True


@pytest.mark.parametrize("linha", [
    "Divisão de Obras e Urbanismo",
    "Departamento de Ação Social",
    "Gabinete de Apoio ao Munícipe",
    "Divisão Administrativa e Financeira",
])
def test_a_unidade_so_e_timbre_no_alto_da_folha(linha):
    """O serviço emissor vive no timbre, e o timbre vive no alto."""
    assert doc.e_cabecalho(linha, no_topo=True) is True
    assert doc.e_cabecalho(linha) is False


@pytest.mark.parametrize("linha", [
    "DELIBERAÇÕES DA ASSEMBLEIA MUNICIPAL COM EFICÁCIA EXTERNA",
    "Aviso aos munícipes sobre a recolha de resíduos verdes",
    "FICHA DE PROJETO",
    "Regulamento municipal de trânsito",
    # Estes são o motivo de haver duas listas em vez de uma. São títulos de
    # edital perfeitamente vulgares numa câmara, e começam todos por uma palavra
    # que também abre o nome de um serviço. A primeira versão desta correção
    # engolia-os aos sete, e o teste que devia apanhá-lo só usava títulos que
    # não começavam por essas palavras — passava com o buraco aberto.
    "SERVIÇOS MÍNIMOS DURANTE A GREVE DOS TRABALHADORES",
    "SERVIÇO DE ÁGUAS — INTERRUPÇÃO DO ABASTECIMENTO",
    "UNIDADE DE SAÚDE FAMILIAR — NOVO HORÁRIO",
    "DEPARTAMENTO DE OBRAS — ABERTURA DE CONCURSO PÚBLICO",
    "GABINETE DE APOIO AO EMPRESÁRIO — CANDIDATURAS ABERTAS",
    "SETOR DA EDUCAÇÃO — TRANSPORTES ESCOLARES 2026/2027",
    "DIVISÃO DE URBANISMO — CONSULTA PÚBLICA DO PDM",
])
def test_um_titulo_de_edital_nunca_e_timbre_fora_do_alto(linha):
    """«DELIBERAÇÕES DA ASSEMBLEIA MUNICIPAL ...» começa por uma palavra de
    matéria e só depois nomeia o órgão: é assunto, e tem de continuar a sê-lo.
    Uma exclusão demasiado larga calaria o assunto verdadeiro — que é trocar um
    defeito por outro, e por um pior, porque este é silencioso."""
    assert doc.e_cabecalho(linha) is False


def test_um_edital_pode_chamar_se_servicos_minimos():
    """O caso que a primeira versão da correção partia: abaixo do marcador
    «EDITAL» o que vem é o título, sempre, custe o que custar à heurística."""
    m = doc.extract_metadata(
        "MUNICÍPIO DE MOIMENTA DA BEIRA\n"
        "Divisão Administrativa\n"
        "EDITAL\n"
        "SERVIÇOS MÍNIMOS DURANTE A GREVE DOS TRABALHADORES\n"
        "Número: 2026-0031\n", fallback_name="edital.pdf")
    assert m["assunto"] == "SERVIÇOS MÍNIMOS DURANTE A GREVE DOS TRABALHADORES"
    assert m["confianca"]["assunto"] == 0.9


def test_o_caso_ambiguo_sai_com_pouca_confianca():
    """Sem «EDITAL» e com o título a começar por palavra de unidade logo a
    seguir ao timbre, nenhuma regra de texto acerta — a olho distingue-se pelo
    corpo de letra, que o texto extraído não tem.

    O que NÃO se pode é acertar por acaso e apresentar o resultado como certo.
    A confiança fica abaixo do limiar, o painel assinala e a certidão declara
    que ninguém confirmou. Este teste fixa esse contrato, não o acerto."""
    m = doc.extract_metadata(
        "MUNICÍPIO DE MOIMENTA DA BEIRA\n\n"
        "SERVIÇOS MÍNIMOS DURANTE A GREVE\n"
        "Aviso aos utentes\n", fallback_name="aviso.pdf")
    assert m["confianca"]["assunto"] <= 0.5


def test_um_edital_normal_nao_muda_de_assunto():
    """A correção não pode mexer no caso que já funcionava."""
    m = doc.extract_metadata(EDITAL, fallback_name="edital_am_17.pdf")
    assert m["confianca"]["assunto"] == 0.9
    assert "DELIBERAÇÕES" in m["assunto"]


def test_uma_folha_que_so_tem_timbre_nao_inventa_assunto():
    """Sem matéria nenhuma, o nome do ficheiro e confiança baixa — e não o
    timbre com um ar de assunto legítimo."""
    m = doc.extract_metadata("CÂMARA MUNICIPAL DE MOIMENTA DA BEIRA\n",
                             fallback_name="scan_0042.pdf")
    assert "MUNICÍPIO" not in m["assunto"].upper()
    assert "CÂMARA" not in m["assunto"].upper()
    assert m["confianca"]["assunto"] <= 0.2
