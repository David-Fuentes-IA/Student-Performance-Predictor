# Brief for writing the USER MANUAL: Student Performance Predictor (Team 5)

> **For the assistant who writes the manual.** Write a **user manual for teachers and for the person who administers
> the groups**. Everything below was checked against the real application (labels, buttons, messages and limits are
> copied from the code). Use only this material; do not invent screens, buttons or features.
>
> **Rules**
> 1. Write the manual in **English** (the team's report language), but quote every **on-screen label exactly as it
>    appears, in Spanish**, in bold, for example the button **Cargar grupo**. Add a short English gloss the first time.
> 2. Audience: a teacher with no technical background. Short steps, one action per step, no jargon. The professor
>    criticised the Milestone 2 manual because it described a drop-down and a "View report" button that did not match
>    the interface: **only describe what is in section 3 and 4**.
> 3. Put `[SCREENSHOT: ...]` where an image belongs (suggestions are given in section 9).
> 4. All data are **synthetic**. The model is a **demonstration** model. Never say it works on real students.
> 5. The risk score is **not a grade**. The system **only recommends**; the teacher decides. Say this clearly.
> 6. Do not describe features marked "not available" in section 8.

Repository: <https://github.com/David-Fuentes-IA/Student-Performance-Predictor>, branch `milestone-3`.

---

## 1. What the system is for

A decision-support tool for teachers. From each student's partial-exam grades, attendance and participation, it
estimates a **risk (0–100)** of ending the term with low performance, marks the students who need attention, explains
**why** each alert was raised, and produces PDF reports for the whole group and for each student. It never acts on a
student by itself: every alert is a suggestion for the teacher to review.

Two screens, one application:

| Screen | Address | Who uses it |
|---|---|---|
| **Dashboard** (panel docente) | `/` | teachers: see the group, find students who need attention, download PDFs |
| **Administration** ("Base de datos") | `/admin` | whoever manages groups: create groups, add students, import Excel files |

How to open them: when the system is started with Docker, **http://localhost:8000** (dashboard) and
**http://localhost:8000/admin** (administration). Started with Python: **http://127.0.0.1:5000**. Starting the system
is the technical team's job (see the technical manual); the user manual starts with the browser already open.

## 2. Key ideas the user must understand

**Risk levels.** Every student is in exactly one level:

| Level (as shown) | Meaning | Rule |
|---|---|---|
| **Alto riesgo** (high risk), shown with **⚠ Alerta** | needs review now | average grade **below 6.0** (60 out of 100, a failing average) **or** estimated risk **75 or more** |
| **En observación** (under observation) | keep an eye on this student | estimated risk 40 or more (and not high risk) |
| **Buen camino** (on track) | no signs of concern | everything else |

**Estimated risk (0–100).** The model's estimate that the student ends the term with low performance. It is **not a
grade** and not a certainty. Roughly 1 alert in 4 is a false alarm, and some students who do end up at risk are not
flagged (validation results: precision 0.77, recall 0.73 on synthetic test students). The teacher's judgment always
comes first.

**Reason for the alert.** Each alert says why: **Promedio reprobatorio** (failing average), **Riesgo estimado alto**
(high estimated risk), or both ("Promedio reprobatorio y Riesgo estimado alto").

**Grades are called "registros".** The dashboard calls each partial exam **Registro 1, Registro 2…**; the Excel file and
the administration screen call them **parcial1…parcial4**. They are the same thing.

**Scale.** Everything is 0–100. The "6.0" in the alert rule is the same as 60 out of 100.

## 3. The dashboard (`/`), exactly as it is

### 3.1 Top of the page
- Header: logo **Student Predictor**, **Ingeniería en IA · UAEMéx**, a link **Administrar grupos** (goes to `/admin`) and a
  label **DEMOSTRACIÓN**.
- Title: **Cada alumno cuenta.** and the button **↓ Descargar reporte del grupo** (disabled until a group is loaded).
- Group bar: a selector labelled **Grupo**, the button **Cargar grupo**, a tag showing the alert rule (for example
  **Alerta: promedio < 6 o riesgo ≥ 75**), the note "Modelo de demostración entrenado con datos sintéticos." and the
  button **↻ Actualizar**.
- A yellow banner appears only in **demo mode**: "Modo demo: sin conexión a la base de datos. Los grupos mostrados son de
  ejemplo y no se pueden administrar." (see section 7).
- If there are no groups: "Selecciona o crea un grupo. Aún no hay grupos disponibles." with a link **Ir a administrar grupos**.

### 3.2 Loading a group
1. Open the **Grupo** selector and choose a group. It lists the real groups of the database.
2. Press **Cargar grupo**. A message "Cargando información del grupo…" appears, then "Grupo X actualizado · hora".
3. A group created or changed in the administration screen appears **without restarting anything**: press
   **↻ Actualizar** (or reload the page).

### 3.3 The four cards
**Alumnos del grupo** (number of students) · **Promedio de calificaciones** (group average, scale 0–100) ·
**Asistencia promedio** (average attendance, %) · **Alumnos en alerta** (number of high-risk students, with the rule
written below it).

### 3.4 Panorama del grupo
Three rows, one per level (**Alto riesgo**, **En observación**, **Buen camino**), each with a bar and the count "n /total".
**Clicking a row filters the student table by that level.** Below, the sentence that defines the levels.

### 3.5 Calificaciones por registro
Bars with the group's average for each exam: **Registro 1, Registro 2…**

### 3.6 The student table (**Alumnos**)
- Counter next to the title: for example "12 de 34".
- Filters: **Buscar alumno** (type a name or ID; the field says "Nombre o matrícula…"), **Nivel de riesgo** (Todos los
  niveles / Alto riesgo / En observación / Buen camino), **Ordenar por** (Mayor riesgo / Mayor promedio / Menor promedio /
  Nombre (A–Z)) and the button **Limpiar filtros**.
- Columns: **Alumno** (name, ID, and **⚠ Alerta** for high-risk students; hovering over **⚠ Alerta** shows the reason),
  **Promedio /100**, **Asistencia**, **Riesgo estimado** (the number plus a colour badge with the level) and **Acciones**
  (**Ver detalle** and **↓ PDF**).
- If nothing matches: "No hay alumnos que coincidan con los filtros."
- Note under the table: "El reporte grupal siempre incluye a todo el grupo, aunque haya filtros activos."

### 3.7 The student card (**FICHA DEL ALUMNO**)
Opened with **Ver detalle**. Shows: name and ID; the level badge and "Riesgo estimado: NN.N/100"; for high-risk students
"En alerta: <reason>"; **Promedio /100**, **Asistencia**, **Participación /100**; **Calificaciones registradas**
(Registro 1…n); "Cambio del primer al último registro: ±N puntos"; a note that the risk is an estimate and the final
interpretation belongs to the teacher; the button **↓ Descargar PDF individual**; and **×** (aria-label "Cerrar ficha") to close.

### 3.8 PDF reports
Both are downloaded through the browser ("Preparando PDF…", then "PDF listo. Revisa las descargas de tu navegador.").
- **Group report** (**↓ Descargar reporte del grupo**): header "SEGUIMIENTO ACADÉMICO", group and issue date/time (UTC);
  **Resumen de todo el grupo** ("N alumnos incluidos. Los filtros de la interfaz no modifican este reporte."),
  **Distribución de riesgo**, **Promedios por registro de calificación**, **Detalle de alumnos**, **Seguimiento sugerido**
  (how many students to review first) and the definition of the levels.
- **Individual report** (**↓ PDF** in the table, or **↓ Descargar PDF individual** in the card): name, ID, estimated risk and
  level, **Motivo de la alerta** (when high risk), **Calificaciones registradas**, change between first and last
  registro, a table **Indicador / Alumno / Promedio del grupo** (average grade, attendance, participation) comparing the
  student with the group, and **Sugerencias de seguimiento**.
- The suggestions follow simple rules: average below 60 → review the weakest topics and agree a support session;
  attendance below 80 % → talk about absences and agree an attendance plan; participation below 60 → propose short
  activities to improve participation; grades falling between first and last registro → review the decline; if none
  applies → "Mantener los hábitos de estudio y realizar seguimiento periódico." The report states that suggestions are
  based on the indicators and **do not explain causes**.

### 3.9 Typical use (a good "quick start" section)
1. Open the dashboard and choose your group → **Cargar grupo**.
2. Look at **Alumnos en alerta** and **Panorama del grupo**.
3. Click **Alto riesgo** in the panorama to list only the students in alert.
4. Hover over **⚠ Alerta** (or open **Ver detalle**) to read the reason.
5. Download the individual **↓ PDF** to prepare a conversation with the student.
6. Download **↓ Descargar reporte del grupo** to keep a record.

## 4. The administration screen (`/admin`), exactly as it is

### 4.1 Layout
- Header: link **← Volver al dashboard**, title **Student Performance Predictor · Base de datos**, a badge (green
  **MongoDB conectado: <name>** or red **Sin conexion a la base de datos**) and counters (**Grupos, Alumnos, Registros,
  Historial, Predicciones**).
- Left column: **Grupos** (list; click one to open it), **Nuevo grupo**, **Crear grupo desde Excel**, **Datos de prueba**.
- Right column: the selected group (**Grupo X - N alumnos**), **Explorador de la base de datos** and **Ultimas importaciones**.
- Messages appear as green (ok) or red (error) notices at the bottom for a few seconds.
- If the system has a password (see 4.8), the browser asks "Contrasena de administrador:".

### 4.2 Create a group (**Nuevo grupo**)
Fields: **ID del grupo \*** (required), **Nombre / materia**, **Periodo**, **Profesor**; button **Crear grupo**.
The ID: letters and digits, may contain `.`, `_`, `-`, must start with a letter or digit, **at most 32 characters**
(example `301-A`). Spaces are not allowed. If it already exists: "El grupo 'X' ya existe."

### 4.3 Add or update one student (select the group first)
Form **Agregar alumno**: **Matricula \*** (max 32), **Nombre \*** (max 120), **Parcial 1 \*** (required), **Parcial 2, 3,
4** (optional), **Asistencia % \***, **Participacion \***; button **Guardar alumno**. All values 0–100. Partials cannot
have gaps (do not fill Parcial 3 without Parcial 2). **To edit a student, save again with the same Matricula**: the data
are updated. Each change keeps a snapshot in the history.
**Quitar** (in the table) removes a student from the group. Table columns: **Matricula, Nombre, Parciales, Asist. %,
Partic., Origen, Actualizado**. **Origen** shows where the data came from (for example `excel`, `manual` or `synthetic`).

### 4.4 Import an Excel file
Two ways:
- **Crear grupo desde Excel** (left): type the **ID del grupo**, choose the `.xlsx`, press **Crear e importar**. The group
  is created and filled in one step (partial mode).
- Inside a selected group: **Importar calificaciones desde Excel**: choose the file, choose the **Modo**, press **Importar**.

Modes:
| Mode (as shown) | What happens |
|---|---|
| **Importar filas validas, reportar el resto** (partial) | valid rows are saved; invalid rows are listed and skipped |
| **Estricto: cancelar si hay errores** (strict) | if **any** row is invalid, **nothing** is saved |

Result: a summary "Filas leidas: N · nuevos: N · actualizados: N · sin cambios: N · rechazados: N" and, if there are
rejected rows, a table **Fila / Matricula / Motivo** with the Excel row number and the reason. Importing the same file
twice changes nothing ("sin cambios"). If the group did not exist (when importing inside the group form) the error is
"El grupo 'X' no existe. Crealo primero o activa 'crear grupo'."

**The Excel file.** Press **Descargar plantilla** to get the template (already contains the right headers and two example
rows, which can be deleted). Sheet name `Calificaciones`, **one row per student**:

| matricula | nombre | parcial1 | parcial2 | parcial3 | parcial4 | asistencia_pct | participacion |
|---|---|---|---|---|---|---|---|
| A0001 | Ana Garcia Lopez | 85 | 90 | 78 | 92 | 95 | 88 |
| A0002 | Luis Hernandez Perez | 55 | 48 | 60 | | 70 | 40 |

Rules (from the template's own instructions): do not change the headers; `matricula` is unique (max 32 characters);
grades 0–100; `parcial1` is required, the others may be empty if that exam has not happened yet, **without gaps**;
attendance and participation 0–100; **at most 1,000 students and 4 MB per file**. Accepted formats: `85,5` and `90%`;
headers with or without accents. The file must be a real `.xlsx` (not `.xls`, not a renamed PDF).

**Reasons a row is rejected** (shown in the **Motivo** column; examples of real messages): empty name ("nombre vacio"),
a text where a number is expected ("parcial1: 'abc' no es un numero"), a grade out of range ("invalid grade: 150"),
no grades, a gap between partials, a repeated ID in the file ("matricula 'D0003' repetida en el archivo").
**Reasons the whole file is refused:** empty file ("El archivo esta vacio."), not a valid Excel ("No se pudo leer el
archivo. Sube un Excel valido (.xlsx)."), no file chosen ("Selecciona un archivo Excel (.xlsx)."), wrong extension
("Solo se admiten archivos .xlsx."), missing required columns, no students ("El archivo no contiene alumnos."), more than
1,000 students ("El archivo supera el maximo de 1000 alumnos.").

A ready-made file with errors to practise with is in the repository: `demo/grupo_con_errores.xlsx` (9 rows: 5 valid, 4
rejected). A realistic class of 240 students is `data/grupo_evaluacion.xlsx`.

### 4.5 Delete data
In the selected group: **Vaciar alumnos del grupo** (removes all its students; asks "Vaciar todos los alumnos del grupo X?")
and **Eliminar grupo** (removes the group with all its data; asks "Eliminar el grupo X con todos sus datos?"). Deleting cannot be undone.

### 4.6 Datos de prueba (demo data)
Creates fictitious students marked `synthetic`, in groups 301-A, 301-B and 301-C. **Cantidad de alumnos** (1–500, default
100) and the buttons **Generar** (create, does nothing if they exist), **Regenerar** (replace the synthetic ones) and
**Quitar** (remove only the synthetic ones; real groups are never touched; asks for confirmation).

### 4.7 Explorador de la base de datos and Ultimas importaciones
A read-only viewer: choose a collection (groups, students, academic_records, record_history, predictions, import_logs) and
**Actualizar**. **Ultimas importaciones** lists recent imports with the result "+created / ~updated / rechazadas N".
This part is for the technical team; teachers do not need it.

### 4.8 Password
If the administrator set one, the first time the browser asks **"Contrasena de administrador:"**. Without a password
configured the panel is open to anyone who can reach the address (warn about this).

## 5. Messages the user may see on the dashboard, and what to do

| Message | Meaning | What to do |
|---|---|---|
| "Modo demo: sin conexión a la base de datos…" | no database configured; only 3 example groups of 12 students | tell the technical team; administration is disabled |
| "El grupo 'X' no existe en la base de datos." | the group ID was not found | check the ID or create the group in `/admin` |
| "La base de datos no respondio correctamente. Intenta de nuevo." | the database is not answering | wait a minute and press **↻ Actualizar**; if it persists, tell the technical team |
| "No se pudo generar la información del grupo. Inténtalo de nuevo." | an unexpected problem; the system never shows technical details | try again; report it with the time |
| "No se pudo generar el PDF." / "El servidor no devolvió un PDF válido." | the PDF could not be produced | try again |
| the group list is empty | no groups yet | create one in `/admin` |
| a group has no students | the report is empty (this is valid) | add students or import an Excel |

Records with invalid data (for example a grade over 100) are **skipped** and the rest of the group is still analysed.

## 6. Good practice and limits to put in the manual
- The estimate guides the teacher's attention; **it must not be used as the only reason for any decision about a student**.
- Names and IDs are personal data: do not share the dashboard address or the PDFs with people who should not see them.
  The system has **no login** for the dashboard.
- Re-importing an Excel updates the students with the same ID; the dashboard reflects the new data immediately.
- A student with fewer than 4 partial exams is analysed with the grades available (the model tends to miss such students
  more often: pay attention to them).

## 7. Demo mode (no database)
If the system is started without a database, it shows three example groups (301-A, 301-B, 301-C, 12 students each),
a yellow "Modo demo" banner, and the administration screen only explains that a database is needed. Nothing can be
created. This mode exists for demonstrations without installing a database.

## 8. Not available (do not describe as features)
Teacher login or roles; sending alerts by e-mail/SMS (alerts are only shown on screen and logged); a chart of a student's
history (the changes are stored but no screen shows them); editing a student inside the dashboard (only in `/admin`);
charts over time; any real student data; mobile app. The deployment on Vercel was not verified.

## 9. Suggested screenshots for the manual
1. Dashboard with a group loaded (cards, panorama, table).
2. The **⚠ Alerta** tooltip showing the reason.
3. The student card (**FICHA DEL ALUMNO**).
4. The panorama filtered by **Alto riesgo**.
5. A downloaded group PDF and an individual PDF (first page).
6. Administration: group list and **Nuevo grupo**.
7. **Crear grupo desde Excel** and the import result with rejected rows (use `demo/grupo_con_errores.xlsx`).
8. **Agregar alumno** form.
9. The demo-mode banner.

## 10. Glossary (for the end of the manual)
**Riesgo estimado**: model estimate 0–100, not a grade. **Alerta**: high-risk level, with a stated reason. **Registro /
parcial**: one partial exam. **Promedio**: average of a student's grades. **Asistencia**: attendance %. **Participación**:
participation score 0–100. **Grupo**: a class identified by an ID. **Matrícula**: the student's unique ID. **Modo
parcial / estricto**: how an Excel import treats invalid rows. **Datos sintéticos**: simulated, not real.
