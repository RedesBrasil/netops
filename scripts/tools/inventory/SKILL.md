---
id: inventory-map
name: Descobrir hosts e organizar no mapa
type: script
runtime: python
description: Descobre CTs/VMs de um Proxmox, cadastra no inventário e posiciona no mapa dentro da caixa do Proxmox, com linhas em ângulo reto.
env: []
---

## O que faz

Receita (e script) para "cadastre os containers ligados do Proxmox X no inventário e no mapa":
descobre o que está ligado, cadastra em `network/hosts.yaml` e coloca no mapa **Rede geral** dentro da
caixa azul do Proxmox, ligado à bridge com linhas em ângulo reto — o mesmo desenho do Proxmox Techify.

## Quando usar

Pedido de cadastrar/mapear CTs, VMs ou "tudo que roda no Proxmox X". Também para reorganizar um Proxmox
cujo desenho ficou fora da caixa ou com linhas diagonais.

## Passo a passo

**1. Escolha o Proxmox.** Ache em `network/hosts.yaml`. Se houver mais de um candidato (ex.: dois "PROXMOX TESTES"),
**pergunte qual** (`AskUserQuestion`); não cadastre nos dois por palpite.

**2. Descubra o que está ligado** (só leitura, uma sessão por host, `session.py exec`):

```bash
python3 scripts/tools/access/session.py exec --host-id <PVE> --command "pct list; qm list"
```

"Containers ligados" = `pct list` com `running`. VMs (`qm list`) só se o usuário pedir; avise que ficaram de fora.
Depois colete os detalhes de cada CT ligado num único comando (config + SO + IP + portas + docker):

```bash
python3 scripts/tools/access/session.py exec --host-id <PVE> --command 'for i in <CTs>; do echo "== $i $(pct config $i | grep -E "^(hostname|cores|memory|ostype)" | tr "\n" " ") $(pct config $i | grep -oE "ip=[^,]*,|tag=[0-9]+|bridge=[a-z0-9]+" | tr "\n" " ")"; pct exec $i -- sh -c ". /etc/os-release; echo \$PRETTY_NAME; ip -4 -o addr show scope global | awk \"{print \\\$2,\\\$4}\"; ss -tlnH | awk \"{print \\\$4}\" | sed \"s/.*://\" | sort -un | tr \"\n\" \" \"; echo; command -v docker >/dev/null && docker ps --format \"{{.Names}}\" | head -8 | tr \"\n\" \" \"" 2>&1 | head -8; done'
```

Dá hostname, vCPU/RAM, bridge/VLAN (`tag=`), IP, SO, portas e containers Docker (daqui saem os `apps`). CT sem `ip=` fixo = DHCP
(avise na nota "IP pode mudar"). CT com IP **público** direto na bridge merece destaque na nota.

**3. Cheque o que já existe** antes de cadastrar: `grep -n "mgmt_ip: <IP>" network/hosts.yaml` e pelo nome. O `register`
pula nome ou IP repetido. Nome igual ao de outro host (ex.: dois `PROXY-TESTE` em Proxmox diferentes) → use um sufixo
(`PROXY-TESTE-DESKTOP`) e diga isso na resposta; o nome dentro do Proxmox não se renomeia sem pedido (exige `change.py begin/end`).

**4. Cadastre** (`register`). Regras: hostname **TUDO MAIÚSCULO** com hífen; `runs_on` = ID do Proxmox; nota
`CT N do <PROXMOX> (host P)`; `group: LINUX-SERVERS`, `icon: linux-server`, `model: LXC`. Escreva a spec fora de `/tmp`
(ex.: `/var/tmp/netops-inv/spec.yaml`) e apague no fim.

```bash
python3 scripts/tools/inventory/map_place.py register --spec /var/tmp/netops-inv/spec.yaml          # dry-run
python3 scripts/tools/inventory/map_place.py register --spec /var/tmp/netops-inv/spec.yaml --apply  # grava
```

**5. Posicione no mapa** (`place`). Roda sobre **todos** os hosts com `runs_on` = Proxmox (reorganiza a caixa inteira).
Rótulo nas linhas: `VLANxxxx` para o que tem `tag=` no `pct config`; nome da bridge (`vmbr1`, `vmbr2`) para rede interna sem VLAN;
vazio para a rede padrão.

```bash
python3 scripts/tools/inventory/map_place.py place --proxmox <PVE> --labels 37=VLAN3000,55=vmbr1          # dry-run
python3 scripts/tools/inventory/map_place.py place --proxmox <PVE> --labels 37=VLAN3000,55=vmbr1 --apply
```

**5b. Caixa que já tem desenho próprio** (Redes Brasil, Techify) **não se reorganiza**: use `append` (põe embaixo da coluna menos cheia) e, se a
caixa estiver cheia, `--xy x,y [...] --trunk X` (posição à mão, p. ex. no vão entre duas linhas já existentes). Proxmox **sem zona** no mapa
(ex.: Wholesale): `zone --proxmox <ID> --name "Proxmox X" --apply` cria caixa + nota + bridge abaixo da última e põe o host na coluna dos
Proxmox; depois `place`. `place` alarga a caixa sozinho quando passa de 15 hosts (4+ colunas).

```bash
python3 scripts/tools/inventory/map_place.py append --proxmox <PVE> --hosts <IDs> [--labels ID=vmbr1] [--apply]
python3 scripts/tools/inventory/map_place.py zone --proxmox <PVE> --name "Proxmox X" --apply
```

**6. Avise o usuário para recarregar o mapa.** A tela aberta guarda o estado antigo e, se ele mexer em algo, sobrescreve o arquivo.

## Varredura de TODOS os Proxmox (sem duplicar)

Para cada Proxmox do inventário (`icon: proxmox`, hoje 14–18): liste `pct list`/`qm list` ligados, pegue o IP de cada um (`pct exec`) e compare
com `hosts.yaml` **por IP e por nome**. Cuidado com falso positivo: o mesmo IP privado repete em redes internas diferentes (`192.168.100.1` é
o modem Vivo E a bridge do MANAGER-ATLAS; `10.8.100.x` aparece em vários Proxmox) — decida pelo nome + `runs_on` + nota "CT N do …", não só
pelo IP. Um mesmo CT pode ter 2 IPs e o inventário guardar só um. VM sem guest agent: ache o IP pelo MAC (`qm config` → `net0`) com ping sweep da
rede na bridge (`seq 1 254 | xargs -P64 -I{} ping -c1 -W1 10.8.200.{}`) e `grep -i <mac> /proc/net/arp` no Proxmox; roteador CHR = IP do gateway dos
CTs da mesma bridge (`pct exec <ct> -- ip route`), marcando "deduzido" na nota. Termine com `inventory.py --validate` e confira IDs, nomes e IPs únicos.
Hosts que ficam **fora** do mapa por desenho: CHR dos labs (MK-00-201..204) e o 2º grupo do Techify (ligado ao proxy, linhas verdes da topologia).

## Como o mapa funciona (aprendizados)

- Cada Proxmox tem 3 coisas em `network/maps.yaml` (mapa `all`): o **host** Proxmox (coluna x≈435), uma **bridge** (`type: shape`,
  `label: bridge`) e uma **caixa azul** (`type: shape` sem label, `color: '#dbeafe'`, 1328×941) com uma **nota** de título
  (`type: note`, ex. "Proxmox Testes HP"). O texto grande no topo da caixa é a nota; a forma é o shape. **Hosts novos têm de
  ficar DENTRO da caixa** (x 883–2211, y do topo até +941); quem sai da caixa "ficou fora da forma".
- Um mapa tem `positions` (host_id, x, y, z_index), `objects` (formas/notas) e `visual_links` (bridge → host). Linhas **sem** `anchors`
  e `route` saem diagonais; para o ângulo reto cada link leva
  `anchors: {source: {side: right, ratio: 0.5}, target: {side: left, ratio: 0.5}}` e `route: {axis: x, tracks: [X]}`, onde `X` é o
  vão vertical (tronco) entre a bridge/coluna anterior e a coluna do host.
- Geometria do Techify (copiada pelo script): coluna 1 em x = caixa + 308, passo de colunas 297, linhas a cada 134 (host ≈ 105 de
  altura), 1ª linha a +176 do topo, **máx. 3 colunas × 5 linhas** (15 hosts) por caixa; tronco = x da coluna − 52.
- A **bridge** fica no x = caixa + 71 e com o centro **no vão entre duas linhas**, porque a linha horizontal das colunas 2 e 3 sai
  do centro da bridge e passaria por cima de um host. Por isso o script move a bridge.
- Enchendo em coluna (coluna 1 de cima a baixo, depois a 2…), agrupando por afinidade (ex.: proxy + coolify de cada cliente na
  mesma coluna).
- O mapa é gravado pelo console também: use o lock (`inventory_lock`, o script já usa) e sempre copie antes
  (`runs/copias-seguranca/network/`, nunca `.bak` ao lado). `maps.yaml` e `hosts.yaml` são git-ignorados (vão no backup completo).
- Não mexe no `topology.yaml`: containers só aparecem no mapa, nunca lá.

## Exemplos

```bash
python3 scripts/tools/inventory/map_place.py place --proxmox 17 --labels 55=vmbr1,56=vmbr2,57=vmbr2 --apply
```
