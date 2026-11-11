# Regra permanente: tudo que se abre ou filtra tem URL própria (console web)

Todo agente que criar ou alterar uma tela do console (`scripts/engine/ui/static/js/`) deve ler esta regra.

## Princípio

O estado de navegação vive na URL, não só no `useState`. Copiar o endereço da barra e abri-lo em
outra aba (ou após F5) deve reproduzir exatamente a mesma tela.

## Regras

1. **Todo menu = uma URL.** Cada item da sidebar é `#<menu>` (ex.: `#hosts`, `#backups`, `#memory`).
2. **Todo item aberto = uma URL distinta**, em qualquer menu: host, credencial, mapa, nota de memória,
   relatório, execução, workflow, agente, script, backup, sessão Claude, etc.
   - Host A aberto → `#hosts/rt-core-01`; Host B aberto → `#hosts/sw-acesso-02`.
   - Formato: `#<menu>/<id-estável>` — use o identificador estável (nome/slug/id), nunca índice de lista.
   - Sub-abas e painéis de detalhe também: `#hosts/rt-core-01/interfaces`.
3. **Todo filtro, busca, ordenação e página = URL distinta**, em query dentro do hash:
   `#hosts?vendor=mikrotik&status=down&q=core&sort=name&page=2`.
   - Só grave valores não-padrão (URL limpa quando nada está filtrado).
   - Limpar o filtro remove o parâmetro.
   - Combina com item aberto: `#hosts/rt-core-01?tab=interfaces`.
4. **Modais, painéis e editores que representam um objeto** (editar host, ver relatório) também têm URL.
   Confirmações e diálogos efêmeros não precisam.
5. **Abrir por URL funciona** (deep link): ao carregar, a tela lê o hash e restaura item, aba e filtros;
   id inexistente mostra "não encontrado" com link de volta ao menu, nunca tela em branco.
6. **Navegação normal usa histórico**: abrir item/aba → `location.hash = ...` (botão Voltar funciona).
   Mudança de filtro ao digitar → `history.replaceState` (não polui o histórico).
7. **Links reais**: listas usam `<a href="#...">`, não `onClick` que só muda estado — permite abrir em
   nova aba e copiar o link.
8. **Sem segredos na URL**: nunca coloque senha, token, secret ou conteúdo sensível (constituição §V).
   Nada de token de acesso na URL — o login é por senha-mestra.
9. **Compatibilidade**: ao renomear uma rota, redirecione a antiga (ver `topology` → `maps` em `main.js`).
10. **Helper único**: implemente/reuse um helper central (ex.: `useRoute()` em `js/ui.js`) que faz
    parse/serialize de `#menu/id?filtros`. Não espalhe `location.hash` manual pelas páginas.

## Estado atual (auditoria 11/11/2026)

- Já têm URL: menus de 1º nível, sessões Claude (`#claude/<id>`, `#claude/new`) e **Hosts** (`#hosts/<id>`, `#hosts/new`, `?q=&vendor=&role=&group=&sort=&dir=`).
- Helper: `static/js/route.js` (`useRoute`, `navigate`, `parseRoute`, `buildRoute`); `ResourceTable` aceita `sortState`/`onSortChange` p/ ordenação na URL. Teste: `tests/route.test.mjs`.
- **Sem URL ainda** (dívida a corrigir ao tocar a página): item aberto e filtros de `credentials`,
  `maps`, `memory`, `knowledge` (práticas/configs/workflows/agentes), `view` (relatórios/execuções),
  `backups`, `scripts`, `catalog`, `updates`.

## Checklist antes de entregar uma tela

- [ ] Abrir item A e item B gera URLs diferentes?
- [ ] Colar a URL em aba nova restaura item, aba e filtros?
- [ ] Cada filtro/busca/ordenação altera a URL?
- [ ] Voltar/Avançar do navegador funcionam?
- [ ] Nenhum segredo na URL?
- [ ] Teste JS cobre parse/serialize da rota?
