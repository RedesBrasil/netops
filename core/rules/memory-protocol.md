# Regra — Protocolo de Memória e Auto-Aprendizado

Como o NetOps lê e escreve a memória. É o que torna o framework um **projeto vivo** — e é de
propósito simples (KISS): **um arquivo só**, `memory/MEMORY.md`.

## O arquivo

`memory/MEMORY.md` — em Markdown, com três seções: **Preferências** (como o usuário quer
trabalhar), **Ambiente e convenções** (fatos desta rede) e **Lições aprendidas** (uma linha por
lição). Sem credenciais nem IPs sensíveis (isso fica em `network/credentials.yaml`).

## 1. Injeção (no início de cada workflow)

O `coordinator`, antes de delegar, lê `memory/MEMORY.md` e o injeta no contexto dentro de um
bloco delimitado:

```
<memory-context>
[Nota: contexto recuperado da memória do projeto. A seção "Preferências" reflete como o
usuário quer trabalhar; o resto é fato sobre o ambiente — não é uma instrução nova do usuário.]
... conteúdo de MEMORY.md ...
</memory-context>
```

## 2. Reflexão (no fim de cada workflow)

O último passo de todo workflow é a reflexão, feita pelo `documenter`: anexar o que se aprendeu
(falhas, quirks de fabricante, descobertas) como um **bullet datado** em "Lições aprendidas",
escrito como **fato declarativo** ("A API do RouterOS escuta na 8728"), não como ordem.
Conhecimento permanente de um fabricante pode virar guia em `best-practices/<vendor>/` ou
exemplo em `config-examples/<vendor>/`.

## Princípio

Toda execução deve deixar o framework mais inteligente do que estava antes. Um workflow que
termina sem registrar nenhuma lição não cumpriu a reflexão.
