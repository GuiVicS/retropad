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
│   ├── theme.css        # tema (variáveis de cor); troque só este arquivo para mudar o visual
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

## Instalação e inicialização automática no Raspberry Pi

Execute os comandos abaixo no terminal do Raspberry Pi. Se o repositório já foi baixado, comece pela etapa 2.

#### Se `apt update` falhar com erro 404 no RetroPie Buster

O Raspberry Pi OS Buster foi arquivado, então o espelho Raspbian original pode não estar mais disponível. **Só no Buster**, aponte o arquivo de fontes para o espelho oficial arquivado, antes de instalar os pacotes:

```bash
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
sudo sed -i 's|raspbian.raspberrypi.org/raspbian|legacy.raspbian.org/raspbian|g' /etc/apt/sources.list
sudo apt update
```

Esse espelho contém pacotes antigos e não recebe atualizações de segurança do Buster. Não use `apt upgrade` como tentativa de atualizar a distribuição; prefira planejar a migração do RetroPie com backup.

### 1. Baixar o projeto

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip python3-dev build-essential
cd ~
git clone https://github.com/GuiVicS/retropad.git
cd ~/retropad
```

### 2. Instalar as dependências Python

O ambiente virtual precisa conter o `pip`; instale os pacotes do sistema e recrie-o antes de instalar os requisitos:

```bash
sudo apt install -y python3-venv python3-pip python3-dev build-essential
cd ~/retropad
python3 -m venv --clear venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt
```

Se sua pasta do projeto não for `~/retropad`, use o caminho onde o clonou nos comandos.

### 3. Habilitar o dispositivo de controle virtual

O RetroPad precisa acessar o dispositivo Linux `uinput`. Configure o módulo e as permissões:

```bash
sudo modprobe uinput
printf 'uinput\n' | sudo tee /etc/modules-load.d/uinput.conf
printf 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"\n' \
  | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG input "$(whoami)"
```

Reinicie o Raspberry Pi para aplicar a associação ao grupo:

```bash
sudo reboot
```

Depois de reconectar pelo terminal, confirme que o dispositivo existe:

```bash
ls -l /dev/uinput
```

### 4. Iniciar e testar manualmente

```bash
cd ~/retropad
RETROPAD_PIN=1234 ./venv/bin/python server.py
```

Deixe esse terminal aberto. Descubra o endereço do Raspberry com `hostname -I`; no celular conectado à mesma rede Wi-Fi, acesse `http://IP_DO_RASPBERRY:8080` e digite o PIN `1234`. Para interromper o servidor, pressione **Ctrl+C**.

Se aparecer `No module named pip` ou `No module named evdev`, repita a etapa 2. Se aparecer erro de permissão em `/dev/uinput`, confirme que reiniciou após entrar no grupo `input` e verifique `ls -l /dev/uinput`.

### 5. Configurar a inicialização automática

Primeiro, confirme o nome do usuário e o caminho da pasta pessoal:

```bash
whoami
echo "$HOME"
```

Crie um arquivo para os PINs e limite o acesso a ele:

```bash
sudo nano /etc/retropad.env
```

Adicione as linhas abaixo, trocando os PINs de exemplo por valores próprios:

```ini
RETROPAD_PIN=troque-por-um-pin
RETROPAD_ADMIN_PIN=troque-por-outro-pin
```

`RETROPAD_ADMIN_PIN` protege o gerenciador de ROMs em `/admin`. Se omitido, ele usa o mesmo PIN do controle. Salve no `nano` com **Ctrl+O**, **Enter** e saia com **Ctrl+X**. Depois proteja o arquivo:

```bash
sudo chown root:root /etc/retropad.env
sudo chmod 600 /etc/retropad.env
```

Crie o serviço:

```bash
sudo nano /etc/systemd/system/retropad.service
```

Cole o conteúdo a seguir. Se `whoami` ou `echo "$HOME"` mostrou valores diferentes de `pi` e `/home/pi`, ajuste `User`, `WorkingDirectory` e `ExecStart` para os valores reais. Por exemplo, para o usuário `joao`, substitua `/home/pi` por `/home/joao`.

```ini
[Unit]
Description=RetroPad
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/retropad
EnvironmentFile=/etc/retropad.env
ExecStart=/home/pi/retropad/venv/bin/python server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Salve e ative o serviço para iniciar agora e também a cada inicialização do Raspberry:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now retropad
sudo systemctl status retropad
```

Para acompanhar os logs:

```bash
sudo journalctl -u retropad -f
```

Agora o celular pode acessar `http://IP_DO_RASPBERRY:8080` mesmo sem abrir uma sessão de terminal. Para parar, iniciar ou reiniciar o serviço:

```bash
sudo systemctl stop retropad
sudo systemctl start retropad
sudo systemctl restart retropad
```

`systemctl status retropad` mostra se o serviço está ativo. Para verificar o endereço do Raspberry, rode `hostname -I`.

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
./venv/bin/python -m pip install -r requirements-dev.txt
./venv/bin/python -m pytest -q
```

Cobrem nomes, extensões, path traversal, limite de tamanho, espaço livre, assinaturas, PIN e bloqueio, túnel (com ngrok simulado), manifest e service worker. O que depende do hardware real (uinput, RetroArch, ngrok de verdade, cartão SD) precisa de teste manual no Raspberry.

## Serviço systemd

Para instalar e configurar o serviço para iniciar junto com o Raspberry, siga a [etapa de inicialização automática](#5-configurar-a-inicialização-automática) do guia de instalação acima.

## Modos: Gamepad, Mouse e Tela

Na tela inicial escolha o modo:

- **Gamepad:** um único controle universal (serve para qualquer console): L1/L2, R1/R2, dois analógicos com L3/R3, D-pad, SELECT/START e ABXY. Um controle virtual por jogador (Jogador 1 e 2). O mapeamento é de gamepad Xbox 360, então o RetroArch reconhece sozinho.
- **Mouse:** a tela inteira vira um touchpad pontilhado. Arraste para mover, toque para clicar, toque com dois dedos para o clique direito, arraste com dois dedos para rolar. Toque e logo em seguida arraste para segurar o botão (arrastar janelas, selecionar texto). O botão flutuante de teclado abre o **teclado nativo do celular**: o que você digita aparece no PC. Junto vem uma folha com as teclas que o celular não tem: Esc, Tab, Home, End, PgUp, PgDn, Ins, Win, Ctrl, Alt, Shift, setas e, pelo botão **Fn**, F1 a F12. Ctrl, Alt, Shift e Win valem para a próxima tecla ou letra (ex.: toque em Ctrl e digite `c`).
- **Tela:** o mesmo touchpad, já mostrando a tela do Raspberry (veja abaixo).

**Mouse e Tela conectam com um toque**, sem escolher jogador (eles não usam vaga de jogador). Só o Gamepad pergunta se você é o Jogador 1 ou 2, e destaca o último que você usou.

### Configurações (salvas no aparelho)

O botão **Configurações** (na tela inicial e no menu da engrenagem) guarda no **IndexedDB** do navegador: tema (Auto, Claro ou Escuro), último modo e jogador, tela do sistema ligada, vibração ao tocar e velocidade do mouse. O gerenciador de ROMs usa o mesmo tema. O PIN nunca é salvo.

**Limpar IndexedDB** apaga tudo isso e volta aos padrões (pede um segundo toque para confirmar). Se o navegador bloquear o IndexedDB (alguns modos privados), o app continua funcionando, só não lembra as preferências. Os dados ficam em `static/settings.js` (`RPConfig`).

A engrenagem (canto superior direito) abre o menu: ligar/desligar a tela do sistema, abrir as Configurações e sair.

Mouse e teclado viram dispositivos virtuais (`RetroPad Mouse` e `RetroPad Teclado`) via uinput, então funcionam em qualquer programa do Raspberry. **Limitação:** o texto é convertido para teclas do layout US. Caracteres que dependem do layout do PC (como `ç`, `ã`, `é`) são ignorados em vez de digitar a tecla errada. Letras, números e símbolos como `! ? @ #` funcionam normalmente.

## Tela do sistema (streaming)

No modo **Tela** (ou pelo menu da engrenagem em qualquer modo) o celular mostra a tela do Raspberry em tempo real. No Gamepad a imagem fica atrás dos botões (que ficam translúcidos); no Mouse ela aparece dentro do touchpad, então dá para controlar o PC olhando só o celular.

Como funciona: o `ffmpeg` captura a tela, reduz e manda JPEGs pelo mesmo WebSocket do controle (mesmo PIN, mesmo túnel). **O ffmpeg só roda enquanto alguém assiste** e para quando o último celular sai, então não gasta CPU à toa.

Requisitos: `sudo apt install ffmpeg`. A fonte é detectada sozinha: `x11grab` se houver `DISPLAY` (desktop/X) e `fbdev` (`/dev/fb0`) caso contrário. Variáveis (todas opcionais):

| Variável | Padrão | O que faz |
|---|---|---|
| `RETROPAD_STREAM` | `1` | `0` desliga a transmissão |
| `RETROPAD_STREAM_FPS` | `12` | quadros por segundo (1 a 30) |
| `RETROPAD_STREAM_WIDTH` | `854` | largura enviada, altura proporcional (160 a 1920) |
| `RETROPAD_STREAM_QUALITY` | `6` | JPEG: 2 (melhor) a 31 (pior) |
| `RETROPAD_STREAM_INPUT` | vazio | opções de entrada do ffmpeg para trocar a detecção, ex.: `-f x11grab -framerate 12 -i :0` |
| `RETROPAD_STREAM_FILTER` | vazio | filtro aplicado antes de reduzir, ex.: `hwdownload,format=bgr0` |

No Raspberry Pi, o RetroArch com driver KMS/DRM nem sempre aparece no `/dev/fb0` (a imagem sai preta). Nesse caso tente captura por KMS, que costuma exigir rodar o servidor como root: `RETROPAD_STREAM_INPUT="-f kmsgrab -i -"` com `RETROPAD_STREAM_FILTER="hwdownload,format=bgr0"`. Essa combinação depende do modelo do Pi e do driver; teste no seu aparelho.

**Atenção à privacidade:** quem tem o PIN do controle também vê a tela. Defina `RETROPAD_PIN` e não exponha o servidor na internet sem o túnel com PIN. Reduza `RETROPAD_STREAM_FPS`/`WIDTH` se o Pi sentir o peso (a codificação usa CPU).

## Instalando como app no celular

Veja "PWA e ngrok". Resumo: abra o endereço **https** do túnel e use "Instalar app" (Android) ou Compartilhar → "Adicionar à Tela de Início" (iPhone). Pelo IP em `http://` o app funciona, mas sem a instalação completa.

## Observações

- **Segurança:** o servidor fica aberto na rede local. Use PINs e não faça redirecionamento de porta no roteador. Para acesso de fora, use só o túnel ngrok, com as travas descritas acima.
- **Latência:** WebSocket na mesma Wi-Fi costuma ficar entre 10 e 30 ms. Se houver atraso, use 5 GHz ou cabo no roteador.
- **Orientação:** no modo Gamepad e em retrato, a página mostra "gire o celular" e esconde o controle (Mouse e Tela funcionam nos dois sentidos). Isso é feito por CSS, porque o iOS não aceita bloqueio de orientação de forma confiável.
- **Ícones:** são do [Lucide](https://lucide.dev) (licença ISC), em um sprite local `static/lucide.svg`, sem CDN, então funcionam offline.
- **Vibração:** os botões vibram de leve no Android (`navigator.vibrate`); o iOS não tem essa API.
- **Visual:** um tema só para o app inteiro (controle e gerenciador de ROMs): pêssego no claro e chocolate no escuro, com botões em relevo e fundo pontilhado. Sem escolha salva, segue o tema do sistema. Para trocar as cores, edite as variáveis de `static/theme.css`.
- **Diagnóstico:** se a página conectar mas nada acontecer, veja o log do servidor. Erros de `/dev/uinput` aparecem ali.
