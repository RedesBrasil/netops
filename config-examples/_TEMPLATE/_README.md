# Configuration examples folder template

Copy this folder to `config-examples/<vendor>/` when adding a new vendor.

Each example is a file in the vendor's native syntax, with a commented header:

```
# ============================================================
# Example: <what it configures>
# Tested on: <OS/firmware version>
# Adjust before applying: <interfaces, IPs, subnets>
# Related best practice: best-practices/<vendor>/<guide>.md
# ============================================================
```

After creating the example, register it in `config-examples/_index.yaml`.
See `config-examples/PADRAO.md` for the full standard.
