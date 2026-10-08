"""test_regras_da_casa.py — As regras do AGENTS.md que uma máquina pode conferir.

Nasceu de uma contagem. O número de testes que o README cita arrastou-se
desatualizado três vezes numa só onda de trabalho, e as três foram apanhadas por
revisores — uma delas depois de a correção anterior ter arranjado um dos dois
sítios onde o número aparece e deixado o outro, pondo o ficheiro a dizer duas
coisas diferentes sobre a mesma coisa.

Alugar um revisor para reparar que um número está desatualizado é pagar a alguém
para fazer o trabalho de um `assert`. As regras que são mecânicas passam a ser
verificadas por máquina, de graça, sem rede e sempre; o que sobra para quem revê
é o que precisa de juízo.

O que NÃO está aqui, e de propósito: as regras que pedem leitura. «O teste tem
de falhar contra o código anterior», «os comentários explicam o porquê», «medir
com a mesma régua» — nenhuma delas se reduz a uma expressão regular, e fingir
que sim daria a tranquilidade falsa de uma verificação que não verifica.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# Ficheiros que não se leem como texto.
BINARIOS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".ttf", ".otf", ".woff",
            ".woff2", ".zip", ".docx", ".odt"}


def _versionados():
    """Os ficheiros de texto que o git segue, lidos uma vez só."""
    saida = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True,
                           text=True, check=True).stdout.split("\n")
    for nome in filter(None, saida):
        caminho = RAIZ / nome
        if caminho.suffix.lower() in BINARIOS or not caminho.is_file():
            continue
        try:
            yield nome, caminho.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def _versao_do_agente():
    """O VERSAO que o agente.py declara."""
    texto = (RAIZ / "agente.py").read_text(encoding="utf-8")
    return re.search(r'^VERSAO\s*=\s*"([^"]+)"', texto, re.M).group(1)


def _versao_do_pyproject():
    """O `version` que o pyproject.toml declara.

    Por expressão regular e não pelo `tomllib`, que só existe a partir do
    Python 3.11 e a matriz desta casa começa no 3.10. A primeira versão deste
    ficheiro importava-o e deixou a perna do 3.10 vermelha — num ficheiro
    escrito, entre outras coisas, para impor «verde nas DUAS versões da
    matriz». Trazer o `tomli` só para ler um campo não se justificava.
    """
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    achado = re.search(r'^version\s*=\s*"([^"]+)"', texto, re.M)
    assert achado, "o pyproject.toml deixou de declarar um `version` na raiz"
    return achado.group(1)


def _seccoes_do_changelog():
    """As versões que o CHANGELOG.md tem, pela ordem em que lá estão."""
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    return [tuple(int(n) for n in m)
            for m in re.findall(r"^## (\d+)\.(\d+)\.(\d+)", texto, re.M)]


def _quantos_testes(marcador=None):
    """Quantos testes a suite colhe mesmo, perguntando ao pytest.

    Com `--collect-only` nada corre, por isso não há recursão: este processo
    filho colhe os mesmos ficheiros e sai. É mais lento do que contar à mão,
    e é a única maneira de o número ser medido em vez de declarado.
    """
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q",
           "-p", "no:cacheprovider"]
    if marcador:
        cmd += ["-m", marcador]
    saida = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True).stdout
    achado = re.search(r"^(\d+)(?:/\d+)? tests? collected", saida, re.M)
    assert achado, f"o pytest não disse quantos colheu:\n{saida[-500:]}"
    return int(achado.group(1))


# --------------------------------------------------------------------------
# A versão, que sobe em dois ficheiros ao mesmo tempo
# --------------------------------------------------------------------------

def test_a_versao_e_a_mesma_no_agente_e_no_pyproject():
    """«`VERSAO` e `version` sobem juntos e nunca se separam» (AGENTS.md)."""
    assert _versao_do_agente() == _versao_do_pyproject(), (
        f"agente.py diz {_versao_do_agente()} e o pyproject.toml diz "
        f"{_versao_do_pyproject()}")


# --------------------------------------------------------------------------
# O CHANGELOG, que cresce para baixo
# --------------------------------------------------------------------------

def test_o_changelog_cresce_para_baixo():
    """A mais antiga em cima, a mais recente no fim.

    «Já se inseriu uma no sítio errado por se assumir a ordem contrária»
    (AGENTS.md). Uma secção posta a meio passa despercebida a quem lê o diff,
    porque o diff mostra-a certa — é o ficheiro inteiro que fica errado.
    """
    seccoes = _seccoes_do_changelog()
    assert seccoes, "o CHANGELOG.md não tem secções de versão"
    for anterior, seguinte in zip(seccoes, seccoes[1:], strict=False):
        assert anterior < seguinte, (
            f"a {'.'.join(map(str, seguinte))} vem depois da "
            f"{'.'.join(map(str, anterior))} e devia vir antes")


def test_a_ultima_seccao_do_changelog_e_a_versao_que_o_agente_declara():
    """Subir a versão sem a registar deixa uma entrega sem rasto no histórico."""
    ultima = ".".join(map(str, _seccoes_do_changelog()[-1]))
    assert ultima == _versao_do_agente(), (
        f"o agente está na {_versao_do_agente()} e a última secção do "
        f"CHANGELOG é a {ultima}")


# --------------------------------------------------------------------------
# Os números que o README cita
# --------------------------------------------------------------------------

# Onde é que o README afirma uma contagem de testes, e o que é que ela conta.
# São duas e não uma, que foi precisamente a armadilha: a correção anterior
# arranjou a do arranque rápido e deixou a da secção dos testes de browser.
CONTAGENS_DO_README = [
    (re.compile(r"# (\d+) testes"), None),
    (re.compile(r"mais (\d+) de browser"), "navegador"),
    (re.compile(r"Há agora (\d+) testes"), "navegador"),
]


def test_o_readme_cita_a_contagem_certa_da_suite_normal():
    """«Os números que o README cita conferem-se contra a realidade» (AGENTS.md).

    Arrastou-se desatualizado três vezes numa só onda. É mecânico: pergunta-se
    ao pytest em vez de se escrever de cabeça.
    """
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    real = _quantos_testes()
    rx = CONTAGENS_DO_README[0][0]
    citadas = [int(m) for m in rx.findall(readme)]
    assert citadas, f"o README deixou de citar a contagem ({rx.pattern})"
    for citada in citadas:
        assert citada == real, (
            f"o README diz {citada} testes e a suite colhe {real}")


@pytest.mark.navegador
def test_o_readme_cita_a_contagem_certa_dos_testes_de_browser():
    """O mesmo para os de Chromium, e marcado para correr onde há playwright.

    Sem o playwright instalado, `-m navegador` não colhe nada e este teste
    daria um número errado em vez de falhar — por isso vive no trabalho da
    integração contínua que tem Chromium, e não no pytest de todos os dias.
    """
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    real = _quantos_testes("navegador")
    assert real, "o -m navegador não colheu nada: falta o playwright?"
    for rx, _ in CONTAGENS_DO_README[1:]:
        citadas = [int(m) for m in rx.findall(readme)]
        assert citadas, f"o README deixou de citar a contagem ({rx.pattern})"
        for citada in citadas:
            assert citada == real, (
                f"o README diz {citada} testes de browser e colhem-se {real}")


# --------------------------------------------------------------------------
# Sem emojis
# --------------------------------------------------------------------------

# Emoji a sério, e não tipografia. As setas («→», «↑»), as aspas angulares e os
# travessões ficam de fora de propósito: o README desenha com eles o percurso de
# um edital, e proibi-los seria empobrecer o texto em nome de uma regra que
# nunca foi sobre isso. Entram os blocos pictográficos, as bandeiras, e
# qualquer símbolo que peça apresentação de emoji com o U+FE0F.
# Construída a partir de PONTOS DE CÓDIGO e não de caracteres, para este
# ficheiro — que proíbe emojis — não ter de conter um único.
#
# A primeira versão escrevia-os como «\u2705» e alguma coisa pelo caminho
# converteu os escapes em caracteres: o ficheiro foi para o repositório com
# sete emojis dentro da própria regra que os proíbe. Quem o apanhou foi a
# regra, ao correr contra si mesma.
_BLOCOS = [(0x1F000, 0x1FAFF),   # pictogramas, emoticons, símbolos, transportes
           (0x1F1E6, 0x1F1FF)]   # indicadores regionais (bandeiras)
_SOLTOS = [0x2705, 0x274C, 0x2728, 0x2B50, 0x2B55, 0x2757, 0x2753]
_SIMBOLOS = (0x2600, 0x27BF)     # mistos: só contam com o seletor a seguir
_SELETOR_DE_EMOJI = 0xFE0F

EMOJI = re.compile("|".join(
    [f"[{chr(a)}-{chr(b)}]" for a, b in _BLOCOS]
    + [f"[{chr(_SIMBOLOS[0])}-{chr(_SIMBOLOS[1])}]{chr(_SELETOR_DE_EMOJI)}"]
    + [chr(c) for c in _SOLTOS]
))


def test_nao_ha_emojis_no_que_esta_versionado():
    """«Não há um único emoji (…) e não vai haver» (AGENTS.md).

    A assinatura que as ferramentas põem no fim de uma PR não conta — não é
    escolha de quem escreve, e não está em ficheiro nenhum do repositório.
    """
    achados = [f"{nome}:{n}: {m.group()}"
               for nome, texto in _versionados()
               for n, linha in enumerate(texto.splitlines(), 1)
               for m in EMOJI.finditer(linha)]
    assert not achados, "emojis encontrados:\n  " + "\n  ".join(achados[:20])


# --------------------------------------------------------------------------
# Português europeu
# --------------------------------------------------------------------------

# Palavras que em português europeu se dizem de outra maneira. A lista é curta
# de propósito: um falso positivo numa verificação destas é pior do que a
# verificação não existir, porque ensina a ignorá-la.
#
# Ficaram de fora, depois de medidas contra o repositório:
#   «tela»    — em «tela branca do tamanho exato» (lib/tratamento.py) está no
#               sentido de tela de pintura, que é português europeu correto;
#   «arquivo» — é o nome de uma peça deste sistema, e aqui quer dizer arquivo
#               e não ficheiro;
#   «time»    — é o módulo do Python, e aparece em dezenas de ficheiros. Esteve
#               nesta lista durante exatamente uma corrida, e a verificação
#               rebentou com 40 falsos positivos. Fica escrito porque é a prova
#               de que a lista curta não é timidez: é o que a torna utilizável.
BRASILEIRISMOS = {
    "usuário": "utilizador",
    "usuários": "utilizadores",
    "você": "tu",
    "vocês": "vocês (não se trata ninguém por «você» aqui)",
    "deletar": "apagar",
    "gerenciar": "gerir",
    "registrar": "registar",
    "planejar": "planear",
    "acessar": "aceder",
    "aplicativo": "aplicação",
}

# As excepções, com a razão ao lado em vez de a palavra sair da lista acima.
SABIDOS = {
    ("AGENTS.md", "você"): "a própria regra que o proíbe, a citar a palavra",
    ("tests/test_regras_da_casa.py", "você"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "usuário"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "usuários"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "vocês"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "deletar"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "gerenciar"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "registrar"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "planejar"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "acessar"): "a lista desta verificação",
    ("tests/test_regras_da_casa.py", "aplicativo"): "a lista desta verificação",
}


def test_nao_ha_portugues_do_brasil():
    """«Registo técnico-operacional, nunca português do Brasil» (AGENTS.md)."""
    achados = []
    for nome, texto in _versionados():
        for palavra, europeu in BRASILEIRISMOS.items():
            if (nome, palavra) in SABIDOS:
                continue
            rx = re.compile(r"\b" + palavra + r"\b", re.I)
            for n, linha in enumerate(texto.splitlines(), 1):
                if rx.search(linha):
                    achados.append(f"{nome}:{n}: «{palavra}» — em português "
                                   f"europeu, «{europeu}»")
    assert not achados, "\n  ".join([""] + achados[:20])


def test_os_sabidos_nao_se_acumulam_sem_razao():
    """Cada excepção tem de nomear uma palavra que a lista conhece.

    Sem isto, a maneira mais fácil de calar a verificação acima era despejar
    nomes no SABIDOS até ela se calar — que é o contrário do que ela existe
    para fazer.
    """
    for (ficheiro, palavra), razao in SABIDOS.items():
        assert palavra in BRASILEIRISMOS, (
            f"o SABIDOS perdoa «{palavra}» em {ficheiro}, e essa palavra já não "
            f"está na lista: a excepção deixou de ter sentido")
        assert razao.strip(), f"a excepção de {ficheiro} não diz porquê"
        assert (RAIZ / ficheiro).exists(), (
            f"o SABIDOS perdoa {ficheiro}, que já não existe")
