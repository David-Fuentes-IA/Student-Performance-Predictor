# Estructura del código: guía para quien llega nuevo

Esta guía es para cualquier persona que nunca haya visto el proyecto: un compañero nuevo, un revisor o un profesor. Explica
**para qué sirve cada carpeta y cada archivo**, **cómo viaja una petición por el código** y **a dónde ir para cambiar algo**.
No supone ningún conocimiento previo del proyecto. Todo lo que dice coincide con el repositorio en la rama `milestone-3`.

*(Traducción de `docs/CODE_STRUCTURE.md`. Los nombres de archivos, funciones y variables se dejan tal como están en el código.)*

## 1. El proyecto en un minuto

Un profesor abre una página web, elige un grupo de alumnos y la aplicación le muestra quiénes necesitan atención. Para cada
alumno calcula un **puntaje de riesgo de 0 a 100** (una estimación de terminar el periodo con bajo rendimiento) a partir de
cuatro números: el promedio, cómo cambiaron las calificaciones, la asistencia y la participación. Un alumno se marca como
**alto riesgo** cuando su promedio es menor a 6.0 (60/100) **o** su puntaje de riesgo es 75 o más. La aplicación también crea
reportes en PDF y tiene una página de administración para crear grupos e importar calificaciones desde Excel. **Solo
recomienda: quien decide es el profesor.** Todos los datos son sintéticos (simulados).

El código es Python (Flask para la web, scikit-learn para la predicción, MongoDB para guardar los datos).

## 2. La idea detrás de la estructura: capas

El código está organizado en **capas**. Cada capa solo habla con la que tiene debajo, así que un cambio en un lugar no rompe
el resto. Un restaurante sirve de imagen (es solo una analogía):

| Capa | Restaurante | En el código | Qué hace |
|---|---|---|---|
| Presentación | el mesero y el menú | `webapp/`, `templates/`, `static/`, `presentation/` | muestra páginas, responde peticiones web, dibuja los PDF |
| Lógica de negocio | el gerente | `main_api.py` | coordina, en orden, los pasos de un reporte |
| IA / predicción | la cocina | `data_pipeline/`, `feature_store/`, `inference_engine/`, `learning_module/` | valida los datos, los convierte en números, predice el riesgo, entrena el modelo |
| Acceso a datos | la despensa | `data_access/` | lee y escribe alumnos y predicciones (MongoDB o memoria) |
| Herramientas compartidas | las reglas de la casa | `core/` | configuración, registro de eventos (logs), errores, alertas, niveles de riesgo: lo usan todos |

```
Presentación      webapp/ · templates/ · static/ · presentation/
      │ llama a
Lógica de negocio main_api.py
      │ llama a
IA / predicción   data_pipeline/ · feature_store/ · inference_engine/ · learning_module/
      │ llama a
Acceso a datos    data_access/            (MongoDB o memoria)

core/  lo usan todas las capas anteriores
```

**Una regla que vale la pena recordar:** la capa de predicción nunca ve el **nombre** del alumno, solo un ID y los cuatro
números (requisito DR-1, privacidad). Los nombres se vuelven a agregar solo al dibujar la página o el PDF.

## 3. El recorrido de una petición

Qué pasa cuando un profesor elige el grupo `301-A` en el dashboard:

1. **El navegador** (`static/dashboard.js`) pide `GET /api/groups/301-A`.
2. **`webapp/dashboard.py`** la recibe, revisa que el ID del grupo sea válido y llama a `main_api`.
3. **`main_api.py`** (`_run_risk_workflow`) ejecuta los pasos en orden:
   1. *Validar la solicitud* (que el ID del grupo no esté vacío).
   2. *Leer el grupo una sola vez* desde el repositorio (`data_access/`).
   3. *Revisar el registro de cada alumno* (`data_pipeline/fail_fast_validator.py`): un registro con una calificación de 150 o
      con texto donde va un número se **omite**, y el resto del grupo continúa.
   4. *Convertir cada registro en cuatro números* (`feature_store/feature_manager.py`): promedio, tendencia de las
      calificaciones (última menos primera), asistencia y participación. El resultado no lleva nombre.
   5. *Predecir todo el grupo en una sola llamada* (`inference_engine/`). Un caché recuerda los resultados recientes y se
      escribe en el log una línea de auditoría por alumno.
   6. *Avisar cada resultado* a los observadores (`core/audit_observer.py`): el observador de alertas escribe en el log una
      línea `RISK ALERT` con el motivo cuando un alumno es de alto riesgo.
   7. *Guardar las predicciones* en un solo lote (`data_access/`). Si esto falla, el reporte se genera de todos modos.
4. **`webapp/dashboard.py`** agrega nombres, niveles y un resumen (`presentation/report_data.py`) y devuelve JSON.
5. **El navegador** dibuja las tarjetas, la gráfica y la tabla de alumnos. **↓ PDF** le pide un archivo a
   `presentation/pdf_reports.py`.

Si algún paso falla de una forma que el usuario deba conocer, la respuesta es un mensaje corto y seguro (nunca el detalle
técnico del error). Los mensajes salen de las clases de error de `core/exception_handler.py`.

## 4. Carpeta por carpeta

### Raíz del proyecto

| Archivo / carpeta | Qué es |
|---|---|
| `main_api.py` | **El coordinador.** Construye todo una sola vez al arrancar (`_bootstrap`: carga el modelo, crea el repositorio, conecta el caché, la auditoría y los observadores) y expone `get_group_dashboard_data` y `generate_group_risk_report`. Si se ejecuta directamente, corre una demostración en texto |
| `web_app.py`, `admin_app.py` | Dos lanzadores pequeños. Ambos arrancan la **misma** aplicación (puertos 5000 y 5001); existen para que los comandos antiguos sigan funcionando |
| `api/index.py`, `vercel.json` | Punto de entrada para el servicio Vercel (configurado, **no verificado**) |
| `requirements.txt`, `requirements-dev.txt` | Librerías para ejecutar la app / para ejecutar además las pruebas |
| `pytest.ini`, `ruff.toml`, `.coveragerc` | Configuración del ejecutor de pruebas, del revisor de estilo de código y del reporte de cobertura |
| `.env.example` | Plantilla del archivo de configuración. Se copia a `.env`; `.env` nunca se sube a git |
| `Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh`, `.dockerignore` | Empaquetar la app como contenedor y arrancarla con su base de datos |
| `k8s/` | Archivos de Kubernetes (varias copias de la app, recuperación automática) |
| `.github/workflows/ci.yml` | El flujo automático que revisa cada push |
| `README.md` | Punto de partida para instalar y ejecutar |

### `webapp/`: la aplicación web (Presentación)

| Archivo | Función |
|---|---|
| `__init__.py` | `create_app()`: construye la aplicación Flask, registra los dos blueprints, fija el límite de 4 MB para archivos subidos y los manejadores de error seguros |
| `dashboard.py` | El lado del profesor: `/`, `/api/groups`, `/api/groups/<id>`, las rutas de PDF, `/health` y `/ready` |
| `admin.py` | El lado de administración bajo `/admin`: grupos, alumnos, importación de Excel, datos de prueba, explorador de la base de datos. Se protege con `ADMIN_PASSWORD` cuando está definida |

### `templates/` y `static/`: lo que recibe el navegador

| Archivo | Función |
|---|---|
| `templates/index.html` | La página del dashboard (etiquetas en español) |
| `static/dashboard.js`, `static/dashboard.css` | Comportamiento del dashboard (cargar un grupo, filtrar, abrir la ficha del alumno, descargar PDF) y su apariencia |
| `templates/admin.html` | Toda la página de administración, con su propio script y sus estilos dentro del mismo archivo |

### `presentation/`: reportes

| Archivo | Función |
|---|---|
| `report_data.py` | Convierte las predicciones en lo que necesitan las pantallas: el resumen del grupo, la descripción de los niveles, las sugerencias de seguimiento |
| `pdf_reports.py` | Dibuja el PDF del grupo y el PDF individual (reportlab) |
| `teacher_report_ui.py` | El reporte en texto plano (también lo usa la demostración en consola) |

### `core/`: herramientas compartidas que se usan en todas partes

| Archivo | Función |
|---|---|
| `config.py` | Lee la configuración de las variables de entorno (`MONGODB_URI`, `PASSING_GRADE`, `RISK_THRESHOLD`…) y **detiene el arranque con un mensaje claro** si alguna no es válida |
| `risk_levels.py` | **La única definición** de "alto / medio / bajo" y de los motivos de alerta. Si la regla cambia, cambia aquí |
| `audit_observer.py` | El mecanismo *Observer*: después de cada predicción se avisa a varios "oyentes". Uno escribe las alertas y otro guarda un historial. Un oyente que falla nunca detiene el reporte |
| `exception_handler.py` | Los tipos de error del proyecto (`ValidationError`, `DataAccessError`, `NotFoundError`, `ModelLoadError`…), cada uno con un mensaje seguro para el usuario |
| `logger.py` | El registro de eventos en un solo formato; `sanitize()` oculta nombres y correos en las líneas del log |

### `data_access/`: almacenamiento (Acceso a datos)

| Archivo | Función |
|---|---|
| `student_repository.py` | El **contrato** (`IAcademicDataRepository`: obtener un alumno, obtener un grupo, guardar predicciones, listar grupos) y la versión **demo en memoria** con tres grupos fijos |
| `mongo_repository.py` | La implementación real sobre MongoDB, más las operaciones de administración (crear grupo, importar, borrar, historial) |
| `mongo_connection.py` | Abre la conexión con MongoDB; oculta las contraseñas al registrar la dirección |
| `schema.py` | Define las seis colecciones, sus reglas de validación y sus índices únicos |
| `repository_factory.py` | Elige qué repositorio usar: MongoDB si `MONGODB_URI` está definida, memoria si no. Si MongoDB está configurada pero caída, **se detiene** en lugar de mostrar datos falsos |
| `synthetic_students.py` | El simulador que crea alumnos ficticios (se usa para los datos de entrenamiento, los datos demo y el libro de evaluación) |

### `data_pipeline/`: revisar y preparar los datos

| Archivo | Función |
|---|---|
| `fail_fast_validator.py` | Rechaza de inmediato un registro malo, indicando el motivo |
| `etl_processor.py` | El pipeline: valida cada registro y luego extrae los cuatro números de todo el grupo |
| `excel_importer.py` | Lee un `.xlsx`, valida cada fila y construye la plantilla descargable. Reporta las filas rechazadas con su número de fila en Excel |
| `group_import_service.py` | Los casos de uso del administrador: crear un grupo, agregar un alumno, importar un Excel (modo parcial o estricto) |
| `synthetic_seed.py` | Llena la base de datos con grupos de demostración |

### `feature_store/` e `inference_engine/`: de los datos al puntaje de riesgo

| Archivo | Función |
|---|---|
| `feature_store/feature_manager.py` | `FeatureVector` (ID + cuatro números, **sin nombre**) y el código que los calcula |
| `inference_engine/risk_predictor.py` | La *Strategy*: dos motores de predicción intercambiables (Random Forest y Regresión Logística) y la *Factory* `create_risk_engine` que elige uno. Predice un alumno o un grupo completo |
| `inference_engine/cache_manager.py` | Dos *Decorators* que envuelven al motor: una capa de **auditoría** (registra la versión del modelo y el tiempo) y un **caché** (recuerda resultados durante 60 s) |

### `learning_module/`: crear y comprobar el modelo

| Archivo | Función |
|---|---|
| `model_trainer.py` | Construye y ajusta los dos tipos de modelo; genera el conjunto de entrenamiento simulado |
| `training_pipeline.py` | `run_training`: entrena, evalúa, guarda el modelo y su **tarjeta del modelo** (model card) |
| `model_store.py` | Guarda y carga el modelo. Si el archivo falta o está dañado: `ModelLoadError` y la app no arranca |
| `model_evaluator.py` | Exactitud (accuracy), precisión, recall, F1 y una revisión de equidad por subgrupo |
| `model_validation.py` | Validación cruzada, intervalos de confianza, selección del modelo, análisis de umbrales, la puerta de calidad |
| `evaluation_data.py` | Carga `data/grupo_evaluacion.xlsx` (los 240 alumnos con los que se mide el modelo) |

### `models/`, `data/`, `demo/`

| Ruta | Qué es |
|---|---|
| `models/model_card.json` | Registro del modelo entrenado (versión, variables, datos). **Se sube a git** |
| `models/risk_model.joblib` | El modelo entrenado. **No se sube**: lo genera `scripts/train_model.py` (Docker lo hace al construir la imagen) |
| `data/grupo_evaluacion.xlsx`, `data/README.md` | Un grupo fijo de 240 alumnos ficticios con el resultado real, usado para validar el modelo |
| `demo/grupo_con_errores.xlsx` | Un archivo pequeño con errores a propósito para practicar la importación |

### `scripts/`: comandos que se ejecutan a mano

| Script | Qué hace |
|---|---|
| `train_model.py` | Entrena y guarda el modelo |
| `evaluate_models.py` | Valida el modelo y reescribe `docs/evidence/model/` (`--gate` es la puerta de calidad) |
| `seed_demo_data.py` | Crea alumnos de demostración en MongoDB |
| `smoke_test.py` | 15 comprobaciones de punta a punta contra una instancia en ejecución |
| `benchmark.py` | Mide velocidad y recursos |
| `collect_test_evidence.py`, `collect_docker_evidence.py` | Ejecutan todo y reescriben `docs/evidence/testing/` y `docs/evidence/docker/` |
| `build_evaluation_dataset.py`, `memory_profile.py`, `migrate_local_to_atlas.py` | Reconstruyen el libro de evaluación, miden memoria, copian datos demo a Atlas |

### `tests/`: la red de seguridad (288 pruebas)

| Carpeta | Pregunta que responde |
|---|---|
| `tests/unit/` | ¿Funciona cada pieza **por separado**? (validador, variables, importador, motores, caché, niveles de riesgo…) |
| `tests/integration/` | ¿Funcionan las piezas **juntas**, y qué pasa si una falla? (el flujo completo, las rutas web, la API de administración sobre un MongoDB real) |
| `tests/system/` | ¿Cumple el **sistema completo** los requisitos? (flujo del profesor, fallas al arrancar, la puerta de calidad, y comprobaciones de que el Dockerfile, el archivo del CI y los archivos de Kubernetes conserven sus protecciones) |
| `tests/performance/` | ¿Cuánta memoria usan las operaciones pesadas? |
| `tests/helpers.py`, `tests/conftest.py` | Ayudas compartidas; el conftest limpia variables de entorno para que el `.env` de un desarrollador no altere los resultados |

### `docs/`

| Ruta | Qué es |
|---|---|
| `docs/evidence/{testing,model,docker,cicd,performance}/` | Resultados de cada medición, cada una con un README que **interpreta** los números |
| `docs/DATABASE.md` | Configuración de MongoDB y Atlas (en español) |
| `docs/M3_CORRECCION.md`, `docs/MANUAL_*_BRIEF.md`, `docs/CODE_STRUCTURE.md`, `docs/ESTRUCTURA_DEL_CODIGO.md` | Material para los reportes y manuales, y esta guía (en inglés y en español) |

## 5. Patrones de diseño, en palabras simples

| Patrón | El problema que resuelve | Dónde |
|---|---|---|
| **Strategy** | Queremos cambiar el modelo de predicción sin tocar el resto | `inference_engine/risk_predictor.py` |
| **Factory** | "¿Qué motor / qué repositorio construyo?" se decide en un solo lugar, a partir de la configuración | `create_risk_engine`, `repository_factory.py` |
| **Decorator** | Agregar un caché y un registro de auditoría **alrededor** del motor sin modificarlo | `inference_engine/cache_manager.py` |
| **Observer** | Varias partes deben reaccionar a una predicción (alerta, historial) sin que el predictor las conozca | `core/audit_observer.py` |
| **Pipeline (ETL)** | Los datos pasan por pasos fijos: extraer, validar, transformar | `data_pipeline/etl_processor.py` |
| **Inversión de dependencias** | El resto del código depende del *contrato* `IAcademicDataRepository`, no de MongoDB. Por eso cambiar la base de datos de PostgreSQL (el diseño original) a MongoDB significó escribir **una sola clase nueva** | `data_access/` |

## 6. "Quiero cambiar X: ¿a dónde voy?"

| Quiero… | Voy a |
|---|---|
| Cambiar qué cuenta como alto riesgo (el 6.0 o el 75) | los valores son configuración: `PASSING_GRADE`, `RISK_THRESHOLD` en `.env`. La regla en sí: `core/risk_levels.py` |
| Cambiar un texto, botón o color del dashboard | `templates/index.html`, `static/dashboard.js`, `static/dashboard.css` |
| Cambiar la página de administración | `templates/admin.html` (la página, el script y los estilos están en el mismo archivo) |
| Cambiar qué contiene un PDF | `presentation/pdf_reports.py` y `presentation/report_data.py` |
| Agregar una columna a la plantilla de Excel | `data_pipeline/excel_importer.py` y `data_access/schema.py` |
| Cambiar qué filas se rechazan por inválidas | `data_pipeline/fail_fast_validator.py` (registros) y `data_pipeline/excel_importer.py` (filas) |
| Agregar un modelo de predicción nuevo | `inference_engine/risk_predictor.py`, `core/config.py` (`MODEL_TYPES`), `learning_module/model_trainer.py`; después entrenar, validar y agregar pruebas |
| Usar otra base de datos | implementar `IAcademicDataRepository` en `data_access/` y elegirla en `repository_factory.py` |
| Enviar de verdad las alertas a los profesores | agregar un observador en `core/audit_observer.py` y conectarlo en `main_api._bootstrap` (hoy las alertas solo se registran en el log) |
| Agregar una ruta web nueva | `webapp/dashboard.py` (profesor) o `webapp/admin.py` (administración) |
| Cambiar el nombre o el valor por defecto de una configuración | `core/config.py` y `.env.example` (y la tabla del README) |
| Cambiar cómo se empaqueta o se despliega el proyecto | `Dockerfile`, `docker-compose.yml`, `k8s/`, `.github/workflows/ci.yml` |

Después de cualquier cambio: ejecuta `python -m pytest` y `python -m ruff check .`. Si cambias un comportamiento que describe un
documento, actualiza el documento: el proyecto exige que el código y la documentación coincidan.

## 7. Convenciones

- **Idioma:** el código, los comentarios, el cuerpo de los commits, el README y los reportes van en inglés; las pantallas, en español.
- **Nombres:** módulos y funciones en `snake_case`, clases en `MayúsculaCadaPalabra` (`CapitalizedWords`); un guion bajo al inicio
  (`_bootstrap`) significa "interno, no llamar desde fuera".
- **Sin secretos en el repositorio:** la dirección real de la base de datos vive solo en `.env` o en variables de entorno.
- **Sin datos personales en la capa de IA ni en los logs:** el ID sí, el nombre no (los ID de alumno sí aparecen en las líneas de auditoría del log).
- **Los mensajes de error para el usuario son cortos y seguros;** el detalle técnico va solo al log.
- **Los archivos generados no se suben:** `.env`, `models/risk_model.joblib`, `logs/`, `.coverage`.

## 8. Glosario

| Término | Significado |
|---|---|
| **Grupo** | Una clase identificada por un ID como `301-A` |
| **Matrícula / ID del alumno** | El identificador único del alumno |
| **Parcial / registro** | Un examen parcial (el dashboard lo llama "Registro 1, 2…") |
| **Puntaje de riesgo** | La estimación del modelo, de 0 a 100; **no es una calificación** |
| **Alerta** | Un alumno de alto riesgo, mostrado como "⚠ Alerta" con su motivo |
| **Variable (feature)** | Uno de los cuatro números que usa el modelo |
| **Tarjeta del modelo (model card)** | Registro en JSON de cómo se entrenó un modelo |
| **Fail-Fast** | Rechazar de inmediato datos o configuración inválidos, con un mensaje claro, en lugar de continuar |
| **Repositorio** | La clase que lee y escribe datos, ocultando dónde se guardan |
| **Blueprint** | Un grupo de rutas de Flask (aquí: el dashboard y la administración) |
| **CI/CD** | El flujo automático que construye, prueba y empaqueta el proyecto en cada push |
| **Datos sintéticos** | Simulados, no son alumnos reales |
