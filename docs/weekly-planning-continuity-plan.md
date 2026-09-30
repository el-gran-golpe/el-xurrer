# Plan: fechas reales por semana + continuidad narrativa Meta/Fanvue

## Contexto

Investigación (2 exploradores + 3 opiniones independientes: arquitecto, crítico YAGNI, estrategia de contenido) confirmó:

- **No hay aritmética de fechas en ningún sitio.** `get_closest_monday()` (`llm/utils/utils.py`) solo mete texto cosmético en el prompt, recalculado del reloj, nunca persistido. La clave de nivel superior del JSON de planning está **hardcodeada como el literal `"week_1"`** en el prompt de formato de salida — todos los `*_planning.json` reales lo confirman. `plan_job_id`/`_group_key` en `jobs/tasks.py` no tienen dimensión semana: replanear pisa el único plan existente.
- **`StorylineTracker.update_storyline()`** (`planning/storyline_tracker.py`) apéndiza un resumen a `initial_conditions.md` tras cada plan — y ese mismo fichero es uno de los dos inputs hasheados por `run_plan` para decidir "ya está hecho, no replanees". Como el fichero cambia en cada ejecución, ese hash nunca coincide entre invocaciones separadas de `jobs run`: el resume-skip está roto en la práctica, y una segunda ejecución sobre la misma semana la replanea entera (efecto observado por el usuario: "dos semanas para el mismo tiempo").
- **Meta y Fanvue del mismo perfil son totalmente independientes**: dos `initial_conditions.md`, dos `{profile}.json`, dos historiales de storyline que nunca se cruzan. Los hechos fijos de personaje (edad, backstory) están duplicados a mano casi verbatim. Más importante (según el análisis de estrategia de contenido): cada plataforma genera su semana de forma aislada, así que la influencer puede estar "en Lisboa" en Meta y "en Berlín" en Fanvue la misma semana — rompe la ilusión de continuidad para cualquier fan que siga ambas cuentas, justo el público que convierte a pago.

Decisiones tomadas con el usuario:
1. Clave de semana real ahora, y como `--weeks N` sale casi gratis una vez que el flujo semanal es correcto (ver más abajo), se incluye en este cambio.
2. Continuidad: backstory estático compartido entre Meta y Fanvue. El estado narrativo compartido **no** es parte de `plan` — ver sección 4.
3. El bug del hash roto se arregla aquí mismo, como consecuencia natural del rediseño (no como parche aparte).
4. **Capa repositorio primero.** Antes de tocar ninguna ruta o formato de fichero, se introduce la interfaz del repositorio con una implementación V1 sobre filesystem que mantiene el layout actual. Mismo patrón que `JobStore`/`Queue`/`GenerationBackend` en `docs/jobs-dag-plan.md`: interfaz pequeña + V1 concreta, migrable a otro backend (p.ej. una DB) sin tocar los consumidores. Ver sección 0 para lo que finalmente se entregó, que se desvió del boceto inicial en dos puntos.
5. **Alcance narrativo mínimo en esta primera pasada.** Solo se implementa lo que el comando `plan` ya usa hoy: la persona estática. Todo el estado narrativo (arco y capítulo) queda fuera, porque cada nivel es un comando con su propia cadencia — ver sección 4, reescrita tras descubrir en review que el primer intento colgaba el arco de una plataforma.

## Diseño

### 0. Capa repositorio para recursos de planning — HECHO

Entregado en `05c901e` (modelos), `273eef3` (repositorio) y `344a249` (consumidores). Se desvió
del boceto inicial en dos puntos, ambos a petición del usuario durante el review:

- **La interfaz habla de modelos de dominio, no de `Path`.** El boceto original devolvía la ruta
  del prompt template y el markdown de `initial_conditions.md` en crudo, con el planning como
  `dict`; así una DB no podría implementarla sin imitar ficheros. La versión entregada expone
  `get_platform_profile` → `PlatformProfile`, `get_week_plan`/`save_week_plan` → `WeekPlan`, y
  `add_storyline_summary(summary)` (el separador y el timestamp son detalle de almacenamiento, y
  pasaron al repositorio).
- **El repositorio absorbió `ProfileManager`.** Descubrir qué perfiles existen y leer sus ficheros
  de planning son el mismo trabajo — el árbol `resources/` en disco — así que
  `profiles/profile.py` desaparece y todo vive en `profiles/repository.py`. `Profile` se importa
  de `domain/types.py`, que es a donde apuntaba el re-export accidental. Esto adelanta lo que el
  plan aplazaba al paso 2.

Lo entregado:

- `domain/plans.py`: `WeekPlan` → `DayPlan` → `PostPlan` → `ImagePlan`, con
  `from_planning_dict`/`to_planning_dict` para la forma `{week: [días]}` que usan el fichero y la
  respuesta del LLM. `upload_time` sigue siendo `str` a propósito: tiparlo como datetime con
  offset convertiría un fallo de publicación en un fallo de planificación, y eso merece su propio
  commit.
- `domain/types.py`: `PlatformProfile` (lang + prompts validados + initial conditions).
- `profiles/repository.py`: `ProfileRepository` (`Protocol`) y `FilesystemProfileRepository`, con
  `resource_path: Path` como **parámetro obligatorio del constructor** — sin valor por defecto, para
  que ningún test pueda apuntar al `resources/` real por accidente. Los tests usan el helper
  `repository_for(profile)` del conftest sobre `tmp_path`.
- `BaseLLM` recibe los prompts ya validados en vez de una ruta JSON, que es lo que permite que el
  repositorio sea dueño de ese fichero: `load_and_prepare_prompts` pierde su mitad de carga y pasa
  a ser `prepare_prompts`.
- Se eliminó una lectura duplicada: la carga de perfiles ya parseaba cada `{profile}.json` y se
  quedaba solo el `lang`, tirando los prompts, mientras la planificación releía el mismo fichero.
  Ahora ambas pasan por `_read_profile_input`.

Dos cambios de comportamiento que conviene recordar al ejecutar:

- `run_plan` hashea los prompts validados en vez del texto crudo de los ficheros de entrada, así
  que el primer `jobs run` tras este cambio replanifica semanas ya marcadas como hechas.
- Los campos que ningún consumidor lee dejan de round-tripear al `*_planning.json` guardado.

Queda pendiente para los pasos siguientes: `persona.md`, `arcs/` y el archivado current/history.
- Detalle importante: las rutas nuevas (`persona.md`, `arcs/current.md`) las resuelve el
  repositorio a partir de `resources_root`/`profile.name`, **no** se cuelgan de
  `Profile.platform_info`. `PlatformInfo` (`domain/types.py`) valida con `field_validator` que sus
  `inputs_path`/`outputs_path` ya existan (`exists()`/`is_dir()`) en el momento de cargar perfiles
  (`profiles/repository.py::_gather_platforms`); si las rutas nuevas dependieran de ahí, cualquier
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

### 4. Persona compartida, y por qué el arco no entra aquí

**Corregido en review.** El primer intento hizo que `plan` escribiera `arcs/current.md` tras
planear, y que solo Meta lo hiciera, con Fanvue leyéndolo después. Eso ponía el nivel narrativo más
alto a depender de una plataforma y del orden de dos jobs. El error de fondo fue confundir dos
cosas distintas y guardarlas en el mismo fichero:

1. **Arco**: la intención narrativa. El nivel más alto, cadencia lenta, independiente de plataforma
   y también de `plan`.
2. **Recap semanal**: el resumen de lo que se acaba de planear. Derivado, por plataforma.

El arco es **entrada**, nunca salida de `plan`. El modelo acordado son tres niveles, cada uno con
su comando y su cadencia, y cada uno dependiendo solo del de encima:

```
arco      (cadencia lenta, p.ej. temporada)   — comando propio
  └─ chapter (cadencia media, mayor que semanal) — depende del arco
       └─ plan  (semanal)                        — depende del chapter
```

El arco puede tener en cuenta los planes anteriores si existe histórico, pero a priori es
independiente. Como `plan` depende del **chapter** y el chapter todavía no existe, `plan` tampoco
lee el arco: leerlo sería saltarse un nivel. Hasta que existan esos dos comandos, `plan` no tiene
continuidad automática entre semanas, y la continuidad Meta/Fanvue vendrá del chapter cuando
llegue.

Lo que sí entra en este plan:

- `resources/{profile}/persona.md`: hechos fijos de personaje (edad, backstory, descripción física base) — un solo fichero por perfil, ya no duplicado en los dos `{profile}.json`/`initial_conditions.md`. Se lee y se concatena al construir el prompt de ambas plataformas (mismo punto de integración que ya existe: `PlanningManager` arma hoy un `storyline: str` a partir de `initial_conditions.md` y se lo pasa a `BaseLLM` como `previous_storyline` — solo cambia qué texto se concatena ahí, no la mecánica). Incluido en el hash de la sección 3 (editarlo a mano es una señal intencional).
- **`StorylineTracker` desaparece.** Era lo único que escribía estado narrativo desde `plan`, y
  ahora sabemos que está en el nivel equivocado. Con él se va el bug del hash de la sección 3: al
  no escribir nadie dentro de `inputs/`, el hash de resume vuelve a ser estable sin ningún parche.
  `initial_conditions.md` vuelve a ser un fichero estático, editado a mano.

**Fuera de este plan, ahora con forma concreta:** los comandos de arco y de chapter, cada uno con
su cadencia y su fichero, y `plan` pasando a leer el chapter en vez de la persona a secas. Es un
camino nuevo, no un paso más de esta lista.

## Ficheros clave a tocar

- `apps/ai-content-pipeline/ai_content_pipeline/profiles/repository.py` — **hecho.** `ProfileRepository` (`Protocol`) + `FilesystemProfileRepository(resource_path: Path)`, ver sección 0. Los pasos 2-4 añaden métodos aquí (`get_persona`, `get_current_arc`/`save_arc`, resolución current-vs-history), no rutas nuevas en los consumidores.
- `apps/ai-content-pipeline/ai_content_pipeline/llm/utils/utils.py` — nueva función de fecha, retirar el uso puramente cosmético de `get_closest_monday()`.
- `apps/ai-content-pipeline/ai_content_pipeline/planning/planning_manager.py` — deja de tocar `Path` directamente y pasa a usar `PlanningResourcesRepository` (paso 1); después, leer/archivar planning existente en vez de sobreescribir sin más (paso 3); ensamblar `persona.md` + `arcs/current.md` + `initial_conditions.md` propio de la plataforma (paso 2).
- `apps/ai-content-pipeline/ai_content_pipeline/planning/storyline_tracker.py` — deja de tocar `Path` directamente (paso 1); después, cambiar destino de escritura (de apéndice en `initial_conditions.md` a sobreescritura de `arcs/current.md`, paso 2), condicionado a la plataforma que "posee" el arco.
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/tasks.py` — `plan_job_id` con dimensión semana, resolución current-vs-history en `_fan_out_images` (vía el repositorio, ver sección 2), y el cálculo de hash de `run_plan` (excluir `arcs/current.md`, incluir `persona.md`). `schedule_job_id` se deja tal cual, sin semana. Se toca en el paso 3-4, no en el paso 1 (repositorio).
- `apps/ai-content-pipeline/ai_content_pipeline/cli/commands/jobs.py` — opción `--weeks N` y `seed_plans` encolando un job `plan` por semana (no uno por perfil+plataforma).
- `apps/ai-content-pipeline/ai_content_pipeline/publishing/posting_scheduler.py` — **añadido tras revisar el código real de la rama DAG.** `_iter_day_folders` valida los nombres de carpeta de semana con la regex `^week_\d+$`; en cuanto la clave de nivel superior del planning (y por tanto el nombre de carpeta que usa `jobs/tasks.py:_fan_out_images`) pase a ser una fecha ISO, esa validación revienta con `ValueError: Invalid week folder name` y el scheduler deja de funcionar. Hay que adaptar el patrón a fechas ISO (o desacoplar el nombre de carpeta de la clave del JSON, pero el diseño actual los liga 1:1).
- `domain/types.py` — **no hace falta tocarlo para `persona.md`/`arcs/current.md`**: esas rutas las resuelve el repositorio desde su `resource_path` + `profile.name`, no desde `Profile.platform_info` (ver el porqué en la sección 0 — evita romper `load_profiles()` para perfiles aún no migrados).
- Migración manual de contenido para los perfiles existentes (`laura_vigne`, `maria_larsen`): extraer backstory de sus `initial_conditions.md`/`{profile}.json` actuales a `persona.md` nuevo, y sembrar `arcs/current.md` inicial — contenido curado, no automatizable, requiere aprobación explícita del usuario (regla de `AGENTS.md` sobre editar esos ficheros). Se hace en el paso 2, no en el paso 1.
- `AGENTS.md` — actualizar la nota de cadencia semanal para reflejar semanas con clave real, `--weeks N`, y la existencia de `persona.md`/`arcs/current.md` (instrucción del propio repo: agent instructions se actualizan en el mismo cambio que altera el flujo). Se hace al final, cuando el flujo completo esté validado.

## Orden de pasos

Cada paso deja `all.py`/`pipeline.py`/`jobs run` funcionando igual que antes de empezar el plan
(mismos ficheros, mismo comportamiento observable), igual que `docs/jobs-dag-plan.md` exige para
sus propios commits:

1. ~~**Repositorio**~~ — **HECHO** (`05c901e`, `273eef3`, `344a249`). Sin cambios de formato en
   disco. Probado contra un árbol bajo `tmp_path`, nunca contra el `resources/` real. Incluyó,
   adelantándose al paso 2, la absorción de `ProfileManager` dentro del repositorio.
2. **`persona.md`** — **HECHO** (`a99d4a6` inyección obligatoria del repositorio, y el commit de
   persona). `initial_conditions.md` se adelgaza y deja de recibir escrituras; `StorylineTracker`
   se elimina. Sin `arcs/` ni `chapters/`: son comandos aparte. Queda pendiente la migración manual
   de contenido de los perfiles existentes, que requiere aprobación explícita.
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

## Notas: acceso a disco que todavía no pasa por el repositorio

**Fuera del alcance de este plan.** Son observaciones recogidas al implementar la capa
repositorio, apuntadas aquí para no perderlas. Nada de esto se toca mientras duren los pasos 1-4;
es material para un roadmap posterior.

El repositorio es hoy la única fuente de verdad para *inputs de perfil* y para el fichero de
planning. El resto del árbol `resources/` — sobre todo `outputs/publications/` — se sigue
manipulando con `Path` desde varios sitios, cada uno con su propia copia del layout.

### 1. La estructura de publicaciones se escribe y se lee desde dos sitios distintos, sin contrato común

- `generation/publications_generator.py::DirectoryManager.create_structure` crea
  `outputs/publications/{week}/day_{n}/` y escribe `captions.txt` y `upload_times.txt`.
- `publishing/posting_scheduler.py::_iter_day_folders` recorre esas mismas carpetas, valida sus
  nombres con `^week_\d+$` / `^day_\d+$`, lee los dos ficheros y hace `glob` de
  `*.png`/`*.jpg`/`*.jpeg`.

Son el lado escritor y el lado lector del mismo formato, y ninguno lo declara: el contrato vive
implícito en dos módulos que no se conocen. Por eso el paso 3 de este plan tiene que acordarse de
tocar la regex de `_iter_day_folders` al cambiar la clave de semana — justo el tipo de acoplamiento
que el repositorio existe para eliminar. `_upload_profile` ya lleva un
`# TODO: should be this included in the Profile class?` en ese punto.

### 2. Rutas de salida construidas a mano en los consumidores

- `jobs/tasks.py`: `_outputs_dir`, `_publications_dir` y el nombre de cada imagen
  (`{slug}_{index}.jpeg`), además del `output_path.exists()` que decide saltarse una generación.
- `generation/publications_generator.py::ImageGeneratorService`: misma convención de nombre de
  imagen, resuelta por segunda vez.
- `cli/commands/all.py`: vacía `outputs/` con `rmtree` y comprueba si está vacío para
  `--no-overwrite-outputs`.

### 3. Otros sitios que conocen el layout de `resources/`

- `domain/types.py::PlatformInfo` valida con `exists()`/`is_dir()` que las rutas existan: un modelo
  de dominio comprobando disco. Sacarlo de ahí es lo que permitiría que el repositorio resuelva
  las rutas desde `resources_root` + nombre de perfil, en vez de recibirlas ya resueltas dentro del
  `Profile`.
- `integrations/google_drive/sync_resources.py` recorre el árbol por su cuenta (carpetas de perfil,
  `inputs/`, fichero de workflow). Ya toma prestadas `WORKFLOW_SUFFIX` y `PROFILE_NAME_REGEX` de
  `FilesystemProfileRepository`, señal de que comparten contrato pero no implementación.
- `integrations/comfyui/local.py` lee `{profile}_comfyworkflow.json`, un fichero cuya existencia
  valida el repositorio al cargar perfiles, pero que el repositorio no sirve.

### Hacia dónde apunta esto

El siguiente escalón natural, una vez cerrado este plan, es que el repositorio sirva también las
publicaciones como modelos (algo tipo `get_publications(profile, platform, week)` y
`save_publication_assets(...)`) en lugar de que cada consumidor recomponga rutas. Eso dejaría
`PostingScheduler` y `PublicationsGenerator` hablando de días y publicaciones, no de carpetas, y
haría que cambiar el nombre de una carpeta de semana fuera un cambio de un solo fichero.

No conviene hacerlo dentro de este plan: los pasos 1-4 ya cambian la clave de semana y el formato
de continuidad, y mezclar ambas cosas haría irrevisable el diff.
