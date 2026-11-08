# Plano de melhorias do RetroPad

Este documento é o guia para evoluir o projeto. Use-o como contexto no Claude Code, rodando dentro da pasta `retropad/`.

## 1. Objetivos

1. **Gerenciador de ROMs pela web:** enviar, listar e apagar ROMs direto pelo navegador, sem tirar o cartão SD.
2. **Leveza:** tudo roda no Raspberry Pi (3, 4 ou Zero 2 W) sem banco de dados, sem build de frontend e sem dependências pesadas.
3. **Integração com o EmulationStation:** o usuário consegue iniciar, parar e ver o status do RetroPad a partir do menu do RetroPie.
4. **Visual:** o estilo será definido depois, a partir de referências que o usuário vai fornecer. Este plano só reserva o lugar para isso.

## 2. Restrições técnicas

- **Raspberry:** 512 MB a 4 GB de RAM, SD card lento. Evitar escrita desnecessária e processos em segundo plano.
- **Python:** manter Flask e flask-sock. Não adicionar React, Node, bancos de dados ou Celery.
- **Frontend:** HTML, CSS e JavaScript puros, sem bundler. Cada página ideal abaixo de 50 KB sem imagens.
- **Sem thumbnails automáticos:** gerar capas pesa no Pi. Se precisar, fazer sob demanda e guardar em cache.
- **Uploads grandes:** ROMs de PS1, Dreamcast ou PSP podem ter centenas de MB. O upload precisa ser gravado em disco em partes, não carregado na memória.
- **Rede local:** o servidor continua só para a LAN, protegido por PIN.

## 3. Fases

### Fase 1: Base do gerenciador de ROMs

Objetivo: listar sistemas e enviar ROMs para a pasta certa.

- Detectar a pasta de ROMs do RetroPie (padrão `~/RetroPie/roms`) e tornar o caminho configurável por variável de ambiente `RETROPAD_ROMS`.
- Listar sistemas como subpastas, mostrando quantidade de arquivos e tamanho total.
- Mapa de extensões aceitas por sistema (ex.: `snes` aceita `.sfc`, `.smc`, `.zip`; `psx` aceita `.cue`, `.bin`, `.chd`, `.iso`, `.pbp`). Manter em um arquivo `systems.json` simples.
- Rota `POST /api/roms/<sistema>` que recebe o arquivo em multipart e grava em streaming.
- Usar `werkzeug.utils.secure_filename` e confirmar que o destino fica dentro da pasta do sistema, para evitar path traversal.
- Limite de tamanho por upload definido em `MAX_CONTENT_LENGTH` (configurável).
- Não sobrescrever arquivo existente sem confirmação explícita (`?overwrite=1`).
- Antes de gravar, checar espaço livre com `shutil.disk_usage` e recusar se não houver margem.

**Critério de aceite:** enviar um arquivo de 300 MB de um celular na mesma Wi-Fi, ver a barra de progresso chegar a 100% e o arquivo aparecer na pasta certa, com o Pi sem travar.

### Fase 2: Gerenciamento completo

- Listar ROMs de um sistema com nome, tamanho e data.
- Apagar ROM com confirmação na tela.
- Renomear ROM (opcional).
- Mostrar espaço livre do cartão SD no topo da página.
- Filtro e busca simples por nome no navegador, sem recarregar o servidor.

**Critério de aceite:** apagar uma ROM pela página e confirmar que ela sumiu da pasta.

### Fase 3: Segurança e robustez

- PIN obrigatório também para as rotas de upload e exclusão. Idealmente, um PIN de administrador separado do PIN do controle.
- Limite de tentativas de PIN (ex.: bloqueio de 1 minuto após 5 erros).
- Logs de upload e exclusão em arquivo com rotação simples.
- Validar tipo de conteúdo além da extensão quando possível (ZIP e ISO têm assinatura conhecida).
- Nunca expor a porta à internet. Documentar no README.

### Fase 4: Integração com o EmulationStation

Ver seção 5 deste plano, com o passo a passo completo.

### Fase 5: Interface e estilo

- Telas separadas: controle (`/`) e gerenciador (`/admin`).
- O gerenciador deve funcionar bem no celular em retrato. O controle continua exigindo paisagem.
- **Estilo:** reservar um arquivo `static/theme.css` com variáveis (`--bg`, `--surface`, `--accent`, `--text`, `--radius`, `--font`). Assim, quando o usuário colar o estilo, basta trocar esse arquivo sem mexer no HTML.
- Estado vazio, mensagens de erro e barra de progresso devem estar previstos desde o início.

> **Pendente:** referência de estilo fornecida pelo usuário. Quando chegar, mapear cores, fontes, bordas e espaçamentos para as variáveis de `theme.css`.

### Fase 6: Testes e entrega

- Testes unitários para: sanitização de nomes, validação de extensão, path traversal, limite de tamanho e checagem de espaço.
- Teste manual no Raspberry real com um sistema de cada tipo (um de cartucho, um de CD).
- Checklist de desempenho: uso de RAM do processo abaixo de 80 MB em repouso e durante upload.
- Atualizar o README com as novas rotas e variáveis.

## 4. Estrutura alvo

```
retropad/
├── server.py
├── config.py            # caminhos, limites e PINs lidos do ambiente
├── roms.py              # listar, validar, gravar e apagar ROMs
├── systems.json         # sistemas e extensões aceitas
├── static/
│   ├── index.html       # controle
│   ├── admin.html       # gerenciador de ROMs
│   ├── theme.css        # estilo (pendente)
│   ├── app.js           # lógica do gerenciador
│   └── manifest.json
├── scripts/
│   ├── retropad-start.sh
│   └── retropad-status.sh
├── tests/
├── requirements.txt
├── PLANO_MELHORIAS.md
└── README.md
```

## 5. Integração com o EmulationStation (passo a passo)

O RetroPie tem duas formas de expor o RetroPad no menu. Use as duas.

### 5.1 Entrada "RetroPad" na lista de Ports

1. Crie a pasta de ports, se ainda não existir: `mkdir -p ~/RetroPie/roms/ports`.
2. Crie o arquivo `~/RetroPie/roms/ports/RetroPad.sh`:
   ```bash
   #!/bin/bash
   # Mostra o status e o endereço do RetroPad
   IP=$(hostname -I | awk '{print $1}')
   clear
   echo "RetroPad"
   echo "Acesse no celular: http://$IP:8080"
   systemctl is-active --quiet retropad && echo "Status: rodando" || echo "Status: parado"
   echo ""
   read -p "Pressione ENTER para voltar..."
   ```
3. Dê permissão de execução: `chmod +x ~/RetroPie/roms/ports/RetroPad.sh`.
4. No EmulationStation, abra **Ports**. Se não aparecer, vá em **Configurações → Atualizar lista de jogos** ou reinicie o EmulationStation.
5. Teste: selecione "RetroPad" e confirme que o IP e o status aparecem.

### 5.2 Iniciar e parar o servidor a partir do menu

Crie `scripts/retropad-start.sh` e `scripts/retropad-status.sh` no projeto, e entradas separadas em `ports`:

- `RetroPad Iniciar.sh`: `sudo systemctl start retropad`
- `RetroPad Parar.sh`: `sudo systemctl stop retropad`

Para o usuário não precisar digitar senha, crie uma regra no sudoers apenas para esses comandos, em `/etc/sudoers.d/retropad`:

```
pi ALL=(root) NOPASSWD: /bin/systemctl start retropad, /bin/systemctl stop retropad, /bin/systemctl restart retropad
```

Use `sudo visudo -f /etc/sudoers.d/retropad` para editar com segurança. Troque `pi` pelo seu usuário.

### 5.3 Comando personalizado no es_systems.cfg (opcional)

Se quiser um botão de sistema em vez de um item de Ports, edite o arquivo de sistemas do EmulationStation. Faça backup antes:

```bash
sudo cp /etc/emulationstation/es_systems.cfg /etc/emulationstation/es_systems.cfg.bak
sudo nano /etc/emulationstation/es_systems.cfg
```

Adicione um bloco `<system>` novo. A estrutura é a mesma dos sistemas existentes (`name`, `fullname`, `path`, `extension`, `command`, `platform`, `theme`). Como isso mexe no núcleo do menu, prefira a opção 5.1 e só use esta se entender a sintaxe. Confira o XML com `xmllint --noout /etc/emulationstation/es_systems.cfg` antes de reiniciar.

### 5.4 Verificação

- Reinicie o EmulationStation e confira se "RetroPad" aparece em Ports.
- Rode "Iniciar", depois "Status", e confirme que o endereço está correto.
- Acesse o endereço no celular e teste o controle.
- Rode "Parar" e confirme que a página deixa de responder.

> Observação: os caminhos acima seguem o padrão do RetroPie. Se a sua instalação for diferente, o Claude Code deve checar com `ls` antes de editar.

## 6. Ordem sugerida de execução

1. Fase 1 (gerenciador básico com upload).
2. Seção 5.1 (entrada em Ports), porque é rápida e já dá acesso ao IP.
3. Fase 3 (PIN de admin e logs), antes de liberar uploads na rede.
4. Fase 2 (listar e apagar).
5. Seção 5.2 (iniciar e parar pelo menu).
6. Fase 5 (interface e estilo), quando a referência chegar.
7. Fase 6 (testes e documentação).

## 7. Instruções para o Claude Code

- Trabalhe em pequenos commits, um por fase ou subtarefa.
- Antes de cada mudança grande, rode os testes da Fase 6.
- Não adicione dependências sem justificar o peso no Raspberry.
- Não altere o controle (`index.html` e `server.py` do gamepad) sem rodar o teste manual com o RetroArch.
- Se algo depender do hardware real (uinput, caminhos do RetroPie, permissões), pergunte ao usuário antes de assumir.
