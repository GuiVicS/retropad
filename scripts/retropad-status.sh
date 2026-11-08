#!/bin/bash
# Mostra o status e o endereço do RetroPad.
SERVICE="${RETROPAD_SERVICE:-retropad}"
PORT="${RETROPAD_PORT:-8080}"

IP=$(hostname -I | awk '{print $1}')
clear
echo "RetroPad"
if [ -z "$IP" ]; then
  echo "Sem rede: conecte o Raspberry ao Wi-Fi ou ao cabo."
else
  echo "Acesse no celular: http://$IP:$PORT"
  echo "Gerenciar ROMs:    http://$IP:$PORT/admin"
fi
if systemctl is-active --quiet "$SERVICE"; then echo "Status: rodando"; else echo "Status: parado"; fi
echo ""
read -r -p "Pressione ENTER para voltar..."
