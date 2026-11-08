# RetroPad

Usa o celular como controle para o RetroPie. O Raspberry sobe um servidor na rede local, o celular abre a página no navegador, escolhe Jogador 1 ou 2, e os toques viram um gamepad virtual (uinput) que o EmulationStation e o RetroArch reconhecem como controle USB.

## Plano de ação

1. **Validar o gamepad virtual.** Instalar as dependências, rodar o servidor e confirmar com `ls /dev/input/` e `evtest` que aparece "RetroPad P1".
2. **Validar o controle no RetroArch.** Mapear o RetroPad P1 na porta 1 e testar botões e D-pad.
3. **Validar a página no celular.** Abrir pelo IP do Raspberry, entrar como Jogador 1 e testar multitoque (ex.: direção + A ao mesmo tempo).
4. **Jogador 2.** Abrir a página em um segundo celular, escolher Jogador 2 e mapear a porta 2 no RetroArch.
5. **Endurecer.** Definir PIN (`RETROPAD_PIN`), rodar como serviço systemd e tentar instalar na tela inicial.
6. **Próximos passos (opcionais):** ícones do PWA, vibração no Android, configuração de botões na própria página.

## Estrutura

```
retropad/
├── server.py            # Flask + WebSocket + gamepads virtuais (uinput) + páginas
├── config.py            # caminhos, limites, PINs e ngrok lidos do ambiente
├── roms.py              # listar, validar, gravar, renomear e apagar ROMs
├── api.py               # rotas /api/* do gerenciador (PIN, limite de tentativas, logs)
├── tunnel.py            # túnel ngrok opcional (HTTPS público) e travas de segurança
├── systems.json         # sistemas e extensões aceitas
├── static/
│   ├── index.html       # controle (paisagem, multitoque)
│   ├── admin.html       # gerenciador de ROMs (funciona em retrato)
│   ├── theme.css        # tema (variáveis); troque só este arquivo para mudar o visual
│   ├── admin.css, app.js
│   ├── sw.js, pwa.js    # service worker e botão "Instalar app"
│   ├── manifest.json    # PWA
│   └── icons/
├── scripts/             # integração com o EmulationStation
├── tests/
├── requirements.txt, requirements-dev.txt
├── PLANO_MELHORIAS.md
└── README.md
```

## Instalação no Raspberry

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git

cd ~
git clone https://github.com/GuiVicS/retropad.git retropad
cd ~/retropad

python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### Permissão para o uinput

```bash
sudo modprobe uinput
echo uinput | sudo tee -a /etc/modules-load.d/uinput.conf

echo 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input $USER    # depois faça logout/login
```

Para o primeiro teste, você pode rodar com `sudo` se a permissão falhar.

## Rodando

```bash
RETROPAD_PIN=1234 ./venv/bin/python server.py
```

No celular (mesma Wi-Fi), abra `http://IP_DO_RASPBERRY:8080`. Descubra o IP com `hostname -I`.

Para ver os gamepads criados, em outro terminal: `ls /dev/input/by-id/` ou `sudo evtest`.

## Configurando o RetroArch

1. **Settings → Input → Port 1 Controls**: Device Type "RetroPad P1" (ou "Auto").
2. Para o segundo jogador, faça o mesmo na **Port 2 Controls** com "RetroPad P2".
3. Se o RetroArch não detectar, reinicie o RetroArch depois de abrir a página e escolher o jogador.

Se preferir pelo EmulationStation: **Configurações → Configuração de controles**, pressione os botões quando pedido, com o jogador já conectado.

## Gerenciador de ROMs

Abra `http://IP_DO_RASPBERRY:8080/admin` no celular (funciona em retrato) e entre com o PIN de administrador.

- **Enviar:** escolha um ou mais arquivos. Há barra de progresso, e o servidor grava em blocos de 1 MB (RAM do processo fica em ~40 MB mesmo com 300 MB enviados). A página confere nome, extensão, tamanho e espaço livre antes de enviar, e pede confirmação para sobrescrever.
- **Listar, buscar, renomear e apagar:** com confirmação para apagar. O espaço livre do cartão aparece no topo.
- **Só aparecem** arquivos com extensão aceita pelo sistema (veja `systems.json`), então `gamelist.xml` e pastas de mídia não são listados nem podem ser apagados por aqui.
- Cada sistema é uma subpasta de `RETROPAD_ROMS`. Pastas que não estão em `systems.json` aparecem, mas ficam sem envio até você adicionar as extensões.
- Nomes: espaços, acentos e `()[]` são mantidos (para scrapers reconhecerem a ROM). Separadores de caminho, caracteres de controle e pontos no início são removidos, e o destino é conferido para ficar dentro da pasta do sistema.
- ZIP, 7z, CHD, PBP e ISO têm a assinatura conferida. Arquivos que não batem são recusados.
- Sem rede? O `curl` também funciona: `curl -H "X-Admin-PIN: 1234" -F file=@jogo.sfc http://IP:8080/api/roms/snes`.

### Rotas

| Rota | O que faz |
|---|---|
| `GET /api/status` | espaço livre, limites, URL do túnel |
| `GET /api/systems` | sistemas, contagem e tamanho |
| `GET /api/roms/<sistema>` | ROMs (nome, tamanho, data) |
| `GET /api/check/<sistema>?name=&size=` | valida antes de enviar |
| `POST /api/roms/<sistema>?name=arq.ext[&overwrite=1]` | envia (corpo cru) ou multipart (campo `file`) |
| `POST /api/roms/<sistema>/<arq>/rename` | `{"name": "novo.ext"}` |
| `DELETE /api/roms/<sistema>/<arq>` | apaga |

Todas exigem o cabeçalho `X-Admin-PIN`.

### Variáveis de ambiente

| Variável | Padrão | Função |
|---|---|---|
| `RETROPAD_PIN` | (vazio) | PIN do controle |
| `RETROPAD_ADMIN_PIN` | = `RETROPAD_PIN` | PIN do gerenciador. Sem nenhum PIN, o gerenciador fica desativado |
| `RETROPAD_ROMS` | `~/RetroPie/roms` | pasta de ROMs |
| `RETROPAD_MAX_UPLOAD_MB` | `4096` | limite por arquivo |
| `RETROPAD_MIN_FREE_MB` | `200` | margem que deve sobrar no cartão após o envio |
| `RETROPAD_PIN_ATTEMPTS` / `RETROPAD_PIN_LOCK_SECONDS` | `5` / `60` | bloqueio por IP após PINs errados (controle e admin) |
| `RETROPAD_LOG` | `logs/retropad.log` | log de envios, exclusões e PINs errados (rotaciona em 256 KB x 3) |
| `RETROPAD_SYSTEMS` | `systems.json` | mapa de extensões |
| `RETROPAD_HOST` / `RETROPAD_PORT` | `0.0.0.0` / `8080` | endereço do servidor |
| `RETROPAD_NGROK` | `0` | `1` abre o túnel ngrok |
| `RETROPAD_NGROK_AUTHTOKEN` | | token do ngrok (ou `NGROK_AUTHTOKEN`) |
| `RETROPAD_NGROK_DOMAIN` | | domínio fixo, ex. `meu-retropad.ngrok-free.app` |
| `RETROPAD_NGROK_ADMIN` | `0` | `1` libera `/admin` também pelo túnel |

## PWA e ngrok

O RetroPad é um PWA: tem manifest, ícones, service worker e botão **Instalar app**. Depois de instalado, abre em tela cheia, com ícone próprio, e a "casca" do app abre mesmo sem rede (os botões só funcionam conectados ao Raspberry; `/api` e `/ws` nunca são guardados em cache).

**O service worker só funciona em HTTPS** (ou `localhost`). Pelo IP do Raspberry em `http://`, tudo funciona, mas o navegador não oferece a instalação completa. Para ter HTTPS, o projeto traz o ngrok:

1. Crie uma conta em ngrok.com e copie o authtoken. Na conta gratuita, reserve também um domínio fixo (assim o app instalado não quebra a cada reinício).
2. Defina as variáveis e inicie:

```bash
RETROPAD_PIN=minhasenha1 RETROPAD_ADMIN_PIN=outrasenha2 \
RETROPAD_NGROK=1 RETROPAD_NGROK_AUTHTOKEN=SEU_TOKEN \
RETROPAD_NGROK_DOMAIN=meu-retropad.ngrok-free.app \
./venv/bin/python server.py
```

3. O endereço `https://...` aparece no terminal (e em `logs/tunnel_url.txt`, que o menu do EmulationStation mostra). Abra-o no celular e use **Instalar app** (Android/Chrome) ou Compartilhar → "Adicionar à Tela de Início" (iPhone).

Na primeira execução o `pyngrok` baixa o programa do ngrok, o que exige internet no Raspberry.

> **Segurança.** O túnel coloca o servidor na internet, o que o plano original proibia. Por isso, com `RETROPAD_NGROK=1`: o servidor **não sobe** se `RETROPAD_PIN` tiver menos de 6 caracteres; `/admin` e `/api` ficam **bloqueados pelo túnel** (só rede local) a menos que `RETROPAD_NGROK_ADMIN=1`, e nesse caso exige um `RETROPAD_ADMIN_PIN` diferente e com 6+ caracteres; e o bloqueio de tentativas conta pelo IP real do visitante. Mesmo assim, qualquer pessoa com o endereço e o PIN controla o seu jogo. Use PINs fortes e feche o túnel quando não precisar.
>
> O plano gratuito do ngrok mostra uma página de aviso na primeira visita ao navegador. Ela é ignorada pelo cache do app.

## Integração com o EmulationStation

```bash
./scripts/install-ports.sh            # copia as entradas para ~/RetroPie/roms/ports
```

Isso cria **RetroPad** (status e endereços), **RetroPad Iniciar** e **RetroPad Parar** em *Ports*. Para iniciar e parar sem senha, o script imprime a linha do sudoers; crie com `sudo visudo -f /etc/sudoers.d/retropad`. Reinicie o EmulationStation para as entradas aparecerem. O serviço systemd precisa se chamar `retropad` (ou defina `RETROPAD_SERVICE`).

## Testes

```bash
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python -m pytest -q
```

Cobrem nomes, extensões, path traversal, limite de tamanho, espaço livre, assinaturas, PIN e bloqueio, túnel (com ngrok simulado), manifest e service worker. O que depende do hardware real (uinput, RetroArch, ngrok de verdade, cartão SD) precisa de teste manual no Raspberry.

## Serviço systemd (iniciar com o Raspberry)

Crie `/etc/systemd/system/retropad.service`:

```ini
[Unit]
Description=RetroPad
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/retropad
Environment=RETROPAD_PIN=1234
Environment=RETROPAD_ADMIN_PIN=5678
Environment=RETROPAD_ROMS=/home/pi/RetroPie/roms
# Túnel ngrok (opcional, veja "PWA e ngrok"):
# Environment=RETROPAD_NGROK=1
# Environment=RETROPAD_NGROK_AUTHTOKEN=SEU_TOKEN
# Environment=RETROPAD_NGROK_DOMAIN=meu-retropad.ngrok-free.app
ExecStart=/home/pi/retropad/venv/bin/python server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Ajuste `User` e os caminhos para o seu usuário. Depois:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now retropad
journalctl -u retropad -f
```

## Instalando como app no celular

Veja "PWA e ngrok". Resumo: abra o endereço **https** do túnel e use "Instalar app" (Android) ou Compartilhar → "Adicionar à Tela de Início" (iPhone). Pelo IP em `http://` o app funciona, mas sem a instalação completa.

## Observações

- **Segurança:** o servidor fica aberto na rede local. Use PINs e não faça redirecionamento de porta no roteador. Para acesso de fora, use só o túnel ngrok, com as travas descritas acima.
- **Latência:** WebSocket na mesma Wi-Fi costuma ficar entre 10 e 30 ms. Se houver atraso, use 5 GHz ou cabo no roteador.
- **Orientação:** no modo retrato, a página mostra "gire o celular" e esconde o controle. Isso é feito por CSS, porque o iOS não aceita bloqueio de orientação de forma confiável.
- **Vibração:** não implementada. A API `navigator.vibrate` existe só no Android.
- **Visual:** o tema vem do tweakcn (neo-brutalista, roxo e creme), com modo claro e escuro (botão ☀/☾; sem escolha, segue o sistema). Para trocar, edite `static/theme.css`.
- **Diagnóstico:** se a página conectar mas nada acontecer, veja o log do servidor. Erros de `/dev/uinput` aparecem ali.
