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
Seleccionar un grupo (301-A, 301-B, 301-C) y hacer clic en **Ver reporte** para obtener el análisis de riesgo.

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
