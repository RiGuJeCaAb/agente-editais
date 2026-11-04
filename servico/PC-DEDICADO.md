# O agente num PC dedicado

Quando não há espaço nos servidores para uma VM, um PC só para isto faz o
mesmo serviço. O agente, a partilha de entrada no domínio, a televisão, o
painel em HTTPS e as cópias de segurança são os mesmos do `HYPER-V.md`, e
segue-se esse guia. Este diz só o que muda: os passos que existiam por causa do
Hyper-V, e os que um PC precisa a mais, porque está numa sala e não num
servidor.

```
  postos do domínio  --SMB 445-->  [ PC editais ]  --HTTP 80-->  televisão
  (\\editais\entrada)              Debian, membro do AD           (Raspberry Pi)
                                   agente + Samba + nginx
  o teu PC  --SSH 22 (túnel)-->    painel em 127.0.0.1:8770
                                        |
                                        +--cópia noturna--> 2.º disco, no mesmo PC
                                                              |
                                                              +--uma vez por mês--> disco USB, guardado noutro sítio
```

| Passo do `HYPER-V.md` | No PC |
|---|---|
| 1. A VM | **Substitui-se** pelo passo 1 daqui: o PC e a BIOS |
| 2. O Debian | **Muda**: sem `hyperv-daemons`, com `smartmontools`, e o relógio pelos controladores de domínio (passo 2 daqui) |
| 3 a 7, 9 e 11 | Iguais. Onde diz VM, lê-se PC; onde diz «a consola do Hyper-V», lê-se o teclado e o ecrã ligados ao PC |
| 8. As cópias | **Muda o destino**: um segundo disco no próprio PC, em vez da partilha (passo 3 daqui) |
| 10. Atualizar | **Muda**: sem pontos de verificação, a rede de segurança é a cópia (passo 4 daqui) |

Os valores entre `<>` são da Câmara e não se adivinham.

---

## 1. O PC e a BIOS

**O que chega.** 16 GB de memória e um SSD de 256 GB sobram: a unidade do
agente tem um teto de 2 GB, e a conversão de um `.docx` pelo LibreOffice
soma-se a isso. O que cresce é o arquivo dos originais. Vê quanto ocupa hoje
a pasta do agente no posto Windows, e garante pelo menos quatro vezes isso
livre no SSD depois de instalado o sistema, como no `HYPER-V.md`.

**O segundo disco, para as cópias.** Um disco rígido com pelo menos o dobro do
espaço que a pasta do agente vier a ocupar: as cópias guardam os originais uma
vez e o estado de cada noite durante 60 dias. É o passo 3.

Na BIOS (a tecla aparece no arranque: `F2`, `Del` ou `F10`, conforme o
fabricante):

- **Voltar a ligar depois de uma falta de luz.** «Restore on AC power loss»,
  «After power failure» ou «AC Back», posto em **Power On**. Sem isto, uma
  falta de luz à noite deixa a televisão sem página até alguém ir carregar no
  botão. O agente acaba no arranque o documento que ficou a meio (0.27.1).
- **ErP, EuP ou «Deep Sleep» desligado.** É a poupança de energia em
  desligado, e em muitas placas impede a opção anterior de funcionar.
- **Arranque pelo SSD em primeiro lugar**, depois da instalação.

O arranque seguro pode ficar ligado: o Debian arranca com ele num PC.

**Onde fica.** Por cabo na rede, nunca por Wi-Fi. Numa sala fechada, com uma
etiqueta «Não desligar — editais», porque um PC debaixo de uma secretária é
desligado por quem precisa da tomada. Uma UPS pequena compensa o preço: a
falta de luz deixa de ser um corte a meio de uma escrita.

A informática deve saber que esta máquina existe. Vai ser membro do domínio,
guarda registos com valor legal, e é mais uma no inventário.

**O que tens de ver:** desligado da tomada e voltado a ligar, o PC arranca
sozinho, sem ninguém carregar no botão.

---

## 2. O Debian

Instalação mínima do Debian 13, como no passo 2 do `HYPER-V.md` (nome
`editais`, endereço fixo ou reserva no DHCP, **DNS nos controladores de
domínio**, só «servidor SSH» e «utilitários padrão do sistema»), com uma
diferença na instalação:

- **Instala só no SSD.** Na partição guiada, escolhe o disco pelo tamanho e
  pelo modelo. O mais seguro é instalar com o disco das cópias ainda
  desligado, e ligá-lo no passo 3.

Os pacotes são os do guia, **sem o `hyperv-daemons`** e **com o
`smartmontools`**:

```bash
sudo timedatectl set-timezone Europe/Lisbon
sudo apt update && sudo apt full-upgrade
sudo apt install smartmontools chrony unattended-upgrades \
                 git python3-venv rsync nginx ufw cifs-utils \
                 samba winbind libnss-winbind krb5-user \
                 libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea \
                 tesseract-ocr tesseract-ocr-por
```

- **`smartmontools`** lê o estado dos discos e regista no diário do sistema
  quando um começa a falhar. Num servidor há quem vigie os discos; aqui não há
  mais ninguém.

### O relógio, pelos controladores de domínio

Na VM, o relógio vinha do Hyper-V. Num PC, vem dos controladores de domínio,
e é o que deve ser: a hora de afixação que vai para a certidão é a hora desta
máquina, e o Kerberos do domínio recusa uma máquina com mais de cinco minutos
de desvio em relação a eles. Uma só fonte de hora, a do domínio.

```bash
printf 'server %s iburst\n' <DC1> <DC2> | sudo tee /etc/chrony/conf.d/dominio.conf
grep -rn '^[[:space:]]*pool' /etc/chrony/
```

O `grep` mostra onde estão os servidores de hora da Internet que o Debian
traz: costuma ser uma linha `pool` no `/etc/chrony/chrony.conf`, mas isto não
foi ensaiado num Debian 13, e é mais seguro ver do que supor. Desliga cada
linha que ele mostrar, pondo-lhe um `#` à frente:

```bash
sudo sed -i 's/^\([[:space:]]*pool \)/#\1/' <ficheiro-que-o-grep-mostrou>
sudo systemctl restart chrony
chronyc sources
```

A firewall da Câmara pode nem deixar passar os servidores da Internet, e dois
relógios que discordam por meio segundo é uma pergunta que ninguém precisa de
ter.

**O que tens de ver:** `timedatectl` com `Time zone: Europe/Lisbon`, e em
`chronyc sources` **só** os controladores de domínio, um deles com `^*`. O
asterisco quer dizer que é por ele que o relógio está a acertar. Se aparecer
outro nome, veio de algum lado: de uma linha que o `grep` não apanhou, ou do
DHCP, que pode anunciar servidores de hora (a linha `sourcedir
/run/chrony-dhcp` do `chrony.conf`). Desliga essa linha da mesma forma, e volta
a ver.

Daqui segue-se o `HYPER-V.md` do passo 3 ao 7.

---

## 3. As cópias, no segundo disco

O script e as unidades das cópias são os mesmos do passo 8 do `HYPER-V.md`.
Muda só o que está montado em `/mnt/copias`: um disco do próprio PC em vez
de uma partilha de rede.

### O que protege e o que não protege

| Contra | Segundo disco no PC | Disco USB guardado noutro sítio |
|---|---|---|
| O SSD avariar | Sim | Sim |
| Um ficheiro apagado ou estragado por engano | Sim, até 60 dias | Sim, até à última cópia |
| Uma atualização que estraga o registo | Sim | Sim |
| Roubo, incêndio, água, uma sobretensão que queima o PC | **Não** | Sim |

O segundo disco resolve quase tudo o que acontece no dia a dia. Não resolve o
que leva o PC inteiro, e é por isso que há a cópia do fim deste passo.

### Preparar o disco

Com o PC desligado, liga o disco. Depois:

```bash
lsblk -o NAME,SIZE,MODEL,MOUNTPOINTS
```

O disco das cópias é o que **não** tem `/` nem `/boot/efi` na última coluna.
Confirma pelo tamanho e pelo modelo. O comando seguinte apaga tudo o que lá
estiver, e escolher o disco errado apaga o sistema.

```bash
sudo parted /dev/<sdX> --script mklabel gpt mkpart copias ext4 0% 100%
sudo mkfs.ext4 -L copias /dev/<sdX>1
```

Em `/etc/fstab`, pela etiqueta e não pelo nome `sdX`, que pode mudar de um
arranque para o outro:

```
LABEL=copias  /mnt/copias  ext4  defaults,nofail,x-systemd.device-timeout=10s  0  2
```

O `nofail` é o que importa: com o disco das cópias avariado ou desligado, o PC
arranca na mesma, e o agente e a televisão continuam. O que falha é só a cópia,
e falha a dizer porquê.

```bash
sudo mkdir -p /mnt/copias
sudo systemctl daemon-reload
sudo mount /mnt/copias
findmnt /mnt/copias
```

**Só depois de o `findmnt` mostrar o disco**, a pasta e o ficheiro que o script
procura:

```bash
sudo mkdir -p /mnt/copias/agente-editais
sudo chmod 700 /mnt/copias/agente-editais
sudo touch /mnt/copias/agente-editais/.destino-de-copias
```

A ordem não é zelo. Criado com o disco por montar, o ficheiro ficava no SSD,
dentro da pasta `/mnt/copias` vazia, e num dia em que o disco não montasse a
cópia ia para o SSD e dava-se por feita. Assim, com o disco em falta, o script
não encontra o ficheiro e recusa.

A seguir, o passo 8 do `HYPER-V.md` a partir de «Todas as noites». A secção «A
partilha de destino» salta-se.

### Uma vez por mês, para fora do PC

Um disco USB, guardado noutro edifício ou pelo menos noutra sala. Ligado ao
PC:

```bash
lsblk -o NAME,SIZE,MODEL,MOUNTPOINTS          # o USB é o que acabou de aparecer
sudo mkdir -p /mnt/usb
sudo mount /dev/<sdY>1 /mnt/usb
sudo rsync -rt /mnt/copias/agente-editais/ /mnt/usb/agente-editais/
sudo umount /mnt/usb
```

O `-rt` copia os ficheiros e as datas, e não tenta copiar donos nem
permissões: um disco USB formatado no Windows não os guarda, e o `-a` falharia
nele. Na reposição, o `chown -R` do passo 8 volta a pô-los.

Põe no calendário. Uma cópia mensal que depende de alguém se lembrar
transforma-se numa cópia anual sem ninguém dar por isso.

---

## 4. Atualizar o agente

Num PC não há pontos de verificação. A rede de segurança é uma cópia feita
mesmo antes, e o número da versão que estava:

```bash
sudo systemctl start copia-de-seguranca.service
journalctl -u copia-de-seguranca -n 3          # tem de dizer «cópia feita»
cd /opt/agente-editais
sudo -u editais git rev-parse --short HEAD    # anota este número
```

Depois, os comandos do passo 10 do `HYPER-V.md`, a partir do `systemctl stop`.

### Se correr mal

Quase sempre chega recuar o código, sem mexer no estado. Foi ensaiado da 0.27.2
para a 0.26.1, que é a versão antes de o registo ganhar campos novos. A 0.26.1
leu o registo da 0.27.2 e trabalhou normalmente:
- recebeu um documento novo, validou-o e retirou o publicado;
- o `--conferir` não encontrou problemas;
- o campo que não conhece ficou no registo, intacto.

De volta à 0.27.2, ficou tudo certo, incluindo o documento recebido pela 0.26.1.
Entre outras versões não se ensaiou. Se a anterior não arrancar, ou o `--conferir`
mostrar problemas, é caso para repor o estado (abaixo).

```bash
sudo systemctl stop agente-editais
cd /opt/agente-editais
sudo -u editais git checkout <número-anotado>
sudo -u editais .venv/bin/pip install -r requirements.txt
sudo cp servico/agente-editais.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start agente-editais
```

Para voltar a receber atualizações mais tarde, `sudo -u editais git checkout
main` antes do `git pull`.

**Abaixo da 0.27.0, o painel perde as proteções da Fase 2.** A chave
`painel_atras_de_proxy` não existe nessas versões e é ignorada:
- o cookie de sessão deixa de levar `Secure`;
- atrás do nginx, todos os pedidos voltam a chegar como `127.0.0.1`, e uma
  pessoa a errar a senha bloqueia a entrada a toda a gente.

Enquanto estiver recuado, entra-se pelo túnel SSH (passo 6 do `HYPER-V.md`),
e não pelo endereço HTTPS.

**Repor o estado só se a versão nova o estragou**, com a secção «Repor» do
passo 8 do `HYPER-V.md` e o `estado-*.tar.gz` feito antes da atualização. A
reposição traz o registo de volta a esse instante: um documento que tenha
entrado depois dele está em `entrada/tratados/` e já não está no registo. Volta
a copiá-lo de lá para a `entrada/`, e a vigia recebe-o outra vez.

---

## 5. Os discos

O `smartmontools` corre sozinho e escreve no diário do sistema. Uma vez por mês,
junto com a cópia para o USB:

```bash
sudo smartctl -H /dev/<sdX>                    # o disco das cópias
sudo smartctl -H /dev/<nvme0n1 ou sda>         # o SSD
journalctl -u smartmontools --since "1 month ago" | grep -i -E 'fail|error|pending|realloc'
```

**O que tens de ver:** `PASSED` nos dois, e nada no `journalctl`. Um disco que
deixe de dizer `PASSED`, ou com setores realocados a subir de mês para mês,
troca-se já, enquanto ainda se lê.

---

## Verificação final

A do `HYPER-V.md`, e mais estas:

- [ ] Desligado da tomada a meio do dia e voltado a ligar, o PC arranca
      sozinho, a televisão volta, e o diário do agente não tem erros.
- [ ] `chronyc sources` mostra `^*` num controlador de domínio.
- [ ] Na manhã seguinte há um `estado-*.tar.gz` novo em
      `/mnt/copias/agente-editais`.
- [ ] **Com o disco das cópias desligado** (PC desligado, cabo de dados
      solto, PC ligado), o PC arranca, a televisão responde, e
      `sudo systemctl start copia-de-seguranca.service` falha ao fim de uns
      dez segundos, com o `journalctl -u copia-de-seguranca` a dizer que a
      dependência falhou (é o `/mnt/copias` por montar), sem copiar nada para
      o SSD. Volta a ligar o disco no fim.
- [ ] A primeira cópia mensal está no disco USB, e o disco está guardado
      noutro sítio.
- [ ] **A reposição foi ensaiada uma vez**, como o passo 8 pede, a partir do
      disco USB e não do segundo disco: é a que vai ser precisa no pior dia.
