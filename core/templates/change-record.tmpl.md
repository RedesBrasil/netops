# Registro de Mudança — <host>

> Modelo. O `documenter` preenche os campos `<...>` e salva em `reports/<data>-change-<host>.md`.

- **Data:** <YYYY-MM-DD HH:MM>
- **Execução:** <runs/ID>
- **Host:** <host> (<fabricante> · <modelo>)
- **Objetivo:** <o que a mudança visava>
- **Resultado:** <SUCESSO / REVERTIDO / PARCIAL>

## O que mudou

<descrição da mudança em linguagem clara.>

## Diff aplicado

```
<saída de scripts/analysis/config_diff.py — before x after>
```

## Verificação pós-mudança

<o que o `tester` confirmou: efeito esperado, conectividade preservada.>

## Rollback

- **Disponível em:** <runs/ID/proposals/<host>.rollback.txt>
- **Executado?** <não / sim — motivo>

## Lições

<o que foi aprendido — também registrado em memory/MEMORY.md.>

---
_Gerado pelo NetOps — agente `documenter`._
