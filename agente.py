#!/usr/bin/env python3
"""
agente.py — Agente de automação dos editais do expositor municipal.

É o "maestro" do sistema: liga o módulo de documentos (ler/converter) ao de
tratamento (compor), guarda tudo no registo de entrada e serve o painel onde
as pessoas validam e publicam.

Fluxo de um edital, do disco ao expositor:
  1. O documento aparece na pasta de entrada (PDF, imagem, Word).
  2. A vigia lê-o, guarda o original no arquivo imutável, propõe assunto,
     número e data com um grau de confiança, e cria um RASCUNHO.
  3. Uma pessoa revê no painel, escolhe o tipo de documento, confirma as datas
     e VALIDA. O sistema propõe o prazo e avisa se ficar aquém do legal.
  4. Ao PUBLICAR, as imagens 4K são compostas e o edital entra no slides.json
     que a televisão consulta. É este o instante que a certidão certifica.
  5. A RETIRADA acontece por data ou à mão; o PNG vai para o arquivo.

Um só caminho, e passa sempre por uma pessoa
--------------------------------------------
Até à versão 0.13 havia um segundo caminho, automático: lia a pasta e punha as
imagens no ecrã sem ninguém ver. Saiu na 0.14, com o `editais.json` e o
`retiradas.txt` que o serviam.

A razão não é arrumação. Desde a Onda 2 a aplicação emite uma certidão que diz
QUEM afixou cada edital, e um caminho que publicava sem ninguém não tinha essa
resposta. Quem tiver dados do modelo antigo não os perde: ver lib/migracao.py,
que os traz na primeira execução.

Modo de utilização:
  python agente.py --painel                     # o serviço
  python agente.py --criar-utilizador NOME      # a primeira conta
  python agente.py --utilizadores               # quem tem acesso

Ficheiros de estado (na raiz do projeto):
  - registo_entrada.json    : os editais e o seu percurso (gravação atómica).
  - registo_auditoria.jsonl : trilho de auditoria, apenas-acrescento.
  - utilizadores.json       : contas do painel (senhas derivadas).
  - originais/              : arquivo imutável dos documentos, por SHA-256.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from datetime import datetime

# Versão do pacote, espelhada no pyproject.toml. Vai no /saude e nos registos,
# para se saber qual a versão que está a correr num posto sem abrir ficheiros.
VERSAO = "0.16.0"

# A pasta do próprio script é a raiz do projeto; 'lib/' é adicionada ao path
# para importar os módulos internos sem depender de instalação.
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "lib"))
from PIL import Image

import armazenamento as arm  # escrita durável (atómica, com gerações)
import diario  # registo técnico (níveis, rotação, ficheiro)
import documentos as doc
import migracao
import originais as orig  # arquivo imutável dos documentos
import painel as painel_mod  # servidor do painel de gestão
import prazos as pr  # tipos de documento e janelas legais
import registo as reg_mod  # registo de entrada (fluxo de estados)
import tratamento as trat
import utilizadores as utl  # contas, senhas derivadas e sessões

# Registadores, um por subsistema. Os nomes são os prefixos que já se liam nas
# linhas do agente — [AGENTE], [PAINEL], [TV] — agora com significado para a
# biblioteca de registo em vez de serem texto colado à frente da mensagem.
_agente = diario.obter("AGENTE")
_config = diario.obter("CONFIG")
_painel = diario.obter("PAINEL")
_arquivo = diario.obter("ARQUIVO")
_fundos = diario.obter("FUNDOS")
_tv = diario.obter("TV")

# Configuração por omissão. Pode ser sobreposta por um 'config.json' na raiz —
# assim o utilizador altera tempos, título e limites sem tocar no código.
CONFIG = {
    "entrada":  os.path.join(BASE, "entrada"),
    # Para onde vai um documento depois de virar rascunho. Fica DENTRO de
    # entrada/ e não ao lado por uma razão prática: quem larga ficheiros na
    # pasta vê ali mesmo o que já foi recebido, sem ter de procurar noutro sítio.
    "tratados": os.path.join(BASE, "entrada", "tratados"),
    "saida":    os.path.join(BASE, "saida"),
    "arquivo":  os.path.join(BASE, "arquivo"),   # ZIP permanente dos retirados
    "previas":  os.path.join(BASE, "previas"),   # pré-visualizações leves p/ o painel
    "originais": os.path.join(BASE, "originais"), # arquivo imutável dos documentos
    # Pastas por estado, para consulta no explorador de ficheiros. São uma VISTA
    # do registo, reconstruída a pedido — nunca a verdade. Ver lib/exportacao.py.
    "exportacao": os.path.join(BASE, "exportacao"),
    "fundos":   os.path.join(BASE, "fundos"),    # cache dos fundos metálicos pré-desenhados
    "trabalho": os.path.join(BASE, "trabalho"),
    # Ficheiros do modelo antigo. Já não são escritos — só lidos uma vez, pela
    # migração, e depois renomeados. Ver lib/migracao.py.
    "estado_antigo":    os.path.join(BASE, "estado.json"),
    "registo_antigo":   os.path.join(BASE, "editais.json"),
    "retiradas_antigo": os.path.join(BASE, "retiradas.txt"),
    "registo_entrada": os.path.join(BASE, "registo_entrada.json"),  # fluxo de estados
    "utilizadores": os.path.join(BASE, "utilizadores.json"),        # contas do painel
    "diario":   os.path.join(BASE, "diario", "agente.log"),         # registo técnico
    "nivel_diario": "INFO",
    "logo_sym": os.path.join(BASE, "assets", "sym_ok.png"),
    "logo_txt": os.path.join(BASE, "assets", "txt_ok.png"),
    "intervalo_watch": 30,
    "segundos_por_ecra": 30,
    "manter_zips": 3,
    "titulo_tv": "Editais \u00b7 C\u00e2mara Municipal de Moimenta da Beira",
    # --- Painel de gestão ---
    # Fluxo com validação humana: quando True, os documentos entram como RASCUNHO
    # e só vão para o ecrã depois de validados/publicados no painel. Quando False,
    # mantém o comportamento antigo (publicação automática) — útil para migração.
    "usar_registo_entrada": True,
    "painel_host": "127.0.0.1",     # "0.0.0.0" para expor à rede (dentro da VLAN)
    "painel_porta": 8770,
    # --- Identificação para a certidão de afixação ---
    # Aparecem no cabeçalho e no corpo do documento que a aplicação emite, por
    # isso convém estarem certos antes de a primeira certidão sair para um processo.
    "municipio": "Município de Moimenta da Beira",
    "servico": "",
    "local_do_expositor": "Expositor eletrónico do Município",
    # Tipos de documento com prazos próprios do município, que se somam ou
    # sobrepõem aos de origem. Ver lib/prazos.py.
    "tipos_de_documento": {},
}

def load_config():
    """Carrega a configuração, fundindo os defaults com um config.json opcional.

    Também garante que as pastas de trabalho existem, para o resto do código
    poder assumir que estão lá.

    Ao contrário de uma leitura ingénua, esta função NÃO falha em silêncio: se o
    config.json existir mas tiver erro de sintaxe (aspas curvas de um editor de
    texto, vírgula a mais, etc.), avisa em alto e bom som e explica a causa
    provável — em vez de arrancar sorrateiramente com a config por defeito (senha
    vazia), que deixava o utilizador sem perceber porque o login falhava.

    Returns:
        dict: configuração efetiva a usar nesta execução.
    """
    cfg = dict(CONFIG)
    # O registo técnico arranca ANTES de se ler o config.json, com os valores por
    # omissão. Parece redundante, mas não é: os avisos sobre o próprio
    # config.json — aspas curvas, erro de sintaxe — são dos mais importantes que
    # o agente emite, e sem isto seriam os únicos a não ficar em lado nenhum.
    diario.configurar(cfg["diario"], nivel=cfg["nivel_diario"])
    p = os.path.join(BASE, "config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                conteudo = f.read()
            # Deteta o erro mais traiçoeiro: aspas "curvas" (tipográficas) que o
            # Notepad/Word inserem e que invalidam o JSON.
            if "\u201c" in conteudo or "\u201d" in conteudo:
                _config.warning(
                    "O config.json tem aspas curvas (\u201c \u201d) e foi IGNORADO. "
                    "Foi provavelmente guardado no Word ou no Notepad com "
                    "formatação; use aspas retas (\") num editor de texto simples.")
            else:
                cfg.update(json.loads(conteudo))
        except json.JSONDecodeError as e:
            # JSON malformado: avisa e continua com defaults, mas deixa claro.
            _config.error(
                f"Erro de sintaxe no config.json: {e}. O ficheiro foi IGNORADO e o "
                f"agente vai usar os valores por omissão. Corrija-o e reinicie.")
    for k in ("entrada", "tratados", "saida", "arquivo", "previas", "fundos",
              "originais", "trabalho"):
        os.makedirs(cfg[k], exist_ok=True)

    # A senha partilhada foi retirada na Onda 2. Se ainda estiver no config,
    # avisa-se em vez de a ignorar em silêncio — quem a lá tem julga que está a
    # proteger o painel com ela.
    if cfg.get("painel_senha"):
        _config.warning(
            "A chave 'painel_senha' do config.json já não é usada e pode ser "
            "retirada. O painel passou a ter contas individuais, para a certidão "
            "de afixação poder dizer quem afixou cada edital. Crie contas com: "
            "python agente.py --criar-utilizador NOME --administrador")

    # Carrega a tabela de tipos de documento (os de origem, mais os do município).
    pr.carregar_tipos(cfg)
    _agente.debug(f"agente de editais {VERSAO} | registo em {cfg['diario']}")
    return cfg

def file_hash(path):
    """Calcula o SHA-1 do conteúdo de um ficheiro (lido em blocos de 64 KB).

    Usa-se como "impressão digital" para saber se um ficheiro já foi processado,
    mesmo que o renomeiem — o que importa é o conteúdo, não o nome.

    Args:
        path (str): caminho do ficheiro.

    Returns:
        str: hash SHA-1 em hexadecimal.
    """
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def nome_saida(indice, slug, parte=None, total=None):
    """Constrói o nome do PNG de saída, com grupo data/hora à cabeça.

    Formato: AAAAMMDDHHMM_NN_slug[_pXdeY]_16x9_3d_CLD.png
    O prefixo temporal garante ordenação cronológica em qualquer gestor de
    ficheiros; o sufixo _pXdeY só aparece quando o edital ocupa vários ecrãs.

    Args:
        indice (int): índice sequencial do ecrã.
        slug (str): versão do assunto segura para nome de ficheiro.
        parte (int|None): número do ecrã dentro do edital (1-based).
        total (int|None): total de ecrãs do edital.

    Returns:
        str: nome do ficheiro PNG.
    """
    ts = datetime.now().strftime("%Y%m%d%H%M")
    sufixo = f"_p{parte}de{total}" if (parte and total and total > 1) else ""
    return f"{ts}_{indice:02d}_{slug}{sufixo}_16x9_3d_CLD.png"

def _rodar_zips(cfg):
    """Mantém só as N cópias ZIP mais recentes na saída, apagando as restantes.

    Evita a acumulação indefinida de ficheiros ZIP na pasta de saída. Ordena por
    data de modificação (mais recente primeiro) e remove tudo o que passe de N.

    Args:
        cfg (dict): configuração (usa 'manter_zips', por omissão 3).
    """
    manter = int(cfg.get("manter_zips", 3))
    zips = sorted(glob.glob(os.path.join(cfg["saida"], "*_editais_expositor_CLD.zip")),
                  key=os.path.getmtime, reverse=True)
    for velho in zips[manter:]:
        try:
            os.remove(velho)
            _agente.info(f"LIMP zip antigo removido: {os.path.basename(velho)}")
        except OSError:
            pass

# ===========================================================================
# FLUXO COM REGISTO DE ENTRADA (validação humana antes de publicar)
# Este é o modelo novo: os documentos entram como RASCUNHO e só a página da TV
# reflete o que estiver em estado PUBLICADO. A composição dos PNG é feita no
# momento da publicação (não na leitura), para não gastar trabalho com editais
# que possam ser corrigidos ou rejeitados.
# ===========================================================================
def varrer_para_registo(cfg, reg, logo_im):
    """Lê os documentos novos e cria RASCUNHOS no registo de entrada.

    Difere de varrer(): não publica nada. Cada documento novo (por hash) vira um
    rascunho com metadados propostos + confiança, à espera de validação humana.

    Args:
        cfg (dict): configuração.
        reg (RegistoEntrada): registo de entrada (fluxo de estados).
        logo_im: não usado aqui (a composição só acontece na publicação), mantido
            por simetria de assinatura.

    Returns:
        int: número de rascunhos criados.
    """
    novos = 0
    for nome in sorted(os.listdir(cfg["entrada"])):
        path = os.path.join(cfg["entrada"], nome)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(nome)[1].lower() not in doc.SUPPORTED:
            continue
        h = file_hash(path)
        if reg.hash_existe(h):        # já registado antes → ignora
            continue
        try:
            doc_lido = doc.ler_documento(path, cfg["trabalho"])
            pages = doc_lido["pages"]
            meta = doc.extract_metadata(doc_lido["text"], fallback_name=nome,
                                        fonte_ocr=doc_lido["ocr"])
            # O original vai para o arquivo imutável ANTES de o registo existir.
            # A ordem importa: se falhasse ao contrário, ficaria um edital no
            # registo a apontar para um documento que nunca foi guardado, e é
            # exatamente esse o estado que este arquivo existe para impedir.
            sha256, _caminho = orig.arquivar(cfg["originais"], path)
            meta = dict(meta, sha256=sha256)
            r = reg.criar_rascunho(ficheiro_origem=nome, hash_ficheiro=h,
                                   num_paginas=len(pages), meta=meta)
            # Gera pré-visualizações LEVES (a página crua, sem o tratamento verde/4K)
            # para o painel poder mostrar o documento já no rascunho — é quando o
            # funcionário mais precisa de o ver, para confirmar assunto/número/data.
            previas = _gerar_previas(cfg, r["id"], pages)
            if previas:
                reg.definir_previas(r["id"], previas)
            # Só agora, com o rascunho criado e o original arquivado, é que o
            # ficheiro sai da pasta de entrada.
            _tirar_da_entrada(cfg, path, nome)
            ocr_nota = " [via OCR]" if doc_lido["ocr"] else ""
            duv = ", ".join(r["campos_duvidosos"]) or "nenhum"
            print(f"[RASCUNHO #{r['id']}] {nome}{ocr_nota}: {len(pages)} pág | "
                  f"assunto: {meta['assunto'] or '(n/d)'} | a confirmar: {duv}")
            novos += 1
        except Exception as ex:
            _agente.error(f"{nome}: {ex}")
    return novos


def _procurar_na_entrada(cfg, nome):
    """Procura um documento pelo nome na pasta de entrada e na de tratados.

    Só serve de recurso: o arquivo imutável é a primeira fonte, e desde a Onda 2
    todos os registos novos lá têm o seu original. Isto existe para os registos
    anteriores, que só têm o nome do ficheiro.

    Args:
        cfg (dict): configuração.
        nome (str): nome do ficheiro de origem, como o registo o guardou.

    Returns:
        str|None: caminho do ficheiro, ou None se não estiver em nenhuma das duas.
    """
    if not nome:
        return None
    for pasta in (cfg["entrada"], cfg["tratados"]):
        caminho = os.path.join(pasta, nome)
        if os.path.isfile(caminho):
            return caminho
    return None


def _tirar_da_entrada(cfg, caminho, nome):
    """Move um documento já recebido de entrada/ para entrada/tratados/.

    Chamada DEPOIS de o rascunho existir e de o original estar no arquivo
    imutável. A ordem é o que torna isto seguro: quando o ficheiro sai da pasta
    de entrada, já há uma cópia idêntica ao byte em originais/, endereçada pelo
    seu SHA-256, e é dela que a composição lê. O que fica em entrada/ depois da
    ingestão não tem função nenhuma.

    Existe porque a pasta nunca se esvaziava. Ao fim de umas semanas ninguém
    conseguia responder a olho à pergunta que interessa — «o que é que chegou de
    novo?» — e a resposta a essa pergunta é metade do trabalho do posto.

    Mover e não apagar, como em todo o resto do projeto: se alguma coisa correu
    mal na leitura, o ficheiro de origem continua ali ao lado.

    Falhar aqui é inofensivo e por isso não interrompe nada: o registo já existe,
    e a varredura seguinte reconhece o ficheiro pelo hash e não o volta a ingerir.
    Fica o aviso, para não ser um silêncio.

    Args:
        cfg (dict): configuração.
        caminho (str): caminho atual do ficheiro, em entrada/.
        nome (str): nome do ficheiro.

    Returns:
        str|None: caminho de destino, ou None se não foi possível mover.
    """
    destino = os.path.join(cfg["tratados"], nome)
    # Nome livre: dois editais podem chegar com o mesmo nome em meses
    # diferentes, e o segundo não pode apagar o primeiro.
    if os.path.exists(destino):
        raiz, ext = os.path.splitext(nome)
        destino = os.path.join(cfg["tratados"],
                               f"{raiz}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}")
    try:
        os.replace(caminho, destino)
        return destino
    except OSError as ex:
        _agente.warning(f"{nome} ficou na pasta de entrada: {ex}")
        return None


def _gerar_previas(cfg, rid, pages, larg=900):
    """Gera pré-visualizações leves das páginas de um documento, para o painel.

    Ao contrário dos PNG finais (verde metálico, 4K, com logótipo — pesados e só
    compostos na publicação), estas são a página CRUA redimensionada para uma
    largura moderada. São rápidas de gerar e leves de servir, e existem logo no
    rascunho para o funcionário ver o documento enquanto valida os campos.

    Args:
        cfg (dict): configuração.
        rid (int): id do registo.
        pages (list[PIL.Image.Image]): páginas rasterizadas do documento.
        larg (int): largura-alvo da pré-visualização em píxeis (altura proporcional).

    Returns:
        list[str]: nomes dos ficheiros de pré-visualização gerados.
    """
    nomes = []
    for i, pg in enumerate(pages, start=1):
        w, h = pg.size
        nh = max(1, int(round(h * (larg / w))))
        prev = pg.convert("RGB").resize((larg, nh), Image.LANCZOS)
        nome = f"previa_{rid:04d}_{i:02d}.jpg"
        # JPEG com qualidade média: a pré-visualização não precisa de ser perfeita,
        # só legível; JPEG reduz muito o tamanho face a PNG para fotos de páginas.
        prev.save(os.path.join(cfg["previas"], nome), "JPEG", quality=82)
        nomes.append(nome)
    return nomes


def publicar_registos(cfg, reg, logo_im):
    """Compõe os PNG dos editais PUBLICADOS e (re)gera a página da TV + ZIP.

    Percorre os registos em estado PUBLICADO, gera os ecrãs que ainda não têm PNG
    (agrupando páginas em blocos de até 3, como antes) e reconstrói o index.html
    só com esses editais. É chamada após qualquer publicação/retirada.

    Antes de compor, trata dois movimentos de arquivo:
      - RETIRADOS: o PNG solto sai da pasta saida/ (poupa disco) mas fica guardado
        no ZIP de arquivo permanente, de onde pode ser recuperado se for reposto.
      - REPOSTOS (retirado→publicado sem PNG na pasta): o PNG é recuperado do ZIP
        de arquivo, sem recompor tudo do zero.

    Args:
        cfg (dict): configuração.
        reg (RegistoEntrada): registo de entrada.
        logo_im: logótipo a aplicar (ou None).

    Returns:
        int: número de ecrãs ativos na TV.
    """
    # Aplica primeiro as retiradas automáticas por data (publicado → retirado).
    retirados = reg.aplicar_retiradas_automaticas()
    if retirados:
        _agente.info(f"AUTO retirados por data: {retirados}")

    # Arruma a pasta: PNG de retirados vão para o arquivo e saem de saida/.
    arquivar_retirados(cfg, reg)

    publicados = reg.por_estado(reg_mod.PUBLICADO)
    slides = []
    for r in publicados:
        # Caso 1: nunca teve PNG — primeira publicação, compõe de novo.
        # Grava-se por definir_pngs() e não por mutação do dicionário: desde que
        # por_estado() devolve cópias, escrever no resultado não chega ao registo.
        if not r.get("ficheiros_png"):
            r["ficheiros_png"] = _compor_edital(cfg, r, logo_im, reg)
            reg.definir_pngs(r["id"], r["ficheiros_png"])
        # Caso 2: tem nome de PNG registado mas o ficheiro não está na pasta
        # (foi arquivado quando esteve retirado) — recupera-o do ZIP de arquivo.
        else:
            faltam = [p for p in r["ficheiros_png"]
                      if not os.path.exists(os.path.join(cfg["saida"], p))]
            if faltam:
                recuperados = recuperar_do_arquivo(cfg, faltam)
                # Se algum não estava no arquivo (arquivo perdido?), recompõe tudo.
                if len(recuperados) != len(faltam):
                    _arquivo.info(f"recomposição de recurso para #{r['id']} "
                          f"(nem tudo estava arquivado)")
                    r["ficheiros_png"] = _compor_edital(cfg, r, logo_im, reg)
                    reg.definir_pngs(r["id"], r["ficheiros_png"])
        # Cada ecrã (PNG) do edital é um slide, com assunto + data de publicação.
        for png in r["ficheiros_png"]:
            slides.append({"src": png, "assunto": r["assunto"],
                           "pub": r["data_publicacao"] or ""})
        # O edital entrou mesmo na rotação do expositor. É o registo de
        # disponibilidade que acompanha a certidão em anexo — a confirmação
        # material, distinta do instante oficial de afixação, que é o da
        # publicação no painel. Só se marca se houve PNG: um edital publicado
        # cujo ficheiro de origem desapareceu não chega a ficar visível.
        if r["ficheiros_png"]:
            reg.marcar_disponivel(r["id"])

    _escrever_pagina_tv(cfg, slides)
    _escrever_zip_publicados(cfg, reg, publicados)
    return len(slides)


def arquivar_retirados(cfg, reg):
    """Move os PNG de editais RETIRADOS para o ZIP de arquivo e limpa a pasta.

    Poupa espaço em disco: um edital fora do ecrã não precisa de ocupar a pasta
    saida/ como ficheiro solto. Antes de apagar, garante SEMPRE que cada PNG está
    guardado no ZIP de arquivo permanente (arquivo/arquivo_editais.zip), para
    poder ser reposto mais tarde sem recompor.

    Args:
        cfg (dict): configuração.
        reg (RegistoEntrada): registo de entrada.
    """
    import zipfile
    os.makedirs(cfg["arquivo"], exist_ok=True)
    zpath = os.path.join(cfg["arquivo"], "arquivo_editais.zip")

    # Nomes já presentes no arquivo, para não duplicar escritas.
    ja_arquivados = set()
    if os.path.exists(zpath):
        with zipfile.ZipFile(zpath, "r") as z:
            ja_arquivados = set(z.namelist())

    movidos = 0
    for r in reg.por_estado(reg_mod.RETIRADO):
        for png in r.get("ficheiros_png", []):
            caminho = os.path.join(cfg["saida"], png)
            if not os.path.exists(caminho):
                continue  # já foi arquivado numa passagem anterior
            # 1) garantir que está no arquivo (append; abre o ZIP em modo 'a').
            if png not in ja_arquivados:
                with zipfile.ZipFile(zpath, "a", zipfile.ZIP_DEFLATED) as z:
                    z.write(caminho, png)
                ja_arquivados.add(png)
            # 2) só depois de garantido no ZIP é que se apaga o ficheiro solto.
            try:
                os.remove(caminho)
                movidos += 1
            except OSError:
                pass
    if movidos:
        _arquivo.info(f"{movidos} PNG de retirados movidos para o arquivo "
              f"(libertados de saida/)")


def recuperar_do_arquivo(cfg, nomes):
    """Extrai PNG específicos do ZIP de arquivo de volta para a pasta saida/.

    Usado quando um edital retirado é reposto no ecrã: em vez de recompor a
    imagem 4K do zero, recupera-se o PNG exato que foi arquivado.

    Args:
        cfg (dict): configuração.
        nomes (list[str]): nomes dos PNG a recuperar.

    Returns:
        list[str]: nomes efetivamente recuperados (os que existiam no arquivo).
    """
    import zipfile
    zpath = os.path.join(cfg["arquivo"], "arquivo_editais.zip")
    if not os.path.exists(zpath):
        return []
    recuperados = []
    with zipfile.ZipFile(zpath, "r") as z:
        no_zip = set(z.namelist())
        for nome in nomes:
            if nome in no_zip:
                # extrai diretamente para saida/, preservando o nome.
                z.extract(nome, cfg["saida"])
                recuperados.append(nome)
    if recuperados:
        _arquivo.info(f"{len(recuperados)} PNG recuperados do arquivo para o ecrã")
    return recuperados


def _compor_edital(cfg, r, logo_im, reg=None):
    """Rasteriza o documento de um registo e compõe os seus ecrãs (PNG).

    Relê o ficheiro de origem a partir da pasta de entrada, parte as páginas em
    blocos de até 3 e gera um PNG por bloco, com o tratamento visual habitual.

    Args:
        cfg (dict): configuração.
        r (dict): registo de entrada (já publicado).
        logo_im: logótipo a aplicar (ou None).
        reg (RegistoEntrada|None): registo, para gravar o sha256 quando um
            original antigo é arquivado nesta passagem.

    Returns:
        list[str]: nomes dos PNG gerados (na pasta de saída).
    """
    # O arquivo imutável é a PRIMEIRA fonte, e a pasta de entrada só o recurso.
    # Era ao contrário, e por isso limpar a pasta de entrada tornava impossível
    # recompor um edital já publicado.
    extensao = os.path.splitext(r["ficheiro_origem"])[1]
    origem = orig.procurar(cfg["originais"], r.get("sha256", ""), extensao)
    if not origem:
        # Recurso para registos anteriores ao arquivo: o ficheiro pode estar
        # ainda na pasta de entrada, ou já em entrada/tratados/ se entretanto
        # passou por uma varredura desta versão.
        origem = _procurar_na_entrada(cfg, r["ficheiro_origem"])
        if origem:
            # Registo anterior ao arquivo: aproveita-se esta passagem para o
            # arquivar, de modo que a próxima já não dependa da pasta de entrada.
            try:
                sha256, _c = orig.arquivar(cfg["originais"], origem)
                if not r.get("sha256") and reg is not None:
                    _arquivo.info(f"original do registo #{r['id']} arquivado agora")
                    reg.definir(r["id"], sha256=sha256)
                    r["sha256"] = sha256
            except OSError as ex:
                _agente.warning(f"não foi possível arquivar o original de #{r['id']}: {ex}")
    if not origem or not os.path.exists(origem):
        _agente.warning(f"original em falta para o registo #{r['id']}: "
              f"{r['ficheiro_origem']} — não está no arquivo nem na pasta de entrada.")
        return []
    try:
        pages, _ = doc.to_pages_and_text(origem, cfg["trabalho"])
    except Exception as ex:
        _agente.warning(f"falha a compor o registo #{r['id']} ({r['ficheiro_origem']}): {ex}")
        return []
    slug = doc.slugify(r["assunto"] or doc._humanize(r["ficheiro_origem"]))
    # Agrupamento por orientação, e não divisão cega em três: um documento
    # horizontal leva um ecrã só para si, onde ocupa ~60% da área em vez dos
    # 10% que lhe sobravam encaixado na caixa vertical.
    blocos = trat.agrupar_ecras(pages)
    total = len(blocos)
    nomes = []
    for bi, bloco in enumerate(blocos, start=1):
        seed = 3 + (r["id"] * 7 + bi)   # padrão de fundo estável por edital/ecrã
        comp = trat.compose_sheets(bloco, seed=seed, logo_im=logo_im,
                                   cache_fundos=cfg["fundos"])
        nome = nome_saida(r["id"], slug, parte=bi, total=total)
        comp.save(os.path.join(cfg["saida"], nome), "PNG")
        nomes.append(nome)
    return nomes


# ===========================================================================
# Template da página da TV (expositor).
#
# Arquitetura:
#   - Os slides NÃO estão embebidos no HTML. A página busca 'slides.json' em
#     ciclo e atualiza o carrossel AO VIVO — editais novos entram sem recarregar
#     a página e sem cortar a rotação. Só __SPE__ e __TITULO__ são injetados.
#   - Carrossel infinito: roda para sempre. Não há location.reload().
#   - Fundo com "veias" douradas num <canvas>. É DESIGN, não anti-screensaver.
#   - Anti-screensaver do webOS: tentativa via API Luna (WebOSServiceBridge),
#     que pode não estar acessível a partir do browser. Ver o comentário no
#     código e a secção 12 do README.
# ===========================================================================
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-PT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<style>
  :root{ --verde:#0D4D33; --verde2:#08301c; --verde3:#052316; --ouro:#C8A84B; --ouro2:#e6cf8d; }
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{height:100%;background:#000;overflow:hidden;cursor:none;
    font-family:"Segoe UI",system-ui,sans-serif;color:#fff}
  /* Canvas do fundo ondulante: ocupa tudo, fica ATRÁS dos editais (z-index baixo). */
  #fundo{position:fixed;inset:0;z-index:0;display:block}
  #palco{position:fixed;inset:0;z-index:1;display:flex;align-items:center;justify-content:center}
  .slide{position:absolute;inset:0;opacity:0;transition:opacity 1s ease;
    display:flex;align-items:center;justify-content:center}
  .slide.ativo{opacity:1}
  .slide img{max-width:100%;max-height:100%;object-fit:contain;display:block;
    filter:drop-shadow(0 10px 40px rgba(0,0,0,.45))}
  #info{position:fixed;left:0;right:0;bottom:0;z-index:2;padding:2.2vh 3vw;
    background:linear-gradient(transparent,rgba(0,0,0,.55));
    display:flex;justify-content:space-between;align-items:flex-end;font-size:1.5vw}
  #assunto{max-width:74%;text-shadow:0 2px 6px #000}
  #pub{color:var(--ouro);text-align:right;text-shadow:0 2px 6px #000;white-space:nowrap}
  #vazio{position:fixed;inset:0;z-index:2;display:none;align-items:center;justify-content:center;
    font-size:2vw;color:var(--ouro);opacity:.9;text-align:center}
  #arranque{position:fixed;inset:0;z-index:50;
    background:radial-gradient(circle at 30% 25%,var(--verde),var(--verde2));
    display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;cursor:pointer}
  #arranque h1{font-family:Georgia,serif;font-weight:600;font-size:3vw;color:#fff;text-align:center;max-width:80%}
  #arranque p{color:#cfe3d6;font-size:1.3vw}
  #arranque .btn{border:2px solid var(--ouro);color:var(--ouro);padding:14px 30px;border-radius:99px;font-size:1.4vw}
  #estado{position:fixed;top:1vh;right:1vw;z-index:3;font-size:.8vw;color:rgba(255,255,255,.25)}
</style>
</head>
<body>
  <canvas id="fundo"></canvas>
  <div id="palco"></div>
  <div id="vazio">Sem editais a apresentar.</div>
  <div id="info"><div id="assunto"></div><div id="pub"></div></div>
  <div id="estado"></div>
  <div id="arranque">
    <h1>__TITULO__</h1>
    <p>Toque no ecr&atilde; para iniciar a apresenta&ccedil;&atilde;o em ecr&atilde; inteiro</p>
    <div class="btn">&#9654; Iniciar</div>
  </div>
<script>
  "use strict";
  // __SPE__ = segundos por ecrã por defeito (usado até o slides.json dizer outro).
  var SPE_DEFAULT = __SPE__ * 1000;

  // ---------------------------------------------------------------------------
  // 1) FUNDO ONDULANTE — "veias" douradas que ondulam, desenhadas por baixo dos
  //    editais. É DESIGN, não anti-screensaver. Usa requestAnimationFrame.
  // ---------------------------------------------------------------------------
  (function fundoOndulante(){
    var cv = document.getElementById('fundo');
    var ctx = cv.getContext('2d');
    var W, H;
    function dim(){ W = cv.width = window.innerWidth; H = cv.height = window.innerHeight; }
    window.addEventListener('resize', dim); dim();

    // Cada veia é uma linha diagonal que ondula com o tempo. Guardamos parâmetros
    // fixos por veia (posição, ângulo, frequência, fase) para o movimento ser
    // orgânico mas estável — não aleatório a cada frame.
    var veias = [];
    var N = 26;
    for (var i=0;i<N;i++){
      veias.push({
        y0: Math.random()*1.2 - 0.1,      // origem vertical (fração do ecrã)
        ang: -0.6 + Math.random()*0.35,   // inclinação diagonal ascendente
        amp: 8 + Math.random()*22,        // amplitude da ondulação (px)
        freq: 0.6 + Math.random()*1.4,    // nº de ondas ao longo da largura
        fase: Math.random()*Math.PI*2,    // desfasamento inicial
        vel: 0.12 + Math.random()*0.25,   // velocidade da ondulação
        larg: 0.6 + Math.random()*1.6,    // espessura do traço
        alfa: 0.05 + Math.random()*0.13   // opacidade (subtil)
      });
    }

    function fundoGradiente(){
      var g = ctx.createRadialGradient(W*0.3, H*0.25, 0, W*0.5, H*0.5, Math.max(W,H));
      g.addColorStop(0, '#0D4D33');
      g.addColorStop(0.6, '#08301c');
      g.addColorStop(1, '#052316');
      ctx.fillStyle = g; ctx.fillRect(0,0,W,H);
    }

    function desenha(t){
      fundoGradiente();
      ctx.lineCap = 'round';
      for (var i=0;i<veias.length;i++){
        var v = veias[i];
        ctx.beginPath();
        // Traça a veia amostrando pontos ao longo da largura e aplicando a onda.
        for (var x=-40; x<=W+40; x+=16){
          var fx = x / W;
          var base = v.y0*H + Math.tan(v.ang) * x;              // linha diagonal
          var onda = Math.sin(fx*Math.PI*2*v.freq + v.fase + t*v.vel) * v.amp; // ondulação
          var y = base + onda;
          if (x===-40) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        // Gradiente dourado ao longo do traço, para "brilhar" mais no meio.
        var grad = ctx.createLinearGradient(0,0,W,0);
        grad.addColorStop(0, 'rgba(200,168,75,0)');
        grad.addColorStop(0.5, 'rgba(230,207,141,'+v.alfa+')');
        grad.addColorStop(1, 'rgba(200,168,75,0)');
        ctx.strokeStyle = grad; ctx.lineWidth = v.larg;
        ctx.stroke();
      }
    }

    var t0 = null;
    function loop(ts){
      if (t0===null) t0 = ts;
      var t = (ts - t0) / 1000;   // segundos desde o início
      desenha(t);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
  })();

  // ---------------------------------------------------------------------------
  // 2) CARROSSEL INFINITO com atualização AO VIVO a partir de slides.json.
  //    - roda para sempre;
  //    - de X em X segundos vai buscar o slides.json e, se a versão mudou,
  //      reconcilia os nós (adiciona os novos, remove os que saíram) SEM
  //      reiniciar a rotação nem piscar.
  // ---------------------------------------------------------------------------
  var palco = document.getElementById('palco');
  var elA = document.getElementById('assunto');
  var elP = document.getElementById('pub');
  var elV = document.getElementById('vazio');
  var elE = document.getElementById('estado');

  // Ao fim de quantos minutos sem o agente escrever o slides.json se considera
  // que o que está no ecrã pode já não valer. Três ciclos do vigia (30 s) com
  // folga larga: abaixo disto seria alarme falso a cada hesitação da rede.
  var MINUTOS_ATE_SUSPEITAR = 30;

  var slides = [];      // lista atual [{src,assunto,pub}]
  var nodes = [];       // <div.slide> correspondentes, na mesma ordem
  var idx = 0;          // índice do slide visível
  var spe = SPE_DEFAULT;
  var versao = null;    // última versão vista do slides.json
  var timer = null;

  function fmt(d){ if(!d) return ''; var p=(''+d).split('-'); return p.length===3? p[2]+'/'+p[1]+'/'+p[0] : d; }

  // Cria o nó DOM de um slide (div + img). A imagem só carrega uma vez.
  function criaNode(s){
    var d = document.createElement('div'); d.className = 'slide';
    var img = document.createElement('img'); img.src = s.src; img.alt = s.assunto||'';
    d.appendChild(img); palco.appendChild(d);
    return d;
  }

  // Mostra o slide i (por opacidade) e atualiza o rodapé.
  function mostra(i){
    if(!nodes.length) return;
    for (var k=0;k<nodes.length;k++) nodes[k].classList.remove('ativo');
    // Protege contra i fora de gama se a lista encolheu entretanto.
    idx = ((i % nodes.length) + nodes.length) % nodes.length;
    nodes[idx].classList.add('ativo');
    var s = slides[idx];
    elA.textContent = s && s.assunto ? s.assunto : '';
    elP.textContent = s && s.pub ? ('Publicado em ' + fmt(s.pub)) : '';
  }

  function avanca(){ if(nodes.length) mostra(idx + 1); }

  // (Re)arranca o temporizador da rotação com o intervalo atual.
  function arrancaRotacao(){
    if (timer) clearInterval(timer);
    timer = setInterval(avanca, spe);
  }

  // Reconciliação: aplica uma nova lista de slides SEM destruir o que já está,
  // para a rotação não piscar. Só mexe no que mudou.
  function aplica(novos){
    // Identidade de um slide = o seu 'src' (nome único do PNG).
    var srcAntigos = nodes.map(function(_,k){ return slides[k].src; });
    var srcNovos = novos.map(function(s){ return s.src; });

    // Remover nós que já não existem na lista nova.
    for (var k = nodes.length - 1; k >= 0; k--){
      if (srcNovos.indexOf(slides[k].src) === -1){
        palco.removeChild(nodes[k]);
        nodes.splice(k,1); slides.splice(k,1);
      }
    }
    // Adicionar os novos (no fim — entram na fila e aparecem na sua vez).
    for (var j = 0; j < novos.length; j++){
      if (srcAntigos.indexOf(novos[j].src) === -1){
        slides.push(novos[j]);
        nodes.push(criaNode(novos[j]));
      }
    }

    // Estado vazio vs com conteúdo.
    if (!nodes.length){
      elV.style.display = 'flex'; elA.textContent=''; elP.textContent='';
      if (timer){ clearInterval(timer); timer=null; }
    } else {
      elV.style.display = 'none';
      if (!timer){ idx = 0; mostra(0); arrancaRotacao(); }
      else if (idx >= nodes.length) { mostra(0); }  // reancorar se a lista encolheu
    }
  }

  // Assinala, com discrição, que o conteúdo no ecrã já tem muito tempo. Sem isto,
  // um agente que morra deixa a TV a mostrar editais de há uma semana com um ar
  // perfeitamente normal, e ninguém dá por nada — que é o pior desfecho possível
  // num expositor onde a lei conta os dias de afixação.
  function avisaSeVelho(gerado){
    if (!gerado){ return; }
    var minutos = (Date.now() - new Date(gerado).getTime()) / 60000;
    elE.textContent = minutos > MINUTOS_ATE_SUSPEITAR
      ? 'conteúdo de ' + new Date(gerado).toLocaleString('pt-PT') + ' — verificar o agente'
      : '';
  }

  // Vai buscar o slides.json. Se a versão mudou, aplica. Tolerante a falhas de rede.
  function sincroniza(){
    // cache:'no-store' para a TV não servir uma cópia velha do ficheiro.
    fetch('slides.json?_=' + Date.now(), {cache:'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(data){
        if(!data) return;
        if (typeof data.spe === 'number' && data.spe*1000 !== spe){
          spe = data.spe * 1000;
          if (timer) arrancaRotacao();  // aplica novo intervalo sem parar
        }
        if (data.v !== versao){
          versao = data.v;
          aplica(Array.isArray(data.slides) ? data.slides : []);
        }
        avisaSeVelho(data.gerado_em);
      })
      .catch(function(){
        // Sem rede: mantém o que está no ecrã (não interrompe nada).
        elE.textContent = 'sem ligação — a manter último conteúdo';
      });
  }

  // ---------------------------------------------------------------------------
  // 3) ANTI-SCREENSAVER do webOS via API Luna (não-documentada).
  //    Regista-se no gestor de energia da TV e, quando este avisa que vai ligar
  //    o screensaver, responde 'ack:false' = "não ligues agora". É isto (e não a
  //    animação) que pode manter o ecrã aceso.
  //    IMPORTANTE: WebOSServiceBridge existe em apps webOS empacotadas; a partir
  //    do BROWSER pode não estar disponível. Se não estiver, falha em silêncio e
  //    o ecrã comporta-se como antes — é preciso testar na TV real. Caso não
  //    funcione, a recomendação mantém-se: mini-PC por HDMI.
  // ---------------------------------------------------------------------------
  function anti_screensaver_webos(){
    try{
      if (typeof WebOSServiceBridge === 'undefined') return false;
      var bridge = new WebOSServiceBridge();
      bridge.onservicecallback = function(msg){
        try{
          var m = JSON.parse(msg);
          // Quando o sistema sinaliza que o screensaver vai ativar, recusamos.
          if (m && (m.state === 'Active' || m.timestamp)){
            var resp = new WebOSServiceBridge();
            resp.call(
              'luna://com.webos.service.tvpower/power/responseScreenSaverRequest',
              JSON.stringify({ clientName:'expositorCMMB', ack:false, timestamp:m.timestamp })
            );
          }
        }catch(e){}
      };
      bridge.call(
        'luna://com.webos.service.tvpower/power/registerScreenSaverRequest',
        JSON.stringify({ subscribe:true, clientName:'expositorCMMB' })
      );
      return true;
    }catch(e){ return false; }
  }

  // ---------------------------------------------------------------------------
  // Arranque
  // ---------------------------------------------------------------------------
  var arr = document.getElementById('arranque');

  function fs(){
    var el = document.documentElement;
    var r = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
    if (r){ try{ r.call(el); }catch(e){} }
  }

  // Arranca a sondagem do slides.json UMA vez. Havia dois setInterval — um no
  // comeca() e outro no listener de load — por isso, depois de um toque no ecrã
  // de arranque, a TV ficava a buscar o ficheiro a dobrar, para sempre.
  var sondagem = null;
  function arrancaSondagem(){
    if (sondagem) return;
    sincroniza();
    sondagem = setInterval(sincroniza, 15000);
  }

  function comeca(){
    arr.style.display = 'none';
    fs();
    anti_screensaver_webos();   // tenta o wake lock real
    arrancaSondagem();
  }

  arr.addEventListener('click', comeca);

  // Tenta arrancar automaticamente; se o fullscreen precisar de toque, o ecrã de
  // arranque fica à espera, mas a apresentação começa na mesma passado 1s para o
  // ecrã nunca ficar parado.
  window.addEventListener('load', function(){
    var el = document.documentElement;
    var r = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
    var auto = false;
    if (r){
      var pr = r.call(el);
      if (pr && pr.then){ pr.then(function(){ auto=true; arr.style.display='none'; }).catch(function(){}); }
    }
    anti_screensaver_webos();
    arrancaSondagem();
  });
</script>
</body>
</html>
"""


def _escrever_pagina_tv(cfg, slides):
    """Escreve o index.html e o slides.json da TV.

    Mudança de arquitetura face à versão anterior: os slides deixam de ser
    embebidos no HTML. Passam a viver num ficheiro à parte, 'slides.json', que a
    página busca periodicamente (polling). Assim, editais novos entram no carrossel
    SEM recarregar a página nem interromper a rotação — o HTML é escrito uma vez e
    só o JSON muda. O 'v' (versão) é um carimbo temporal que a página usa para
    detetar se houve alteração sem comparar a lista toda.

    Args:
        cfg (dict): configuração.
        slides (list[dict]): itens {src, assunto, pub}.
    """
    # slides.json — a fonte viva que a TV consulta em ciclo.
    payload = {
        "v": datetime.now().isoformat(timespec="seconds"),  # versão p/ deteção de mudança
        "gerado_em": datetime.now().isoformat(timespec="seconds"),  # frescura (ver TV)
        "spe": int(cfg["segundos_por_ecra"]),
        "titulo": cfg["titulo_tv"],
        "slides": slides,
    }
    # Escrita atómica, e não `open(..., "w")`: a TV busca este ficheiro de 15 em
    # 15 segundos e, com a escrita destrutiva, havia uma janela em que apanhava
    # JSON truncado. O fetch falhava, a página mostrava "sem ligação" e o operador
    # via um erro que não existia. Sem gerações — é um ficheiro derivado, que se
    # regenera sozinho no ciclo seguinte.
    arm.gravar_json(os.path.join(cfg["saida"], "slides.json"), payload, geracoes=0)

    # index.html — escrito uma vez; já não leva os slides lá dentro. Só precisa de
    # saber o título inicial e o intervalo por defeito (o resto vem do JSON).
    html = (_HTML_TEMPLATE.replace("__TITULO__", cfg["titulo_tv"])
            .replace("__SPE__", str(int(cfg["segundos_por_ecra"]))))
    _escrever_texto_atomico(os.path.join(cfg["saida"], "index.html"), html)


def _escrever_texto_atomico(caminho, texto):
    """Escreve um ficheiro de texto de forma atómica (temporário + troca).

    O index.html é reescrito a cada republicação enquanto a TV o pode estar a
    carregar. Vale a mesma regra do slides.json: ou tem a versão anterior inteira,
    ou a nova inteira.
    """
    import tempfile
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pasta, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _escrever_zip_publicados(cfg, reg, publicados):
    """Cria o ZIP de arquivo com os PNG publicados + o registo, e roda os antigos.

    Args:
        cfg (dict): configuração.
        reg (RegistoEntrada): registo de entrada.
        publicados (list[dict]): registos publicados.
    """
    import zipfile
    ts = datetime.now().strftime("%Y%m%d%H%M")
    zpath = os.path.join(cfg["saida"], f"{ts}_editais_expositor_CLD.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for r in publicados:
            for png in r.get("ficheiros_png", []):
                p = os.path.join(cfg["saida"], png)
                if os.path.exists(p):
                    z.write(p, png)
        z.writestr("registo_entrada.json",
                   json.dumps(reg._dados, ensure_ascii=False, indent=2))
    _rodar_zips(cfg)


def iniciar_painel(cfg):
    """Arranca o painel de gestão (servidor web) e o ciclo de leitura em fundo.

    Junta as duas metades do modelo novo: uma thread vigia a pasta de entrada e
    cria rascunhos; o servidor do painel serve a interface e a API de validação.
    A publicação (a partir do painel) regenera a página da TV via callback.

    Args:
        cfg (dict): configuração.
    """
    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])

    # Traz os editais do modelo antigo, se os houver. Corre antes de tudo o
    # resto e uma vez só: a seguir os ficheiros de origem são renomeados.
    if migracao.precisa_de_migrar(cfg):
        _agente.info("Encontrados editais no modelo antigo. A migrar…")
        migracao.migrar(cfg, reg)

    contas = utl.Utilizadores(cfg["utilizadores"])
    logo_im = carregar_logo(cfg)
    estado_do_agente = {"arranque": datetime.now().isoformat(timespec="seconds"),
                        "ultima_varredura": None, "ultima_publicacao": None,
                        "ecras_no_ar": 0}

    # Callback que o painel invoca após publicar/retirar: recompõe a TV.
    def republicar():
        n = publicar_registos(cfg, reg, logo_im)
        estado_do_agente["ultima_publicacao"] = datetime.now().isoformat(timespec="seconds")
        estado_do_agente["ecras_no_ar"] = n
        _tv.info(f"atualizada: {n} ecr\u00e3(s) no ar")

    # Thread de fundo: lê documentos novos e cria rascunhos periodicamente.
    def vigiar():
        while True:
            try:
                n = varrer_para_registo(cfg, reg, logo_im)
                estado_do_agente["ultima_varredura"] = datetime.now().isoformat(timespec="seconds")
                if n:
                    _agente.info(f"ENTRADA {n} novo(s) documento(s) em rascunho")
                # Aplica retiradas automáticas mesmo sem novos documentos.
                if reg.aplicar_retiradas_automaticas():
                    republicar()
                # Deita fora os testemunhos de sessões já sem validade, para a
                # memória não crescer com cada entrada que nunca é fechada.
                contas.limpar_sessoes_expiradas()
            except Exception as ex:
                print(f"[ERRO vigia] {ex}")
            time.sleep(int(cfg["intervalo_watch"]))

    def aquecer_fundos():
        """Desenha as variantes de fundo em falta, antes de alguém precisar delas.

        Cada variante custa ~7 s a desenhar e depois vive em disco para sempre.
        Feito aqui, em fundo e a baixa prioridade, a primeira publicação do dia
        já as encontra prontas em vez de as pagar uma a uma no pior momento —
        que é justamente quando alguém está à espera de ver o edital no ecrã.
        """
        for i in range(trat.VARIANTES_DE_FUNDO):
            try:
                trat.obter_fundo(seed=i, cache=cfg["fundos"])
            except Exception as ex:
                _fundos.info(f"falha a preparar a variante {i}: {ex}")
                return
        _fundos.info(f"{trat.VARIANTES_DE_FUNDO} variantes prontas em {cfg['fundos']}")

    import threading
    threading.Thread(target=aquecer_fundos, daemon=True).start()
    threading.Thread(target=vigiar, daemon=True).start()

    # Primeira publicação da TV em FUNDO: compor imagens 4K é pesado e não deve
    # atrasar o arranque do painel. O servidor fica disponível de imediato; a TV
    # atualiza-se assim que a composição terminar.
    threading.Thread(target=republicar, daemon=True).start()

    # Servidor do painel (bloqueante) — arranca já, sem esperar pela composição.
    html_path = os.path.join(BASE, "lib", "painel.html")
    servidor = painel_mod.PainelServer(
        reg, cfg, republicar_callback=republicar, painel_html_path=html_path,
        contas=contas,
        saude_callback=lambda: estado_de_saude(cfg, reg, estado_do_agente))
    servidor.iniciar(host=cfg["painel_host"], porta=int(cfg["painel_porta"]),
                     bloquear=True)


def estado_de_saude(cfg, reg, estado):
    """Reúne o estado do agente para a rota /saude.

    Serve para um supervisor de serviço (systemd, Nagios, Zabbix, um relógio de
    parede) saber se isto está vivo SEM ter de entrar no painel — daí ser a
    única rota que dispensa sessão. Por essa mesma razão só devolve números e
    instantes: contagens por estado, sim; assuntos de editais por validar, não.
    Um endereço sem autenticação não pode revelar o que ainda não é público.

    Args:
        cfg (dict): configuração.
        reg (RegistoEntrada): registo de entrada.
        estado (dict): marcadores vivos que o ciclo do painel vai atualizando.

    Returns:
        dict: estado, pronto a servir em JSON.
    """
    import shutil
    contagens = {e: len(reg.por_estado(e)) for e in reg_mod.ESTADOS}
    try:
        uso = shutil.disk_usage(cfg["saida"])
        disco = {"livre_mb": round(uso.free / 1e6), "total_mb": round(uso.total / 1e6)}
    except OSError:
        disco = None

    # 'ok' é o que um supervisor lê sem interpretar o resto: a vigia tem de ter
    # corrido há menos de três intervalos (dá folga a uma passagem demorada sem
    # deixar passar um ciclo morto) e tem de haver espaço para escrever as
    # imagens 4K, que é o que primeiro falha num disco cheio.
    limite = int(cfg["intervalo_watch"]) * 3
    fresco = True
    if estado.get("ultima_varredura"):
        idade = (datetime.now() - datetime.fromisoformat(estado["ultima_varredura"])).total_seconds()
        fresco = idade < limite
    espaco = disco is None or disco["livre_mb"] > 500

    return {
        "ok": bool(fresco and espaco),
        "versao": VERSAO,
        "arranque": estado.get("arranque"),
        "ultima_varredura": estado.get("ultima_varredura"),
        "ultima_publicacao": estado.get("ultima_publicacao"),
        "ecras_no_ar": estado.get("ecras_no_ar", 0),
        "editais": contagens,
        "disco": disco,
        "agora": datetime.now().isoformat(timespec="seconds"),
    }


def comando_criar_utilizador(cfg, nome, administrador=False):
    """Cria uma conta do painel a partir da linha de comandos.

    É por aqui que nasce a primeira conta, quando ainda não há painel onde
    entrar. A senha é pedida sem eco (getpass) e nunca passa por argumento da
    linha de comandos — um argumento fica no histórico da consola e na lista de
    processos, à vista de quem tiver acesso à máquina.

    Args:
        cfg (dict): configuração.
        nome (str): nome de utilizador a criar.
        administrador (bool): se True, a conta pode gerir contas.

    Returns:
        int: código de saída (0 = criada).
    """
    import getpass
    contas = utl.Utilizadores(cfg["utilizadores"])
    papel = utl.ADMINISTRADOR if administrador else utl.OPERADOR
    print(f"A criar a conta '{nome}' com o papel de {utl.PAPEL_LABEL[papel].lower()}.")
    nome_completo = input("Nome completo (como aparece na certidão): ").strip()
    senha = getpass.getpass("Senha (mínimo 10 caracteres): ")
    if senha != getpass.getpass("Repita a senha: "):
        _agente.error("As senhas não coincidem. Nada foi criado.")
        return 1
    try:
        conta = contas.criar(nome, senha, nome_completo=nome_completo, papel=papel,
                             por="linha de comandos")
    except utl.ErroDeUtilizador as e:
        _agente.error(f"{e}")
        return 1
    print(f"Conta '{conta['nome']}' criada. Já pode entrar no painel.")
    return 0


def comando_listar_utilizadores(cfg):
    """Mostra as contas do painel, para se saber quem tem acesso."""
    contas = utl.Utilizadores(cfg["utilizadores"])
    lista = contas.listar()
    if not lista:
        print("Ainda não há contas. Crie a primeira com:")
        print("  python agente.py --criar-utilizador NOME --administrador")
        return 0
    print(f"{'utilizador':<18}{'nome completo':<26}{'papel':<16}{'estado':<10}última entrada")
    print("-" * 92)
    for c in lista:
        print(f"{c['nome']:<18}{c['nome_completo'][:25]:<26}"
              f"{utl.PAPEL_LABEL[c['papel']]:<16}"
              f"{'activa' if c['activo'] else 'desactivada':<10}"
              f"{c['ultima_entrada'] or 'nunca'}")
    return 0


def carregar_logo(cfg):
    """Constrói o logótipo dourado gravado, se os ficheiros do símbolo existirem.

    Se faltarem os PNG do símbolo/texto, o agente continua a funcionar — apenas
    produz as composições sem logótipo (com aviso), em vez de falhar.

    Args:
        cfg (dict): configuração (caminhos logo_sym e logo_txt).

    Returns:
        PIL.Image.Image | None: logótipo pronto, ou None se indisponível.
    """
    if os.path.exists(cfg["logo_sym"]) and os.path.exists(cfg["logo_txt"]):
        return trat.build_logo(cfg["logo_sym"], cfg["logo_txt"], out_h=160)
    _agente.warning("log\u00f3tipo n\u00e3o encontrado em assets/ \u2014 sa\u00edda sem logo.")
    return None

def comando_conferir(cfg):
    """Relata o que está desalinhado entre o registo e o disco.

    Não apaga nem corrige nada, e isso é o desenho: as decisões sobre um edital
    municipal são de quem responde por ele. Isto diz o que há, e diz por onde se
    resolve.

    Args:
        cfg (dict): configuração.

    Returns:
        int: 0 se não houver nada a assinalar, 1 se houver.
    """
    import conferencia

    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    r = conferencia.conferir(cfg, reg)

    e = r["registos"]["por_estado"]
    print(f"\nREGISTO — {r['registos']['total']} editais")
    print("  " + " · ".join(f"{reg_mod.ESTADO_LABEL[k].lower()}: {v}"
                            for k, v in e.items()))
    mb = r["arquivo"]["bytes"] / (1024 * 1024)
    print(f"  arquivo imutável: {r['arquivo']['documentos']} documentos, {mb:.1f} MB")

    if r["sem_original"]:
        print(f"\nSEM ORIGINAL — {len(r['sem_original'])} registo(s)")
        print("  O documento não está no arquivo nem nas pastas de entrada.")
        print("  Estes editais NÃO se conseguem compor, e por isso não vão ao ecrã.")
        for x in r["sem_original"]:
            falta = "" if x["tem_data"] else "  [e sem data de publicação]"
            print(f"  #{x['id']:<4} {x['estado']:<11} {x['numero'] or '(sem número)':<12} "
                  f"{x['assunto'] or '(sem assunto)'}{falta}")
            print(f"       ficheiro que falta: {x['ficheiro_origem'] or '(não registado)'}")

    if r["rascunhos_impossiveis"]:
        print(f"\nSEM SAÍDA — {len(r['rascunhos_impossiveis'])} rascunho(s)")
        print("  Sem data de publicação não se validam; sem original não se publicam.")
        print("  Ficam na fila «Por validar» para sempre. Ou se lhes dá a data e se")
        print("  repõe o ficheiro em entrada/, ou se descartam no painel com o motivo.")
        print("  ids: " + ", ".join(f"#{x['id']}" for x in r["rascunhos_impossiveis"]))

    for chave, titulo, onde in (
            ("png_orfaos", "ECRÃS ÓRFÃOS", "saida/"),
            ("previas_orfas", "PRÉ-VISUALIZAÇÕES ÓRFÃS", "previas/"),
            ("originais_orfaos", "ORIGINAIS ÓRFÃOS", "originais/")):
        if r[chave]:
            print(f"\n{titulo} — {len(r[chave])} ficheiro(s) em {onde}")
            print("  Nenhum registo os reclama. Não são apagados por aqui.")
            for nome in r[chave][:12]:
                print(f"  {nome}")
            if len(r[chave]) > 12:
                print(f"  … e mais {len(r[chave]) - 12}")

    if not conferencia.ha_problemas(r):
        print("\nTudo alinhado: cada registo tem o seu documento, e cada ficheiro")
        print("em disco tem o seu registo.\n")
        return 0
    print("\nNada foi apagado nem alterado. Isto é um relatório.\n")
    return 1


def comando_exportar_pastas(cfg):
    """Reconstrói as pastas publicados/ e retirados/ a partir do registo.

    Args:
        cfg (dict): configuração.

    Returns:
        int: 0 em caso de sucesso, 1 se a exportação foi recusada.
    """
    import exportacao

    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    try:
        r = exportacao.exportar(cfg, reg)
    except RuntimeError as ex:
        _agente.error(f"{ex}")
        return 1
    print(f"\nExportado para {r['raiz']}")
    print(f"  publicados: {r['publicados']}")
    print(f"  retirados:  {r['retirados']}")
    print(f"  índice:     {r['indice']}")
    if r["sem_original"]:
        print(f"\n  {len(r['sem_original'])} edital(is) sem original arquivado ficaram")
        print("  só no índice, sem ficheiro. Use --conferir para os ver.")
    print("\nEstas pastas são uma VISTA do registo, construída agora. Mover um")
    print("ficheiro de lá não muda o estado de nada — isso faz-se no painel.\n")
    return 0


def main():
    """Ponto de entrada da linha de comandos.

    Há um só modo de serviço: --painel. Os modos --once, --watch e --rebuild-web
    saíram na versão 0.14 com o caminho de publicação automática que serviam.

    A razão não é arrumação. Desde a Onda 2 a aplicação emite uma certidão que
    diz QUEM afixou cada edital, e um caminho que publicava sem ninguém não
    tinha essa resposta. Mantê-lo era garantir que, mais cedo ou mais tarde,
    alguém pediria a certidão de um edital afixado por ninguém.
    """
    ap = argparse.ArgumentParser(
        description="Agente de editais do expositor municipal",
        epilog="Os modos --once, --watch e --rebuild-web foram retirados na "
               "versão 0.14: a publicação passa sempre pelo painel, para a "
               "certidão de afixação poder dizer quem afixou cada edital.")
    ap.add_argument("--painel", action="store_true",
                    help="arranca o painel de gestão (validação humana no browser)")
    ap.add_argument("--criar-utilizador", metavar="NOME",
                    help="cria uma conta de acesso ao painel (pede a senha sem eco)")
    ap.add_argument("--administrador", action="store_true",
                    help="com --criar-utilizador: dá-lhe também a gestão de contas")
    ap.add_argument("--utilizadores", action="store_true",
                    help="lista as contas de acesso ao painel")
    ap.add_argument("--conferir", action="store_true",
                    help="compara o registo com o disco e relata o que não bate certo")
    ap.add_argument("--exportar-pastas", action="store_true",
                    help="reconstrói as pastas publicados/ e retirados/ a partir do registo")
    ap.add_argument("--versao", action="version", version=f"agente de editais {VERSAO}")
    args = ap.parse_args()

    cfg = load_config()

    # Gestão de contas: não arranca serviço nenhum, faz o que lhe pedem e sai.
    if args.criar_utilizador:
        return comando_criar_utilizador(cfg, args.criar_utilizador, args.administrador)
    if args.utilizadores:
        return comando_listar_utilizadores(cfg)
    if args.conferir:
        return comando_conferir(cfg)
    if args.exportar_pastas:
        return comando_exportar_pastas(cfg)

    if not args.painel:
        # Sem argumentos, mostra a ajuda em vez de não fazer nada em silêncio.
        # Antes, correr `python agente.py` sem mais nada fazia uma publicação
        # automática — precisamente o que deixou de existir.
        ap.print_help()
        return 0

    try:
        iniciar_painel(cfg)
    except RuntimeError as e:
        # Erro esperado e acionável (tipicamente: ainda não há contas). A
        # mensagem da exceção já diz o que fazer, e é mostrada tal e qual em
        # vez de um traceback que assusta sem informar.
        _painel.error(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
