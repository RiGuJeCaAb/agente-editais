#!/usr/bin/env bash
# Cópia de segurança do estado do agente de editais, para FORA da máquina.
#
# O que se copia é o que não se refaz: o registo de entrada e as suas gerações,
# o jornal de auditoria, as contas, a configuração, o arquivo imutável dos
# originais, o arquivo dos editais retirados e as pré-visualizações. O código
# volta a buscar-se ao Git; a saida/ refaz-se na publicação seguinte.
#
# Uso (normalmente pelo copia-de-seguranca.timer, todas as noites):
#   sudo DESTINO=/mnt/copias/agente-editais servico/copia-de-seguranca.sh
#
# Variáveis:
#   RAIZ     pasta do agente               (por omissão /opt/agente-editais)
#   DESTINO  pasta de destino, FORA da VM  (por omissão /mnt/copias/agente-editais)
#   DIAS     dias que se guardam do estado (por omissão 60)
#   SERVICO  unidade systemd do agente     (por omissão agente-editais)
set -euo pipefail
shopt -s nullglob

RAIZ=${RAIZ:-/opt/agente-editais}
DESTINO=${DESTINO:-/mnt/copias/agente-editais}
DIAS=${DIAS:-60}
SERVICO=${SERVICO:-agente-editais}

# O destino tem de ter este ficheiro, criado à mão uma vez. Sem ele, se a
# partilha de rede não tiver montado, a cópia ia parar a uma pasta vazia DENTRO
# da VM — e dava-se por feita uma cópia que morre com a máquina.
if [[ ! -f "$DESTINO/.destino-de-copias" ]]; then
    echo "ERRO: $DESTINO/.destino-de-copias não existe. A partilha de cópias" >&2
    echo "      está montada? Se sim, cria o ficheiro uma vez:" >&2
    echo "      sudo touch $DESTINO/.destino-de-copias" >&2
    exit 1
fi

# Confirma-se antes de parar o agente. O Debian mínimo não traz o rsync, e sem
# esta linha a cópia parava o agente, guardava o estado e só rebentava a meio.
for programa in tar rsync; do
    if ! command -v "$programa" >/dev/null; then
        echo "ERRO: falta o $programa (sudo apt install $programa)" >&2
        exit 1
    fi
done

carimbo=$(date +%Y%m%d-%H%M)
parado=0

# O agente volta a arrancar aconteça o que acontecer à cópia: um tar que falhe
# não pode deixar o painel parado até alguém reparar de manhã.
retomar() {
    if [[ $parado -eq 1 ]]; then
        systemctl start "$SERVICO" || echo "ERRO: o $SERVICO não voltou a arrancar" >&2
        parado=0
    fi
}
trap retomar EXIT

# Pára-se o agente durante a cópia. O registo e o jornal de auditoria gravam-se
# em dois passos, e uma cópia apanhada entre os dois guardava-os em desacordo.
# A televisão não dá por isso: quem a serve é o nginx, não o agente.
if systemctl is-active --quiet "$SERVICO"; then
    systemctl stop "$SERVICO"
    parado=1
fi

cd "$RAIZ"
# O config.json junta-se depois da verificação, e só se existir: escrito na
# lista, o nullglob não o tira mesmo que falte (não tem asterisco), e a lista
# nunca ficava vazia — a RAIZ errada passava como cópia de um config.json só.
estado=(registo_entrada.json* registo_auditoria.jsonl* utilizadores.json*)
if [[ ${#estado[@]} -eq 0 ]]; then
    echo "ERRO: não há estado em $RAIZ — a RAIZ está certa?" >&2
    exit 1
fi
[[ -f config.json ]] && estado+=(config.json)
tar -czf "$DESTINO/estado-$carimbo.tar.gz" "${estado[@]}"

# Os arquivos só crescem: copia-se o que é novo, e nunca se apaga no destino o
# que tenha desaparecido na origem. Um arquivo apagado por engano na VM continua
# a existir na cópia.
for pasta in originais arquivo previas; do
    if [[ -d "$RAIZ/$pasta" ]]; then
        mkdir -p "$DESTINO/$pasta"
        rsync -a "$RAIZ/$pasta/" "$DESTINO/$pasta/"
    fi
done

retomar

find "$DESTINO" -maxdepth 1 -name 'estado-*.tar.gz' -mtime +"$DIAS" -delete
echo "cópia feita: $DESTINO/estado-$carimbo.tar.gz"
