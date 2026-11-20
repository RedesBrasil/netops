# STANDARD — `config-examples/`

**Real and applicable** configuration examples, in the native syntax of each vendor. Where
`best-practices/` explains the "why", here is the "how" — ready config for the `planner`
to adapt (REUSE > ADAPT > CREATE).

## Organization

- `<vendor>/` — one folder per vendor (`mikrotik/`, `linux/`, `cisco/`, ...).
- `_index.yaml` — index of all examples, per vendor and topic.
- `_TEMPLATE/` — template to copy when adding a new vendor/example.

## Format of an example

File with the vendor's native extension, with a **commented header** explaining:
what it configures, which version it was tested on, and what to adjust before applying.

| Vendor | Extension | Syntax |
|--------|-----------|--------|
| MikroTik | `.rsc` | RouterOS script (`/command ...`) |
| Cisco | `.ios` | IOS CLI |
| Linux | `.conf`, `.sh`, `.yml` | Service config / shell / compose |
| Huawei | `.cfg` | VRP CLI |

Header example (MikroTik):

```
# ============================================================
# Example: <what it configures>
# Tested on: RouterOS 7.x
# Adjust before applying: <interfaces, IPs, subnets>
# Related best practice: best-practices/mikrotik/<guide>.md
# ============================================================
```

## Rules

- An example is a starting point — **always** adjust interfaces/IPs/subnets to the real host.
- Every change applied from here requires baseline + rollback (see `core/rules/connection-safety.md`).
- Register the example in `_index.yaml`.

## How to add one

Copy `_TEMPLATE/`, create the example in the vendor's syntax, register it in `_index.yaml`.
Seed content: `mikrotik/` and `linux/`. Other vendors: fill in as the project evolves.
