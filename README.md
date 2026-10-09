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

> Para instalar **no posto**, a passos e com o que tens de ver a cada um, usa a
> **[lista de verificação](servico/LISTA-DE-VERIFICACAO.md)**. Esta secção diz o
> que é preciso; a lista diz por que ordem e como saber que correu bem.

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
  estático, em HTTP(S) na porta 80/443. A página busca o `slides.json` de 15 em
  15 segundos e aplica os editais novos **sem recarregar** — não é preciso tocar
  na TV, e o carrossel nem sequer se interrompe. (Isto esteve aqui descrito como
  «auto-recarrega de 5 em 5 minutos». Era errado nas duas metades: não recarrega,
  e é vinte vezes mais rápido do que isso.)

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
pytest          # 749 testes (mais 39 de browser: pytest -m navegador)
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
- **Data de retirada**: deixou de ser manual. Ao publicar, o tipo do documento
  propõe o prazo, e o painel mostra-o antes de se publicar — ver a secção 20.
  Para o tipo por omissão, que não tem prazo declarado, continua em branco.
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

**A pasta de trabalho tem o ramo base, não o da PR.** A documentação de segurança
da ação é explícita — *«do not check out an untrusted ref into the workspace root
before this action»* — e nesta configuração há uma razão pior do que a geral: o
prompt manda ler o `AGENTS.md` da pasta. Vindo do topo da PR, bastava alterar
esse ficheiro para reescrever as regras que o revisor foi mandado obedecer. O
revisor a receber instruções do código que está a rever. Vindo da base, as regras
são as que já foram fundidas, e o que a PR mudou vê-se pelo `gh pr diff`.

O número da PR vai **explícito** nesse comando. Sem ele, o `gh` procura a PR
do ramo atual — e o checkout de um SHA deixa a cópia sem ramo nenhum. A
revisão corria e ficava sem ver o diff.

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

---

## 20. A data de retirada, proposta pelo tipo — NOVO

Duas metades já existiam e nunca se tinham encontrado. O módulo `prazos.py`
sabia calcular o prazo de cada tipo de documento, com a base legal ao lado. O
registo sabia retirar sozinho tudo o que estivesse publicado com a data
vencida. A data chegava de duas maneiras — alguém a escrever no painel, ou a
migração a trazê-la do modelo antigo — e nas duas a retirada dava-se. **O que
nunca ganhava data era um edital nascido no fluxo atual**, e a retirada
automática só olha para quem a tem.

Num posto real isso deu **oito editais publicados e zero retirados**, com
documentos de junho ainda no ecrã em setembro.

### Como funciona agora

Ao **publicar**, se ninguém tiver escrito uma data de retirada, ela passa a vir
do tipo do documento: o mínimo legal quando existe, o prazo sugerido quando não
há mínimo. Para uma deliberação de órgão autárquico são cinco dias, pelo artigo
56.º do Anexo I da Lei n.º 75/2013.

E o painel mostra a data proposta **antes** de se publicar, no campo da retirada,
com uma linha a dizer de onde veio. Quem estiver ao teclado altera-a se o caso
pedir outra coisa — e aí a decisão é da pessoa, como sempre foi.

### Os três limites, e a razão de cada um

- **Só na publicação.** É aí que o relógio legal começa, e é da afixação que a
  certidão conta o prazo. Propor antes seria contar de uma data que ainda pode
  mudar.
- **Nunca por cima de uma data escrita.** A tabela informa; o posto decide.
- **Nada para o tipo por omissão.** Esse não tem prazo declarado, e a aplicação
  não inventa um prazo legal para um documento cuja natureza ninguém declarou.
  Fica em branco, e fica à espera de uma pessoa — que é o comportamento certo.

Quando a data vem da tabela, **o histórico do edital di-lo**, com o tipo que a
produziu. Quem audita tem de poder distinguir um prazo que alguém decidiu de um
que saiu de uma regra.

### Os prazos alteram-se sem tocar no código

A tabela de tipos vive em `lib/prazos.py` com valores de partida, e cada
município sobrepõe os seus em `config.json`. Cada tipo declara a norma e a
fonte, porque um prazo sem proveniência é um número que ninguém pode confirmar
nem contestar.

---

## 21. A referência interna, e os lençóis — NOVO

### A referência não é o número do edital

O **número do edital** vem do **Gestiona**, é oficial, e quem está ao teclado
copia-o de lá para o campo. A aplicação **nunca** lho atribui — inventar uma
designação que sai impressa numa certidão de afixação é a primeira coisa que
este projeto se proibiu de fazer.

A **referência interna** é outra coisa: uma etiqueta nossa, para se poder dizer
«o AE-20260929-0021» em vez de «aquele aviso da escola, salvo erro». Aparece no
painel e na certidão, sempre rotulada como interna, a seguir ao número e nunca
no lugar dele.

```
AE-20260929-0021
   └ data     └ id do registo
```

**É derivada e não guardada.** Sai da data de criação e do id, que já existem e
já são imutáveis. Guardá-la outra vez abria a porta a que divergisse do que a
produziu, e obrigava a uma migração para nada.

**A data sozinha não chegava.** Num único minuto entram vários ficheiros de uma
vez — já entraram, está no registo deste posto. O id é o que garante que duas
referências nunca colidem, e uma referência que pode colidir é pior do que não
existir.

**Imprime-se, não se atesta.** A referência sai na certidão mas fica **fora dos
factos que o selo de conferência cobre**, e isso é deliberado. Duas razões:

1. O selo atesta o que esteve afixado, quando e por quem. A referência é uma
   etiqueta nossa, não um facto do ato administrativo.
2. A referência deriva do `criado_em`, que o selo não cobre. Um facto derivado
   de um campo não selado faz o selo mudar sem que nenhum facto selado tenha
   mudado — e quem confere um papel legítimo vê uma discrepância que ninguém
   consegue explicar.

Isto custou um defeito a aprender, dentro desta mesma peça: a referência entrou
nos factos, o selo do mesmo registo mudou, e as certidões emitidas na 0.21.0
deixavam de conferir com o rodapé a dizer «formato 2» na mesma. Está no
CHANGELOG com os dois selos medidos.

### Os lençóis

O fundo da televisão eram vinte e seis linhas traçadas com 0,6 a 2,2 px, e
liam-se como filamentos. Engrossar o traço não resolvia: uma linha grossa é uma
fita, não um tecido.

O que faz ler como pano são quatro coisas, e nenhuma é a espessura sozinha:

1. É uma **faixa preenchida**, com duas margens, e não um traço.
2. A espessura **respira** ao longo do comprimento. Um lençol apanhado pelo ar
   não tem a mesma largura de ponta a ponta; uma fita tem.
3. As duas margens ondulam com **fases diferentes** — é isso que torce o pano.
4. **Duas frequências somadas**, para a margem não ser uma senóide perfeita.
   Nada em tecido é.

São onze em vez de vinte e seis, e mais fracos: a área de cada um cresceu umas
quarenta vezes, e vinte e seis lençóis a esta escala não é um fundo, é sopa.

Se ficar pesado na televisão, o número está numa linha só — `var N = 11`.

---

## 22. A certidão, escrita como se escreviam as certidões — NOVO

A certidão de afixação é **prosa**, e não um formulário. O modelo são as
certidões de oitocentos e do princípio de novecentos: o funcionário identifica-se,
escreve `CERTIFICA`, conta os factos em frases corridas e fecha com a fórmula —
*«Por ser verdade e me ter sido pedida, mandei passar a presente certidão, que
vai por mim assinada.»* — seguida do lugar, da data e do traço por onde se assina.

### As datas por extenso

```
aos vinte e nove dias do mês de junho de 2026, pelas nove horas e catorze minutos
```

**Não é enfeite: um algarismo altera-se com um traço de caneta e «vinte e nove»
não.** Era por isso que os livros de notas se escreviam assim.

Vive em `lib/extenso.py`, em português **europeu** — «catorze», «dezasseis»,
«dezassete», «dezanove». O ano fica em algarismos de propósito: com ele também
por extenso, numa certidão que cita leis com ano e prazos com ano, a frase
deixava de se ler. Os meses vão em minúscula, que é o que a norma manda — o ar
antigo vem da estrutura e das fórmulas, não de erros de ortografia.

### O que se certifica e como se confere

| Parte | O quê |
|---|---|
| Corpo | O que a certidão **afirma**: o documento, a afixação, a retirada, a base legal e as ressalvas |
| Assinatura | O traço, o nome e o cargo. Uma certidão vale quando alguém a assina |
| Nota de conferência | Como se **confere**: registo, referência interna, resumo do original, selo e formato |

As ressalvas não se omitem. Um incumprimento do prazo ou um campo que a leitura
automática propôs e ninguém confirmou aparecem no corpo, em itálico — *uma
certidão que escondesse o que a lei pede e o que de facto aconteceu seria pior
do que não haver certidão nenhuma.*

### O timbre vem da configuração, não do código

O desenho do cabeçalho e do rodapé vem dos editais do município. Os **valores**
não: ficam no `config.json`, e em branco a certidão sai sem eles.

```json
"distrito": "Distrito de Viseu",
"servico": "Divisão Administrativa e Financeira",
"cargo_de_quem_certifica": "Chefe da Divisão Administrativa e Financeira",
"morada": "Largo do Tabolado, 0000-000 Moimenta da Beira, Portugal",
"sitio": "www.cm-moimenta.pt",
"telefone": "+351 254 000 000"
```

O **logótipo** não se configura: são as mesmas duas peças que vão para a
televisão, `logo_sym` e `logo_txt`, compostas lado a lado. Quem tenha um timbre
próprio já desenhado num ficheiro põe-no em `logo_certidao`, e esse sobrepõe-se
aos dois.

**Copie-os do cabeçalho e do rodapé dos editais verdadeiros.** Não estão no
código porque não são adivinháveis, e uma certidão com a morada errada é um
documento com um erro.

### O selo não mudou

Esta peça mudou o aspeto todo e **não tocou num facto**. O `FORMATO` continua em
2 e o selo do mesmo registo continua a ser o mesmo — medido antes e depois,
`0129 7FA6 7E5E B66C` nos dois casos. As certidões já emitidas continuam a
conferir, e há um teste que fixa esse valor para ninguém o mudar por distração.

---

## 23. A folha encontra os limites do ecrã — NOVO

Reportado do posto, com fotografias: num monitor vertical a folha ficava
«quase a meio» do ecrã, e no Raspberry o fundo preenchia tudo mas o edital e o
logótipo ficavam numa ilha no meio.

### Porquê

A televisão desenhava num palco de 3840×2160 — as medidas em que a imagem do
arquivo se compõe — e encolhia esse palco inteiro até ele caber, com o menor
dos dois rácios. Num ecrã 16:9 isso é exatamente certo. Em qualquer outro punha
o desenho todo numa faixa, com o ecrã a sobrar dos dois lados. Medido:

| ecrã | antes | depois |
|---|---|---|
| TV 16:9 (4K ou FullHD) | 24,3 % da área | **24,3 %** — intocado |
| Raspberry a 1280×1024 | 17,1 % | **34,6 %** |
| monitor vertical 1080×1920 | 7,7 % | **72,1 %** |
| monitor 4:3 1024×768 | 18,2 % | **32,4 %** |

A folha num monitor vertical ocupava **sete por cento e sete décimas** do ecrã,
com 37,8 % de verde vazio acima e 37,6 % abaixo. E o logótipo, que viaja com o
palco, flutuava no meio desse vazio em vez de estar num canto.

### O que mudou

O palco **é** o ecrã. A caixa que envolve as folhas é ampliada até encostar ao
espaço disponível, com **uma escala só** — a mesma nos dois eixos, e por isso
nenhuma folha se deforma, por construção. A disposição relativa sobrevive
porque é toda medida a partir dessa caixa: os intervalos, a caixa larga da
página deitada e o alinhamento saem exatamente na mesma proporção.

**Num ecrã 16:9 nada muda**, e isso não é feliz coincidência: as três faixas
que delimitam o espaço são as do próprio palco, ditas em frações
(`FRACAO_TOPO`, `FRACAO_FUNDO`, `FRACAO_LADO` no `tratamento.py`), e por isso a
ampliação dá exatamente 1. A televisão do átrio é 16:9, e o que lá está é
certo.

### Dois defeitos que isto destapou

**O logótipo assentava trinta píxeis acima do sítio.** O CSS tinha
`top:1.76%`, e uma percentagem de `top` resolve-se sobre a **altura** do
elemento que a contém; o 0,0176 do Python nasceu de multiplicar a margem pela
**largura**. Num ecrã 4K: y=38 na televisão, y=67,6 na imagem que ficava no
arquivo — a prova e o que se viu não batiam certo. As frações passam a sair
todas do `tratamento.py` e a ser injetadas na página.

**Num ecrã muito largo o logótipo podia cair sobre a primeira folha**, porque
ele é uma fração da largura e a faixa é uma fração da altura. A faixa passa a
crescer o necessário para o conter. Custo medido num 21:9 de 3440×1440: a folha
fica 9 % menor do que ficaria sem a guarda — e sem ela o logótipo assentava em
cima do texto de um edital.

**E se o `logotipo.png` faltar**, a televisão desenha o ecrã sem ele e as
folhas assentam exatamente onde assentariam se nunca tivesse havido logótipo. O
ficheiro vive na pasta de saída e pode desaparecer — um disco cheio a meio da
escrita, uma sincronização interrompida, alguém a arrumar a pasta —, e o edital
não pode sair do sítio por causa disso. Medido no browser, em seis ecrãs.

**Mas a faixa não cresce sem travão.** Com um logótipo mais alto do que largo
num ecrã muito largo, ela comia o ecrã: medido com um rácio de 0,5 num 21:9,
ficava com 1092 dos 1440 píxeis e a folha saía com **0,7×1,0 píxeis**. O
logótipo encolhe, com o rácio intacto, antes de a faixa passar de 25 % da
altura, e a folha nunca desce dos 64 %. Com o logótipo que o município usa a
faixa fica nos 11,5 % e este teto nunca chega a morder.

### A página da televisão passou a ser testada num browser

Até aqui nenhum teste a abria: verificava-se o HTML por pesquisa de texto, e foi
assim que este defeito passou sem uma única linha vermelha. Há agora 39 testes
que a abrem num Chromium, medem o que lá está desenhado e comparam com o
`trat.desenho_no_ecra()` — incluindo o ecrã largo com um logótipo alto e o caso
do `logotipo.png` em falta. Correm num trabalho próprio da integração contínua:

```bash
pip install playwright && playwright install chromium
pytest -m navegador
```

Ficam de fora do `pytest` normal — o playwright não é dependência de execução do
agente e não se impõe a quem corre a suite à mão. Para os correr contra um
Chromium já instalado: `CHROMIUM_PARA_TESTES=/caminho/para/chrome pytest -m navegador`.

### O que continua por resolver

Três folhas lado a lado num ecrã vertical continuam pequenas — 23 % da área —
porque três A4 em fila não cabem noutro sítio numa largura de 1080. Resolver
isso é **reorganizar** o ecrã (empilhar em vez de alinhar), não ampliá-lo, e é
outra peça.

---

## 24. O timbre da Câmara, e a esquemática de uma certidão — NOVO

Visto no posto a 09/10/2026, com o modelo ao lado: «não tem o cabeçalho actual
da CMMB, e apesar de ter um português arcaico a esquemática do documento é
exactamente a mesma». Duas observações, e as duas certas.

### O cabeçalho estava a meio

A certidão punha o `logo_txt` — o letreiro «Moimenta da Beira / Município» — e
mais nada. O logótipo da Câmara são **duas** peças, o monograma e o letreiro, e
é com as duas que ela assina um ofício. A aplicação já tinha as duas para a
televisão; a certidão usava uma.

Passam a compor-se lado a lado, alinhadas pela **altura** — têm proporções
muito diferentes, 134×118 e 375×96, e escalá-las pela largura dava o monograma
do tamanho de um selo ao lado de um letreiro. Por cima do nome do município vai
a linha de estado, «REPÚBLICA PORTUGUESA · DISTRITO DE VISEU», com o distrito
vindo da configuração: é do município, não da aplicação.

### A esquemática

O texto já era prosa desde a 0.23.0, mas a folha continuava a ser uma coluna
corrida com um traço no fim. Passa a ter a forma de uma certidão:

| Peça | O quê |
|---|---|
| Moldura | Duas réguas concêntricas, em todas as folhas, como nos livros de termos |
| Timbre | Monograma e letreiro, linha de estado, nome do município, serviço, régua dupla |
| Título | «CERTIDÃO» entre duas réguas curtas, num compartimento seu |
| Corpo | Prosa justificada, com os **elementos identificadores em negrito** |
| Fecho | Lugar do selo à esquerda, assinatura encostada à direita |
| Conferência | O miudinho, numa caixa ao pé da folha |

**O negrito não é enfeite.** Quem abre uma certidão procura quatro coisas — o
número, a entidade, o assunto e a referência interna. Em redondo no meio de um
parágrafo justificado, são indistinguíveis do resto, e era esse o sentido de
«a esquemática é a mesma». O realce vai também nas datas por extenso e nos
nomes de quem afixou e retirou.

O realce é da **palavra inteira** e não do trecho exato: mudar de tipo a meio
de uma palavra obrigava a tratar cada palavra como uma lista de pedaços em toda
a aritmética de quebra de linha, e o que se ganhava era pôr «Beira» em negrito
e a vírgula a seguir em redondo. E um realce que não apareça no texto **não
rebenta a emissão**: fica registado e o parágrafo sai sem ele — os realces saem
de dados do registo, e uma certidão sem negrito certifica exatamente o mesmo.

### O lugar do selo diz que é um lugar

O círculo à esquerda da assinatura vai **a tracejado**, com «LOCUS SIGILLI» lá
dentro e a legenda «lugar do selo branco, a apor no exemplar impresso» por
baixo. Um círculo a cheio num documento oficial lê-se como selo aposto, e o PDF
não leva selo nenhum: seria o desenho a afirmar o que o texto não afirma, que é
a forma mais silenciosa de um documento mentir.

### A nota de conferência desceu ao pé da folha

Deixa de ser um bloco à solta a seguir à assinatura e passa a ser um painel
encostado ao rodapé, dentro de uma caixa. Quando não cabe no que resta da
folha, não se empurra nada: vai inteira para o alto da seguinte, como já ia.
Um painel no alto de uma folha lê-se; um painel por cima do rodapé, não.

### O selo de conferência não mudou

Outra vez: o `FORMATO` continua em **2** e o selo do mesmo registo continua a
ser o mesmo. Isto mexeu no aspeto e não tocou num facto — e há um teste que fixa
o valor para ninguém o mudar por distração.

