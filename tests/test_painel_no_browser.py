"""
test_painel_no_browser.py — O painel a sério, num browser, onde o defeito se via.

Os testes de `test_retirada_automatica.py` leem o `painel.html` como texto: dizem
que o campo já não é escrito com a proposta e que há um botão. Não dizem o que
interessa, que é o que um Guardar envia. Isso só se vê com o JavaScript a correr,
e é por isso que este ficheiro existe.

O defeito que guarda é da classe número um do AGENTS.md. Com o campo da retirada
pré-preenchido, quem abrisse o registo para corrigir o assunto e carregasse em
Guardar enviava a proposta como se a tivesse escrito. A publicação deixava de a
recalcular da afixação real, e um edital podia sair do ecrã antes do prazo.

Marcados como `navegador`, como os da televisão: correm no trabalho da CI que tem
o Chromium, e à mão com `pytest -m navegador`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import painel as painel_mod
import prazos as pr
import registo as reg_mod
import utilizadores as utl
from conftest import META_BOA

pytestmark = pytest.mark.navegador

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

PAINEL_HTML = Path(__file__).resolve().parents[1] / "lib" / "painel.html"
SENHA = "senha-de-teste-comprida-1"
DELIBERACAO = "deliberacao_orgao_autarquico"    # 5 dias mínimos, Lei 75/2013


@pytest.fixture
def painel(tmp_path):
    """O painel a correr com o painel.html verdadeiro e uma deliberação por validar.

    A deliberação tem data de publicação e tipo com prazo, por isso o servidor
    manda-lhe uma `retirada_proposta`. É essa proposta que não pode ir parar ao
    campo sem ninguém a pedir.
    """
    contas = utl.Utilizadores(str(tmp_path / "utilizadores.json"))
    contas.criar("ana.abreu", SENHA, nome_completo="Ana Abreu",
                 papel=utl.ADMINISTRADOR)
    reg = reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))
    r = reg.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                           num_paginas=1, meta=dict(META_BOA))
    reg.editar(r["id"], {"tipo": DELIBERACAO}, utilizador="ana.abreu")
    proposta = pr.propor_retirada(DELIBERACAO, META_BOA["data_publicacao"])
    assert proposta, "a deliberação devia ter prazo, senão o teste não prova nada"

    cfg = {"saida": str(tmp_path), "previas": str(tmp_path),
           "arquivo": str(tmp_path), "municipio": "Município de Teste",
           "intervalo_watch": 30}
    srv = painel_mod.PainelServer(reg, cfg, republicar_callback=lambda: None,
                                  painel_html_path=str(PAINEL_HTML),
                                  contas=contas,
                                  saude_callback=lambda: {"ok": True})
    porta = srv.iniciar(host="127.0.0.1", porta=0, bloquear=False)
    base = f"http://127.0.0.1:{porta}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/saude", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            pass
    yield {"reg": reg, "rid": r["id"], "base": base, "proposta": proposta}
    srv._httpd.shutdown()


@pytest.fixture
def pagina(painel):
    """O painel aberto no ecrã de validação, já com a sessão iniciada."""
    executavel = os.environ.get("CHROMIUM_PARA_TESTES") or None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=executavel)
        ctx = b.new_context()
        base = painel["base"]
        # A sessão abre-se pelo mesmo pedido que a página de entrada faz, e o
        # cookie fica no contexto, partilhado com a página.
        resp = ctx.request.post(base + "/api/entrar",
                                data=json.dumps({"utilizador": "ana.abreu",
                                                 "senha": SENHA}),
                                headers={"Content-Type": "application/json",
                                         "X-Painel-Pedido": "1",
                                         "Origin": base})
        assert resp.status == 200, resp.text()
        pg = ctx.new_page()
        pg.goto(base + "/")
        pg.click('[data-sec="validar"]')
        pg.wait_for_selector("#f-data_retirada")
        yield pg
        b.close()


def _guardar(pg):
    """Carrega em Guardar e espera pelo pedido de edição, que é o que conta."""
    with pg.expect_response(lambda r: r.url.endswith("/api/editar")) as resp:
        pg.click('.acoes [data-acao="guardar"]')
    assert resp.value.ok


def test_guardar_outra_coisa_nao_grava_a_proposta(painel, pagina):
    """Corrigir o assunto e guardar deixa a data de retirada em branco.

    É o caminho exato do defeito. Ninguém tocou na data. Contra o código
    anterior, o campo vinha com a proposta escrita, e o Guardar mandava-a.
    """
    campo = pagina.locator("#f-data_retirada")
    assert campo.input_value() == "", "o campo vem com a proposta escrita"
    assert painel["proposta"] in pagina.locator(".nota-proposta").inner_text()

    pagina.fill("#f-assunto", "ASSUNTO CORRIGIDO POR QUEM ESTÁ AO TECLADO")
    _guardar(pagina)

    r = painel["reg"].por_id(painel["rid"])
    assert r["assunto"] == "ASSUNTO CORRIGIDO POR QUEM ESTÁ AO TECLADO"
    assert not r.get("data_retirada"), (
        "o Guardar gravou a proposta como se alguém a tivesse escrito: a "
        "publicação já não a recalcula da afixação real")


def test_aceitar_a_proposta_e_um_ato_de_quem_esta_ao_teclado(painel, pagina):
    """O botão enche o campo, e só depois disso a data fica gravada."""
    pagina.click(".btn-proposta")
    assert pagina.locator("#f-data_retirada").input_value() == painel["proposta"]

    _guardar(pagina)

    assert painel["reg"].por_id(painel["rid"])["data_retirada"] == painel["proposta"]
