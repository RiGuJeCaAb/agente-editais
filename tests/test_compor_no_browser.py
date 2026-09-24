"""
test_compor_no_browser.py — A televisão passou a compor o ecrã.

Compunha-se em Python uma imagem de 3840×2160 por ecrã, com fundo, sombras e
folhas cozidos lá dentro, e mandava-se essa imagem para a televisão. Medido, era
o passo mais caro de publicar: 3,02 s e 546 MB de pico por ecrã, dos quais 0,88 s
só para gravar o ficheiro de 3,14 MB.

E era trabalho a dobrar sem se saber: a página da televisão já desenhava um
fundo verde com veias douradas, e esse fundo estava 100% tapado pelo PNG opaco —
num ecrã 16:9 a imagem cobre tudo. Pagava-se duas vezes pelo mesmo fundo e via-se
o mais caro.

Agora a televisão recebe as folhas e as coordenadas, e compõe. O PNG continua a
existir, mas mudou de momento: faz-se na RETIRADA, à porta do arquivo, que é
quando há um facto completo para registar e ninguém está à espera.

O que estes testes protegem, por ordem de gravidade:
  1. o que fica no arquivo tem de ser o que esteve no ecrã;
  2. um edital afixado tem de ter folhas na pasta, senão a televisão fica vazia;
  3. nada do que se escreve na pasta de saída pode ficar sem dono.
"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

import agente
import conferencia
import registo as reg_mod
import tratamento as trat


@pytest.fixture
def posto(tmp_path):
    """Uma instalação com um edital de três páginas à espera na entrada."""
    import fitz
    cfg = dict(agente.CONFIG)
    for chave, valor in agente.CONFIG.items():
        if isinstance(valor, str) and valor.startswith(agente.BASE):
            cfg[chave] = str(tmp_path / os.path.relpath(valor, agente.BASE))
    # O logótipo vive no repositório, não na instalação.
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg["logo_sym"] = os.path.join(raiz, "assets", "sym_ok.png")
    cfg["logo_txt"] = os.path.join(raiz, "assets", "txt_ok.png")
    for nome in ("entrada", "saida", "previas", "originais", "trabalho",
                 "fundos", "arquivo", "exportacao"):
        os.makedirs(cfg[nome], exist_ok=True)
    cfg["tratados"] = os.path.join(cfg["entrada"], "tratados")
    os.makedirs(cfg["tratados"], exist_ok=True)

    d = fitz.open()
    for i in range(3):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((70, 150), f"EDITAL — pagina {i + 1}", fontsize=22)
    d.save(os.path.join(cfg["entrada"], "edital.pdf"))
    d.close()
    return {"cfg": cfg, "reg": reg_mod.RegistoEntrada(cfg["registo_entrada"]),
            "logo": agente.carregar_logo(cfg)}


def publicar(posto):
    """Leva o edital da entrada até ao ecrã, e devolve o seu id."""
    agente.varrer_para_registo(posto["cfg"], posto["reg"], posto["logo"])
    rid = posto["reg"].todos()[0]["id"]
    posto["reg"].editar(rid, {"data_publicacao": "2026-06-29"}, utilizador="ana.abreu")
    posto["reg"].mover_estado(rid, reg_mod.VALIDADO, utilizador="ana.abreu")
    posto["reg"].mover_estado(rid, reg_mod.PUBLICADO, utilizador="ana.abreu")
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])
    return rid


def folhas_na_pasta(cfg):
    return sorted(f for f in os.listdir(cfg["saida"]) if f.startswith("folha_"))


def pngs_na_pasta(cfg):
    return sorted(f for f in os.listdir(cfg["saida"])
                  if f.endswith(".png") and f != "logotipo.png")


# ---------------------------------------------------------------------------
# Publicar: folhas, não imagem composta
# ---------------------------------------------------------------------------
def test_publicar_deixa_folhas_e_nenhum_png(posto):
    """É o cerne da peça: ao publicar já não se compõe imagem nenhuma."""
    publicar(posto)
    assert len(folhas_na_pasta(posto["cfg"])) == 3
    assert pngs_na_pasta(posto["cfg"]) == []


def test_o_registo_guarda_o_desenho_e_nao_o_png(posto):
    rid = publicar(posto)
    r = posto["reg"].por_id(rid)
    assert len(r["ecras"]) == 1
    assert len(r["ecras"][0]["folhas"]) == 3
    assert r["ficheiros_png"] == []


def test_as_coordenadas_sao_as_mesmas_que_o_python_usa(posto):
    """O que a televisão desenha tem de ser o que o arquivo vai guardar.

    Se divergissem, a imagem arquivada deixava de ser prova do que esteve
    afixado — e é só para isso que ela existe.
    """
    from PIL import Image
    rid = publicar(posto)
    r = posto["reg"].por_id(rid)
    a4 = [Image.new("RGB", (1785, 2526), "white") for _ in range(3)]
    esperadas = trat.caixas_do_ecra(a4)
    obtidas = [(f["x"], f["y"], f["w"], f["h"]) for f in r["ecras"][0]["folhas"]]
    assert obtidas == esperadas


def test_a_televisao_recebe_o_desenho_no_slides_json(posto):
    publicar(posto)
    d = json.loads((open(os.path.join(posto["cfg"]["saida"], "slides.json"),
                         encoding="utf-8")).read())
    assert len(d["slides"]) == 1
    assert len(d["slides"][0]["ecra"]["folhas"]) == 3
    assert "src" not in d["slides"][0], "o slide já não é uma imagem composta"


def test_a_pagina_da_tv_leva_as_medidas_do_palco_do_tratamento(posto):
    """As coordenadas das folhas foram calculadas sobre este palco. Um palco de
    outras medidas punha-as no sítio errado sem nada se queixar."""
    publicar(posto)
    html = open(os.path.join(posto["cfg"]["saida"], "index.html"),
                encoding="utf-8").read()
    assert f"width:{trat.CANVAS_W}px" in html
    assert f"height:{trat.CANVAS_H}px" in html
    assert "__PALCO_W__" not in html, "ficou um marcador por substituir"


def test_o_logotipo_e_servido_para_a_televisao_o_poder_assentar(posto):
    """Vinha gravado dentro de cada PNG. Agora quem o assenta é a televisão."""
    publicar(posto)
    assert os.path.exists(os.path.join(posto["cfg"]["saida"], "logotipo.png"))


# ---------------------------------------------------------------------------
# Retirar: é aqui que a imagem do arquivo se faz
# ---------------------------------------------------------------------------
def test_retirar_compoe_o_png_e_arquiva_o(posto):
    """O ZIP de arquivo tem de receber exatamente o que recebia antes."""
    rid = publicar(posto)
    posto["reg"].mover_estado(rid, reg_mod.RETIRADO, utilizador="ana.abreu")
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])

    r = posto["reg"].por_id(rid)
    assert len(r["ficheiros_png"]) == 1
    zpath = os.path.join(posto["cfg"]["arquivo"], "arquivo_editais.zip")
    with zipfile.ZipFile(zpath) as z:
        assert z.namelist() == r["ficheiros_png"]
        # Uma imagem 4K a sério, e não um ficheiro vazio com o nome certo.
        assert z.getinfo(r["ficheiros_png"][0]).file_size > 100_000


def test_retirar_limpa_as_folhas_da_pasta_de_saida(posto):
    """O edital saiu do ecrã; as folhas não são de ninguém e refazem-se."""
    rid = publicar(posto)
    posto["reg"].mover_estado(rid, reg_mod.RETIRADO, utilizador="ana.abreu")
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])
    assert folhas_na_pasta(posto["cfg"]) == []


def test_repor_um_edital_refaz_as_folhas(posto):
    """Refazer custa 0,36 s. Por isso não há recuperação de arquivo nenhuma —
    era mais caro ir buscar do que voltar a fazer, e punha o ZIP a ser fonte de
    coisas substituíveis."""
    rid = publicar(posto)
    posto["reg"].mover_estado(rid, reg_mod.RETIRADO, utilizador="ana.abreu")
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])
    posto["reg"].mover_estado(rid, reg_mod.PUBLICADO, utilizador="ana.abreu")
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])
    assert len(folhas_na_pasta(posto["cfg"])) == 3


def test_uma_folha_apagada_a_mao_e_refeita_na_publicacao_seguinte(posto):
    """Sem isto, um ficheiro perdido deixava um buraco no ecrã para sempre."""
    publicar(posto)
    os.remove(os.path.join(posto["cfg"]["saida"], folhas_na_pasta(posto["cfg"])[0]))
    agente.publicar_registos(posto["cfg"], posto["reg"], posto["logo"])
    assert len(folhas_na_pasta(posto["cfg"])) == 3


# ---------------------------------------------------------------------------
# O que mais dependia do PNG
# ---------------------------------------------------------------------------
def test_o_zip_do_expositor_leva_as_folhas_e_nao_fica_vazio(posto):
    """Levava os PNG. Sem esta correção passaria a levar só o registo — vazio de
    imagens e sem se queixar, que é a pior forma de uma cópia falhar."""
    publicar(posto)
    zips = [f for f in os.listdir(posto["cfg"]["saida"]) if f.endswith(".zip")]
    assert len(zips) == 1
    with zipfile.ZipFile(os.path.join(posto["cfg"]["saida"], zips[0])) as z:
        nomes = z.namelist()
    assert sum(1 for n in nomes if n.startswith("folha_")) == 3
    assert "slides.json" in nomes
    assert "registo_entrada.json" in nomes


def test_o_conferir_nao_se_queixa_do_logotipo(posto):
    """Um relatório que se queixa sempre da mesma coisa deixa de ser lido."""
    publicar(posto)
    rel = conferencia.conferir(posto["cfg"], posto["reg"])
    assert "logotipo.png" not in rel["png_orfaos"]
    assert rel["png_orfaos"] == []


def test_o_conferir_denuncia_uma_folha_sem_dono(posto):
    """As folhas são JPEG. Enquanto o conferir só olhava para PNG, uma folha
    deixada para trás por um registo apagado não era denunciada por ninguém."""
    publicar(posto)
    orfa = os.path.join(posto["cfg"]["saida"], "folha_9999_01_01.jpg")
    open(orfa, "wb").write(b"nao e de ninguem")
    rel = conferencia.conferir(posto["cfg"], posto["reg"])
    assert "folha_9999_01_01.jpg" in rel["png_orfaos"]


def test_a_exportacao_conta_os_ecras_do_que_esta_afixado(posto):
    """Citava os nomes dos PNG, que num edital afixado já não existem: a coluna
    ficava vazia justamente para os editais que interessam a quem abre a folha."""
    import csv as csv_mod

    import exportacao
    rid = publicar(posto)
    exportacao.exportar(posto["cfg"], posto["reg"])
    indice = os.path.join(posto["cfg"]["exportacao"], "INDICE.csv")
    with open(indice, encoding="utf-8-sig", newline="") as f:
        linhas = list(csv_mod.DictReader(f, delimiter=";"))
    nossa = [x for x in linhas if x["id"] == str(rid)]
    assert nossa, f"o edital publicado não aparece na exportação: {linhas}"
    assert nossa[0]["ecras_na_tv"] == "1"
