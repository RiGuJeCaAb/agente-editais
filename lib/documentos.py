# -*- coding: utf-8 -*-
"""
documentos.py — Conversão de documentos para imagem e extração de metadados.

Este módulo é a "porta de entrada" do agente: pega em qualquer documento que
apareça na pasta de entrada e devolve (a) as suas páginas já como imagens e
(b) os metadados (assunto, número do edital, data de publicação) lidos do texto.

Formatos suportados:
  - PDF              — via PyMuPDF (fitz);
  - imagens          — png, jpg, jpeg, tif, tiff, bmp, webp;
  - Word/ODT/RTF     — convertidos primeiro para PDF via LibreOffice headless,
                       porque não existe biblioteca Python que renderize .docx
                       com fidelidade visual suficiente para afixação.

Nota de conceção: a *data de retirada* (saída de exposição) NÃO é extraída daqui.
É uma decisão administrativa que não consta do documento e vive no ficheiro
'retiradas.txt' (ver agente.py). Este módulo só lê o que o documento realmente diz.

Dependências: pymupdf, pillow. Para Word é ainda preciso o 'soffice' (LibreOffice)
acessível no PATH do sistema.
"""
from __future__ import annotations
import os, re, subprocess, shutil
from datetime import datetime
from PIL import Image

# O PyMuPDF é opcional em tempo de importação: se faltar, o módulo ainda carrega
# e só rebenta (com mensagem clara) quando alguém tentar processar um PDF. Isto
# permite, por exemplo, correr testes que só usam imagens sem ter o fitz instalado.
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# Conjuntos de extensões reconhecidas. SUPPORTED é a união e é o que o agente
# consulta para decidir se pega ou ignora um ficheiro que aparece na pasta.
PDF_EXT   = {'.pdf'}
IMG_EXT   = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp'}
WORD_EXT  = {'.docx', '.doc', '.odt', '.rtf'}
SUPPORTED = PDF_EXT | IMG_EXT | WORD_EXT


# ===========================================================================
# Conversão para imagem
# ===========================================================================
def _pdf_to_images(path, zoom=3.0):
    """Rasteriza TODAS as páginas de um PDF para imagens de alta resolução.

    O zoom=3.0 multiplica a resolução base do PDF (72 dpi) para ~216 dpi, o que
    dá nitidez suficiente para uma folha A4 ocupar bem a área que lhe cabe no
    ecrã 4K sem pesar demasiado em memória.

    Args:
        path (str): caminho do ficheiro PDF.
        zoom (float): fator de ampliação da rasterização (3.0 ≈ 216 dpi).

    Returns:
        tuple[list[PIL.Image.Image], str]: (uma imagem por página, texto de
        todas as páginas concatenado — usado depois para extrair metadados).

    Raises:
        RuntimeError: se o PyMuPDF não estiver instalado.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF não instalado (pip install pymupdf)")
    doc = fitz.open(path)
    imgs = []
    for page in doc:
        # get_pixmap com uma matriz de escala é a forma recomendada de rasterizar
        # no PyMuPDF; alpha=False porque as folhas são opacas e não queremos canal
        # de transparência a duplicar o peso da imagem.
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        imgs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    # O texto é recolhido de todas as páginas de uma vez: os metadados (número,
    # data, assunto) podem estar em qualquer página, não só na primeira.
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    return imgs, text


def _word_to_pdf(path, workdir):
    """Converte um documento Word/ODT/RTF para PDF usando o LibreOffice headless.

    Porquê passar por PDF: renderizar .docx diretamente em Python não produz um
    resultado visualmente fiel (tipos de letra, tabelas, cabeçalhos saem trocados).
    O LibreOffice em modo --headless é o motor de renderização de facto para isto
    e garante que o que sai é igual ao que o funcionário vê no Word.

    Args:
        path (str): caminho do documento Word/ODT/RTF.
        workdir (str): pasta de trabalho onde o PDF temporário é escrito.

    Returns:
        str: caminho do PDF gerado.

    Raises:
        RuntimeError: se o LibreOffice não estiver acessível, ou se a conversão
        não produzir o PDF esperado.
    """
    # O executável chama-se 'soffice' na maioria dos sistemas, mas 'libreoffice'
    # nalgumas distribuições — tentamos os dois antes de desistir.
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(
            "LibreOffice não encontrado. Instala com:\n"
            "  Ubuntu/Debian: sudo apt install libreoffice\n"
            "  Windows: instalar LibreOffice e garantir soffice no PATH")
    # timeout defensivo: um documento corrompido pode fazer o soffice pendurar-se;
    # 120s é folgado para um edital e evita que o agente fique bloqueado para sempre.
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", workdir, path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=120)
    # O LibreOffice nomeia o PDF com o mesmo nome-base do original; reconstruímos
    # esse caminho para o devolver a quem chamou.
    base = os.path.splitext(os.path.basename(path))[0]
    out_pdf = os.path.join(workdir, base + ".pdf")
    if not os.path.exists(out_pdf):
        raise RuntimeError(f"Falha a converter {path} para PDF")
    return out_pdf


def _ocr_imagem(img):
    """Extrai texto de uma imagem via OCR (Tesseract), em português.

    É a rede de segurança para documentos que são imagens (printscreens,
    digitalizações) e para PDFs sem texto pesquisável: nesses casos não há texto
    a extrair diretamente, e o OCR "lê" os caracteres a partir dos píxeis.

    Falha graciosamente: se o Tesseract/pytesseract não estiver disponível, ou se
    der erro, devolve string vazia em vez de rebentar — o sistema continua a
    funcionar (apenas sem texto para essa imagem, como antes).

    Args:
        img (PIL.Image.Image): imagem a processar.

    Returns:
        str: texto reconhecido (pode ser vazio se o OCR falhar ou nada reconhecer).
    """
    try:
        import pytesseract
    except ImportError:
        # OCR não instalado — comporta-se como antes (sem texto para imagens).
        return ""
    try:
        # 'por' = modelo português (acentos, ç). Se faltar o pacote, o Tesseract
        # cai para o inglês automaticamente, o que ainda apanha números e datas.
        return pytesseract.image_to_string(img, lang="por")
    except Exception:
        try:
            return pytesseract.image_to_string(img)   # tentativa sem idioma específico
        except Exception:
            return ""


def ler_documento(path, workdir):
    """Lê um documento devolvendo páginas, texto E se o texto veio de OCR.

    É uma variante de to_pages_and_text() que expõe a informação extra de ter
    usado OCR, para quem chama poder ajustar a confiança dos metadados (texto de
    OCR é fiável mas menos que texto nativo de um PDF).

    Args:
        path (str): caminho do documento.
        workdir (str): pasta de trabalho.

    Returns:
        dict: {"pages": list[Image], "text": str, "ocr": bool}
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXT:
        imgs, text = _pdf_to_images(path)
        if len(text.strip()) < 20 and imgs:
            ocr_text = _ocr_imagem(imgs[0])
            return {"pages": imgs, "text": ocr_text, "ocr": True}
        return {"pages": imgs, "text": text, "ocr": False}
    if ext in IMG_EXT:
        img = Image.open(path).convert("RGB")
        return {"pages": [img], "text": _ocr_imagem(img), "ocr": True}
    if ext in WORD_EXT:
        pdf = _word_to_pdf(path, workdir)
        imgs, text = _pdf_to_images(pdf)
        return {"pages": imgs, "text": text, "ocr": False}
    raise ValueError(f"Formato não suportado: {ext}")


def to_pages_and_text(path, workdir):
    """Converte QUALQUER documento suportado nas suas páginas-imagem + texto.

    É o ponto de entrada usado pelo agente. Encaminha cada tipo de ficheiro para
    o tratamento certo e uniformiza a saída, para o resto do sistema não ter de
    saber se a origem era PDF, imagem ou Word.

    Extração de texto em duas camadas:
      1. Direta — para PDFs com texto pesquisável (rápida, exata).
      2. OCR (recurso) — para imagens e PDFs SEM texto (printscreens,
         digitalizações). Só é acionada quando a camada 1 não deu texto, para não
         abrandar o caso normal (a maioria dos documentos são PDFs com texto).

    Args:
        path (str): caminho do documento de entrada.
        workdir (str): pasta de trabalho (necessária para a conversão de Word).

    Returns:
        tuple[list[PIL.Image.Image], str]: (páginas como imagens, texto extraído).

    Raises:
        ValueError: se a extensão não for suportada.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXT:
        imgs, text = _pdf_to_images(path)
        # Se o PDF não trouxe texto útil (é digitalização/imagem), tenta OCR na 1ª
        # página. Limiar baixo (20 chars) para apanhar PDFs quase-vazios de texto.
        if len(text.strip()) < 20 and imgs:
            text = _ocr_imagem(imgs[0])
        return imgs, text
    if ext in IMG_EXT:
        # Uma imagem não tem texto pesquisável: o OCR é a única forma de obter o
        # conteúdo (assunto, número, data) de dentro dela.
        img = Image.open(path).convert("RGB")
        return [img], _ocr_imagem(img)
    if ext in WORD_EXT:
        # Word → PDF → imagens: reaproveita todo o caminho do PDF já testado.
        pdf = _word_to_pdf(path, workdir)
        return _pdf_to_images(pdf)
    raise ValueError(f"Formato não suportado: {ext}")


def to_image_and_text(path, workdir):
    """Atalho de compatibilidade: devolve apenas a 1ª página + texto.

    Mantido para código antigo que só esperava uma página. O fluxo atual usa
    to_pages_and_text (multipágina), mas esta função continua a servir chamadas
    pontuais que só querem espreitar a capa de um documento.

    Args:
        path (str): caminho do documento.
        workdir (str): pasta de trabalho.

    Returns:
        tuple[PIL.Image.Image, str]: (primeira página, texto extraído).
    """
    pages, text = to_pages_and_text(path, workdir)
    return pages[0], text


# ===========================================================================
# Extração de metadados a partir do texto
# ===========================================================================
def _parse_date(s):
    """Tenta interpretar uma data em vários formatos comuns em PT.

    Aceita DD/MM/AAAA, DD-MM-AAAA e AAAA-MM-DD (ISO). Devolve None em vez de
    rebentar quando não reconhece — quem chama decide o que fazer com a ausência.

    Args:
        s (str): texto com a data.

    Returns:
        datetime.date | None: a data, ou None se nenhum formato encaixar.
    """
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def extract_metadata(text, fallback_name="", fonte_ocr=False):
    """Extrai assunto, número e data de publicação do texto de um edital.

    As expressões regulares estão calibradas para o layout dos editais da CMMB
    (rodapé lateral com "Número: AAAA-NNNN" e "Data: DD/MM/AAAA"; título em
    maiúsculas a seguir a "EDITAL"). São heurísticas, não garantias: para
    documentos com layout muito diferente, o assunto pode precisar de correção
    manual no registo.

    Além dos valores, devolve um dicionário de CONFIANÇA por campo (0.0 a 1.0),
    para o painel poder assinalar ao funcionário o que merece verificação.

    Args:
        text (str): texto integral extraído do documento.
        fallback_name (str): nome do ficheiro, usado como assunto de recurso
            quando não há texto (ex.: imagens) ou quando nada é reconhecido.

    Returns:
        dict: {
            "assunto": str,
            "numero": str,               # "" se não encontrado
            "data_publicacao": str|None, # ISO "AAAA-MM-DD" ou None
            "entidade": str,             # "" se não encontrada
            "confianca": {               # 0.0-1.0 por campo
                "assunto": float,
                "numero": float,
                "data_publicacao": float
            }
        }
    """
    meta = {"assunto": "", "numero": "", "data_publicacao": None, "entidade": "",
            "confianca": {"assunto": 0.0, "numero": 0.0, "data_publicacao": 0.0}}

    # Sem texto (tipicamente imagens): o melhor que temos é o nome do ficheiro,
    # e a confiança é mínima porque não lemos nada do conteúdo.
    if not text:
        meta["assunto"] = _humanize(fallback_name)
        meta["confianca"]["assunto"] = 0.2
        return meta

    # Normaliza espaços/tabs para uma única versão "achatada", o que torna as
    # regex abaixo mais robustas a espaçamento irregular vindo do PDF.
    flat = re.sub(r"[ \t]+", " ", text)

    # Número do edital: padrão fixo "AAAA-NNNN" (ex.: 2026-0017). Se casa o padrão
    # exato, a confiança é alta (é um formato muito específico, difícil de falso positivo).
    mnum = re.search(r"N[úu]mero[:\s]+([0-9]{4}-[0-9]{3,4})", flat)
    if mnum:
        meta["numero"] = mnum.group(1)
        meta["confianca"]["numero"] = 0.95

    # Data de publicação: a que aparece rotulada como "Data:" no documento.
    mdata = re.search(r"Data[:\s]+([0-3]?\d[/-][0-1]?\d[/-]\d{4})", flat)
    if mdata:
        d = _parse_date(mdata.group(1))
        if d:
            # Guardamos sempre em ISO (AAAA-MM-DD): formato único internamente,
            # sem ambiguidade dia/mês; a formatação PT é feita só na apresentação.
            meta["data_publicacao"] = d.isoformat()
            meta["confianca"]["data_publicacao"] = 0.9

    # Entidade emissora: útil para contexto/arquivo. Lista fechada das que
    # aparecem nestes editais; re.I para apanhar maiúsculas/minúsculas.
    ment = re.search(r"(ASSEMBLEIA MUNICIPAL|C[ÂA]MARA MUNICIPAL|"
                     r"REP[ÚU]BLICA PORTUGUESA|DI[ÁA]RIO DA REP[ÚU]BLICA)", flat, re.I)
    if ment:
        meta["entidade"] = ment.group(1).upper()

    # Assunto: heurística própria, que devolve também a sua própria confiança.
    assunto, conf_assunto = _guess_subject(text, fallback_name)
    meta["assunto"] = assunto
    meta["confianca"]["assunto"] = conf_assunto

    # Se o texto veio de OCR (imagem/digitalização), o reconhecimento pode ter
    # pequenos erros. Aplica-se um TETO à confiança de cada campo para o painel
    # assinalar que estes valores merecem uma confirmação extra — sem os marcar
    # como duvidosos se a leitura foi boa (o teto 0.75 fica acima do limiar 0.6).
    if fonte_ocr:
        for campo in meta["confianca"]:
            if meta["confianca"][campo] > 0.75:
                meta["confianca"][campo] = 0.75

    return meta


def _guess_subject(text, fallback_name):
    """Adivinha o "assunto" do edital: o título que costuma vir logo após "EDITAL".

    Estratégia: percorrer as linhas, esperar por "EDITAL" (ou "AM / ANO"), e a
    partir daí apanhar a primeira linha "de conteúdo" — ignorando cabeçalhos
    vazios como "AM / 2026" e linhas só de tracejado. Se nada encaixar, recai numa
    primeira linha suficientemente "rica" ou, em último caso, no nome do ficheiro.

    Devolve também um grau de confiança, para o painel poder sinalizar ao
    funcionário quando o assunto merece uma segunda vista de olhos:
      - 0.9  : título encontrado logo após "EDITAL" (o caso normal e fiável);
      - 0.5  : título tirado de uma linha "rica" qualquer (deteção de recurso);
      - 0.2  : sem texto útil, caiu no nome do ficheiro (pouco fiável).

    Args:
        text (str): texto integral do documento.
        fallback_name (str): nome do ficheiro para o caso de recurso.

    Returns:
        tuple[str, float]: (assunto estimado, confiança 0.0-1.0).
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    seen_edital = False
    for l in lines:
        up = l.upper()
        # Fase 1: procurar o marcador que antecede o título.
        if not seen_edital and ("EDITAL" in up or re.match(r"AM\s*/?\s*20\d\d", up)):
            seen_edital = True
            continue
        # Fase 2: já passámos o "EDITAL" — a próxima linha "a sério" é o assunto.
        if seen_edital:
            # Saltar o subtítulo "AM / 2026" e linhas só de traços/espaços.
            if re.fullmatch(r"AM\s*/?\s*20\d\d", up) or re.fullmatch(r"[-—\s]*", l):
                continue
            # Considera-se assunto uma linha com pelo menos 8 letras (evita apanhar
            # números soltos, códigos ou pontuação como se fossem título).
            if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", l)) >= 8:
                return _clean_subject(l), 0.9   # caso normal: confiança alta

    # Recurso: se o marcador "EDITAL" não apareceu, aceita a primeira linha
    # com corpo de texto razoável (>=12 letras). Confiança média — pode falhar.
    for l in lines:
        if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", l)) >= 12:
            return _clean_subject(l), 0.5

    # Último recurso: nome do ficheiro humanizado. Confiança baixa.
    return _humanize(fallback_name), 0.2


def _clean_subject(s):
    """Limpa uma linha de título: remove tracejados de preenchimento e apara.

    Os editais usam longas cadeias de "----" como preenchimento visual; aqui
    tiram-se, colapsam-se espaços e limita-se o comprimento para o assunto caber
    bem no rodapé do ecrã.

    Args:
        s (str): linha bruta.

    Returns:
        str: assunto limpo, no máximo 140 caracteres.
    """
    s = re.sub(r"-{2,}", "", s).strip(" -—:")
    s = re.sub(r"\s+", " ", s)
    return s[:140]


def _humanize(name):
    """Transforma um nome de ficheiro num rótulo legível.

    Ex.: "edital_ef_ext_2.pdf" -> "Edital Ef Ext 2". Serve de assunto quando não
    há texto (imagens) ou quando a deteção falha.

    Args:
        name (str): nome ou caminho do ficheiro.

    Returns:
        str: versão legível (sem extensão, com espaços e capitalização).
    """
    name = os.path.splitext(os.path.basename(name))[0]
    name = re.sub(r"[_\-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip().title()


def slugify(s, maxlen=60):
    """Converte texto em "slug" seguro para nomes de ficheiro (sem acentos/espaços).

    Usado para o nome dos PNG gerados. Remove acentos manualmente (não dependemos
    de unicodedata para manter o comportamento previsível) e troca tudo o que não
    for letra/dígito por "_".

    Args:
        s (str): texto de origem (tipicamente o assunto).
        maxlen (int): comprimento máximo do slug.

    Returns:
        str: slug em minúsculas, sem acentos, separado por "_".
    """
    s = s.lower()
    repl = (("á","a"),("à","a"),("â","a"),("ã","a"),("é","e"),("ê","e"),
            ("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u"),("ç","c"))
    for a, b in repl:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:maxlen]
