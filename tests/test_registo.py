"""
test_registo.py — A máquina de estados e o que ela promete.

É o coração do sistema: define quem pode ir para onde, e é o que impede um edital
de chegar ao ecrã sem alguém o ter visto. Um defeito aqui não dá erro nenhum —
publica-se o que não devia, e só se descobre quando alguém repara no expositor.
"""
from __future__ import annotations

import pytest
import registo as reg_mod
from conftest import META_BOA

TRANSICOES_VALIDAS = [
    (reg_mod.RASCUNHO, reg_mod.VALIDADO),
    (reg_mod.VALIDADO, reg_mod.PUBLICADO),
    (reg_mod.VALIDADO, reg_mod.RASCUNHO),
    (reg_mod.PUBLICADO, reg_mod.RETIRADO),
    (reg_mod.RETIRADO, reg_mod.PUBLICADO),
]

# O que NÃO pode acontecer. A primeira é a que interessa mesmo: publicar sem
# passar pela validação humana derrotaria o propósito inteiro do painel.
TRANSICOES_PROIBIDAS = [
    (reg_mod.RASCUNHO, reg_mod.PUBLICADO),
    (reg_mod.RASCUNHO, reg_mod.RETIRADO),
    (reg_mod.VALIDADO, reg_mod.RETIRADO),
    (reg_mod.PUBLICADO, reg_mod.RASCUNHO),
    (reg_mod.PUBLICADO, reg_mod.VALIDADO),
    (reg_mod.RETIRADO, reg_mod.RASCUNHO),
    (reg_mod.RETIRADO, reg_mod.VALIDADO),
]


def _levar_a(registo, rid, estado):
    """Move um registo até ao estado pedido pelo caminho legítimo."""
    caminho = {
        reg_mod.RASCUNHO: [],
        reg_mod.VALIDADO: [reg_mod.VALIDADO],
        reg_mod.PUBLICADO: [reg_mod.VALIDADO, reg_mod.PUBLICADO],
        reg_mod.RETIRADO: [reg_mod.VALIDADO, reg_mod.PUBLICADO, reg_mod.RETIRADO],
    }[estado]
    for passo in caminho:
        assert registo.mover_estado(rid, passo, utilizador="teste")["ok"]


@pytest.mark.parametrize("de,para", TRANSICOES_VALIDAS, ids=lambda v: v)
def test_transicao_permitida(registo, rascunho, de, para):
    """Os cinco caminhos do fluxo documentado funcionam."""
    _levar_a(registo, rascunho["id"], de)
    res = registo.mover_estado(rascunho["id"], para, utilizador="ana.abreu")
    assert res["ok"], res["erro"]
    assert registo.por_id(rascunho["id"])["estado"] == para


@pytest.mark.parametrize("de,para", TRANSICOES_PROIBIDAS, ids=lambda v: v)
def test_transicao_proibida(registo, rascunho, de, para):
    """Tudo o que está fora do fluxo é recusado, e o estado não se mexe."""
    _levar_a(registo, rascunho["id"], de)
    res = registo.mover_estado(rascunho["id"], para, utilizador="intruso")
    assert not res["ok"]
    assert "não permitida" in res["erro"]
    assert registo.por_id(rascunho["id"])["estado"] == de


def test_nao_valida_sem_data_de_publicacao(registo):
    """Validar exige data de publicação: o rodapé da TV mostra-a sempre.

    A regra existe para o ecrã nunca apresentar um edital sem dizer de quando é —
    o que, num expositor onde a lei conta os dias de afixação, é informação e não
    enfeite.
    """
    meta = dict(META_BOA, data_publicacao=None)
    r = registo.criar_rascunho(ficheiro_origem="x.pdf", hash_ficheiro="h",
                               num_paginas=1, meta=meta)
    res = registo.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana.abreu")
    assert not res["ok"]
    assert "data de publicação" in res["erro"].lower()
    assert registo.por_id(r["id"])["estado"] == reg_mod.RASCUNHO


def test_estado_inexistente_e_recusado(registo, rascunho):
    """Um estado que não existe é recusado como tal, e não tratado como transição."""
    res = registo.mover_estado(rascunho["id"], "arquivado_para_sempre", utilizador="x")
    assert not res["ok"]
    assert "inválido" in res["erro"]


def test_auditoria_regista_quem_e_o_percurso(registo, rascunho):
    """Cada passagem deixa autor, origem e destino no histórico."""
    registo.mover_estado(rascunho["id"], reg_mod.VALIDADO, utilizador="ana.abreu")
    registo.mover_estado(rascunho["id"], reg_mod.PUBLICADO, utilizador="rui.santos",
                         nota="Afixado no expositor do átrio")
    hist = registo.por_id(rascunho["id"])["historico"]
    assert [(h["utilizador"], h["de"], h["para"]) for h in hist] == [
        ("sistema", None, reg_mod.RASCUNHO),
        ("ana.abreu", reg_mod.RASCUNHO, reg_mod.VALIDADO),
        ("rui.santos", reg_mod.VALIDADO, reg_mod.PUBLICADO),
    ]
    assert hist[-1]["nota"] == "Afixado no expositor do átrio"


def test_auditoria_vai_tambem_para_o_jornal(registo, rascunho):
    """O jornal apenas-acrescento recebe os mesmos eventos, com contexto próprio.

    O jornal é lido fora do registo — quem audita abre o .jsonl sozinho — por
    isso cada linha tem de bastar-se: número e assunto vão com o evento.
    """
    registo.mover_estado(rascunho["id"], reg_mod.VALIDADO, utilizador="ana.abreu")
    eventos = registo.jornal.ler_tudo()
    assert [e["para"] for e in eventos] == [reg_mod.RASCUNHO, reg_mod.VALIDADO]
    assert eventos[-1]["utilizador"] == "ana.abreu"
    assert eventos[-1]["numero"] == META_BOA["numero"]
    assert eventos[-1]["id"] == rascunho["id"]


def test_editar_so_toca_na_lista_branca(registo, rascunho):
    """Editar muda os campos do formulário e ignora tudo o resto.

    Sem a lista branca, um pedido malformado (ou mal-intencionado) mudava o
    estado ou o hash por esta via, contornando a máquina de estados inteira.
    """
    registo.editar(rascunho["id"], {
        "assunto": "Assunto corrigido à mão",
        "estado": reg_mod.PUBLICADO,      # não é editável
        "hash": "outro",                  # não é editável
        "id": 9999,                       # não é editável
    }, utilizador="ana.abreu")
    r = registo.por_id(rascunho["id"])
    assert r["assunto"] == "Assunto corrigido à mão"
    assert r["estado"] == reg_mod.RASCUNHO
    assert r["hash"] == "abc123"
    assert r["id"] == rascunho["id"]


def test_corrigir_campo_duvidoso_tira_a_duvida(registo):
    """Um campo lido com pouca confiança deixa de estar assinalado depois de corrigido."""
    meta = dict(META_BOA, confianca={"assunto": 0.2, "numero": 0.95, "data_publicacao": 0.9})
    r = registo.criar_rascunho(ficheiro_origem="cartaz.png", hash_ficheiro="h2",
                               num_paginas=1, meta=meta)
    assert "assunto" in r["campos_duvidosos"]
    registo.editar(r["id"], {"assunto": "Assunto lido pelo funcionário"}, utilizador="ana")
    assert "assunto" not in registo.por_id(r["id"])["campos_duvidosos"]


def test_retirada_automatica_so_apanha_publicados_com_data_vencida(registo):
    """A retirada por data mexe no que está no ecrã e com prazo vencido, e mais nada."""
    ids = {}
    for nome, data, estado in [
        ("vencido", "2020-01-01", reg_mod.PUBLICADO),
        ("por_vencer", "2099-01-01", reg_mod.PUBLICADO),
        ("sem_data", None, reg_mod.PUBLICADO),
        ("vencido_mas_rascunho", "2020-01-01", reg_mod.RASCUNHO),
    ]:
        r = registo.criar_rascunho(ficheiro_origem=f"{nome}.pdf", hash_ficheiro=nome,
                                   num_paginas=1, meta=dict(META_BOA))
        ids[nome] = r["id"]
        _levar_a(registo, r["id"], estado)
        registo.editar(r["id"], {"data_retirada": data}, utilizador="ana")

    assert registo.aplicar_retiradas_automaticas() == [ids["vencido"]]
    assert registo.por_id(ids["vencido"])["estado"] == reg_mod.RETIRADO
    assert registo.por_id(ids["por_vencer"])["estado"] == reg_mod.PUBLICADO
    assert registo.por_id(ids["sem_data"])["estado"] == reg_mod.PUBLICADO
    assert registo.por_id(ids["vencido_mas_rascunho"])["estado"] == reg_mod.RASCUNHO


def test_data_de_retirada_mal_escrita_nao_derruba_o_ciclo(registo, publicado):
    """Uma data impossível é ignorada, e não interrompe a passagem pelos outros."""
    registo.editar(publicado["id"], {"data_retirada": "30 de fevereiro"}, utilizador="ana")
    assert registo.aplicar_retiradas_automaticas() == []
    assert registo.por_id(publicado["id"])["estado"] == reg_mod.PUBLICADO


def test_definir_pngs_persiste(registo, publicado, tmp_path):
    """Os nomes dos PNG compostos ficam mesmo gravados no registo.

    Guarda esta regressão: quando por_estado() passou a devolver cópias, o agente
    continuava a gravar os nomes por mutação do resultado — e portanto não gravava
    nada. O efeito não era um erro, era a imagem 4K a ser recomposta a cada ciclo.
    """
    registo.definir_pngs(publicado["id"], ["202609181200_01_editais_16x9_3d_CLD.png"])
    outro = reg_mod.RegistoEntrada(registo.path)   # relê do disco
    assert outro.por_id(publicado["id"])["ficheiros_png"] == [
        "202609181200_01_editais_16x9_3d_CLD.png"]


def test_todos_devolve_copia_e_nao_a_lista_interna(registo, rascunho):
    """Mexer no que todos() devolve não altera o registo.

    Era uma referência viva: o painel entregava a lista interna ao serializador
    JSON enquanto a thread de vigia lhe fazia append.
    """
    copia = registo.todos()
    copia[0]["assunto"] = "alterado por fora"
    copia.append({"id": 999})
    assert registo.por_id(rascunho["id"])["assunto"] == rascunho["assunto"]
    assert len(registo.todos()) == 1


def test_hash_repetido_e_reconhecido(registo, rascunho):
    """O mesmo conteúdo não entra duas vezes, mesmo com outro nome de ficheiro."""
    assert registo.hash_existe("abc123")
    assert not registo.hash_existe("conteudo_diferente")
