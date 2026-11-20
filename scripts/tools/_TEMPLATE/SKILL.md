---
id: script-name
name: Readable Script Name
type: script
runtime: python
description: One line — what the script does.
env: []
---

## What it does

Description of the problem the script solves.

## When to use

In which situation the agent should call this script.

## How to use

```bash
python3 scripts/<family>/<script>.py --option value
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--host-id` | one of the two | Integer ID in `network/hosts.yaml` |
| `--host` | one of the two | Unique hostname or legacy alias |

## Setup

Dependencies (already in `requirements.txt`) and external binaries, if any.

## Examples

```bash
python3 scripts/tools/<family>/<script>.py --host-id 1
```
