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

### Corrigido na revisão à mão, antes de entrar

O Sourcery voltou a ficar sem orçamento e este trabalho também não teve revisão
automática. A revisão à mão não encontrou defeito no código — encontrou um
**buraco nos testes**: nenhum deles usava um documento **deitado**.

Isso importa porque a caixa larga tem outra regra. A caixa vertical é de tamanho
fixo; a larga encolhe ao tamanho exato do que leva dentro e recentra-se. É por aí
que uma diferença entre o que a televisão desenha e o que o arquivo guarda
entraria sem ninguém dar por ela — e é precisamente a coisa que esta peça não
pode deixar acontecer.

Verificado a funcionar, e não só a ler: um misto de duas verticais, uma deitada e
outra vertical dá três ecrãs, e as caixas medidas no browser batem certo com as
que o Python compõe (x=732 e 2375 de largura, que ao meio da escala dão 366 e
1188). Acrescentados três testes, incluindo a retirada de um documento de vários
ecrãs — só se tinha provado com um, e um edital de três folhas que deixasse duas
por arquivar perdia dois terços da prova do que esteve afixado.

De caminho, um susto que não era: numa fotografia, a folha deitada aparecia
acinzentada. Medida, estava a 93 % de opacidade — o `.slide` desvanece em 1 s e
eu fotografei aos 700 ms. Com o tempo completo, branco puro. O erro era do meu
método, não da página.

### Testes

31 novos, 457 no total. Os dezassete de `test_compor_no_browser.py` foram
corridos contra o código anterior: onze falham lá e passam aqui; os outros seis
cobrem o caso deitado, que o código anterior nem conseguia executar.

## 0.20.0 — Três arestas que ficaram por limar

Nenhuma destas impedia a aplicação de funcionar, e é por isso que ficaram para
trás — foram sendo assinaladas ao longo da Onda 3, sempre fora do âmbito da peça
que estava em cima da mesa. As três apareciam no pior momento possível: a
instalar, ao fim de um ano, ou a correr a bateria duas vezes ao mesmo tempo.

### Corrigido

- **`--criar-utilizador` sem terminal respondia com um traceback.** É o primeiro
  comando que alguém corre numa instalação nova, e num serviço ou num script
  saíam sete linhas de `EOFError: EOF when reading a line` — que não dizem a
  ninguém o que fazer a seguir.

  E havia um caso pior, que só apareceu a reproduzir isto com calma: com o
  stdin canalizado, **a conta era criada na mesma**. O `getpass` não falha sem
  terminal; cai para uma leitura normal, avisa `Password input may be echoed` em
  inglês no meio de uma aplicação toda em português, e deixa a senha à vista. A
  razão de o `getpass` ali estar é precisamente a senha não ficar à vista.

  Passa a recusar **antes de perguntar seja o que for**, e a dizer em português
  o que falta e qual é o comando a repetir. Ctrl-D ou Ctrl-C a meio das
  perguntas passam a ser o que são — uma desistência, não uma avaria.

  De caminho, duas correções ao diagnóstico que eu próprio tinha escrito: o
  código de saída já era 1 e não 0 (tinha-me enganado com um `tail` a engolir o
  código), e quem rebentava era o `input()` do nome completo, não o `getpass`.

- **A pasta de trabalho crescia sem fim.** Guarda o PDF de cada `.docx`
  convertido, para não se pagar um arranque do LibreOffice de cada vez que se
  volta ao mesmo documento. Medido: **duzentos editais em Word deixavam lá
  duzentos ficheiros**, e um documento editado cinco vezes deixava cinco cópias.
  Não é muito por ano — é que não tinha fim.

  Passa a apagar-se o que ninguém usa há trinta dias, na mesma arrumação do
  ciclo onde já se limpa o resto. **Por desuso e não por idade**: cada
  reaproveitamento marca a conversão como usada, senão um documento
  reconvertido todas as semanas era apagado na mesma ao fim de um mês e a
  conversão seguinte pagava outro arranque do LibreOffice sem razão nenhuma.

  Apaga só o que esta aplicação escreveu — os nomes com o resumo de doze
  dígitos que o `_word_to_pdf` lhes dá. Uma pasta chamada «trabalho» convida a
  lá pôr coisas, e uma limpeza que apaga o que não conhece é uma armadilha à
  espera.

- **Os testes do painel disputavam uma porta fixa.** Um contador subia a partir
  de 8951 a cada teste, o que dava portas diferentes dentro de uma execução mas
  a mesma sequência em todas. Medido: **22 erros de «Address already in use»**
  em duas execuções em paralelo, com 22 testes a não chegar a correr.

  O `PainelServer.iniciar()` passa a devolver a porta em que ficou mesmo a
  escutar, e os testes pedem `porta=0` — é o sistema operativo que escolhe uma
  livre, sem disputa possível. As mesmas duas execuções em paralelo: 30 e 30
  testes verdes, zero erros de porta.

### Corrigido na revisão à mão, antes de entrar

O Sourcery continua sem orçamento e este trabalho também não teve revisão
automática. A revisão à mão encontrou **um buraco na própria correção** da
primeira aresta.

`sys.stdin.isatty()` parece bastar, e não basta. No Windows, um programa aberto
com o **pythonw** — que é o que acontece a um duplo clique num ficheiro `.py` —
corre com `sys.stdin` a `None`, e o `isatty` rebenta com um `AttributeError`.

Ou seja: a verificação que existe para não haver traceback nenhum **produzia ela
própria um traceback**, e logo no caso mais provável de alguém a instalar isto
num posto municipal, que é o duplo clique. Em Linux nunca se via, porque há
sempre um stdin.

Passa por uma função que responde à pergunta sem confiar em que o stdin exista:
`None`, um stdin já fechado (`ValueError`) e um objeto sem `isatty` nenhum dão
todos a mesma resposta — não há teclado do outro lado.

### Testes

15 novos, 472 no total. Treze falham contra o código anterior; os outros dois —
o que exige que nada recente seja apagado, e o que aceita uma pasta inexistente —
passam nos dois lados **de propósito**, porque fixam o que a limpeza *não* pode
fazer.

---

## 0.20.1 — As regras da casa, por escrito

Terceiro número e não segundo: **nada mudou no que a aplicação faz.** O que mudou
foi aquilo contra o que ela passa a ser revista.

### O que se descobriu

O repositório não tinha ficheiro nenhum de instruções para quem revê: nem
`AGENTS.md`, nem `CLAUDE.md`, nem `CONTRIBUTING.md`, nem
`.github/copilot-instructions.md`. A doutrina toda — português europeu, nada de
emojis, o `CHANGELOG` a crescer para baixo, os testes a correrem de propósito sem
LibreOffice, os assuntos de commit sem acentos — vivia em 800 linhas de `README`
escritas para pessoas.

Nenhum revisor automático lê um `README` de 800 linhas à procura de convenções.
Revê contra o que conhece de outros projetos. Isso explica boa parte do que se
viu: descrição em vez de achados.

### Acrescentado

- **`AGENTS.md`** — as regras completas, derivadas de prova neste repositório e
  não de boas intenções. Cada uma delas nasceu de um defeito concreto: a regra de
  que um teste novo tem de falhar contra o código anterior nasceu de três testes
  que descreviam o caso difícil e exercitavam o fácil; a regra de medir os dois
  lados com a mesma régua nasceu de uma tabela de memória que dizia o contrário
  do que acontecia; o aviso sobre alargar listas de exclusão nasceu da correção
  que engolia sete em sete títulos de edital legítimos.
- **`.github/copilot-instructions.md`** — o mesmo em resumo, para a revisão do
  Copilot, que trabalha com menos contexto.
- **`README`, secção 19** — o processo de revisão, e porque é que a revisão à mão
  fica de pé independentemente da ferramenta que estiver ligada.

### Corrigido

- O `CHANGELOG.md` tinha, na última linha, um `\n` literal — resto de um heredoc
  mal fechado numa peça anterior. Estava publicado assim desde a 0.20.0. Não tem
  consequência nenhuma além de ser feio, e é exatamente o género de coisa que uma
  revisão automática apanha e que uma pessoa cansada não vê.

### Sobre a revisão automática

As sete PRs anteriores mediram-se: 325 759 caracteres de diff em 1 dia e 20 horas.
O orçamento do Sourcery são 250 000 caracteres por 7 dias, ou seja 35 714 por dia.
Este ritmo é cinco vezes o que esse orçamento aguenta, e partir as PRs em pedaços
mais pequenos não resolve nada — o orçamento conta caracteres, não PRs.

Fica dito, em abono da ferramenta: quando teve orçamento, na #7, o Sourcery
encontrou uma janela entre conferir uma pasta e limpá-la que mais ninguém tinha
visto. O problema não é a qualidade da revisão. É ela não acontecer.

---

## 0.20.2 — A revisão automática passa a ler as regras da casa

Terceiro número outra vez: **nada mudou no que a aplicação faz.**

### Acrescentado

- **`.github/workflows/revisao.yml`** — revisão automática em cada PR, pela ação
  `anthropics/claude-code-action@v1`. O primeiro que faz é ler o `AGENTS.md`,
  que é o ponto todo: o revisor anterior revia contra convenções genéricas
  porque não tinha como conhecer as nossas.

  Corre com a conta Claude de quem mantém o projeto e não com uma chave de API
  — segredo `CLAUDE_CODE_OAUTH_TOKEN`, gerado com `claude setup-token`.

### A decisão que ficou tomada

**Sem credencial, o trabalho salta em vez de falhar.** O contexto `secrets` não
está disponível num `if` de passo, por isso passa por uma variável de ambiente ao
nível do trabalho, que é onde está acessível. Sem esse contorno, quem clonasse
este repositório sem token via **todas** as PRs a vermelho — e uma revisão que
estraga o CI é pior do que revisão nenhuma.

O gatilho é `[opened, synchronize]`: revê a PR e revê outra vez a cada push. As
PRs daqui levam correções a meio da revisão e é precisamente aí que entram os
defeitos. Se o consumo da subscrição incomodar, tira-se o `synchronize` e passa a
uma revisão por PR.

O comentário é fixo e atualiza-se em vez de se empilhar. São precisos **dois**
parâmetros, e o que faz o trabalho é o `track_progress`: com um `prompt`, a ação
corre em modo de automação e não cria comentário nenhum, e nesse modo o
`use_sticky_comment` sozinho não tem o que governar.

O `gh pr comment` não está na lista de ferramentas, de propósito. O exemplo
oficial com `track_progress` mantém-no, mas aí a promessa de um só comentário
depende de o modelo obedecer ao prompt. Sem a ferramenta, passa a ser estrutural.

**Um push durante uma revisão cancela a anterior.** Sem o grupo de concorrência,
uma sequência rápida de correções punha três revisões a correr ao mesmo tempo,
todas a gastar subscrição e só a última a interessar.

**O checkout não deixa credenciais para trás.** O `actions/checkout@v6` guarda o
token num ficheiro sob `$RUNNER_TEMP` e aponta-lhe do `git config`. Quem revê tem
leitura de ficheiros e recebe pela frente texto escrito por qualquer pessoa que
abra uma PR neste repositório público. A revisão não faz operações git
autenticadas: `persist-credentials: false`.

**A pasta de trabalho tem o ramo base, não o da PR.** A `docs/security.md` da
ação diz *«do not check out an untrusted ref into the workspace root before this
action»*, e aqui havia uma razão acrescida: o prompt manda ler o `AGENTS.md` da
pasta de trabalho. Vindo do topo da PR, uma alteração a esse ficheiro reescrevia
as regras que o revisor foi mandado obedecer — o revisor a receber instruções do
código que está a rever. Da base, as regras são as que já foram fundidas.

O que a PR mudou vê-se pelo `gh pr diff`, que lê a API e não a pasta — **com o
número da PR explícito**. Sem ele, o `gh` procura a PR do ramo atual, e um
checkout por SHA deixa a cópia sem ramo nenhum: a revisão corria e ficava sem
ver o diff. A correção de segurança cortou, sem dar por isso, a única via que
restava ao revisor para ver o que estava a rever.

### A primeira revisão automática foi ao próprio revisor

Vale a pena registar como isto foi parar aqui, porque é o argumento todo desta
peça em miniatura. As três correções acima **não são minhas**: são achados do
CodeRabbit sobre a versão anterior deste mesmo ficheiro, na PR que o trouxe.

A do comentário único era a mais séria, e era um defeito a sério: o que estava
escrito no `use_sticky_comment` prometia uma coisa que o modo de automação não
fazia, e este CHANGELOG dizia-o com todas as letras. Estava errado.

A verificação seguinte foi minha e nasceu da correção: ao explicar por escrito
porque é que o `gh pr comment` saía da lista, pus o comentário **dentro** do
bloco literal do `claude_args` — onde uma linha começada por `#` não é
comentário nenhum, é texto passado ao CLI. Cinco linhas de lixo à frente dos
argumentos. Apanhado a imprimir o que o CLI receberia mesmo, em vez de a olhar
para o ficheiro.

### Porque não o CodeRabbit, que também ficou ligado

Nenhuma razão contra — ficam os dois, e por uns tempos é bom que fiquem: revêem
o mesmo diff e vê-se o que cada um apanha. A preferência por este é de operação e
não de qualidade: é a conta de quem faz o trabalho, e é o único que lê o
`AGENTS.md` e revê pela ordem de gravidade deste projeto, em vez da ordem que
traria de qualquer outro.

O que ficou medido sobre o anterior está na 0.20.1 e não se repete aqui.

---

## 0.20.3 — A instalação no posto, por passos

Terceiro número: **nada mudou no que a aplicação faz.** O que mudou foi o que
existe para quem a vai instalar.

### Acrescentado

- **`servico/LISTA-DE-VERIFICACAO.md`** — a instalação toda por passos, da
  máquina à televisão. Cada passo diz **o que fazer** e **o que tens de ver**,
  porque uma lista que só manda fazer deixa quem a segue sem saber se resultou.

  Duas coisas que lá estão de propósito e não são burocracia: **a prova com
  editais verdadeiros** antes de dar a instalação por feita — é a única forma de
  saber se as heurísticas de extração servem para os editais desta câmara — e
  **alguém do posto a publicar um edital à frente de quem instala**. Se ninguém
  ali souber usar isto, não está instalado, está copiado.

  A lista acaba a dizer que, se alguma coisa não bater certo com ela, o defeito
  é dela. É para ser corrigida por quem a usou no terreno.

### Corrigido

- **O `config.exemplo.json` mandava definir `painel_senha`**, que foi retirada
  na Onda 2 e há três versões só serve para o agente avisar, no arranque, que
  já não faz nada. Quem copiasse o exemplo ficava a julgar que tinha o painel
  protegido por essa senha. Saiu, e o ficheiro passa a trazer o `municipio` e o
  `local_do_expositor` — que são os dois campos que saem impressos na certidão
  de afixação e que, esses sim, ninguém quer errados.

Apanhado a escrever a lista de verificação: ao conferir chave a chave o que o
exemplo mandava pôr contra o que o código lê mesmo, a `painel_senha` tinha uma
única ocorrência em todo o projeto — o aviso a dizer que não servia para nada.

### E três defeitos que a primeira revisão automática apanhou nesta própria peça

O revisor no CI correu pela primeira vez sobre esta PR e encontrou três coisas.
As três verificadas no código antes de se lhes tocar. A primeira é grave.

**1. A unidade systemd arrancava e não gravava nada.**

`ProtectSystem=strict` torna tudo só de leitura salvo o que estiver em
`ReadWritePaths` — e a lista tinha as pastas de trabalho mas **não a raiz do
projeto**, onde vivem o `registo_entrada.json`, o `utilizadores.json` e o
`registo_auditoria.jsonl`. Pior: a gravação atómica cria o temporário na mesma
pasta do destino (tem de ser — `os.replace` só é atómico dentro do mesmo sistema
de ficheiros), por isso nem declarar os ficheiros um a um resolveria. É a pasta
que tem de ser escrivível.

O serviço subia. O `/saude` respondia. O painel abria. E **nem uma conta, nem um
edital, nem uma linha de auditoria chegavam ao disco.** A pior forma de uma
falha se apresentar, porque parece que está a funcionar.

O custo da correção fica dito na unidade: o código passa a ser escrivível pelo
utilizador do serviço. A alternativa mais apertada — `StateDirectory=`, que a
documentação do systemd diz excluir a pasta do efeito do `ProtectSystem=` — fica
documentada no `servico/LEIAME.md` e não vai já, porque mudar onde o estado vive
faz uma instalação existente deixar de encontrar o registo dela.

**E a lista de verificação ganhou o passo que teria apanhado isto:** publicar um
edital verdadeiro **com o serviço instalado**. A lista mandava confirmar que o
serviço se levantava, e ele levantava-se. Arrancar não é funcionar.

**2. A televisão não recarrega de 5 em 5 minutos.**

Nunca recarregou. Busca o `slides.json` de **15 em 15 segundos**, compara a
versão e aplica os editais novos **sem recarregar** — o carrossel nem se
interrompe, e o `agente.py` até diz isso à letra num comentário. A afirmação
errada estava na lista nova *e* no README desde a secção 5.1. Corrigida nos
dois: era errada nas duas metades, porque não recarrega e é vinte vezes mais
rápida do que se dizia.

**3. A lista dava comandos que não correm em Windows.**

`.venv/bin/python` é Linux. O posto a que esta lista se destina é Windows, onde
o caminho é `.venv\Scripts\python.exe`. A lista estabelece agora a convenção
uma vez, com as duas formas, e usa-a nos cinco comandos.

## 0.21.0 — A data de retirada, proposta pelo tipo

Segundo número: **isto muda o que a aplicação faz.**

### O defeito, que era um buraco entre duas coisas certas

O `prazos.py` sabia calcular o prazo de cada tipo de documento, com a base legal
declarada e testado desde a Onda 2. O `registo.aplicar_retiradas_automaticas()`
sabia retirar sozinho tudo o que estivesse publicado com a data vencida, e é
chamado pelo agente a cada ciclo.

**Entre os dois não havia nada.** O `propor_retirada()` não era chamado em lado
nenhum fora dos próprios testes, e a `data_retirada` continuava a nascer vazia e
a depender de alguém se lembrar. A retirada automática só olha para quem tem
data — sem data, não há o que vencer.

Para ser exato, porque a primeira versão desta entrada exagerava: a data chegava
por **duas** vias, e as duas funcionavam. Alguém a escrever no painel, e a
migração do modelo antigo, que a traz do `retiradas.txt` (`lib/migracao.py`).
Os editais migrados tinham data e retiraram-se sozinhos como deviam.

O que nunca acontecia era um edital **nascido no fluxo atual** ganhar data. Esse
ficava afixado para sempre — e é toda a produção desde a Onda 2.

Não se descobriu a ler o código: descobriu-se a correr `--conferir` num posto
real, que respondeu **`publicado: 8 · retirado: 0`**, com documentos de junho
ainda no ecrã em setembro.

### Acrescentado

- **Ao publicar, o tipo do documento propõe a data de retirada** quando ninguém
  a escreveu. Mínimo legal quando existe; prazo sugerido quando não há mínimo.
  Cinco dias para uma deliberação de órgão autárquico, pelo artigo 56.º do
  Anexo I da Lei n.º 75/2013.
- **O painel mostra a proposta antes de se publicar**, no campo da retirada e
  com uma linha a dizer de onde veio. Se preenchesse em silêncio, decidia — e o
  `prazos.py` diz de si próprio, na primeira linha, que propõe e não decide.
- **O histórico regista de onde veio a data**, com o tipo que a produziu. Quem
  audita tem de poder distinguir um prazo decidido de um prazo calculado.

### As três recusas

- **Só na publicação**, porque é aí que o relógio legal começa e é da afixação
  que a certidão conta. Propor na validação seria contar de uma data que ainda
  pode mudar.
- **Nunca por cima de uma data escrita por uma pessoa.**
- **Nada para o tipo por omissão.** O `propor_retirada` devolve `None` e não se
  inventa um prazo legal para um documento cuja natureza ninguém declarou. Fica
  em branco à espera de uma pessoa, que é o comportamento certo.

### A conta não se repete em JavaScript

O painel recebe a data já calculada pelo servidor, num campo derivado que não se
grava. A alternativa — mandar os dias para o browser e somá-los lá — punha a
mesma regra em dois sítios, e aritmética de datas em JavaScript ainda por cima
arrisca o fuso horário.

### Testes

8 novos, 480 no total. **Seis falham contra o código anterior.** Os outros dois
passam dos dois lados **de propósito**, e está escrito no ficheiro: fixam o que
a alteração não podia mudar — que uma data escrita por uma pessoa não é pisada,
e que um tipo sem prazo não ganha data nenhuma.

---

## 0.22.0 — A referência interna, e os lençóis

### A referência, e sobretudo o que ela não é

Ficou esclarecido de onde vem o número do edital: do **Gestiona**, a aplicação
de gestão documental da Câmara. É oficial, e quem está ao teclado copia-o de lá.
**A aplicação não lho atribui, e esta peça não muda isso** — inventar uma
designação que sai impressa numa certidão de afixação é a primeira coisa que
este projeto se proibiu de fazer, e a tentação de «preencher o campo só para não
ficar vazio» é exatamente a forma que essa falha tomaria.

O que entra é uma etiqueta **nossa**, ao lado e nunca no lugar:

```
AE-20260929-0021
```

Aparece no painel e na certidão, rotulada como «Referência interna», a seguir ao
número. Serve para se dizer «o AE-20260929-0021» em vez de «aquele aviso da
escola, salvo erro».

**Derivada, não guardada.** Sai do `criado_em` e do `id`, que já existem e já são
imutáveis. Guardá-la abria a porta a divergir do que a produziu, e obrigava a uma
migração para nada.

**A data sozinha não chegava.** Num minuto entram vários ficheiros de uma vez, e
no registo deste posto entraram. O id é o que garante que não colidem.

### Os lençóis dourados

Pedido de quem usa isto: os filamentos do fundo da televisão deviam parecer
lençóis a esvoaçar. Eram vinte e seis linhas de 0,6 a 2,2 px de espessura.

Engrossar o traço não resolvia — uma linha grossa é uma fita, não um tecido. São
agora faixas preenchidas com duas margens, com a espessura a respirar ao longo
do comprimento, as duas margens em fases diferentes (é a torção que faz o pano
parecer pano) e duas frequências somadas para a margem não ser uma senóide
perfeita. Onze em vez de vinte e seis, e mais fracos: a área de cada um cresceu
umas quarenta vezes.

**Verificado com os olhos, não por dedução.** A página foi renderizada em
Chromium e fotografada em dois instantes, com o `requestAnimationFrame`
substituído por um que chama a função duas vezes com tempos escolhidos — assim
corre o código verdadeiro e a fotografia é de um segundo exato, reproduzível.

E a primeira leitura dessas fotografias foi **errada**: «a animação não corre».
Corria. O ecrã de arranque tem `z-index: 50` e fundo opaco, e eu estava a
fotografar a cortina. A segunda impressão também foi errada — «perdeu o
dourado» — e a medição desmentiu-a: nas zonas claras, o R menos o B passou de
−21,7 para −13,3. A versão nova é **mais** quente, não menos.

### O defeito que a revisão apanhou, e onde passa a fronteira do selo

A referência tinha entrado em `certidao.factos()`, e o selo de conferência é
calculado sobre esse dicionário. Medido: o mesmo registo passava de
`6295 6080 C2D5 1D18` para `DAA5 8F48 31AC 94A7`, com o rodapé a dizer «formato
2» nos dois casos. **Uma certidão emitida na 0.21.0 deixava de conferir** — e o
comentário que descreve exatamente este caso está no código, cinco linhas acima
de onde o campo foi acrescentado. Passei por cima dele.

Havia duas saídas: subir o `FORMATO` para 3, ou tirar a referência dos factos. A
medição decidiu, e não a preferência: a referência deriva do `criado_em`, que o
selo **não** cobre. Com ela lá dentro, o selo mudava sem que nenhum facto selado
tivesse mudado. Subir o formato tornava a discrepância legível mas deixava essa
dependência de pé.

Fica portanto fora dos factos e imprime-se na folha à mesma — **imprime-se, não
se atesta**. O selo volta ao valor da 0.21.0, e as duas certidões já emitidas
conferem outra vez. O `FORMATO` fica em 2, que é o que é verdade.

**Os três revisores apanharam este defeito, os três na mesma linha.** Os três
prescreveram subir o `FORMATO`; dois deles pediram ainda «verificação ciente da
versão», que não existe neste código — não há verificador nenhum, o selo
imprime-se e quem confere refaz a conta à mão. Construir esse mecanismo para
poder selar um campo que não devia ser selado era resolver o problema ao
contrário.

### A etiqueta no painel

Segundo achado, do CodeRabbit: o painel mostrava o `AE-...` cru, por baixo do
número do Gestiona, sem nada a distingui-los. A certidão imprime «Referência
interna» precisamente por essa razão — e eu apliquei a regra à certidão e não ao
painel. São dois sítios de desenho no `painel.html`, e o teste conta-os: se um
terceiro aparecer, ou se uma alteração futura mexer só num, falha.

### Testes

10 novos, 490 no total. Oito falham contra alguma versão anterior: quatro contra
a 0.21.0 (a referência não existia), dois contra o código desta mesma PR antes
da correção do selo, um contra a 0.21.0 por outra via (a certidão não imprimia a
referência) e um contra o painel sem etiqueta.

Os outros dois passam dos dois lados **de propósito**, e está escrito no
ficheiro: fixam que a referência não é guardada e que a aplicação nunca preenche
o número do edital.

O teste do selo é deliberadamente mais largo do que o defeito: não diz «a
referência não pode entrar nos factos», diz que **nenhum campo derivado do
`criado_em` pode mexer no selo**. Vale para o que lá quiserem pôr a seguir.

---

## 0.23.0 — A certidão, escrita como se escreviam as certidões

Pedido de quem usa isto, a 07/10/2026: tomar as certidões de oitocentos e do
princípio de novecentos como modelo, e ir buscar ao cabeçalho e ao rodapé dos
próprios editais do município o que falta.

### De formulário a documento

A certidão era uma lista de pares rótulo/valor em quatro secções numeradas.
Funcionava, e lia-se como um ecrã impresso. Passa a ser **prosa**:

```
                M U N I C Í P I O   D E   M O I M E N T A   D A   B E I R A
                        Divisão Administrativa e Financeira
    ───────────────────────────────────────────────────────────────────────

                                C E R T I D Ã O
                      de afixação e desafixação de edital
                              ──────────────────

    ANA ABREU, Chefe da Divisão Administrativa e Financeira, do Município
    de Moimenta da Beira:

                                C E R T I F I C A

        que, para os devidos efeitos, foi afixado no átrio do edifício dos
    Paços do Concelho, por este Município, o seguinte documento: deliberação
    de órgão autárquico, com o n.º 2026-0017, da autoria de ASSEMBLEIA
    MUNICIPAL, com data de vinte e nove dias do mês de junho de 2026 (...)
```

Texto justificado às duas margens, título com as letras afastadas, uma regra
curta a fechá-lo, o traço da assinatura e, por baixo, a **nota de conferência**
em corpo pequeno — a divisão que as certidões antigas já faziam entre o que se
certifica e as anotações de registo.

### As datas por extenso, e porquê

Não é enfeite. **Um algarismo altera-se com um traço de caneta e «vinte e nove»
não** — era por isso que os livros de notas se escreviam assim. Entra um módulo
novo, `lib/extenso.py`, em português **europeu**: «catorze» e não «quatorze»,
«dezasseis», «dezassete» e «dezanove» e não as formas com 'e'. Uma certidão de
um município português com «quatorze» lá dentro tem um erro à vista de quem a
receber.

O ano fica em algarismos de propósito: experimentou-se com ele por extenso e,
numa certidão que cita leis com ano, prazos com ano e um edital com ano, a
frase deixava de se ler.

Meses em minúscula, que é o que a norma em vigor manda. **A certidão vai buscar
o seu ar antigo à estrutura e às fórmulas, não a erros de ortografia.**

### O que o selo cobre não mudou — e está medido

Esta é a condição que a peça tinha de respeitar, e a regra do `FORMATO` di-lo
expressamente: ele sobe quando muda o **conjunto de factos** e nunca quando muda
o aspeto. Medido no mesmo registo, antes e depois da reescrita:

```
antes:  FORMATO 2 | selo 0129 7FA6 7E5E B66C | 17 chaves
depois: FORMATO 2 | selo 0129 7FA6 7E5E B66C | 17 chaves
```

Idêntico. As certidões já emitidas continuam a conferir. Há agora um teste que
fixa esse valor dígito a dígito: se mudar, alguém mexeu num facto sem subir o
formato.

### Três defeitos que a mudança destapou

**1. A régua media mal as aspas angulares.** O `get_text_length` do PyMuPDF para
de contar no primeiro carácter que não sabe ler. Medido:

```
'DELIBERACOES'    devolve 82,50 e desenha 82,50
'«DELIBERACOES'   devolve 80,06 e desenha 88,00
'«a'              devolve  5,50 e desenha 10,38
```

Repare-se na última: acrescentar uma letra não aumentou a medida nenhuma. A
correção anterior media o texto com os **acentos** retirados e acertava só neles.
A certidão passou a citar o assunto entre «angulares» e a primeira palavra do
assunto saiu desenhada **por cima** da segunda. Agora soma-se a largura de cada
carácter, um a um — bate ao centésimo nos três casos, e deixa de haver uma
classe inteira de caracteres por onde a régua possa voltar a falhar.

**2. O parêntesis do plural voltou pela porta das traseiras.** O `prazos.py`
escrevia «a afixação dura 2 dia(s)», e esse texto vai impresso na certidão. O
teste que proibia `dia(s)` passava por sorte: a sua fixture não gerava
incumprimento nenhum, e por isso nunca lá chegava.

**3. «do Moimenta da Beira».** A configuração de campo tem o nome sem o
«Município de». O formulário antigo nunca esbarrou nisto porque punha o nome
sozinho num cabeçalho, onde não concorda com nada.

### O cabeçalho e o rodapé dos editais

O desenho vem de lá: rótulos a negrito separados por barras, com o número de
folha à direita. Os **valores** não: a morada e os telefones ficam na
configuração, em `servico`, `cargo_de_quem_certifica`, `morada`, `sitio` e
`telefone`. Dão-se a ler na fotografia de um ecrã mas não se leem ao dígito, e
**ler um código postal de uma fotografia e escrevê-lo no código seria inventar a
morada de uma câmara municipal**. Em branco, a certidão sai sem eles.

### A nota de conferência vai inteira

Partida entre duas páginas, deixava a segunda com **uma linha solta** — mediu-se:
página 2 com uma linha de texto e o rodapé. Lê-se como defeito de impressão, não
como documento. O bloco passa a reservar o seu espaço antes de começar, e o
caso comum voltou a caber numa folha.

### Testes

**542 no total, 52 novos.** Quarenta e três vêm do `extenso.py`, que é módulo
novo e portanto não tinha como passar contra código onde ele não existe: as
formas do português europeu uma a uma, a regra do «e» depois dos milhares, a
concordância da preposição das horas e o plural das folhas e dos dias.

Dos quatro restantes, **dois falham contra o código anterior** — a régua a medir
as aspas angulares, e o nome do município a concordar na frase — e **dois passam
dos dois lados de propósito**, com a razão escrita no ficheiro:

- o **do selo** fixa um valor que tem de ser o mesmo antes e depois. É a prova
  de que a reescrita não tocou num facto, e falhar ali é uma certidão antiga
  deixar de conferir.
- o **da sobreposição de palavras** olha para as palavras realmente desenhadas e
  exige que cada uma acabe antes de a seguinte começar. Passava antes porque não
  havia justificação nenhuma; falhou contra a versão intermédia desta peça, com
  a régua ainda errada — e foi assim que o defeito das angulares se apanhou.

No `test_prazos.py`, o teste do aviso curto passa a exigir «dois dias» e a
proibir `dia(s)` no próprio aviso, que é onde o parêntesis nascia.

### Apanhado em revisão: a certidão não se emitia com o local em branco

Um `"local_do_expositor": ""` no `config.json` rebentava com `IndexError`.
Reproduzido antes de se lhe tocar, e o mecanismo confirmado no código: o
`load_config()` faz `cfg.update(json.loads(...))`, portanto a chave presente com
valor vazio **sobrepõe-se** ao valor por omissão. O `.get(chave, omissao)` só
cobre a chave em falta, e a seguir fazia-se `local[0]`.

Antes desta peça isso imprimia um campo vazio. Depois dela deixava de emitir a
certidão — no caminho do pedido de certidão.

A revisão sugeria documentar que a chave tem de ser um nome masculino singular.
**Fui mais longe**, porque isso resolvia o sintoma e deixava a armadilha montada:
«Paços do Concelho» é um valor plausível para muita câmara, e é plural.

```
antes:  foi afixado no {local}              ->  «no receção», «no Paços»
agora:  no local designado por «{local}»    ->  certo para qualquer género e número
```

O valor sai tal e qual foi configurado, entre angulares, sem minusculizar a
inicial. **Deixa de concordar com o que quer que seja** — que é o que o torna
certo para todos os casos de uma vez, em vez de certo para os que hoje por acaso
lá estão.

Cinco testes, todos a falhar contra o código desta PR antes da correção: um para
o valor em branco, e quatro parametrizados com um local masculino, um feminino,
um plural e outro feminino singular.

## 0.23.1 — Sete erros que a revisão da certidão apanhou

A certidão oitocentista entrou na 0.23.0 e a revisão automática leu-a com mais
atenção do que eu. Sete defeitos, duas rondas, todos reproduzidos antes de se
lhes tocar — e todos num documento que entra num processo, que é onde um erro
de português custa mais do que um erro de código.

### Cinco erros de português apanhados pela revisão automática

Todos reproduzidos antes de se lhes tocar, e todos num documento que entra num
processo — que é onde um erro de português custa mais do que um erro de código.

**1. O feminino (o mais grave).** O módulo só tinha a forma masculina:

```
pelas dois horas            ->  pelas duas horas
pelas vinte e dois horas    ->  pelas vinte e duas horas
dois folhas                 ->  duas folhas
vinte e um folhas           ->  vinte e uma folhas
duzentos folhas             ->  duzentas folhas
dois mil folhas             ->  duas mil folhas
```

«Hora» e «folha» são femininos. «Minuto» e «dia» são masculinos e ficam na forma
de `numero()` — «duas horas e dois minutos» está certo assim. A conversão é por
TERMOS completos e não por finais de palavra: «doze» acaba em «ze» e não se
toca, mas «cento e dois» tem de dar «cento e duas».

**2. «aos um dia do mês de março».** Em todos os dias 1 de todos os meses. A
preposição passa para dentro do módulo, como já estava na hora:

```
ext.aos("2026-03-01")  ->  ao primeiro dia do mês de março de 2026
ext.aos("2026-03-29")  ->  aos vinte e nove dias do mês de março de 2026
```

E o `ext.data()` fica com a forma de CITAR — «com data de vinte e nove de junho
de 2026» — que é outra coisa e lê-se melhor.

**3. O rodapé passava por cima do número de folha.** Medido com uma morada
realista: 484,7 pt de texto para 426,1 pt de espaço. Quem configura a morada não
tem como adivinhar o limite, por isso o limite passa a tratar de si: o texto
quebra à largura disponível, até duas linhas, e encolhe a letra se nem assim
couber.

**4. «...deste tipo de documento..»** Os avisos do `prazos.py` já acabam em
ponto final, e a ressalva juntava outro.

**5. O meu próprio teste da sobreposição tinha um buraco.** Agrupava as palavras
pelo par (bloco, linha) que o PyMuPDF atribui — e como cada palavra é inserida à
parte, nada garante que duas vizinhas caiam no mesmo bloco. Deixava passar
precisamente a sobreposição ENTRE blocos, que é o caso que ele existe para
apanhar. Passa a agrupar pela altura. Verificado: neste documento nenhuma linha
atravessa blocos, pelo que o buraco não chegou a morder — mas estava lá.

Os casos destas cinco correções levam a suite a **561**. Dezanove novos nesta
ronda, e vinte e dois dos existentes falhavam contra o código da PR antes dela —
as formas femininas, a fórmula de datar e a hora, todos verificados com
`git stash`.

### Segunda ronda da revisão: mais dois

**A primeira linha de um parágrafo é mais estreita do que as outras**, e o
`_quebrar_em_palavras` partia sempre pela largura da caixa. Medido: uma palavra
de 90 letras mede 439,6 pt — cabe na caixa de 451 e não cabe nos 423 que sobram
depois do recuo, ficava inteira e transbordava 16,6 pt.

Com uma ressalva honesta: **hoje não há caminho até lá a partir do `gerar()`.**
Os parágrafos começam todos por «que,», «Mais», «Por», «Ressalva-se» — nenhum
começa por uma palavra longa. O teste exercita a função e não uma certidão
inteira, e diz isso no próprio ficheiro. Fica corrigido porque o primeiro
parágrafo que venha a começar por um resumo ou um nome de ficheiro abre a porta.

**As ressalvas eram de dois tipos tratados como um.** As do `prazos.py` são
frases COMPLETAS, e às vezes duas:

```
A afixação termina a 2026-10-30, depois do limite de 2026-10-11 — 10 dias
após a data do documento. Os dias fora da janela não contam para o mínimo.
```

Metidas no molde «Ressalva-se que » com a inicial em minúscula, davam
«Ressalva-se que a afixação termina ... Os dias fora ...», com o ponto a dobrar
pelo meio. Passam a citar-se **tal e qual**, que é o que se faz a um texto de
outra autoria: «Ressalva-se o seguinte: A afixação dura dois dias, abaixo do
mínimo...». As minhas, que são meias-frases feitas à medida, continuam com o
«que».

### Terceira ronda: o rodapé cortava em silêncio

Três apontamentos da revisão automática da PR, os três verificados antes de se
lhes tocar.

**O rodapé deitava fora o que não coubesse em duas linhas.** Duas é o que cabe
a 7 pt — e a letra encolhe até 5 pt, onde cabem três. A terceira linha
desaparecia sem uma palavra. Medido com um rodapé de 547 caracteres (morada,
sítio, correio, telefone, fax, NIF, horário e serviços descentralizados, que é
o que um município põe no rodapé dos seus editais):

```
antes:  3 linhas a 5 pt, a terceira deitada fora -> «Serviços descentralizados:
        Loja do Munícipe de Leomil...» nunca chegava ao papel
agora:  as três saem inteiras
```

O número de linhas deixa de ser um valor escrito à mão e sai da **geometria da
faixa**: a última linha assenta `RODAPE_DESCIDA` abaixo da margem do corpo, a
régua fica `RODAPE_ACIMA_DA_REGUA` acima da primeira, e a régua não pode subir
acima da margem sob pena de invadir o texto. Dá duas a 7 pt e três a 5 pt, que
é o que lá cabe e não o que alguém contou de cabeça.

E quando nem três chegam, **corta mas diz**: fica um aviso no registo técnico
com o que ficou de fora. Quem configurou a morada não vê a certidão a ser
gerada; o que lhe resta é o registo contar-lhe.

**O meu teste do rodapé olhava só para o span mais à direita**, e por isso teria
passado igualmente se o rodapé tivesse desaparecido por completo — que é a outra
maneira de não transbordar. Passa a exigir também que a morada, o sítio e o
telefone configurados apareçam no texto extraído do PDF.

**A docstring citava um aviso que a certidão nunca imprime.** O «Sem data de
retirada: ...» é de grau `informacao`, e a certidão só cita os de grau `aviso` —
filtro que já lá estava e que está certo: um edital ainda afixado não tem data
de retirada, e isso é o seu estado normal, não uma falta. O exemplo passa a ser
o aviso da janela legal, que tem mesmo duas frases e chega mesmo ao papel.

**A contagem de testes da entrada 0.23.0** tinha ficado com os números desta
PR. Volta a dizer o que a 0.23.0 entregou — 542 no total, 52 novos — e os desta
ficam na 0.23.1, que é onde pertencem.
