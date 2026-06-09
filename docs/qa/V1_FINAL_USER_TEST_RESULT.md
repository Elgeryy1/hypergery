# Resultado de la prueba final de usuario — HyperGery v1.0

> Plantilla. Rellenar siguiendo `docs/qa/V1_FINAL_USER_TEST_PLAN.md`.

| Campo | Valor |
|---|---|
| Fecha de ejecución | |
| Rama probada | `feature/v1.1-ux` @ commit `____` |
| Versión reportada por la app | |
| PC sobremesa | gerard-MS-7E26 |
| Portátil | gery-Lenovo-ideapad-330S-14IKB |
| Hub | http://192.168.1.150:8765 |
| Duración total | |

**Leyenda resultado:** PASS / FAIL / BLOCKED / SKIP — **Severidad:** BLOCKER / mayor / menor / polish

---

## A — Preparación

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| A1 Rama feature/v1.1-ux | | | | |
| A2 Versión 1.0.0rc1 | | | | |
| A3 Hub /health ok | | | | |
| A4 Dos agentes online y al día | | | | |
| A6 Doctor PC todo OK | | | | |
| A6 Doctor portátil todo OK | | | | |

## B — App abierta en ambos equipos

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| B1 Arranque UI en PC | | 01 | | |
| B2 Arranque UI en portátil | | 02 | | |
| B3 Hosts/VMs/Hub/NAS coherentes en ambas | | 03 | | |
| B4 Se entiende sin documentación | | | | |

## C — Revisión visual

| Pantalla | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| Inicio (dashboard) | | | | |
| Máquinas virtuales | | | | |
| Laboratorios | | | | |
| Plantillas | | | | |
| Otros equipos | | | | |
| Migraciones | | | | |
| Tareas remotas | | | | |
| Centro de control | | 04 | | |
| Diagnóstico | | | | |
| Ajustes | | 10 | | |
| Consola integrada | | 05 | | |
| Diálogos de confirmación | | | | |
| Mensajes de error | | | | |
| Tooltips y ayudas | | | | |

## D — Idioma y humanización

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| Sin inglés visible | | | | |
| Sin textos demasiado técnicos | | | | |
| Sin JSON crudo fuera de zonas técnicas | | | | |
| Botones comprensibles | | | | |
| Errores que dicen qué hacer | | | | |

Textos concretos detectados (pantalla → texto → propuesta):

| Pantalla | Texto actual | Problema | Propuesta | Destino (v1.0.1/v1.1) |
|---|---|---|---|---|
| | | | | |

## E — Flujo usuario normal

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| E1 Ver lab | | | | |
| E2 Ver VM | | | | |
| E3 Consola: conectar/capturar/soltar | | 05 | | |
| E4 Cerrar consola no apaga; apagado suave OK | | | | |
| E5 Logs legibles | | | | |
| E6 Estado se actualiza solo entre equipos | | | | |

## F — NAS

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| F1 Commit dry-run | | | | |
| F2 Commit real (commit_id: ______) | | | | |
| F3 Restore a /tmp con verified: true | | 08 | | |
| F4 No sobrescribe destino existente | | | | |
| F5 Commit visible en la UI | | | | |

## G — Teleport

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| G1 Dry-run PC → portátil | | | | |
| G2 Loopback | | | | |
| G3 Host→host real desde la UI | | 06, 07 | | |
| G4 Origen intacto | | | | |
| G5 Destino con UUID/MAC nuevos | | | | |
| G6 Staging limpio | | | | |

## H — Errores controlados

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| H1 Agente portátil offline | | | | |
| H2 Hub no disponible | | | | |
| H3 NAS staging malo | | 09 | | |
| H4 Target offline en preflight | | | | |
| H5 Cancelar acción destructiva no hace nada | | | | |
| Sin tracebacks en ningún caso | | | | |

## I — save_restore

| Prueba | Resultado | Evidencia/captura | Notas | Severidad |
|---|---|---|---|---|
| I1–I3 La VM continúa en destino (no reinicia) | | | | |
| I4 Si falla: origen se reanuda solo | | | | |
| I5 Mensaje comprensible | | | | |
| I6 No se vende como live migration | | | | |

---

## Capturas obligatorias

| Nº | Captura | Archivo en docs/qa/evidence/ | Hecha |
|---|---|---|---|
| 01 | Dashboard en PC | | ☐ |
| 02 | Dashboard en portátil | | ☐ |
| 03 | Otros equipos, ambos online | | ☐ |
| 04 | Centro de control | | ☐ |
| 05 | Consola integrada traducida | | ☐ |
| 06 | Preflight de teleport | | ☐ |
| 07 | Teleport completado | | ☐ |
| 08 | NAS commit/restore verified true | | ☐ |
| 09 | Error controlado sin traceback | | ☐ |
| 10 | Ajustes / estado Hub y NAS | | ☐ |

## Comandos ejecutados

> Pegar aquí los comandos reales con su salida resumida (o referencia a un log).

```
```

## Bugs encontrados

| # | Bloque | Descripción | Severidad | Reproducción | Destino (bloqueante v1 / v1.0.1 / v1.1) |
|---|---|---|---|---|---|
| 1 | | | | | |

## Veredicto

- **Bloqueantes para v1 final:**
  - (ninguno / lista)
- **Para v1.0.1:**
  - (lista)
- **Polish para v1.1:**
  - (lista)

### Decisión final

**APTO / NO APTO** para publicar v1.0 final: ________

Justificación (2–3 líneas):

### Firma de Gerard

| Campo | Valor |
|---|---|
| Nombre | Gerard |
| Fecha | |
| Firma / OK | |
