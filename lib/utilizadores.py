"""
utilizadores.py — Contas individuais, senhas derivadas e sessões do painel.

Porque existe: até aqui o painel tinha UMA senha partilhada e o nome do
utilizador era texto livre no Basic Auth. Quem soubesse a senha assinava com o
nome que quisesse — está reproduzido nos testes da Onda 1, onde uma ação ficou
registada em nome de "qualquer.nome". Num organismo público isso é pior do que
não ter auditoria nenhuma, porque dá falsa confiança a um registo que não
aguenta a primeira pergunta séria.

E a partir desta onda deixa de ser só uma questão de higiene: a certidão de
afixação diz, a preto e branco, QUEM afixou o edital. Se a identidade não for
verificável, o documento que a aplicação emite não vale o papel.

Decisões, e porquê:

  - **scrypt da biblioteca padrão**, e não bcrypt ou argon2. Mantém a promessa
    de zero dependências novas, que é o que permite instalar isto num posto
    municipal sem passar pelos serviços informáticos. scrypt é uma função de
    derivação com custo de memória, portanto resiste a ataque por GPU, que é o
    que interessa aqui.
  - **Parâmetros guardados com cada senha.** Custa três campos e permite
    aumentar o custo no futuro sem invalidar as contas existentes: quem entra
    com parâmetros antigos vê a senha re-derivada com os novos, sem dar por isso.
  - **Sessões em memória, não em disco.** Reiniciar o agente termina as sessões,
    o que é o comportamento certo: uma sessão é um estado vivo, não um registo.
    Poupa também um ficheiro com segredos a mais no disco.
  - **Dois papéis apenas**, operador e administrador. Três seria arquitetura a
    mais para um serviço com meia dúzia de pessoas; um só não chega, porque
    criar contas não pode ser coisa que qualquer operador faça.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime

import armazenamento as arm

# Custo da derivação. n=2^15 são ~34 MB e ~165 ms por tentativa nesta geração de
# máquinas: fica muito acima do que o Python aceita sem maxmem explícito, e
# continua imediato para quem entra. Subir isto no futuro é seguro — as contas
# existentes re-derivam sozinhas na entrada seguinte.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_BYTES = 32

# Sessão inativa expira. Trinta minutos é o compromisso entre não interromper
# quem está a validar um lote de editais e não deixar um posto aberto à tarde
# inteira porque alguém foi almoçar.
MINUTOS_DE_SESSAO = 30

OPERADOR = "operador"
ADMINISTRADOR = "administrador"
PAPEIS = (OPERADOR, ADMINISTRADOR)

PAPEL_LABEL = {OPERADOR: "Operador", ADMINISTRADOR: "Administrador"}

# Tentativas falhadas antes de a CONTA ficar trancada, a par do limite por
# endereço que já existia. São defesas diferentes: o limite por endereço trava
# quem varre senhas de um sítio, o limite por conta trava quem varre a mesma
# conta a partir de vários sítios.
TENTATIVAS_POR_CONTA = 10
MINUTOS_DE_TRANCA = 15


class ErroDeUtilizador(Exception):
    """Falha previsível na gestão de contas, com mensagem própria para mostrar."""


def _derivar(senha: str, sal: bytes, n: int = SCRYPT_N, r: int = SCRYPT_R,
             p: int = SCRYPT_P) -> bytes:
    """Deriva a chave de uma senha com scrypt.

    O maxmem tem de ser passado explicitamente: acima de n=2^14 o OpenSSL recusa
    com 'memory limit exceeded', porque o limite por omissão do Python é menor
    do que o que estes parâmetros precisam. Dar-lhe o dobro do necessário deixa
    folga para variações entre versões da biblioteca.
    """
    return hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=n, r=r, p=p,
                          dklen=SCRYPT_BYTES, maxmem=128 * n * r * 2)


def _agora() -> str:
    """Instante atual em ISO, ao segundo."""
    return datetime.now().isoformat(timespec="seconds")


class Utilizadores:
    """Cofre de contas e sessões do painel.

    Guarda as contas num JSON (escrito de forma atómica, como tudo o resto) e as
    sessões em memória. Todas as operações passam por um lock, porque o painel é
    servido por várias threads.
    """

    def __init__(self, caminho: str):
        """
        Args:
            caminho: ficheiro JSON das contas (criado à primeira conta).
        """
        self.caminho = caminho
        self._lock = threading.RLock()
        self._dados = arm.ler_json(caminho, {"utilizadores": []})
        self._sessoes: dict[str, dict] = {}

    # ---- contas -----------------------------------------------------------
    def criar(self, nome: str, senha: str, *, nome_completo: str = "",
              papel: str = OPERADOR, por: str = "sistema") -> dict:
        """Cria uma conta nova.

        Args:
            nome: identificador de entrada, em minúsculas (ex.: "ana.abreu").
            senha: senha em claro; só a chave derivada é guardada.
            nome_completo: nome como aparece na certidão de afixação.
            papel: OPERADOR ou ADMINISTRADOR.
            por: quem criou a conta (para o histórico).

        Returns:
            dict: a conta criada, já sem a chave nem o sal.

        Raises:
            ErroDeUtilizador: nome inválido, repetido, papel desconhecido ou
                senha curta demais.
        """
        nome = (nome or "").strip().lower()
        if not nome or not all(c.isalnum() or c in "._-" for c in nome):
            raise ErroDeUtilizador(
                "O nome de utilizador só pode ter letras, dígitos, ponto, "
                "traço e sublinhado (ex.: ana.abreu).")
        if papel not in PAPEIS:
            raise ErroDeUtilizador(f"Papel desconhecido: {papel}")
        if len(senha or "") < 10:
            # Dez e não oito: com contas nominais e sem segundo fator, o
            # comprimento é a única defesa que resta. Não se impõem regras de
            # composição de propósito — obrigam a senhas piores e anotadas.
            raise ErroDeUtilizador("A senha tem de ter pelo menos 10 caracteres.")
        with self._lock:
            if self._procurar(nome):
                raise ErroDeUtilizador(f"Já existe um utilizador chamado '{nome}'.")
            sal = os.urandom(16)
            conta = {
                "nome": nome,
                "nome_completo": nome_completo.strip() or nome,
                "papel": papel,
                "activo": True,
                "sal": sal.hex(),
                "chave": _derivar(senha, sal).hex(),
                "scrypt": {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
                "criado_em": _agora(),
                "criado_por": por,
                "ultima_entrada": None,
                "falhas": 0,
                "trancado_ate": 0.0,
            }
            self._dados["utilizadores"].append(conta)
            self._guardar()
            return self._publico(conta)

    def mudar_senha(self, nome: str, senha_nova: str, *, senha_atual: str | None = None) -> None:
        """Muda a senha de uma conta.

        Args:
            nome: conta a alterar.
            senha_nova: a nova senha em claro.
            senha_atual: senha em vigor. Obrigatória quando é o próprio a mudar;
                um administrador a repor a senha de outrem passa None.

        Raises:
            ErroDeUtilizador: conta inexistente, senha atual errada ou nova curta.
        """
        with self._lock:
            conta = self._procurar(nome)
            if not conta:
                raise ErroDeUtilizador(f"Não existe o utilizador '{nome}'.")
            if senha_atual is not None and not self._confere(conta, senha_atual):
                raise ErroDeUtilizador("A senha atual não está correta.")
            if len(senha_nova or "") < 10:
                raise ErroDeUtilizador("A senha tem de ter pelo menos 10 caracteres.")
            sal = os.urandom(16)
            conta["sal"] = sal.hex()
            conta["chave"] = _derivar(senha_nova, sal).hex()
            conta["scrypt"] = {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P}
            conta["falhas"] = 0
            conta["trancado_ate"] = 0.0
            self._guardar()
            # Uma senha mudada termina as outras sessões da mesma conta: se a
            # senha foi mudada por ter sido comprometida, deixar sessões abertas
            # anularia o efeito.
            self._sessoes = {t: s for t, s in self._sessoes.items() if s["nome"] != nome}

    def definir_activo(self, nome: str, activo: bool) -> None:
        """Ativa ou desativa uma conta, sem a apagar.

        Não se apagam contas de propósito: o nome aparece no histórico de
        editais e nas certidões já emitidas, e um registo de auditoria que
        aponta para um utilizador que já não existe é um registo pior.
        """
        with self._lock:
            conta = self._procurar(nome)
            if not conta:
                raise ErroDeUtilizador(f"Não existe o utilizador '{nome}'.")
            conta["activo"] = bool(activo)
            if not activo:
                self._sessoes = {t: s for t, s in self._sessoes.items() if s["nome"] != nome}
            self._guardar()

    def listar(self) -> list[dict]:
        """Todas as contas, sem os campos secretos."""
        with self._lock:
            return [self._publico(c) for c in self._dados["utilizadores"]]

    def ha_contas(self) -> bool:
        """Indica se existe pelo menos uma conta ativa.

        O painel usa isto para recusar arrancar num estado em que ninguém
        conseguiria entrar — e para dizer qual é o comando que resolve.
        """
        with self._lock:
            return any(c["activo"] for c in self._dados["utilizadores"])

    # ---- autenticação -----------------------------------------------------
    def autenticar(self, nome: str, senha: str) -> dict | None:
        """Verifica as credenciais e devolve a conta, ou None.

        Devolve None para conta inexistente, senha errada, conta desativada e
        conta trancada — sem distinguir, de propósito: dizer "esse utilizador
        não existe" entrega a quem tenta a lista de nomes válidos.

        Args:
            nome: nome de entrada.
            senha: senha em claro.

        Returns:
            dict | None: a conta (sem segredos) se as credenciais servirem.
        """
        with self._lock:
            conta = self._procurar((nome or "").strip().lower())
            if not conta or not conta["activo"]:
                # Deriva à mesma, com uma senha falsa, para o tempo de resposta
                # não revelar se o nome existe. Sem isto, um nome inexistente
                # responderia em microssegundos e um existente em ~165 ms.
                _derivar(senha or "", b"sal-de-equilibrio")
                return None
            if conta.get("trancado_ate", 0) > time.time():
                return None
            if not self._confere(conta, senha):
                conta["falhas"] = conta.get("falhas", 0) + 1
                if conta["falhas"] >= TENTATIVAS_POR_CONTA:
                    conta["trancado_ate"] = time.time() + MINUTOS_DE_TRANCA * 60
                self._guardar()
                return None
            conta["falhas"] = 0
            conta["trancado_ate"] = 0.0
            conta["ultima_entrada"] = _agora()
            self._migrar_custo_se_preciso(conta, senha)
            self._guardar()
            return self._publico(conta)

    def _confere(self, conta: dict, senha: str) -> bool:
        """Compara a senha com a chave guardada, em tempo constante."""
        par = conta.get("scrypt", {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P})
        tentativa = _derivar(senha or "", bytes.fromhex(conta["sal"]),
                             n=par["n"], r=par["r"], p=par["p"])
        return hmac.compare_digest(tentativa, bytes.fromhex(conta["chave"]))

    def _migrar_custo_se_preciso(self, conta: dict, senha: str) -> None:
        """Re-deriva a senha com os parâmetros atuais, se os dela forem mais fracos.

        Acontece em silêncio na entrada, que é o único momento em que a senha em
        claro está disponível. É o que permite subir o custo do scrypt daqui a
        uns anos sem obrigar ninguém a mudar de senha.
        """
        if conta.get("scrypt", {}).get("n", 0) >= SCRYPT_N:
            return
        sal = os.urandom(16)
        conta["sal"] = sal.hex()
        conta["chave"] = _derivar(senha, sal).hex()
        conta["scrypt"] = {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P}

    # ---- sessões ----------------------------------------------------------
    def abrir_sessao(self, conta: dict) -> str:
        """Cria uma sessão e devolve o seu testemunho (o valor do cookie).

        O testemunho vem de secrets.token_urlsafe, que usa a fonte de aleatório
        do sistema operativo — e não de random, que é previsível e não serve
        para segredos.
        """
        testemunho = secrets.token_urlsafe(32)
        with self._lock:
            self._sessoes[testemunho] = {
                "nome": conta["nome"],
                "nome_completo": conta["nome_completo"],
                "papel": conta["papel"],
                "aberta_em": time.time(),
                "ultimo_uso": time.time(),
            }
        return testemunho

    def sessao(self, testemunho: str) -> dict | None:
        """Devolve a sessão de um testemunho, renovando-a, ou None se não servir.

        A validade conta-se desde o ÚLTIMO uso e não desde a abertura: quem está
        a trabalhar não é interrompido, quem se ausentou é fechado.
        """
        if not testemunho:
            return None
        with self._lock:
            s = self._sessoes.get(testemunho)
            if not s:
                return None
            if time.time() - s["ultimo_uso"] > MINUTOS_DE_SESSAO * 60:
                del self._sessoes[testemunho]
                return None
            s["ultimo_uso"] = time.time()
            return dict(s)

    def fechar_sessao(self, testemunho: str) -> None:
        """Termina uma sessão (usado pelo botão de sair)."""
        with self._lock:
            self._sessoes.pop(testemunho, None)

    def limpar_sessoes_expiradas(self) -> int:
        """Deita fora as sessões já sem validade, e diz quantas eram.

        Sem isto, um painel exposto a muitos postos acumularia testemunhos em
        memória indefinidamente. É chamado a par da vigia da pasta de entrada.
        """
        limite = time.time() - MINUTOS_DE_SESSAO * 60
        with self._lock:
            velhas = [t for t, s in self._sessoes.items() if s["ultimo_uso"] < limite]
            for t in velhas:
                del self._sessoes[t]
            return len(velhas)

    # ---- auxiliares -------------------------------------------------------
    def _procurar(self, nome: str) -> dict | None:
        """Encontra a conta pelo nome, ou None."""
        for c in self._dados["utilizadores"]:
            if c["nome"] == nome:
                return c
        return None

    @staticmethod
    def _publico(conta: dict) -> dict:
        """Versão de uma conta sem sal, chave nem contadores de falha.

        Existe para nunca haver o risco de um destes campos sair pela API do
        painel por distração de quem escrever a rota seguinte.
        """
        return {k: v for k, v in conta.items()
                if k not in ("sal", "chave", "scrypt", "falhas", "trancado_ate")}

    def _guardar(self) -> None:
        """Grava as contas de forma atómica."""
        arm.gravar_json(self.caminho, self._dados)
