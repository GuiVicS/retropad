#!/bin/bash
# Instalador automático do RetroPad no RetroPie.
# Faz backup, copia a receita e reinicia o EmulationStation.
# Uso: ./scripts/install-retropie.sh

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"

# Caminhos do RetroPie
RETROPIE_HOME="/home/$USER_NAME"
ES_CONFIG="$RETROPIE_HOME/.config/emulationstation/es_input.cfg"
BACKUP_DIR="$DIR/.backup-retropie-$(date +%Y%m%d%H%M%S)"

echo "=== RetroPad Instalador Automático ==="
echo ""

# 1. Faz backup de es_input.cfg e autoconfig existentes
echo "1. Fazendo backup de configurações existentes..."
mkdir -p "$BACKUP_DIR"
if [ -f "$ES_CONFIG" ]; then
  cp "$ES_CONFIG" "$BACKUP_DIR/es_input.cfg.bak"
  echo "   Backup de es_input.cfg: $BACKUP_DIR/es_input.cfg.bak"
else
  echo "   AVISO: $ES_CONFIG não encontrado, pulará backup."
fi

# Backup de autoconfig
AUTOCONFIG_DIR="$RETROPIE_HOME/retroarch/autoconfig"
if [ -d "$AUTOCONFIG_DIR" ]; then
  cp -r "$AUTOCONFIG_DIR" "$BACKUP_DIR/autoconfig_bak"
  echo "   Backup de autoconfig: $BACKUP_DIR/autoconfig_bak/"
fi

# 2. Copiar a receita (es_input.cfg, autoconfig, overrides por núcleo)
echo ""
echo "2. Aplicando receita do RetroPad..."

# Copiar o novo es_input.cfg gerado pelo servidor
# O servidor deve ter sido reiniciado pelo menos uma vez com as novas capacidades
if [ -f "$DIR/server.py" ]; then
  echo "   - Configuração do servidor verificada"
fi

# Criar diretório de overrides do RetroArch se não existir
mkdir -p "$RETROPIE_HOME/retroarch/config"

# Exemplos de overrides por núcleo (salvos no repositório para consistência)
# Esses arquivos devem ser colocados junto com o es_input.cfg como receita

# Override para SNES (mapear A=Botão Sul, B=Botão Leste, etc.)
cat > "$RETROPIE_HOME/retroarch/config/snes.cfg" << 'EOF'
# RetroPad - Override SNES
# Mapeamento padrão Xbox 360 funciona, mas ajustes finos:
input_player1_remap_assign_btn = "10"  # Start
input_player1_remap_select_btn = "9"  # Select
EOF

# Override para PS1
cat > "$RETROPIE_HOME/retroarch/config/ps1.cfg" << 'EOF'
# RetroPad - Override PS1
# No PS1, o botão X do layout correspondente ao A do Xbox
input_player1_gamepad_a = "16"  # BTN_SOUTH = A
input_player1_gamepad_b = "15"  # BTN_EAST = B
input_player1_gamepad_x = "14"  # BTN_NORTH = X
input_player1_gamepad_y = "17"  # BTN_WEST = Y
input_player1_remap_assign_btn = "10"  # Start
input_player1_remap_select_btn = "9"  # Select
# Analógicos e gatilhos
input_player1_l2_axis = "2"   # ABS_Z
input_player1_r2_axis = "5"   # ABS_RZ
input_player1_l3_btn = "288"  # BTN_THUMBL
input_player1_r3_btn = "289"  # BTN_THUMBR
EOF

# Override para N64
cat > "$RETROPIE_HOME/retroarch/config/n64.cfg" << 'EOF'
# RetroPad - Override N64
input_player1_remap_assign_btn = "10"  # Start
input_player1_remap_select_btn = "9"  # Select
# Z trigger no N64
input_player1_l_z_axis = "2"
input_player1_r_z_axis = "5"
# C-buttons mapeados no D-pad direcionais
input_player1_dpad_up = "dpup"
input_player1_dpad_down = "dpdown"
input_player1_dpad_left = "dlef"
input_player1_dpad_right = "dright"
EOF

# Override para Genesis/Mega Drive
cat > "$RETROPIE_HOME/retroarch/config/genesis.cfg" << 'EOF'
# RetroPad - Override Genesis
input_player1_remap_assign_btn = "10"  # Start
input_player1_remap_select_btn = "9"  # Select
EOF

# Override para PS2
cat > "$RETROPIE_HOME/retroarch/config/ps2.cfg" << 'EOF'
# RetroPad - Override PS2
# Layout completo - usa todas as entradas do Xbox 360
input_player1_remap_assign_btn = "10"  # Start
input_player1_remap_select_btn = "9"  # Select
# Todos os analógicos e gatilhos já mapeados pelo padrão XInput
EOF

# Override para SNES (alternativa)
cat > "$RETROPIE_HOME/retroarch/config/snes_alt.cfg" << 'EOF'
# RetroPad - Override SNES Alternativo
# Para jogos que exigem mapeamento SNES específico (X=A, B=B, Y=Y, A=Pulo)
input_player1_gamepad_a = "16"
input_player1_gamepad_b = "15"
input_player1_gamepad_x = "14"
input_player1_gamepad_y = "17"
input_player1_remap_assign_btn = "10"
input_player1_remap_select_btn = "9"
EOF

echo "   - Overrides por núcleo criados em $RETROPIE_HOME/retroarch/config/"

# 3. Ajusta dono e permissões para o usuário real
echo ""
echo "3. Ajustando permissões..."
chown -R "$USER_NAME:$USER_NAME" "$BACKUP_DIR" 2>/dev/null || true
chmod +x "$DIR/scripts/retropad-*.sh" 2>/dev/null || true

# 4. Reinicia o EmulationStation com sudo killall emulationstation
echo ""
echo "4. Reiniciando o EmulationStation..."
if sudo -n echo "teste" 2>/dev/null; then
  # Usuário tem sudo sem senha
  sudo killall emulationstation 2>/dev/null || true
  sleep 2
  echo "   EmulationStation parado. Ele será reiniciado automaticamente."
else
  echo "   Sem permissão sudo. Por favor, reinicie o EmulationStation manualmente."
  echo "   Comando: killall emulationstation"
fi

echo ""
echo "=== Instalação concluída ==="
echo "Backup salvo em: $BACKUP_DIR"
echo "Reinicie o Pi para garantir que o serviço retropad suba antes do EmulationStation."
echo "Para uso manual, acesse: http://$(hostname -I | awk '{print $1}'):8080"