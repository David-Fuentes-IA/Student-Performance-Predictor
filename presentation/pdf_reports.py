"""PDF presentation: no temporary files or new model training per download."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.config import DEFAULT_PASSING_GRADE, DEFAULT_RISK_THRESHOLD
from presentation.report_data import (
    ALERT_REASON_LABELS,
    STATUS_LABELS,
    describe_levels,
    recommendations,
    summarize,
)

INK = colors.HexColor('#202b46')
PURPLE = colors.HexColor('#6454cc')
TIERS = {'high': '#c43c50', 'medium': '#ac7014', 'low': '#147b65'}
FONT_DIR = Path(reportlab.__file__).parent / 'fonts'
pdfmetrics.registerFont(TTFont('Vera', str(FONT_DIR / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('VeraBold', str(FONT_DIR / 'VeraBd.ttf')))
pdfmetrics.registerFontFamily('Vera', normal='Vera', bold='VeraBold', italic='Vera', boldItalic='VeraBold')
STYLES = getSampleStyleSheet()
for style in STYLES.byName.values():
    style.fontName = 'Vera'
STYLES['Heading2'].fontName = 'VeraBold'
STYLES['Heading2'].keepWithNext = True
STYLES.add(ParagraphStyle(name='ReportTitle', fontName='VeraBold', fontSize=21,
                          leading=27, textColor=INK, spaceAfter=12))
STYLES.add(ParagraphStyle(name='ReportBody', fontName='Vera', fontSize=10, leading=15, textColor=INK, spaceAfter=8))
STYLES.add(ParagraphStyle(name='SmallNote', fontName='Vera', fontSize=8, leading=12, textColor=colors.HexColor('#626b80'), spaceAfter=10))
STYLES.add(ParagraphStyle(name='TableText', fontName='Vera', fontSize=8, leading=11, textColor=INK))


def para(text, style='ReportBody'):
    return Paragraph(escape(str(text)), STYLES[style])


def table(rows, widths):
    cells = [[para(v, 'TableText') for v in row] for row in rows]
    result = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
    result.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ebe9fa')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f7fb')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('LINEBELOW', (0, 0), (-1, 0), .6, PURPLE),
    ]))
    return result


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#dce0eb'))
    canvas.line(1.8*cm, 1.5*cm, 19.2*cm, 1.5*cm)
    canvas.setFont('Vera', 8)
    canvas.setFillColor(INK)
    canvas.drawString(1.8*cm, 1*cm, 'Student Performance Predictor | Demostración académica')
    canvas.drawRightString(19.2*cm, 1*cm, f'Página {doc.page}')
    canvas.restoreState()


def document(title, group_id, content):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(21*cm, 29.7*cm), rightMargin=1.8*cm,
                            leftMargin=1.8*cm, topMargin=1.6*cm, bottomMargin=2*cm,
                            title=title, author='Student Performance Predictor')
    heading = [para('SEGUIMIENTO ACADÉMICO', 'SmallNote'), para(title, 'ReportTitle'),
               para(f'Grupo {group_id} | Emitido: {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC', 'SmallNote'),
               para('Modelo de demostración entrenado con datos sintéticos. '
                    'El riesgo es una estimación del modelo, no una calificación ni un diagnóstico.', 'SmallNote')]
    doc.build(heading + content, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def build_student_report(group_id, student, summary, threshold=DEFAULT_RISK_THRESHOLD,
                         passing_grade=DEFAULT_PASSING_GRADE):
    s = student
    body = [para(s['name'], 'Heading2'), para(f"Matrícula: {s['student_id']}"),
            para(f"Riesgo estimado: {s['risk_score']:.1f}/100 | {STATUS_LABELS[s['risk_label']]}"),
            *([para("Motivo de la alerta: " + ", ".join(ALERT_REASON_LABELS[r] for r in s["alert_reasons"]))]
              if s.get("alert_reasons") else []),
            table([['Indicador', 'Alumno', 'Promedio del grupo'],
                   ['Calificación promedio (0-100)', f"{s['average_grade']:.2f}", f"{summary['average_grade']:.2f}"],
                   ['Asistencia', f"{s['attendance_pct']:.1f}%", f"{summary['attendance_pct']:.1f}%"],
                   ['Participación (0-100)', f"{s['participation_score']:.1f}", f"{summary['participation_score']:.1f}"]], [8*cm, 4.7*cm, 4.7*cm]),
            Spacer(1, 14), para('Calificaciones registradas', 'Heading2'),
            table([['Registro', 'Calificación (0-100)']] + [[f'Registro {i+1}', f'{g:.1f}'] for i, g in enumerate(s['grades'])], [8*cm, 9.4*cm]),
            Spacer(1, 12), para(f"Cambio entre primer y último registro: {s['grade_trend']:+.2f} puntos."),
            para('Sugerencias de seguimiento', 'Heading2')]
    body += [para(f'{i+1}. {action}') for i, action in enumerate(recommendations(s))]
    body += [para('Estas sugerencias se basan en los indicadores observados; no explican causalmente la predicción. '
                  f'Niveles: {describe_levels(threshold, passing_grade)}. '
                  'La interpretación final corresponde al docente.', 'SmallNote')]
    return document('Reporte individual', group_id, body)


def build_group_report(group_id, students, threshold=DEFAULT_RISK_THRESHOLD, passing_grade=DEFAULT_PASSING_GRADE):
    summary = summarize(students)
    n = summary['total']
    body = [para('Resumen de todo el grupo', 'Heading2'),
            para(f'{n} alumnos incluidos. Los filtros de la interfaz no modifican este reporte.'),
            table([['Indicador', 'Resultado'],
                   ['Calificación promedio (0-100)', f"{summary['average_grade']:.2f}"],
                   ['Asistencia promedio', f"{summary['attendance_pct']:.1f}%"],
                   ['Participación promedio (0-100)', f"{summary['participation_score']:.1f}"],
                   ['Riesgo promedio del modelo (0-100)', f"{summary['average_risk']:.1f}"]], [11*cm, 6.4*cm]),
            Spacer(1, 14), para('Distribución de riesgo', 'Heading2'),
            table([['Nivel', 'Alumnos', 'Porcentaje']] + [[label, summary['counts'][tier],
                   f"{100*summary['counts'][tier]/n if n else 0:.1f}%"] for tier, label in STATUS_LABELS.items()], [9*cm, 4.2*cm, 4.2*cm]),
            Spacer(1, 14), para('Promedios por registro de calificación', 'Heading2'),
            table([['Registro', 'Promedio (0-100)']] + [[f'Registro {i+1}', f'{g:.2f}'] for i, g in enumerate(summary['period_averages'])], [9*cm, 8.4*cm]),
            Spacer(1, 14), para('Detalle de alumnos', 'Heading2'),
            table([['Alumno / Matrícula', 'Prom.', 'Asist. %', 'Partic.', 'Riesgo /100', 'Nivel']] + [
                [f"{s['name']} / {s['student_id']}", f"{s['average_grade']:.1f}", f"{s['attendance_pct']:.1f}",
                 f"{s['participation_score']:.1f}", f"{s['risk_score']:.1f}", STATUS_LABELS[s['risk_label']]]
                for s in students], [5.4*cm, 2*cm, 2*cm, 2*cm, 2.4*cm, 3.6*cm]),
            Spacer(1, 14), para('Seguimiento sugerido', 'Heading2'),
            para(f"Priorizar la revisión individual de {summary['counts']['high']} alumnos con riesgo alto y "
                 f"dar seguimiento a {summary['counts']['medium']} en observación. "
                 'Contrastar los indicadores con el contexto de cada alumno antes de decidir acciones.'),
            para('Los promedios son medias aritméticas por alumno; cada registro usa los alumnos que lo tienen disponible. Niveles de riesgo: '
                 f'{describe_levels(threshold, passing_grade)}. El puntaje de riesgo no mide directamente el rendimiento.', 'SmallNote')]
    return document('Reporte de rendimiento grupal', group_id, body)
