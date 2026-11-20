---
id: linux-services-hardening
title: Linux Services Hardening (Apache, Docker, FTP)
vendor: linux
tags: [security, linux, apache, docker, ftp, services]
severity: medium
---

## Summary

Best practices for the most common services running on Linux servers. Every exposed service
is an attack surface — this guide covers Apache, Docker and FTP.

## Apache HTTP Server

- [ ] TLS enabled; HTTP redirects to HTTPS; valid certificate (Let's Encrypt).
- [ ] Server version hidden (`ServerTokens Prod`, `ServerSignature Off`).
- [ ] Unused modules disabled; `mod_status`/`mod_info` restricted or turned off.
- [ ] `Indexes` disabled (no directory listing).
- [ ] Security headers (`X-Content-Type-Options`, `X-Frame-Options`, HSTS).
- [ ] Request size limits and timeouts configured (basic anti-DoS).
- [ ] Access and error logs enabled.

## Docker

- [ ] Docker daemon **not** exposed over TCP without TLS (`/var/run/docker.sock` local only).
- [ ] Containers do not run as `root` when avoidable (`USER` in the Dockerfile).
- [ ] Images from a trusted source and with a pinned tag (not `latest` in production).
- [ ] Only the required ports published (`-p`); prefer binding to `127.0.0.1` when local.
- [ ] Resource limits defined (`--memory`, `--cpus`) to isolate failures.
- [ ] `--cap-drop` whatever is not needed; avoid `--privileged`.
- [ ] Images up to date; vulnerability scanning in the pipeline.

## FTP

- [ ] Plain FTP (port 21, plain text) **disabled** — prefer SFTP/SCP (over SSH).
- [ ] If FTP is unavoidable, use FTPS (FTP over TLS) and restrict it by firewall.
- [ ] No anonymous write access; users confined to their own directory (`chroot`).

## Details

The common principle: **least privilege and least exposure**. A service should run with the
minimum permission, listen only where it needs to, and expose only what is necessary. A `docker.sock`
exposed over TCP without TLS is equivalent to giving `root` on the host — it is a CRITICAL finding.

## Related configuration

- `config-examples/linux/sshd_config` — hardened SSH access (seed example).
- Apache, Docker and FTP examples: to be added to `config-examples/linux/` as the
  living project evolves (follow `config-examples/STANDARD.md`).

## References

- Apache HTTP Server — Security Tips.
- Docker — Security best practices.
