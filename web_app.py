"""Interactive Flask dashboard and downloadable, in-memory PDF reports."""
from io import BytesIO
import re

from werkzeug.utils import secure_filename
from flask import Flask, jsonify, render_template, request, send_file
from core.exception_handler import AppError
from main_api import get_group_dashboard_data
from presentation.report_data import summarize
from presentation.pdf_reports import build_student_report, build_group_report

app = Flask(__name__)
DEFAULT_GROUP_ID = '301-A'


def valid_group(group_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,39}', group_id):
        return False
    return True


def load_group(group_id):
    if not valid_group(group_id):
        return None
    return get_group_dashboard_data(group_id)


def pdf_response(data, filename):
    response = send_file(BytesIO(data), mimetype='application/pdf', as_attachment=True,
                         download_name=filename, max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def index():
    group_id = request.args.get('group', DEFAULT_GROUP_ID)
    if not valid_group(group_id):
        return render_template('index.html', group_id=DEFAULT_GROUP_ID,
                               initial_error='Identificador de grupo inválido.'), 400
    return render_template('index.html', group_id=group_id, initial_error=None)


@app.get('/api/groups/<group_id>')
def group_data(group_id):
    students = load_group(group_id)
    if students is None:
        return jsonify(error='Identificador de grupo inválido.'), 400
    response = jsonify(group_id=group_id, students=students, summary=summarize(students), model_demo=True)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/reports/groups/<group_id>.pdf')
def group_pdf(group_id):
    students = load_group(group_id)
    if students is None:
        return jsonify(error='Identificador de grupo inválido.'), 400
    return pdf_response(build_group_report(group_id, students), f'reporte_grupo_{group_id}.pdf')


@app.get('/reports/groups/<group_id>/students/<path:student_id>.pdf')
def student_pdf(group_id, student_id):
    if not valid_group(group_id) or not student_id or len(student_id) > 128:
        return jsonify(error='Identificador inválido.'), 400
    students = load_group(group_id)
    student = next((s for s in students if s['student_id'] == student_id), None)
    if student is None:
        return jsonify(error='El alumno no pertenece a este grupo.'), 404
    return pdf_response(build_student_report(group_id, student, summarize(students)),
                        f'reporte_alumno_{secure_filename(student_id)}.pdf')


@app.errorhandler(AppError)
def app_error(exc):
    app.logger.warning('Academic workflow failed: %s', exc)
    return jsonify(error='No se pudo generar la información del grupo. Inténtalo de nuevo.'), 503


@app.errorhandler(500)
def server_error(exc):
    return jsonify(error='No se pudo completar la operación. Inténtalo de nuevo.'), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
