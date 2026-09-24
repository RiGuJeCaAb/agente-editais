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
   distribui-as por ecrãs **conforme a orientação**: folhas verticais juntam-se
   até 3 por ecrã, todas ao mesmo tamanho; um documento **horizontal**
   (printscreen, A4 deitado, mapa) leva um ecrã só para si, onde ocupa ~60 % da
   área em vez dos 10 % que lhe sobravam encaixado na caixa vertical.
4. **Trata** visualmente e **converte** para PNG 16:9 (3840×2160).
5. **Numera**: `AAAAMMDDHHMM_nn_assunto_p1de2_16x9_3d_CLD.png`.
6. **Espera por uma pessoa.** Nada vai ao ecrã sozinho: cada documento fica como
   rascunho no painel até alguém o validar e publicar. É essa pessoa que a
   certidão de afixação nomeia.
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

Há um só modo de serviço — o painel:

```bash
# criar a primeira conta (pede a senha sem eco); --administrador dá-lhe
# também a gestão de contas.
# Precisa de um terminal: a senha escreve-se ao teclado e não passa por
# argumento nem por canalização, para não ficar no histórico da consola.
python agente.py --criar-utilizador ana.silva --administrador

# arrancar o painel de gestão
python agente.py --painel

# ver as contas que existem
python agente.py --utilizadores

# conferir o registo contra o disco (relata; não apaga nada)
python agente.py --conferir

# reconstruir as pastas publicados/ e retirados/ para consulta no Explorador
python agente.py --exportar-pastas
```

**Fluxo diário típico:**
1. Atiras os PDFs novos para `entrada/`. Assim que o agente os recebe, passam
   para `entrada/tratados/` — a pasta de entrada fica só com o que ainda não foi
   visto, que é como se responde a «o que chegou de novo?» sem abrir nada.
2. Abres o painel, secção **Por validar**. Cada documento aparece um de cada vez,
   com a pré-visualização ao lado e os metadados extraídos já preenchidos.
3. Confirmas ou corriges o assunto, o número e o **tipo de documento** — é o tipo
   que diz qual o prazo de afixação que a lei manda cumprir.
4. **Publicas.** A partir daí o edital está no ecrã e há uma certidão que diz
   quem o afixou, quando, e com que resumo SHA-256 do original.
5. Chegada a hora, **retiras** — e sai outra certidão, a da desafixação.

> **Os modos `--once`, `--watch` e `--rebuild-web` saíram na versão 0.14.**
> Publicavam sem ninguém ver. Desde a 0.12 a aplicação emite uma certidão que
> diz *quem* afixou cada edital, e um caminho automático não tem essa resposta.
> Quem tenha dados do modelo antigo não os perde: ver **secção 3.1**.

### 3.1 Migração do modelo antigo

Se a pasta ainda tiver um `editais.json`, o agente migra-o sozinho ao arrancar o
painel. Não é preciso fazer nada, nem correr comando nenhum.

O modelo antigo guardava um registo por **ecrã** — um edital de cinco folhas
aparecia lá três vezes. A migração reagrupa-os no edital a que pertencem, lê as
datas do `retiradas.txt`, recupera o resumo SHA-256 do original quando o ficheiro
ainda existe, e reconstrói o estado de cada um (publicado, ou retirado se a data
já passou).

O que o modelo antigo não tinha, assume-se em vez de se inventar:

| | o que fica | porquê |
|---|---|---|
| quem afixou | `migracao` | não havia contas; a certidão di-lo em vez de inventar um nome |
| hora da afixação | o `processado_em` do primeiro ecrã | é quando a imagem foi composta — o mais próximo que os dados permitem |
| tipo de documento | o de omissão | o prazo não é verificado até alguém o escolher no painel |
| resumo do original | o SHA-256, se o ficheiro ainda estiver em `entrada/`; senão, vazio | o modelo antigo só guardava o SHA-1. Havendo ficheiro, calcula-se e arquiva-se; não havendo, a certidão cala-se em vez de citar o que não conferiu |

Um edital antigo **sem data de publicação** não vai ao ecrã: fica em **Por
validar**, à espera de quem saiba a data — que é obrigatória porque o rodapé da
TV a mostra. O arranque diz quantos ficaram assim, para não se descobrir pela
ausência deles no expositor.

Os ficheiros de origem são **renomeados** para `.migrado`, não apagados. Se a
migração tiver lido alguma coisa ao contrário, os dados continuam lá para se
conferir — e o painel mostra os editais migrados como quaisquer outros.

---

## 3.2 Conferir e exportar

### `--conferir` — o que está desalinhado

O registo manda, mas o disco tem os ficheiros, e as duas coisas separam-se: uma
pasta que alguém limpou à mão, uma migração que trouxe editais cujos originais já
não existem, um PNG que sobreviveu ao registo que o gerou.

```bash
python agente.py --conferir
```

Relata quatro coisas:

| | o que quer dizer |
|---|---|
| **Sem original** | o documento não está no arquivo nem nas pastas de entrada. Estes editais não se conseguem compor, e por isso não vão ao ecrã |
| **Sem saída** | rascunhos sem data **e** sem original. Não se validam nem se publicam: ficam na fila para sempre. É a forma exata dos que a migração deixou |
| **Ecrãs / pré-visualizações órfãs** | ficheiros em `saida/` e `previas/` que nenhum registo reclama |
| **Originais órfãos** | documentos arquivados que nenhum registo aponta |

**Não apaga, não move, não corrige** — é um relatório. As decisões sobre um
edital são de quem responde por ele. Devolve `1` quando encontra alguma coisa,
o que dá para agendar e só chamar a atenção quando houver.

### `--exportar-pastas` — a vista no Explorador

```bash
python agente.py --exportar-pastas
```

Constrói `exportacao/publicados/` e `exportacao/retirados/` com o documento
original de cada edital, nomeado `AAAA-MM-DD_numero_assunto.pdf` — a data à
cabeça para o gestor de ficheiros os ordenar sozinho, que é como alguém procura
um edital: «foi aí por junho». Junta um `INDICE.csv` (abre no Excel) com tudo o
que a pasta não sabe dizer, incluindo **quem afixou e quando**.

> **Estas pastas são uma vista, não a verdade.** Mover um ficheiro de lá não
> retira nem publica nada — o estado muda-se no painel, onde fica documentado
> quem o fez. Se as pastas e o registo divergirem, corre-se o comando outra vez
> e fica resolvido.
>
> Houve a hipótese de fazer ao contrário: mover o ficheiro de pasta a cada
> mudança de estado, e a pasta ser o estado. Não se fez, porque passaria a haver
> duas afirmações sobre o mesmo edital — e duas afirmações divergem. A pasta não
> sabe dizer quem publicou; o registo sabe.

Cada subpasta leva um `_GERADO_PELO_AGENTE.txt` a explicar isto. É também a
marca de segurança: a exportação **recusa-se a limpar uma pasta que não tenha a
marca**, porque apaga ficheiros e o caminho vem do `config.json`.

---

## 4. Configuração

Opcional: cria um `config.json` ao lado do `agente.py` para alterar defaults:

```json
{
  "segundos_por_ecra": 30,
  "manter_zips": 3,
  "titulo_tv": "Editais · Câmara Municipal de Moimenta da Beira"
}
```

- `segundos_por_ecra` — tempo de cada ecrã na TV (predefinição 30 s).
- `manter_zips` — quantas cópias ZIP guardar na saída (predefinição 3; as antigas
  são apagadas automaticamente).

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

## 6. Correr como serviço

Não há nada a agendar: o que se põe a correr sozinho é o **painel**, e é ele que
vigia a pasta de entrada. O processamento acontece quando chega um ficheiro; a
publicação, quando uma pessoa a autoriza.

- **Linux** (`systemd`): a unidade está feita em `servico/`, com as instruções.
  ```bash
  sudo cp servico/agente-editais.service /etc/systemd/system/
  sudo systemctl enable --now agente-editais
  ```
- **Windows**: o painel como serviço via NSSM, apontado a
  `python agente.py --painel`.

O endpoint `/saude` responde sem sessão e serve para o supervisor saber se o
painel está de pé.

---

## 7. Estrutura

```
agente_editais/
├── agente.py            # orquestrador (CLI)
├── config.json          # (opcional) overrides
├── assets/              # logótipo (sym_ok.png, txt_ok.png)
├── exportacao/          # pastas por estado — VISTA do registo, gerada a pedido
├── registo_entrada.json # registo de editais + histórico (gravação atómica)
├── registo_auditoria.jsonl # trilho de auditoria, apenas-acrescento
├── utilizadores.json    # contas do painel (senhas derivadas, nunca em claro)
├── originais/           # arquivo imutável dos documentos (endereçado por SHA-256)
├── diario/              # registo técnico, com rotação
├── servico/             # unidade systemd e instruções de serviço
├── entrada/             # <- pões aqui os documentos
├── saida/               # -> index.html + slides.json (TV) + PNGs + ZIP
├── previas/             # pré-visualizações leves para o painel
├── fundos/              # cache dos fundos metálicos (gerada sozinha)
├── trabalho/            # temporários (conversão Word)
├── tests/               # suite de testes (pytest)
└── lib/
    ├── armazenamento.py # escrita durável e jornal de auditoria
    ├── certidao.py      # certidão de afixação em PDF
    ├── diario.py        # registo técnico (níveis, rotação)
    ├── documentos.py    # conversão + extração de metadados
    ├── conferencia.py   # compara o registo com o disco (relata, não corrige)
    ├── progresso.py     # o que o agente está a fazer agora, para o painel mostrar
    ├── entrada.html     # página de início de sessão
    ├── exportacao.py    # pastas por estado, construídas a partir do registo
    ├── migracao.py      # traz o modelo antigo para o registo (código com prazo)
    ├── originais.py     # arquivo imutável dos documentos
    ├── painel.py        # servidor do painel + API
    ├── prazos.py        # tipos de documento e janelas legais
    ├── registo.py       # máquina de estados do fluxo
    ├── tratamento.py    # tratamento visual (fundo, folha, logo)
    └── utilizadores.py  # contas, senhas derivadas e sessões
```

### Desenvolvimento

```bash
pip install -e ".[dev]"
pytest          # 472 testes
ruff check .    # análise estática
mypy lib/ agente.py   # tipos: rigoroso nos módulos novos, tolerante nos antigos
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

1. Crie a primeira conta (a senha é pedida sem eco, não vai na linha de comandos):

   ```bash
   python agente.py --criar-utilizador ana.abreu --administrador
   ```

2. Arranque:

   ```bash
   python agente.py --painel
   ```

3. Abra no browser: `http://127.0.0.1:8770/`. Cada pessoa entra com a **sua**
   conta. É esse nome que fica no histórico de cada edital e na certidão de
   afixação — por isso não se partilham contas.

Para ver quem tem acesso: `python agente.py --utilizadores`.

O agente fica a vigiar a pasta de entrada: documentos novos aparecem como
rascunho no painel, prontos a validar.

### Autenticação

Contas individuais, com senha derivada por **scrypt** (biblioteca padrão do
Python — nenhuma dependência nova) e sessão por cookie `HttpOnly` +
`SameSite=Strict`, com validade contada desde o último uso. Dois papéis:
**operador** valida e publica; **administrador** gere também as contas.

A senha partilhada que existia até à versão 0.11 foi retirada. Não era uma
questão de higiene: o nome que ia para o trilho de auditoria era texto livre, e
uma certidão que nomeia quem afixou o edital não pode assentar nisso.

Há limite de tentativas por **endereço** e por **conta**. São defesas
diferentes: o primeiro trava quem varre senhas de um sítio, o segundo trava quem
varre a mesma conta a partir de vários.

**O que continua por fazer**, e é honesto dizê-lo: isto não é autenticação
centralizada. O passo seguinte é o **Active Directory / Entra ID** da CMMB, e o
gancho está em `Utilizadores.autenticar()` — trocar a verificação local por uma
consulta LDAP/OIDC não obriga a mexer em mais nada. É o tipo de autenticação que
o **Decreto-Lei n.º 125/2025** (NIS2), em vigor desde 3 de abril de 2026,
favorece face a contas dispersas por aplicações.

### Expor a outros postos (rede interna)

Por omissão o painel só escuta em `127.0.0.1` (a própria máquina). Para o abrir a
outros postos, muda `"painel_host": "0.0.0.0"` no config — **preferencialmente
dentro da VLAN de gestão**, nunca exposto à Internet.

### Já não há dois modos

Até à 0.13 havia um modo automático a viver ao lado do painel: `--watch` lia a
pasta e punha os editais no ecrã sem ninguém ver. Saiu na **0.14**, e vale a pena
dizer porquê, porque não foi arrumação.

Desde a 0.12 cada afixação e cada desafixação produzem uma certidão que nomeia
**quem** praticou o ato. Um caminho que publica sozinho não tem essa resposta.
Mantê-lo era garantir que mais cedo ou mais tarde alguém pediria a certidão de um
edital afixado por ninguém — e a única resposta honesta seria «o computador».

Publica-se pelo painel. Quem tenha editais do modelo antigo não os perde: a
migração corre sozinha, e está descrita na **secção 3.1**.

---

## 11. Painel renovado — navegação por secções (UI/UX)

O painel passou a organizar-se por **secções** na barra lateral, em vez de mostrar
tudo ao mesmo tempo. Cada secção mostra só o que interessa naquele momento:

- **No ecrã** (onde abre por omissão): os editais publicados no expositor agora.
- **Por validar**: a caixa de entrada de trabalho, em vista **foco** — um documento
  de cada vez, espaçoso, com o documento e os campos lado a lado. O número dourado
  ao lado assinala quantos esperam validação.
- **Arquivo**: os editais retirados, com **pesquisa** por assunto ou número.
- **Descartados**: os que foram postos de parte, com o motivo à vista. Nada foi
  apagado — qualquer um volta à fila com um clique. Também tem pesquisa.
- **Vista geral**: as cinco colunas (kanban), para quem quer o panorama completo.

### O documento todo, não só a primeira folha

Um documento com várias páginas mostra-se com um **visor**: as miniaturas de
todas as páginas por cima, o contador (`2 / 5`), setas, e o teclado. A lógica é
bidimensional e vale a pena guardá-la:

| tecla | faz |
|---|---|
| `←` `→` | muda de **documento** |
| `↑` `↓` | muda de **página** dentro do documento |
| `V` | valida |
| `P` | publica |

Clicar numa página abre-a em grande. O número de páginas aparece também em cada
ficha da lista, antes sequer de abrir.

> Até à 0.15 o painel mostrava **só a primeira página**, sem o dizer. Quem
> validava um edital de cinco folhas via uma, e assinava uma certidão a afirmar
> que o tinha afixado. Se vens de uma versão anterior, vale a pena reabrir o que
> publicaste e conferir o resto.

### Enquanto o agente trabalha

Compor os ecrãs 4K de um edital demora — cerca de **2,5 segundos por ecrã**, e um
documento de vinte páginas dá oito ecrãs. O painel mostra uma faixa a dizer em
que vai:

> A compor os ecrãs de «edital_grande.pdf» (3 de 8)

Enquanto há trabalho, o painel actualiza-se de 3 em 3 segundos; em repouso, de 20
em 20. Não é preciso carregar outra vez em «Publicar»: se a faixa está lá, está a
andar — e quando o trabalho acaba a faixa desaparece, que é como se sabe que
acabou.

**Documentos grandes.** Até à 0.17 a leitura carregava todas as páginas para
memória ao mesmo tempo — cerca de 18 MB por página, sem tecto, o que fazia um
documento de 50 páginas pedir 955 MB e um de 100 pedir 1,8 GB. Passou a ler uma
página de cada vez: **pico de 102 MB, seja o documento de 5 ou de 500 páginas**
— e metade disso são os módulos carregados, antes de se ler fosse o que fosse.

**Publicar deixou de compor imagens.** Até à 0.18, cada ecrã era uma imagem de
3840×2160 desenhada em Python e gravada em disco. Desde a 0.19 é a televisão que
compõe o ecrã, a partir das folhas e das coordenadas onde assentam. Publicar um
edital de 50 páginas passou de **117,76 s e 1,2 GB** para **5,20 s e 441 MB**, e
de 51,65 MB de ficheiros para 6,66 MB.

### A imagem que fica no arquivo

A imagem 4K não desapareceu: mudou de momento. Faz-se quando o edital é
**retirado**, e vai para o ZIP de arquivo permanente — é ela a prova do que
esteve afixado, e é exatamente o mesmo ficheiro que lá ia antes. O que mudou é
que já não se paga essa composição com alguém à espera de ver o edital no ecrã;
paga-se na arrumação, onde ninguém espera.

Enquanto o edital está afixado, a pasta de saída tem as suas folhas em JPEG e o
`slides.json` que diz onde assentam. O ZIP do expositor leva as duas coisas mais
o registo: com elas reconstrói-se o expositor noutra máquina, sem o agente.

### Descartar, que não é apagar

Um documento que não deve ir ao expositor — duplicado, engano, ou um registo
antigo sem original nem data — sai da fila por **Descartar**. Pede **motivo**,
que é obrigatório: guardar a linha e perder a razão seria guardar a parte que não
interessa. O registo fica em «Descartados», com quem, quando e porquê no jornal
de auditoria, e volta à fila quando se quiser.

**Um edital publicado não se descarta.** Sai do ecrã por «Retirar do ecrã», que é
o que carimba a desafixação e o que a certidão cita. O botão nem aparece nos
publicados, em vez de aparecer e dar erro.

Detalhes de usabilidade: cada estado tem o seu **carimbo** (Rascunho, Validado,
Publicado, Retirado, Descartado); os campos com leitura automática pouco fiável ficam
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

---

## 16. Certidão de afixação e prazos legais — NOVO

### O documento que prova a afixação

A aplicação passou a emitir a **certidão de afixação e desafixação** em PDF, a
partir da ficha de qualquer edital já afixado. É o documento que se junta a um
processo ou se mostra a quem audite, e diz:

- que documento foi afixado (tipo, número, assunto, entidade, resumo do original);
- **quando** foi afixado e **por quem**;
- quando foi desafixado e por quem, e quantos dias durou;
- a **base legal** aplicável, e uma observação se o prazo não tiver sido cumprido;
- em **anexo**, o registo de disponibilidade no expositor.

### Que instante conta como afixação

O instante **oficial** é o da publicação no painel — o momento em que uma pessoa
com competência para o fazer carregou em publicar.

A razão: a afixação é um ato administrativo, não um evento de infraestrutura. Se
o expositor estiver avariado, a deliberação foi afixada à mesma e o que falhou
foi o meio de a mostrar. Fazer depender a validade de um ato administrativo do
funcionamento de uma televisão seria trocar as voltas às duas coisas.

Dito isto, a outra pergunta também aparece — «e esteve mesmo lá?» — e por isso a
certidão leva em anexo o instante em que o edital entrou na rotação do expositor.
Instante oficial no corpo, confirmação material no anexo, distinguidos em vez de
misturados.

### Selo de conferência

Cada certidão leva um resumo criptográfico dos factos que afirma. **Não é
assinatura digital**, e a própria certidão o diz. O que permite é confirmar mais
tarde que um papel corresponde ao que o registo diz: recalcula-se o resumo a
partir do registo e compara-se.

### Prazos por tipo de documento

Cada edital tem um **tipo**, e cada tipo traz a sua janela de afixação. O
principal é a deliberação de órgão autárquico, regida pelo **artigo 56.º do
Anexo I da Lei n.º 75/2013**: afixada nos lugares de estilo durante **cinco dos
10 dias subsequentes** à deliberação.

A redação engana, e o sistema trata as duas partes em separado:

- o mínimo de afixação são **5 dias**, não 10;
- os **10 dias** são a janela, contada da deliberação, onde esses cinco têm de
  caber. Afixar ao oitavo dia e retirar ao décimo terceiro dá cinco dias de
  afixação e mesmo assim não cumpre.

O painel **propõe** a data de retirada e **avisa** quando o que está escrito fica
aquém — com a norma ao lado, para ser verificável em vez de ter de se acreditar.
O que não faz é impor: a data continua a ser do posto, que é quem sabe se aquele
documento é mesmo do tipo que diz.

Tipos com prazos próprios do município declaram-se em `config.json`, sem tocar
no código:

```json
{
  "tipos_de_documento": {
    "postura_municipal": {
      "rotulo": "Postura municipal",
      "dias_minimos": 15,
      "base_legal": "Regulamento municipal X, artigo 4.º"
    }
  }
}
```

---

## 17. Arquivo dos originais, registo técnico e serviço — NOVO

### Os originais deixam de depender da pasta de entrada

Cada documento é copiado, na ingestão, para `originais/`, num arquivo
endereçado pelo **conteúdo** (SHA-256). Antes, a composição relia o ficheiro de
`entrada/` — e quem limpasse essa pasta deixava os editais publicados sem forma
de serem recompostos, e sem o documento que a certidão afirma ter sido afixado.

Copia-se, não se move: a pasta de entrada continua a ser de quem a usa e pode ser
limpa a qualquer momento. Como o endereço é o conteúdo, o mesmo documento largado
duas vezes com nomes diferentes ocupa espaço uma vez, e um ficheiro adulterado
deixa de corresponder ao endereço por onde é procurado.

### Registo técnico

`diario/agente.log`, com níveis, rotação (10 ficheiros de 2 MB) e saída
simultânea para a consola. O ficheiro guarda mais do que a consola mostra — é no
dia do incidente que a diferença se paga.

### Correr como serviço

`servico/agente-editais.service` está pronto a instalar, com restrições de
superfície. Ver `servico/LEIAME.md`, que cobre também o Windows (NSSM).

### Saber se está vivo

```bash
curl -s http://127.0.0.1:8770/saude
```

Devolve `"ok": true` quando a vigia correu há pouco e há espaço em disco. É a
única rota sem sessão, e por isso só devolve números e instantes — nunca o
conteúdo de editais por validar.

---

## 18. Ecrãs conforme a orientação do documento — NOVO

Havia uma caixa-folha só, vertical, e tudo era encaixado nela. Para um edital em
A4 isso está certo — enche-a quase toda. Para um documento **horizontal** não
estava: sobrava-lhe uma faixa fina no meio de muito branco.

Medido num ecrã 4K:

| documento | antes | agora |
|---|---|---|
| A4 vertical | 24 % | 24 % (igual) |
| A4 deitado | 12 % | 48 % |
| printscreen 16:9 | 10 % | 60 % |
| panorama 21:9 | 7 % | 69 % |

Numa televisão vista a seis ou dez metros, 10 % da área é texto que não existe.

**A regra:** um documento mais largo do que alto vai sozinho para um ecrã, numa
caixa larga que herda as margens do trio de folhas verticais — para os dois
tipos de ecrã parecerem do mesmo sistema. A folha larga é do tamanho exato do
que leva dentro, e o verde do fundo aparece dos lados; preenchê-la a branco até
à caixa toda lia-se como defeito.

Um documento misto (um ofício com um mapa deitado no meio) fica com os verticais
agrupados e o horizontal isolado, na sua vez, sem perder a ordem.

**O que NÃO mudou:** a composição dos documentos verticais é idêntica ao píxel —
verificado contra a versão anterior, 100 % dos píxeis iguais em 1, 2 e 3 folhas.

---

## 19. Como se revê este código — NOVO

As regras de trabalho passaram a estar escritas num ficheiro, `AGENTS.md`, em vez
de dispersas por estas 800 linhas. A diferença não é de arrumação: é que um
revisor automático lê um e não lê as outras.

Até aqui, qualquer revisor que chegasse a uma PR deste repositório não tinha como
saber que se escreve em português europeu, que não entram emojis, que o
`CHANGELOG.md` cresce para baixo, que os testes correm de propósito sem
LibreOffice, ou que a classe de defeito que interessa mesmo é um edital que não
aparece na televisão. Revia contra o que conhecesse de outros projetos — e foi
mais ou menos isso que se viu acontecer.

Os ficheiros:

| ficheiro | quem o lê |
|---|---|
| `AGENTS.md` | as regras completas, para pessoas e para as ferramentas que o suportam |
| `.github/copilot-instructions.md` | o resumo, para a revisão do GitHub Copilot |
| `.github/workflows/revisao.yml` | a revisão automática, que começa por ler o `AGENTS.md` |

### A revisão automática

Corre em cada PR aberta e em cada push para ela. O primeiro que faz é ler o
`AGENTS.md`, e é contra essas regras que revê — não contra as convenções
genéricas que traria de outros projetos.

Corre com a conta Claude de quem mantém o projeto, não com uma chave de API. Para
a ligar:

```bash
claude setup-token   # localmente; precisa de subscrição Pro ou Max
```

e o valor que sair vai para `Settings > Secrets and variables > Actions`, com o
nome `CLAUDE_CODE_OAUTH_TOKEN`.

**Sem esse segredo o trabalho não falha, salta.** É de propósito: uma revisão que
põe o CI a vermelho em quem clona o repositório sem credencial é pior do que
revisão nenhuma. Quem clonar isto e não tiver token vê a `verificar` a correr
normalmente e a `revisao` a dizer, numa linha, o que falta.

Se o consumo da subscrição incomodar, a linha a mexer é o gatilho:
`types: [opened, synchronize]` passa a `types: [opened]` e revê-se uma vez por
PR em vez de a cada push.

**Um push durante uma revisão cancela a anterior.** Sem o grupo de concorrência,
uma sequência rápida de correções punha três revisões a correr ao mesmo tempo
sobre o mesmo ramo — todas a gastar subscrição e só a última a interessar.

**A revisão vive num só comentário, que se atualiza.** São precisos os dois
parâmetros, e o que faz o trabalho é o `track_progress`: com um `prompt`, a ação
corre em modo de automação e não cria comentário nenhum, e nesse modo o
`use_sticky_comment` não tem o que governar. Pela mesma razão, `gh pr comment`
não está na lista de ferramentas — se estivesse, a promessa de um só comentário
dependia de o modelo obedecer ao prompt em vez de ser estrutural.

**O checkout não deixa credenciais para trás** (`persist-credentials: false`).
O `actions/checkout@v6` guarda o token num ficheiro sob `$RUNNER_TEMP` e
aponta-lhe a partir do `git config`. Quem revê tem leitura de ficheiros e recebe
pela frente texto escrito por qualquer pessoa que abra uma PR neste repositório
público; a revisão não faz operações git autenticadas, portanto o token não
precisa de lá estar.

### A revisão à mão continua

Não é um remendo à espera de ferramenta melhor. Em sete PRs seguidas, a revisão à
mão — ler o diff outra vez, à procura do que se estragou — encontrou defeitos que
nenhuma análise estática apanha: um sinalizador de progresso que nunca era
desligado, uma conversão de Word repetida cinco vezes por documento, uma lista de
exclusão que engolia títulos de edital legítimos, uma verificação de terminal que
rebentava precisamente no ambiente que devia proteger.

A regra que a torna útil está no `AGENTS.md` e vale a pena repetir aqui: **um
teste novo tem de falhar contra o código anterior.** Um teste que passa dos dois
lados não prova nada, e dá a sensação de provar — que é pior.
