# O agente numa VM Debian no Hyper-V

Do servidor Hyper-V da Câmara até à televisão a ler da VM, por esta ordem. Cada
passo diz o que fazer e o que tens de ver; se não vires isso, não passes ao
seguinte.

A `LISTA-DE-VERIFICACAO.md` continua a servir a instalação num posto qualquer.
Esta é a da VM, e acrescenta-lhe três coisas que um posto isolado não tinha: a
pasta de entrada partilhada na rede, o registo de **quem colocou** cada
documento, e as cópias de segurança para fora da máquina.

```
  postos do domínio  --SMB 445-->  [ VM editais ]  --HTTP 80-->  televisão
  (\\editais\entrada)              Debian, membro do AD           (Raspberry Pi)
                                   agente + Samba + nginx
  o teu PC  --SSH 22 (túnel)-->    painel em 127.0.0.1:8770
                                        |
                                        +--cópia noturna--> partilha de cópias
```

Os valores entre `<>` são da Câmara e não se adivinham: pede-os à informática
ou tira-os de um posto do domínio.

---

## 1. A VM

No servidor Hyper-V, em PowerShell como administrador. Ajusta os caminhos e o
nome do comutador virtual (`Get-VMSwitch` lista-os).

```powershell
$nome = "editais"
New-VM -Name $nome -Generation 2 -MemoryStartupBytes 4GB `
       -NewVHDPath "D:\Hyper-V\$nome\$nome.vhdx" -NewVHDSizeBytes 40GB `
       -SwitchName "<COMUTADOR>"
Set-VMProcessor -VMName $nome -Count 2
Set-VMMemory    -VMName $nome -DynamicMemoryEnabled $false
Set-VMFirmware  -VMName $nome -SecureBootTemplate MicrosoftUEFICertificateAuthority
Set-VM -Name $nome -AutomaticStartAction Start -AutomaticStopAction ShutDown `
       -CheckpointType Production
Add-VMDvdDrive  -VMName $nome -Path "D:\ISO\debian-13-amd64-netinst.iso"
Set-VMFirmware  -VMName $nome -FirstBootDevice (Get-VMDvdDrive -VMName $nome)
Start-VM $nome
```

Porque cada linha:

- **Geração 2 com o modelo `MicrosoftUEFICertificateAuthority`.** O modelo de
  arranque seguro que vem por omissão é o do Windows, e com ele o Debian não
  arranca. A documentação da Microsoft sobre máquinas Debian no Hyper-V manda
  trocar para este.
- **4 GB fixos.** A unidade do agente tem um teto de 2 GB, e a conversão de um
  `.docx` pelo LibreOffice soma-se a isso. Memória dinâmica num serviço que
  corre o dia todo só acrescenta uma variável quando alguma coisa correr mal.
- **40 GB de disco** são um ponto de partida, não uma medida: o que cresce é o
  arquivo dos originais. Vê quanto ocupa hoje a pasta do agente no posto
  Windows e garante pelo menos quatro vezes isso.
- **Arranque e paragem automáticos** com o servidor, para a televisão não ficar
  sem página depois de uma manutenção do Hyper-V.

**O que tens de ver:** a VM a arrancar o instalador do Debian. Se aparecer um
ecrã de erro de arranque seguro, o modelo não ficou trocado.

---

## 2. O Debian

Instalação mínima do Debian 13:

- **Nome da máquina:** curto, até 15 caracteres, sem pontos — é também o nome
  NetBIOS no domínio, e esse tem esse limite. Aqui usa-se `editais`.
- **Domínio:** o DNS do domínio, `<dominio.dns>` em minúsculas.
- **Rede:** endereço fixo, ou reserva no DHCP. **Os servidores de DNS são os
  controladores de domínio**, não o router: é por eles que a VM encontra o AD.
- **Software:** só «servidor SSH» e «utilitários padrão do sistema». Nada de
  ambiente gráfico.

Depois do primeiro arranque, por SSH:

```bash
sudo timedatectl set-timezone Europe/Lisbon
sudo apt update && sudo apt full-upgrade
sudo apt install hyperv-daemons chrony unattended-upgrades \
                 git python3-venv rsync nginx ufw cifs-utils \
                 samba winbind libnss-winbind krb5-user \
                 libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea \
                 tesseract-ocr tesseract-ocr-por
```

- **`hyperv-daemons`** é o que deixa o Hyper-V congelar o sistema de ficheiros
  durante um ponto de verificação. Sem ele, o «Production» do passo 1 recua em
  silêncio para um ponto de verificação comum, que guarda a máquina a meio de
  uma escrita.
- **Carlito e Caladea** têm as mesmas medidas da Calibri e da Cambria. Os
  editais escritos em Word usam quase todos uma das duas, e sem elas o
  LibreOffice troca a letra e o texto muda de linha na conversão.
- **`unattended-upgrades`** aplica as atualizações de segurança do Debian
  sozinho. É uma VM que ninguém vai abrir todas as semanas.
- **LibreOffice e Tesseract são opcionais**, como em qualquer posto: sem eles,
  ficam de fora o Word e a leitura de texto de imagens, e o resto funciona.

**O que tens de ver:** `timedatectl` com `Time zone: Europe/Lisbon`, e
`soffice --version` e `tesseract --list-langs` (com `por` na lista) a responder.

### O relógio

A hora de afixação que vai para a certidão é a hora desta máquina, e o
Kerberos do domínio recusa uma máquina com mais de cinco minutos de desvio. O
Hyper-V dá à VM um relógio de referência próprio, que o `chrony` sabe ler:

```bash
ls -l /dev/ptp*                          # procura o do Hyper-V
cat /sys/class/ptp/ptp0/clock_name       # tem de dizer hyperv
```

Se existir `/dev/ptp_hyperv`, usa esse nome; senão, o `/dev/ptp0` que disse
`hyperv`.

```bash
echo 'refclock PHC /dev/ptp_hyperv poll 3 dpoll -2 offset 0 stratum 2' \
  | sudo tee /etc/chrony/conf.d/hyperv.conf
sudo systemctl restart chrony
chronyc sources
```

**O que tens de ver:** uma linha `#* PHC0` em `chronyc sources`. O asterisco
quer dizer que é por ela que o relógio está a acertar.

---

## 3. O agente

```bash
sudo useradd --system --home-dir /opt/agente-editais --shell /usr/sbin/nologin editais
sudo git clone https://github.com/RiGuJeCaAb/agente-editais.git /opt/agente-editais
sudo chown -R editais:editais /opt/agente-editais
cd /opt/agente-editais
sudo -u editais python3 -m venv .venv
sudo -u editais .venv/bin/pip install -r requirements.txt
sudo -u editais mkdir -p entrada saida previas originais arquivo fundos trabalho diario
sudo chmod 3770 entrada
```

Se a VM não chegar ao GitHub, copia a pasta do repositório por `scp` em vez do
`git clone`, e o resto é igual.

**As pastas criam-se todas antes de arrancar o serviço**, e não é zelo: a
unidade declara-as em `ReadWritePaths`, e o systemd recusa arrancar quando
uma delas não existe.

O `3770` na entrada é o que a partilha vai precisar: o dono (`editais`) e o
grupo (`editais`) escrevem, o bit de grupo faz tudo o que lá for criado
herdar o grupo `editais`, e o bit «sticky» deixa apagar ou mudar o nome de um
ficheiro só ao dono dele e ao agente. Sem esse, quem carrega podia apagar os
documentos das colegas antes de a vigia passar.

O Debian 13 traz o Python 3.13. O `pyproject.toml` pede 3.10 ou mais recente, e
a integração contínua corre em 3.10 e 3.12. A 3.13 não está na matriz.

```bash
sudo -u editais .venv/bin/python agente.py --versao
sudo -u editais cp config.exemplo.json config.json
sudo -u editais nano config.json
```

O `painel_host` fica em `127.0.0.1`. É de propósito, e o passo 6 diz porquê.

```bash
sudo -u editais .venv/bin/python agente.py --criar-utilizador <NOME> --administrador
sudo cp servico/agente-editais.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agente-editais
curl -s http://127.0.0.1:8770/saude | python3 -m json.tool
```

**O que tens de ver:** `"ok": true`. Se o serviço não arrancar,
`journalctl -u agente-editais -n 30` diz qual pasta faltou.

---

## 4. A partilha de entrada, no domínio

### O que pedir à informática

- O nome NetBIOS do domínio (`<DOMINIO>`) e o DNS (`<DOMINIO.DNS>`).
- **Um grupo do AD para quem carrega documentos** (`<GRUPO-AD>`), com as
  pessoas lá dentro. Grupo próprio, e não «Utilizadores do domínio»: quem pode
  pôr um documento no expositor público de uma Câmara é uma lista, não toda a
  gente.
- Uma conta com permissão para juntar máquinas ao domínio, só para o passo do
  `net ads join`.

### Kerberos

Em `/etc/krb5.conf`, a secção `[libdefaults]` fica só com isto:

```
[libdefaults]
    default_realm = <DOMINIO.DNS>
    dns_lookup_realm = false
    dns_lookup_kdc = true
```

### Samba

```bash
sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.original
sudo cp servico/smb.conf.exemplo /etc/samba/smb.conf
sudo nano /etc/samba/smb.conf       # substitui os três valores entre <>
testparm -s
```

**O que tens de ver:** o `testparm` sem erros, e a secção `[entrada]` no fim.

### Juntar ao domínio

```bash
sudo net ads join -U <conta-que-junta-maquinas>
```

Em `/etc/nsswitch.conf`, acrescenta `winbind` às linhas `passwd` e `group`:

```
passwd:  files systemd winbind
group:   files systemd winbind
```

```bash
sudo systemctl restart winbind smbd
sudo systemctl disable --now nmbd
wbinfo -t
getent passwd <um.utilizador.do.ad>
```

**O que tens de ver:** `wbinfo -t` a dizer que o segredo de confiança está
bem, e o `getent` a devolver o utilizador com um número a partir de 10000. É
esse número, guardado em cada ficheiro como dono, que o agente traduz de volta
para o nome.

O `nmbd` é o serviço de nomes NetBIOS, da rede de antigamente. A partilha
abre-se pelo nome DNS, que o `net ads join` regista no domínio, e não precisa
dele. Se `\\editais\entrada` não abrir num posto, `nslookup editais` nesse
posto diz se o nome chegou ao DNS do domínio. Se não chegou, o registo faz-se à
mão, e é a informática que o faz.

### Como fica registado quem colocou

O `smb.conf.exemplo` explica-o linha a linha. Em resumo:

- **Sem `force user`.** Cada ficheiro copiado para a partilha fica com o dono
  da conta do domínio que o copiou. Com `force user`, todos seriam do mesmo
  utilizador.
- **`force group = editais`.** Os ficheiros ficam do grupo do agente, com
  permissão `0640`: ele lê-os e move-os sem mudar o dono, e as outras pessoas
  do grupo não escrevem por cima. Com o bit «sticky» da pasta, também não os
  apagam.
- **`server smb encrypt = required`.** Os documentos atravessam a rede antes de
  serem públicos, e vão cifrados. Um posto sem SMB3 é recusado.
- O agente lê o dono no momento em que cria o rascunho, e é esse nome que fica
  no histórico do edital: «Documento recebido e lido», por `ana.abreu`.

### A cópia que ainda está a chegar

Um PDF grande copiado pela rede chega aos bocados, e a vigia passa de 30 em 30
segundos. Um ficheiro a meio já tem nome e tamanho, e o PyMuPDF repara PDFs
truncados sem se queixar: lia-se metade de um edital como se fosse o edital.

O agente espera que o ficheiro esteja **15 segundos sem mudar** antes de lhe
tocar (`entrada_assentamento` no `config.json`). Conta pela hora da VM, e não
pela data que o posto pôs no ficheiro: um posto com o relógio errado não prende
um edital na entrada. Uma cópia lenta fica para a volta seguinte; nada se perde
por isso.

---

## 5. A televisão

```bash
sudo cp servico/nginx-editais.conf /etc/nginx/sites-available/editais
sudo ln -s /etc/nginx/sites-available/editais /etc/nginx/sites-enabled/editais
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
curl -sI http://127.0.0.1/ | head -1
```

**O que tens de ver:** `HTTP/1.1 200 OK`. A televisão passa a apontar para
`http://<IP-DA-VM>/`.

A VM tem endereço fixo, e esse endereço é o que fica na televisão. Se a TV
vive numa VLAN de *signage* (README, secção 5.2), a regra entre VLANs que
deixava a TV chegar ao posto Windows passa a apontar a este endereço, na porta
80.

---

## 6. O painel, até haver HTTPS

**Nesta fase, o painel não se abre à rede.** Sem HTTPS, a senha atravessava a
rede em claro, e a sessão também. O `painel_host` fica em `127.0.0.1`, e chega-se
lá por um túnel SSH, que o Windows 10 e 11 já trazem:

```
ssh -L 8770:127.0.0.1:8770 <utilizador>@editais
```

Com essa janela aberta, o painel está em `http://127.0.0.1:8770/` no teu
browser, cifrado de ponta a ponta pelo SSH.

É suficiente enquanto quem valida és só tu. Quando houver mais pessoas, é a
Fase 2, no passo 11: o painel em HTTPS, com o certificado da autoridade de
certificação da Câmara. O túnel continua a funcionar depois disso, e fica como
porta das traseiras se o nginx falhar.

---

## 7. A firewall

```bash
sudo ufw default deny incoming
sudo ufw allow from <REDE-ADMINISTRATIVA> to any port 22  proto tcp
sudo ufw allow from <REDE-DOS-POSTOS>     to any port 445 proto tcp
sudo ufw allow from <IP-DA-TELEVISAO>     to any port 80  proto tcp
sudo ufw enable
sudo ufw status numbered
```

**Ativa só depois de confirmares a regra do SSH**, ou ficas fora da VM — e
nesse caso a consola do Hyper-V é o caminho de volta.

A porta 8770 do painel não aparece: escuta só em `127.0.0.1`, e o túnel chega
lá por dentro. Com a Fase 2 (passo 11), abre-se a 443 aos postos.

---

## 8. As cópias de segurança

Copia-se o que não se refaz: o registo, o jornal de auditoria, as contas, a
configuração, os originais, o arquivo e as pré-visualizações. Vai **para fora
da VM**: uma cópia que vive no mesmo disco morre com ele.

### A partilha de destino

Uma partilha noutro servidor, com uma conta de serviço do AD que só escreve
lá:

```bash
sudo mkdir -p /mnt/copias
sudo install -m 600 /dev/null /root/.credenciais-copias
sudo nano /root/.credenciais-copias
```

```
username=<conta-de-copias>
password=<senha>
domain=<DOMINIO>
```

Em `/etc/fstab`:

```
//<SERVIDOR>/<PARTILHA>  /mnt/copias  cifs  credentials=/root/.credenciais-copias,vers=3.0,uid=0,gid=0,dir_mode=0700,file_mode=0600,_netdev,x-systemd.automount  0  0
```

```bash
sudo systemctl daemon-reload
ls /mnt/copias
sudo mkdir -p /mnt/copias/agente-editais
sudo touch /mnt/copias/agente-editais/.destino-de-copias
```

O ficheiro `.destino-de-copias` é o que o script procura antes de copiar.
Sem ele, se a partilha não tivesse montado, a cópia ia parar a uma pasta vazia
dentro da própria VM, e dava-se por feita.

### Todas as noites

```bash
sudo cp servico/copia-de-seguranca.service servico/copia-de-seguranca.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now copia-de-seguranca.timer
sudo systemctl start copia-de-seguranca.service
journalctl -u copia-de-seguranca -n 20
```

**O que tens de ver:** `cópia feita: /mnt/copias/agente-editais/estado-...tar.gz`.

O agente pára durante a cópia, uns segundos, e volta a arrancar mesmo que a
cópia falhe. A televisão não dá por isso: quem a serve é o nginx.

### Repor

```bash
sudo systemctl stop agente-editais
cd /opt/agente-editais
sudo tar -xzf /mnt/copias/agente-editais/estado-<AAAAMMDD-HHMM>.tar.gz
sudo rsync -a /mnt/copias/agente-editais/{originais,arquivo,previas} ./
sudo chown -R editais:editais /opt/agente-editais
sudo systemctl start agente-editais
sudo -u editais .venv/bin/python agente.py --conferir
```

A pasta `saida/` não está na cópia de propósito: as folhas da televisão
refazem-se na publicação seguinte.

A pasta `entrada/` também não. Tudo o que lá chegou a rascunho está em
`originais/`, que vai na cópia. Um documento que ainda esteja na entrada à hora
da cópia, por não ter sido aceite ou por ter chegado no minuto anterior, não
tem cópia fora da VM; quem o carregou ainda tem o original.

**Ensaia isto uma vez**, numa VM de teste, antes de precisares. Uma cópia que
nunca se repôs é uma esperança, não uma cópia.

### Os pontos de verificação não são cópias

Um ponto de verificação do Hyper-V vive no mesmo armazenamento da VM. Serve
para voltar atrás numa atualização (passo 10), não para sobreviver à perda do
disco. Se o servidor Hyper-V tem cópia própria das VMs, ótimo: soma-se a esta,
não a substitui. Esta é a que guarda o estado num instante em que o agente
estava parado, e por isso coerente.

---

## 9. Trazer o estado do posto Windows

**Os dois nunca correm ao mesmo tempo.** Dois agentes com dois registos e duas
pastas de entrada separavam o histórico dos editais em dois, e não há maneira
limpa de os voltar a juntar.

### No posto Windows

1. Espera que a pasta `entrada` fique vazia: tudo o que lá estiver tem de
   chegar a rascunho primeiro.
2. Guarda o relatório da conferência, para comparar depois:
   ```powershell
   cd C:\agente-editais
   .venv\Scripts\python.exe agente.py --conferir > $env:TEMP\conferir-windows.txt
   ```
3. Pára o agente (`nssm stop AgenteEditais`, ou fecha a janela do painel).
4. Junta o estado num arquivo e envia-o para a VM:
   ```powershell
   tar -czf $env:TEMP\migracao.tar.gz registo_entrada.json registo_auditoria.jsonl `
       utilizadores.json config.json originais arquivo previas
   scp $env:TEMP\migracao.tar.gz <utilizador>@editais:/tmp/
   ```

### Na VM

```bash
sudo systemctl stop agente-editais
cd /opt/agente-editais
sudo tar -xzf /tmp/migracao.tar.gz
sudo chown -R editais:editais /opt/agente-editais
sudo -u editais nano config.json
```

**Revê o `config.json` que veio do Windows** antes de arrancar:

- Se tiver algum caminho de pasta escrito à mão (`"entrada": "C:\\..."`),
  apaga essa linha. Sem ela, valem as pastas da VM.
- O `painel_host` volta a `127.0.0.1` (passo 6).

O registo guarda nomes de ficheiro e resumos, não caminhos, e por isso passa
de Windows para Linux sem conversão nenhuma.

```bash
sudo systemctl start agente-editais
sudo -u editais .venv/bin/python agente.py --conferir
```

**O que tens de ver:** o mesmo relatório que o Windows deu no ponto 2.
Diferenças só nas folhas da televisão, que a primeira publicação refaz.

### A televisão e o recuo

Aponta a televisão para `http://<IP-DA-VM>/`. **O posto Windows fica parado
mas intacto duas semanas.** Se alguma coisa correr mal, volta-se a arrancar lá,
com a televisão apontada de volta. O que entrou na VM entretanto terá de ser
carregado outra vez, e é por isso que o recuo se decide cedo ou não se usa.

---

## 10. Atualizar o agente

```powershell
Checkpoint-VM -Name editais -SnapshotName "antes de <versao>"
```

```bash
sudo systemctl stop agente-editais
cd /opt/agente-editais
sudo -u editais git pull
sudo -u editais .venv/bin/pip install -r requirements.txt
sudo cp servico/agente-editais.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start agente-editais
sudo -u editais .venv/bin/python agente.py --versao
curl -s http://127.0.0.1:8770/saude
```

A unidade copia-se outra vez porque também muda entre versões: esta traz o
fuso horário e a pasta pessoal do LibreOffice.

Se correr bem, apaga o ponto de verificação ao fim de uns dias
(`Remove-VMCheckpoint`). Um ponto de verificação esquecido faz crescer um disco
diferencial que ninguém vigia, e a VM fica mais lenta a cada escrita.

---

## 11. Fase 2 — o painel em HTTPS

O painel continua a escutar só em `127.0.0.1:8770`. Quem fala com a rede é o
nginx, que cifra a ligação com um certificado emitido pela autoridade de
certificação da Câmara e passa os pedidos ao painel por dentro da VM. Os postos
do domínio já confiam nessa autoridade, e por isso o browser não mostra aviso
nenhum.

O endereço fica `https://agente-edital-digital.<dominio.dns>/`.

### O que pedir à informática

- **Um registo no DNS do domínio**: `agente-edital-digital`, do tipo A, para o
  endereço da VM.
- **O certificado**, emitido a partir do pedido que se gera abaixo, com o
  modelo de servidor web da autoridade da Câmara.
- **A cadeia da autoridade**, em Base64: o certificado da autoridade que emitiu
  e, se a Câmara tiver uma raiz e uma emissora, os dois.

### O pedido de certificado

Gera-se na VM, e a chave privada nunca sai de lá:

```bash
sudo mkdir -p /etc/ssl/agente-edital-digital
cd /etc/ssl/agente-edital-digital
sudo openssl req -new -newkey rsa:3072 -nodes \
    -keyout chave.pem -out pedido.csr \
    -subj "/CN=agente-edital-digital.<dominio.dns>" \
    -addext "subjectAltName=DNS:agente-edital-digital.<dominio.dns>"
sudo chmod 600 chave.pem
```

O `subjectAltName` não é opcional: os browsers atuais ignoram o `CN` e recusam
um certificado que não traga o nome nesse campo.

O `pedido.csr` vai para a informática. Num posto do domínio com permissão de
inscrição, o pedido submete-se com:

```
certreq -submit -attrib "CertificateTemplate:WebServer" pedido.csr servidor.cer
```

`WebServer` é o nome interno do modelo «Servidor Web» de origem. Se a Câmara
usar um modelo próprio, o nome é o dele.

### Instalar o certificado

Com o `servidor.cer` e a cadeia da autoridade (`autoridade.cer`) na VM:

```bash
cd /etc/ssl/agente-edital-digital
for f in servidor autoridade; do
    sudo openssl x509 -in $f.cer -out $f.pem 2>/dev/null \
      || sudo openssl x509 -inform der -in $f.cer -out $f.pem
done
openssl x509 -in servidor.pem -noout -subject -issuer -enddate -ext subjectAltName
```

O ciclo aceita os dois formatos em que o Windows entrega certificados, Base64 e
binário (DER), e deixa os dois em `.pem`, que é o que o nginx lê.

**O que tens de ver:** o nome `agente-edital-digital.<dominio.dns>` no
`subjectAltName`, e a autoridade da Câmara no `issuer`. Sem o nome no
`subjectAltName`, o certificado não serve, e volta para a informática.

```bash
cat servidor.pem autoridade.pem | sudo tee cadeia.pem > /dev/null
openssl verify -CAfile autoridade.pem servidor.pem
```

**O que tens de ver:** `servidor.pem: OK`. A cadeia vai inteira para o nginx
porque um posto que não tenha a autoridade emissora em cache recusa a ligação
sem ela, e o erro não diz porquê.

### O nginx e o agente

```bash
sudo cp servico/nginx-painel.conf /etc/nginx/sites-available/painel
sudo sed -i 's/<DOMINIO.DNS>/<dominio.dns>/g' /etc/nginx/sites-available/painel
sudo ln -s /etc/nginx/sites-available/painel /etc/nginx/sites-enabled/painel
sudo nginx -t && sudo systemctl reload nginx
```

No `config.json` do agente, `"painel_atras_de_proxy": true`, e depois
`sudo systemctl restart agente-editais`. Duas coisas mudam no painel com ela:

- **O cookie de sessão passa a levar `Secure`**, e nunca viaja por HTTP simples.
- **O endereço de quem entra passa a vir do nginx.** Atrás dele, todos os
  pedidos chegavam de `127.0.0.1`, e o bloqueio de tentativas falhadas, que
  conta por endereço, trancava a Câmara inteira por causa de uma pessoa.

O `painel_host` continua em `127.0.0.1`. Nunca se põe a `0.0.0.0` com o nginx à
frente: o painel ficava acessível por HTTP ao lado do HTTPS.

O túnel SSH do passo 6 continua a servir de porta das traseiras no Chrome, no
Edge e no Firefox. No Safari não: ele não guarda o cookie com `Secure` em
`http://127.0.0.1`, e não se consegue entrar por ali.

### A firewall

```bash
sudo ufw allow from <REDE-DOS-POSTOS> to any port 443 proto tcp
sudo ufw allow from <REDE-DOS-POSTOS> to any port 80  proto tcp
```

A 80 é só para quem escrever o endereço sem `https` ser reencaminhado. Pelo
endereço IP da VM, na 80, os postos passam a ver a página da televisão, que é
pública de qualquer forma. Na 443, pelo IP ou por qualquer nome que não seja o
do painel, a ligação é recusada logo no início, em vez de chegar ao painel com
um aviso de certificado.

### Verificar

- [ ] Num posto do domínio, `https://agente-edital-digital.<dominio.dns>/` abre
      o painel com o cadeado e sem aviso nenhum.
- [ ] `http://agente-edital-digital.<dominio.dns>/` vai parar ao `https`.
- [ ] Depois de entrar, as ferramentas do browser mostram o cookie
      `editais_sessao` com `Secure` e `HttpOnly`.
- [ ] Uma senha errada várias vezes num posto deixa esse posto de castigo, e um
      colega noutro posto continua a entrar. O diário mostra os endereços dos
      postos, e não `127.0.0.1`.
- [ ] Publicar um edital grande acaba sem erro. O nginx espera até 300 s pela
      resposta, porque publicar compõe as imagens antes de responder.

### Quando o certificado expira

O modelo de servidor web da autoridade dá normalmente uma validade de um a dois
anos, e a data certa vê-se no `-enddate` acima. Um certificado expirado põe o
painel atrás de um aviso vermelho que ninguém deve ensinar os colegas a
ultrapassar.

Se o supervisor da Câmara (Zabbix, uptime-kuma) vigiar o
`https://agente-edital-digital.<dominio.dns>/saude`, a maior parte deles avisa
sozinha antes de o certificado expirar. Senão, a data vai para o calendário de
quem trata dos servidores, um mês antes. A renovação é repetir este passo: novo
pedido, novo certificado, `systemctl reload nginx`.

---

## Verificação final

- [ ] Um posto do domínio copia um PDF para `\\editais\entrada`.
- [ ] Ao fim de um minuto, o rascunho aparece no painel, pelo túnel.
- [ ] O histórico do rascunho diz «Documento recebido e lido» com **o nome AD
      de quem copiou**, e não `editais` nem `sistema`.
- [ ] O `diario/agente.log` tem a linha `RASCUNHO #... (de <nome>)`.
- [ ] Uma pessoa fora do `<GRUPO-AD>` não consegue abrir a partilha.
- [ ] Uma pessoa do grupo não consegue apagar nem alterar um ficheiro que uma
      colega lá pôs (copia um `.zip`, que a vigia ignora, e experimenta com
      outra conta).
- [ ] `curl -sI http://<IP-DA-VM>/slides.json` dá `200`, e não `403`.
- [ ] **A espera pela cópia vê a cópia a correr.** Copia para a partilha um
      `.zip` de algumas centenas de MB (a vigia ignora os `.zip`) e, durante a
      cópia, na VM:
      ```bash
      watch -n1 stat -c '%z %s' '/opt/agente-editais/entrada/<ficheiro>.zip'
      ```
      O `%z` é a hora que o agente lê. Tens de a ver acompanhar o relógio
      enquanto o tamanho cresce. No fim, apaga o `.zip`.
- [ ] Validado e publicado, o edital aparece na televisão sem lhe tocar.
- [ ] A certidão traz a hora certa: a de Lisboa, e não uma hora a menos.
- [ ] Na manhã seguinte há um `estado-*.tar.gz` novo na partilha de cópias.

---

## O que fica para depois

- **Fase 3 — entrar no painel com a conta do Entra.** Os papéis passam a vir de
  grupos do Entra, e fica uma conta local de administrador para quando o Entra
  não responder. Nessa altura o nome de quem valida no painel passa a ser o
  mesmo de quem colocou o documento na partilha. Até lá, o histórico mostra o
  nome do domínio para quem colocou e o nome da conta local do painel para quem
  validou, e podem não coincidir.
