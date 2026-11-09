#!/bin/bash
# Descobre qual método de captura de tela funciona NESTE Raspberry.
#
# RODE COM O EMULATIONSTATION (ou um jogo) ABERTO NA TV. Se rodar com a tela no terminal, todos os
# métodos mostram "preto" ou só o texto do console.
#
# Uso:   bash scripts/diagnose-screen.sh
#
# Para cada método, captura 1 quadro e mede o brilho médio (0 = preto, 255 = branco).
# Um método "funciona" se o brilho for maior que 3 e o quadro tiver cor/variação.

FPS=12
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
OK_LINES=()

say() { printf '%s\n' "$*"; }
hr()  { say "------------------------------------------------------------"; }

hr
say "RetroPad: diagnóstico de captura de tela"
hr
MODEL=desconhecido; [ -r /proc/device-tree/model ] && MODEL=$(tr -d '\0' </proc/device-tree/model)
say "Modelo:   $MODEL"
say "Sistema:  $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?}") | kernel $(uname -r)"
say "Usuário:  $(id -un) (uid $(id -u))"
if command -v ffmpeg >/dev/null; then
  say "ffmpeg:   $(ffmpeg -hide_banner -version 2>/dev/null | head -1)"
else
  say "ffmpeg:   NÃO INSTALADO  ->  sudo apt install -y ffmpeg"; exit 1
fi
say "Telas:    DISPLAY='${DISPLAY:-}'  fb0=$([ -e /dev/fb0 ] && echo sim || echo não)  dri=$(ls /dev/dri 2>/dev/null | tr '\n' ' ')"
[ -e /sys/class/graphics/fb0/virtual_size ] && say "fb0:      $(cat /sys/class/graphics/fb0/virtual_size) ($(cat /sys/class/graphics/fb0/bits_per_pixel) bpp)"
if [ -r /boot/config.txt ]; then
  say "config:   $(grep -E '^(dtoverlay=vc4|dtoverlay=.*kms|gpu_mem)' /boot/config.txt | tr '\n' ' ')"
fi
if command -v tvservice >/dev/null; then say "HDMI:     $(tvservice -s 2>/dev/null)"; fi
say "Dispositivos de captura do ffmpeg: $(ffmpeg -hide_banner -devices 2>/dev/null | grep -oE 'x11grab|kmsgrab|fbdev' | sort -u | tr '\n' ' ')"
hr

# Mede o brilho médio (YAVG) do primeiro quadro. Argumentos: opções de entrada do ffmpeg, depois o filtro inicial.
measure() {
  local filter="$1"; shift
  local vf="signalstats,metadata=print:key=lavfi.signalstats.YAVG"
  [ -n "$filter" ] && vf="$filter,$vf"
  timeout 20 ffmpeg -hide_banner -nostdin -loglevel info "$@" -frames:v 1 -vf "$vf" -f null - 2>&1
}
yavg() { grep -oE 'YAVG=[0-9.]+' | head -1 | cut -d= -f2; }

report() {   # nome, resultado do measure, linhas de config se funcionar
  local name="$1" out="$2" cfg="$3" y
  y=$(printf '%s' "$out" | yavg)
  if [ -z "$y" ]; then
    local why; why=$(printf '%s' "$out" | grep -iE 'error|cannot|failed|permission|denied|no such|not found|unknown' | head -1 | cut -c1-110)
    printf '  %-10s  FALHOU  %s\n' "$name" "${why:-sem detalhes}"
  elif awk "BEGIN{exit !($y > 3)}"; then
    printf '  %-10s  FUNCIONA  (brilho médio %.1f)\n' "$name" "$y"
    OK_LINES+=("$name|$cfg")
  else
    printf '  %-10s  tela PRETA  (brilho %.1f; não mostra o que está na TV)\n' "$name" "$y"
  fi
}

say "Testando (1 quadro de cada, com a tela atual da TV):"

if [ -n "$DISPLAY" ]; then
  report "x11grab" "$(measure "" -f x11grab -framerate $FPS -i "$DISPLAY")" "(automático, nada a configurar)"
fi
if [ -e /dev/fb0 ]; then
  report "fbdev" "$(measure "" -f fbdev -framerate $FPS -i /dev/fb0)" "(automático, nada a configurar)"
fi
if [ -e /dev/dri/card0 ] && ffmpeg -hide_banner -devices 2>/dev/null | grep -q kmsgrab; then
  KMS_IN="-device /dev/dri/card0 -f kmsgrab -framerate $FPS -i -"
  CFG="RETROPAD_STREAM_INPUT=\"$KMS_IN\"
RETROPAD_STREAM_FILTER=\"hwdownload,format=bgr0\"
(e no serviço: AmbientCapabilities=CAP_SYS_ADMIN, ou rodar como root)"
  if [ "$(id -u)" -eq 0 ]; then
    # shellcheck disable=SC2086
    report "kmsgrab" "$(measure "hwdownload,format=bgr0" $KMS_IN)" "$CFG"
  elif sudo -n true 2>/dev/null; then
    # shellcheck disable=SC2086
    report "kmsgrab" "$(sudo -n bash -c "$(declare -f measure); measure 'hwdownload,format=bgr0' $KMS_IN")" "$CFG"
  else
    printf '  %-10s  não testado (precisa de root: rode  sudo bash scripts/diagnose-screen.sh)\n' "kmsgrab"
  fi
fi
if command -v raspi2png >/dev/null; then
  if timeout 15 raspi2png -p "$TMP/snap.png" >/dev/null 2>&1 && [ -s "$TMP/snap.png" ]; then
    report "raspi2png" "$(measure "" -i "$TMP/snap.png")" "(automático: com o raspi2png instalado o RetroPad já usa esta captura)"
  else
    printf '  %-10s  FALHOU  (raspi2png existe mas não gerou imagem)\n' "raspi2png"
  fi
else
  printf '  %-10s  não instalado (é ele que mostra o EmulationStation nos Pi 0 a 3; veja o README)\n' "raspi2png"
fi

hr
if [ ${#OK_LINES[@]} -eq 0 ]; then
  say "Nenhum método mostrou a tela. Me mande TODA esta saída (em especial o modelo do Pi e as linhas acima)."
else
  say "Métodos que enxergam a tela da TV:"
  for l in "${OK_LINES[@]}"; do
    say "  * ${l%%|*}"
    [ -n "${l#*|}" ] && printf '%s\n' "${l#*|}" | sed 's/^/      /'
  done
  say ""
  say "Coloque as linhas RETROPAD_* (se houver) em /etc/retropad.env e rode:  sudo systemctl restart retropad"
fi
hr
