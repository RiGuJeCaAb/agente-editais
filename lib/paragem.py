"""
paragem.py — Parar o agente sem deixar um documento a meio.

Receber um documento são quatro passos: arquivar o original, criar o rascunho
(o evento vai para o jornal de auditoria e só depois o registo é gravado), gerar
as pré-visualizações e tirar o ficheiro da entrada. O agente não tratava o
SIGTERM, e um `systemctl stop` matava-o onde estivesse. Entre o jornal e o
registo, o jornal ficava com um id que o registo não tinha, e o rascunho
seguinte reutilizava-o. Entre o registo e a mudança de pasta, o ficheiro ficava
na entrada para sempre, saltado em todas as voltas por o resumo já existir. Ver
a issue #29.

Isto é o porteiro desse trabalho. Cada peça que não pode ficar a meio — um
documento a ser recebido, uma publicação — entra e sai por aqui. Pedida a
paragem, não entra mais nenhuma, e quem pediu espera que as que estão dentro
acabem. Não é uma fila nem cancela nada: o agente faz poucas coisas ao mesmo
tempo, e o que falta é saber quando nenhuma delas está a meio.
"""
from __future__ import annotations

import threading


class Paragem:
    """Conta o trabalho em curso que não pode ficar a meio, e deixa esperar por ele.

    Attributes:
        pedida (threading.Event): fica posto quando alguém pede para parar. A
            vigia dorme nele em vez de num sleep, para acordar logo.
    """

    def __init__(self) -> None:
        """Começa sem trabalho em curso e sem paragem pedida."""
        self._cond = threading.Condition()
        self._em_curso = 0
        self.pedida = threading.Event()

    def entrar(self) -> bool:
        """Regista o início de uma peça de trabalho, se ainda for permitido.

        A verificação e a contagem fazem-se debaixo do mesmo lock da paragem: de
        outra forma uma peça podia começar no instante entre o pedido e a
        espera, e quem pediu saía com ela a meio.

        Returns:
            bool: False se a paragem já foi pedida. Quem recebe False não começa,
            e não chama sair().
        """
        with self._cond:
            if self.pedida.is_set():
                return False
            self._em_curso += 1
            return True

    def sair(self) -> None:
        """Regista o fim de uma peça começada com entrar()."""
        with self._cond:
            self._em_curso -= 1
            self._cond.notify_all()

    def pedir_e_esperar(self, limite: float) -> bool:
        """Pede a paragem e espera que o trabalho em curso acabe.

        Args:
            limite: segundos de espera, no máximo. Tem de ficar abaixo do
                TimeoutStopSec da unidade systemd: passado esse, o systemd mata
                o processo, e mais vale sair a dizer que ficou trabalho a meio do
                que ser morto sem dizer nada.

        Returns:
            bool: True se tudo acabou; False se o limite passou com trabalho
            ainda em curso.
        """
        with self._cond:
            self.pedida.set()
            return self._cond.wait_for(lambda: self._em_curso == 0, timeout=limite)
