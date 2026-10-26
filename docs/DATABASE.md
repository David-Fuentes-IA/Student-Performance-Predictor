# Base de datos (MongoDB Atlas) e importación de grupos desde Excel

Etapa 2 · bloque 1 — *Base de datos e importación*.

## 1. Qué se construyó

| Pieza | Archivo | Responsabilidad |
|---|---|---|
| Configuración | `core/config.py` | Lee `MONGODB_URI`, `MONGODB_DB`, `ADMIN_PASSWORD` del entorno (`.env` local / variables de Vercel). Nunca hay credenciales en el código. |
| Conexión | `data_access/mongo_connection.py` | Cliente MongoDB cacheado (una conexión por instancia serverless). La URI nunca se escribe en logs. |
| Esquema | `data_access/schema.py` | Colecciones, validadores `$jsonSchema` e índices únicos. Idempotente. |
| Repositorio | `data_access/mongo_repository.py` | Implementa `IAcademicDataRepository` sobre MongoDB (+ operaciones de administración). Solo lee/escribe. |
| Factory | `data_access/repository_factory.py` | Con `MONGODB_URI` → MongoDB; sin ella → repositorio en memoria (modo demo, 3 grupos fijos). Si `MONGODB_URI` está definida pero la BD no responde, la aplicación **no arranca** (salvo `ALLOW_DEMO_FALLBACK=true`, solo para desarrollo). |
| Importador Excel | `data_pipeline/excel_importer.py` | Lee el `.xlsx`, valida con `FailFastValidator`, genera la plantilla descargable. |
| Casos de uso | `data_pipeline/group_import_service.py` | Crear grupo, agregar alumno, importar Excel (modo normal / estricto). |
| Datos de prueba | `data_pipeline/synthetic_seed.py`, `scripts/seed_demo_data.py` | Alumnos ficticios marcados `source="synthetic"`; se pueden quitar sin tocar datos reales. |
| Migración | `scripts/migrate_local_to_atlas.py` | Copia los 100 alumnos sintéticos de Mongo local a Atlas con el esquema nuevo. |
| Panel de administración | `webapp/admin.py` (blueprint en `/admin`) + `templates/admin.html` | Muestra la BD y permite agregar/quitar grupos y alumnos, importar Excel y generar datos de prueba. Es parte de la misma aplicación que el dashboard; `admin_app.py` solo la levanta en el puerto 5001. |
| Vercel | `api/index.py`, `vercel.json`, `.vercelignore` | Despliegue serverless de la app Flask. |

Al conectar MongoDB, el pipeline de riesgo (`main_api.py`) solo cambió **dos líneas**: usa `build_repository()` en lugar de instanciar `InMemoryAcademicRepository()`. Es el ejemplo real del principio DIP del documento: se cambió la fuente de datos sin tocar ETL, modelo, observers ni UI.

## 2. Modelo de datos

```
groups            { group_id (único), name, period, teacher, source, created_at }
students          { student_id (único), name, created_at, updated_at }          ← identidad (PII), separada
academic_records  { group_id, student_id, grades[], attendance_pct,
                    participation_score, source, created_at, updated_at }       ← único (group_id, student_id)
record_history    { group_id, student_id, grades[], attendance_pct,
                    participation_score, source, created_at }                   ← snapshot por cada cambio
predictions       { student_ref, risk_score, risk_label, recorded_at }
import_logs       { group_id, filename, mode, total_rows, created, updated,
                    unchanged, rejected_count, status, created_at }             ← solo metadatos, sin nombres
```

- **DR-1 (privacidad):** el nombre vive solo en `students`. El pipeline de IA recibe `FeatureVector` sin nombre, y `import_logs` no guarda datos personales.
- **Historial:** `record_history` guarda una foto cada vez que cambian las calificaciones de un alumno. Se consulta con `GET /admin/api/groups/<g>/students/<s>/history` y en el explorador de la BD; ninguna pantalla lo muestra todavía como gráfica.
- **Idempotencia:** reimportar el mismo Excel no duplica nada (índice único + upsert; las filas iguales cuentan como "sin cambios").

## 3. Formato del Excel

Hoja `Calificaciones`, una fila por alumno (descarga la plantilla en `/admin/api/template.xlsx` o con el botón de la interfaz):

| matricula | nombre | parcial1 | parcial2 | parcial3 | parcial4 | asistencia_pct | participacion |
|---|---|---|---|---|---|---|---|
| A0001 | Ana Garcia Lopez | 85 | 90 | 78 | 92 | 95 | 88 |

Reglas (Fail-Fast, capa Data Access/ETL de la matriz del §8.0):
- **Rechazo del archivo completo:** no es `.xlsx`, hoja vacía, faltan columnas obligatorias, más de 1000 filas, más de 4 MB.
- **Rechazo de una fila** (se reporta con número de fila y motivo; las demás siguen): matrícula/nombre vacío, valor no numérico, fuera de 0–100, sin calificaciones, huecos entre parciales, matrícula repetida.
- `parcial1` es obligatorio; los siguientes pueden ir vacíos mientras el parcial no se evalúe.
- Acepta `85,5` y `90%`; reconoce encabezados con acentos o variantes (`Matrícula`, `Asistencia`, `Participación`…).
- **Modo normal:** importa las filas válidas y reporta las inválidas. **Modo estricto:** si hay una fila inválida no se guarda nada.
- "Crear grupo desde Excel": si el grupo no existe se crea y se importa en un solo paso.

## 4. Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `MONGODB_URI` | No (vacía = modo demo) | Cadena `mongodb+srv://...` de Atlas, o `mongodb://localhost:27018` para el contenedor local del README. |
| `MONGODB_DB` | No | Nombre de la BD (por defecto `student_predictor`). |
| `ADMIN_PASSWORD` | No | Si se define, la interfaz y la API de administración piden esta contraseña (cabecera `X-Admin-Password`). |
| `ALLOW_DEMO_FALLBACK` | No (`false`) | Solo desarrollo: usar datos demo si la BD configurada no responde al arrancar. |

El resto de variables (`PASSING_GRADE`, `RISK_THRESHOLD`, `RISK_MODEL`, `MODEL_DIR`) están en el README, sección 3.

Local: copia `.env.example` a `.env` y rellénalo (`.env` está en `.gitignore`).

## 5. Ejecutar en local

```powershell
pip install -r requirements.txt
python scripts/train_model.py            # una vez: sin modelo entrenado la app no arranca
python admin_app.py                       # interfaz de la BD  -> http://127.0.0.1:5001/admin
python scripts/seed_demo_data.py          # 100 alumnos de prueba (--count, --reset, --purge)
python scripts/migrate_local_to_atlas.py --dry-run   # luego sin --dry-run
python web_app.py                         # dashboard de riesgo -> http://127.0.0.1:5000 (admin en /admin)
```

## 6. MongoDB Atlas

1. Cluster gratuito (M0) → *Database Access*: usuario y contraseña.
2. *Network Access* → agrega `0.0.0.0/0` (Vercel no tiene IP fija).
3. *Connect → Drivers* → copia la cadena y pégala en `.env` (y en Vercel).
4. Si la contraseña tiene caracteres especiales (`@ : / ?`), hay que codificarlos en la URL (o usar una contraseña solo alfanumérica).

## 7. Despliegue en Vercel

1. Sube el repositorio a GitHub.
2. vercel.com/new → importa el repositorio (Framework Preset: *Other*; Root Directory: raíz del repo).
3. *Settings → Environment Variables*: agrega `MONGODB_URI` (y opcionalmente `MONGODB_DB`, `ADMIN_PASSWORD`) para *Production*, *Preview* y *Development*.
4. Deploy. Abre la URL: `/` es el dashboard, `/admin` la administración y `/health` confirma la conexión (`"database": true`).

Notas:
- `vercel.json` redirige todas las rutas a `api/index.py`; el límite de cuerpo de Vercel (4.5 MB) coincide con el límite de subida del Excel (4 MB).
- El sistema de archivos de Vercel es de solo lectura: el logger escribe a consola en ese entorno.
- `api/index.py` exporta la misma aplicación unificada (dashboard + administración). **El despliegue en Vercel no se verificó en este avance**; el despliegue probado es Docker (`docs/evidence/docker/`). Nota: el modelo entrenado (`models/risk_model.joblib`) no está en git, así que Vercel tendría que generarlo en el build.

## 8. API de administración (prefijo `/admin/api`)

| Método y ruta | Uso |
|---|---|
| `GET /admin/api/health` | Estado de la conexión (público). |
| `GET /admin/api/auth-required` | Indica si se pide contraseña (público). |
| `GET /admin/api/stats` | Conteo por colección. |
| `GET/POST /admin/api/groups` | Listar / crear grupos. |
| `DELETE /admin/api/groups/<g>` | Eliminar grupo y sus datos. |
| `GET/POST/DELETE /admin/api/groups/<g>/students` | Listar / agregar / vaciar alumnos. |
| `DELETE /admin/api/groups/<g>/students/<s>` | Quitar un alumno. |
| `GET /admin/api/groups/<g>/students/<s>/history` | Historial de cambios del alumno. |
| `POST /admin/api/groups/<g>/import` | Importar Excel (`file`, `mode`, `create_group`). |
| `GET /admin/api/imports` | Últimas importaciones. |
| `GET /admin/api/template.xlsx` | Plantilla de Excel (público). |
| `POST/DELETE /admin/api/seed` | Generar / quitar datos de prueba. |
| `GET /admin/api/collections/<nombre>` | Explorador de la BD. |

Las rutas del dashboard (`/api/groups`, reportes PDF, `/health`, `/ready`) están en el README, sección 2.

## 9. ¿Dónde usamos PostgreSQL?

El documento del Milestone 2 propone PostgreSQL + SQLAlchemy (§6.5) y el bloque 1 de la etapa lo planteaba para Docker. **En esta versión la base de datos es MongoDB (Atlas)**, por decisión del equipo; PostgreSQL **no se usa**. Gracias a `IAcademicDataRepository`, migrar a PostgreSQL consistiría en escribir *una* clase nueva (`PostgresAcademicRepository`) y cambiar `repository_factory.py`, sin tocar ETL, modelo, observers ni UI (FR-8 / NFR-3). El documento de diseño debe actualizarse para reflejarlo.
