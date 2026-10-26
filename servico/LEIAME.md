# Correr o agente como serviço

O README descrevia isto em prosa. Aqui ficam os ficheiros, que é o que
efetivamente se instala.

`LISTA-DE-VERIFICACAO.md` é a instalação toda por passos, para levar ao posto:
da máquina à televisão, com o que tens de ver a cada passo para saber que
correu bem.

`HYPER-V.md` é a mesma coisa para uma VM Debian no Hyper-V da Câmara, membro do
domínio: a pasta de entrada partilhada na rede, o registo de quem colocou cada
documento, a televisão servida por nginx e as cópias de segurança para fora da
VM. Inclui a migração do estado de um posto Windows.

| Ficheiro | Para quê |
|---|---|
| `agente-editais.service` | o agente como serviço systemd |
| `nginx-editais.conf` | a televisão: a pasta `saida/` como site estático |
| `smb.conf.exemplo` | a partilha `entrada`, com a VM membro do AD |
| `copia-de-seguranca.sh` | a cópia do estado para fora da máquina |
| `copia-de-seguranca.service`, `.timer` | a mesma cópia, todas as noites |

## Linux (systemd) — recomendado

`agente-editais.service` está pronto a copiar. Ajuste `User`, `Group` e os
caminhos, e depois:

```bash
sudo cp servico/agente-editais.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agente-editais
```

A unidade traz restrições de superfície (`ProtectSystem=strict`,
`ReadWritePaths` limitado ao que o agente escreve, sem privilégios novos). Não
mudam o que o agente faz — reduzem o que ele conseguiria fazer se fosse
comprometido, que é o tipo de minimização que o Decreto-Lei n.º 125/2025 (NIS2)
espera de um operador de serviço público.

## Windows

Não há unidade equivalente. Use o **NSSM** (Non-Sucking Service Manager):

```powershell
nssm install AgenteEditais "C:\agente-editais\.venv\Scripts\python.exe" "C:\agente-editais\agente.py --painel"
nssm set AgenteEditais AppDirectory C:\agente-editais
nssm set AgenteEditais AppExit Default Restart
nssm set AgenteEditais AppStopMethodConsole 240000
nssm start AgenteEditais
```

O `AppStopMethodConsole` é o tempo, em milissegundos, que o NSSM espera depois
do Ctrl+C antes de passar a métodos mais bruscos. Por omissão é 1500, e o
agente, que acaba o documento em curso antes de sair, era morto a meio dele.
Os 240000 são os mesmos quatro minutos que o agente se dá a si próprio.

O registo técnico fica em `diario/agente.log` de qualquer forma, com rotação
própria — não depende de o serviço redirecionar a consola.

## Verificar que está vivo

```bash
curl -s http://127.0.0.1:8770/saude | python3 -m json.tool
```

Devolve `"ok": true` quando a vigia correu há pouco e há espaço em disco. É a
única rota sem sessão, e por isso só devolve números e instantes — nunca o
conteúdo de editais por validar.

Para vigiar a sério, aponte o supervisor (Nagios, Zabbix, uptime-kuma) a esse
endereço e alerte quando `ok` for `false` ou a resposta não chegar.

## A raiz do projeto tem de estar escrivível

O `ReadWritePaths` inclui a **raiz**, e não incluía — era um defeito. O
`registo_entrada.json`, o `utilizadores.json` e o `registo_auditoria.jsonl`
vivem ali, e a gravação atómica cria o temporário na mesma pasta do destino,
porque `os.replace` só é atómico dentro do mesmo sistema de ficheiros.

Sem isso o serviço **arrancava e não gravava nada**: o `/saude` respondia, o
painel abria, e nem uma conta nem um edital chegavam ao disco. É a pior forma de
uma falha se apresentar — parece que está a funcionar.

**Se quiseres apertar mais**, o caminho é tirar o estado de dentro da pasta do
código. A documentação do systemd diz que o `StateDirectory=` exclui a pasta do
efeito do `ProtectSystem=`, e o `config.json` sobrepõe qualquer caminho, por
isso dá para apontar `registo_entrada` e `utilizadores` para
`/var/lib/agente-editais` sem tocar no código. Não vem assim de origem por uma
razão só: mudar onde o estado vive faz uma instalação existente deixar de
encontrar o registo dela, e isso perde-se uma vez só.
