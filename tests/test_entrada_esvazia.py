"""
test_entrada_esvazia.py — A pasta de entrada deixa de ser um pântano.

Os ficheiros ficavam lá para sempre depois de recebidos. Ao fim de umas semanas
ninguém conseguia responder a olho à pergunta que interessa — «o que é que
chegou de novo?» — e essa pergunta é metade do trabalho do posto.

O que torna isto seguro é a ordem, e é ela que os testes fixam: quando o
ficheiro sai da pasta de entrada, já há uma cópia idêntica ao byte em
`originais/`, endereçada pelo SHA-256, e é dela que a composição lê. Mover e não
apagar, como em todo o resto do projeto.
"""
from __future__ import annotations

import os

import pytest

import agente
import originais as orig
import registo as reg_mod


@pytest.fixture
def posto(tmp_path):
    """Uma instalação com um PDF de uma página à espera na entrada."""
    import fitz
    cfg = {}
    for nome in ("entrada", "saida", "previas", "originais", "trabalho", "fundos"):
        (tmp_path / nome).mkdir(parents=True, exist_ok=True)
        cfg[nome] = str(tmp_path / nome)
    cfg["tratados"] = str(tmp_path / "entrada" / "tratados")
    os.makedirs(cfg["tratados"], exist_ok=True)
    cfg["registo_entrada"] = str(tmp_path / "registo_entrada.json")

    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((70, 140), "EDITAL 2026-0050", fontsize=24)
    d.save(os.path.join(cfg["entrada"], "edital.pdf"))
    d.close()

    reg = reg_mod.RegistoEntrada(cfg["registo_entrada"])
    return {"cfg": cfg, "reg": reg, "pasta": tmp_path}


def test_o_ficheiro_sai_da_entrada(posto):
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert "edital.pdf" not in os.listdir(posto["cfg"]["entrada"])
    assert "edital.pdf" in os.listdir(posto["cfg"]["tratados"])


def test_o_original_ja_esta_no_arquivo_quando_sai(posto):
    """A ordem é o que torna a mudança segura, e não o contrário."""
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    r = posto["reg"].todos()[0]
    assert r["sha256"]
    assert orig.procurar(posto["cfg"]["originais"], r["sha256"], ".pdf")


def test_mover_e_nao_apagar(posto):
    """Se a leitura correu mal, o ficheiro de origem continua ali ao lado."""
    antes = (posto["pasta"] / "entrada" / "edital.pdf").read_bytes()
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    depois = (posto["pasta"] / "entrada" / "tratados" / "edital.pdf").read_bytes()
    assert depois == antes


def test_a_varredura_seguinte_nao_volta_a_ler_o_que_esta_em_tratados(posto):
    """A subpasta não é varrida, e o hash já está registado de qualquer forma."""
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None) == 1
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None) == 0
    assert len(posto["reg"].todos()) == 1


def test_dois_ficheiros_com_o_mesmo_nome_nao_se_apagam(posto):
    """Dois editais podem chegar com o mesmo nome em meses diferentes."""
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    # Um segundo documento, conteúdo diferente, mesmo nome.
    import fitz
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((70, 140), "OUTRO EDITAL, MESMO NOME", fontsize=24)
    d.save(os.path.join(posto["cfg"]["entrada"], "edital.pdf"))
    d.close()
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    assert len(os.listdir(posto["cfg"]["tratados"])) == 2
    assert len(posto["reg"].todos()) == 2


# --- a pasta de entrada partilhada pela rede --------------------------------

def test_um_ficheiro_a_meio_da_copia_espera_pela_volta_seguinte(posto):
    """Um ficheiro alterado há instantes não é lido: pode estar a meio da cópia.

    Com a entrada partilhada por Samba, a vigia pode passar enquanto um posto
    Windows ainda copia o documento. O PyMuPDF repara PDFs partidos, e um PDF
    cortado abria com páginas a menos e entrava assim no arquivo imutável.
    """
    cfg = dict(posto["cfg"], entrada_assentamento=60)
    assert agente.varrer_para_registo(cfg, posto["reg"], None) == 0
    assert posto["reg"].todos() == []
    assert "edital.pdf" in os.listdir(cfg["entrada"]), "saiu da entrada sem ser lido"
    # O que interessa mesmo: um pedaço de PDF no arquivo imutável já não sai.
    assert not any(fs for _r, _d, fs in os.walk(cfg["originais"])), "arquivou um pedaço"


def test_um_ficheiro_assente_e_lido(posto, monkeypatch):
    """Passado o tempo de assentamento, o mesmo ficheiro entra normalmente.

    Passa contra o código anterior de propósito, e o AGENTS.md pede que se
    diga: fixa que a espera não engole o documento para sempre. O tempo anda
    pelo relógio e não pela data do ficheiro, que é a que o cliente escolhe.
    """
    cfg = dict(posto["cfg"], entrada_assentamento=60)
    agora = agente.time.time()
    monkeypatch.setattr(agente.time, "time", lambda: agora + 120)
    assert agente.varrer_para_registo(cfg, posto["reg"], None) == 1


def test_um_ficheiro_com_data_no_futuro_tambem_assenta(posto, monkeypatch):
    """A data que o cliente pôs no ficheiro não o prende na entrada.

    Um posto com o relógio adiantado, numa cópia que preserva a data do
    original, deixava o ficheiro com o mtime no futuro. A idade ficava negativa
    e o edital nunca entrava, sem um erro. Falha contra a versão que lia o
    mtime.
    """
    cfg = dict(posto["cfg"], entrada_assentamento=60)
    caminho = os.path.join(cfg["entrada"], "edital.pdf")
    daqui_a_um_ano = agente.time.time() + 365 * 86400
    os.utime(caminho, (daqui_a_um_ano, daqui_a_um_ano))
    agora = agente.time.time()
    monkeypatch.setattr(agente.time, "time", lambda: agora + 120)
    assert agente.varrer_para_registo(cfg, posto["reg"], None) == 1


@pytest.mark.skipif(os.name == "nt", reason="o dono do ficheiro lê-se pelo pwd, que é POSIX")
def test_o_historico_diz_quem_colocou_o_documento(posto, monkeypatch):
    """O evento que abre o histórico é de quem pôs o ficheiro na pasta.

    Gravava-se «sistema» para toda a gente. Numa partilha Samba ligada ao
    domínio, o dono do ficheiro é a conta com que a pessoa abriu a pasta.
    """
    import pwd

    dono = os.stat(os.path.join(posto["cfg"]["entrada"], "edital.pdf")).st_uid
    # O processo finge ser outro utilizador. O ficheiro foi criado por este
    # processo, e sem isto uma versão que gravasse o utilizador do AGENTE, e não
    # o dono do ficheiro, passava igual — que é exatamente o erro a apanhar,
    # porque na VM o agente é sempre «editais».
    monkeypatch.setattr(agente.os, "getuid", lambda: dono + 1)
    monkeypatch.setattr(agente.os, "geteuid", lambda: dono + 1)
    agente.varrer_para_registo(posto["cfg"], posto["reg"], None)
    primeiro = posto["reg"].todos()[0]["historico"][0]
    assert primeiro["utilizador"] == pwd.getpwuid(dono).pw_name


def test_um_assentamento_mal_escrito_nao_para_a_entrada(posto, monkeypatch):
    """Um «15s» no config.json vale o de omissão, e a entrada continua a andar.

    O float() rebentava fora da proteção de cada ficheiro, e a volta inteira
    caía: nenhum documento chegava a rascunho até alguém corrigir a chave.
    """
    cfg = dict(posto["cfg"], entrada_assentamento="15s")
    agora = agente.time.time()
    monkeypatch.setattr(agente.time, "time", lambda: agora + 120)
    assert agente.varrer_para_registo(cfg, posto["reg"], None) == 1


def test_um_ficheiro_que_muda_durante_a_leitura_nao_e_arquivado(posto, monkeypatch):
    """Se a cópia retoma enquanto o agente lê, o arquivo não fica com outra versão.

    Uma cópia pela rede pode parar mais do que o assentamento e retomar. O
    assunto e as páginas viriam de uma versão e o arquivo imutável guardava
    outra.
    """
    caminho = os.path.join(posto["cfg"]["entrada"], "edital.pdf")
    ler = agente.doc.ler_metadados

    def ler_e_a_copia_retoma(*args, **kwargs):
        info = ler(*args, **kwargs)
        with open(caminho, "ab") as f:
            f.write(b"%% resto da copia\n")
        return info

    monkeypatch.setattr(agente.doc, "ler_metadados", ler_e_a_copia_retoma)
    assert agente.varrer_para_registo(posto["cfg"], posto["reg"], None) == 0
    assert posto["reg"].todos() == []
    assert not any(fs for _r, _d, fs in os.walk(posto["cfg"]["originais"]))
    assert "edital.pdf" in os.listdir(posto["cfg"]["entrada"])
