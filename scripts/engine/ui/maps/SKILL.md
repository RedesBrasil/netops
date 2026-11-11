# Editor de mapas do console

Editor React Flow integrado à SPA Preact do NetOps. Fontes em `maps/`, assets finais em
`../static/vendor/map-editor.js` e `map-editor.css`. O operador não precisa de Node nem npm.
O build serve apenas à manutenção do editor; não compila ou substitui o restante do console.

## Manutenção

```bash
npm --prefix scripts/engine/ui/maps ci --include=dev
npm --prefix scripts/engine/ui/maps run build
npm --prefix scripts/engine/ui/maps test
```

Dependências pinadas: React Flow `12.12.1`, Preact `10.27.2`, esbuild `0.28.2`.
O build empacota React Flow e suas dependências, mas externaliza Preact e seus hooks.
Um shim ESM adapta imports de React para o `preact/compat` local do console, sem runtime
React e sem uma segunda cópia de Preact. `build.mjs` verifica isso pelo metafile.

Depois de reconstruir, atualizar `static/vendor/VERSIONS.txt` com os hashes dos assets.
Licenças das dependências estão em `static/vendor/map-editor.LICENSE.txt`.

## Estrutura e comportamento

- `editor.jsx`: componente `MapEditor`, sem mount global e sem armazenamento próprio.
- `node-state.js`: reconcilia nós preservando medidas e seleção do React Flow.
- `parallel-edges.js`: faixas independentes e âncoras de linhas retas.
- `orthogonal-route.js`: dobras unitárias e saída perpendicular nas bordas.
- `straight-edges.jsx`: gestos com mouse/toque e controles de enlaces.
- `editor.css`: estilos limitados a `.netops-maps`, com temas do console.
- `test-geometry.mjs`: contagem de dobras, orientação e preservação das rotas.
- `../static/js/pages/maps.js`: controlador de API, revisão, fila de salvamento e forms reais.

Os dados ficam em YAML no servidor, compartilhados entre navegadores. Host no mapa é
referência ao inventário, nunca uma cópia do cadastro. As conexões entre hosts usam enlaces
reais, com interfaces opcionais. Referências entre mapas são objetos visuais, não hosts fictícios.

### Identidade inteira e formato v2

Os IDs dos hosts são inteiros internos, automáticos e imutáveis. O cadastro pede somente o
nome editável e os demais dados; seletores de host mostram nome/IP. As APIs usam inteiros
em `members`, `host_ids` e `topology.links[].a.host`/`b.host`. O snapshot fornece `hosts` como
lista de registros com `id`, e as posições são uma lista de `{host_id, x, y, z_index?}`.
As pontas de `visual_links` usam `{kind: host, host_id: 42}` ou
`{kind: object, object_id: forma}`. `maps.yaml` e `topology.yaml` usam `version: 2`.

`static/js/host-identity.js` adapta essa representação para o editor: índices de posição
efêmeros e IDs de nós React Flow como `host:42` existem só na apresentação. Toda gravação
e exportação v2 reconverte para listas e referências tipadas com IDs inteiros. O backend
recusa identidade textual/booleana, posição de host duplicada e host fora do inventário.
Inventário v1 continua visível em modo somente leitura, sem migração implícita por GET.

`node --test scripts/engine/ui/tests/host-identity.test.mjs` verifica essa fronteira;
`tests/test_maps_identity.py` cobre validação estrita e leitura legada sem escrita.
`tests/integer-hosts.browser.mjs` valida desktop/toque: cadastro por Hosts/Mapas sem campo
de ID, seletores nome/IP, enlace inteiro, ligação visual tipada e edição do nome preservando
ID, ícone, posição e enlace. Usa as mesmas variáveis Playwright e a exigência de fixture
isolada dos cenários abaixo. O cenário principal `tests/maps.browser.mjs` também usa o v2.

Não restaurar o afastamento automático ou outra alteração de movimento livre removida
na avaliação da demo. Os quatro handles do React Flow existem internamente, mas são invisíveis.

## Teste no navegador

O teste integrado reside em `../tests/maps.browser.mjs`. Usa Playwright e Chromium já
instalados pelo operador; não baixa ferramentas automaticamente. Apontar somente para um
console com dados fictícios, iniciado pelo launcher com `NETOPS_UI_DATA_ROOT`.

```bash
NETOPS_E2E_URL=http://127.0.0.1:8771 \
PLAYWRIGHT_MODULE=/caminho/playwright/index.mjs \
CHROMIUM_EXECUTABLE=/caminho/chrome \
node scripts/engine/ui/tests/maps.browser.mjs
```

O teste exige um diretório de dados alternativo, comunicado nos metadados do console.
Ele cria hosts e mapas de teste, portanto recusa uma instância de produção.

Depois do cenário integrado de cadastro, `tests/maps-endpoints.browser.mjs` valida as duas
pontas nos quatro lados, com as mesmas variáveis de ambiente. Ele usa apenas os hosts de
teste criados pelo cenário anterior e também recusa uma instância com dados reais.


## Visão principal sem duplicação

Quando todos os hosts têm o mesmo Site, o seletor exibe somente **Rede geral** como mapa
automático. Mapas adicionais continuam disponíveis. A leitura calcula a unificação sem
escrever; a próxima gravação persiste o resultado com revisão e backup. Posições e trajetos
do geral têm precedência, anotações e demais ajustes exclusivos do mapa de localidade são
incorporados, e referências antigas passam a apontar para `all`.

`tests/maps-single-site.browser.mjs` valida desktop e toque com um diretório de teste contendo
os exemplos `hosts.example.yaml`/`topology.example.yaml` e uma fixture `maps.yaml`: geral com
posições salvas, mapa de `matriz` com a nota “Anotação preservada da matriz” e um mapa adicional
com referência à antiga matriz. Usar as mesmas variáveis Playwright dos testes anteriores.


## Arraste estável

A confirmação do autosave e o polling não recriam nós já medidos. `reconcileNodes` mantém
`measured`, seleção e estado transitório, aplicando apenas as mudanças do layout/cadastro.
Arraste e redimensionamento usam o estado atual por referência; o YAML só é salvo ao terminar
o gesto. Respostas de leitura iniciadas antes de uma edição são descartadas, e uma confirmação
de gravação anterior não muda a posição de um host ainda em movimento.

`tests/maps-drag.browser.mjs` simula GET/PUT atrasados, arrastes seguidos e atualização sem
mudanças em desktop e toque, monitorando a visibilidade dos nós por MutationObserver e frame.
Requer console isolado com os hosts dos exemplos e aceita as variáveis Playwright dos demais
testes. `npm test` no editor também executa os testes de preservação de estado dos nós.


## Ícones locais de hosts

O editor renderiza o campo `icon` do host com miniaturas em `static/icons/network/thumbnails/`.
O catálogo é embutido no build somente para resolver IDs locais permitidos; o cadastro fica
no inventário, não no layout. Uma imagem inválida/indisponível retorna ao símbolo anterior,
e seu tamanho reservado evita alterar a posição do host durante a carga.
Ao atualizar a biblioteca, reconstruir o editor após `vendor_icons.py`.


## Controles compactos e menus contextuais

O mapa ocupa toda a área disponível abaixo de uma única linha: mapa atual, **+** para novo
mapa e exportação. As ações de edição foram movidas para o botão direito no fundo, nos nós,
no traço/rótulo dos enlaces e nos cantos. A seleção normal mantém os controles de geometria
A/B e cantos arrastáveis, sem abrir uma segunda barra de ações.

No toque, **⋯** usa o item selecionado ou o fundo quando não há seleção. **Shift+F10** abre
o menu do item focado/selecionado; setas navegam e Escape fecha. Menus são limitados ao
viewport, com rolagem em paisagem. O menu não inclui velocidade, lista de hosts, exportação,
legenda/ajuda ou novo mapa. Novo mapa e exportação ficam só no topo; velocidade permanece
no formulário de enlace.

`tests/maps-context.browser.mjs` cobre a remoção dos itens antigos, a linha única, criação e
edição por menu, dobras, exportação, atalhos e recuperação de conflito em mouse e toque.
`tests/maps-actions.mjs` é o helper de gestos dos cenários do navegador, não código da UI.
Os arquivos de inventário/layout e o fluxo de autosave permanecem os mesmos.


## Formas conectáveis e grupos

`Shape` usa os mesmos `NodeHandles` invisíveis dos hosts. O fluxo único de conexão aceita
formas como origem/destino e reutiliza `visual_links`; não cria hosts sem IP. O catálogo de
ícones é validado em `MapObject`, enquanto o `IconPicker` compartilhado é recebido da SPA
como prop, sem duplicar componentes/API/Preact no bundle.

A seleção múltipla usa `node.selected` do React Flow, seus modificadores Ctrl/Meta e seleção
por retângulo com botão esquerdo no fundo, sem modificadores (Shift também funciona).
O retângulo seleciona itens inteiramente contidos; o botão central ou Espaço permitem mover
o mapa, e o gesto de arraste com toque continua navegando. O menu de grupo e a alternativa por toque chamam `alignNodes` em
`node-state.js`, função pura que retorna posições por ID, ordenadas no eixo e separadas por
24 unidades entre bordas. O editor aplica posições de hosts e objetos numa única gravação.
A reconciliação mantém medidas/seleção e nenhuma rota é reiniciada pelo alinhamento.

`tests/shapes-align.browser.mjs` cobre conexões nos dois sentidos, ícones, persistência,
seleção de quatro hosts, grupo misto, espaçamento igual e dispositivos não selecionados
intactos. Executar em uma fixture isolada exclusiva, sem cenários concorrentes alterando
o mesmo arquivo de mapas.

## Texto opcional, cores e camadas

Enlaces reais exibem somente `desc`, editável no cadastro do enlace. Ligações visuais usam
`label` e nascem com texto vazio; nem velocidade nem nomes genéricos geram rótulos. Formas
também podem ter texto vazio. O traço continua selecionável para ajustar/editar a ligação.

O formulário de forma oferece seletores nativos de preenchimento e contorno, campos HEX
editáveis/copiáveis e prévia. `color` e `stroke` opcionais usam `#RRGGBB` em `maps.yaml`.
O texto da forma e da prévia usa preto ou branco conforme a luminância do preenchimento,
conservando contraste independentemente do tema do console.
Objetos antigos sem esses campos conservam as cores do tema até serem editados.

Hosts e objetos compartilham a mesma ordem visual, salva em `positions[].z_index`
(associada pelo inteiro `positions[].host_id`) e
`objects[].z_index`. Enviar para frente/trás troca exatamente com o vizinho, sem salto ao
extremo. A seleção não altera a camada; mapas antigos mantêm as formas atrás dos hosts.
Mover/alinha um host preserva sua camada. Duplicar cria outra forma com ID próprio, mesmas
cores/ícone/tamanho/texto, deslocada 32 unidades e uma camada acima da original.

Delete remove objetos selecionados e suas ligações visuais. Em mapas adicionais, hosts
selecionados são apenas removidos do mapa. Em mapas automáticos, a seleção com hosts abre
confirmação explícita de exclusão do inventário e dos enlaces/referências em todos os mapas.
A operação usa revisões por exclusão e interrompe na primeira falha, informando quantos
hosts já foram removidos; não é uma transação única para todo o grupo. O mapa fica somente
leitura durante a sequência. Delete em campos de texto mantém a edição normal.

`node-state.test.mjs` cobre a pilha mista, limites, duplicação e limpeza de grupos sem mutar
o snapshot anterior. `tests/maps-editing.browser.mjs` verifica os recursos no navegador
com dados fictícios isolados.

O React Flow omite `onPaneClick` no toque quando `selectionOnDrag` está ativo. O canvas
reconhece um toque curto no fundo por `pointerId` e deslocamento máximo de 6px para limpar
a seleção; arrastes continuam sendo pan e a seleção por mouse permanece disponível também
em dispositivos híbridos. Seleção múltipla, conexão e duplicação devolvem o foco ao canvas,
permitindo Escape/Delete imediatamente após fechar o menu.

Escolher uma ligação por clique, botão direito ou Shift+F10 limpa a seleção anterior de
nós antes de disponibilizar Delete. Assim a exclusão atua somente na ligação escolhida
(enlace físico com confirmação), preservando as formas/hosts anteriormente selecionados.
O menu aberto num nó que integra uma seleção múltipla mantém o grupo selecionado.
