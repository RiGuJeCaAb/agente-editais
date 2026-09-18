"""
test_originais.py — O arquivo imutável, e a promessa que ele faz.

A promessa: um edital publicado pode ser recomposto e certificado mesmo depois
de alguém limpar a pasta de entrada — e ninguém lhe chamou "arquivo", por isso é
natural que a limpem. Sem isto, limpar a entrada apagava o documento que foi
afixado, e a certidão passava a afirmar factos sobre um ficheiro inexistente.
"""
from __future__ import annotations

import os

import originais as orig
import pytest


@pytest.fixture
def arquivo(tmp_path):
    return str(tmp_path / "originais")


@pytest.fixture
def documento(tmp_path):
    """Um ficheiro com conteúdo suficiente para atravessar mais de um bloco."""
    caminho = tmp_path / "edital.pdf"
    caminho.write_bytes(b"conteudo do edital numero dezassete\n" * 5000)
    return str(caminho)


def test_arquiva_e_encontra(arquivo, documento):
    """O caminho normal: arquivar devolve o resumo, procurar devolve o ficheiro."""
    sha, destino = orig.arquivar(arquivo, documento)
    assert len(sha) == 64 and os.path.exists(destino)
    assert orig.procurar(arquivo, sha, ".pdf") == destino


def test_o_endereco_e_o_conteudo_e_nao_o_nome(arquivo, documento, tmp_path):
    """O mesmo documento com outro nome ocupa espaço uma vez.

    O nome é do utilizador e muda ('(1)', '_final_v2'); o conteúdo é do
    documento e não muda.
    """
    outro = tmp_path / "edital (1) FINAL.pdf"
    outro.write_bytes(open(documento, "rb").read())
    sha1, p1 = orig.arquivar(arquivo, documento)
    sha2, p2 = orig.arquivar(arquivo, str(outro))
    assert sha1 == sha2 and p1 == p2
    assert orig.estatisticas(arquivo)["documentos"] == 1


def test_conteudos_diferentes_nao_colidem(arquivo, tmp_path):
    """Dois documentos diferentes são dois ficheiros no arquivo."""
    for i in (1, 2):
        f = tmp_path / f"e{i}.pdf"
        f.write_bytes(f"documento numero {i}".encode())
        orig.arquivar(arquivo, str(f))
    assert orig.estatisticas(arquivo)["documentos"] == 2


def test_distribui_por_subpastas(arquivo, documento):
    """Dois caracteres do resumo formam a subpasta.

    Não é enfeite: alguns sistemas de ficheiros degradam-se com dezenas de
    milhares de entradas numa só pasta.
    """
    sha, destino = orig.arquivar(arquivo, documento)
    assert os.path.relpath(destino, arquivo).startswith(sha[:2] + os.sep)


def test_detecta_adulteracao(arquivo, documento):
    """Se alguém mexer no ficheiro arquivado, o resumo deixa de bater.

    É o que transforma o arquivo em prova em vez de mera cópia.
    """
    sha, destino = orig.arquivar(arquivo, documento)
    assert orig.conferir(arquivo, sha, ".pdf")
    with open(destino, "ab") as f:
        f.write(b"uma linha acrescentada por alguem")
    assert not orig.conferir(arquivo, sha, ".pdf")


def test_encontra_sem_saber_a_extensao(arquivo, documento):
    """Um registo antigo pode ter o resumo e não o nome do ficheiro."""
    sha, destino = orig.arquivar(arquivo, documento)
    assert orig.procurar(arquivo, sha) == destino


def test_procurar_o_que_nao_existe_devolve_nada(arquivo):
    """Sem arquivo, sem subpasta, sem ficheiro: None em todos os casos, sem exceção."""
    assert orig.procurar(arquivo, "0" * 64, ".pdf") is None
    assert orig.procurar(arquivo, "") is None
    assert not orig.conferir(arquivo, "0" * 64)


def test_nao_deixa_temporarios(arquivo, documento):
    """A cópia é feita para um temporário e renomeada — nada fica a meio.

    Sem isso, uma cópia interrompida deixava no arquivo um ficheiro truncado
    com um nome que promete um conteúdo que ele já não tem.
    """
    for _ in range(3):
        orig.arquivar(arquivo, documento)
    restos = [f for _r, _p, fs in os.walk(arquivo) for f in fs if f.endswith(".tmp")]
    assert restos == []


def test_o_original_nao_e_movido(arquivo, documento):
    """Copia-se, não se move: a pasta de entrada continua a ser de quem a usa."""
    orig.arquivar(arquivo, documento)
    assert os.path.exists(documento)


def test_resumo_e_estavel_e_sensivel(tmp_path):
    """O mesmo conteúdo dá sempre o mesmo resumo; um byte diferente muda-o todo."""
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"x" * 100000)
    b.write_bytes(b"x" * 99999 + b"y")
    assert orig.resumo(str(a)) == orig.resumo(str(a))
    assert orig.resumo(str(a)) != orig.resumo(str(b))


def test_estatisticas_ignoram_temporarios(arquivo, documento):
    """Um .tmp deixado por uma cópia interrompida não conta como documento."""
    sha, destino = orig.arquivar(arquivo, documento)
    with open(destino + ".tmp", "wb") as f:
        f.write(b"restos de uma copia interrompida")
    assert orig.estatisticas(arquivo)["documentos"] == 1
