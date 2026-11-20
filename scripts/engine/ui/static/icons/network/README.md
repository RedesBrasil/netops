# Redes Brasil network icons

Source: https://github.com/RedesBrasil/network-icons

Pinned commit: `3bfe4c177ea78b91846517bd1a6964da3e3f55d3`.

- The ten PNGs at the root are the originals, unchanged.
- `catalog.json` is the original catalog, with names, dimensions and SHA-256.
- `thumbnails/` contains RGBA PNGs of up to 128 px, keeping the aspect ratio and transparency.
- `SHA256SUMS` records the checksums of the catalog, the originals and the local thumbnails.

The originals total about 10 MB; the ten thumbnails add up to approximately 139 KB.
The console uses only the thumbnails in the picker and on the map. No file is fetched from GitHub
or a CDN when using the interface.

## Origin and permission of use

The README of the revision above describes the icons as created for Redes Brasil with AI-assisted
generation and instructs to download and import the PNGs into editors/applications. The repository
does not declare a license file in that revision. This copy keeps the attribution and does not add
a license that the source project did not provide.

## Reproducible update

```bash
python3 scripts/engine/ui/vendor_icons.py
```

The script requires Pillow only for maintenance, downloads from an explicit commit, checks SHA-256 and
dimensions of all originals and generates the thumbnails. To update the library, review the
commit and the usage rights in `vendor_icons.py`, run it and rebuild the editor:

```bash
npm --prefix scripts/engine/ui/maps run build
```

The console's Python runtime does not depend on Pillow. After the build, update the hashes of the
editor assets in `static/vendor/VERSIONS.txt`.
