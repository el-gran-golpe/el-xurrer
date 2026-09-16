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
4. **Capa repositorio primero, como refactor puro.** Antes de tocar cualquier ruta o formato de fichero, se introduce una interfaz `PlanningResourcesRepository` (prompt template, `initial_conditions.md`, guardar/leer planning, actualizar continuidad narrativa) con una implementación V1 sobre filesystem que reproduce 1:1 el comportamiento actual. Mismo patrón que `JobStore`/`Queue`/`GenerationBackend` en `docs/jobs-dag-plan.md`: interfaz pequeña + V1 concreta, migrable a otro backend (p.ej. una DB) más adelante sin tocar `PlanningManager`/`StorylineTracker`/`jobs/tasks.py`. Este commit no cambia ningún comportamiento observable — es lo que permite que `all.py`/`pipeline.py`/`jobs run` sigan funcionando exactamente igual mientras se construye el resto del plan encima.
5. **Alcance narrativo mínimo en esta primera pasada.** Solo se implementa lo que el comando `plan` ya usa hoy: persona estática + un arco activo, sin historial. `arcs/history/` (rollover trimestral) y `chapters/` (mensual, derivado del arco) quedan fuera de esta v1 — son conceptuales hasta que exista un comando que gestione esas cadencias; la interfaz del repositorio se diseña para poder añadirlos después sin reescribir los consumidores.

## Diseño

### 0. Capa repositorio para recursos de planning

- Interfaz `PlanningResourcesRepository` (`typing.Protocol`, mismo estilo que
  `jobs/generation_backend.py::GenerationBackend`), con los métodos que `PlanningManager.plan()` y
  `StorylineTracker` ya usan hoy contra `Path` directamente: ruta del prompt template, lectura de
  `initial_conditions.md`, guardar/leer el planning, y actualizar la continuidad narrativa (hoy
  apéndice a `initial_conditions.md`, más adelante sobrescritura de `arcs/current.md`).
- V1: `FilesystemPlanningResourcesRepository`, con `resources_root: Path` como **parámetro del
  constructor** (no una constante `RESOURCES_DIR` importada dentro de la clase) — permite apuntar
  a una copia en tests o a otra raíz en producción sin tocar el código del repositorio. Reproduce
  exactamente las rutas/formato actuales; no introduce `persona.md`/`arcs/`/archivado todavía —
  eso llega en los pasos siguientes, ya apoyados en esta interfaz.
- Detalle importante: las rutas nuevas (`persona.md`, `arcs/current.md`) las resuelve el
  repositorio a partir de `resources_root`/`profile.name`, **no** se cuelgan de
  `Profile.platform_info`. `PlatformInfo` (`domain/types.py`) valida con `field_validator` que sus
  `inputs_path`/`outputs_path` ya existan (`exists()`/`is_dir()`) en el momento de cargar perfiles
  (`profiles/profile.py::_gather_platforms`); si las rutas nuevas dependieran de ahí, cualquier
  perfil aún no migrado a la nueva estructura rompería `ProfileManager.load_profiles()`. Mantener
  esta resolución fuera de `Profile` es lo que permite migrar perfil a perfil sin tumbar la carga
  de perfiles ni el resto de comandos.

### 1. Clave de semana real (sustituye `"week_1"`)

- Nueva función en `llm/utils/utils.py`, p.ej. `next_planning_monday(existing_weeks: set[str]) -> date`: si hay semanas ya planeadas en el fichero de planning, devuelve el lunes siguiente a la última; si no hay ninguna, el lunes más próximo (reemplaza el rol de `get_closest_monday()`, que se elimina/se fusiona aquí). Representar la semana como fecha ISO del lunes (`"2026-09-21"`), no como número de semana ISO — evita casos raros de año/semana y es directamente ordenable y legible.
- El prompt de `json_friendly_posts` deja de instruir un literal `"week_1"`; se le pasa la fecha calculada (mismo mecanismo de sustitución `{day}` que ya existe) y se le pide que use esa fecha como clave del nivel superior.
- `{initials}_planning.json` sigue conteniendo **solo la semana actual**, igual que hoy — no se fusiona en un único fichero creciente. Antes de escribir la semana nueva como "current", si ya había una semana distinta como current (`week` != la que se va a planear), el repositorio la archiva a `outputs/history/{week}_planning.json`. Así cada fichero de planning es pequeño y su hash sigue siendo representativo de una sola semana — ver el porqué en la sección 2 (evita el bug de fan-in de una versión anterior de este plan que sí proponía fusionar).

### 2. Identidad de job por semana

- `plan_job_id` → `f"plan:{profile.name}:{platform.value}:{week}"`. Con esto, cada job `plan` planea **una sola semana**: `PlanningManager.plan()` deja de recibir "N semanas" de una vez y pasa a planear la semana concreta del job (fusionándola con lo ya presente en el fichero, punto 1). Esto da resumabilidad por semana gratis: si al pedir `--weeks 2` falla la llamada LLM de la semana 2, relanzar solo repite la semana 2 — la 1 ya quedó `DONE` en el `JobStore`.
- `jobs run` gana `--weeks N` (default 1): `seed_plans` calcula las N claves de semana por perfil+plataforma (con `next_planning_monday` sobre lo ya planeado) y encola **un job `plan` por semana**, no uno por perfil+plataforma como hoy. Como la cola de `plan` tiene `concurrency=1` (ya es así hoy), las semanas de un mismo perfil+plataforma se procesan en orden de encolado sin tocar el `Queue` — no hace falta ninguna dependencia nueva entre jobs.
- **`schedule_job_id` NO gana dimensión semana.** `_iter_day_folders` (`publishing/posting_scheduler.py`) ya recorre todas las carpetas de semana bajo `publications/` en una sola llamada a `PostingScheduler.upload()`, así que sigue siendo un `schedule` por perfil+plataforma, igual que hoy. Solo `plan` y el contador fan-in (punto siguiente) necesitan la dimensión semana.
- **Contador fan-in: resuelto por diseño gracias al archivado current/history (punto 1), no por un hash parcial.** Una versión anterior de este plan proponía fusionar todas las semanas en un único `planning.json` creciente; eso rompía el fan-in porque `_group_key`/`_fan_out_images` hashean y cuentan el fichero **completo** (`_hash(planning_path.read_text(...))`, `len(children)` sobre `planning.items()`), así que cada replan generaba un contador nuevo inicializado con imágenes de semanas antiguas que nunca se reencolan para decrementarlo. Con archivado current/history, `{initials}_planning.json` vuelve a contener una sola semana — igual que hoy — así que `_group_key`/`_fan_out_images` no necesitan cambiar su forma de hashear/contar en absoluto.
- **Matiz real que sí introduce el archivado:** `run_plan`/`_fan_out_images` para el job de una semana concreta ya no pueden asumir que "el" `{initials}_planning.json` es esa semana — puede haberse archivado ya a `history/` porque este mismo `--weeks N` planeó una semana posterior primero. Hace falta una resolución (vía el repositorio de la sección 0) que compruebe si la semana pedida es la actual o ya está en `history/`, para que reanudar un job de una semana ya archivada siga leyendo el fichero correcto.

### 3. Arreglo del hash de resume (efecto colateral de lo anterior)

- El hash de "¿ya está hecho, no replanees?" pasa a calcularse solo sobre contenido **estático** (prompt template + backstory compartido, ver punto 4) — nunca sobre el estado narrativo que el propio plan actualiza como efecto (punto 4). Así, planear la semana 2 no invalida el hash de la semana 1, y volver a lanzar `jobs run` el mismo día no dispara un replan espurio.
- `StorylineTracker` deja de escribir dentro de `initial_conditions.md` (que vuelve a ser un fichero puramente estático, editado a mano, con la semántica de "cambios aquí sí deben afectar a semanas aún no planeadas" ya documentada en `run_plan`). Su salida se redirige al fichero nuevo del punto 4.

### 4. Backstory + arco narrativo compartidos entre Meta y Fanvue

- `resources/{profile}/persona.md`: hechos fijos de personaje (edad, backstory, descripción física base) — un solo fichero por perfil, ya no duplicado en los dos `{profile}.json`/`initial_conditions.md`. Se lee y se concatena al construir el prompt de ambas plataformas (mismo punto de integración que ya existe: `PlanningManager` arma hoy un `storyline: str` a partir de `initial_conditions.md` y se lo pasa a `BaseLLM` como `previous_storyline` — solo cambia qué texto se concatena ahí, no la mecánica). Incluido en el hash de la sección 3 (editarlo a mano es una señal intencional).
- `resources/{profile}/arcs/current.md`: estado rotativo pequeño en markdown (ubicación/temporada actual, hilo narrativo activo, últimos 1-2 eventos), **no** un log que crece sin fin — sustituye la idea original de `narrative_arc.json` (JSON) por el formato markdown del boceto de reestructuración de `resources/`. Se actualiza tras planear cada semana usando la misma llamada LLM de resumen que ya hace `StorylineTracker` hoy, pero sobreescribiendo el fichero en vez de apendizar. Se lee (igual que persona.md) al construir el prompt de ambas plataformas, para que la semana de Fanvue sea consistente con lo que le pasó a la influencer esa semana en Meta. Excluido del hash de la sección 3 a propósito.
- **Fuera de esta v1, explícitamente diferido:** `arcs/history/{year}_q{n}.md` (archivar el arco al rotar de trimestre) y `chapters/current.md`+`chapters/history/` (una capa mensual de beats concretos derivados del arco). Son conceptuales hasta que exista un comando que gestione esas cadencias (trimestral/mensual) — no las necesita el comando `plan` tal como existe hoy. La interfaz del repositorio (sección 0) se diseña para poder añadirlas después sin reescribir `PlanningManager`/`StorylineTracker`.
- **Decisión de diseño abierta, con valor por defecto propuesto**: solo Meta actualiza `arcs/current.md` tras su plan (es la capa "pública"/canónica según el análisis de estrategia — Fanvue reinterpreta esos mismos hechos en su propio tono, no genera hechos nuevos). Fanvue solo lee. Evita duplicar/mezclar dos resúmenes del mismo evento y no requiere ninguna sincronización nueva en el DAG. Fácil de cambiar después (una constante `Platform.META` en un solo sitio).
- `StorylineTracker._extract_all_captions` hoy itera `planning_data.items()` (el fichero **completo**) para generar el resumen. Con el archivado current/history (punto 1), esto deja de ser un problema por sí solo porque el fichero current vuelve a tener una sola semana — pero conviene revisar que, tras el cambio, se siga resumiendo solo la semana recién planeada y no una que quedó archivada por error.

## Ficheros clave a tocar

- `apps/ai-content-pipeline/ai_content_pipeline/planning/resources_repository.py` — **nuevo.** Interfaz `PlanningResourcesRepository` (`Protocol`) + `FilesystemPlanningResourcesRepository(resources_root: Path)`, ver sección 0. Se implementa primero, como refactor puro.
- `apps/ai-content-pipeline/ai_content_pipeline/llm/utils/utils.py` — nueva función de fecha, retirar el uso puramente cosmético de `get_closest_monday()`.
- `apps/ai-content-pipeline/ai_content_pipeline/planning/planning_manager.py` — deja de tocar `Path` directamente y pasa a usar `PlanningResourcesRepository` (paso 1); después, leer/archivar planning existente en vez de sobreescribir sin más (paso 3); ensamblar `persona.md` + `arcs/current.md` + `initial_conditions.md` propio de la plataforma (paso 2).
- `apps/ai-content-pipeline/ai_content_pipeline/planning/storyline_tracker.py` — deja de tocar `Path` directamente (paso 1); después, cambiar destino de escritura (de apéndice en `initial_conditions.md` a sobreescritura de `arcs/current.md`, paso 2), condicionado a la plataforma que "posee" el arco.
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/tasks.py` — `plan_job_id` con dimensión semana, resolución current-vs-history en `_fan_out_images` (vía el repositorio, ver sección 2), y el cálculo de hash de `run_plan` (excluir `arcs/current.md`, incluir `persona.md`). `schedule_job_id` se deja tal cual, sin semana. Se toca en el paso 3-4, no en el paso 1 (repositorio).
- `apps/ai-content-pipeline/ai_content_pipeline/cli/commands/jobs.py` — opción `--weeks N` y `seed_plans` encolando un job `plan` por semana (no uno por perfil+plataforma).
- `apps/ai-content-pipeline/ai_content_pipeline/publishing/posting_scheduler.py` — **añadido tras revisar el código real de la rama DAG.** `_iter_day_folders` valida los nombres de carpeta de semana con la regex `^week_\d+$`; en cuanto la clave de nivel superior del planning (y por tanto el nombre de carpeta que usa `jobs/tasks.py:_fan_out_images`) pase a ser una fecha ISO, esa validación revienta con `ValueError: Invalid week folder name` y el scheduler deja de funcionar. Hay que adaptar el patrón a fechas ISO (o desacoplar el nombre de carpeta de la clave del JSON, pero el diseño actual los liga 1:1).
- `apps/ai-content-pipeline/ai_content_pipeline/profiles/profile.py` / `domain/types.py` — **no hace falta tocarlos para `persona.md`/`arcs/current.md`**: esas rutas las resuelve el repositorio de la sección 0 directamente desde `resources_root`/`profile.name`, no `Profile.platform_info` (ver el porqué en la sección 0 — evita romper `ProfileManager.load_profiles()` para perfiles no migrados).
- Migración manual de contenido para los perfiles existentes (`laura_vigne`, `maria_larsen`): extraer backstory de sus `initial_conditions.md`/`{profile}.json` actuales a `persona.md` nuevo, y sembrar `arcs/current.md` inicial — contenido curado, no automatizable, requiere aprobación explícita del usuario (regla de `AGENTS.md` sobre editar esos ficheros). Se hace en el paso 2, no en el paso 1.
- `AGENTS.md` — actualizar la nota de cadencia semanal para reflejar semanas con clave real, `--weeks N`, y la existencia de `persona.md`/`arcs/current.md` (instrucción del propio repo: agent instructions se actualizan en el mismo cambio que altera el flujo). Se hace al final, cuando el flujo completo esté validado.

## Orden de pasos

Cada paso deja `all.py`/`pipeline.py`/`jobs run` funcionando igual que antes de empezar el plan
(mismos ficheros, mismo comportamiento observable), igual que `docs/jobs-dag-plan.md` exige para
sus propios commits:

1. **Repositorio** (`resources_repository.py` + refactor de `planning_manager.py`/
   `storyline_tracker.py` para usarlo) — refactor puro, sin cambiar ningún fichero ni formato en
   disco. Probado contra una copia de `resources/` bajo `tmp_path` (mismo patrón que
   `tests/jobs/conftest.py::make_profile`), nunca contra el `resources/` real.
2. **`persona.md` + `arcs/current.md`** (sin `history/`, sin `chapters/`) — `initial_conditions.md`
   se adelgaza, `StorylineTracker` escribe al arco en vez de apendizar. Migración manual de
   contenido de los perfiles existentes.
3. **Semana real + archivado current/history** (secciones 1-3 del diseño).
4. **Identidad de job por semana / `--weeks N`** (sección 2), que ya encaja de forma natural sobre
   los pasos 1-3.

## Verificación

- Test del repositorio filesystem (paso 1): round-trip de cada método contra una copia en
  `tmp_path`, y que el commit de este paso no cambia ningún test existente de comportamiento
  observable (`all.py`/`pipeline.py`/`jobs run` sin cambios).
- Tests unitarios nuevos/actualizados en `apps/ai-content-pipeline/tests/`: cálculo de la siguiente semana (incluyendo el caso "sin semanas previas" y "última semana ya presente"), resolución current-vs-history sin pisar semanas archivadas, identidad de job por semana en `tasks.py`, y que editar `arcs/current.md` NO invalide el hash de una semana ya `DONE` mientras que editar `persona.md` sí.
- Test específico de la resolución current/history: encolar dos semanas seguidas para el mismo perfil+plataforma (`--weeks 2` en dos runs separados o en uno solo) y confirmar que el contador de fan-in de la segunda semana llega a 0 y dispara `schedule` solo, y que reanudar el job de la primera semana (ya archivada) la sigue encontrando en `history/`.
- Test para `posting_scheduler.py:_iter_day_folders` con una carpeta de semana nombrada como fecha ISO (`"2026-09-21"`), confirmando que ya no la rechaza como nombre de carpeta inválido.
- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest -q`.
- Prueba manual con `--skip-schedule --weeks 2` sobre un perfil, confirmando: dos semanas distintas archivadas correctamente en `outputs/`/`outputs/history/` (claves de fecha reales, no `"week_1"` repetido), `arcs/current.md` actualizado tras la semana de Meta antes de que arranque la de Fanvue, y una segunda ejecución del mismo comando sin cambios no vuelve a replanear nada ya hecho.
