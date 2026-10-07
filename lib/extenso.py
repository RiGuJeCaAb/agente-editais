"""
extenso.py — Números, datas e horas escritos por palavras.

Existe por causa da certidão. Um documento que vai para um processo escreve as
datas por extenso desde que há certidões, e não é adorno: um algarismo altera-se
com um traço de caneta e «vinte e nove» não. Era por isso que os livros de notas
se escreviam assim, e é por isso que a certidão desta aplicação voltou a essa
forma.

Português EUROPEU, que aqui não é detalhe de estilo: «catorze», «dezasseis»,
«dezassete» e «dezanove» — e não as formas brasileiras com 'e'. Uma certidão
emitida por um município português com «quatorze» lá dentro é uma certidão com
um erro de português à vista de quem a receber.

Meses em minúscula, que é o que a norma em vigor manda. A certidão vai buscar o
seu ar antigo à estrutura e às fórmulas, não a erros de ortografia.
"""
from __future__ import annotations

from datetime import date, datetime

# 0 a 19 têm nome próprio; daí para cima compõem-se.
_ATE_DEZANOVE = (
    "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito",
    "nove", "dez", "onze", "doze", "treze", "catorze", "quinze", "dezasseis",
    "dezassete", "dezoito", "dezanove")

_DEZENAS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
            "setenta", "oitenta", "noventa")

# «cem» só quando está sozinho; seguido de mais alguma coisa é «cento».
_CENTENAS = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
             "seiscentos", "setecentos", "oitocentos", "novecentos")

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")

# Em português, «um», «dois» e as centenas a partir de duzentos concordam em
# género. «dois folhas» e «pelas dois horas» são erros que saltam à cara de
# quem recebe uma certidão, e a primeira versão deste módulo escrevia-os: só
# tinha a forma masculina. O resto do vocabulário é invariável — «cem», «mil»,
# «doze», «vinte» —, e por isso a tabela é curta.
_FEMININOS = {
    "um": "uma", "dois": "duas",
    "duzentos": "duzentas", "trezentos": "trezentas",
    "quatrocentos": "quatrocentas", "quinhentos": "quinhentas",
    "seiscentos": "seiscentas", "setecentos": "setecentas",
    "oitocentos": "oitocentas", "novecentos": "novecentas",
}


# Escreve por palavras um número de 0 a 999.
def _ate_novecentos(n: int) -> str:
    """Devolve a parte de 0 a 999 escrita por palavras.

    Separado de numero() porque é o bloco que se repete: o mesmo pedaço serve
    as unidades de milhar e o resto, e escrevê-lo duas vezes era convidar as
    duas cópias a divergirem.
    """
    if n < 20:
        return _ATE_DEZANOVE[n]
    if n < 100:
        dezena, unidade = divmod(n, 10)
        return _DEZENAS[dezena] + (f" e {_ATE_DEZANOVE[unidade]}" if unidade else "")
    if n == 100:
        return "cem"
    centena, resto = divmod(n, 100)
    return _CENTENAS[centena] + (f" e {_ate_novecentos(resto)}" if resto else "")


# Escreve um número inteiro por palavras, em português europeu.
def numero(n: int) -> str:
    """Devolve um inteiro de 0 a 9999 escrito por palavras.

    O limite chega e sobra para o que a certidão escreve: dias do mês, horas,
    minutos, anos, folhas e dias de afixação. Acima disso devolve os algarismos,
    porque uma certidão com um número errado por extenso é pior do que uma
    certidão com algarismos.

    A regra do «e» a seguir aos milhares é a que faz tropeçar quem escreve isto
    de cabeça: há «e» quando o que sobra é menor que cem ou é uma centena
    redonda — «dois mil e vinte e seis», «dois mil e cem» — e não há quando o
    resto tem centenas E mais alguma coisa: «dois mil cento e cinquenta».

    Args:
        n (int): o número.

    Returns:
        str: o número por palavras, ou em algarismos se estiver fora do alcance.
    """
    if not isinstance(n, int) or n < 0 or n > 9999:
        return str(n)
    if n < 1000:
        return _ate_novecentos(n)
    milhares, resto = divmod(n, 1000)
    cabeca = "mil" if milhares == 1 else f"{_ate_novecentos(milhares)} mil"
    if not resto:
        return cabeca
    ligacao = " e " if (resto < 100 or resto % 100 == 0) else " "
    return cabeca + ligacao + _ate_novecentos(resto)


# Escreve um número por palavras, no feminino.
def numero_f(n: int) -> str:
    """Devolve o número por palavras a concordar com um nome feminino.

    «duas folhas», «pelas duas horas», «duzentas folhas», «vinte e uma folhas».
    Converte os termos COMPLETOS e não os finais de palavra: «doze» acaba em
    «ze» e não leva nada, mas «cento e dois» tem de dar «cento e duas» e «dois
    mil» tem de dar «duas mil».
    """
    return " ".join(_FEMININOS.get(palavra, palavra)
                    for palavra in numero(n).split())


# Escreve uma data para ser citada no meio de uma frase.
def data(valor: str | date | datetime) -> str:
    """Devolve a data na forma «vinte e nove de junho de 2026».

    É a forma de CITAR uma data — «com data de ...», «prevista para ...». Para
    datar um ato, que leva a fórmula longa e a preposição, usa-se o aos().

    O ano vai em algarismos de propósito. Experimentei com ele por extenso e
    numa certidão que cita leis com ano, prazos com ano e um edital com ano, a
    frase deixava de se ler. O dia por extenso é o que protege contra a rasura;
    o ano repete-se tantas vezes no documento que ninguém o altera sem que salte
    à vista.
    """
    d = _para_data(valor)
    if d is None:
        return str(valor)
    return f"{numero(d.day)} de {MESES[d.month - 1]} de {d.year}"


# Data um ato, com a fórmula e a preposição que a certidão usa.
def aos(valor: str | date | datetime) -> str:
    """Devolve «aos vinte e nove dias do mês de junho de 2026».

    Traz a preposição de dentro porque ela muda com o dia: no primeiro do mês
    não se diz «aos um dia», diz-se «AO PRIMEIRO dia». A versão anterior deixava
    o «aos» a cargo de quem chamava e escrevia «aos um dia do mês de março» —
    numa certidão, em todos os dias 1 de todos os meses.

    Args:
        valor: data ISO (os 10 primeiros caracteres bastam), date ou datetime.

    Returns:
        str: a fórmula completa, ou o valor original se não for interpretável.
    """
    d = _para_data(valor)
    if d is None:
        return str(valor)
    cauda = f"do mês de {MESES[d.month - 1]} de {d.year}"
    if d.day == 1:
        return f"ao primeiro dia {cauda}"
    return f"aos {numero(d.day)} dias {cauda}"


# Escreve a hora como a escreve uma certidão.
def hora(valor: str | datetime) -> str:
    """Devolve a hora na forma «pelas nove horas e catorze minutos».

    Inclui a preposição porque ela muda com o número — «pela uma hora», «pelas
    nove horas» — e deixá-la a cargo de quem chama era espalhar a concordância
    por todo o lado onde a certidão cita uma hora.

    As HORAS são femininas e os MINUTOS masculinos: «pelas duas horas e dois
    minutos». A primeira versão usava a forma masculina nos dois e escrevia
    «pelas dois horas».

    Args:
        valor: instante ISO ou datetime.

    Returns:
        str: a hora por palavras, ou o valor original se não for interpretável.
    """
    t = _para_datahora(valor)
    if t is None:
        return str(valor)
    h, m = t.hour, t.minute
    if h == 0:
        cabeca = "pelas zero horas"
    elif h == 1:
        cabeca = "pela uma hora"
    else:
        cabeca = f"pelas {numero_f(h)} horas"
    if not m:
        return cabeca
    return cabeca + (" e um minuto" if m == 1 else f" e {numero(m)} minutos")


# Diz quantas folhas, em palavras e com o plural certo.
def folhas(n: int) -> str:
    """Devolve «uma folha», «duas folhas», e nada quando o número não se sabe.

    «Folha» é feminino, e por isso o número também tem de o ser: a primeira
    versão escrevia «dois folhas» e «duzentos folhas».
    """
    if not n:
        return ""
    return "uma folha" if n == 1 else f"{numero_f(n)} folhas"


# Diz quantos dias durou, em palavras e com o plural certo.
def dias(n: int) -> str:
    """Devolve a duração em dias por palavras.

    «Dia» é masculino, e portanto fica com a forma de numero(): «dois dias».

    Zero dias não existe em português corrente: um edital afixado de manhã e
    retirado à tarde não esteve afixado zero dias, esteve afixado nesse dia.
    """
    if n <= 0:
        return "menos de um dia"
    return "um dia" if n == 1 else f"{numero(n)} dias"


# --- auxiliares de conversão ------------------------------------------------
def _para_data(valor):
    """Aceita date, datetime ou texto ISO e devolve um date, ou None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


def _para_datahora(valor):
    """Aceita datetime ou texto ISO e devolve um datetime, ou None."""
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.fromisoformat(str(valor))
    except (ValueError, TypeError):
        return None
