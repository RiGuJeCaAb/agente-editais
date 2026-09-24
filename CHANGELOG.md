# Registo de alterações

Formato: uma entrada por onda de trabalho, com o porquê e não só o quê.

## 0.11.0 — Onda 1: travar a hemorragia

Cinco frentes, todas verificadas com medição ou teste, nenhuma delas visível
para quem usa o painel — o objetivo desta onda era tornar o sistema seguro de
mudar, não mudá-lo.

### Corrigido
- **Registo destruído por escrita interrompida.** `registo_entrada.json` era
  escrito com `open(path, "w")`; uma interrupção entre o truncar e o escrever
  deixava-o ilegível e o agente deixava de arrancar. Passa por escrita atómica
  (temporário, `fsync`, `os.replace`) com três gerações de recurso.
- **CSRF no painel.** Com as credenciais Basic em cache no browser, um POST
  nascido noutro sítio retirava editais do ecrã. Exige-se agora
  `application/json`, o cabeçalho próprio `X-Painel-Pedido` e concordância entre
  `Origin` e `Host`.
- **Senha comparada em tempo variável**, e que rebentaria com `TypeError` se
  tivesse cedilha ou acento. Passa por `hmac.compare_digest` sobre bytes.
- **Travessia de caminho** verificada por comparação de prefixo de texto, onde
  `/dados/saida_antiga` passava a barreira de `/dados/saida`.
- **Onze pares de cor** abaixo do mínimo das WCAG 2.1 AA, entre eles os carimbos
  de estado e o aviso "campo a confirmar".
- **Dupla sondagem na TV**: dois `setInterval` faziam a página buscar o
  `slides.json` a dobrar depois de um toque no ecrã de arranque.
- **`slides.json` e `index.html`** escritos de forma destrutiva enquanto a TV os
  lia, o que mostrava "sem ligação" sem haver falha nenhuma.
- **`return` em falta** em `_servir_previa`.

### Acrescentado
- `lib/armazenamento.py`: escrita atómica com gerações, leitura que recua para
  as cópias, e jornal de auditoria apenas-acrescento (`registo_auditoria.jsonl`).
- Limitador de tentativas de senha por endereço (8 falhas, 5 minutos).
- Cabeçalhos de segurança em todas as respostas do painel.
- Cache de fundos em disco, com aquecimento em segundo plano ao arrancar.
- Indicador de frescura na TV: conteúdo com mais de 30 minutos é assinalado.
- `pyproject.toml`, `ruff`, `pytest` e integração contínua.

### Desempenho
Medido em processo novo, na mesma máquina, com a cache em disco:

| | antes | agora |
|---|---|---|
| tempo por ecrã | 8,90 s | 1,08 s |
| pico de memória | 1380 MB | 601 MB |
| publicar 10 editais | ~89 s | ~11 s |

O estrangulamento não era o que se supunha. O perfil mostrou que 3,1 s dos 5,2 s
eram os dois desfoques gaussianos da *sombra*, não a geração do fundo.

## 0.12.0 — Onda 2: tornar defensável

A Onda 1 tornou o sistema seguro de mudar. Esta torna-o defensável perante quem
pergunte «e provam isso?».

### Acrescentado
- **Certidão de afixação e desafixação em PDF** (`lib/certidao.py`). É o
  documento que faltava: identifica o edital, o instante de afixação e quem a
  ordenou, o de desafixação, a duração e a base legal. Decidido a 18/09/2026 que
  o instante OFICIAL é o da publicação no painel — a afixação é um ato
  administrativo, não um evento de infraestrutura, e confundi-los poria a
  validade de um ato a depender do uptime de uma televisão. O registo de
  disponibilidade no expositor vai em anexo, claramente distinto. Leva um selo
  de conferência (SHA-256 dos factos) e diz no corpo que não é assinatura
  eletrónica.
- **Contas individuais** (`lib/utilizadores.py`), com senha derivada por scrypt,
  sessão por cookie `HttpOnly` + `SameSite=Strict`, dois papéis e limite de
  tentativas por endereço e por conta. A senha partilhada foi retirada: com ela,
  o nome no trilho de auditoria era o que quem entrasse escrevesse, e uma
  certidão que nomeia quem afixou não pode assentar nisso.
- **Tipos de documento com prazo legal** (`lib/prazos.py`), ampliáveis em
  `config.json`. O tipo principal cita o artigo 56.º do Anexo I da Lei
  n.º 75/2013 e trata as duas partes da regra em separado: o mínimo são cinco
  dias, e os 10 são a janela onde esses cinco têm de caber. O sistema propõe e
  avisa; a decisão continua do posto.
- **Arquivo imutável dos originais** (`lib/originais.py`), endereçado por
  SHA-256. Limpar a pasta de entrada deixa de tornar impossível recompor um
  edital publicado — e deixa de apagar o documento que a certidão afirma ter
  sido afixado. Deteta adulteração de graça.
- **Registo técnico** (`lib/diario.py`) com níveis, rotação e saída simultânea
  para consola e ficheiro, em vez de 71 `print()`.
- **Rota `/saude`** e **unidade systemd** (`servico/`), com restrições de
  superfície. A única rota sem sessão, e por isso devolve números e instantes,
  nunca conteúdo de editais por validar.
- `mypy` na integração contínua, rigoroso nos módulos novos e tolerante nos
  antigos.

### Corrigido
- **O PyMuPDF mede mal os acentos.** `get_text_length` trata os caracteres
  acentuados dos tipos base do PDF como se não ocupassem largura: «AÇÃO» devolve
  23,3 pt e desenha 30,9 pt. Numa certidão em português o erro é sistemático, e
  a primeira versão transbordava a margem direita em 19,8 pt. Mede-se agora uma
  cópia sem acentos — o glifo acentuado tem o mesmo avanço da letra de base.
- Datas de retirada anteriores à afixação davam avisos com contagens negativas
  («a afixação dura -79 dia(s)»).
- `por_estado()` devolve cópias desde a Onda 1, e o agente continuava a gravar
  o `sha256` por mutação do resultado. Os três métodos quase iguais que isso
  gerou (`definir_previas`, `definir_pngs`, e o novo) deram lugar a um só,
  `definir()`, com lista branca de campos de sistema.

### Números
| | Onda 1 | Onda 2 |
|---|---|---|
| testes | 109 | 207 |
| módulos em `lib/` | 5 | 10 |
| verificação de tipos | — | `mypy` limpo |

## 0.13.0 — Onda 3 (1/4): ecrãs conforme a orientação

### Corrigido
- **Documentos horizontais ocupavam 10 % do ecrã.** Havia uma caixa-folha só,
  vertical, e tudo era encaixado nela. Um printscreen ou um A4 deitado ficava
  numa faixa fina no meio de muito branco — numa televisão vista a seis ou dez
  metros, texto que não existe. Passam a ter ecrã próprio, com ~60 % da área.

  | documento | antes | agora |
  |---|---|---|
  | A4 vertical | 24 % | 24 % (igual) |
  | A4 deitado | 12 % | 48 % |
  | printscreen 16:9 | 10 % | 60 % |
  | panorama 21:9 | 7 % | 69 % |

### Acrescentado
- `tratamento.agrupar_ecras()`: distribui as páginas por ecrãs respeitando a
  orientação, em vez da divisão cega em blocos de três. Substitui `_chunk()`,
  que foi removido.
- A caixa larga herda as margens do trio de folhas verticais, e a folha é do
  tamanho exato do que leva dentro — preenchê-la a branco até à caixa toda
  deixava quase 700 píxeis que se liam como defeito.
- 27 testes de orientação.

### Garantido
A composição dos documentos verticais é **idêntica ao píxel** à da versão
anterior: 100 % dos píxeis iguais em 1, 2 e 3 folhas. A esmagadora maioria dos
editais é vertical, e uma melhoria que estragasse esses seria mau negócio.

## 0.14.0 — Onda 3 (2/4): um só modelo de dados

### Removido
- **O caminho de publicação automática.** Os modos `--once`, `--watch` e
  `--rebuild-web` saem, e com eles 370 linhas do `agente.py` (1595 → 1198).
  Liam a pasta, compunham as imagens e punham-nas no ecrã sem ninguém ver.

  A razão não é arrumação. Desde a 0.12 a aplicação emite uma certidão que diz
  **quem** afixou cada edital. Um caminho que publica sozinho não tem essa
  resposta, e mantê-lo era garantir que mais cedo ou mais tarde alguém pediria
  a certidão de um edital afixado por ninguém. Dois modelos de dados a viver
  lado a lado é uma dívida que só cresce: `editais.json` com um registo por
  **ecrã**, mais um `retiradas.txt` editado à mão, contra o
  `registo_entrada.json` com um registo por **edital**, estados e auditoria.
- Com eles saem `varrer`, `reconstruir_saidas`, `gerar_pagina_web`, `gerar_zip`,
  `garantir_retiradas`, `retirada_de`, `proximo_indice`, `ativos_hoje` e o par
  `_load_json`/`_save_json`, que escrevia sem ser atomicamente.

### Acrescentado
- **`lib/migracao.py`** — ninguém perde editais na mudança. Ao arrancar o
  painel, se encontrar `editais.json`, o agente reagrupa os registos por ecrã
  no edital a que pertencem (o modelo antigo repetia um edital de cinco folhas
  três vezes, com `parte` e `total_partes`), lê as datas do `retiradas.txt`,
  recupera o resumo SHA-256 do original quando o ficheiro ainda existe, e cria
  cada edital no registo novo passando pelos estados legítimos
  (rascunho → validado → publicado → retirado, quando for o caso).

  O que o modelo antigo não tinha, assume-se em vez de se inventar: **quem**
  afixou fica `migracao` — não havia contas, e a certidão de um edital migrado
  di-lo em letra gorda; a **hora** da afixação é o `processado_em` do primeiro
  ecrã, o mais próximo que os dados permitem; o **tipo de documento** fica o
  de omissão, e o prazo não é verificado até alguém o escolher no painel.

  Os ficheiros de origem são **renomeados** para `.migrado`, não apagados: se a
  migração tiver interpretado alguma coisa mal, os dados continuam lá.
- `registo.definir_instante_de_afixacao()`, único caminho que corrige um
  instante de afixação para o passado. Não está na lista branca do `editar()`
  nem nos campos de sistema, e regista a correção com o valor anterior — a
  própria correção fica auditável.
- 38 testes novos. De migração: reagrupamento, sobrevivência dos metadados,
  recuperação do resumo, reconstrução dos estados, afixação datada no passado,
  rasto de auditoria, idempotência, um `retiradas.txt` maltratado de cinco
  maneiras, e o edital sem data de publicação que tem de ficar em rascunho e
  dizê-lo. De certidão: cinco valores que não são resumos e não podem aparecer
  debaixo de «Resumo do original».

### Corrigido
- **A certidão citava como «Resumo do original» coisas que não eram resumos.**
  O campo `hash` de um registo nem sempre traz um resumo de ficheiro: um edital
  migrado cujo original já não estava na pasta leva lá uma chave sintética
  (`migrado:numero+assunto`), que serve para o registo não colidir consigo
  próprio e não serve para mais nada. A certidão imprimia-a como se fosse a
  impressão digital do documento — ou seja, afirmava ter conferido um ficheiro
  que nunca viu. Passa a aceitar só o que tem forma de resumo (SHA-256 ou o
  SHA-1 antigo) e a calar-se no resto: um documento que se cala vale mais do
  que um que afirma o que não sabe.
- **A migração perdia o SHA-256 quando ainda era calculável.** O modelo antigo
  só guardava o SHA-1, e o arquivo imutável endereça por SHA-256. Enquanto o
  original estiver na pasta de entrada há por onde o calcular — e se não for
  ali, nunca mais é: o edital fica para sempre sem forma de recuperar o
  documento que afixou. Passa a calcular-se e a arquivar-se o original.
- **`mover_estado` falhava em silêncio na migração.** Recusa devolvendo
  `{"ok": False}`, não levantando exceção, e a migração ignorava a resposta. Um
  edital antigo sem data de publicação falhava a validação, falhava a seguir a
  publicação, ficava contado como migrado — e o posto era informado de que um
  edital desaparecido do expositor tinha sido migrado com êxito. Ficar em
  rascunho é a resposta certa (a data é obrigatória, e quem a sabe é uma
  pessoa); o que não podia era acontecer calado.
- **A ordem dos imports dependia de ter corrido o programa.** O `ruff` não sabia
  que os módulos do projeto vivem em `lib/`, e classificava-os pela heurística —
  que olha para as pastas da raiz. Como `diario/` e `originais/` são pastas de
  dados criadas em execução e ignoradas pelo git, `import diario` era
  primeira-parte na máquina de quem já tinha corrido a aplicação e
  terceira-parte numa clonagem limpa. A CI dizia verde e o computador de quem
  escrevia dizia vermelho, pelo mesmo código. Declarado em `pyproject.toml`
  (`src` e `known-first-party`), é igual em todo o lado.

## 0.15.0 — O que a pessoa vê, e o que pode desfazer

Dois defeitos apanhados no primeiro uso a sério, ambos do mesmo tipo: buracos
entre o que o sistema faz e o que quem está ao teclado consegue ver ou desmanchar.

### Corrigido
- **O painel mostrava apenas a primeira página de cada documento.** A função que
  escolhia a imagem devolvia `ficheiros_previa[0]` e mais nada. As
  pré-visualizações das outras páginas eram geradas, guardadas e servidas — e
  ignoradas. Não havia setas, nem contador, nem forma de lá chegar.

  Não é cosmética. A vista de validação é o **único** ecrã onde uma pessoa
  confere o que vai afixar, e mostrava-lhe uma folha de um documento com cinco.
  Ao publicar, a aplicação emite uma certidão com o nome dessa pessoa a dizer que
  foi ela que afixou aquele edital. Certificava-se o que não se tinha visto.

  Passa a haver um visor com todas as páginas: miniaturas, contador, setas e
  teclado (`↑ ↓` dentro do documento, `← →` entre documentos). As miniaturas são
  deliberadamente visíveis em vez de um contador discreto — o problema não era
  chegar às outras páginas, era não se saber que existiam. Pela mesma razão, o
  número de páginas aparece agora em cada ficha da lista.

  A barra ficou **acima** da imagem depois de uma primeira tentativa a ter posto
  por baixo: num ecrã de 1080 caía abaixo da dobra, e uma pista que só se vê
  depois de rolar não é uma pista.

- **A máquina de estados não tinha saída.** O mapa de transições ia de rascunho
  a retirado e nunca para fora; o que entrava no registo ficava lá para sempre.
  Descobriu-se pela pior via: a migração do modelo antigo criou rascunhos de
  editais sem data de publicação e sem ficheiro de origem, que não se conseguem
  validar nem publicar, e que ficavam eternamente na fila «Por validar» a tapar
  o trabalho a sério.

### Acrescentado
- **Estado `descartado`**, com secção própria no painel. Descartar **não é
  apagar**, de propósito: a linha fica no registo, o motivo é obrigatório e vai
  ao jornal de auditoria, e um clique repõe o documento na fila. Um registo de
  editais municipais não deve perder linhas — deve marcá-las.
- Um edital **publicado não se descarta**, e é a regra que interessa: sai do
  ecrã por «Retirar», que é o que carimba a desafixação e o que a certidão cita.
  Descartá-lo fá-lo-ia desaparecer do expositor sem ficar registado quem o
  desafixou nem quando — o buraco que a Onda 2 existiu para tapar. O botão nem
  aparece, em vez de aparecer e dar erro.
- 27 testes novos: 15 do descarte (reversibilidade, motivo obrigatório, rasto de
  auditoria, e a recusa de descartar um publicado), 10 do visor e 2 pares de
  contraste. 299 no total.

### Nota sobre a cobertura dos testes do visor
Os testes do visor são análise estática do `painel.html`: garantem que a forma
exata do defeito não volta — indexar a primeira página, ou um dos dois sítios de
desenho ficar para trás numa alteração futura. **Não provam que funciona no
browser**; isso foi verificado a olho, com um documento de três páginas, num
ecrã de 1366×768. Vale na mesma: o defeito nasceu de uma linha com `[0]`.

## 0.16.0 — O registo manda, o disco acompanha

O registo de entrada é a verdade sobre cada edital: tem os estados, as datas,
quem afixou e o rasto de auditoria. O disco tem os ficheiros. Esta onda trata do
espaço entre os dois.

### A decisão que ficou tomada

O posto pediu que um edital mudasse de pasta conforme o estado — de `entrada/`
para `publicados/`, e daí para `retirados/`. A razão é boa e é operacional: quem
lá trabalha quer abrir o Explorador e ver o que está afixado, sem depender de
uma aplicação.

Não foi feito assim, e vale a pena registar porquê. Nesse desenho, **a pasta
onde um ficheiro está passa a ser uma segunda afirmação sobre o estado do
edital**, ao lado da que está no registo. E duas afirmações sobre a mesma coisa
divergem — não é «se», é «quando»: alguém arrasta um ficheiro, o antivírus põe
outro em quarentena, uma mudança falha a meio. A partir daí, qual manda? O
registo grava de forma atómica e diz quem fez o quê; uma mudança de pasta não
faz nem uma coisa nem outra, e não sabe dizer **quem** publicou — que é a
pergunta a que esta aplicação existe para responder.

A saída: **o registo manda, e as pastas são uma exportação.** O posto tem a
vista que queria, reconstrutível a pedido, e o sistema continua a ter uma só
verdade. Se divergirem, volta-se a gerar e fica resolvido.

### Acrescentado
- **`--exportar-pastas`** (`lib/exportacao.py`) constrói `exportacao/publicados/`
  e `exportacao/retirados/` a partir do registo, com o documento original
  nomeado `AAAA-MM-DD_numero_assunto.pdf` — a data à cabeça porque é assim que
  alguém procura um edital: «foi aí por junho». Junta um `INDICE.csv` com tudo
  o que a pasta não sabe dizer, incluindo **quem afixou e quando**.

  Cada subpasta leva um `_GERADO_PELO_AGENTE.txt` que explica que é uma vista e
  que mover ficheiros de lá não muda o estado de nada. É também a marca de
  segurança: **a exportação recusa-se a limpar uma pasta que não tenha a
  marca**, porque apaga ficheiros e o caminho vem do config, que alguém pode ter
  apontado para o sítio errado.

  Os PNG compostos ficam em `saida/`, onde a televisão os lê: duplicá-los
  gastaria o dobro do disco para mostrar a mesma coisa. Vão nomeados no índice.

- **`--conferir`** (`lib/conferencia.py`) compara o registo com o disco e
  relata: registos cujo original não está em lado nenhum, os rascunhos que por
  isso **não têm saída** (sem data não se validam, sem documento não se
  publicam — a forma exata dos zombies que a migração deixou), e os ficheiros
  que nenhum registo reclama em `saida/`, `previas/` e `originais/`.

  **Não apaga, não move, não corrige.** É deliberado: as decisões sobre um
  edital municipal são de quem responde por ele, e uma ferramenta que arruma
  sozinha é uma ferramenta em que é preciso confiar cegamente. Esta só tem de
  ser lida. Devolve 1 quando encontra alguma coisa, para dar para agendar.

### Corrigido
- **A pasta `entrada/` nunca se esvaziava.** Os ficheiros ficavam lá para sempre
  depois de recebidos, e ao fim de umas semanas ninguém conseguia responder a
  olho a «o que é que chegou de novo?» — que é metade do trabalho do posto.

  Passam para `entrada/tratados/` assim que o rascunho existe. O que torna isto
  seguro é a **ordem**: quando o ficheiro sai, já há uma cópia idêntica ao byte
  em `originais/`, endereçada pelo SHA-256, e é dela que a composição lê. Mover
  e não apagar, como em todo o resto. Falhar a mudança é inofensivo — o registo
  já existe e o hash impede a reingestão — por isso avisa e não interrompe nada.

### Corrigido na própria onda, antes de entrar
O revisor automático esgotou o orçamento e não reviu este trabalho. A revisão
foi feita à mão sobre o diff, e encontrou três coisas:

- **A exportação apagava um edital em silêncio.** Dois registos com o mesmo
  número, data e assunto — o mesmo edital registado duas vezes com ficheiros
  diferentes, que acontece — davam o mesmo nome de ficheiro, e o segundo
  escrevia por cima do primeiro. A exportação dizia «2 publicados», ficava um
  ficheiro, e o índice apontava as duas linhas para ele. Perder um documento em
  silêncio é o pior que uma exportação pode fazer, porque quem a lê julga que
  está a ver tudo. O número do registo entra agora no nome quando é preciso.
- **Uma pasta recusada deixava a outra a meio.** As subpastas eram validadas à
  medida que se limpavam; se a segunda fosse recusada, a primeira já tinha o
  retrato de agora e a segunda o de ontem. Conferem-se as duas antes de se tocar
  em alguma.
- **O `--conferir` ia relatar ficheiros que não são ecrãs.** A lista era de
  exclusões (`.html`, `.json`, `.zip`), e uma cópia `.bak.1` de uma gravação
  atómica não acaba em `.json` — apareceria como ecrã órfão, a mandar alguém
  procurar um problema que não existe. Passa a contar o que É um ecrã. Um
  relatório que grita por nada deixa de ser lido, e aí deixa de apanhar o que
  interessa.

### Testes
37 novos, 336 no total. Os dois que mais interessam não testam funcionalidade,
testam **contenção**: `--conferir` não mexe num único ficheiro nem num único
estado, e a exportação não apaga uma pasta que não tenha sido ela a criar.

## 0.17.0 — Onda 3 (3/4): ler aos bocados, e dizer em que vai

### Corrigido
- **A leitura de um documento carregava todas as páginas rasterizadas de uma
  vez.** Medido a sério, com o RSS do processo e não com o `tracemalloc` — que
  não vê estes buffers, porque são do PyMuPDF em C:

  | páginas | antes | agora |
  |---|---|---|
  | 5 | 180 MB · 0,45 s | 101 MB · 0,33 s |
  | 20 | 430 MB · 2,03 s | 102 MB · 0,50 s |
  | 50 | 955 MB · 5,28 s | 102 MB · 1,29 s |
  | 100 | **1826 MB** · 11,65 s | **102 MB** · 2,99 s |

  Pico absoluto do processo, medido nos dois lados com a mesma régua, num
  processo por medição e com o PDF já feito. Desses 102 MB, **53 MB são os
  módulos** — o PyMuPDF e o Pillow importados, antes de se ler o que quer que
  seja. O trabalho em si são os ~49 MB que sobram, e é esse número que deixa de
  crescer.

  (A primeira versão desta tabela dava 48 MB na coluna da direita. Era o
  *acréscimo* sobre a linha de base, posto a par de absolutos na coluna da
  esquerda — uma tabela com duas réguas, que é uma forma educada de exagerar. A
  medição refeita está acima; o ganho é o mesmo, e o de 100 páginas é maior do
  que o que estava dito.)

  Antes era linear e sem tecto. Num portátil de serviço isso não é lentidão, é o
  processo a morrer — e morre no documento grande, que é o que ninguém quer ter
  de voltar a tratar. Passa a ser **constante**.

  A peça que torna isto possível é o tamanho de cada página sair do PDF **sem
  rasterizar nada**, e é só disso que o agrupamento por orientação precisa.
  Decide-se primeiro o que vai com o quê, e só então se rasterizam as (até três)
  páginas do ecrã que se está a compor.

  Os metadados também deixam de exigir rasterização: num PDF com texto
  pesquisável, que é a maioria dos editais, lêem-se em **0,057 s e 6 MB** contra
  os 3,76 s e 900 MB de antes. Só um documento sem texto — uma digitalização, um
  printscreen — obriga a rasterizar uma página, para o OCR ter de onde ler.

- **O painel não dizia nada enquanto trabalhava.** Compor os ecrãs de um edital
  de vinte páginas leva dezenas de segundos entre carregar em «Publicar» e a
  imagem aparecer na televisão. Durante esse tempo quem estava ao teclado tinha
  duas hipóteses igualmente más: esperar sem saber se alguma coisa estava a
  acontecer, ou carregar outra vez — que é o que as pessoas fazem, e com razão.

### Acrescentado
- `lib/progresso.py` e uma faixa no painel: «A compor os ecrãs de
  «edital_grande.pdf» (3 de 8)». Enquanto há trabalho, o painel sonda de 3 em 3
  segundos em vez de 20 — uma barra que só se mexe de vinte em vinte segundos
  não é progresso, é um cartaz. Acabado o trabalho, volta ao ritmo lento.

  Não é uma fila de tarefas, e não finge sê-lo: o agente faz uma coisa de cada
  vez, e o que faltava responder é «está a fazer o quê, e em que ponto». Uma
  fila com prioridades e cancelamento resolveria um problema que este posto não
  tem.
- `tratamento.agrupar_indices()`: a regra de agrupamento a trabalhar sobre
  dimensões em vez de imagens. `agrupar_ecras()` passou a delegar aqui, para a
  regra viver num sítio só — uma segunda cópia era o caminho certo para os dois
  agrupamentos discordarem um dia, e para o ecrã da televisão ficar diferente do
  que o painel mostrou.
- 48 testes novos, 385 no total.

### Corrigido na revisão à mão, antes de entrar
O Sourcery ficou sem orçamento de revisão e este trabalho entrou sem revisão
automática. A revisão à mão — a tentar partir o código com código, e não só a
lê-lo — encontrou cinco defeitos: quatro nascidos nesta peça, e um antigo que
esta peça tornaria perigoso.

- **A faixa de trabalho nunca se apagava.** O `progresso.parado()` estava
  escrito, documentado e testado, e não era chamado de lado nenhum. A faixa
  acendia-se no primeiro documento e ficava acesa para sempre, a anunciar um
  trabalho terminado — e o painel, que sonda de três em três segundos enquanto
  ela estiver visível, ficava preso nesse ritmo até alguém reiniciar o serviço.
  Uma função testada não é uma função ligada: os testes do módulo estavam todos
  verdes. Os novos atravessam o agente, que é onde o defeito vivia.
- **Um `.docx` arrancava o LibreOffice uma vez por ecrã.** Ler por página quer
  dizer voltar ao documento de cada vez, e num Word isso custa uma conversão
  inteira. Dez páginas davam **cinco arranques** onde antes havia um, e cada
  arranque custa segundos. A conversão passa a ser guardada e reaproveitada.
- **Dois `edital.docx` em pastas diferentes davam o mesmo PDF** na pasta de
  trabalho — defeito antigo, que passava despercebido só porque cada chamada
  reconvertia por cima. Com a conversão reaproveitada deixaria de ser inofensivo:
  o segundo edital sairia na televisão com o conteúdo do primeiro. O PDF
  convertido passa a ser nomeado pela identidade do original.
- **As dimensões previstas não eram as reais.** Estavam calculadas com `round()`,
  e um comentário afirmava que era o que o PyMuPDF fazia. Não era: medido em 300
  páginas aleatórias, errava em **217**. Num A4 não se vê; numa página quase
  quadrada um píxel decide a orientação, e a orientação decide se a folha vai
  sozinha para um ecrã. Quatro páginas assim davam **dois ecrãs em vez de
  quatro**. Passa a ser a mesma conta que o `get_pixmap` faz, e não uma imitação.
- **A contagem da publicação nunca chegava ao fim** («0 de 4» a «3 de 4»), e uma
  composição que falhasse a meio deixava os ecrãs já gravados na pasta de saída
  sem dono — a televisão não os mostra, o arquivo não os conhece e o
  `--conferir` não dá por eles, porque só olha do registo para o disco.

Os dezassete testes que os fixam foram corridos contra o código anterior, que é
a única forma de saber se provam alguma coisa: **treze falham lá e passam aqui.**
Os outros quatro são os casos fáceis — um A4 direito, um A4 rodado — que passam
dos dois lados; ficam para fixar o comportamento, não para apanhar o defeito. Um
teste que passa nos dois lados não estava a provar nada, e o teste que já lá
estava para este caso usava só A4 exacto: passava com qualquer arredondamento, e
a docstring dele falava justamente do caso que não cobria.

### Garantido
**A composição é idêntica ao bit.** Seis formas de documento — uma, duas, três e
cinco verticais, uma deitada, e um misto — compostas pelos dois caminhos e
comparadas pelo resumo SHA-256 de cada PNG: **9 imagens, 9 iguais, 0 diferentes.**
O teste corre em cada execução, e não foi uma verificação de uma vez.

Esta peça é desempenho, e uma melhoria de desempenho que muda o que aparece na
televisão não é uma melhoria — é uma regressão com um gráfico bonito.

### O que esta peça NÃO resolve
A composição 4K continua a custar **~2,5 s e ~650 MB de pico por ecrã**, e isso
não mudou. A diferença é que esse custo é **por ecrã** e não por documento: era
o crescimento sem tecto da leitura que matava o processo, e é esse que
desapareceu. Um documento de trezentas páginas passa a ser lento; deixa de ser
impossível.

## 0.18.0 — A certidão a dizer a verdade

Veio uma certidão real do registo 19 para ser lida com olhos de ver. Trazia, no
campo **Assunto**, isto: «MUNICÍPIO DE MOIMENTA DA BEIRA». O nome da câmara
impresso duas vezes na mesma folha — uma como timbre, no cabeçalho, e outra como
matéria daquilo que ela própria tinha afixado. A partir desse fio vieram os
outros.

### Corrigido

- **O timbre virava assunto.** A leitura procura o título a seguir à palavra
  «EDITAL»; num documento que não é edital — uma ficha de projeto, um ofício —
  esse marcador não existe e caía-se no recurso: «a primeira linha com doze
  letras». Numa folha timbrada, a primeira linha é sempre o timbre. E havia um
  segundo buraco a agravá-lo: a entidade emissora era procurada numa lista
  fechada de quatro nomes onde «MUNICÍPIO DE …» não estava, por isso o timbre
  nem sequer era reconhecido como entidade — e nada o impedia de virar assunto.

  Passa a haver uma lista só, que serve para as duas coisas: reconhecer quem
  emite, e excluí-lo de ser tomado por aquilo que se diz. O mesmo documento dá
  agora assunto «FICHA DE PROJETO» e entidade «MUNICÍPIO DE MOIMENTA DA BEIRA»,
  cada coisa no seu sítio.

  A ordem importa e é o contrário da intuitiva: procura-se primeiro o **órgão**
  (Assembleia Municipal, Câmara Municipal) e só depois o timbre. Num edital da
  assembleia em papel do município, quem pratica o ato é a assembleia. Cheguei a
  pôr o timbre à frente, e um teste que já existia apanhou-o na primeira
  execução.

- **«0 dia(s) desde a afixação».** Duas coisas más ao mesmo tempo: o parêntesis
  do plural, que não se escreve num documento que vai para dentro de um
  processo, e o zero, que em português não é uma duração — um documento afixado
  esta manhã não esteve afixado zero dias. Passa a «Menos de um dia», «1 dia»,
  «N dias».

- **O número desaparecia em silêncio.** Só se imprimia quando existia. Quem lia
  a certidão não conseguia distinguir «este documento não tem número» de «o
  sistema perdeu o número». Passa a imprimir-se sempre, com «(não atribuído)»
  quando é o caso — como já se fazia com o assunto.

- **A certidão não dizia o tamanho do que foi afixado.** Identificava o
  documento pelo nome, pela data e pelo resumo criptográfico, e nunca pelo
  número de folhas. Se amanhã alguém discutir o que esteve no expositor, quantas
  páginas lá estiveram faz parte da identidade daquilo. Passa a constar.

- **«Mantém-se afixado nesta data» sem dizer até quando.** É a pergunta mais
  útil que a certidão pode responder, e é uma data que a lei fixa. Quando há
  data de retirada prevista, aparece.

- **Um palpite da máquina com ar de facto verificado.** O registo marca os
  campos que a leitura automática propôs e que ninguém confirmou — e limpa essa
  marca assim que uma pessoa corrige o campo, por isso o que lá fica é mesmo por
  confirmar. A certidão imprimia-os ao lado dos confirmados, sem distinção
  nenhuma. Foi exactamente assim que o timbre da câmara se tornou, num documento
  oficial, o assunto de um documento afixado. Passa a haver uma linha a dizer
  quais os elementos que foram lidos automaticamente e não chegaram a ser
  confirmados por quem afixou.

### Alterado

- **O selo de conferência passa a cobrir os factos novos** (páginas, retirada
  prevista, campos por confirmar). De nada serviria imprimir o número de páginas
  se o selo não o cobrisse: bastava alterá-lo no papel para a conferência
  continuar a bater certo.

  Isto tem uma consequência que não se esconde: **o selo do mesmo registo muda.**
  Uma certidão emitida antes desta versão deixa de conferir contra o registo, e
  isso parece-se com uma falsificação em vez de com uma actualização. Por isso o
  rodapé passa a dizer o **formato** a que o selo pertence — «(formato 2)» —, e
  quem confere um papel que não o mencione sabe que é do formato 1 e refaz a
  conta sobre o conjunto de factos antigo. O número do formato sobe quando mudar
  o que o selo cobre, nunca por uma mudança de aspeto.

### Mantido de propósito

A certidão continua **sem espaço para assinatura**. Foi desenhada para se
conferir pelo selo junto do serviço emissor, e diz isso na cara: «Não constitui
assinatura eletrónica». Uma linha de assinatura convidaria a tratá-la como
documento assinado, que não é. Decidido na conversa de 23/09/2026.

### Corrigido na revisão à mão, antes de entrar

O Sourcery voltou a ficar sem orçamento e este trabalho também não teve revisão
automática. A revisão à mão encontrou **um defeito na própria correção**, e pior
do que o defeito que ela vinha corrigir.

A lista que passou a reconhecer o timbre incluía as palavras que abrem o nome de
um serviço — «Divisão», «Departamento», «Gabinete», «Serviços», «Setor»,
«Unidade» — e excluía do assunto qualquer linha começada por elas, em qualquer
ponto da folha. Só que essas mesmas palavras abrem títulos de edital
perfeitamente vulgares:

```
SERVIÇOS MÍNIMOS DURANTE A GREVE DOS TRABALHADORES
DIVISÃO DE URBANISMO — CONSULTA PÚBLICA DO PDM
DEPARTAMENTO DE OBRAS — ABERTURA DE CONCURSO PÚBLICO
```

Sete de sete títulos plausíveis desapareciam, e desapareciam **em silêncio**: o
assunto passava a ser a linha seguinte, que podia ser qualquer coisa. Trocar o
timbre impresso como assunto por um assunto certo apagado é trocar um defeito
por um pior, porque o primeiro vê-se e o segundo não.

O teste que devia ter apanhado isto existia — e passou, porque só experimentava
títulos que não começavam por essas palavras. É o mesmo padrão da peça anterior:
o teste cobre o caso fácil e a docstring fala do difícil.

A correção da correção são **duas listas em vez de uma**:

- **Instituições** («MUNICÍPIO DE …», «CÂMARA MUNICIPAL …», «JUNTA DE FREGUESIA
  …»): excluídas onde quer que apareçam. O nome da instituição nunca é o assunto
  de coisa nenhuma, e era este o defeito original.
- **Unidades orgânicas** («Divisão de …», «Serviços …»): só contam como timbre
  nas **três primeiras linhas** da folha, que é onde o timbre vive — e nunca
  abaixo do marcador «EDITAL», porque abaixo dele o que vem é o título, por
  construção.

Fica um caso que nenhuma regra de texto resolve: um documento **sem** o marcador
«EDITAL» cujo título comece por uma palavra de unidade e esteja logo a seguir ao
timbre. A olho distingue-se pelo corpo de letra e pela posição na folha; no texto
extraído de um PDF, não. Aí não se inventa certeza — o assunto sai com confiança
0,5, abaixo do limiar, o painel assinala-o para confirmação e a certidão declara
que ninguém o confirmou. Há um teste que fixa esse contrato, e não o acerto.

### Testes

41 novos nesta versão, 426 no total depois de a 0.17.0 entrar. Os dezanove que
guardam a segunda correção foram corridos contra a primeira: os dezanove falham
lá e passam aqui.

## 0.19.0 — Onda 3 (4/4): quem compõe o ecrã é a televisão

Compunha-se em Python uma imagem de 3840×2160 por ecrã — fundo, sombras e
folhas cozidos num PNG de 3 MB — e mandava-se para a televisão. Era o passo mais
caro de publicar, e o mais desnecessário dos dois que existiam.

### O que se descobriu antes de mudar fosse o que fosse

A página da televisão **já desenhava** um fundo verde com veias douradas, em
canvas. Esse fundo estava 100 % tapado: num televisor 16:9, o PNG opaco de 16:9
cobre o ecrã todo. Confirmado a medir a imagem no browser — 1920×1080 numa janela
de 1920×1080 — e a fotografar a página com o PNG escondido, que é o que mostra o
que estava por baixo.

Pagava-se duas vezes pelo mesmo fundo, e via-se o mais caro.

### Corrigido

- **Publicar deixa de compor.** A televisão passa a receber as folhas já
  ajustadas à sua caixa e as coordenadas onde assentam, e compõe o ecrã ela
  própria: as folhas posicionadas sobre o fundo que já desenhava, com as sombras
  em `box-shadow` — os dois níveis que o numpy fazia com dois desfoques
  gaussianos sobre uma máscara de 3840×2160, e que aqui custam zero.

  Medido com o mesmo guião e instalação nova dos dois lados:

  | páginas | ecrãs | antes | agora |
  |---|---|---|---|
  | 3 | 1 | 12,01 s · 1131 MB | **0,42 s · 441 MB** |
  | 20 | 7 | 73,82 s · 1213 MB | **2,16 s · 441 MB** |
  | 50 | 17 | **117,76 s** · 1214 MB | **5,20 s** · 442 MB |

  Estes números incluem o aquecimento da cache de fundos, que uma instalação
  nova paga e as seguintes não. Em regime, por ecrã e com a cache quente, são
  3,02 s e 546 MB contra 0,36 s e 200 MB. As duas medições estão aqui porque uma
  sozinha exagerava: a primeira a favor, a segunda contra.

  Em disco, um edital de 50 páginas passa de 51,65 MB de PNG para 6,66 MB de
  folhas.

- **O PNG 4K mudou de momento, não desapareceu.** Faz-se na **retirada**, à porta
  do arquivo. O ZIP de arquivo permanente continua a receber exatamente o mesmo
  ficheiro que recebia antes — é ele a prova do que esteve afixado — mas o custo
  saiu de onde havia alguém à espera e passou para uma arrumação onde não há.
  Decidido na conversa de 24/09/2026.

- **O ZIP do expositor ficava vazio de imagens.** Agrupava os PNG dos editais
  publicados, que passaram a não existir enquanto o edital está afixado. Sem
  correção, passaria a levar o registo e mais nada, sem se queixar — que é a pior
  forma de uma cópia de segurança falhar. Passa a levar as folhas, o `slides.json`
  e o registo: com as três coisas reconstrói-se o expositor noutra máquina.

- **O `--conferir` denunciava o logótipo e não via as folhas.** O logótipo passou
  a ser servido como imagem à parte, e era reclamado por registo nenhum: seria
  apontado como órfão a cada execução, e um relatório que se queixa sempre da
  mesma coisa deixa de ser lido. As folhas, sendo JPEG, não eram sequer contadas
  — uma folha deixada para trás por um registo apagado não era denunciada por
  ninguém.

### Acrescentado

- `tratamento.caixas_do_ecra()` e `folhas_do_ecra()`: a regra de onde cada folha
  assenta, num sítio só. Há dois consumidores das mesmas coordenadas — a
  composição que vai para o arquivo e o browser que desenha o ecrã — e uma
  segunda cópia da regra era o caminho certo para o arquivo deixar de provar o
  que esteve afixado. Mesma lição do `agrupar_indices`, na peça anterior.
- `tratamento.ha_espaco_para_o_logotipo()`: a mesma pergunta de sempre —
  «o canto está livre?» — respondida por geometria em vez de amostragem de
  píxeis, porque quem compõe no browser não tem imagem para amostrar.
- Campo `ecras` no registo, com migração. Fica vazio nos registos anteriores: era
  possível inventar um desenho a partir do PNG já composto, mas isso é adivinhar
  onde as folhas assentaram, e a publicação seguinte sabe-o de facto.

### Garantido

**As coordenadas são as mesmas nos dois lados.** O que a televisão desenha, medido
no browser, é o que o Python calcula: com o ecrã a metade da escala, as folhas em
x=81, 1319 e 2557 aparecem em 41, 660 e 1279. Se divergissem, a imagem arquivada
deixava de ser prova do que esteve afixado — e é só para isso que ela existe.

**A composição 4K não mudou um píxel.** A extração da regra das caixas foi
verificada a comparar o resumo SHA-256 de um PNG composto antes e outro depois:
idênticos ao byte. Fazia falta prová-lo por fora, porque o teste de «idêntico ao
bit» da peça 3 compara os dois caminhos um com o outro na mesma execução, e não
apanharia uma alteração que afectasse os dois por igual.

### Removido

`recuperar_do_arquivo()`. Existia para trazer de volta do ZIP os PNG de um edital
reposto no ecrã, em vez de os recompor. As folhas refazem-se em 0,36 s, que é
menos do que abrir o ZIP — e deixa o arquivo de ser fonte de coisas substituíveis.

### Testes

28 novos, 454 no total. Os catorze de `test_compor_no_browser.py` foram corridos
contra o código anterior: onze falham lá e passam aqui.

