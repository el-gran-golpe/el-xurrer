# Plan: fechas reales por semana + continuidad narrativa Meta/Fanvue

## Contexto

Investigación (2 exploradores + 3 opiniones independientes: arquitecto, crítico YAGNI, estrategia de contenido) confirmó:

- **No hay aritmética de fechas en ningún sitio.** `get_closest_monday()` (`llm/utils/utils.py`) solo mete texto cosmético en el prompt, recalculado del reloj, nunca persistido. La clave de nivel superior del JSON de planning está **hardcodeada como el literal `"week_1"`** en el prompt de formato de salida — todos los `*_planning.json` reales lo confirman. `plan_job_id`/`_group_key` en `jobs/tasks.py` no tienen dimensión semana: replanear pisa el único plan existente.
- **`StorylineTracker.update_storyline()`** (`planning/storyline_tracker.py`) apéndiza un resumen a `initial_conditions.md` tras cada plan — y ese mismo fichero es uno de los dos inputs hasheados por `run_plan` para decidir "ya está hecho, no replanees". Como el fichero cambia en cada ejecución, ese hash nunca coincide entre invocaciones separadas de `jobs run`: el resume-skip está roto en la práctica, y una segunda ejecución sobre la misma semana la replanea entera (efecto observado por el usuario: "dos semanas para el mismo tiempo").
- **Meta y Fanvue del mismo perfil son totalmente independientes**: dos `initial_conditions.md`, dos `{profile}.json`, dos historiales de storyline que nunca se cruzan. Los hechos fijos de personaje (edad, backstory) están duplicados a mano casi verbatim. Más importante (según el análisis de estrategia de contenido): cada plataforma genera su semana de forma aislada, así que la influencer puede estar "en Lisboa" en Meta y "en Berlín" en Fanvue la misma semana — rompe la ilusión de continuidad para cualquier fan que siga ambas cuentas, justo el público que convierte a pago.

Decisiones tomadas con el usuario:
1. Clave de semana real ahora, y como `--weeks N` sale casi gratis una vez que el flujo semanal es correcto (ver más abajo), se incluye en este cambio.
2. Continuidad: backstory estático compartido + arco narrativo semanal compartido entre Meta y Fanvue.
3. El bug del hash roto se arregla aquí mismo, como consecuencia natural del rediseño (no como parche aparte).

## Diseño

### 1. Clave de semana real (sustituye `"week_1"`)

- Nueva función en `llm/utils/utils.py`, p.ej. `next_planning_monday(existing_weeks: set[str]) -> date`: si hay semanas ya planeadas en el fichero de planning, devuelve el lunes siguiente a la última; si no hay ninguna, el lunes más próximo (reemplaza el rol de `get_closest_monday()`, que se elimina/se fusiona aquí). Representar la semana como fecha ISO del lunes (`"2026-09-21"`), no como número de semana ISO — evita casos raros de año/semana y es directamente ordenable y legible.
- El prompt de `json_friendly_posts` deja de instruir un literal `"week_1"`; se le pasa la fecha calculada (mismo mecanismo de sustitución `{day}` que ya existe) y se le pide que use esa fecha como clave del nivel superior.
- `{initials}_planning.json` deja de sobreescribirse entero: se lee el existente, se calculan las N semanas siguientes a partir de la última clave presente, se llama al LLM una vez por semana nueva, y se fusiona el resultado en el dict existente (no se tocan las semanas ya presentes).

### 2. Identidad de job por semana

- `plan_job_id` → `f"plan:{profile.name}:{platform.value}:{week}"`; `_group_key` → añade `week`. `_fan_out_images` ya itera `planning.items()`, así que solo cambia a fanear por la(s) semana(s) pedidas en vez de "lo que haya en el fichero".
- `jobs run` gana `--weeks N` (default 1): `seed_plans` calcula las N claves de semana por perfil+plataforma y encola un job de plan por cada una. Como la cola de `plan` tiene `concurrency=1` (ya es así hoy), las semanas de un mismo perfil+plataforma se procesan en orden de encolado sin tocar el `Queue` — no hace falta ninguna dependencia nueva entre jobs.

### 3. Arreglo del hash de resume (efecto colateral de lo anterior)

- El hash de "¿ya está hecho, no replanees?" pasa a calcularse solo sobre contenido **estático** (prompt template + backstory compartido, ver punto 4) — nunca sobre el estado narrativo que el propio plan actualiza como efecto (punto 4). Así, planear la semana 2 no invalida el hash de la semana 1, y volver a lanzar `jobs run` el mismo día no dispara un replan espurio.
- `StorylineTracker` deja de escribir dentro de `initial_conditions.md` (que vuelve a ser un fichero puramente estático, editado a mano, con la semántica de "cambios aquí sí deben afectar a semanas aún no planeadas" ya documentada en `run_plan`). Su salida se redirige al fichero nuevo del punto 4.

### 4. Backstory + arco narrativo compartidos entre Meta y Fanvue

- `resources/{profile}/persona.md`: hechos fijos de personaje (edad, backstory, descripción física base) — un solo fichero por perfil, ya no duplicado en los dos `{profile}.json`/`initial_conditions.md`. Se lee y se concatena al construir el prompt de ambas plataformas (mismo punto de integración que ya existe: `PlanningManager` arma hoy un `storyline: str` a partir de `initial_conditions.md` y se lo pasa a `BaseLLM` como `previous_storyline` — solo cambia qué texto se concatena ahí, no la mecánica). Incluido en el hash de la sección 3 (editarlo a mano es una señal intencional).
- `resources/{profile}/narrative_arc.json`: estado rotativo pequeño (ubicación/temporada actual, hilo narrativo activo, últimos 1-2 eventos), **no** un log que crece sin fin. Se actualiza tras planear cada semana usando la misma llamada LLM de resumen que ya hace `StorylineTracker` hoy, pero sobreescribiendo el estado en vez de apendizar. Se lee (igual que persona.md) al construir el prompt de ambas plataformas, para que la semana de Fanvue sea consistente con lo que le pasó a la influencer esa semana en Meta. Excluido del hash de la sección 3 a propósito.
- **Decisión de diseño abierta, con valor por defecto propuesto**: solo Meta actualiza `narrative_arc.json` tras su plan (es la capa "pública"/canónica según el análisis de estrategia — Fanvue reinterpreta esos mismos hechos en su propio tono, no genera hechos nuevos). Fanvue solo lee. Evita duplicar/mezclar dos resúmenes del mismo evento y no requiere ninguna sincronización nueva en el DAG. Fácil de cambiar después (una constante `Platform.META` en un solo sitio).

## Ficheros clave a tocar

- `apps/ai-content-pipeline/ai_content_pipeline/llm/utils/utils.py` — nueva función de fecha, retirar el uso puramente cosmético de `get_closest_monday()`.
- `apps/ai-content-pipeline/ai_content_pipeline/planning/planning_manager.py` — leer/fusionar planning existente en vez de sobreescribir; ensamblar `persona.md` + `narrative_arc.json` + `initial_conditions.md` propio de la plataforma.
- `apps/ai-content-pipeline/ai_content_pipeline/planning/storyline_tracker.py` — cambiar destino de escritura (de apéndice en `initial_conditions.md` a sobreescritura de `narrative_arc.json`), condicionado a la plataforma que "posee" el arco.
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/tasks.py` — `plan_job_id`, `_group_key`, `_fan_out_images`, y el cálculo de hash de `run_plan` (excluir `narrative_arc.json`, incluir `persona.md`).
- `apps/ai-content-pipeline/ai_content_pipeline/cli/commands/jobs.py` — opción `--weeks N` y bucle de `seed_plans` por semana.
- `apps/ai-content-pipeline/ai_content_pipeline/profiles/profile.py` / `domain/types.py` — solo si hace falta exponer la ruta de `persona.md`/`narrative_arc.json` en `Profile`/`PlatformInfo` (probablemente sí, como rutas nuevas a nivel de perfil, no de plataforma).
- `AGENTS.md` — actualizar la nota de cadencia semanal para reflejar semanas con clave real, `--weeks N`, y la existencia de `persona.md`/`narrative_arc.json` (instrucción del propio repo: agent instructions se actualizan en el mismo cambio que altera el flujo).

## Verificación

- Tests unitarios nuevos/actualizados en `apps/ai-content-pipeline/tests/`: cálculo de la siguiente semana (incluyendo el caso "sin semanas previas" y "última semana ya presente"), fusión de planning sin pisar semanas existentes, identidad de job por semana en `tasks.py`, y que editar `narrative_arc.json` NO invalide el hash de una semana ya `DONE` mientras que editar `persona.md` sí.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest -q`.
- Prueba manual con `--skip-schedule --weeks 2` sobre un perfil, confirmando: dos semanas distintas en el `_planning.json` (claves de fecha reales, no `"week_1"` repetido), `narrative_arc.json` actualizado tras la semana de Meta antes de que arranque la de Fanvue, y una segunda ejecución del mismo comando sin cambios no vuelve a replanear nada ya hecho.
