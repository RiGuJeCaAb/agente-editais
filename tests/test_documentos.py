"""
test_documentos.py — A leitura dos editais, que é heurística e tem de o assumir.

As expressões regulares estão calibradas para o layout da CMMB. Não são garantias,
e a confiança que cada campo devolve é o que diz ao painel o que assinalar para
confirmação. Estes testes fixam o comportamento nos dois lados: o que se lê bem,
e o que se admite não saber.
"""
from __future__ import annotations

import datetime as dt

import documentos as doc
import pytest

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
