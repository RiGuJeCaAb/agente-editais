# -*- coding: utf-8 -*-
"""
painel.py — Servidor web do painel de gestão dos editais (back-end).

Serve o painel no browser local e expõe uma API mínima para o front-end operar
o registo de entrada (listar, editar, mudar de estado). Usa apenas a biblioteca
padrão do Python (http.server) — ZERO dependências novas, para não complicar a
instalação no município.

Segurança (versão honesta, como combinado):
  - o acesso ao painel é protegido por UMA senha partilhada (definida em
    config.json -> "painel_senha"); sem senha definida, o painel recusa arrancar,
    para nunca ficar aberto por esquecimento;
  - cada ação exige o NOME do utilizador, que fica no trilho de auditoria;
  - NÃO é autenticação empresarial. O gancho para ligar ao Active Directory /
    Entra ID da CMMB fica identificado em _verificar_sessao() para evolução futura.

Isto é deliberado: fazer SSO/LDAP a sério exige testes e integração com a vossa
infraestrutura, que não se fazem à séria num único passo. Melhor uma proteção
simples e honesta do que uma complexa e furada.
"""
from __future__ import annotations
import base64
import hmac
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import registo as reg_mod

# Cabeçalho próprio que o painel envia em todos os pedidos de escrita. É metade
# da defesa contra CSRF: um <form> de outro sítio consegue enviar um POST com as
# credenciais Basic em cache, mas NÃO consegue pôr um cabeçalho personalizado —
# isso exigiria CORS com pedido prévio (preflight), que este servidor nunca
# autoriza. A outra metade é exigir Content-Type: application/json, que um
# formulário simples também não consegue produzir.
CABECALHO_PEDIDO = "X-Painel-Pedido"

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


class PainelServer:
    """Encapsula o servidor do painel e as dependências que ele precisa.

    Guarda referências ao registo de entrada, à configuração e a um callback de
    'republicar' (que o agente fornece para regenerar a página da TV e o ZIP
    sempre que algo muda de estado).
    """

    def __init__(self, registo: reg_mod.RegistoEntrada, cfg: dict,
                 republicar_callback=None, painel_html_path=None):
        """
        Args:
            registo (RegistoEntrada): o gestor do registo de entrada.
            cfg (dict): configuração do agente (senha, saída, etc.).
            republicar_callback (callable|None): função sem argumentos que
                regenera a página da TV + ZIP; chamada após publicar/retirar.
            painel_html_path (str|None): caminho do ficheiro HTML do painel.
        """
        self.registo = registo
        self.cfg = cfg
        self.republicar = republicar_callback or (lambda: None)
        self.painel_html_path = painel_html_path
        self._httpd = None
        # Contagem de falhas de senha por endereço: {ip: [falhas, bloqueado_ate]}.
        self._falhas = {}
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
            ate = time.time() + SEGUNDOS_DE_BLOQUEIO if falhas >= TENTATIVAS_ANTES_DE_BLOQUEAR else 0.0
            self._falhas[ip] = (falhas, ate)
            if ate:
                print(f"[PAINEL] {falhas} senhas erradas de {ip} — bloqueado "
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
        if not self.cfg.get("painel_senha"):
            raise RuntimeError(
                "Sem 'painel_senha' em config.json — o painel não arranca sem senha. "
                "Define uma senha de acesso antes de usar o painel.")
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

            # -- autenticação (versão simples e honesta) --
            def _verificar_sessao(self):
                """Valida o acesso via HTTP Basic com a senha partilhada.

                GANCHO FUTURO: é aqui que se ligaria ao Active Directory / Entra ID
                da CMMB (validar credenciais contra LDAP/OAuth) em vez da senha
                partilhada. A assinatura mantém-se, o resto do código não muda.

                Returns:
                    str|None: o nome do utilizador (parte do Basic Auth) se válido;
                    None se falhar.
                """
                self._bloqueio_restante = 0
                ip = self.client_address[0]
                bloqueado, restam = servidor._bloqueado(ip)
                if bloqueado:
                    self._bloqueio_restante = restam
                    return None
                cab = self.headers.get("Authorization", "")
                if not cab.startswith("Basic "):
                    return None
                try:
                    dec = base64.b64decode(cab[6:]).decode("utf-8")
                    utilizador, _, senha = dec.partition(":")
                except Exception:
                    return None
                # compare_digest e não '!=': a comparação de strings do Python sai
                # no primeiro carácter diferente, e o tempo que demora revela
                # quantos caracteres iniciais estavam certos. Numa rede local isso
                # é difícil de explorar, mas a correção é uma linha.
                # Em bytes, e não em str: o compare_digest lança TypeError com
                # strings que tenham caracteres fora de ASCII, e uma senha com
                # cedilha ou acento é das coisas mais prováveis num município
                # português. Codificar em UTF-8 resolve e mantém o tempo constante.
                if not hmac.compare_digest(senha.encode("utf-8"),
                                           str(servidor.cfg.get("painel_senha", "")).encode("utf-8")):
                    servidor._falhou(ip)
                    return None
                servidor._acertou(ip)
                return utilizador or "utilizador"

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

            def _pedir_login(self):
                restam = getattr(self, "_bloqueio_restante", 0)
                if restam:
                    # Enquanto bloqueado, responde-se 429 e NÃO se manda o browser
                    # pedir senha outra vez: repetir o pedido de credenciais
                    # convidaria a continuar a tentar.
                    return self._texto(
                        f"Demasiadas tentativas. Tente de novo dentro de {restam} s.",
                        429, "text/plain; charset=utf-8")
                self.send_response(401)
                self.send_header("WWW-Authenticate",
                                 'Basic realm="Painel de Editais CMMB"')
                self._cabecalhos_seguranca()
                self.end_headers()

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
                # Página principal do painel.
                if rota in ("/", "/index.html", "/painel"):
                    if self._verificar_sessao() is None:
                        return self._pedir_login()
                    return servidor._servir_html(self)
                # API: listar registos.
                if rota == "/api/registos":
                    if self._verificar_sessao() is None:
                        return self._pedir_login()
                    return self._json({"registos": servidor.registo.todos(),
                                       "estados": reg_mod.ESTADO_LABEL})
                # Pré-visualização de um PNG já gerado (para o painel mostrar).
                if rota.startswith("/saida/"):
                    if self._verificar_sessao() is None:
                        return self._pedir_login()
                    return servidor._servir_ficheiro_saida(self, rota)
                # Pré-visualização LEVE do documento (existe já no rascunho, para
                # o funcionário ver o documento enquanto valida).
                if rota.startswith("/previa/"):
                    if self._verificar_sessao() is None:
                        return self._pedir_login()
                    return servidor._servir_previa(self, rota)
                return self._texto("Não encontrado", 404, "text/plain; charset=utf-8")

            def do_POST(self):
                utilizador = self._verificar_sessao()
                if utilizador is None:
                    return self._pedir_login()
                # Só depois de autenticado: a origem do pedido tem de ser o painel.
                recusa = self._verificar_escrita()
                if recusa:
                    print(f"[PAINEL] escrita recusada de {self.client_address[0]}: {recusa}")
                    return self._json({"ok": False, "erro": recusa}, 403)
                rota = urlparse(self.path).path
                dados = self._ler_corpo_json()

                # Editar campos de um registo.
                if rota == "/api/editar":
                    reg = servidor.registo.editar(
                        dados.get("id"), dados.get("campos", {}), utilizador=utilizador)
                    return self._json({"ok": bool(reg), "registo": reg})

                # Mudar o estado de um registo (validar/publicar/retirar/devolver).
                if rota == "/api/estado":
                    res = servidor.registo.mover_estado(
                        dados.get("id"), dados.get("estado"),
                        utilizador=utilizador, nota=dados.get("nota", ""))
                    # Se a mudança afeta o que está no ar, republica a TV.
                    if res["ok"] and dados.get("estado") in (reg_mod.PUBLICADO,
                                                             reg_mod.RETIRADO):
                        servidor.republicar()
                    return self._json(res)

                return self._json({"ok": False, "erro": "Rota desconhecida"}, 404)

        self._httpd = ThreadingHTTPServer((host, porta), Handler)
        url = f"http://{host if host!='0.0.0.0' else '<IP-do-servidor>'}:{porta}/"
        print(f"[PAINEL] a servir em {url}  (Ctrl+C para parar)")
        # Diagnóstico útil sem revelar a senha: mostra o comprimento, para o
        # utilizador confirmar que foi lida (e não está vazia). Se aqui aparecer
        # "0 caracteres", o config.json não foi lido — é o problema de login.
        _senha = self.cfg.get("painel_senha", "")
        print(f"[PAINEL] senha de acesso: configurada ({len(_senha)} caracteres). "
              f"Utilizador: escreva o SEU nome (qualquer), a senha é a do config.json.")
        if bloquear:
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n[PAINEL] terminado.")
        else:
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

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
