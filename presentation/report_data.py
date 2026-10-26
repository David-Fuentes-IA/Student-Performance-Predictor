"""Shared definitions used by the dashboard and both PDF reports."""
from core.config import DEFAULT_PASSING_GRADE, DEFAULT_RISK_THRESHOLD
from core.risk_levels import FAILING_AVERAGE, HIGH_PREDICTED_RISK, risk_bands

STATUS_LABELS = {'high': 'Alto riesgo', 'medium': 'En observación', 'low': 'Buen camino'}


ALERT_REASON_LABELS = {FAILING_AVERAGE: 'Promedio reprobatorio', HIGH_PREDICTED_RISK: 'Riesgo estimado alto'}


def describe_levels(threshold=DEFAULT_RISK_THRESHOLD, passing_grade=DEFAULT_PASSING_GRADE):
    """Spanish description of the risk levels, derived from the configured threshold and passing grade."""
    medium_floor, high_floor = risk_bands(threshold)
    high = (f'alto: promedio menor a {passing_grade / 10:.1f} ({passing_grade:g}/100) '
            f'o riesgo estimado desde {high_floor:g}')
    if medium_floor >= high_floor:
        return f'{high}; bajo: el resto'
    return f'{high}; observación: riesgo estimado desde {medium_floor:g}; bajo: el resto'


def summarize(students):
    count = len(students)
    def average(key):
        return round(sum(s[key] for s in students) / count, 2) if count else 0
    return {
        'total': count,
        'counts': {tier: sum(s['risk_label'] == tier for s in students) for tier in STATUS_LABELS},
        'average_grade': average('average_grade'),
        'attendance_pct': average('attendance_pct'),
        'participation_score': average('participation_score'),
        'average_risk': average('risk_score'),
        'period_averages': [round(sum(s['grades'][i] for s in students if len(s['grades']) > i) / sum(len(s['grades']) > i for s in students), 2)
                            for i in range(max(len(s['grades']) for s in students))] if count else [],
    }


def recommendations(student):
    actions = []
    if student['average_grade'] < 60:
        actions.append('Revisar los temas con menor dominio y acordar una sesión de apoyo académico.')
    if student['attendance_pct'] < 80:
        actions.append('Conversar sobre las faltas y acordar un plan de asistencia.')
    if student['participation_score'] < 60:
        actions.append('Proponer actividades breves para fortalecer la participación en clase.')
    if student['grade_trend'] < 0:
        actions.append('Revisar el descenso entre el primer y el último registro de calificaciones.')
    return actions or ['Mantener los hábitos de estudio y realizar seguimiento periódico.']
