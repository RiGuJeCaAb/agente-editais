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

# Com os segundos: duas cópias no mesmo minuto, uma à mão e outra do timer,
# escreviam no mesmo nome, e a segunda podia apagar a primeira a meio.
carimbo=$(date +%Y%m%d-%H%M%S)
final="$DESTINO/estado-$carimbo.tar.gz"
parcial="$DESTINO/.estado-$carimbo.tar.gz.parcial"
parado=0

# O agente volta a arrancar aconteça o que acontecer à cópia: um tar que falhe
# não pode deixar o painel parado até alguém reparar de manhã.
#
# O --no-block é por causa do Before= da copia-de-seguranca.service: o arranque
# do agente espera que esta unidade acabe, e um start que bloqueasse aqui
# dentro ficava à espera de si próprio. Assim o arranque fica pedido e acontece
# quando a cópia termina. Corrido à mão, fora do systemd, arranca logo.
retomar() {
    if [[ $parado -eq 1 ]]; then
        systemctl start --no-block "$SERVICO" \
            || echo "ERRO: o $SERVICO não voltou a arrancar" >&2
        parado=0
    fi
}
# Um arquivo a meio, de uma cópia que falhou, não fica com cara de cópia boa.
limpar() {
    rm -f "$parcial"
    retomar
}
trap limpar EXIT

# Pára-se o agente durante a cópia. O registo e o jornal de auditoria gravam-se
# em dois passos, e uma cópia apanhada entre os dois guardava-os em desacordo.
# A televisão não dá por isso: quem a serve é o nginx, não o agente.
if systemctl is-active --quiet "$SERVICO"; then
    systemctl stop "$SERVICO"
    parado=1
fi

cd "$RAIZ"
# O registo de entrada é o que tem de lá estar. Um jornal ou um ficheiro de
# contas sozinhos passavam por cópia feita, e repor essa cópia dava um posto
# sem um único edital — numa RAIZ errada, ou num estado já estragado.
if [[ ! -s registo_entrada.json ]]; then
    echo "ERRO: não há registo_entrada.json em $RAIZ — a RAIZ está certa?" >&2
    exit 1
fi
estado=(registo_entrada.json* registo_auditoria.jsonl* utilizadores.json*)
[[ -f config.json ]] && estado+=(config.json)
tar -czf "$parcial" "${estado[@]}"

# Os arquivos só crescem: copia-se o que é novo, e nunca se apaga no destino o
# que tenha desaparecido na origem. Um arquivo apagado por engano na VM continua
# a existir na cópia.
#
# -rt e não -a: o destino é uma partilha Windows montada por CIFS, onde o dono,
# o grupo e as permissões POSIX não se guardam, e o -a, que tenta mudá-los,
# pode fazer falhar a cópia. Na reposição o chown -R volta a pô-los.
for pasta in originais arquivo previas; do
    if [[ -d "$RAIZ/$pasta" ]]; then
        mkdir -p "$DESTINO/$pasta"
        rsync -rt "$RAIZ/$pasta/" "$DESTINO/$pasta/"
    fi
done

# Só aqui, com tudo copiado, o arquivo do estado ganha o nome definitivo.
mv "$parcial" "$final"

retomar

find "$DESTINO" -maxdepth 1 -name 'estado-*.tar.gz' -mtime +"$DIAS" -delete
echo "cópia feita: $final"
