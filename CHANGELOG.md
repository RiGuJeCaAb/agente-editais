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
