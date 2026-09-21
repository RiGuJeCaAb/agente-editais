"""
test_utilizadores.py — Contas, senhas e sessões.

O que está aqui em causa não é só o acesso: é se a certidão de afixação diz a
verdade. Enquanto o painel teve uma senha partilhada, o nome que ia para o
histórico era o que quem entrasse escrevesse. Estes testes fixam o
comportamento que substitui isso.
"""
from __future__ import annotations

import json
import time

import pytest

import utilizadores as utl

SENHA = "uma-senha-suficiente"


@pytest.fixture
def cofre(tmp_path):
    """Cofre vazio, em pasta descartável."""
    return utl.Utilizadores(str(tmp_path / "utilizadores.json"))


@pytest.fixture
def com_ana(cofre):
    """Cofre com uma administradora."""
    cofre.criar("ana.abreu", SENHA, nome_completo="Ana Abreu", papel=utl.ADMINISTRADOR)
    return cofre


def test_cria_e_autentica(com_ana):
    """O caminho normal: a conta criada entra com a sua senha."""
    conta = com_ana.autenticar("ana.abreu", SENHA)
    assert conta and conta["nome_completo"] == "Ana Abreu"
    assert conta["papel"] == utl.ADMINISTRADOR


@pytest.mark.parametrize("nome,senha,motivo", [
    ("ana abreu", SENHA, "espaço no nome"),
    ("ana/abreu", SENHA, "barra no nome"),
    ("", SENHA, "nome vazio"),
    ("joao", "curta", "senha com menos de 10 caracteres"),
])
def test_recusa_dados_invalidos(cofre, nome, senha, motivo):
    """Nomes e senhas fora das regras são recusados com mensagem, não em silêncio."""
    with pytest.raises(utl.ErroDeUtilizador):
        cofre.criar(nome, senha)


def test_nao_deixa_criar_duas_vezes_o_mesmo_nome(com_ana):
    """Dois utilizadores com o mesmo nome tornariam a auditoria ambígua."""
    with pytest.raises(utl.ErroDeUtilizador, match="Já existe"):
        com_ana.criar("ana.abreu", "outra-senha-comprida")


def test_a_senha_nunca_e_guardada_em_claro(com_ana, tmp_path):
    """No ficheiro há sal e chave derivada — a senha não aparece em lado nenhum."""
    bruto = (tmp_path / "utilizadores.json").read_text(encoding="utf-8")
    assert SENHA not in bruto
    conta = json.loads(bruto)["utilizadores"][0]
    assert len(conta["sal"]) == 32 and len(conta["chave"]) == 64
    assert conta["scrypt"]["n"] == utl.SCRYPT_N


def test_listar_nao_expoe_segredos(com_ana):
    """A listagem não pode carregar o sal, a chave nem os contadores de falha.

    Filtra-se no cofre e não em cada rota que a usa, para não depender de quem
    escrever a próxima se lembrar de o fazer.
    """
    conta = com_ana.listar()[0]
    for proibido in ("sal", "chave", "scrypt", "falhas", "trancado_ate"):
        assert proibido not in conta


def test_conta_desactivada_nao_entra(com_ana):
    """Desativar fecha a porta, sem apagar o nome que está no histórico."""
    com_ana.definir_activo("ana.abreu", False)
    assert com_ana.autenticar("ana.abreu", SENHA) is None
    assert len(com_ana.listar()) == 1        # a conta continua lá
    com_ana.definir_activo("ana.abreu", True)
    assert com_ana.autenticar("ana.abreu", SENHA)


def test_conta_tranca_ao_fim_de_muitas_tentativas(com_ana):
    """Tentar a mesma conta a partir de vários sítios acaba por a trancar.

    É a defesa que complementa o limite por endereço do painel: aquele trava
    quem varre senhas de um sítio, este trava quem varre a mesma conta de vários.
    """
    for _ in range(utl.TENTATIVAS_POR_CONTA):
        assert com_ana.autenticar("ana.abreu", "senha-errada-mas-longa") is None
    assert com_ana.autenticar("ana.abreu", SENHA) is None   # trancada, mesmo com a certa


def test_tempo_de_resposta_nao_revela_se_o_nome_existe(com_ana):
    """Um nome inexistente demora o mesmo que um existente com senha errada.

    Sem a derivação de equilíbrio em autenticar(), um nome que não existisse
    respondia em microssegundos e um existente em ~165 ms — o que entrega a
    lista de nomes válidos a quem cronometrar.
    """
    def medir(nome):
        t = time.perf_counter()
        com_ana.autenticar(nome, "senha-errada-mas-longa")
        return time.perf_counter() - t

    existente = min(medir("ana.abreu") for _ in range(3))
    inexistente = min(medir("nao.existe") for _ in range(3))
    # Ordens de grandeza, não igualdade: basta que o inexistente não seja
    # instantâneo perto do existente.
    assert inexistente > existente * 0.5


def test_mudar_senha_exige_a_atual(com_ana):
    """O próprio muda a senha provando que sabe a anterior."""
    with pytest.raises(utl.ErroDeUtilizador, match="atual"):
        com_ana.mudar_senha("ana.abreu", "nova-senha-comprida", senha_atual="errada")
    com_ana.mudar_senha("ana.abreu", "nova-senha-comprida", senha_atual=SENHA)
    assert com_ana.autenticar("ana.abreu", "nova-senha-comprida")
    assert com_ana.autenticar("ana.abreu", SENHA) is None


def test_mudar_senha_fecha_as_sessoes_da_conta(com_ana):
    """Se a senha foi mudada por suspeita, deixar sessões abertas anularia o efeito."""
    t = com_ana.abrir_sessao(com_ana.autenticar("ana.abreu", SENHA))
    assert com_ana.sessao(t)
    com_ana.mudar_senha("ana.abreu", "nova-senha-comprida", senha_atual=SENHA)
    assert com_ana.sessao(t) is None


def test_administrador_repoe_senha_sem_saber_a_anterior(com_ana):
    """Quem esquece a senha não fica de fora: um administrador repõe-na."""
    com_ana.mudar_senha("ana.abreu", "reposta-por-administrador")
    assert com_ana.autenticar("ana.abreu", "reposta-por-administrador")


def test_sessao_expira_por_inatividade(com_ana, monkeypatch):
    """A validade conta desde o último uso, não desde a abertura."""
    monkeypatch.setattr(utl, "MINUTOS_DE_SESSAO", 0.001)   # 60 ms
    t = com_ana.abrir_sessao(com_ana.autenticar("ana.abreu", SENHA))
    assert com_ana.sessao(t)
    time.sleep(0.12)
    assert com_ana.sessao(t) is None


def test_sessao_renova_se_for_usada(com_ana, monkeypatch):
    """Quem está a trabalhar não é interrompido."""
    monkeypatch.setattr(utl, "MINUTOS_DE_SESSAO", 0.005)   # 300 ms
    t = com_ana.abrir_sessao(com_ana.autenticar("ana.abreu", SENHA))
    for _ in range(4):
        time.sleep(0.1)
        assert com_ana.sessao(t), "a sessão expirou apesar de estar a ser usada"


def test_testemunhos_sao_diferentes_e_imprevisiveis(com_ana):
    """Duas sessões nunca partilham testemunho."""
    conta = com_ana.autenticar("ana.abreu", SENHA)
    fichas = {com_ana.abrir_sessao(conta) for _ in range(20)}
    assert len(fichas) == 20
    assert all(len(f) >= 32 for f in fichas)


def test_limpa_sessoes_expiradas(com_ana, monkeypatch):
    """As sessões velhas são deitadas fora, para a memória não crescer sem fim."""
    conta = com_ana.autenticar("ana.abreu", SENHA)
    for _ in range(5):
        com_ana.abrir_sessao(conta)
    monkeypatch.setattr(utl, "MINUTOS_DE_SESSAO", 0.001)
    time.sleep(0.12)
    assert com_ana.limpar_sessoes_expiradas() == 5


def test_custo_da_senha_sobe_sozinho_na_entrada_seguinte(com_ana, tmp_path, monkeypatch):
    """Uma conta com parâmetros antigos é re-derivada ao entrar, sem dar por isso.

    É o que permite subir o custo do scrypt daqui a uns anos sem obrigar toda a
    gente a mudar de senha.
    """
    caminho = str(tmp_path / "utilizadores.json")
    dados = json.loads((tmp_path / "utilizadores.json").read_text(encoding="utf-8"))
    # Simula uma conta gravada por uma versão com custo mais baixo.
    import hashlib
    import os as _os
    sal = _os.urandom(16)
    fraco = {"n": 2 ** 12, "r": 8, "p": 1}
    dados["utilizadores"][0]["sal"] = sal.hex()
    dados["utilizadores"][0]["chave"] = hashlib.scrypt(
        SENHA.encode(), salt=sal, n=fraco["n"], r=fraco["r"], p=fraco["p"],
        dklen=32, maxmem=128 * fraco["n"] * fraco["r"] * 2).hex()
    dados["utilizadores"][0]["scrypt"] = fraco
    (tmp_path / "utilizadores.json").write_text(json.dumps(dados), encoding="utf-8")

    cofre = utl.Utilizadores(caminho)
    assert cofre.autenticar("ana.abreu", SENHA), "a senha antiga tem de continuar a entrar"
    novo = json.loads((tmp_path / "utilizadores.json").read_text(encoding="utf-8"))
    assert novo["utilizadores"][0]["scrypt"]["n"] == utl.SCRYPT_N
    assert utl.Utilizadores(caminho).autenticar("ana.abreu", SENHA)


def test_ha_contas_so_conta_as_activas(cofre):
    """O painel usa isto para recusar arrancar sem ninguém que possa entrar."""
    assert not cofre.ha_contas()
    cofre.criar("ana.abreu", SENHA)
    assert cofre.ha_contas()
    cofre.definir_activo("ana.abreu", False)
    assert not cofre.ha_contas()
