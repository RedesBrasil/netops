# Ícones de rede da Redes Brasil

Origem: https://github.com/RedesBrasil/network-icons

Commit fixado: `3bfe4c177ea78b91846517bd1a6964da3e3f55d3`.

- Os dez PNGs na raiz são os originais, sem alterações.
- `catalog.json` é o catálogo original, com nomes, dimensões e SHA-256.
- `thumbnails/` contém PNGs RGBA de até 128 px, mantendo a proporção e a transparência.
- `SHA256SUMS` registra os checksums do catálogo, dos originais e das miniaturas locais.

Os originais totalizam cerca de 10 MB; as dez miniaturas somam aproximadamente 139 KB.
O console usa somente as miniaturas no seletor e no mapa. Nenhum arquivo é buscado no GitHub
ou em CDN ao usar a interface.

## Origem e permissão de uso

O README da revisão acima descreve os ícones como criados para a Redes Brasil com geração
assistida por IA e orienta baixar e importar os PNGs em editores/aplicações. O repositório
não declara arquivo de licença nessa revisão. Esta cópia mantém a atribuição e não acrescenta
uma licença que o projeto de origem não forneceu.

## Atualização reproduzível

```bash
python3 scripts/engine/ui/vendor_icons.py
```

O script requer Pillow apenas na manutenção, baixa de um commit explícito, confere SHA-256 e
dimensões de todos os originais e gera as miniaturas. Para atualizar a biblioteca, revise o
commit e os direitos de uso em `vendor_icons.py`, execute-o e reconstrua o editor:

```bash
npm --prefix scripts/engine/ui/maps run build
```

O runtime Python do console não depende de Pillow. Depois do build, atualize os hashes dos
assets do editor em `static/vendor/VERSIONS.txt`.
