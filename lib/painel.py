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
import os, json, html, base64, mimetypes, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import registo as reg_mod


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
            def _json(self, obj, code=200):
                corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def _texto(self, corpo, code=200, tipo="text/html; charset=utf-8"):
                if isinstance(corpo, str):
                    corpo = corpo.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
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
                cab = self.headers.get("Authorization", "")
                if not cab.startswith("Basic "):
                    return None
                try:
                    dec = base64.b64decode(cab[6:]).decode("utf-8")
                    utilizador, _, senha = dec.partition(":")
                except Exception:
                    return None
                if senha != servidor.cfg.get("painel_senha"):
                    return None
                return utilizador or "utilizador"

            def _pedir_login(self):
                self.send_response(401)
                self.send_header("WWW-Authenticate",
                                 'Basic realm="Painel de Editais CMMB"')
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
                if self._verificar_sessao() is None:
                    return self._pedir_login()
                utilizador = self._verificar_sessao()
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
        caminho = os.path.join(self.cfg["saida"], nome)
        # Barreira de segurança: o ficheiro tem mesmo de estar dentro de saida/.
        if not os.path.abspath(caminho).startswith(os.path.abspath(self.cfg["saida"])):
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
        caminho = os.path.join(self.cfg["previas"], nome)
        if not os.path.abspath(caminho).startswith(os.path.abspath(self.cfg["previas"])):
            return handler._texto("Proibido", 403, "text/plain")
        if not os.path.exists(caminho):
            return handler._texto("Não encontrado", 404, "text/plain")
        tipo = mimetypes.guess_type(caminho)[0] or "image/jpeg"
        with open(caminho, "rb") as f:
            handler._texto(f.read(), 200, tipo)
