# Agente de Editais — Expositor CMMB

Automatiza a publicação dos editais no ecrã do expositor (Smart TV):
lê documentos de uma pasta, extrai metadados, converte-os para PNG tratado
(fundo verde metálico CMMB + folha a pairar + logótipo dourado gravado),
numera-os com grupo data/hora e gera uma **página web auto-atualizável** que a
TV abre num URL — mais um ZIP de arquivo.

---

## 1. O que faz, por passos
1. **Lê** a pasta `entrada/` (PDF, imagens, Word/.docx/.odt/.rtf) — **todas as páginas**.
2. **Extrai** assunto, número e data de publicação do texto do documento.
3. **Agrupa** folhas do mesmo documento **e** documentos com o mesmo assunto, e
   distribui-as por **ecrãs de até 3 folhas** (todas ao mesmo tamanho), aproveitando o 16:9.
4. **Trata** visualmente e **converte** para PNG 16:9 (3840×2160).
5. **Numera**: `AAAAMMDDHHMM_nn_assunto_p1de2_16x9_3d_CLD.png`.
6. **Datas de saída**: ficheiro de texto simples `retiradas.txt` (ver secção 5).
7. **Publica** `saida/index.html` (a página da TV, ecrã inteiro, 30 s por ecrã) + um ZIP
   (mantém só as **3 cópias mais recentes**).
8. Editais cuja data de saída já passou são **escondidos automaticamente** da TV.

---

## 2. Instalação

Requer **Python 3.10+**. Dependências:

```bash
pip install pymupdf pillow scipy numpy
```

Para documentos **Word** (.docx/.odt/.rtf) é preciso **LibreOffice** (conversão fiel):

- Ubuntu/Debian: `sudo apt install libreoffice`
- Windows: instalar o LibreOffice e garantir que `soffice.exe` está no PATH.

(PDF e imagens não precisam de LibreOffice.)

Os ficheiros do logótipo (`assets/sym_ok.png`, `assets/txt_ok.png`) já vão incluídos.

---

## 3. Utilização

```bash
# processar uma vez tudo o que estiver em entrada/ e gerar página + zip
python agente.py --once

# vigiar a pasta em contínuo (processa ficheiros novos automaticamente)
python agente.py --watch

# só reconstruir a página/zip depois de editares datas de retirada no JSON
python agente.py --rebuild-web
```

**Fluxo diário típico:**
1. Atiras os PDFs novos para `entrada/`.
2. O agente (em `--watch`, ou agendado) processa-os.
3. Abres `editais.json` e preenches a `data_retirada` de cada um (campo manual).
4. O agente reconstrói a página; a TV mostra os ativos e esconde os expirados.

### O ficheiro `retiradas.txt` (datas de saída — modo simples)

Já não precisa de mexer em JSON. Há um ficheiro de texto, `retiradas.txt`, que o
agente vai preenchendo sozinho com uma linha por edital. Você só escreve a **data
de saída** à frente do `=`:

```
# DELIBERAÇÕES PROFERIDAS PELA ASSEMBLEIA MUNICIPAL COM EFICÁCIA EXTERNA  (publicado 2026-06-29)
2026-0017 = 2026-07-29
```

Regras simples:
- Data no formato `AAAA-MM-DD` (ex.: `2026-07-29`) ou `DD/MM/AAAA`.
- **Em branco** = fica no ecrã indefinidamente.
- A partir da data escrita, o edital **sai do ecrã** (não é apagado do arquivo).
- A chave à esquerda pode ser o **número** do edital ou parte do **assunto**.

Depois de gravar, peça a reconstrução da página:

```bash
python agente.py --rebuild-web
```

(No modo `--watch` isto acontece sozinho no ciclo seguinte.)

---

## 4. Configuração

Opcional: cria um `config.json` ao lado do `agente.py` para alterar defaults:

```json
{
  "segundos_por_ecra": 30,
  "manter_zips": 3,
  "intervalo_watch": 30,
  "titulo_tv": "Editais · Câmara Municipal de Moimenta da Beira"
}
```

- `segundos_por_ecra` — tempo de cada ecrã na TV (predefinição 30 s).
- `manter_zips` — quantas cópias ZIP guardar na saída (predefinição 3; as antigas
  são apagadas automaticamente).
- `intervalo_watch` — segundos entre varrimentos no modo `--watch`.

### A televisão arranca em ecrã inteiro

A página da TV pede o **ecrã inteiro** automaticamente ao abrir. Alguns browsers de
Smart TV, por segurança, só entram em ecrã inteiro após **um toque** — por isso a
página mostra um ecrã de arranque com o botão **▶ Iniciar**. Um único toque no
comando/ecrã e fica em ecrã inteiro, a rodar de 30 em 30 segundos. Se o browser
permitir, nem o toque é preciso.

Para um arranque 100 % automático sem qualquer toque, configure a app de
**modo quiosque** da TV (ou um mini-player como um Raspberry Pi com o Chromium em
`--kiosk --start-fullscreen`) a abrir o URL — aí o ecrã de arranque é dispensável.

---

## 5. Pôr na televisão — e a questão da VLAN

A TV é uma **Smart TV com browser**, por isso o conteúdo chega-lhe por **URL**,
não por pasta partilhada nem pen. Isto separa dois problemas que convém **não**
misturar:

### 5.1 Ponto de publicação (de ONDE a TV lê)

A pasta `saida/` é um site estático. Serve-a por HTTP a partir da máquina onde
corre o agente. Opções, da mais simples à mais robusta:

- **Teste rápido** (mesma máquina):
  ```bash
  cd saida && python -m http.server 8080
  ```
  TV aponta para `http://IP-DA-MAQUINA:8080/`.

- **Produção** (recomendado): servir `saida/` com **nginx** ou **IIS** como site
  estático, em HTTP(S) na porta 80/443. A página já se auto-recarrega de 5 em 5
  minutos para apanhar editais novos — não é preciso tocar na TV.

A TV fica com um único URL fixo na app de browser/kiosk. Nunca mais lhe mexes.

### 5.2 Segmentação de rede (ONDE a TV vive) — a VLAN

Aqui está o ponto importante, e onde o pedido inicial estava trocado: **uma VLAN
não serve ficheiros**. Uma VLAN é segmentação de camada 2 — separa domínios de
broadcast e permite aplicar políticas. A TV não "lê uma VLAN"; lê o URL acima.

Dito isto, **faz todo o sentido** pôr o expositor numa VLAN dedicada de
*digital signage*, mas por razões de **segurança e gestão**, não de "atualização":

- **Isolamento**: a TV e o servidor de signage ficam numa VLAN própria
  (ex. `VLAN 50 – SIGNAGE`), separada da rede administrativa. Se a TV for
  comprometida (são aparelhos com firmware fraco), não alcança a rede de gestão.
- **Regras de firewall entre VLANs**: permitir **apenas** o necessário —
  da VLAN_SIGNAGE para o servidor web, na porta 80/443, e bloquear o resto.
  Isto é exatamente o tipo de minimização de superfície que a **NIS2 / DL 125/2025**
  espera de um operador de serviços essenciais.
- **Sem acesso à Internet** para a TV, se possível (ou só o estritamente
  necessário para updates de firmware), reduzindo risco.
- **DHCP/reserva** na VLAN para a TV ter sempre o mesmo IP, e o servidor um IP
  fixo, para o URL nunca mudar.

Esboço mínimo (adapta ao teu equipamento — pelo histórico, ambiente UniFi):

```
VLAN 50  "SIGNAGE"   10.50.0.0/24
  - Servidor web (agente)   10.50.0.10   (fixo)
  - Smart TV expositor      10.50.0.20   (reserva DHCP)

Firewall (inter-VLAN):
  PERMITIR  SIGNAGE -> 10.50.0.10 : 80,443    (TV lê a página)
  PERMITIR  ADMIN   -> 10.50.0.10 : 22/3389   (gestão do servidor)
  NEGAR     SIGNAGE -> ADMIN  (qualquer)
  NEGAR     SIGNAGE -> Internet (exceto o que for mesmo preciso)
```

Resumo da decisão: **a atualização do conteúdo resolve-se com a página
auto-atualizável + servidor web; a VLAN resolve o isolamento.** São camadas
independentes — e tê-las separadas é o desenho correto.

---

## 6. Agendamento (correr sozinho)

- **Linux** (cron, a cada 5 min):
  ```
  */5 * * * * cd /caminho/agente_editais && /usr/bin/python3 agente.py --once >> agente.log 2>&1
  ```
  ou correr `--watch` como serviço `systemd`.

- **Windows** (Task Scheduler): tarefa que corre `python agente.py --once`
  ao arranque e/ou a cada X minutos. Em alternativa, `--watch` como serviço
  (ex. via NSSM).

---

## 7. Estrutura

```
agente_editais/
├── agente.py            # orquestrador (CLI)
├── config.json          # (opcional) overrides
├── editais.json         # metadados + data_retirada MANUAL
├── estado.json          # controlo do que já foi processado
├── assets/              # logótipo (sym_ok.png, txt_ok.png)
├── registo_entrada.json # registo de editais + histórico (gravação atómica)
├── registo_auditoria.jsonl # trilho de auditoria, apenas-acrescento
├── entrada/             # <- pões aqui os documentos
├── saida/               # -> index.html + slides.json (TV) + PNGs + ZIP
├── previas/             # pré-visualizações leves para o painel
├── fundos/              # cache dos fundos metálicos (gerada sozinha)
├── trabalho/            # temporários (conversão Word)
├── tests/               # suite de testes (pytest)
└── lib/
    ├── armazenamento.py # escrita durável e jornal de auditoria
    ├── documentos.py    # conversão + extração de metadados
    ├── painel.py        # servidor do painel + API
    ├── registo.py       # máquina de estados do fluxo
    └── tratamento.py    # tratamento visual (fundo, folha, logo)
```

### Desenvolvimento

```bash
pip install -e ".[dev]"
pytest          # 109 testes: máquina de estados, durabilidade, segurança, contraste
ruff check .    # análise estática
```

Os testes correm sem LibreOffice e sem Tesseract de propósito: ambos são
opcionais em execução, e a suite tem de provar que o agente funciona sem eles.

### A pasta `fundos/`

O tratamento visual desenha o fundo metálico uma vez por variante (oito ao todo,
~70 MB) e reutiliza-as. É gerada sozinha e pode ser apagada à vontade — volta a
nascer. O painel prepara-as em segundo plano ao arrancar, para a primeira
publicação do dia não esperar por elas.

---

## 8. Notas e limites honestos

- **Assunto / datas**: a extração é por heurística calibrada para os editais da
  CMMB (linha de título em maiúsculas; `Número:` e `Data:` no rodapé lateral).
  Para documentos com layout muito diferente, confirma o `assunto` no JSON.
- **Imagens sem texto** (cartazes): não há texto para ler, por isso o assunto
  vem do nome do ficheiro — preenche no JSON se quiseres outro.
- **Data de retirada**: é mesmo manual, por opção. Se um dia quiseres
  "30 dias após publicação" automático, é uma linha a mudar — diz.
- **Word**: depende do LibreOffice. Sem ele, PDFs e imagens continuam a funcionar.
```

---

## 10. Painel de gestão (validação humana no browser) — NOVO

O agente deixou de publicar às cegas. Passou a haver um **registo de entrada**
com quatro estados, gerido num painel web local, onde nada vai para o ecrã sem
uma pessoa validar.

### Fluxo dos quatro estados

    Rascunho  →  Validado  →  Publicado  →  Retirado
    (lido)       (aprovado)   (no ecrã)     (arquivado)

- **Rascunho**: o agente leu o documento e propôs assunto, número e datas, com um
  grau de **confiança**. Campos pouco fiáveis são assinalados para confirmação.
- **Validado**: um utilizador reviu/corrigiu e aprovou. A data de publicação é
  obrigatória para validar.
- **Publicado**: está no expositor. Só neste estado o edital vai à TV.
- **Retirado**: saiu do ecrã (por data de retirada ou à mão). Fica no arquivo.

Cada mudança fica no **histórico de auditoria** (quem, quando, de→para).

### Arrancar o painel

1. Defina uma senha de acesso num `config.json` (veja `config.exemplo.json`):

   ```json
   { "painel_senha": "a-sua-senha", "painel_porta": 8770 }
   ```

2. Arranque:

   ```bash
   python agente.py --painel
   ```

3. Abra no browser: `http://127.0.0.1:8770/`. Ao entrar, o browser pede
   utilizador e senha (Basic Auth). **O utilizador que escrever fica no registo
   de auditoria** — use o seu nome (ex.: `ana.abreu`). A senha é a do config.

O agente fica a vigiar a pasta de entrada: documentos novos aparecem como
rascunho no painel, prontos a validar.

### Autenticação — nota honesta

Esta é uma proteção **simples e honesta**: uma senha partilhada + registo de quem
fez cada ação. **Não** é autenticação empresarial. Para "vários utilizadores com
contas e permissões" a sério, o passo certo é ligar ao **Active Directory / Entra
ID** da CMMB — o código já tem o gancho preparado (`_verificar_sessao` em
`lib/painel.py`). Fazer SSO/LDAP exige integração testada com a vossa
infraestrutura, e é exatamente o tipo de autenticação centralizada que a NIS2 /
DL 125/2025 favorece face a contas dispersas por aplicações.

### Expor a outros postos (rede interna)

Por omissão o painel só escuta em `127.0.0.1` (a própria máquina). Para o abrir a
outros postos, mude `"painel_host": "0.0.0.0"` no config — **preferencialmente
dentro da VLAN de gestão**, nunca exposto à Internet.

### Os dois modos, lado a lado

| Modo | Comando | Publica sozinho? |
|------|---------|------------------|
| Automático (antigo) | `python agente.py --watch` | Sim — direto ao ecrã |
| Com validação (novo) | `python agente.py --painel` | Não — só após aprovação |

Para uso municipal corrente, recomenda-se o **modo painel**.

---

## 11. Painel renovado — navegação por secções (UI/UX)

O painel passou a organizar-se por **secções** na barra lateral, em vez de mostrar
tudo ao mesmo tempo. Cada secção mostra só o que interessa naquele momento:

- **No ecrã** (onde abre por omissão): os editais publicados no expositor agora.
- **Por validar**: a caixa de entrada de trabalho, em vista **foco** — um documento
  de cada vez, espaçoso, com pré-visualização e campos lado a lado, e navegação
  seguinte/anterior (setas do teclado também funcionam). O número dourado ao lado
  assinala quantos esperam validação.
- **Arquivo**: os editais retirados, com **pesquisa** por assunto ou número.
- **Vista geral**: as quatro colunas (kanban), para quem quer o panorama completo.

Detalhes de usabilidade: cada estado tem o seu **carimbo** (Rascunho, Validado,
Publicado, Retirado); os campos com leitura automática pouco fiável ficam
**assinalados a confirmar**; a atualização automática (20 s) **não apaga** o que
estiver a ser escrito num formulário aberto; e o painel **arranca de imediato** —
a composição das imagens 4K acontece em segundo plano, sem prender a interface.

---

## 12. Página da TV — carrossel infinito, atualização ao vivo e fundo animado

A página do expositor foi reformulada em três pontos.

### Carrossel verdadeiramente infinito

Roda para sempre, até ordem em contrário. Foi **removido** o `location.reload()`
periódico que existia antes — era ele que, com poucos editais, dava a ilusão de
"volta ao início e pára", além de piscar e poder perder o ecrã inteiro.

### Editais novos entram SEM interromper o ciclo

Mudança de arquitetura: os slides deixaram de estar embebidos no `index.html`.
Passam a viver num ficheiro **`slides.json`** que a página vai buscar de 15 em 15
segundos. Quando publica ou retira um edital no painel, só o `slides.json` muda —
a página deteta a nova versão e **reconcilia o carrossel ao vivo** (adiciona os
novos no fim da fila, remove os que saíram) sem recarregar nem cortar a rotação
que está a decorrer. O `index.html` é escrito uma vez; a fonte viva é o JSON.

Ficheiros gerados em `saida/`: `index.html` (uma vez), `slides.json` (muda a cada
publicação), os PNG e o ZIP de arquivo.

### Fundo com veias douradas ondulantes

Por baixo dos editais corre agora um `<canvas>` animado com "veias" douradas que
ondulam sobre o gradiente verde — a mesma linguagem visual das imagens tratadas,
agora viva. É subtil de propósito, para não competir com o conteúdo.

**Aviso honesto — isto NÃO resolve o screensaver.** Foi confirmado (fórum de
developers do webOS, e testes anteriores nossos) que imagem em movimento — mesmo
vídeo real — não impede o screensaver desta TV. O fundo animado é **design**, não
função. A solução real do screensaver é a seguinte.

### Anti-screensaver do webOS (a tentativa a sério)

A página tenta falar diretamente com o gestor de energia da TV via a API Luna
não-documentada `registerScreenSaverRequest`, respondendo `ack:false` quando o
sistema avisa que vai dormir. É o mesmo mecanismo (wake lock de sistema) que a app
do YouTube usa — não é o vídeo que mantém o ecrã aceso, é este pedido ao SO.

**Limite conhecido, sem rodeios:** a API `WebOSServiceBridge` existe em *apps*
webOS empacotadas; a partir do **browser** da TV pode não estar acessível. Só se
confirma **testando na TV real**. Se não funcionar do browser, mantém-se a
recomendação de longo prazo: um **mini-PC ligado por HDMI** (~60€), que elimina de
vez a dependência do browser da TV e dá controlo total sobre o ecrã.

Para testar na TV: abrir a página, deixar 3-5 min sem tocar, e ver se o
screensaver aparece. Se aparecer, é o momento de decidir o mini-PC.

---

## 13. Correções e melhorias (arquivo, corte de margens, atalhos)

### Corte de margens em printscreens — CORRIGIDO

A função de encaixe (`_fit_sheet` em `tratamento.py`) escalava sempre pela altura
e cortava as laterais quando a imagem ficava mais larga que a caixa. Para folhas
A4 (verticais) era inofensivo, mas um **printscreen** (horizontal, 16:9) tinha as
margens esquerda e direita amputadas — perdia-se texto.

Passou a usar a estratégia "caber inteiro" (*fit*): a imagem é escalada pelo lado
que garante que tudo cabe, e o espaço restante fica branco. Um A4 encaixa como
antes; um printscreen aparece como faixa centrada, **sem perder um pixel**.

### Pasta de saída mais leve — arquivo automático dos retirados

Quando um edital é **retirado do ecrã**, o seu PNG deixa de ocupar a pasta
`saida/` como ficheiro solto: é movido para um ZIP de arquivo permanente em
`arquivo/arquivo_editais.zip`. Isto liberta espaço em disco (as imagens 4K são
pesadas) mantendo o histórico.

Se um edital retirado for **reposto no ecrã**, o PNG é recuperado do ZIP — sem
recompor a imagem do zero. O ZIP é a rede de segurança: retirar poupa disco e
repor continua rápido. As pré-visualizações no painel (secção Arquivo) são
servidas diretamente de dentro do ZIP, sem extrair para disco.

### Melhorias de UX no painel

- **Confirmação antes de retirar**: retirar do ecrã (ação destrutiva) pede
  confirmação, explicando que o edital fica no arquivo e pode ser reposto.
- **Atalhos de teclado** na validação: `←`/`→` navegam entre documentos, `V`
  valida, `P` publica. Ignorados quando se está a escrever num campo. Há uma dica
  visível na barra da secção.
- **Arquivo com imagens**: os editais retirados mostram a pré-visualização mesmo
  com o PNG já fora da pasta (vem do ZIP).

---

## 14. Pré-visualização do documento no painel (com ampliação)

Antes, na validação, o documento só aparecia **depois** de publicado — o que
obrigava a preencher os campos (assunto, número, datas) às cegas. Corrigido.

Agora, quando um documento chega e vira rascunho, o agente gera logo uma
**pré-visualização leve** (a página do PDF/documento rasterizada, sem o tratamento
verde/4K — rápida de gerar, guardada em `previas/` como JPEG). Essa imagem aparece
na vista de validação, ao lado dos campos, para se confirmar os dados com o
documento à frente.

Clicar na pré-visualização **amplia-a** (lightbox) para ler o texto todo. Fecha no
✕, clicando no fundo, ou com a tecla Esc.

---

## 15. OCR — ler tema e data de imagens e digitalizações

Antes, quando um documento era uma **imagem** (printscreen, digitalização), não
havia texto pesquisável: o assunto acabava por vir do nome do ficheiro e a data
ficava por preencher. Corrigido com OCR (Reconhecimento Ótico de Caracteres).

**Como funciona (duas camadas):**
- **PDFs com texto** → extração direta, rápida e exata (o caminho normal, a maioria
  dos casos). NÃO usa OCR.
- **Imagens e PDFs sem texto** → o OCR (Tesseract) "lê" o texto a partir dos
  píxeis. Só é acionado quando não há texto direto, para não abrandar o fluxo
  normal.

Assim, o **tema é sempre retirado do conteúdo do documento** (ponto 5), e a **data
é lida e registada** quando existe no documento, pedindo confirmação apenas quando
não a consegue ler (ponto 4).

Texto vindo de OCR recebe um **teto de confiança** (0.75): fica assinalado para o
funcionário confirmar com atenção, mas sem ser marcado como erro se a leitura foi
boa. O log mostra `[via OCR]` quando um documento passou por reconhecimento.

**Requisito no servidor:** o Tesseract tem de estar instalado.
```bash
# Ubuntu/Debian:
sudo apt install tesseract-ocr tesseract-ocr-por
# Python:
pip install pytesseract
```
Se o Tesseract não estiver instalado, o agente continua a funcionar — apenas não
lê texto de imagens (como antes), sem rebentar.
