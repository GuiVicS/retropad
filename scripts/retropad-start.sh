#!/bin/bash
# Inicia o servidor RetroPad (serviço systemd) e mostra o endereço.
# Requer a regra do sudoers descrita no README (seção "Integração com o EmulationStation").
SERVICE="${RETROPAD_SERVICE:-retropad}"
PORT="${RETROPAD_PORT:-8080}"

sudo -n systemctl start "$SERVICE" || { echo "Falhou ao iniciar. A regra do sudoers está instalada?"; exit 1; }
sleep 1
IP=$(hostname -I | awk '{print $1}')
clear
echo "RetroPad"
if systemctl is-active --quiet "$SERVICE"; then
  echo "Status: rodando"
  echo "Controle:  http://$IP:$PORT"
  echo "ROMs:      http://$IP:$PORT/admin"
else
  echo "Status: parado (veja: journalctl -u $SERVICE -n 20)"
fi
echo ""
read -r -p "Pressione ENTER para voltar..."
