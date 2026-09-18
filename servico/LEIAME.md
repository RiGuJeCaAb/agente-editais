# Correr o agente como serviço

O README descrevia isto em prosa. Aqui ficam os ficheiros, que é o que
efetivamente se instala.

## Linux (systemd) — recomendado

`agente-editais.service` está pronto a copiar. Ajuste `User`, `Group` e os
caminhos, e depois:

```bash
sudo cp servico/agente-editais.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agente-editais
```

A unidade traz restrições de superfície (`ProtectSystem=strict`,
`ReadWritePaths` limitado às pastas de trabalho, sem privilégios novos). Não
mudam o que o agente faz — reduzem o que ele conseguiria fazer se fosse
comprometido, que é o tipo de minimização que o Decreto-Lei n.º 125/2025 (NIS2)
espera de um operador de serviço público.

## Windows

Não há unidade equivalente. Use o **NSSM** (Non-Sucking Service Manager):

```powershell
nssm install AgenteEditais "C:\agente-editais\.venv\Scripts\python.exe" "C:\agente-editais\agente.py --painel"
nssm set AgenteEditais AppDirectory C:\agente-editais
nssm set AgenteEditais AppExit Default Restart
nssm start AgenteEditais
```

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
