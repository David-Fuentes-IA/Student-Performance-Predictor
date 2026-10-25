# Student Performance Predictor — panel interactivo

## Ejecutar la interfaz

Requiere Python 3.10 o superior (recomendado: 3.11 o 3.12).
Desde la carpeta del proyecto, en Windows:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python web_app.py
```

En Linux/macOS: `python3 -m venv .venv` y `source .venv/bin/activate`,
seguido de los mismos comandos de instalación y ejecución.
Abre http://127.0.0.1:5000 en un navegador moderno. Mantén la terminal abierta.
El panel de administración (grupos, alumnos e importación de Excel) está en la misma aplicación:
http://127.0.0.1:5000/admin. `python admin_app.py` sirve la misma app en el puerto 5001
(http://127.0.0.1:5001/admin).
Para detener el servidor, usa Ctrl+C. El servidor de `main_api.py` no es necesario
para utilizar la interfaz: inicia `web_app.py`.

## Qué puedes hacer

- Buscar alumnos por nombre o matrícula, filtrar por nivel de riesgo y ordenar
  por promedio, riesgo o nombre.
- Pulsar un nivel en el panorama del grupo para activar/desactivar el filtro.
- Abrir **Ver detalle** para consultar calificaciones, asistencia, participación
  y cambio entre el primer y último registro. Escape cierra la ficha.
- Pulsar **PDF** en la fila o **Descargar PDF individual** en la ficha.
  Incluye indicadores, comparación con el grupo y sugerencias de seguimiento.
- Pulsar **Descargar reporte del grupo** para obtener indicadores agregados,
  distribución de riesgo, promedios por registro y detalle de todos los alumnos.
  Este reporte siempre incluye el grupo completo, incluso con filtros activos.
- Cambiar el identificador del grupo y pulsar **Cargar grupo**. **Actualizar**
  vuelve a consultar sus datos; no modifica las calificaciones.

El diseño se adapta a pantallas pequeñas; la tabla permite desplazamiento horizontal.
Las gráficas funcionan sin CDN ni recursos externos.

## Datos e interpretación

El panel usa la selección de repositorio existente: MongoDB cuando está configurado
`MONGODB_URI`, o datos sintéticos en memoria en modo de demostración. Se conservan
el panel de administración, la importación Excel y la configuración de Vercel de
`main`. Consulta [docs/DATABASE.md](docs/DATABASE.md) para configurar MongoDB.
El modelo de riesgo sigue entrenado con datos sintéticos. Calificaciones y
participación: escala 0–100; asistencia: porcentaje. El riesgo no es una calificación.
Umbrales: bajo <40, observación >=40 y <75, alto >=75. Los PDF usan fecha/hora UTC.
Los promedios por registro se calculan con los alumnos que tienen ese registro.

Esta actualización cambia el panel docente ejecutado con `python web_app.py`.
La entrada existente de Vercel sigue sirviendo el panel de administración.

## Verificación

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Se incluyen pruebas del servidor, consistencia de indicadores, PDF individual y
grupal, matrículas con guiones, grupos vacíos, nivel intermedio, nombres largos,
paginación con 100 alumnos y respuestas de error. Los archivos de pruebas no
requieren modificar el modelo ni el repositorio original.

Las interacciones de la interfaz también se comprobaron con un DOM simulado.
No fue posible realizar la revisión visual en un navegador real en este entorno.

## Archivos principales de esta actualización

- `web_app.py`: interfaz y rutas JSON/PDF.
- `templates/index.html`, `static/dashboard.css`, `static/dashboard.js`: panel.
- `presentation/report_data.py`: indicadores agregados y sugerencias.
- `presentation/pdf_reports.py`: generación de PDF con ReportLab.
- `main_api.py`: agrega matrícula e indicadores académicos al resultado del panel.
- `data_access/student_repository.py`: corrige la búsqueda de alumnos en grupos
  cuyo identificador contiene guiones.

El ZIP contiene el código y el modelo original. Crea un entorno virtual nuevo en
tu equipo; un entorno virtual de otra computadora no es portable.


---

## Arquitectura y documentación del proyecto

# Student Performance Predictor

**Equipo 5** — Ingeniería de Software II  
Gabriel de Anda Romero · David Nava Fuentes · Marco Uriel Romero Hurtado · Axel Rubén López Soto

Sistema de predicción de riesgo académico que identifica estudiantes en riesgo de reprobación mediante aprendizaje automático, siguiendo los patrones de diseño y la arquitectura definidos en el Milestone 1.

---

## Inicio rápido

### Requisitos previos
- Python 3.11 o superior
- Git

### 1. Clonar el repositorio
```bash
git clone https://github.com/David-Fuentes-IA/Student-Performance-Predictor.git
cd Student-Performance-Predictor
```

### 2. Crear y activar el entorno virtual

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Ejecutar la aplicación web
```bash
python web_app.py
```
Abrir el navegador en `http://127.0.0.1:5000`.  
Cargar un grupo y consultar los alumnos o descargar los reportes desde el panel.

### 5. Ejecutar el demo de consola (pipeline completo sin servidor)
```bash
python main_api.py
```
Muestra el reporte de riesgo del grupo 301-A, la evaluación del modelo en el conjunto de prueba y el tamaño del registro de predicciones persistidas.

---

## Arquitectura

El sistema sigue una arquitectura de **4 capas** con separación estricta de responsabilidades:

```
Presentation         web_app.py · presentation/teacher_report_ui.py
     │
Business Logic       main_api.py (Orchestrator)
     │
AI / Prediction      inference_engine/ · feature_store/ · learning_module/ · data_pipeline/
     │
Data Access          data_access/student_repository.py
```

### Patrones de diseño implementados

| Patrón | Ubicación | Propósito |
|--------|-----------|-----------|
| **Strategy** | `inference_engine/risk_predictor.py` | `IRiskPredictionEngine` — intercambia RandomForest ↔ LogisticRegression sin tocar el orquestador |
| **Factory** | `inference_engine/risk_predictor.py` | `create_risk_engine("random_forest" \| "logistic_regression")` |
| **Decorator** | `inference_engine/cache_manager.py` | `CachingDecorator` (TTL 60 s) + `AuditDecorator` apilados sobre el motor |
| **Observer** | `core/audit_observer.py` | `RiskEventPublisher` notifica a `RiskAlertObserver` y `ModelMonitoringObserver` |
| **Pipeline / ETL** | `data_pipeline/etl_processor.py` | Extrae → valida → transforma registros académicos en vectores de características |

### Flujo de trabajo IA (9 pasos, §8 del documento de diseño)

1. Validar permisos e input (Fail-Fast a nivel de request)
2. Autorizar solicitud (verificación del docente)
3. Recuperar datos académicos (`IAcademicDataRepository`)
4. Verificar calidad de datos (`FailFastValidator`)
5. Ejecutar pipeline ETL (`ETLProcessor` → `FeatureManager`)
6. Ejecutar motor de predicción (`IRiskPredictionEngine` + Strategy + Decorator)
7. Notificar por umbral (`RiskEventPublisher` → Observers)
8. Persistir resultado (`IAcademicDataRepository.save_prediction`)
9. Generar y mostrar reporte (`TeacherReportUI`)

---

## Estructura del proyecto

```
student_predictor_project/
├── main_api.py                  # Orquestador + Flask API + punto de entrada
├── web_app.py                   # Servidor web Flask con interfaz HTML/CSS
├── requirements.txt
│
├── core/
│   ├── logger.py                # Logger centralizado (consola INFO + archivo DEBUG)
│   ├── exception_handler.py     # Jerarquía de excepciones + decorador @handle_errors
│   └── audit_observer.py        # Observer: RiskEventPublisher, RiskAlertObserver, ModelMonitoringObserver
│
├── data_access/
│   └── student_repository.py    # IAcademicDataRepository + InMemoryAcademicRepository
│
├── data_pipeline/
│   ├── etl_processor.py         # Pipeline ETL (Extracción → Validación → Transformación)
│   └── fail_fast_validator.py   # Validación de calidad por registro
│
├── feature_store/
│   └── feature_manager.py       # FeatureVector (DR-1: sin PII) + extracción vectorizada numpy/pandas
│
├── learning_module/
│   ├── model_trainer.py         # ModelTrainer (RandomForest + LogisticRegression) + split_dataset (80/20)
│   └── model_evaluator.py       # Métricas: accuracy, precision, recall, F1
│
├── inference_engine/
│   ├── risk_predictor.py        # IRiskPredictionEngine, RandomForestRiskEngine, LogisticRegressionRiskEngine, Factory
│   └── cache_manager.py         # CachingDecorator (TTL 60 s) + AuditDecorator
│
├── presentation/
│   └── teacher_report_ui.py     # TeacherReportUI: renderiza texto y HTML
│
├── templates/
│   └── dashboard.html           # Interfaz web (Jinja2)
│
└── logs/                        # Archivos de log generados en tiempo de ejecución (excluidos de git)
```

---

## Dependencias y justificación

| Librería | Versión | Justificación |
|----------|---------|---------------|
| `flask` | ≥ 3.0 | Servidor web liviano; tecnología especificada en el stack del proyecto |
| `scikit-learn` | ≥ 1.4 | `RandomForestClassifier`, `LogisticRegression`, `train_test_split` — pipeline ML central |
| `pandas` | ≥ 2.0 | Extracción vectorizada de características (`FeatureManager.extract_many`) |
| `numpy` | ≥ 1.26 | Operaciones matriciales sobre calificaciones (`grades_matrix.mean(axis=1)`) |

---

## Decisiones de diseño relevantes

- **Sin base de datos real**: `InMemoryAcademicRepository` genera datos sintéticos para que el sistema sea ejecutable sin infraestructura externa. Reemplazarlo por SQLAlchemy+PostgreSQL requiere implementar la misma interfaz `IAcademicDataRepository` y cero cambios en el resto del código (DIP).
- **Separación PII**: `FeatureVector` no tiene campo `name` — la capa de IA nunca ve datos identificables. Los nombres se recuperan en la capa de Presentación desde `name_lookup` (DR-1).
- **Evaluación honesta del modelo**: `split_dataset` hace la división 80/20 estratificada antes de entrenar, por lo que la evaluación en `__main__` corre sobre el conjunto de prueba retenido, no sobre datos de entrenamiento.
- **Logging estructurado**: consola en nivel INFO (limpio para demos), archivo en nivel DEBUG (trazabilidad completa). `sanitize()` redacta campos sensibles antes de escribir al log.
