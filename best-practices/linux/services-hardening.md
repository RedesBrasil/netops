---
id: linux-services-hardening
titulo: Hardening de Serviços Linux (Apache, Docker, FTP)
vendor: linux
tags: [security, linux, apache, docker, ftp, services]
severidade: media
---

## Resumo

Boas práticas para os serviços mais comuns rodando em servidores Linux. Cada serviço exposto
é uma superfície de ataque — este guia cobre Apache, Docker e FTP.

## Apache HTTP Server

- [ ] TLS habilitado; HTTP redireciona para HTTPS; certificado válido (Let's Encrypt).
- [ ] Versão do servidor ocultada (`ServerTokens Prod`, `ServerSignature Off`).
- [ ] Módulos não usados desabilitados; `mod_status`/`mod_info` restritos ou desligados.
- [ ] `Indexes` desabilitado (sem listagem de diretório).
- [ ] Cabeçalhos de segurança (`X-Content-Type-Options`, `X-Frame-Options`, HSTS).
- [ ] Limites de tamanho de requisição e timeouts configurados (anti-DoS básico).
- [ ] Logs de acesso e erro habilitados.

## Docker

- [ ] Daemon Docker **não** exposto via TCP sem TLS (`/var/run/docker.sock` só local).
- [ ] Containers não rodam como `root` quando evitável (`USER` no Dockerfile).
- [ ] Imagens de origem confiável e com tag fixa (não `latest` em produção).
- [ ] Só as portas necessárias publicadas (`-p`), preferir bind em `127.0.0.1` quando local.
- [ ] Limites de recurso definidos (`--memory`, `--cpus`) para isolar falhas.
- [ ] `--cap-drop` do que não for necessário; evitar `--privileged`.
- [ ] Imagens atualizadas; varredura de vulnerabilidade no pipeline.

## FTP

- [ ] FTP simples (porta 21, texto puro) **desabilitado** — preferir SFTP/SCP (sobre SSH).
- [ ] Se FTP for inevitável, usar FTPS (FTP sobre TLS) e restringir por firewall.
- [ ] Sem acesso anônimo de escrita; usuários confinados ao seu diretório (`chroot`).

## Detalhamento

O princípio comum: **menor privilégio e menor exposição**. Um serviço deve rodar com o
mínimo de permissão, ouvir só onde precisa, e expor só o necessário. O `docker.sock`
exposto via TCP sem TLS é equivalente a dar `root` no host — é um achado CRÍTICO.

## Configuração relacionada

- `config-examples/linux/sshd_config` — acesso SSH endurecido (exemplo seed).
- Exemplos de Apache, Docker e FTP: a adicionar em `config-examples/linux/` conforme o
  projeto vivo evolui (siga `config-examples/PADRAO.md`).

## Referências

- Apache HTTP Server — Security Tips.
- Docker — Security best practices.
