#!/usr/bin/env python3
"""
agente.py — Agente de automação dos editais do expositor da CMMB.

É o "maestro" do sistema: liga o módulo de documentos (ler/converter) ao módulo
de tratamento (compor) e produz o que a televisão consome.

Fluxo de uma execução:
  1. Lê os documentos NOVOS da pasta de entrada (PDF, imagens, Word) — todas as
     páginas de cada um.
  2. Extrai os metadados (assunto, número, data de publicação) de cada documento.
  3. AGRUPA as folhas por assunto (juntando páginas do mesmo documento E documentos
     diferentes com o mesmo assunto) e distribui-as por ecrãs de até 3 folhas,
     todas ao mesmo tamanho — aproveitando o formato 16:9.
  4. Trata visualmente cada ecrã e grava-o com nome datado.
  5. Datas de saída de exposição: geridas num ficheiro de texto simples,
     'retiradas.txt' (o utilizador só escreve a data à frente de cada edital).
  6. Gera a página da TV ('saida/index.html', ecrã inteiro, 30 s por ecrã) e um
     ZIP de arquivo, mantendo apenas as 3 cópias ZIP mais recentes.

Modos de utilização:
  python agente.py --once          # processa uma vez e termina
  python agente.py --watch         # fica a vigiar a pasta, em ciclo
  python agente.py --rebuild-web   # só reconstrói página+ZIP (após editar retiradas)

Ficheiros de estado (na raiz do projeto):
  - editais.json  : registo de todos os ecrãs já produzidos (metadados).
  - estado.json   : hashes dos ficheiros já processados (evita reprocessar).
  - retiradas.txt : datas de saída, editáveis à mão.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime

# Versão do pacote, espelhada no pyproject.toml. Vai no /saude e nos registos,
# para se saber qual a versão que está a correr num posto sem abrir ficheiros.
VERSAO = "0.12.0"

# A pasta do próprio script é a raiz do projeto; 'lib/' é adicionada ao path
# para importar os módulos internos sem depender de instalação.
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "lib"))
import armazenamento as arm  # escrita durável (atómica, com gerações)
import diario  # registo técnico (níveis, rotação, ficheiro)
import documentos as doc
import originais as orig  # arquivo imutável dos documentos
import painel as painel_mod  # servidor do painel de gestão
import prazos as pr  # tipos de documento e janelas legais
import registo as reg_mod  # registo de entrada (fluxo de estados)
import tratamento as trat
import utilizadores as utl  # contas, senhas derivadas e sessões
from PIL import Image

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
    "saida":    os.path.join(BASE, "saida"),
    "arquivo":  os.path.join(BASE, "arquivo"),   # ZIP permanente dos retirados
    "previas":  os.path.join(BASE, "previas"),   # pré-visualizações leves p/ o painel
    "originais": os.path.join(BASE, "originais"), # arquivo imutável dos documentos
    "fundos":   os.path.join(BASE, "fundos"),    # cache dos fundos metálicos pré-desenhados
    "trabalho": os.path.join(BASE, "trabalho"),
    "estado":   os.path.join(BASE, "estado.json"),
    "registo":  os.path.join(BASE, "editais.json"),
    "retiradas": os.path.join(BASE, "retiradas.txt"),
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
    for k in ("entrada", "saida", "arquivo", "previas", "fundos", "originais", "trabalho"):
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

def _load_json(path, default):
    """Lê um JSON, devolvendo um valor por omissão se o ficheiro não existir.

    Args:
        path (str): caminho do ficheiro.
        default: valor a devolver quando o ficheiro está ausente.

    Returns:
        O conteúdo do JSON, ou 'default'.
    """
    return arm.ler_json(path, default)

def _save_json(path, data):
    """Grava 'data' como JSON de forma atómica, com gerações de recurso.

    Args:
        path (str): destino.
        data: estrutura serializável em JSON.
    """
    arm.gravar_json(path, data)

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


# ===========================================================================
# Datas de saída de exposição — ficheiro de texto simples 'retiradas.txt'
# Optou-se por texto (e não JSON) para o funcionário poder editar sem risco de
# partir sintaxe: basta escrever a data à frente de cada edital.
# ===========================================================================
def garantir_retiradas(cfg, registo):
    """Assegura que o retiradas.txt existe e tem uma linha por edital conhecido.

    Cria o ficheiro com o cabeçalho de ajuda se faltar, e acrescenta uma linha
    (chave + "= ") por cada assunto/número ainda não listado — assim o utilizador
    encontra sempre lá o edital novo, pronto a receber a data.

    Args:
        cfg (dict): configuração (para o caminho do ficheiro).
        registo (dict): registo de editais já produzidos.
    """
    path = cfg["retiradas"]
    existentes = _ler_retiradas(path)   # o que já lá está (para não duplicar)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(_CABECALHO_RETIRADAS)
    # Percorre os editais e junta os que ainda não têm entrada. Usa-se o número
    # (ou o início do assunto) como chave, e um set 'vistos' evita repetir a mesma
    # chave quando há vários ecrãs do mesmo edital (partes p1de2, p2de2...).
    vistos = set()
    novas = []
    for e in registo["editais"]:
        chave = e.get("numero") or (e.get("assunto", "")[:50])
        nk = _norm(chave)
        if not nk or nk in vistos:
            continue
        vistos.add(nk)
        if nk in existentes:
            continue
        novas.append((chave, e.get("assunto", ""), e.get("data_publicacao")))
    if novas:
        with open(path, "a", encoding="utf-8") as f:
            for rotulo, assunto, pub in novas:
                # Comentário com o assunto + linha editável "chave = " (data em branco).
                f.write(f"\n# {assunto}  (publicado {pub or '?'})\n{rotulo} = \n")

def _ler_retiradas(path):
    """Lê o retiradas.txt e devolve um mapa {chave_normalizada: data}.

    Tolerante por design: ignora linhas em branco e comentários (#), aceita '='
    ou ';' como separador, e ignora datas mal escritas (não rebenta).

    Args:
        path (str): caminho do retiradas.txt.

    Returns:
        dict[str, datetime.date]: datas de saída por chave normalizada.
    """
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sep = "=" if "=" in line else (";" if ";" in line else None)
            if not sep:
                continue
            chave, _, valor = line.partition(sep)
            valor = valor.strip()
            if not valor:            # data em branco = fica no ecrã indefinidamente
                continue
            d = _parse_data(valor)
            if d:
                out[_norm(chave)] = d
    return out

def _parse_data(s):
    """Interpreta uma data em ISO, DD/MM/AAAA ou DD-MM-AAAA (ou None).

    Args:
        s (str): texto da data.

    Returns:
        datetime.date | None
    """
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None

def _norm(s):
    """Normaliza uma chave para comparação: minúsculas, só letras e dígitos.

    Torna a correspondência robusta a acentos, espaços e pontuação, para que
    "2026-0017" e "2026 0017" ou variações do assunto casem na mesma.

    Args:
        s (str): texto a normalizar.

    Returns:
        str: versão normalizada (alfanumérica, minúscula).
    """
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())

def retirada_de(e, mapa):
    """Descobre a data de saída de um edital, procurando por número e por assunto.

    Tenta primeiro a correspondência exata pelo número (mais fiável); se falhar,
    procura por inclusão parcial do assunto (para quem preferiu escrever texto
    em vez do número na chave).

    Args:
        e (dict): entrada de edital do registo.
        mapa (dict): mapa {chave: data} vindo de _ler_retiradas.

    Returns:
        datetime.date | None: a data de saída, se encontrada.
    """
    num = _norm(e.get("numero", ""))
    if num and num in mapa:
        return mapa[num]
    asn = _norm(e.get("assunto", ""))[:40]
    for chave, d in mapa.items():
        if chave and (chave in asn or asn in chave):
            return d
    return None


# ===========================================================================
# Numeração e nomes de ficheiro
# ===========================================================================
def proximo_indice(registo):
    """Devolve o próximo índice sequencial global de ecrã.

    O índice é contínuo entre execuções (baseia-se no máximo já registado), para
    a numeração nunca recuar nem repetir.

    Args:
        registo (dict): registo de editais.

    Returns:
        int: próximo índice (>= 1).
    """
    if not registo["editais"]:
        return 1
    return max(e["indice"] for e in registo["editais"]) + 1

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

def _chunk(lst, k):
    """Parte uma lista em blocos de no máximo k elementos (3, 3, ..., resto).

    É o que implementa a regra "encher até 3 folhas por ecrã".

    Args:
        lst (list): itens a dividir.
        k (int): tamanho máximo de cada bloco.

    Returns:
        list[list]: lista de blocos.
    """
    return [lst[i:i + k] for i in range(0, len(lst), k)]

def ativos_hoje(cfg, registo):
    """Devolve os ecrãs que devem estar visíveis hoje (retirada ainda não passou).

    Um ecrã é escondido quando a data de saída do seu edital já ficou para trás.
    Não é apagado do registo — apenas não entra na página nem no ZIP.

    Args:
        cfg (dict): configuração (para ler o retiradas.txt).
        registo (dict): registo de editais.

    Returns:
        list[dict]: ecrãs ativos, ordenados pelo índice.
    """
    mapa = _ler_retiradas(cfg["retiradas"])
    hoje = date.today()
    ativos = [e for e in registo["editais"]
              if not (retirada_de(e, mapa) and retirada_de(e, mapa) < hoje)]
    ativos.sort(key=lambda e: e["indice"])
    return ativos

def gerar_pagina_web(cfg, registo):
    """Escreve a página da TV (saida/index.html) com os ecrãs ativos embebidos.

    Preenche o template HTML com a lista de slides (imagem + assunto + data de
    publicação) e o tempo por ecrã. O rodapé mostra tema à esquerda e data à
    direita — SEM número de ordem, por opção.

    Args:
        cfg (dict): configuração.
        registo (dict): registo de editais.

    Returns:
        tuple[str, int]: (caminho do index.html, nº de ecrãs ativos).
    """
    ativos = ativos_hoje(cfg, registo)
    slides = [{"src": e["ficheiro_png"], "assunto": e["assunto"],
               "pub": e["data_publicacao"] or ""} for e in ativos]
    # Nova arquitetura: escreve o slides.json (fonte viva que a TV consulta em
    # ciclo) e o index.html (sem slides embebidos). Reutiliza a mesma função do
    # fluxo do painel, para os dois modos gerarem exatamente a mesma coisa.
    _escrever_pagina_tv(cfg, slides)
    out = os.path.join(cfg["saida"], "index.html")
    return out, len(ativos)

def gerar_zip(cfg, registo):
    """Cria um ZIP de arquivo com os PNG ativos + o registo, e roda os antigos.

    O ZIP é conveniência de arquivo/partilha — a TV não precisa dele (usa a
    página). Inclui o editais.json para o arquivo ser auto-descritivo.

    Args:
        cfg (dict): configuração.
        registo (dict): registo de editais.

    Returns:
        str: caminho do ZIP criado.
    """
    import zipfile
    ts = datetime.now().strftime("%Y%m%d%H%M")
    zpath = os.path.join(cfg["saida"], f"{ts}_editais_expositor_CLD.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for e in ativos_hoje(cfg, registo):
            p = os.path.join(cfg["saida"], e["ficheiro_png"])
            if os.path.exists(p):
                z.write(p, e["ficheiro_png"])
        z.writestr("editais.json", json.dumps(registo, ensure_ascii=False, indent=2))
    _rodar_zips(cfg)   # limpa cópias antigas logo a seguir a criar a nova
    return zpath

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

def varrer(cfg, registo, estado, logo_im):
    """Processa os documentos novos: lê, agrupa por assunto e compõe os ecrãs.

    É aqui que vive a regra de negócio central. O processamento é feito em quatro
    fases deliberadas, e NÃO documento-a-documento, porque documentos diferentes
    podem partilhar assunto e devem juntar-se no mesmo ecrã:

      1. Ler todas as páginas dos ficheiros ainda não processados (por hash).
      2. Agrupar essas páginas por assunto/número, preservando a ordem de chegada.
      3. Para cada grupo, partir em blocos de até 3 folhas e compor um ecrã por bloco.
      4. Marcar os ficheiros como processados (para não repetir na próxima passagem).

    Args:
        cfg (dict): configuração.
        registo (dict): registo de editais (é ATUALIZADO com os novos ecrãs).
        estado (dict): estado de processamento (é ATUALIZADO com os hashes novos).
        logo_im (PIL.Image.Image | None): logótipo a aplicar, ou None.

    Returns:
        int: número de GRUPOS (assuntos) novos processados nesta passagem.
    """
    # ---- Fase 1: recolher as páginas novas, na ordem alfabética dos ficheiros ----
    # 'pendentes' guarda cada página como um tuplo com tudo o que é preciso depois:
    # a chave de agrupamento, os metadados, a imagem, o hash e o nome de origem.
    pendentes = []
    novos_hashes = {}
    for nome in sorted(os.listdir(cfg["entrada"])):
        path = os.path.join(cfg["entrada"], nome)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(nome)[1].lower() not in doc.SUPPORTED:
            continue
        h = file_hash(path)
        if h in estado["processados"]:   # já visto antes → ignora
            continue
        try:
            pages, text = doc.to_pages_and_text(path, cfg["trabalho"])
            meta = doc.extract_metadata(text, fallback_name=nome)
            # A chave de agrupamento é o número do edital (preferido, mais fiável)
            # ou o assunto; normalizada para casar apesar de acentos/espaços.
            chave = _norm(meta.get("numero") or meta.get("assunto") or nome)
            for pg in pages:
                pendentes.append((chave, meta, pg, h, nome))
            novos_hashes.setdefault(h, {"ficheiro": nome, "paginas": len(pages),
                                        "em": datetime.now().isoformat(timespec="seconds"),
                                        "ecras": []})
            _agente.info(f"LER {nome}: {len(pages)} pág | assunto: {meta['assunto'] or '(n/d)'}")
        except Exception as ex:
            # Um documento problemático não deve derrubar o lote inteiro.
            _agente.error(f"{nome}: {ex}")

    if not pendentes:
        return 0

    # ---- Fase 2: agrupar por assunto, mantendo a ordem de chegada ----
    # 'ordem' preserva a sequência em que os assuntos apareceram (dict mantém
    # inserção, mas ser explícito deixa a intenção clara e é robusto).
    ordem = []
    grupos = {}
    for chave, meta, pg, h, nome in pendentes:
        if chave not in grupos:
            grupos[chave] = {"meta": meta, "itens": []}
            ordem.append(chave)
        grupos[chave]["itens"].append((pg, h, nome))

    # ---- Fase 3: compor ecrãs de até 3 folhas por grupo ----
    novos = 0
    for chave in ordem:
        g = grupos[chave]
        meta = g["meta"]
        itens = g["itens"]
        slug = doc.slugify(meta["assunto"] or doc._humanize(itens[0][2]))
        blocos = _chunk(itens, trat.MAX_POR_ECRA)   # ex.: 5 folhas → [3, 2]
        total = len(blocos)
        for bi, bloco in enumerate(blocos, start=1):
            indice = proximo_indice(registo)
            seed = 3 + (indice - 1) * 7              # padrão de fundo distinto por ecrã
            comp = trat.compose_sheets([it[0] for it in bloco], seed=seed, logo_im=logo_im,
                                       cache_fundos=cfg["fundos"])
            out_name = nome_saida(indice, slug, parte=bi, total=total)
            comp.save(os.path.join(cfg["saida"], out_name), "PNG")
            ent = {"indice": indice, "ficheiro_origem": bloco[0][2],
                   "ficheiro_png": out_name, "assunto": meta["assunto"],
                   "numero": meta["numero"], "entidade": meta["entidade"],
                   "data_publicacao": meta["data_publicacao"],
                   "parte": bi, "total_partes": total, "folhas_neste_ecra": len(bloco),
                   "processado_em": datetime.now().isoformat(timespec="seconds")}
            registo["editais"].append(ent)
            # Regista, em cada ficheiro de origem, que ecrãs gerou (rastreabilidade).
            for (_pg, h, _nome) in bloco:
                if h in novos_hashes:
                    novos_hashes[h]["ecras"].append(out_name)
        _agente.info(f"OK  assunto '{meta['assunto'] or slug}': "
              f"{len(itens)} folha(s) -> {total} ecr\u00e3(s)")
        novos += 1

    # ---- Fase 4: marcar ficheiros como processados ----
    for h, info in novos_hashes.items():
        estado["processados"][h] = info
    return novos

def reconstruir_saidas(cfg, registo):
    """Regenera tudo o que a TV consome: retiradas.txt, index.html e ZIP.

    Chamada no fim de cada ciclo (e pelo modo --rebuild-web). Não processa
    documentos novos; apenas reflete o estado atual do registo nas saídas.

    Args:
        cfg (dict): configuração.
        registo (dict): registo de editais.
    """
    garantir_retiradas(cfg, registo)
    web, n = gerar_pagina_web(cfg, registo)
    zp = gerar_zip(cfg, registo)
    _agente.info(f"WEB {web}  ({n} ecr\u00e3(s) ativos)")
    _agente.info(f"ZIP {zp}")


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
            ocr_nota = " [via OCR]" if doc_lido["ocr"] else ""
            duv = ", ".join(r["campos_duvidosos"]) or "nenhum"
            print(f"[RASCUNHO #{r['id']}] {nome}{ocr_nota}: {len(pages)} pág | "
                  f"assunto: {meta['assunto'] or '(n/d)'} | a confirmar: {duv}")
            novos += 1
        except Exception as ex:
            _agente.error(f"{nome}: {ex}")
    return novos


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
        origem = os.path.join(cfg["entrada"], r["ficheiro_origem"])
        if os.path.exists(origem):
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
    blocos = _chunk(pages, trat.MAX_POR_ECRA)
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

def main():
    """Ponto de entrada da linha de comandos: interpreta o modo e corre o ciclo.

    Modos: --once (uma passagem), --watch (ciclo contínuo), --rebuild-web (só
    regenera saídas). O ciclo interno lê os documentos novos, grava o estado
    apenas se houve novidades, e regenera sempre a página/ZIP no fim.
    """
    ap = argparse.ArgumentParser(description="Agente de editais CMMB")
    ap.add_argument("--once", action="store_true", help="processa uma vez e termina")
    ap.add_argument("--watch", action="store_true", help="vigia a pasta em contínuo")
    ap.add_argument("--rebuild-web", action="store_true",
                    help="só reconstrói página+ZIP (após editar retiradas.txt)")
    ap.add_argument("--painel", action="store_true",
                    help="arranca o painel de gestão (validação humana no browser)")
    ap.add_argument("--criar-utilizador", metavar="NOME",
                    help="cria uma conta de acesso ao painel (pede a senha sem eco)")
    ap.add_argument("--administrador", action="store_true",
                    help="com --criar-utilizador: dá-lhe também a gestão de contas")
    ap.add_argument("--utilizadores", action="store_true",
                    help="lista as contas de acesso ao painel")
    ap.add_argument("--versao", action="version", version=f"agente de editais {VERSAO}")
    args = ap.parse_args()

    cfg = load_config()

    # Gestão de contas: não arranca serviço nenhum, faz o que lhe pedem e sai.
    if args.criar_utilizador:
        return comando_criar_utilizador(cfg, args.criar_utilizador, args.administrador)
    if args.utilizadores:
        return comando_listar_utilizadores(cfg)

    # Modo PAINEL: fluxo com validação humana. Os documentos entram como rascunho
    # e só vão ao ecrã depois de validados/publicados no browser. É o modo
    # recomendado para uso corrente; corre até Ctrl+C.
    if args.painel:
        try:
            iniciar_painel(cfg)
        except RuntimeError as e:
            # Erro esperado e acionável (tipicamente: ainda não há contas). A
            # mensagem da exceção já diz o que fazer, e é mostrada tal e qual em
            # vez de um traceback que assusta sem informar.
            _painel.error(str(e))
            return 1
        return

    # Carrega estado persistente; na primeira execução, arranca de estruturas vazias.
    registo = _load_json(cfg["registo"], {"editais": []})
    estado = _load_json(cfg["estado"], {"processados": {}})

    # Atalho: só reconstruir as saídas (típico depois de editar datas de saída).
    if args.rebuild_web:
        reconstruir_saidas(cfg, registo)
        return

    logo_im = carregar_logo(cfg)

    def ciclo():
        """Uma passagem completa: processar novos + persistir + regenerar saídas."""
        n = varrer(cfg, registo, estado, logo_im)
        if n:  # só grava se houve mudanças, para não reescrever ficheiros à toa
            _save_json(cfg["registo"], registo)
            _save_json(cfg["estado"], estado)
        reconstruir_saidas(cfg, registo)
        return n

    if args.watch:
        # Modo serviço: repete o ciclo com uma pausa entre passagens.
        _agente.info(f"WATCH a vigiar {cfg['entrada']} (Ctrl+C para parar)")
        try:
            while True:
                ciclo()
                time.sleep(int(cfg["intervalo_watch"]))
        except KeyboardInterrupt:
            print("\n[FIM] vigil\u00e2ncia terminada.")
    else:
        # --once (predefinição): uma passagem e sai.
        ciclo()

_CABECALHO_RETIRADAS = """# ---------------------------------------------------------------
# DATAS DE SAÍDA DE EXPOSIÇÃO
# ---------------------------------------------------------------
# Escreva, à frente de cada edital, a data em que ele deve SAIR do ecrã.
# Formato: AAAA-MM-DD  (ex.: 2026-07-29)  ou  DD/MM/AAAA
# Deixe em branco para ficar no ecrã indefinidamente.
# Linhas começadas por # são ignoradas.
# O agente acrescenta aqui, automaticamente, uma linha por edital novo.
# ---------------------------------------------------------------
"""

# ===========================================================================
# Template da página da TV (expositor).
#
# Arquitetura (mudou face à versão anterior):
#   - Os slides NÃO estão embebidos no HTML. A página busca 'slides.json' em ciclo
#     (polling) e atualiza o carrossel AO VIVO — editais novos entram sem recarregar
#     a página e sem cortar a rotação a decorrer. Só o marcador __SPE__ (intervalo
#     por defeito) e __TITULO__ são injetados; tudo o resto vem do JSON.
#   - Carrossel verdadeiramente infinito: roda para sempre até ordem em contrário.
#     Já NÃO há location.reload() (era ele que interrompia o ciclo).
#   - Fundo com "veias" douradas em movimento ondular, desenhadas num <canvas> por
#     baixo dos editais (decisão de DESIGN — não é o que impede o screensaver).
#   - Anti-screensaver do webOS: tentativa via API Luna (WebOSServiceBridge). Fala
#     com o gestor de energia da TV a dizer "não durmas". PODE não estar acessível
#     a partir do browser — só se confirma na TV real; ver comentário no código.
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

if __name__ == "__main__":
    sys.exit(main() or 0)
