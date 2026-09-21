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
