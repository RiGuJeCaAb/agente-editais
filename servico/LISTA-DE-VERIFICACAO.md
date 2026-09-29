# Instalação no posto — lista de verificação

Para levar ao computador onde o agente vai correr. Cada passo tem **o que fazer**
e **o que tens de ver** — se não vires isso, não passes ao seguinte.

O README explica o porquê de cada coisa; esta lista é a ordem das operações.

---

## Antes de sair daqui

- [ ] Saber que máquina é: Windows ou Linux, e quem lhe mexe.
- [ ] Ter quem te abra o `Settings` da rede, se fores fazer a VLAN.
- [ ] Levar **dois ou três editais verdadeiros** — um PDF, um Word e, se houver,
      um cartaz em imagem. São a prova real; os testes não substituem isto.
- [ ] Saber onde fica a televisão e se já tem alimentação e rede.

---

## A. A máquina

- [ ] **Python 3.10 ou mais recente.**
      ```
      python --version
      ```
      Tens de ver `Python 3.10.x` ou acima. Em Linux pode ser `python3`.

- [ ] **Uma pasta para o agente**, que não seja o Ambiente de Trabalho de
      ninguém. Sugestão: `/opt/agente-editais` em Linux, `C:\agente-editais`
      em Windows.

- [ ] **A máquina tem de ficar ligada.** Não é um portátil que vai para casa.
      Se estiver a suspender sozinha, desliga a suspensão antes de continuar —
      uma televisão a mostrar editais de ontem não avisa ninguém.

---

## B. Instalar

- [ ] Copiar o projeto para a pasta (clone do repositório, ou cópia da pasta).

- [ ] **Ambiente virtual e dependências:**
      ```
      python -m venv .venv
      .venv/bin/pip install pymupdf pillow scipy numpy        (Linux)
      .venv\Scripts\pip install pymupdf pillow scipy numpy    (Windows)
      ```

- [ ] **LibreOffice**, só se quiseres aceitar documentos Word:
      - Linux: `sudo apt install libreoffice`
      - Windows: instalar e garantir que o `soffice.exe` está no PATH.

      Confirma com `soffice --version`. **É opcional**: sem ele, PDF e imagens
      continuam a funcionar e só os `.docx` ficam de fora.

- [ ] **Tesseract**, só se quiseres ler texto de imagens e digitalizações.
      Também é opcional, e também só tira funcionalidade se faltar.

> **Daqui para a frente, `PYTHON` é o Python do ambiente virtual:**
> `.venv\Scripts\python.exe` em **Windows**, `.venv/bin/python` em **Linux**.
> Não é o `python` do sistema — esse não tem as dependências instaladas.

- [ ] **Confirmar que arranca:**
      ```
      PYTHON agente.py --versao
      ```
      Tens de ver o número da versão. Se rebentar aqui, para e resolve — não
      vale a pena continuar.

---

## C. Configurar

- [ ] Copiar `config.exemplo.json` para `config.json` e editar **num editor de
      texto simples** — Bloco de Notas, `nano`, `vim`. **Nunca o Word:** as
      aspas curvas que ele põe partem o ficheiro.

- [ ] Preencher o que identifica o posto:
      ```json
      {
        "municipio": "Moimenta da Beira",
        "local_do_expositor": "Átrio do edifício dos Paços do Concelho",
        "painel_host": "127.0.0.1",
        "painel_porta": 8770,
        "segundos_por_ecra": 30,
        "manter_zips": 3
      }
      ```
      O `municipio` e o `local_do_expositor` saem impressos **na certidão de
      afixação**. Vale a pena escrevê-los como querem que apareçam no papel.

- [ ] **Não ponhas `painel_senha`.** Existia no modelo antigo e já não faz nada;
      se estiver lá, o agente avisa no arranque. O painel tem contas
      individuais, precisamente para a certidão poder dizer **quem** afixou.

- [ ] **`painel_host`**: `127.0.0.1` deixa o painel acessível só nessa máquina.
      Se quiseres abri-lo de outro posto da rede interna, tem de mudar — mas lê
      antes a secção do README sobre expor a outros postos, porque isso muda o
      que tens de proteger.

---

## D. A primeira conta

- [ ] Criar a conta de administrador, **numa janela de terminal**:
      ```
      PYTHON agente.py --criar-utilizador ana --administrador
      ```
      Pede nome completo e senha (mínimo 10 caracteres), sem eco.

- [ ] **Se responder que precisa de um terminal**, é porque não há teclado do
      outro lado — duplo clique no ficheiro, consola sem stdin, ou o comando
      dentro de um script. Abre uma janela de terminal a sério e repete. Isto é
      de propósito: a senha não pode passar por argumento nem por canalização,
      senão fica no histórico da consola.

- [ ] Confirmar:
      ```
      PYTHON agente.py --utilizadores
      ```
      Tens de ver a conta na lista.

- [ ] **O nome completo é o que vai na certidão.** Vale a pena estar certo
      à primeira.

---

## E. A primeira prova, com editais verdadeiros

Esta é a parte que não se salta. É aqui que se descobre se as heurísticas de
extração servem para os editais **desta** câmara.

- [ ] Arrancar o painel:
      ```
      PYTHON agente.py --painel
      ```

- [ ] Abrir `http://127.0.0.1:8770` no browser da máquina e entrar com a conta.

- [ ] Pôr **um edital em PDF** na pasta `entrada/`. O painel deteta-o sozinho.

- [ ] **Conferir o que ele extraiu:** assunto, número, data. A extração é
      heurística calibrada para os editais da CMMB — se o layout for diferente,
      corrige no painel. **Anota o que ele errou**: é isso que vale a pena
      afinar depois, e é informação que nenhum teste me dá.

- [ ] Repetir com **um Word** (se instalaste o LibreOffice) e com **um cartaz
      em imagem**. No cartaz sem texto, o assunto vem do nome do ficheiro — é
      esperado, preenche à mão.

- [ ] **Definir a data de retirada.** É manual por opção. Se todos os editais
      desta câmara forem «30 dias após publicação», diz-me e automatizo — o
      README diz que é uma linha a mudar.

- [ ] Publicar um e ver aparecer em `saida/`.

- [ ] **Emitir a certidão** e ler o PDF com atenção: município, local, nome de
      quem afixou, datas. É um documento com valor legal — se alguma coisa lá
      estiver mal, é agora que se corrige.

---

## F. Pôr a correr sozinho

Não há nada a agendar. O que corre sozinho é o **painel**, e é ele que vigia a
entrada. O processamento acontece quando chega um ficheiro; a publicação,
quando uma pessoa autoriza.

### Linux (systemd)

- [ ] Ajustar `User`, `Group` e os caminhos em `servico/agente-editais.service`.
      Vem preenchido para o utilizador `editais` e a pasta `/opt/agente-editais`.
- [ ] Instalar:
      ```
      sudo cp servico/agente-editais.service /etc/systemd/system/
      sudo systemctl daemon-reload
      sudo systemctl enable --now agente-editais
      systemctl status agente-editais
      ```
- [ ] Tem de aparecer `active (running)`.

### Windows

- [ ] O painel como serviço via **NSSM**, apontado a `agente.py --painel` com o
      Python do ambiente virtual.

### Nos dois casos

- [ ] **Confirmar que se levanta sozinho:** mata o processo e vê se volta.
      A unidade tem `Restart=always` com 10 segundos de espera, de propósito —
      se morrer às três da manhã ninguém o vai levantar à mão.

- [ ] **Publicar um edital COM O SERVIÇO INSTALADO**, e não só à mão antes.
      Este passo não estava aqui, e a falta dele deixou passar um defeito real:
      a unidade systemd arrancava com a raiz do projeto só de leitura, por isso
      o serviço subia, o `/saude` respondia, e **nada se gravava**. Arrancar não
      é funcionar. Só se sabe que está instalado quando um edital verdadeiro
      atravessa o circuito todo com o serviço a correr.

- [ ] **Confirmar o `/saude`:**
      ```
      curl http://127.0.0.1:8770/saude
      ```
      Responde sem sessão. É por aqui que um supervisor sabe se está de pé.

- [ ] **Reiniciar a máquina** e confirmar que o serviço volta sozinho. Não
      assumas: testa.

---

## G. Servir a saída para a televisão

A pasta `saida/` é um site estático. A TV lê por **URL** — não por pasta
partilhada nem por pen.

- [ ] **Para experimentar**, na própria máquina:
      ```
      cd saida && python -m http.server 8080
      ```
      A TV aponta para `http://IP-DA-MAQUINA:8080/`.

- [ ] **Para ficar**, servir `saida/` com **nginx** (Linux) ou **IIS**
      (Windows), como site estático na porta 80. O `http.server` do Python é
      para testar, não para viver.

- [ ] **IP fixo na máquina.** Se o IP mudar, a televisão fica a olhar para o
      vazio e ninguém dá por isso até alguém passar no átrio.

- [ ] Abrir esse URL de **outro** computador da rede e confirmar que a página
      aparece. Se só funcionar na própria máquina, é firewall.

---

## H. A televisão

- [ ] Abrir o browser da TV no URL e pô-lo em **modo quiosque / ecrã inteiro**.
- [ ] Confirmar que a página **apanha editais novos sozinha**. Busca o
      `slides.json` de **15 em 15 segundos** e aplica o que houver de novo **sem
      recarregar** — o carrossel nem se interrompe. Publica um edital e conta
      até vinte: tem de aparecer sem ninguém tocar na televisão.

      (A versão anterior desta lista, e o README, diziam «recarrega de 5 em 5
      minutos». Era errado nas duas metades.)
- [ ] **Desligar a proteção de ecrã e a suspensão** da TV.
- [ ] Confirmar que, depois de a TV se desligar e ligar, volta ao URL sozinha.
      Se não voltar, procura a opção de arranque automático no browser dela.
- [ ] Ver de longe, do sítio onde as pessoas param mesmo. Se não se ler a seis
      metros, o problema é real e quero saber.

---

## I. A rede (opcional, mas recomendado)

Uma VLAN **não serve ficheiros** — a TV lê o URL. A VLAN existe para
isolamento, e é isso que a torna útil: se o firmware da televisão for
comprometido, e são aparelhos fracos, não chega à rede administrativa.

- [ ] VLAN dedicada de signage (ex. `VLAN 50 — SIGNAGE`).
- [ ] Servidor com IP fixo, TV com reserva DHCP.
- [ ] Firewall: permitir SIGNAGE → servidor nas portas 80/443; negar
      SIGNAGE → ADMIN; negar SIGNAGE → Internet, salvo o indispensável.

O esboço completo, com as regras, está na secção 5.2 do README.

---

## J. Antes de sair do posto

- [ ] Um edital verdadeiro publicado e **visível na televisão**.
- [ ] A certidão desse edital emitida e lida.
- [ ] O serviço a levantar-se sozinho depois de um reinício da máquina.
- [ ] Alguém do posto **a saber entrar no painel** e a ter feito uma publicação
      à tua frente. Se ninguém souber usar isto, não está instalado.
- [ ] `--conferir` a correr limpo:
      ```
      PYTHON agente.py --conferir
      ```
      Relata o que estiver desalinhado entre o registo e o disco. Não apaga nada.

---

## Quando corre mal

| Sintoma | Onde olhar |
|---|---|
| O painel não abre | o serviço está de pé? `curl .../saude` responde? |
| Abre na máquina e não de fora | `painel_host` e a firewall |
| Documento Word não entra | o LibreOffice está instalado e no PATH? |
| Assunto ou data errados | heurística: corrige no painel e **anota o caso** |
| Cartaz sem assunto | é esperado; vem do nome do ficheiro |
| A TV mostra editais velhos | o URL ainda responde? o IP da máquina mudou? |
| A TV está em branco | a firewall entre VLANs, ou a página não está a ser servida |

O registo técnico fica em `diario/`, com rotação. Em Linux, também em
`journalctl -u agente-editais -f`.

**E se alguma coisa não bater certo com esta lista, o defeito é da lista.**
Anota e diz — ela existe para ser corrigida por quem a usou no terreno.
