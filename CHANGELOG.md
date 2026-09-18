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
