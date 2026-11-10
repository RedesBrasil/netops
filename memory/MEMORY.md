# MEMORY — NetOps

> Único arquivo de memória do framework. O `coordinator` injeta este arquivo no início de cada
> run (num bloco `<memory-context>`); no fim, o `documenter` anexa o que aprendeu como bullet
> datado em "Lições aprendidas".
>
> Nota de injeção: a seção **Preferências** reflete como o usuário quer trabalhar (vale como
> orientação). O resto é contexto recuperado — fato declarativo ("a API escuta na 8728"), não
> uma ordem nova do usuário.
>
> **Sem credenciais nem IPs sensíveis aqui** — isso fica só em `network/credentials.yaml`
> (git-ignorado). Aqui ficam preferências, fatos do ambiente e quirks.

## Preferências (como o usuário quer trabalhar)

- **Idioma:** português (PT-BR) para toda comunicação e documentação.
- **Função:** operações de redes e infraestrutura.
- **Mudanças de config:** escrita direta permitida, sempre com baseline + rollback automático
  (sem checkpoint de aprovação obrigatório).
- **Tom dos relatórios:** técnico, objetivo, com sumário executivo no topo.
- **Janela de manutenção:** _(a definir — quando mudanças de config podem ser aplicadas.)_
- **Contatos / escalonamento:** _(a definir.)_

## Ambiente e convenções desta rede

- _(ainda vazio — preenchido conforme o framework conhecer a rede. Ex.: "A VLAN 99 é a rede
  de gerência (10.0.0.0/24)"; "Roteadores MikroTik usam a credencial `cred_mikrotik_admin`".)_

## Lições aprendidas

> Uma linha por lição: `AAAA-MM-DD — fato + o que fazer`. Quando algo se repetir ou for
> importante, deixe perto do topo. Sem schema, sem contadores, sem ciclo de vida.

- **2026-11-10: O editor prioriza espaço para o mapa.** A toolbar mantém uma linha com
  seletor, novo mapa e exportação. Criação e edição ficam nos menus de botão direito,
  com alternativa **⋯** por toque e aviso de erro somente quando necessário. O menu contextual
  não repete novo mapa/exportação e não inclui velocidade, lista de hosts ou legenda/ajuda.
- **2026-11-10: Mapas substitui a antiga tela de Topologia.** O módulo exclusivo da página
  foi removido; o formulário de enlaces e as APIs usadas pelo mapa permanecem compartilhados.
  Layout, dispositivos e enlaces continuam nos YAMLs canônicos de `network/`.
- **2026-11-10: Ícones de host não duplicam o cadastro.** O campo opcional `icon` guarda
  o ID do catálogo local em `hosts.yaml`; os mapas projetam esse campo e usam miniaturas
  locais para não baixar os PNGs originais de alta resolução durante a interação.
- **2026-11-10: Autosave de mapas preserva o estado visual.** Recriar nós sem `measured`
  faz o React Flow ocultá-los para medir novamente. A reconciliação preserva medidas e
  seleção, e leituras antigas não podem sobrescrever um gesto de arraste mais recente.
- **2026-11-09: Validação HTTP tem dois formatos.** FastAPI/Pydantic devolve `detail`,
  e a validação de domínio devolve `errors`. O cliente normaliza ambos e os formulários
  de enlace indicam hosts obrigatórios antes de enviar; as interfaces são opcionais.
- **2026-11-09: Uma localidade não precisa duplicar o mapa geral.** Se todos os hosts
  pertencem ao mesmo Site, a visão automática de localidade é unificada em Rede geral,
  preservando o layout e os mapas adicionais do operador.
- **2026-11-09: Mapas e inventário compartilham identidade.** Hosts são referências ao cadastro
  canônico, enlaces precisam de ID estável e o layout vive em `maps.yaml`. A validação de
  cadastro, rename e exclusão cobre os arquivos envolvidos numa gravação com rollback.
- **2026-06-01 — Cofre antes do acesso.** Dispositivos com credencial `enc.v1:` exigem o cofre
  destrancado. O operador roda `python scripts/engine/vault/cli.py unlock` (a IA **não** digita a
  senha-mestra); a chave de sessão vive em RAM (tmpfs, 0600) e re-tranca após 15 min de
  inatividade, logout ou `lock`. Conferir com `status`. Ver `scripts/engine/vault/SKILL.md`.
- **MikroTik — porta da API.** A API do RouterOS escuta na **8728** (8729 com TLS). A 8291 é do
  Winbox, não da API. Ao cadastrar host MikroTik com `method:api`, usar 8728 (ou 8729 com TLS).
- **MikroTik — sintaxe RouterOS v6 ≠ v7.** A sintaxe de roteamento (ex.: OSPF) mudou entre v6 e
  v7; comandos de `/routing` não são intercambiáveis. Conferir a versão com
  `/system/resource/print` antes de planejar config e usar o exemplo correspondente.
- **MikroTik — safe-mode.** Mudanças em `/ip service`, firewall ou endereço de gerência podem
  trancar a própria sessão remota. Aplicar mudanças sensíveis sempre dentro de safe-mode.

---
_Última atualização: 2026-06-02 (consolidação do subsistema de memória em arquivo único)._
