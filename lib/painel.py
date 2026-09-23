"""
painel.py — Servidor web do painel de gestão dos editais (back-end).

Serve o painel no browser local e expõe uma API mínima para o front-end operar
o registo de entrada (listar, editar, mudar de estado). Usa apenas a biblioteca
padrão do Python (http.server) — ZERO dependências novas, para não complicar a
instalação no município.

Segurança:
  - contas INDIVIDUAIS, com senha derivada por scrypt (ver lib/utilizadores.py);
    a senha partilhada foi retirada na Onda 2, porque com ela o trilho de
    auditoria registava o nome que quem entrasse quisesse escrever;
  - sessão por cookie HttpOnly + SameSite=Strict, com validade contada desde o
    último uso;
  - escrita protegida contra pedidos nascidos noutro sítio (Content-Type,
    cabeçalho próprio e concordância entre Origin e Host);
  - dois papéis: operador valida e publica, administrador gere também as contas;
  - limite de tentativas por endereço E por conta, que são defesas diferentes.

O que continua por fazer, e é honesto dizê-lo: isto ainda não é autenticação
centralizada. O passo seguinte é o Active Directory / Entra ID da CMMB, e o
gancho está em Utilizadores.autenticar() — trocar a verificação local por uma
consulta LDAP/OIDC não obriga a mexer em mais nada deste ficheiro.
"""
from __future__ import annotations

import http.cookies
import json
import mimetypes
import os
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import certidao as cert_mod
import diario
import prazos as pr_mod
import progresso as prog
import registo as reg_mod
import utilizadores as utl

# Cabeçalho próprio que o painel envia em todos os pedidos de escrita. É metade
# da defesa contra CSRF: um <form> de outro sítio consegue enviar um POST com as
# credenciais Basic em cache, mas NÃO consegue pôr um cabeçalho personalizado —
# isso exigiria CORS com pedido prévio (preflight), que este servidor nunca
# autoriza. A outra metade é exigir Content-Type: application/json, que um
# formulário simples também não consegue produzir.
CABECALHO_PEDIDO = "X-Painel-Pedido"

# Nome do cookie de sessão. O prefixo do nome é deliberado: identifica o serviço
# num browser que possa ter outros cookies do mesmo anfitrião.
COOKIE_SESSAO = "editais_sessao"

# Rotas que não exigem sessão aberta, por razões diferentes: a página de entrada
# porque é onde se entra, e /saude porque tem de poder ser consultada por um
# supervisor de serviço que não faz login (e por isso só devolve estado, nunca
# conteúdo de editais).
ROTAS_ABERTAS = ("/entrar", "/api/entrar", "/saude")

# Tentativas de senha falhadas por endereço antes de o bloquear, e por quanto
# tempo. Uma senha partilhada, exposta em 0.0.0.0 e sem limite de tentativas, é
# uma senha que se descobre — o limite não substitui contas por utilizador
# (Onda 2), mas fecha a porta mais óbvia entretanto.
TENTATIVAS_ANTES_DE_BLOQUEAR = 8
SEGUNDOS_DE_BLOQUEIO = 300

# Política de segurança de conteúdo. O 'unsafe-inline' é uma cedência honesta: o
# painel tem CSS e JS embutidos no HTML, e separá-los é trabalho de outra onda.
# O que já protege a sério é o resto — sem enquadramento por terceiros, sem base
# href injetada, sem submissão de formulários para fora, sem ligações externas.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'none'")


_painel = diario.obter("PAINEL")

class PainelServer:
    """Encapsula o servidor do painel e as dependências que ele precisa.

    Guarda referências ao registo de entrada, à configuração e a um callback de
    'republicar' (que o agente fornece para regenerar a página da TV e o ZIP
    sempre que algo muda de estado).
    """

    def __init__(self, registo: reg_mod.RegistoEntrada, cfg: dict,
                 republicar_callback=None, painel_html_path=None,
                 contas: utl.Utilizadores | None = None, saude_callback=None):
        """
        Args:
            registo (RegistoEntrada): o gestor do registo de entrada.
            cfg (dict): configuração do agente (caminhos, portas, etc.).
            republicar_callback (callable|None): função sem argumentos que
                regenera a página da TV + ZIP; chamada após publicar/retirar.
            painel_html_path (str|None): caminho do ficheiro HTML do painel.
            contas (Utilizadores|None): cofre de contas. Sem ele, o painel não
                arranca — não há forma de saber quem está a afixar o quê.
            saude_callback (callable|None): devolve o dicionário de estado do
                agente para a rota /saude.
        """
        self.registo = registo
        self.cfg = cfg
        self.contas = contas
        self.saude: Callable[[], dict] = saude_callback or (lambda: {})
        self.republicar = republicar_callback or (lambda: None)
        self.painel_html_path = painel_html_path
        self._httpd = None
        # Contagem de falhas de senha por endereço: {ip: [falhas, bloqueado_ate]}.
        self._falhas: dict[str, tuple[int, float]] = {}
        self._falhas_lock = threading.Lock()

    def _bloqueado(self, ip):
        """Indica se um endereço está de castigo, e por quantos segundos ainda."""
        with self._falhas_lock:
            falhas, ate = self._falhas.get(ip, (0, 0.0))
            restam = ate - time.time()
            return (True, int(restam)) if restam > 0 else (False, 0)

    def _falhou(self, ip):
        """Regista uma senha errada e bloqueia o endereço ao fim de N tentativas."""
        with self._falhas_lock:
            falhas, _ate = self._falhas.get(ip, (0, 0.0))
            falhas += 1
            castigo = falhas >= TENTATIVAS_ANTES_DE_BLOQUEAR
            ate = time.time() + SEGUNDOS_DE_BLOQUEIO if castigo else 0.0
            self._falhas[ip] = (falhas, ate)
            if ate:
                _painel.info(f"{falhas} senhas erradas de {ip} — bloqueado "
                      f"{SEGUNDOS_DE_BLOQUEIO // 60} min.")

    def _acertou(self, ip):
        """Limpa a contagem de falhas depois de uma entrada bem sucedida."""
        with self._falhas_lock:
            self._falhas.pop(ip, None)

    # ---- arranque ---------------------------------------------------------
    def iniciar(self, host="127.0.0.1", porta=8770, bloquear=True):
        """Arranca o servidor HTTP do painel.

        Por omissão liga-se só a 127.0.0.1 (localhost) — o painel fica acessível
        apenas na própria máquina, o que é a opção segura por defeito. Para o
        expor a outros postos da rede interna, muda-se o host para "0.0.0.0" em
        config.json ("painel_host"), preferencialmente já dentro da VLAN de gestão.

        Args:
            host (str): interface de escuta.
            porta (int): porta TCP.
            bloquear (bool): se True, corre para sempre (serve_forever);
                se False, arranca numa thread e devolve o controlo.

        Raises:
            RuntimeError: se não houver senha configurada.
        """
        if self.contas is None or not self.contas.ha_contas():
            raise RuntimeError(
                "Não há utilizadores. O painel deixou de usar uma senha "
                "partilhada: cada pessoa entra com a sua conta, para a certidão "
                "de afixação poder dizer quem afixou. Cria a primeira conta com:"
                "\n\n    python agente.py --criar-utilizador NOME --administrador\n")
        servidor = self  # capturado no closure do handler

        class Handler(BaseHTTPRequestHandler):
            # Silencia o log ruidoso por omissão; mensagens úteis são impressas
            # pelo próprio agente.
            def log_message(self, *a):
                pass

            # -- utilitários de resposta --
            def _cabecalhos_seguranca(self):
                """Escreve os cabeçalhos de segurança comuns a todas as respostas.

                Nenhum destes existia. São baratos e cobrem três vetores distintos:
                nosniff impede o browser de adivinhar um tipo diferente do
                declarado (um JPEG servido como HTML deixa de poder correr), o CSP
                limita de onde vem o que a página executa e proíbe enquadramento
                por terceiros, e no-store evita que uma cache intermédia guarde
                dados de editais por validar.
                """
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", CSP)
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")

            def _json(self, obj, code=200):
                corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self._cabecalhos_seguranca()
                self.end_headers()
                self.wfile.write(corpo)

            def _texto(self, corpo, code=200, tipo="text/html; charset=utf-8"):
                if isinstance(corpo, str):
                    corpo = corpo.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self._cabecalhos_seguranca()
                self.end_headers()
                self.wfile.write(corpo)

            # -- autenticação por sessão --
            def _sessao(self):
                """Devolve a sessão aberta neste pedido, ou None.

                Substitui o Basic Auth com senha partilhada. A diferença que
                interessa não é técnica: com Basic, o nome era texto livre e o
                trilho de auditoria registava o que quem entrasse escrevesse.
                Agora o nome vem da conta que provou a senha, e é esse que vai
                para a certidão de afixação.
                """
                bruto = self.headers.get("Cookie", "")
                if not bruto:
                    return None
                try:
                    tarro = http.cookies.SimpleCookie()
                    tarro.load(bruto)
                except http.cookies.CookieError:
                    return None
                morfo = tarro.get(COOKIE_SESSAO)
                return servidor.contas.sessao(morfo.value) if morfo else None

            def _exigir_sessao(self):
                """Devolve a sessão, ou escreve já a resposta de recusa.

                Returns:
                    dict | None: a sessão; None quando a resposta já foi enviada.
                """
                sessao = self._sessao()
                if sessao:
                    return sessao
                # Um pedido de API recebe 401 em JSON, para o painel poder
                # reagir; um pedido de página é reencaminhado para a entrada,
                # que é o que uma pessoa espera ver.
                if urlparse(self.path).path.startswith("/api/"):
                    self._json({"ok": False, "erro": "Sessão terminada",
                                "entrar": True}, 401)
                else:
                    self._redirigir("/entrar")
                return None

            def _exigir_administrador(self, sessao):
                """Confirma que a sessão é de um administrador."""
                if sessao["papel"] == utl.ADMINISTRADOR:
                    return True
                self._json({"ok": False,
                            "erro": "Só um administrador pode gerir contas."}, 403)
                return False

            def _redirigir(self, destino):
                """Envia um reencaminhamento simples."""
                self.send_response(303)
                self.send_header("Location", destino)
                self._cabecalhos_seguranca()
                self.end_headers()

            def _verificar_escrita(self):
                """Valida que um pedido de escrita vem mesmo do painel, e não de outro sítio.

                Isto é a correção do problema mais sério que a análise encontrou.
                O Basic Auth fica em cache no browser e é enviado em pedidos
                iniciados por QUALQUER página. Como o servidor lia o corpo e fazia
                json.loads independentemente do Content-Type, um <form> alojado
                noutro sítio conseguia publicar ou retirar editais em nome de quem
                tivesse o painel aberto. Foi reproduzido com um POST de
                Content-Type text/plain e Origin de outro domínio, que retirou um
                edital do ecrã.

                Três barreiras, todas coisas que um formulário HTML simples não
                consegue vencer sem CORS (que este servidor nunca concede):

                  1. Content-Type tem de ser application/json;
                  2. o cabeçalho próprio X-Painel-Pedido tem de estar presente;
                  3. se vier Origin, o seu host tem de ser o mesmo do Host — ou
                     seja, o pedido tem de nascer da própria página do painel.

                A verificação é contra o Host do pedido e não contra o endereço de
                escuta, de propósito: o painel tanto é aberto por 127.0.0.1 como
                pelo IP da máquina na rede, e ambos são legítimos.

                Returns:
                    str | None: motivo da recusa, ou None se o pedido é válido.
                """
                tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if tipo != "application/json":
                    return f"Content-Type tem de ser application/json (veio '{tipo or 'nada'}')"
                if not self.headers.get(CABECALHO_PEDIDO):
                    return f"Falta o cabeçalho {CABECALHO_PEDIDO}"
                origem = self.headers.get("Origin")
                if origem:
                    anfitriao = self.headers.get("Host", "")
                    if urlparse(origem).netloc != anfitriao:
                        return f"Origem não autorizada: {origem}"
                return None

            def _ler_corpo_json(self):
                tam = int(self.headers.get("Content-Length", 0) or 0)
                if tam == 0:
                    return {}
                try:
                    return json.loads(self.rfile.read(tam).decode("utf-8"))
                except Exception:
                    return {}

            # -- rotas --
            def do_GET(self):
                rota = urlparse(self.path).path

                # Rotas abertas, cada uma pela sua razão (ver ROTAS_ABERTAS).
                if rota == "/entrar":
                    return servidor._servir_entrada(self)
                if rota == "/saude":
                    return self._json(servidor.saude())

                if rota == "/sair":
                    bruto = self.headers.get("Cookie", "")
                    if bruto:
                        try:
                            tarro = http.cookies.SimpleCookie()
                            tarro.load(bruto)
                            morfo = tarro.get(COOKIE_SESSAO)
                            if morfo:
                                servidor.contas.fechar_sessao(morfo.value)
                        except http.cookies.CookieError:
                            pass
                    self.send_response(303)
                    self.send_header("Location", "/entrar")
                    # Cookie apagado explicitamente: fechar a sessão no servidor
                    # basta para a segurança, mas deixar o testemunho morto no
                    # browser faz o painel pedir entrada duas vezes.
                    self.send_header("Set-Cookie",
                                     f"{COOKIE_SESSAO}=; Path=/; Max-Age=0; "
                                     f"HttpOnly; SameSite=Strict")
                    self._cabecalhos_seguranca()
                    return self.end_headers()

                sessao = self._exigir_sessao()
                if sessao is None:
                    return None

                if rota in ("/", "/index.html", "/painel"):
                    return servidor._servir_html(self)
                if rota == "/api/registos":
                    # O progresso viaja com os registos, na sondagem que o
                    # painel já faz, em vez de numa rota própria: uma segunda
                    # sondagem a bater no servidor de dois em dois segundos, só
                    # para saber se há trabalho em curso, era pagar um custo
                    # permanente por uma informação que quase sempre é «nada».
                    return self._json({"registos": servidor.registo.todos(),
                                       "estados": reg_mod.ESTADO_LABEL,
                                       "tipos": pr_mod.tipos_para_painel(),
                                       "progresso": prog.frase(),
                                       "sessao": {"nome": sessao["nome"],
                                                  "nome_completo": sessao["nome_completo"],
                                                  "papel": sessao["papel"]}})
                if rota == "/api/utilizadores":
                    if not self._exigir_administrador(sessao):
                        return None
                    return self._json({"utilizadores": servidor.contas.listar(),
                                       "papeis": utl.PAPEL_LABEL})
                if rota.startswith("/certidao/"):
                    return servidor._servir_certidao(self, rota, sessao)
                if rota.startswith("/saida/"):
                    return servidor._servir_ficheiro_saida(self, rota)
                if rota.startswith("/previa/"):
                    return servidor._servir_previa(self, rota)
                return self._texto("Não encontrado", 404, "text/plain; charset=utf-8")

            def do_POST(self):
                rota = urlparse(self.path).path

                # A verificação anti-CSRF corre ANTES da sessão, e também na
                # entrada: um formulário de terceiros não deve sequer conseguir
                # tentar adivinhar senhas através do browser de quem está lá.
                recusa = self._verificar_escrita()
                if recusa:
                    _painel.info(f"escrita recusada de {self.client_address[0]}: {recusa}")
                    return self._json({"ok": False, "erro": recusa}, 403)

                dados = self._ler_corpo_json()

                if rota == "/api/entrar":
                    return servidor._entrar(self, dados)

                sessao = self._exigir_sessao()
                if sessao is None:
                    return None
                utilizador = sessao["nome"]

                if rota == "/api/editar":
                    reg = servidor.registo.editar(
                        dados.get("id"), dados.get("campos", {}), utilizador=utilizador)
                    return self._json({"ok": bool(reg), "registo": reg})

                if rota == "/api/estado":
                    return servidor._mudar_estado(self, dados, sessao)

                if rota == "/api/senha":
                    return servidor._mudar_senha(self, dados, sessao)

                if rota == "/api/utilizadores":
                    if not self._exigir_administrador(sessao):
                        return None
                    return servidor._gerir_utilizadores(self, dados, sessao)

                return self._json({"ok": False, "erro": "Rota desconhecida"}, 404)

        self._httpd = ThreadingHTTPServer((host, porta), Handler)
        url = f"http://{host if host!='0.0.0.0' else '<IP-do-servidor>'}:{porta}/"
        _painel.info(f"a servir em {url}  (Ctrl+C para parar)")
        # Diagnóstico útil sem revelar a senha: mostra o comprimento, para o
        # utilizador confirmar que foi lida (e não está vazia). Se aqui aparecer
        # "0 caracteres", o config.json não foi lido — é o problema de login.
        nomes = ", ".join(c["nome"] for c in self.contas.listar() if c["activo"])
        _painel.info(f"contas activas: {nomes}")
        if bloquear:
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[PAINEL] terminado.")
        else:
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    # ---- entrada e contas -------------------------------------------------
    def _servir_entrada(self, handler):
        """Envia a página de entrada (o formulário de início de sessão)."""
        caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entrada.html")
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                return handler._texto(f.read())
        return handler._texto("<h1>Página de entrada não encontrada</h1>", 500)

    def _entrar(self, handler, dados):
        """Valida credenciais e abre sessão, devolvendo o cookie.

        A mensagem de recusa é sempre a mesma, seja o utilizador inexistente, a
        senha errada, a conta desativada ou trancada. Distinguir seria cómodo
        para quem entra e uma prenda para quem tenta: diria logo quais os nomes
        que existem.
        """
        nome = str(dados.get("utilizador", "")).strip()
        senha = str(dados.get("senha", ""))
        ip = handler.client_address[0]
        bloqueado, restam = self._bloqueado(ip)
        if bloqueado:
            return handler._json({"ok": False, "erro":
                                  f"Demasiadas tentativas. Aguarde {restam} segundos."}, 429)
        conta = self.contas.autenticar(nome, senha)
        if not conta:
            self._falhou(ip)
            _painel.info(f"entrada recusada para '{nome}' de {ip}")
            return handler._json({"ok": False,
                                  "erro": "Utilizador ou senha incorretos."}, 401)
        self._acertou(ip)
        testemunho = self.contas.abrir_sessao(conta)
        _painel.info(f"{conta['nome']} entrou de {ip}")
        corpo = json.dumps({"ok": True, "nome_completo": conta["nome_completo"],
                            "papel": conta["papel"]}, ensure_ascii=False).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(corpo)))
        # HttpOnly: o testemunho fica fora do alcance de qualquer JavaScript, por
        # isso uma falha de XSS não o consegue roubar. SameSite=Strict: o browser
        # não o envia em pedidos nascidos noutro sítio, o que fecha o CSRF na
        # própria raiz, a par das verificações que já existiam.
        handler.send_header("Set-Cookie",
                            f"{COOKIE_SESSAO}={testemunho}; Path=/; HttpOnly; "
                            f"SameSite=Strict; Max-Age={utl.MINUTOS_DE_SESSAO * 60}")
        handler._cabecalhos_seguranca()
        handler.end_headers()
        return handler.wfile.write(corpo)

    def _mudar_senha(self, handler, dados, sessao):
        """Muda a senha do próprio utilizador da sessão."""
        try:
            self.contas.mudar_senha(sessao["nome"], str(dados.get("nova", "")),
                                    senha_atual=str(dados.get("atual", "")))
        except utl.ErroDeUtilizador as e:
            return handler._json({"ok": False, "erro": str(e)}, 400)
        _painel.info(f"{sessao['nome']} mudou a senha")
        # Mudar a senha fecha as sessões da conta, incluindo esta: quem mudou
        # volta a entrar. É o comportamento certo se a senha foi mudada por
        # suspeita de a terem descoberto.
        return handler._json({"ok": True, "entrar": True})

    def _gerir_utilizadores(self, handler, dados, sessao):
        """Cria contas, repõe senhas e ativa/desativa, a pedido de um administrador."""
        acao = dados.get("acao")
        try:
            if acao == "criar":
                conta = self.contas.criar(
                    dados.get("nome", ""), dados.get("senha", ""),
                    nome_completo=dados.get("nome_completo", ""),
                    papel=dados.get("papel", utl.OPERADOR), por=sessao["nome"])
                _painel.info(f"{sessao['nome']} criou a conta {conta['nome']}")
                return handler._json({"ok": True, "utilizador": conta})
            if acao == "repor_senha":
                self.contas.mudar_senha(dados.get("nome", ""), dados.get("senha", ""))
                _painel.info(f"{sessao['nome']} repôs a senha de {dados.get('nome')}")
                return handler._json({"ok": True})
            if acao == "activo":
                alvo = dados.get("nome", "")
                if alvo == sessao["nome"]:
                    # Sem isto, um administrador distraído desativa-se a si
                    # próprio e, se for o único, tranca o painel para toda a gente.
                    return handler._json({"ok": False,
                                          "erro": "Não pode desativar a sua própria conta."}, 400)
                self.contas.definir_activo(alvo, bool(dados.get("valor")))
                return handler._json({"ok": True})
        except utl.ErroDeUtilizador as e:
            return handler._json({"ok": False, "erro": str(e)}, 400)
        return handler._json({"ok": False, "erro": f"Ação desconhecida: {acao}"}, 400)

    # ---- estado e certidão ------------------------------------------------
    def _mudar_estado(self, handler, dados, sessao):
        """Move um edital de estado e, se isso mexe no ecrã, republica a TV."""
        estado = dados.get("estado")
        res = self.registo.mover_estado(dados.get("id"), estado,
                                        utilizador=sessao["nome"],
                                        nota=dados.get("nota", ""))
        if res["ok"] and estado in (reg_mod.PUBLICADO, reg_mod.RETIRADO):
            self.republicar()
        if res["ok"]:
            _painel.info(f"{sessao['nome']}: registo #{dados.get('id')} -> {estado}")
        return handler._json(res)

    def _servir_certidao(self, handler, rota, sessao):
        """Gera e envia a certidão de afixação de um edital, em PDF.

        Gerada no momento e não guardada em disco, de propósito: a certidão é
        uma vista do registo, e o registo é a fonte. Guardar cópias criaria a
        pergunta de qual delas vale quando o registo for corrigido — e a
        resposta certa é que vale sempre o registo. Quem precisar de a arquivar,
        arquiva o PDF que descarregou, e o selo de conferência permite
        confirmar mais tarde que corresponde ao que o registo diz.
        """
        try:
            rid = int(rota[len("/certidao/"):].split("/")[0])
        except (ValueError, IndexError):
            return handler._texto("Registo inválido", 400, "text/plain; charset=utf-8")
        reg = next((r for r in self.registo.todos() if r["id"] == rid), None)
        if reg is None:
            return handler._texto("Registo não encontrado", 404, "text/plain; charset=utf-8")
        if not reg.get("afixado_em"):
            return handler._texto(
                "Este edital ainda não foi afixado — não há o que certificar.",
                409, "text/plain; charset=utf-8")
        nomes = {c["nome"]: c["nome_completo"] for c in self.contas.listar()}
        pdf = cert_mod.gerar(reg, self.cfg, emitida_por=sessao["nome"],
                             nome_de_quem_emite=sessao["nome_completo"],
                             nomes_completos=nomes)
        _painel.info(f"{sessao['nome']} emitiu a certidão do registo #{rid}")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/pdf")
        handler.send_header("Content-Length", str(len(pdf)))
        handler.send_header("Content-Disposition",
                            f'attachment; filename="{cert_mod.nome_do_ficheiro(reg)}"')
        handler._cabecalhos_seguranca()
        handler.end_headers()
        return handler.wfile.write(pdf)

    # ---- servir ficheiros -------------------------------------------------
    def _servir_html(self, handler):
        """Envia a página do painel (o ficheiro HTML do front-end)."""
        if self.painel_html_path and os.path.exists(self.painel_html_path):
            with open(self.painel_html_path, encoding="utf-8") as f:
                return handler._texto(f.read())
        return handler._texto("<h1>Painel não encontrado</h1>", 500)

    def _servir_ficheiro_saida(self, handler, rota):
        """Serve um PNG para pré-visualização no painel.

        Procura primeiro na pasta saida/ (editais ativos). Se não estiver lá — o
        que acontece com os RETIRADOS, cujo PNG foi movido para o arquivo — tenta
        servi-lo diretamente de dentro do ZIP de arquivo, sem o extrair para disco.
        Assim o painel mostra a imagem dos editais arquivados sem os "ressuscitar"
        na pasta.

        Protege contra travessia de diretórios (../).
        """
        nome = os.path.basename(rota[len("/saida/"):])
        caminho = _dentro_de(self.cfg["saida"], nome)
        if caminho is None:
            return handler._texto("Proibido", 403, "text/plain")
        tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        # 1) Caminho normal: o PNG está na pasta (edital ativo).
        if os.path.exists(caminho):
            with open(caminho, "rb") as f:
                return handler._texto(f.read(), 200, tipo)
        # 2) Recurso: procurar no ZIP de arquivo (edital retirado).
        import zipfile
        zpath = os.path.join(self.cfg.get("arquivo", ""), "arquivo_editais.zip")
        if zpath and os.path.exists(zpath):
            try:
                with zipfile.ZipFile(zpath, "r") as z:
                    if nome in z.namelist():
                        return handler._texto(z.read(nome), 200, tipo)
            except Exception:
                pass
        return handler._texto("Não encontrado", 404, "text/plain")

    def _servir_previa(self, handler, rota):
        """Serve uma pré-visualização leve (JPEG) da pasta previas/.

        Protege contra travessia de diretórios. Estas imagens existem logo no
        rascunho, ao contrário dos PNG finais que só surgem na publicação.
        """
        nome = os.path.basename(rota[len("/previa/"):])
        caminho = _dentro_de(self.cfg["previas"], nome)
        if caminho is None:
            return handler._texto("Proibido", 403, "text/plain")
        if not os.path.exists(caminho):
            return handler._texto("Não encontrado", 404, "text/plain")
        tipo = mimetypes.guess_type(caminho)[0] or "image/jpeg"
        with open(caminho, "rb") as f:
            # O 'return' faltava aqui. Não tinha consequência (a resposta já fora
            # escrita), mas uma assimetria destas entre duas funções irmãs é como
            # nasce o defeito seguinte.
            return handler._texto(f.read(), 200, tipo)


def _dentro_de(pasta_base, nome):
    """Devolve o caminho de 'nome' dentro de 'pasta_base', ou None se escapar dela.

    Substitui o `os.path.abspath(x).startswith(os.path.abspath(base))` que estava
    nos dois servidores de ficheiros. Esse teste é comparação de prefixo de
    texto, e '/dados/saida_antiga' começa por '/dados/saida' — um nome de pasta
    vizinho passava a barreira. Aqui a comparação é de caminhos resolvidos, que
    é o que a pergunta realmente é.

    Hoje o os.path.basename() a montante já neutralizava a travessia, por isso
    não era explorável; corrige-se o padrão para não voltar a depender disso.

    Args:
        pasta_base (str): pasta que delimita o acesso.
        nome (str): nome de ficheiro pedido.

    Returns:
        str | None: caminho absoluto seguro, ou None se ficar fora da pasta.
    """
    base = Path(pasta_base).resolve()
    alvo = (base / nome).resolve()
    return str(alvo) if alvo == base or base in alvo.parents else None
