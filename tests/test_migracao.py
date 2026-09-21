"""
test_migracao.py — Ninguém perde editais quando o modelo antigo sai.

Apagar o caminho de publicação automática é a parte fácil. A parte que tem de
estar certa é esta: uma instalação que já andava a publicar pelo modelo antigo
não pode acordar sem os seus editais, nem com datas erradas, nem com uma
certidão que afirme coisas que não aconteceram.

Os testes cobrem as três coisas que a migração tem de acertar — reagrupar os
ecrãs no edital a que pertencem, reconstruir o percurso de estados, e datar a
afixação no passado — e as três que ela tem de assumir sem inventar: quem
afixou, a hora exata, e o tipo de documento.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

import migracao
import prazos as pr
import registo as reg_mod

# Um editais.json como o modelo antigo o escrevia: um registo por ECRÃ.
# O edital 2026-0017 ocupava dois ecrãs; o 2026-0018, um só.
EDITAIS_ANTIGOS = {
    "editais": [
        {"indice": 1, "ficheiro_origem": "edital_17.pdf",
         "ficheiro_png": "202606290914_01_deliberacoes_p1de2_16x9_3d_CLD.png",
         "assunto": "DELIBERAÇÕES COM EFICÁCIA EXTERNA", "numero": "2026-0017",
         "entidade": "ASSEMBLEIA MUNICIPAL", "data_publicacao": "2026-06-29",
         "parte": 1, "total_partes": 2, "folhas_neste_ecra": 3,
         "processado_em": "2026-06-29T09:14:02"},
        {"indice": 2, "ficheiro_origem": "edital_17.pdf",
         "ficheiro_png": "202606290914_02_deliberacoes_p2de2_16x9_3d_CLD.png",
         "assunto": "DELIBERAÇÕES COM EFICÁCIA EXTERNA", "numero": "2026-0017",
         "entidade": "ASSEMBLEIA MUNICIPAL", "data_publicacao": "2026-06-29",
         "parte": 2, "total_partes": 2, "folhas_neste_ecra": 2,
         "processado_em": "2026-06-29T09:14:48"},
        {"indice": 3, "ficheiro_origem": "aviso_agua.pdf",
         "ficheiro_png": "202607011030_03_corte_de_agua_16x9_3d_CLD.png",
         "assunto": "CORTE DE ÁGUA NA RUA DIREITA", "numero": "2026-0018",
         "entidade": "CÂMARA MUNICIPAL", "data_publicacao": "2026-07-01",
         "parte": 1, "total_partes": 1, "folhas_neste_ecra": 1,
         "processado_em": "2026-07-01T10:30:11"},
    ]
}

ESTADO_ANTIGO = {"processados": {
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0": {
        "ficheiro": "edital_17.pdf", "paginas": 5,
        "em": "2026-06-29T09:14:00", "ecras": []},
    "0f9e8d7c6b5a4938271605f4e3d2c1b0a9887766": {
        "ficheiro": "aviso_agua.pdf", "paginas": 1,
        "em": "2026-07-01T10:30:00", "ecras": []},
}}


@pytest.fixture
def instalacao(tmp_path):
    """Uma instalação com dados do modelo antigo, pronta a migrar."""
    (tmp_path / "editais.json").write_text(
        json.dumps(EDITAIS_ANTIGOS, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "estado.json").write_text(
        json.dumps(ESTADO_ANTIGO, ensure_ascii=False), encoding="utf-8")
    # Um com data já vencida, outro ainda por vencer.
    vencida = (date.today() - timedelta(days=30)).isoformat()
    futura = (date.today() + timedelta(days=30)).isoformat()
    (tmp_path / "retiradas.txt").write_text(
        f"# cabeçalho de ajuda que deve ser ignorado\n"
        f"2026-0017 = {vencida}\n"
        f"2026-0018 = {futura}\n", encoding="utf-8")
    cfg = {"registo_antigo": str(tmp_path / "editais.json"),
           "estado_antigo": str(tmp_path / "estado.json"),
           "retiradas_antigo": str(tmp_path / "retiradas.txt")}
    reg = reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))
    return {"cfg": cfg, "reg": reg, "pasta": tmp_path,
            "vencida": vencida, "futura": futura}


# ---------------------------------------------------------------------------
# Deteção
# ---------------------------------------------------------------------------
def test_deteta_que_ha_o_que_migrar(instalacao):
    assert migracao.precisa_de_migrar(instalacao["cfg"])


def test_instalacao_nova_nao_precisa(tmp_path):
    """Sem ficheiros antigos, a migração não faz nada nem se queixa."""
    assert not migracao.precisa_de_migrar({"registo_antigo": str(tmp_path / "nada.json")})


def test_editais_json_vazio_nao_precisa(tmp_path):
    """Um ficheiro que existe mas está vazio também não é trabalho."""
    (tmp_path / "editais.json").write_text('{"editais": []}', encoding="utf-8")
    assert not migracao.precisa_de_migrar({"registo_antigo": str(tmp_path / "editais.json")})


# ---------------------------------------------------------------------------
# Reagrupamento: o modelo antigo guardava um registo por ECRÃ
# ---------------------------------------------------------------------------
def test_os_ecras_voltam_a_ser_um_edital(instalacao):
    """Três entradas no modelo antigo são dois editais, não três."""
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 2
    assert len(instalacao["reg"].todos()) == 2


def test_o_edital_de_dois_ecras_mantem_os_dois_pngs(instalacao):
    """Nenhuma imagem se perde no reagrupamento."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["ficheiros_png"] == [
        "202606290914_01_deliberacoes_p1de2_16x9_3d_CLD.png",
        "202606290914_02_deliberacoes_p2de2_16x9_3d_CLD.png"]
    assert edital["num_paginas"] == 5          # 3 + 2 folhas


def test_as_partes_ficam_pela_ordem_certa(instalacao):
    """Parte 1 antes da parte 2, mesmo que venham baralhadas do ficheiro."""
    baralhado = {"editais": list(reversed(EDITAIS_ANTIGOS["editais"]))}
    (instalacao["pasta"] / "editais.json").write_text(
        json.dumps(baralhado, ensure_ascii=False), encoding="utf-8")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["ficheiros_png"][0].endswith("p1de2_16x9_3d_CLD.png")


def test_os_metadados_sobrevivem(instalacao):
    """Assunto, número, entidade e data de publicação passam tal e qual."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["assunto"] == "DELIBERAÇÕES COM EFICÁCIA EXTERNA"
    assert edital["entidade"] == "ASSEMBLEIA MUNICIPAL"
    assert edital["data_publicacao"] == "2026-06-29"


def test_o_hash_vem_do_estado_antigo(instalacao):
    """A impressão digital é recuperada, para o documento não ser reingerido."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["hash"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    assert instalacao["reg"].hash_existe(edital["hash"])


def test_sem_hash_conhecido_gera_um_estavel(instalacao):
    """Um edital sem entrada no estado.json não fica com o campo vazio."""
    (instalacao["pasta"] / "estado.json").write_text(
        '{"processados": {}}', encoding="utf-8")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    for edital in instalacao["reg"].todos():
        assert edital["hash"].startswith("migrado:")


# ---------------------------------------------------------------------------
# Estados e datas
# ---------------------------------------------------------------------------
def test_o_que_estava_no_ecra_fica_publicado(instalacao):
    """Um edital com retirada futura continua no expositor."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0018")
    assert edital["estado"] == reg_mod.PUBLICADO
    assert edital["data_retirada"] == instalacao["futura"]


def test_o_que_ja_tinha_saido_fica_retirado(instalacao):
    """Uma retirada vencida não pode ressuscitar o edital no ecrã."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["estado"] == reg_mod.RETIRADO
    assert edital["data_retirada"] == instalacao["vencida"]


def test_a_afixacao_e_datada_no_passado(instalacao):
    """A certidão de um edital de junho não pode dizer que foi afixado hoje.

    É o instante do primeiro ecrã composto — o mais próximo que os dados
    antigos permitem — e não a hora em que a migração correu.
    """
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["afixado_em"] == "2026-06-29T09:14:02"
    assert edital["afixado_por"] == migracao.AUTOR


def test_o_percurso_de_estados_fica_no_historico(instalacao):
    """O edital migrado tem o mesmo tipo de histórico que um normal."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    percurso = [(h["de"], h["para"]) for h in edital["historico"]]
    assert (None, reg_mod.RASCUNHO) in percurso
    assert (reg_mod.RASCUNHO, reg_mod.VALIDADO) in percurso
    assert (reg_mod.VALIDADO, reg_mod.PUBLICADO) in percurso
    assert (reg_mod.PUBLICADO, reg_mod.RETIRADO) in percurso


def test_a_correcao_da_data_e_ela_propria_auditavel(instalacao):
    """Reescrever o instante de afixação deixa rasto, com o valor anterior."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    notas = " ".join(h["nota"] for h in edital["historico"])
    assert "Instante de afixação corrigido" in notas


def test_tudo_vai_para_o_jornal_de_auditoria(instalacao):
    """Os eventos da migração ficam no trilho apenas-acrescento, como os outros."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    eventos = instalacao["reg"].jornal.ler_tudo()
    assert eventos, "a migração não deixou rasto no jornal"
    assert all(e["utilizador"] == migracao.AUTOR for e in eventos)


# ---------------------------------------------------------------------------
# O que a migração assume sem inventar
# ---------------------------------------------------------------------------
def test_o_autor_e_declarado_como_migracao(instalacao):
    """Não havia contas no modelo antigo. Não se inventa um nome.

    Quem ler a certidão de um edital migrado vê 'migracao' e percebe que o ato
    é anterior às contas nominais — o que é a verdade.
    """
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    for edital in instalacao["reg"].todos():
        assert edital["afixado_por"] == "migracao"


def test_o_tipo_fica_por_escolher(instalacao):
    """O modelo antigo não tinha tipos: fica o de omissão, sem prazo verificado."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    for edital in instalacao["reg"].todos():
        assert edital["tipo"] == pr.TIPO_POR_OMISSAO


# ---------------------------------------------------------------------------
# Robustez e idempotência
# ---------------------------------------------------------------------------
def test_nao_migra_duas_vezes(instalacao):
    """Correr outra vez não duplica nada — os ficheiros de origem foram renomeados."""
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 2
    assert not migracao.precisa_de_migrar(instalacao["cfg"])
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 0
    assert len(instalacao["reg"].todos()) == 2


def test_os_ficheiros_antigos_sao_renomeados_e_nao_apagados(instalacao):
    """Se a migração interpretou algo mal, os dados de origem continuam lá."""
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    for nome in ("editais.json", "estado.json", "retiradas.txt"):
        assert not (instalacao["pasta"] / nome).exists()
        assert (instalacao["pasta"] / (nome + migracao.SUFIXO_MIGRADO)).exists()


def test_sem_retiradas_txt_migra_na_mesma(instalacao):
    """A ausência do ficheiro de datas não impede a migração."""
    (instalacao["pasta"] / "retiradas.txt").unlink()
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 2
    for edital in instalacao["reg"].todos():
        assert edital["estado"] == reg_mod.PUBLICADO
        assert edital["data_retirada"] is None


@pytest.mark.parametrize("conteudo", [
    "",
    "# só comentários\n# e mais nada\n",
    "linha sem separador nenhum\n",
    "2026-0017 = 30 de fevereiro\n",
    "2026-0017;2026-12-31\n",          # ';' também é separador
])
def test_retiradas_txt_estranho_nao_rebenta(instalacao, conteudo):
    """O ficheiro era editado à mão: tem de se aguentar a tudo."""
    (instalacao["pasta"] / "retiradas.txt").write_text(conteudo, encoding="utf-8")
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 2


def test_retirada_encontrada_pelo_assunto(instalacao):
    """Quem escreveu o assunto em vez do número também é atendido."""
    futura = (date.today() + timedelta(days=10)).isoformat()
    (instalacao["pasta"] / "retiradas.txt").write_text(
        f"DELIBERAÇÕES COM EFICÁCIA EXTERNA = {futura}\n", encoding="utf-8")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])
    edital = next(r for r in instalacao["reg"].todos() if r["numero"] == "2026-0017")
    assert edital["data_retirada"] == futura


def test_editais_sem_numero_agrupam_pelo_assunto(instalacao):
    """Nem todos os editais antigos tinham número lido."""
    sem_numero = {"editais": [dict(e, numero="") for e in EDITAIS_ANTIGOS["editais"]]}
    (instalacao["pasta"] / "editais.json").write_text(
        json.dumps(sem_numero, ensure_ascii=False), encoding="utf-8")
    assert migracao.migrar(instalacao["cfg"], instalacao["reg"]) == 2


def test_agrupar_preserva_a_ordem_de_chegada():
    """Os editais saem pela ordem em que apareciam no ficheiro."""
    grupos = migracao.agrupar_por_edital(EDITAIS_ANTIGOS["editais"])
    assert [g[0]["numero"] for g in grupos] == ["2026-0017", "2026-0018"]
    assert sum(len(g) for g in grupos) == 3


# ---------------------------------------------------------------------------
# Os dois defeitos que a revisão do PR #4 apanhou
# ---------------------------------------------------------------------------
def test_sem_data_de_publicacao_fica_rascunho_e_nao_publicado_em_silencio(instalacao):
    """O caso que fazia a migração mentir.

    `mover_estado` recusa VALIDADO sem data de publicação — e RECUSA
    devolvendo `{"ok": False}`, não levantando exceção. A migração ignorava a
    resposta, tentava a seguir PUBLICADO a partir de RASCUNHO (transição que
    também não existe, também silenciosa), contava o edital como migrado e
    arquivava os ficheiros de origem. Resultado: um edital que estava no
    expositor desaparecia dele, o posto era informado de que tinha sido
    migrado, e ninguém ficava a saber.

    O comportamento certo não é publicar à força: a data é obrigatória por uma
    razão (o rodapé da TV mostra-a). É ficar em rascunho, à espera de quem
    saiba a data — mas dizê-lo em voz alta.
    """
    dados = json.loads(json.dumps(EDITAIS_ANTIGOS))
    for e in dados["editais"]:
        if e["numero"] == "2026-0018":
            e["data_publicacao"] = ""
    (instalacao["pasta"] / "editais.json").write_text(
        json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    resultado = migracao.migrar(instalacao["cfg"], instalacao["reg"])

    por_numero = {r["numero"]: r for r in instalacao["reg"].todos()}
    assert len(por_numero) == 2, "nenhum edital se perde, mesmo sem data"
    assert por_numero["2026-0017"]["estado"] == reg_mod.RETIRADO
    assert por_numero["2026-0018"]["estado"] == reg_mod.RASCUNHO, (
        "sem data de publicação o edital tem de ficar à espera de uma pessoa")
    assert resultado == 2, "conta-se como migrado — o registo existe"


def test_o_que_ficou_por_completar_e_dito_em_voz_alta(instalacao, caplog):
    """Um rascunho inesperado no arranque tem de aparecer no registo técnico."""
    import logging
    dados = json.loads(json.dumps(EDITAIS_ANTIGOS))
    for e in dados["editais"]:
        if e["numero"] == "2026-0018":
            e["data_publicacao"] = None
    (instalacao["pasta"] / "editais.json").write_text(
        json.dumps(dados, ensure_ascii=False), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        migracao.migrar(instalacao["cfg"], instalacao["reg"])

    texto = caplog.text.lower()
    assert "2026-0018" in texto
    assert "data de publica" in texto


def test_o_original_ainda_na_pasta_entra_no_arquivo_imutavel(instalacao):
    """O SHA-256 recupera-se do ficheiro, não se finge que o SHA-1 serve.

    O modelo antigo só guardava o SHA-1 (identidade para não reingerir o mesmo
    documento). O arquivo imutável da Onda 2 endereça por SHA-256, e a certidão
    cita-o como «Resumo do original». Enquanto o original estiver na pasta de
    entrada, é calculável — e se não se calcular aqui, nunca mais se calcula:
    o edital fica para sempre sem forma de recuperar o documento que afixou.
    """
    import hashlib

    import originais as orig

    entrada = instalacao["pasta"] / "entrada"
    entrada.mkdir()
    conteudo = b"%PDF-1.4 um edital que ainda esta na pasta de entrada"
    (entrada / "edital_17.pdf").write_bytes(conteudo)
    esperado = hashlib.sha256(conteudo).hexdigest()

    instalacao["cfg"]["entrada"] = str(entrada)
    instalacao["cfg"]["originais"] = str(instalacao["pasta"] / "originais")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])

    por_numero = {r["numero"]: r for r in instalacao["reg"].todos()}
    assert por_numero["2026-0017"]["sha256"] == esperado
    assert orig.conferir(instalacao["cfg"]["originais"], esperado, ".pdf"), (
        "o original tem de ficar no arquivo imutável, não só o resumo no registo")
    # O SHA-1 antigo continua a ser a identidade de deduplicação: é o que o
    # caminho de entrada ainda calcula, e trocá-lo reingeria tudo como novo.
    assert por_numero["2026-0017"]["hash"] == (
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0")


def test_sem_o_original_na_pasta_o_resumo_fica_vazio_e_nao_inventado(instalacao):
    """Não havendo ficheiro, não há resumo. O campo fica vazio, não com lixo.

    Punha-se aqui o SHA-1 antigo, ou a cadeia sintética `migrado:...`, e a
    certidão imprimia-a debaixo de «Resumo do original» como se fosse um
    resumo do documento. Não é, e um documento que afirma o que não sabe vale
    menos do que um que se cala.
    """
    instalacao["cfg"]["entrada"] = str(instalacao["pasta"] / "entrada-vazia")
    instalacao["cfg"]["originais"] = str(instalacao["pasta"] / "originais")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])

    for r in instalacao["reg"].todos():
        assert r["sha256"] == ""
        assert not r["sha256"].startswith("migrado:")


def test_a_certidao_de_um_migrado_nao_cita_a_chave_sintetica(instalacao):
    """Sem SHA-1 conhecido inventa-se uma chave de deduplicação — que não é
    um resumo, e não pode aparecer na certidão como se fosse."""
    import certidao as cert

    (instalacao["pasta"] / "estado.json").write_text(
        '{"processados": {}}', encoding="utf-8")
    migracao.migrar(instalacao["cfg"], instalacao["reg"])

    for r in instalacao["reg"].todos():
        assert r["hash"].startswith("migrado:")
        assert "migrado:" not in cert.factos(r)["hash_original"]
