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

## Estado atual (11/11/2026)

Todos os menus do console seguem a regra. Helpers: `static/js/route.js` (`useMenuRoute`, `useRoute`, `navigate`,
`parseRoute`, `buildRoute`, `matchText`) e `FilterBar` em `components.js`; `ResourceTable` aceita `sortState`/`onSortChange`.

| Menu | URL de item | Filtros / parâmetros |
|------|-------------|----------------------|
| Hosts | `#hosts/<id>`, `#hosts/new` | `q vendor role group sort dir` |
| Grupos | `#groups/<nome>`, `/new` | `q vendor role` |
| Credenciais | `#credentials/<nome>`, `/new`, `/<nome>/password`, `/<nome>/secret` | `q` |
| Mapas | `#maps/<mapa>` (`#maps` → `#maps/all`) | `host=<id>\|new`, `link=<id>` |
| Boas práticas / Configurações | `#practices\|configs/<vendor>/<arquivo>`, `/new` | `q vendor` |
| Workflows / Agentes | `#workflows\|agents/<arquivo>`, `/new` | `q` |
| Relatórios | `#reports/<arquivo>` | `q` |
| Execuções | `#runs/<id>` | `q status` |
| Backups | `#backups/services[/<id>\|/new]`, `#backups/storage[/<host>]` | `q run file diffa diffb` |
| Scripts / Skills | abas `#scripts` (Skills) e `#scripts?tab=scripts` (Scripts); `#scripts/<skill>` (página da skill), `#scripts/<skill>/<arquivo>[?tab=scripts]` (script ou `SKILL.md`), `/new` | `tab q location lang sort dir doc` |
| Tarefas agendadas | `#schedules/<id>`, `#schedules/new`, `#schedules/runs`, `#schedules/runs/<tarefa>/<run>` | `q kind status` (tarefas); `q task rstatus unread` (execuções) |
| Configuração | `#settings/updates` (painel de atualizações) | — |
| Claude Code | `#claude/<id>`, `#claude/new` | — |
| Memória | `#memory` (=MEMORY.md), `#memory/AGENTS.md`, `#memory/notas`, `#memory/<nota>.md` | `q` (lista de notas) |
| Terminal | página única (sem item aberto) | — |

**Acessar → Web** (`openWebLaunch`) é uma *ação* (abre aba externa já logada via `POST /api/hosts/<id>/web-launch`), não uma tela do console: não tem hash próprio e nunca coloca ticket/senha na URL.

Filtros efêmeros dentro de formulários/modais (ex.: escolher hosts ao editar um serviço de backup) não vivem na URL.

**Teste obrigatório:** `scripts/engine/ui/tests/urls.browser.mjs` (ambiente isolado: `tests/e2e-env.sh up`; ver SKILL.md).
Ao criar um menu/tela nova, adicione um caso em `CASES` desse teste.

## Checklist antes de entregar uma tela

- [ ] Abrir item A e item B gera URLs diferentes?
- [ ] Colar a URL em aba nova restaura item, aba e filtros?
- [ ] Cada filtro/busca/ordenação altera a URL?
- [ ] Voltar/Avançar do navegador funcionam?
- [ ] Nenhum segredo na URL?
- [ ] Teste JS cobre parse/serialize da rota?
