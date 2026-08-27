# DAG local con checkpoint (plan → generate → schedule), listo para Redis después

## Contexto

`IMPROVEMENT_ROADMAP.md` marcaba como prioridad #1 y #2 la resumabilidad
(checkpoint) y el paralelismo real vía DAG para `plan`/`generate`/`schedule`,
señalando que ambas comparten la misma pieza de fondo: estado de nodo
`pending/done/failed` persistido por unidad de trabajo, en vez de los bucles
`for profile in profiles` actuales (`all.py:_execute_all`,
`pipeline.py:plan/generate`).

El usuario planteó ir más allá: un modelo productor/consumidor con encolado
real (plan encola tareas de generate, generate encola de schedule) para poder
repartir ejecución entre máquinas distintas — confirmó que tener la GPU de
ComfyUI en otra máquina es una necesidad real y cercana, no solo aspiracional.

**Decisión revisada tras discutirlo:** no añadir Redis todavía. Dos motivos:

1. **El alivio inmediato (GPU en otra máquina) no necesita ninguna cola.**
   `ComfyLocal` (`integrations/comfyui/local.py`) ya habla HTTP/websocket
   contra `settings.comfy_host`/`comfy_port` (`config.py`). Apuntar esa
   variable a la IP de la máquina con GPU ya mueve la generación de imágenes
   fuera del PC orquestador, hoy, sin escribir código. Esto se hace aparte de
   este plan, es solo cambiar `.env`.
2. **Lo que sí falta (resumir sin repetir trabajo + no bloquear
   secuencialmente) se resuelve en un solo proceso.** Un pool distribuido de
   verdad (varias máquinas ejecutando jobs, resiliente a que el orquestador
   se caiga) solo se justifica si además de mover la GPU quieres que el
   *propio orquestador* corra como varios workers independientes — eso no es
   la necesidad de hoy.

Además, se comentó llevar la generación de imágenes a un cluster HPC (SLURM,
p.ej. acceso de la UPC) en vez de a un PC con GPU propio. Ahí el punto de
ejecución no es solo "otra IP" sino "otro mecanismo por completo" (SSH +
`sbatch`, agrupar N imágenes en un solo job por el coste de cargar el
checkpoint, recoger el resultado desde storage compartido). Para que ese
salto tampoco obligue a reescribir, la ejecución de una imagen también se
aísla detrás de su propia interfaz.

Para no tirar el trabajo si más adelante hace falta pool distribuido y/o HPC,
el DAG se construye detrás de **tres interfaces pequeñas** en vez de
acoplarse a estructuras en memoria o a `ComfyLocal` directamente:

- **`JobStore`** — `get_status`/`mark_running`/`mark_done`/`mark_failed`,
  `params_hash` (para invalidar `generate` hijos si el `plan` padre cambió), y
  un contador fan-in atómico (cuántas imágenes de un perfil+plataforma faltan
  antes de disparar `schedule`). V1: SQLite local (una tabla, `sqlite3` de
  stdlib — sin ORM, sin dependencia nueva), con la ruta del fichero como
  parámetro de configuración (no hardcodeada), para poder apuntarla a
  storage compartido más adelante sin tocar código. Migración futura a
  Redis: cambiar la implementación de la interfaz, mismas firmas.
- **`Queue`** — `enqueue(job)` / próximo job listo para correr, **y** una
  variante "dame hasta N jobs listos de este tipo" (no solo de uno en uno),
  para que un backend futuro pueda agrupar varias `generate_image` en un
  solo envío (SLURM) sin cambiar el loop. V1: cola en memoria
  (`asyncio.Queue`) consumida por un loop de workers `asyncio.gather`. La
  concurrencia por tipo de job **la decide quien implementa el backend de
  ese tipo, no la `Queue`** (p.ej. `LocalComfyBackend` pide concurrencia 1
  porque es una sola GPU local; un futuro `SlurmComfyBackend` pediría otra
  cosa, porque SLURM ya serializa el acceso a GPU). `plan` mantiene
  concurrencia 1 por el riesgo ya documentado de `ModelRouter._key_cursor`
  no siendo thread-safe; `schedule` sin límite adicional, ya usa
  `asyncio.gather` internamente en `PostingScheduler.upload()`. Migración
  futura: sustituir por RQ + Redis (funciones de job ya serán planas y con
  argumentos serializables, que es justo lo que RQ necesita).
- **`GenerationBackend`** — `generate(spec, output_path) -> None`, con el
  contrato "al terminar, el fichero existe en `output_path` (ruta local)",
  sin importar dónde se computó. V1: `LocalComfyBackend`, que es exactamente
  el `ComfyLocal` de hoy (`integrations/comfyui/local.py`,
  `settings.comfy_host/comfy_port` — ya apuntable a otra máquina vía
  `.env` sin tocar esto). Un futuro `SlurmComfyBackend` implementaría lo
  mismo por SSH + `sbatch`, incluyendo el rsync/scp de vuelta, dentro del
  backend — el resto del DAG no se entera.

Con esas tres interfaces fijas, pasar a Redis/RQ y/o a un backend HPC más
adelante es un cambio de implementación, no una reescritura: la lógica de
fan-out/fan-in (`plan` → imágenes → `schedule`) y las funciones de job no
cambian.

## Alcance de esta v1

- **Sí:** DAG con 3 tipos de nodo — `plan` (por perfil+plataforma),
  `generate_image` (uno por imagen — la unidad que ya usa el skip-if-exists
  de `ImageGeneratorService.generate_images` en
  `generation/publications_generator.py:79-98`), `schedule` (por
  perfil+plataforma).
- **Sí:** `schedule` depende de que **todas** las `generate_image` de ese
  perfil+plataforma estén `done` — y transitivamente de `plan`, porque
  `run_plan` es quien crea esos hijos (ver corrección más abajo: los
  artefactos de texto que `schedule` necesita —`captions.txt`/
  `upload_times.txt`— se generan dentro de `run_plan`, no dentro de
  `generate_image`, así que no hacen falta dos condiciones separadas).
- **Sí:** interfaz `GenerationBackend` con `LocalComfyBackend` como única
  implementación en v1 (mismo comportamiento que hoy, mismo
  `settings.comfy_host/comfy_port`) — ver arriba.
- **Sí:** checkpoint real — estado persistido en SQLite
  (`resources/.pipeline_state.db` o similar, fuera de lo que sincroniza
  Drive), así que reanudar tras Ctrl+C/caída de ComfyUI/corte de red es
  re-lanzar el mismo comando y que salte los nodos ya `done`.
- **Sí:** paralelismo real entre perfiles para `plan` y `generate` (hoy
  bloqueante y secuencial en `all.py:_execute_all` / `pipeline.py:20-27`),
  limitado únicamente por los semáforos de recurso compartido.
- **No (diferido explícitamente):**
  - Redis/RQ y ejecución multi-máquina del propio orquestador — se añade
    después, solo si hace falta un pool resiliente además de mover la GPU.
  - `SlurmComfyBackend` / integración HPC (UPC) real — se implementa cuando
    haya acceso confirmado; v1 solo dedica un asiento en la interfaz.
  - Paralelismo *dentro* de un job de `plan` (múltiples workers de plan a la
    vez) — bloqueado por el riesgo ya documentado de `ModelRouter`; en v1 la
    cola de `plan` tiene concurrencia 1 igual que hoy, solo que ya no bloquea
    a `generate`/`schedule` de otros perfiles mientras corre.
  - Checkpoint *dentro* de un job de `plan` (por prompt individual) — sigue
    siendo atómico por perfil+plataforma.
  - Retries/backoff para Meta/Fanvue/Drive (roadmap ítem 3).
  - Tocar `all.py run_all` — se dejaría intacto como referencia/fallback
    hasta validar el nuevo camino en uso real; se decide luego si se
    reemplaza o conviven ambos.

## Archivos nuevos

- `apps/ai-content-pipeline/ai_content_pipeline/jobs/store.py` —
  `JobStore` sobre `sqlite3` (stdlib): tabla `jobs(id, type, profile,
  platform, status, attempts, error, params_hash)`, más el contador fan-in
  (`fan_in_counters`). Esquema en `jobs/schema.sql`, separado del código.
  Ruta del fichero SQLite configurable (setting), no hardcodeada.
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/queue.py` —
  `Queue` sobre `asyncio.Queue` + loop de workers `asyncio.gather`. La
  concurrencia por tipo de job la fija cada `GenerationBackend`/handler al
  registrarse, no la `Queue`. Un handler puede encolar más jobs mientras
  `run()` está en marcha (fan-out/fan-in); `run()` espera a que se vacíe
  todo, incluido lo encolado dinámicamente.
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/generation_backend.py`
  — interfaz `GenerationBackend.generate(spec, output_path) -> None` +
  `LocalComfyBackend`, que es el mismo `ComfyLocal` de hoy
  (`integrations/comfyui/local.py`, `settings.comfy_host/comfy_port`,
  mismo patrón que `pipeline.py:generate`).
- `apps/ai-content-pipeline/ai_content_pipeline/jobs/tasks.py` — las 3
  funciones de job, reutilizando directamente lo existente:
  - `run_plan`: mismo `PlanningManager(template_profiles=[p], platform_name=...,
    ...).plan()` que ya usa `pipeline.py:plan`; al terminar lee el
    `planning.json` resultante (misma lógica que
    `_load_planning`/`_parse_day` en `generation/publications_generator.py`),
    **llama a `DirectoryManager(...).create_structure(planning)` aquí**
    (misma llamada que ya hace `generate_publications_from_planning` para el
    camino antiguo — no se toca ese archivo, solo se reutiliza `DirectoryManager`
    desde el job nuevo; es idempotente así que no pasa nada si algún día
    ambos caminos coexisten en el mismo run). Solo depende del planning, no
    de ninguna imagen, así que `captions.txt`/`upload_times.txt` quedan
    escritos antes de que exista ningún hijo. Solo entonces encola un
    `generate_image` por cada `ImageSpec`.
  - `run_generate_image`: llama a `GenerationBackend.generate(spec,
    output_path)` (v1: `LocalComfyBackend`) para una sola imagen. Al
    terminar la última imagen pendiente de un perfil+plataforma (contador
    fan-in en `JobStore`), encola el `schedule` correspondiente — esa
    condición ya cubre transitivamente que `run_plan` (y sus artefactos de
    texto) terminó, porque los hijos no existen hasta que `run_plan` los creó.
  - `run_schedule`: mismo `PostingScheduler(template_profiles=[p],
    platform_name=..., publisher=...).upload()` que usa `pipeline.py:schedule`
    hoy (sigue siendo async, se corre dentro del loop de workers).
- `apps/ai-content-pipeline/ai_content_pipeline/cli/commands/jobs.py` —
  nuevo subcomando Typer `jobs run` (equivalente distribuible de
  `all run_all`): misma selección de perfiles vía `resolve_profiles`
  (`cli/commands/utils.py`), misma validación de auth Meta
  (`all.py:_validate_meta_auth_for_profiles`), siembra los `plan` raíz en el
  `JobStore`/`Queue` y arranca el loop de workers hasta vaciar la cola.
  Reentrante: si se relanza tras una caída, siembra solo lo que no esté
  `done`.

## Verificación

1. Tests unitarios para `jobs/store.py` (transición de estados, contador
   fan-in, invalidación por `params_hash`) en
   `apps/ai-content-pipeline/tests/jobs/`, usando SQLite en memoria
   (`sqlite3.connect(":memory:")` — sin dependencia nueva).
2. Test para `jobs/queue.py`: dos jobs del mismo tipo de recurso no corren
   a la vez cuando el semáforo es 1; un `generate_image` fallido no bloquea
   los demás.
3. `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`,
   `uv run pytest -q`.
4. Prueba manual end-to-end con un perfil:
   `uv run python apps/ai-content-pipeline/main.py jobs run -n <profile>`.
   Confirmar que produce el mismo `planning.json`/imágenes/publicación que
   `all run_all` hoy.
5. Prueba de resumabilidad: matar el proceso a mitad de generación de
   imágenes (`Ctrl+C`), volver a lanzar el mismo comando, confirmar que no
   repite imágenes ya generadas ni duplica el job de `schedule`.
6. Prueba de paralelismo: con 2+ perfiles seleccionados, confirmar por logs
   que `plan`/`generate` de distintos perfiles se solapan en el tiempo (a
   diferencia del comportamiento secuencial actual), respetando el semáforo
   de ComfyUI.
7. Prueba específica de la corrección de dependencia: forzar que
   `run_plan` tarde (o inspeccionar manualmente el orden) y confirmar que
   `captions.txt`/`upload_times.txt` existen **antes** de que arranque
   cualquier `generate_image`, y que `schedule` nunca lee un día sin
   `captions.txt` (el `field_validator` de `Publication` en
   `posting_scheduler.py` ya falla fuerte si la caption está vacía —
   suficiente para detectar una regresión de orden).

## Caminos futuros (no en esta v1)

- **Redis + RQ**, si hace falta un pool de workers en varias máquinas para
  el propio orquestador (no solo mover la GPU): implementar
  `RedisJobStore`/`RQQueue` cumpliendo las mismas interfaces de `JobStore`/
  `Queue`, sin tocar `jobs/tasks.py` ni la forma del DAG. Requiere antes
  resolver el riesgo ya documentado de `ModelRouter`/`.cache/model_router`
  si se quiere además paralelismo real entre workers de `plan` (hoy
  limitado a concurrencia 1 también en esta v1 local).
- **`SlurmComfyBackend`** (HPC, p.ej. UPC), si se consigue acceso: implementa
  `GenerationBackend` por SSH + `sbatch`, agrupando varios `generate_image`
  pendientes en un solo envío (evita recargar el checkpoint por imagen) y
  haciendo el rsync/scp de vuelta a `output_path` dentro del propio backend
  — `jobs/tasks.py` y el DAG no cambian. GitHub Actions actuaría solo como
  disparador (`workflow_dispatch`/`schedule`) que hace SSH al login node y
  lanza `jobs run` ahí contra el `JobStore` de esa máquina/almacenamiento
  compartido — no como self-hosted runner (repo público, riesgo de
  seguridad) ni como el que ejecuta ComfyUI. `schedule` (llamadas a
  Meta/Fanvue) puede seguir corriendo en la máquina local/orquestador aunque
  `generate_image` corra en la UPC, ya que el backend de generación es el
  único paso que cambia de sitio.

## Rama y orden de commits

Todo el trabajo va en una rama nueva (`feature/jobs-dag-pipeline`) a partir
de `main`, sin tocar `all.py`/`pipeline.py` en ningún commit de esta lista
(se dejan intactos como fallback, ver "Alcance de esta v1"). Cada commit
deja el árbol en estado compilable/testeable, para poder revisar y parar
entre uno y otro:

1. **`JobStore`** (`jobs/store.py` + `jobs/schema.sql` +
   `tests/jobs/test_store.py`) — estados, `params_hash`, contador fan-in,
   sobre SQLite en memoria. Standalone, sin dependencias del resto de
   `jobs/`. ✅ hecho (`f99f2a1`).
2. **`Queue`** (`jobs/queue.py` + `tests/jobs/test_queue.py`) — loop de
   workers sobre `asyncio.Queue`, concurrencia y `batch_size` inyectados por
   quien registra cada tipo de job. Tests con handlers de mentira (no
   dependen de `GenerationBackend` ni de `PlanningManager`). ✅ hecho
   (`6d43227`).
3. **`GenerationBackend`** (`jobs/generation_backend.py` +
   `tests/jobs/test_generation_backend.py`) — interfaz +
   `LocalComfyBackend` envolviendo el `ComfyLocal` existente. Verificable
   con un `ComfyLocal` mockeado, igual que ya se mockea en los tests
   actuales del paquete `integrations/comfyui`. ⬜ pendiente.
4. **`jobs/tasks.py`** — `run_plan`/`run_generate_image`/`run_schedule`,
   conectando `JobStore`+`Queue`+`GenerationBackend` con `PlanningManager`,
   `DirectoryManager`, `ImageGeneratorService`/`_parse_day` y
   `PostingScheduler` reales. Tests mockeando esas 4 dependencias externas
   (mismo patrón de mocking que ya usa el repo para límites externos). ⬜
   pendiente.
5. **`cli/commands/jobs.py`** — subcomando Typer `jobs run`, registro en el
   CLI principal, reentrancia (siembra solo lo pendiente). Aquí es donde se
   hace la prueba manual end-to-end (verificación 4-7 del apartado
   anterior) antes de dar el commit por bueno. ⬜ pendiente.
6. **Documentación** — actualizar `AGENTS.md` (raíz y/o
   `apps/ai-content-pipeline/AGENTS.md`) con el nuevo comando `jobs run`,
   las 3 interfaces y la decisión de mantener `all run_all` como fallback,
   según la política de mantenimiento de agent instructions del propio
   `AGENTS.md`. ⬜ pendiente.

Commits 1-3 no tienen entre sí dependencia de orden estricta (podrían
intercambiarse), pero se listan en ese orden porque `Queue` y
`GenerationBackend` son más fáciles de revisar ya sabiendo la forma de
`JobStore`. 4 depende de 1-3. 5 depende de 4. 6 se hace al final con todo
ya validado manualmente.
