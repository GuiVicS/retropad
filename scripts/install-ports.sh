#!/bin/bash
# Instala as entradas "RetroPad" na lista Ports do EmulationStation e imprime a regra do sudoers.
# Uso: ./scripts/install-ports.sh [pasta_de_roms]   (padrão: ~/RetroPie/roms)
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROMS="${1:-${RETROPAD_ROMS:-$HOME/RetroPie/roms}}"
PORTS="$ROMS/ports"
USER_NAME="$(id -un)"

if [ ! -d "$ROMS" ]; then
  echo "Pasta de ROMs não encontrada: $ROMS"
  echo "Informe o caminho: $0 /caminho/para/roms"
  exit 1
fi

chmod +x "$DIR"/scripts/retropad-*.sh
mkdir -p "$PORTS"
for f in "$DIR"/scripts/ports/*.sh; do
  dest="$PORTS/$(basename "$f")"
  sed "s|__RETROPAD_DIR__|$DIR|g" "$f" > "$dest"
  chmod +x "$dest"
  echo "Instalado: $dest"
done

SYSTEMCTL="$(command -v systemctl || echo /bin/systemctl)"
echo ""
echo "Para iniciar/parar sem pedir senha, crie a regra abaixo com:"
echo "  sudo visudo -f /etc/sudoers.d/retropad"
echo ""
echo "  $USER_NAME ALL=(root) NOPASSWD: $SYSTEMCTL start retropad, $SYSTEMCTL stop retropad, $SYSTEMCTL restart retropad"
echo ""
echo "Depois reinicie o EmulationStation (ou Menu > Configurações > Atualizar lista de jogos)."
echo ""
echo "Executando instalador automático do RetroPie..."
bash "$DIR/scripts/install-retropie.sh"
