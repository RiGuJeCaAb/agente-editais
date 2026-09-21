"""
test_painel_seguranca.py — As portas que se fecharam, e que têm de ficar fechadas.

Duas camadas, de ondas diferentes e por razões diferentes:

  - Onda 1 fechou o CSRF. Estava reproduzido: com as credenciais Basic em cache
    no browser, um POST nascido noutro sítio retirava um edital do ecrã. Esses
    testes continuam aqui, agora contra sessões por cookie.
  - Onda 2 trocou a senha partilhada por contas nominais. A razão não é
    higiene: a certidão de afixação diz quem afixou o edital, e enquanto o nome
    do utilizador fosse texto livre no Basic Auth, esse "quem" valia zero.

Os testes montam o servidor a sério e repetem os ataques. Se alguém afrouxar
alguma barreira, falham aqui e não no posto.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.request

import pytest

import painel as painel_mod
import registo as reg_mod
import utilizadores as utl
from conftest import META_BOA

SENHA = "senha-de-teste-com-cedilha-ç"
SENHA_OPERADOR = "outra-senha-comprida-2"
_porta = [8950]


class Cliente:
    """Um browser de mentira: guarda cookies e envia os cabeçalhos do painel."""

    def __init__(self, base):
        self.base = base
        self.frasco = http.cookiejar.CookieJar()
        self.abre = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.frasco))

    def pede(self, rota, corpo=None, *, cabecalhos=None, metodo=None):
        """Faz um pedido e devolve (código, corpo, cabeçalhos), sem levantar em 4xx."""
        cab = {"Host": self.base.split("//")[1]}
        dados = None
        if corpo is not None:
            cab.update({"Content-Type": "application/json",
                        "X-Painel-Pedido": "1", "Origin": self.base})
            dados = json.dumps(corpo).encode("utf-8")
        cab.update(cabecalhos or {})
        req = urllib.request.Request(self.base + rota, data=dados,
                                     method=metodo or ("POST" if dados else "GET"),
                                     headers=cab)
        try:
            r = self.abre.open(req)
            return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def entrar(self, utilizador, senha):
        """Abre sessão e devolve o código da resposta."""
        return self.pede("/api/entrar", {"utilizador": utilizador, "senha": senha})[0]

    @property
    def cookies(self):
        return {c.name: c for c in self.frasco}


@pytest.fixture
def painel(tmp_path):
    """Painel a correr, com duas contas e um edital publicado à espera."""
    contas = utl.Utilizadores(str(tmp_path / "utilizadores.json"))
    contas.criar("ana.abreu", SENHA, nome_completo="Ana Abreu", papel=utl.ADMINISTRADOR)
    contas.criar("rui.santos", SENHA_OPERADOR, nome_completo="Rui Santos")

    reg = reg_mod.RegistoEntrada(str(tmp_path / "registo_entrada.json"))
    r = reg.criar_rascunho(ficheiro_origem="e.pdf", hash_ficheiro="h",
                           num_paginas=1, meta=dict(META_BOA))
    reg.mover_estado(r["id"], reg_mod.VALIDADO, utilizador="ana.abreu")
    reg.mover_estado(r["id"], reg_mod.PUBLICADO, utilizador="ana.abreu")

    _porta[0] += 1
    porta = _porta[0]
    cfg = {"saida": str(tmp_path), "previas": str(tmp_path), "arquivo": str(tmp_path),
           "municipio": "Município de Teste", "intervalo_watch": 30}
    srv = painel_mod.PainelServer(reg, cfg, republicar_callback=lambda: None,
                                  painel_html_path=None, contas=contas,
                                  saude_callback=lambda: {"ok": True})
    srv.iniciar(host="127.0.0.1", porta=porta, bloquear=False)
    base = f"http://127.0.0.1:{porta}"
    # Espera a que o socket aceite ligações, em vez de dormir um valor ao calhas:
    # num CI carregado, um sleep fixo ou é lento de mais ou curto de mais.
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/saude", timeout=0.5)
            break
        except (urllib.error.URLError, OSError):
            pass
    yield {"reg": reg, "contas": contas, "rid": r["id"], "base": base,
           "cliente": Cliente(base)}
    srv._httpd.shutdown()


@pytest.fixture
def entrado(painel):
    """O mesmo painel, já com a administradora dentro."""
    assert painel["cliente"].entrar("ana.abreu", SENHA) == 200
    return painel


# ---------------------------------------------------------------------------
# Onda 1 — pedidos nascidos noutro sítio
# ---------------------------------------------------------------------------
ATAQUES = [
    ("formulário text/plain", {"Content-Type": "text/plain"}),
    ("formulário urlencoded", {"Content-Type": "application/x-www-form-urlencoded"}),
    ("formulário multipart", {"Content-Type": "multipart/form-data"}),
    ("json sem o cabeçalho próprio", {"Content-Type": "application/json",
                                      "X-Painel-Pedido": None}),
    ("json e cabeçalho, mas origem de fora", {"Origin": "https://mau.example"}),
]


@pytest.mark.parametrize("nome,cabs", ATAQUES, ids=[a[0] for a in ATAQUES])
def test_pedido_de_outro_sitio_e_recusado(entrado, nome, cabs):
    """Nenhuma variante de CSRF muda o estado de um edital, mesmo com sessão aberta.

    A sessão está aberta de propósito: é o cenário real. O funcionário tem o
    painel aberto noutro separador, e o sítio malicioso conta com isso.
    """
    cliente = entrado["cliente"]
    cabs = {k: v for k, v in cabs.items() if v is not None}
    if "X-Painel-Pedido" not in cabs and "Content-Type" in cabs:
        cabs["X-Painel-Pedido"] = None
    corpo = json.dumps({"id": entrado["rid"], "estado": "retirado"}).encode()
    req = urllib.request.Request(entrado["base"] + "/api/estado", data=corpo,
                                 method="POST", headers={k: v for k, v in cabs.items() if v})
    try:
        codigo = cliente.abre.open(req).status
    except urllib.error.HTTPError as e:
        codigo = e.code
    assert codigo == 403
    assert entrado["reg"].por_id(entrado["rid"])["estado"] == reg_mod.PUBLICADO


def test_o_proprio_painel_continua_a_funcionar(entrado):
    """A correção não pode fechar a porta a quem tem de entrar por ela."""
    codigo, corpo, _ = entrado["cliente"].pede(
        "/api/estado", {"id": entrado["rid"], "estado": reg_mod.RETIRADO})
    assert codigo == 200 and json.loads(corpo)["ok"]
    assert entrado["reg"].por_id(entrado["rid"])["estado"] == reg_mod.RETIRADO


def test_cabecalhos_de_seguranca_presentes(painel):
    """Todas as respostas levam os cabeçalhos de segurança. Não havia nenhum."""
    _c, _b, h = painel["cliente"].pede("/saude")
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "no-referrer"
    assert h.get("Cache-Control") == "no-store"
    assert "frame-ancestors 'none'" in h.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# Onda 2 — contas, sessões e papéis
# ---------------------------------------------------------------------------
def test_sem_sessao_a_api_recusa_e_a_pagina_reencaminha(painel):
    """Um pedido de API leva 401; um pedido de página vai para a entrada.

    A distinção não é preciosismo: o painel precisa do 401 para reagir, e uma
    pessoa que volta ao computador precisa de ver o formulário e não um erro.
    """
    codigo, corpo, _ = painel["cliente"].pede("/api/registos")
    assert codigo == 401 and json.loads(corpo)["entrar"] is True
    codigo, _corpo, _h = painel["cliente"].pede("/")
    assert codigo == 200          # seguiu o reencaminhamento para /entrar


def test_saude_e_a_unica_rota_aberta(painel):
    """A rota de saúde responde sem sessão, para um supervisor a poder vigiar."""
    codigo, corpo, _ = painel["cliente"].pede("/saude")
    assert codigo == 200 and json.loads(corpo)["ok"] is True


def test_entrada_com_senha_acentuada(painel):
    """Uma senha com cedilha entra.

    Guarda a regressão que a Onda 1 encontrou: compare_digest levanta TypeError
    com strings fora de ASCII, o que trancaria fora toda a gente com uma senha
    em português. A comparação é feita sobre bytes.
    """
    assert painel["cliente"].entrar("ana.abreu", SENHA) == 200


@pytest.mark.parametrize("utilizador,senha", [
    ("ana.abreu", "senha-errada-mas-comprida"),
    ("nao.existe", SENHA),
    ("", ""),
])
def test_credenciais_invalidas_dao_sempre_a_mesma_resposta(painel, utilizador, senha):
    """Utilizador inexistente e senha errada são indistinguíveis de fora.

    Distinguir seria cómodo para quem entra e uma prenda para quem tenta: diria
    logo quais os nomes de utilizador que existem.
    """
    codigo, corpo, _ = painel["cliente"].pede(
        "/api/entrar", {"utilizador": utilizador, "senha": senha})
    assert codigo == 401
    assert json.loads(corpo)["erro"] == "Utilizador ou senha incorretos."


def test_cookie_de_sessao_esta_protegido(painel):
    """O testemunho é HttpOnly e SameSite=Strict.

    HttpOnly põe-no fora do alcance de qualquer JavaScript, por isso uma falha
    de XSS não o consegue roubar. SameSite=Strict impede o browser de o enviar
    em pedidos nascidos noutro sítio, o que fecha o CSRF na raiz.
    """
    painel["cliente"].entrar("ana.abreu", SENHA)
    cookie = painel["cliente"].cookies[painel_mod.COOKIE_SESSAO]
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "Strict"
    assert len(cookie.value) >= 32


def test_sair_termina_a_sessao(entrado):
    """Depois de sair, o mesmo cliente deixa de poder ler o registo."""
    assert entrado["cliente"].pede("/api/registos")[0] == 200
    entrado["cliente"].pede("/sair")
    assert entrado["cliente"].pede("/api/registos")[0] == 401


def test_operador_nao_gere_contas(painel):
    """Um operador vê editais, não contas. É a única distinção entre os papéis."""
    painel["cliente"].entrar("rui.santos", SENHA_OPERADOR)
    assert painel["cliente"].pede("/api/registos")[0] == 200
    codigo, corpo, _ = painel["cliente"].pede("/api/utilizadores")
    assert codigo == 403 and "administrador" in json.loads(corpo)["erro"]


def test_administrador_cria_contas(entrado):
    """Um administrador cria contas, e a conta nova entra."""
    codigo, corpo, _ = entrado["cliente"].pede("/api/utilizadores", {
        "acao": "criar", "nome": "joao.dias", "senha": "mais-uma-senha-longa",
        "nome_completo": "João Dias", "papel": "operador"})
    assert codigo == 200 and json.loads(corpo)["ok"]
    novo = Cliente(entrado["base"])
    assert novo.entrar("joao.dias", "mais-uma-senha-longa") == 200


def test_administrador_nao_se_desactiva_a_si_proprio(entrado):
    """Guarda contra o tiro no pé que tranca o painel a toda a gente."""
    codigo, corpo, _ = entrado["cliente"].pede(
        "/api/utilizadores", {"acao": "activo", "nome": "ana.abreu", "valor": False})
    assert codigo == 400 and "própria conta" in json.loads(corpo)["erro"]


def test_conta_desactivada_nao_entra_e_perde_a_sessao(entrado):
    """Desativar uma conta fecha as sessões que ela tenha abertas."""
    operador = Cliente(entrado["base"])
    assert operador.entrar("rui.santos", SENHA_OPERADOR) == 200
    entrado["cliente"].pede("/api/utilizadores",
                            {"acao": "activo", "nome": "rui.santos", "valor": False})
    assert operador.pede("/api/registos")[0] == 401
    assert Cliente(entrado["base"]).entrar("rui.santos", SENHA_OPERADOR) == 401


def test_tentativas_repetidas_bloqueiam_o_endereco(painel):
    """Ao fim de N senhas erradas, o endereço fica de castigo — mesmo com a certa."""
    for _ in range(painel_mod.TENTATIVAS_ANTES_DE_BLOQUEAR + 1):
        painel["cliente"].pede("/api/entrar",
                               {"utilizador": "ana.abreu", "senha": "errada-mas-longa"})
    assert painel["cliente"].entrar("ana.abreu", SENHA) == 429


def test_painel_recusa_arrancar_sem_contas(tmp_path):
    """Sem contas, o painel não sobe — e diz qual é o comando que resolve."""
    reg = reg_mod.RegistoEntrada(str(tmp_path / "r.json"))
    vazio = utl.Utilizadores(str(tmp_path / "vazio.json"))
    srv = painel_mod.PainelServer(reg, {}, painel_html_path=None, contas=vazio)
    with pytest.raises(RuntimeError, match="criar-utilizador"):
        srv.iniciar(host="127.0.0.1", porta=8999, bloquear=False)


# ---------------------------------------------------------------------------
# Certidão
# ---------------------------------------------------------------------------
def test_certidao_sai_em_pdf(entrado):
    """A certidão de um edital afixado sai como PDF, com nome de ficheiro próprio."""
    codigo, corpo, h = entrado["cliente"].pede(f"/certidao/{entrado['rid']}")
    assert codigo == 200
    assert h.get("Content-Type") == "application/pdf"
    assert corpo[:5] == b"%PDF-"
    assert "certidao_afixacao" in h.get("Content-Disposition", "")


def test_certidao_recusa_o_que_nunca_foi_afixado(entrado):
    """Um rascunho não tem afixação para certificar, e o painel di-lo."""
    novo = entrado["reg"].criar_rascunho(ficheiro_origem="b.pdf", hash_ficheiro="h2",
                                         num_paginas=1, meta=dict(META_BOA))
    codigo, corpo, _ = entrado["cliente"].pede(f"/certidao/{novo['id']}")
    assert codigo == 409 and "não foi afixado" in corpo.decode()


def test_certidao_exige_sessao(painel):
    """A certidão nomeia pessoas e cita documentos: não sai sem sessão."""
    assert painel["cliente"].pede(f"/certidao/{painel['rid']}")[0] == 200  # segue p/ /entrar


# ---------------------------------------------------------------------------
# Travessia de caminho (Onda 1, mantida)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "../../../etc/passwd", "..\\..\\config.json", "....//....//etc/shadow",
    "%2e%2e%2fconfig.json", "/etc/passwd",
])
def test_travessia_de_diretorios_nao_sai_da_pasta(tmp_path, nome):
    """Nenhuma forma de '..' consegue apontar para fora da pasta autorizada."""
    caminho = painel_mod._dentro_de(str(tmp_path), nome)
    assert caminho is None or caminho.startswith(str(tmp_path.resolve()))


def test_pasta_vizinha_com_o_mesmo_prefixo_nao_passa(tmp_path):
    """'/dados/saida_antiga' não é '/dados/saida'.

    Era este o defeito do padrão anterior, que comparava prefixos de texto:
    uma pasta vizinha cujo nome começasse igual passava a barreira.
    """
    (tmp_path / "saida").mkdir()
    (tmp_path / "saida_antiga").mkdir()
    (tmp_path / "saida_antiga" / "segredo.png").write_bytes(b"x")
    assert painel_mod._dentro_de(str(tmp_path / "saida"),
                                 "../saida_antiga/segredo.png") is None
