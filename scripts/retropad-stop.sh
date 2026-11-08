#!/bin/bash
# Para o servidor RetroPad (serviço systemd).
SERVICE="${RETROPAD_SERVICE:-retropad}"

sudo -n systemctl stop "$SERVICE" || { echo "Falhou ao parar. A regra do sudoers está instalada?"; exit 1; }
clear
echo "RetroPad"
if systemctl is-active --quiet "$SERVICE"; then echo "Status: ainda rodando"; else echo "Status: parado"; fi
echo ""
read -r -p "Pressione ENTER para voltar..."
