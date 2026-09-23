"""
test_progresso.py — O painel passa a dizer o que está a fazer.

Compor os ecrãs de um edital demora. Um documento de vinte páginas leva dezenas
de segundos entre carregar em «Publicar» e a imagem aparecer na televisão, e
durante esse tempo o painel não dizia nada. Quem estava ao teclado tinha duas
hipóteses igualmente más: esperar sem saber se alguma coisa estava a acontecer,
ou carregar outra vez — que é o que as pessoas fazem, e com razão.
"""
from __future__ import annotations

import threading

import pytest

import progresso


@pytest.fixture(autouse=True)
def limpo():
    progresso.parado()
    yield
    progresso.parado()


def test_em_repouso_nao_ha_frase():
    """Uma faixa que está sempre visível deixa de querer dizer alguma coisa."""
    assert progresso.frase() == ""
    assert progresso.actual()["fase"] == progresso.NADA


def test_a_ler_diz_o_ficheiro_e_a_pagina():
    progresso.a_ler("edital_2026-0050.pdf", 3, 12)
    f = progresso.frase()
    assert "edital_2026-0050.pdf" in f
    assert "3 de 12" in f


def test_a_compor_diz_o_ecra():
    progresso.a_compor(7, "edital.pdf", 2, 4)
    assert "2 de 4" in progresso.frase()
    assert progresso.actual()["registo"] == 7


def test_a_publicar_fala_da_televisao():
    progresso.a_publicar(5, 9)
    assert "televisão" in progresso.frase()
    assert "5 de 9" in progresso.frase()


def test_sem_total_nao_se_inventa_uma_contagem():
    """No arranque da leitura ainda não se sabe quantas páginas há."""
    progresso.a_ler("edital.pdf", 0, 0)
    assert "de 0" not in progresso.frase()
    assert "edital.pdf" in progresso.frase()


def test_substitui_em_vez_de_acumular():
    """O que interessa é o agora; o histórico está no jornal de auditoria."""
    progresso.a_ler("a.pdf", 1, 2)
    progresso.a_compor(1, "b.pdf", 1, 1)
    e = progresso.actual()
    assert e["fase"] == progresso.A_COMPOR
    assert "ficheiro" in e and e["ficheiro"] == "b.pdf"
    assert "a.pdf" not in progresso.frase()


def test_actual_devolve_uma_copia():
    """O painel serializa isto enquanto a thread de trabalho lhe pode mexer.

    Ler e escrever a mesma estrutura em threads diferentes sem lock é a forma de
    ter um erro que só aparece em produção. Já aconteceu neste projeto, com a
    lista de registos.
    """
    progresso.a_ler("edital.pdf", 1, 3)
    copia = progresso.actual()
    copia["ficheiro"] = "mexido"
    assert progresso.actual()["ficheiro"] == "edital.pdf"


def test_aguenta_threads_a_escrever_e_a_ler():
    """Não prova ausência de corridas — nenhum teste prova. Apanha o óbvio."""
    erros = []

    def escrever():
        for i in range(200):
            progresso.a_ler("edital.pdf", i, 200)

    def ler():
        try:
            for _ in range(200):
                progresso.frase()
                progresso.actual()
        except Exception as ex:      # noqa: BLE001 - queremos qualquer falha
            erros.append(ex)

    ts = [threading.Thread(target=escrever), threading.Thread(target=ler),
          threading.Thread(target=escrever), threading.Thread(target=ler)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert erros == []


# ---------------------------------------------------------------------------
# A faixa tem de APAGAR-SE quando o trabalho acaba
#
# Os testes acima exercitam o módulo sozinho, e estavam todos verdes enquanto o
# `parado()` não era chamado de lado nenhum. A faixa acendia-se no primeiro
# documento e ficava acesa para sempre, a anunciar um trabalho terminado — e o
# painel, que sonda de três em três segundos enquanto ela estiver visível,
# ficava preso nesse ritmo até alguém reiniciar o serviço.
#
# A lição é a do ponto de chamada: uma função testada não é uma função ligada.
# Estes testes atravessam o agente, que é onde o defeito vivia.
# ---------------------------------------------------------------------------
@pytest.fixture
def posto(tmp_path):
    """Uma instalação com um PDF de duas páginas à espera na entrada."""
    import os

    import fitz

    import agente
    import registo as reg_mod
    # Parte-se da configuração REAL e só se trocam os caminhos: uma configuração
    # montada à mão no teste fica desactualizada em silêncio assim que o agente
    # ganha uma chave nova, e o teste rebenta longe da causa.
    cfg = dict(agente.CONFIG)
    for chave, valor in agente.CONFIG.items():
        if isinstance(valor, str) and valor.startswith(agente.BASE):
            cfg[chave] = str(tmp_path / os.path.relpath(valor, agente.BASE))
    for nome in ("entrada", "saida", "previas", "originais", "trabalho",
                 "fundos", "arquivo", "exportacao"):
        os.makedirs(cfg[nome], exist_ok=True)
    cfg["tratados"] = os.path.join(cfg["entrada"], "tratados")
    os.makedirs(cfg["tratados"], exist_ok=True)

    d = fitz.open()
    for i in (1, 2):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((70, 140), f"EDITAL 2026-0050 pagina {i}", fontsize=24)
    d.save(os.path.join(cfg["entrada"], "edital.pdf"))
    d.close()
    return {"cfg": cfg, "reg": reg_mod.RegistoEntrada(cfg["registo_entrada"])}


def publicar(reg, rid):
    """Leva um rascunho até PUBLICADO. A data é obrigatória para validar."""
    import registo as reg_mod
    reg.editar(rid, {"data_publicacao": "2026-06-29"}, utilizador="ana.abreu")
    assert reg.mover_estado(rid, reg_mod.VALIDADO, utilizador="ana.abreu")["ok"]
    assert reg.mover_estado(rid, reg_mod.PUBLICADO, utilizador="ana.abreu")["ok"]


def test_a_faixa_apaga_se_quando_a_leitura_acaba(posto):
    """Ficava a dizer «A ler ... (2 de 2)» para sempre."""
    import agente
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert progresso.frase() == ""


def test_a_faixa_apaga_se_mesmo_quando_a_leitura_rebenta(posto, monkeypatch):
    """O finally existe para isto: um erro não pode deixar a faixa acesa."""
    import agente
    import documentos as doc_mod

    def rebenta(*_a, **_k):
        raise OSError("disco cheio a meio da leitura")

    monkeypatch.setattr(doc_mod, "ler_metadados", rebenta)
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert progresso.frase() == ""


def test_a_faixa_apaga_se_quando_a_publicacao_acaba(posto):
    """O mesmo no outro extremo: composição feita, faixa apagada."""
    import agente
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    publicar(posto["reg"], posto["reg"].todos()[0]["id"])
    agente.publicar_registos(posto["cfg"], posto["reg"], None)
    assert progresso.frase() == ""


def test_a_contagem_da_publicacao_chega_ao_fim(posto, monkeypatch):
    """Com enumerate a começar em zero abria em «0 de 1» e parava aí.

    Quem estava a olhar via o último edital eternamente por fazer. Espia-se a
    chamada dentro do agente e não o padrão do enumerate: um teste que repete
    o enumerate do código passa com o código errado, que é o que este fazia.
    """
    import agente
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    publicar(posto["reg"], posto["reg"].todos()[0]["id"])

    vistas = []
    real = progresso.a_publicar
    monkeypatch.setattr(agente.progresso, "a_publicar",
                        lambda f, t: (vistas.append((f, t)), real(f, t))[1])
    agente.publicar_registos(posto["cfg"], posto["reg"], None)
    assert vistas, "a publicação não anunciou nada"
    assert vistas[-1][0] == vistas[-1][1], f"parou em {vistas[-1][0]} de {vistas[-1][1]}"


# ---------------------------------------------------------------------------
# Um ecrã que falha a meio não deixa lixo na pasta de saída
# ---------------------------------------------------------------------------
def test_uma_composicao_falhada_nao_deixa_ecras_orfaos(posto, monkeypatch):
    """Compor passou a ser ecrã a ecrã, com a leitura de cada um a poder falhar.

    Falhando no terceiro, os dois primeiros já estão gravados e o registo fica
    sem PNG nenhum — e esses dois ficheiros não são de ninguém: a televisão não
    os mostra, o arquivo não os conhece e o --conferir não dá por eles, porque
    só olha do registo para o disco e não ao contrário.
    """
    import os

    import fitz

    import agente

    # Um edital de sete páginas verticais dá três ecrãs.
    d = fitz.open()
    for i in range(7):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((70, 140), f"EDITAL 2026-0051 p{i}", fontsize=24)
    d.save(os.path.join(posto["cfg"]["entrada"], "grande.pdf"))
    d.close()
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    r = [x for x in posto["reg"].todos() if x["ficheiro_origem"] == "grande.pdf"][0]
    publicar(posto["reg"], r["id"])

    real = agente.doc.paginas_uma_a_uma
    contador = {"n": 0}

    def falha_ao_terceiro(*a, **k):
        contador["n"] += 1
        if contador["n"] == 3:
            raise OSError("o original desapareceu a meio da composição")
        yield from real(*a, **k)

    monkeypatch.setattr(agente.doc, "paginas_uma_a_uma", falha_ao_terceiro)
    nomes = agente._compor_edital(posto["cfg"], posto["reg"].por_id(r["id"]), None)
    assert nomes == []
    sobras = [f for f in os.listdir(posto["cfg"]["saida"]) if f.endswith(".png")]
    assert sobras == [], f"ficaram ecrãs órfãos na pasta de saída: {sobras}"


def test_a_faixa_apaga_se_mesmo_quando_a_publicacao_rebenta(posto, monkeypatch):
    """O mesmo finally do outro lado: escrever a página da TV pode falhar."""
    import agente
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    publicar(posto["reg"], posto["reg"].todos()[0]["id"])

    def rebenta(*_a, **_k):
        raise OSError("disco cheio a escrever a página da televisão")

    monkeypatch.setattr(agente, "_escrever_pagina_tv", rebenta)
    with pytest.raises(OSError):
        agente.publicar_registos(posto["cfg"], posto["reg"], None)
    assert progresso.frase() == ""
