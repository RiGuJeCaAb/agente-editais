"""
test_extenso.py — Números, datas e horas por palavras.

A certidão passou a prosa e passou a escrever as datas por extenso. Isso é
proteção contra rasura, não enfeite: um algarismo altera-se com um traço de
caneta e «vinte e nove» não. Um erro aqui vai impresso num documento que entra
num processo, por isso as formas testam-se uma a uma.

Português EUROPEU. «catorze» e não «quatorze»; «dezasseis», «dezassete» e
«dezanove» e não as formas com 'e'. Uma certidão de um município português com
«quatorze» lá dentro tem um erro de português à vista de quem a receber.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import extenso as ext  # noqa: E402


@pytest.mark.parametrize("n,esperado", [
    (0, "zero"), (1, "um"), (2, "dois"), (10, "dez"), (15, "quinze"),
    # As quatro que separam o português europeu do brasileiro.
    (14, "catorze"), (16, "dezasseis"), (17, "dezassete"), (19, "dezanove"),
    (20, "vinte"), (21, "vinte e um"), (29, "vinte e nove"), (31, "trinta e um"),
    (50, "cinquenta"), (99, "noventa e nove"),
])
def test_os_numeros_de_uma_data_escrevem_se_em_portugues_europeu(n, esperado):
    """Dias do mês, horas e minutos — o que uma certidão escreve mais vezes."""
    assert ext.numero(n) == esperado


@pytest.mark.parametrize("n,esperado", [
    (100, "cem"),                      # sozinho é «cem»
    (101, "cento e um"),               # acompanhado é «cento»
    (156, "cento e cinquenta e seis"),
    (200, "duzentos"),
    (999, "novecentos e noventa e nove"),
])
def test_a_centena_sozinha_e_cem_e_acompanhada_e_cento(n, esperado):
    """É a distinção que quase toda a gente erra ao escrever isto de cabeça."""
    assert ext.numero(n) == esperado


@pytest.mark.parametrize("n,esperado", [
    (1000, "mil"),                                  # «mil», nunca «um mil»
    (2000, "dois mil"),
    (2026, "dois mil e vinte e seis"),              # resto < 100: leva «e»
    (2100, "dois mil e cem"),                       # centena redonda: leva «e»
    (2156, "dois mil cento e cinquenta e seis"),    # centena + resto: NÃO leva
    (1999, "mil novecentos e noventa e nove"),
])
def test_a_regra_do_e_depois_dos_milhares(n, esperado):
    """Há «e» quando o que sobra é menor que cem ou é uma centena redonda.

    É a regra que faz tropeçar quem escreve números por extenso à mão, e a que
    distingue «dois mil e vinte e seis» de «dois mil cento e cinquenta e seis».
    """
    assert ext.numero(n) == esperado


def test_fora_do_alcance_devolve_algarismos():
    """Um número por extenso ERRADO é pior do que um número em algarismos.

    Acima do alcance coberto, a função não arrisca: devolve o que lá está.
    """
    assert ext.numero(100000) == "100000"
    assert ext.numero(-3) == "-3"


@pytest.mark.parametrize("valor,esperado", [
    ("2026-09-29", "vinte e nove de setembro de 2026"),
    ("2026-03-01", "um de março de 2026"),
    ("2026-12-31", "trinta e um de dezembro de 2026"),
])
def test_a_data_citada_no_meio_de_uma_frase(valor, esperado):
    """A forma de CITAR uma data: «com data de ...», «prevista para ...».

    Os meses vão em minúscula, que é o que a norma em vigor manda. A certidão
    vai buscar o seu ar antigo à estrutura e às fórmulas, não a erros de
    ortografia.
    """
    assert ext.data(valor) == esperado


@pytest.mark.parametrize("valor,esperado", [
    ("2026-09-29", "aos vinte e nove dias do mês de setembro de 2026"),
    # O dia 1 não leva «aos um dia»: leva «AO PRIMEIRO dia», no singular.
    ("2026-03-01", "ao primeiro dia do mês de março de 2026"),
    ("2026-12-31", "aos trinta e um dias do mês de dezembro de 2026"),
])
def test_a_formula_de_datar_um_ato_traz_a_preposicao_de_dentro(valor, esperado):
    """A preposição muda com o dia, e por isso não pode ficar a cargo de quem
    chama.

    A primeira versão deixava o «aos» do lado da certidão e escrevia «aos um dia
    do mês de março» — em todos os dias 1 de todos os meses. Apanhado em revisão.
    """
    assert ext.aos(valor) == esperado


@pytest.mark.parametrize("n,esperado", [
    (2, "duas"), (21, "vinte e uma"), (102, "cento e duas"),
    (200, "duzentas"), (202, "duzentas e duas"), (2000, "duas mil"),
    # Invariáveis: não se tocam.
    (12, "doze"), (20, "vinte"), (100, "cem"), (1000, "mil"),
])
def test_o_numero_concorda_com_um_nome_feminino(n, esperado):
    """«duas folhas», «pelas duas horas», «duzentas folhas».

    A primeira versão deste módulo só tinha a forma masculina, e a certidão
    saía com «dois folhas» e «pelas dois horas» — erros que saltam à cara de
    quem a recebe. Converte os TERMOS completos e não os finais de palavra:
    «doze» acaba em «ze» e não se toca, mas «cento e dois» tem de dar «cento e
    duas» e «dois mil» tem de dar «duas mil».
    """
    assert ext.numero_f(n) == esperado


@pytest.mark.parametrize("valor,esperado", [
    ("2026-09-29T09:14:00", "pelas nove horas e catorze minutos"),
    # A preposição concorda com o número, e é por isso que vem de dentro.
    ("2026-09-29T01:00:00", "pela uma hora"),
    ("2026-09-29T17:01:00", "pelas dezassete horas e um minuto"),
    ("2026-09-29T00:30:00", "pelas zero horas e trinta minutos"),
    ("2026-09-29T15:00:00", "pelas quinze horas"),
    # «hora» é feminino: «pelas DUAS horas», e não «pelas dois horas».
    ("2026-09-29T02:00:00", "pelas duas horas"),
    ("2026-09-29T22:00:00", "pelas vinte e duas horas"),
    # ... e «minuto» é masculino, pelo que fica na forma de numero().
    ("2026-09-29T02:02:00", "pelas duas horas e dois minutos"),
])
def test_a_hora_leva_a_preposicao_que_lhe_pertence(valor, esperado):
    """«pela uma hora» e «pelas nove horas»: deixar a concordância a cargo de
    quem chama era espalhá-la por todo o lado onde a certidão cita uma hora."""
    assert ext.hora(valor) == esperado


@pytest.mark.parametrize("n,esperado", [
    (1, "uma folha"), (5, "cinco folhas"), (0, ""),
    # «folha» é feminino, e o número tem de o acompanhar.
    (2, "duas folhas"), (21, "vinte e uma folhas"), (200, "duzentas folhas"),
])
def test_as_folhas_concordam_em_genero_e_numero(n, esperado):
    """«folha» é feminino: «UMA folha», e não «um folha»."""
    assert ext.folhas(n) == esperado


@pytest.mark.parametrize("n,esperado", [
    (0, "menos de um dia"), (1, "um dia"), (2, "dois dias"), (30, "trinta dias"),
])
def test_zero_dias_nao_e_uma_duracao(n, esperado):
    """Um edital afixado de manhã e retirado à tarde não esteve afixado zero
    dias — esteve afixado nesse dia."""
    assert ext.dias(n) == esperado


def test_um_valor_que_nao_e_data_devolve_se_tal_como_veio():
    """Rebentar a emissão de uma certidão por causa de um campo mal gravado era
    trocar um documento imperfeito por documento nenhum."""
    assert ext.data("isto não é uma data") == "isto não é uma data"
    assert ext.hora("") == ""
