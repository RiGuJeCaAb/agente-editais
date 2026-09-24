# Regras da casa

Instruções para quem revê ou escreve código neste repositório — pessoa ou máquina.
O `README.md` explica o que a aplicação faz; este ficheiro explica como se trabalha
nela e contra o que se revê.

## O contexto, que muda o que é grave

Este agente publica editais da Câmara Municipal de Moimenta da Beira numa televisão
do átrio. Corre num posto municipal, sem ninguém a olhar, e o que mostra tem valor
legal: um edital que não aparece, ou que aparece com o assunto trocado, é uma falha
de afixação — não é um defeito de estilo. Convém ter isto presente ao decidir o que
merece um comentário.

## Língua

Português europeu em tudo: código, comentários, mensagens de erro, documentação e
revisões. Registo técnico-operacional, nunca publicitário, nunca português do
Brasil.

Os assuntos dos commits escrevem-se sem acentos, por hábito de consola
(«Revisao a mao: ...»). O corpo do commit e todo o resto leva acentuação normal.

## Sem emojis

Não há um único emoji no código, na documentação ou nas mensagens de commit, e
não vai haver. A hierarquia faz-se com títulos, tipografia e texto que diz o que
quer dizer. Quem revê também não os usa nos comentários.

A única exceção é a assinatura que as ferramentas acrescentam sozinhas ao fim de
uma PR — não é escolha de quem escreve, e por isso não conta.

## Antes de entregar

```bash
ruff check .
mypy lib/ agente.py
pytest
```

Verde nas **duas** versões da matriz, 3.10 e 3.12, e não só numa. A 3.10 é o mínimo
declarado; a 3.12 apanha o que for depreciado.

Os testes correm de propósito **sem** LibreOffice e **sem** Tesseract: os dois são
opcionais em execução, e a suite tem de provar que o agente funciona sem eles. Um
teste que precise de qualquer um deles está errado.

## O teste tem de provar alguma coisa

**Um teste novo tem de falhar contra o código anterior.** Se passa dos dois lados,
não prova nada — salvo se existir de propósito para fixar o que não pode mudar, e
nesse caso diz-se isso no nome ou num comentário ao lado.

A regra nasceu de uma reincidência: três vezes se escreveu um teste cuja descrição
anunciava o caso difícil e cujo corpo exercitava o fácil. Uma dessas vezes deixou
passar uma correção que engolia sete em sete títulos de edital legítimos.

## Medir com a mesma régua

Uma tabela que compara números mede os dois lados da mesma maneira. Já se publicou
uma comparação de memória em que uma coluna era um acréscimo sobre a linha de base
e a outra eram valores absolutos — não estava errada por pouco, estava a dizer o
contrário do que acontecia.

Número em documento ou em comentário é medido. Se foi estimado, diz-se que foi.

## Os comentários explicam o porquê

Um comentário que repete o nome da função ocupa o lugar do que faria falta.
Comenta-se a razão da escolha, o defeito que a motivou, o que se recusou fazer, e a
medição quando existe. O comentário no topo de `lib/tratamento.py`, sobre o
`float32` e os 1325 MB de pico, é o padrão da casa.

## Heurísticas mexem-se contra exemplos reais

A extração do assunto, do número e da data é heurística calibrada para os editais
da CMMB. Alterar uma dessas regras sem a correr contra documentos verdadeiros já
produziu uma regressão que só apareceu por acaso.

Alargar uma lista de exclusão é o caso mais perigoso de todos: aquilo que ela passa
a excluir a mais nunca dá erro — desaparece em silêncio.

## O CHANGELOG cresce para baixo

`CHANGELOG.md` está por ordem ascendente: a versão mais antiga em cima, a mais
recente no fim. Secção nova vai para o **fim** do ficheiro. Já se inseriu uma no
sítio errado por se assumir a ordem contrária.

Cada peça leva uma versão. `VERSAO` em `agente.py` e `version` em `pyproject.toml`
sobem juntos e nunca se separam. Alteração que não muda o que a aplicação faz leva
o terceiro número; tudo o resto leva o segundo.

## Funcionalidade nova entra no README

E os números que o README cita — o total de testes, sobretudo — conferem-se contra
a realidade antes de entregar, em vez de se arrastarem desatualizados.

## O que interessa numa revisão

Por ordem de gravidade, neste projeto:

1. **Um edital que não aparece na televisão, ou aparece errado.** É o único defeito
   com consequência legal. O resto é incómodo.
2. **Estado em disco que fica a meio.** O registo é a verdade e o disco acompanha.
   Uma operação que escreve metade e falha deixa o posto sem saber o que está
   afixado. Conferir tudo antes de tocar em alguma coisa, nunca à medida.
3. **Janelas entre a validação e a ação.** Uma pasta conferida e só depois limpa
   deixa espaço para outro processo. Já houve uma assim, e foi um revisor
   automático que a apanhou.
4. **Pressupostos sobre o ambiente.** Isto corre num posto com Windows, muitas
   vezes por duplo clique. O `sys.stdin` pode ser `None`. Não há terminal
   garantido, não há rede garantida, não há LibreOffice garantido.
5. **Memória.** Trabalha-se com imagens de 3840×2160. Um `float64` a contaminar um
   intermédio duplica 100 MB de uma vez, e há vários vivos ao mesmo tempo.

O que **não** interessa, e não vale um comentário: preferências de estilo que o
`ruff` não impõe, renomeações sem razão dada, e pedidos para acrescentar anotações
de tipo onde o `mypy` já está satisfeito.

## Como se fala aqui

De igual para igual. Quem escreve trata quem lê por tu, e não há «dono» nem
tratamento por «você». Não se embeleza: o que está por confirmar diz-se por
confirmar, e o que falhou diz-se que falhou, com a saída à vista.
