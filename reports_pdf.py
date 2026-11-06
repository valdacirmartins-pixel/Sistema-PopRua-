"""PDFs privados do Sistema PopRua: fichas, registro e indicadores.

Adicionar ao app.py antes de bootstrap():
    from reports_pdf import register_pdf_routes
    register_pdf_routes(app, db, Person, Attendance, Unit, Organization, User,
                        roles, current_user, org_scope, accessible_units,
                        get_person, decrypt_dict, log_event, FIELDS, ATTENDANCE_FIELDS)
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from html import escape
from zoneinfo import ZoneInfo

from flask import abort, render_template, request, send_file
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, PageBreak, Spacer,
    Table, TableStyle, KeepTogether, LongTable
)
from sqlalchemy import and_, func

BR_TZ = ZoneInfo('America/Sao_Paulo')
ACCENT = colors.HexColor('#154B6E')
INK = colors.HexColor('#183040')
SUBTLE = colors.HexColor('#5C7180')
PALE = colors.HexColor('#EEF4F7')
HAIR = colors.HexColor('#D9E3E9')
MAX_QUANT_RECORDS = 15000
MAX_LIST_RECORDS = 350


def _s(value):
    """Texto para Paragraph; evita injeção de tags e caracteres unsupported em Helvetica.

    A fonte padrão do ReportLab cobre o português em Latin-1; caracteres não Latin-1
    são substituídos, sem descartar registros nem quebrar a geração do PDF.
    """
    if value is None or value == '':
        return 'Não informado'
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    value = str(value).replace('\r\n', '\n').replace('\r', '\n')
    value = (value.replace('–', '-').replace('—', '-').replace('“', '"')
             .replace('”', '"').replace('’', "'").replace('•', '-'))
    value = value.encode('latin-1', errors='replace').decode('latin-1')
    return escape(value, quote=True).replace('\n', '<br/>')


def _fmt_dt(value):
    if not value:
        return 'Não informado'
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M')


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('PopTitle', parent=base['Title'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=ACCENT, spaceAfter=10),
        'h2': ParagraphStyle('PopH2', parent=base['Heading2'], fontName='Helvetica-Bold', fontSize=10, leading=14, textColor=ACCENT, spaceBefore=12, spaceAfter=6),
        'text': ParagraphStyle('PopText', parent=base['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=INK, spaceAfter=5, wordWrap='CJK'),
        'small': ParagraphStyle('PopSmall', parent=base['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=INK, wordWrap='CJK'),
        'tiny': ParagraphStyle('PopTiny', parent=base['Normal'], fontName='Helvetica', fontSize=7, leading=10, textColor=INK, wordWrap='CJK'),
        'label': ParagraphStyle('PopLabel', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=12, textColor=SUBTLE),
        'center': ParagraphStyle('PopCenter', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=12, alignment=TA_CENTER, textColor=ACCENT),
    }


def _p(value, style):
    return Paragraph(_s(value), style)


def _page(canvas, doc, label):
    canvas.saveState()
    width, height = doc.pagesize
    canvas.setFillColor(ACCENT)
    canvas.rect(0, height - 1.2 * cm, width, 1.2 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawString(1.5 * cm, height - 0.8 * cm, 'PopRua  |  Gestão de Atendimentos')
    canvas.setStrokeColor(HAIR)
    canvas.line(1.5 * cm, 1.65 * cm, width - 1.5 * cm, 1.65 * cm)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(SUBTLE)
    canvas.drawString(1.5 * cm, 1.1 * cm, 'USO RESTRITO - documento gerado pelo sistema; não constitui validação externa')
    canvas.drawRightString(width - 1.5 * cm, 1.1 * cm, f'{label}  |  Pág. {doc.page}')
    canvas.restoreState()


def _build_pdf(story, *, label, wide=False):
    out = BytesIO()
    pagesize = landscape(A4) if wide else A4
    doc = BaseDocTemplate(out, pagesize=pagesize, topMargin=2.1 * cm,
                          bottomMargin=2.1 * cm, leftMargin=1.5 * cm,
                          rightMargin=1.5 * cm, title=label,
                          author='Sistema PopRua')
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
                  id='content')
    doc.addPageTemplates([PageTemplate(id='Report', frames=[frame], onPage=lambda c, d: _page(c, d, label))])
    doc.build(story)
    out.seek(0)
    return out


def _download(out, name):
    result = send_file(out, mimetype='application/pdf', as_attachment=True,
                       download_name=name, max_age=0)
    result.headers['Cache-Control'] = 'no-store, private'
    result.headers['X-Content-Type-Options'] = 'nosniff'
    return result


def _meta(story, styles, pairs, wide=False):
    w = (26.7 if wide else 18.0) * cm
    cols = [3.8 * cm, w - 3.8 * cm]
    rows = [[_p(label, styles['label']), _p(value, styles['small'])] for label, value in pairs]
    t = Table(rows, colWidths=cols, hAlign='LEFT', splitByRow=1)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, HAIR),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
        ('RIGHTPADDING', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))


def _field_table(story, styles, fields, data, *, include_unfilled=True):
    width = 18 * cm
    for section, items in fields.items():
        contents = []
        for key, label, _kind in items:
            val = (data or {}).get(key)
            if not include_unfilled and not val:
                continue
            contents.append([_p(label, styles['label']), _p(val, styles['text'])])
        if not contents:
            continue
        story.append(_p(section, styles['h2']))
        t = LongTable(contents, colWidths=[6 * cm, width - 6 * cm], hAlign='LEFT', repeatRows=0, splitInRow=1)
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, -1), 0.45, HAIR),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#FAFCFD')]),
            ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(t)


def _table(story, styles, headers, rows, widths, *, font='small'):
    data = [[_p(x, styles['center']) for x in headers]]
    data += [[_p(x, styles[font]) for x in row] for row in rows]
    if len(data) == 1:
        data.append([_p('Sem registros neste período.', styles[font])] + [''] * (len(headers) - 1))
    t = LongTable(data, colWidths=widths, hAlign='LEFT', repeatRows=1, splitByRow=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PALE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, HAIR),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FCFD')]),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)


def _require_period():
    today = datetime.now(BR_TZ).date()
    raw_start = request.args.get('inicio', today.replace(day=1).isoformat())
    raw_end = request.args.get('fim', today.isoformat())
    try:
        start = date.fromisoformat(raw_start)
        end = date.fromisoformat(raw_end)
    except (ValueError, TypeError):
        abort(400, 'Datas inválidas. Use AAAA-MM-DD.')
    if end < start or (end - start).days > 366:
        abort(400, 'Escolha um período de até 367 dias, com início anterior ao fim.')
    min_utc = datetime.combine(start, time.min, BR_TZ).astimezone(timezone.utc)
    max_utc = datetime.combine(end + timedelta(days=1), time.min, BR_TZ).astimezone(timezone.utc)
    return start, end, min_utc, max_utc


def register_pdf_routes(app, db, Person, Attendance, Unit, Organization, User,
                        roles, current_user, org_scope, accessible_units,
                        get_person, decrypt_dict, log_event, FIELDS, ATTENDANCE_FIELDS):
    """Registra URLs após todos os models/permission helpers e antes do bootstrap()."""

    def _units_context():
        me = current_user()
        org_id = org_scope()
        if me.role == 'gestor':
            units = Unit.query.filter_by(org_id=org_id).order_by(Unit.uf, Unit.city, Unit.name).all()
        else:
            units = accessible_units()
        selected = request.args.get('unidade', '')
        if selected in ('', 'todas') and me.role == 'gestor':
            return units, None
        if selected in ('', 'todas') and me.unit_id:
            selected = str(me.unit_id)
        try:
            ident = int(selected)
        except (ValueError, TypeError):
            abort(400, 'Unidade inválida.')
        unit = next((u for u in units if u.id == ident), None)
        if not unit:
            abort(403)
        return units, unit

    def _attendance_query(min_utc, max_utc, unit):
        q = Attendance.query.filter(Attendance.org_id == org_scope(),
                                    Attendance.created_at >= min_utc,
                                    Attendance.created_at < max_utc)
        if unit:
            q = q.filter(Attendance.unit_id == unit.id)
        else:
            # Somente gestor pode fazer relatório multiunidade.
            if current_user().role != 'gestor':
                abort(403)
        return q

    def _org_and_unit(unit=None):
        org = db.session.get(Organization, org_scope())
        return org.name if org else 'Organização', (f'{unit.name} - {unit.city}/{unit.uf}' if unit else 'Todas as unidades da organização')

    @app.get('/relatorios')
    @roles('gestor', 'atendente', 'leitor')
    def reports_pdf_index():
        units, unit = _units_context()
        today = datetime.now(BR_TZ).date()
        return render_template('relatorios_pdf.html', units=units, selected_unit=unit,
                               inicio=today.replace(day=1).isoformat(), fim=today.isoformat())

    @app.get('/pessoas/<person_id>/ficha.pdf')
    @roles('gestor', 'atendente')
    def report_pdf_person(person_id):
        person = get_person(person_id)
        me = current_user()
        data = decrypt_dict(person.encrypted_data)
        unit = Unit.query.filter_by(id=person.unit_id, org_id=org_scope()).first_or_404()
        org, unit_label = _org_and_unit(unit)
        styles = _styles()
        story = [_p('Ficha cadastral - dados preenchidos', styles['title'])]
        _meta(story, styles, [
            ('Organização', org), ('Unidade', unit_label),
            ('Código do cadastro', person.id),
            ('Data do cadastro', _fmt_dt(person.created_at)),
            ('Data de emissão', _fmt_dt(datetime.now(timezone.utc))),
            ('Emitido por', me.name),
        ])
        story.append(_p('Documento confidencial: contém dados pessoais e eventualmente sensíveis. Compartilhar apenas com pessoas autorizadas.', styles['small']))
        _field_table(story, styles, FIELDS, data, include_unfilled=False)
        out = _build_pdf(story, label='Ficha cadastral')
        log_event('PDF_FICHA_EXPORTADO', person.id)
        db.session.commit()
        return _download(out, f'ficha_cadastral_{person.id[:8]}.pdf')

    @app.get('/pessoas/<person_id>/atendimentos/<attendance_id>/pdf')
    @roles('gestor', 'atendente')
    def report_pdf_attendance(person_id, attendance_id):
        person = get_person(person_id)
        attendance = Attendance.query.filter_by(id=attendance_id, person_id=person.id,
                                                org_id=org_scope()).first_or_404()
        me = current_user()
        if me.role != 'gestor' and attendance.unit_id != me.unit_id:
            abort(403)
        unit = Unit.query.filter_by(id=attendance.unit_id, org_id=org_scope()).first_or_404()
        technician = User.query.filter_by(id=attendance.user_id, org_id=org_scope()).first()
        org, unit_label = _org_and_unit(unit)
        person_data = decrypt_dict(person.encrypted_data)
        data = decrypt_dict(attendance.encrypted_data)
        styles = _styles()
        story = [_p('Relatório individual de atendimento', styles['title'])]
        _meta(story, styles, [
            ('Organização', org), ('Unidade', unit_label),
            ('Data do atendimento', _fmt_dt(attendance.created_at)),
            ('Protocolo interno', attendance.id),
            ('Pessoa atendida', person_data.get('nome_social') or person_data.get('nome_registro') or 'Não informado'),
            ('Código do cadastro', person.id),
            ('Profissional', technician.name if technician else 'Não identificado'),
            ('Data de emissão', _fmt_dt(datetime.now(timezone.utc))),
        ])
        _field_table(story, styles, ATTENDANCE_FIELDS, data, include_unfilled=True)
        story.append(Spacer(1, 14))
        story.append(_p('Este documento reproduz informações registradas no sistema; não substitui validação técnica, assinatura ou protocolo externo.', styles['small']))
        out = _build_pdf(story, label='Registro de atendimento')
        log_event('PDF_ATENDIMENTO_EXPORTADO', attendance.id)
        db.session.commit()
        return _download(out, f'atendimento_{attendance.id[:8]}.pdf')

    @app.get('/relatorios/quantitativo.pdf')
    @roles('gestor', 'atendente', 'leitor')
    def report_pdf_quant():
        start, end, start_utc, end_utc = _require_period()
        units, unit = _units_context()
        q = _attendance_query(start_utc, end_utc, unit)
        total = q.count()
        if total > MAX_QUANT_RECORDS:
            abort(413, 'Muitos registros. Divida o período ou selecione uma unidade.')
        org, unit_label = _org_and_unit(unit)
        unit_ids = [unit.id] if unit else [u.id for u in units]
        people_q = Person.query.filter(Person.org_id == org_scope(), Person.unit_id.in_(unit_ids))
        people_total = people_q.filter(Person.archived.is_(False)).count()
        new_people = people_q.filter(Person.created_at >= start_utc, Person.created_at < end_utc).count()
        unique_people = db.session.query(func.count(func.distinct(Attendance.person_id))).filter(
            Attendance.org_id == org_scope(),
            Attendance.created_at >= start_utc, Attendance.created_at < end_utc,
            Attendance.unit_id.in_(unit_ids)).scalar() or 0
        counts_type, counts_result, counts_month = Counter(), Counter(), Counter()
        filled_fields = 0
        max_fields = len([field for g in ATTENDANCE_FIELDS.values() for field in g])
        for a in q.with_entities(Attendance.encrypted_data, Attendance.created_at).yield_per(250):
            data = decrypt_dict(a.encrypted_data)
            counts_type[data.get('tipo') or 'Não informado'] += 1
            counts_result[data.get('resultado') or 'Não informado'] += 1
            dt = a.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            counts_month[dt.astimezone(BR_TZ).strftime('%Y-%m')] += 1
            filled_fields += sum(bool(str(data.get(key) or '').strip()) for group in ATTENDANCE_FIELDS.values() for key, _, _ in group)
        completeness = 100 * filled_fields / (total * max_fields) if total and max_fields else 0
        rows = db.session.query(Unit.uf, Unit.city, Unit.name,
                                func.count(Attendance.id),
                                func.count(func.distinct(Attendance.person_id))).outerjoin(
            Attendance, and_(Attendance.unit_id == Unit.id,
                             Attendance.org_id == org_scope(),
                             Attendance.created_at >= start_utc,
                             Attendance.created_at < end_utc)).filter(
            Unit.org_id == org_scope(), Unit.id.in_(unit_ids)).group_by(
            Unit.id, Unit.uf, Unit.city, Unit.name).order_by(Unit.uf, Unit.city, Unit.name).all()
        styles = _styles()
        story = [_p('Relatório quantitativo de atendimentos', styles['title'])]
        _meta(story, styles, [
            ('Organização', org), ('Abrangência', unit_label),
            ('Período', f'{start:%d/%m/%Y} a {end:%d/%m/%Y}'),
            ('Emissão', _fmt_dt(datetime.now(timezone.utc))),
        ], wide=True)
        story.append(_p('Indicadores do período', styles['h2']))
        _table(story, styles, ['Indicador', 'Quantidade'], [
            ('Atendimentos realizados (registros)', str(total)),
            ('Pessoas distintas atendidas', str(unique_people)),
            ('Novos cadastros no período', str(new_people)),
            ('Cadastros ativos da abrangência (acumulado)', str(people_total)),
            ('Preenchimento dos campos do atendimento (%)', f'{completeness:.1f}%'),
        ], [20*cm, 6.7*cm])
        story.append(_p('Atendimentos por unidade', styles['h2']))
        _table(story, styles, ['UF', 'Município', 'Unidade', 'Atendimentos', 'Pessoas distintas'],
               [(r[0], r[1], r[2], str(r[3]), str(r[4])) for r in rows],
               [1.5*cm, 5.3*cm, 12.2*cm, 3.8*cm, 3.9*cm], font='tiny')
        story.append(_p('Atendimentos por tipo', styles['h2']))
        _table(story, styles, ['Tipo', 'Atendimentos'], sorted(counts_type.items(), key=lambda x: (-x[1], x[0])), [20*cm, 6.7*cm])
        story.append(_p('Atendimentos por resultado', styles['h2']))
        _table(story, styles, ['Resultado', 'Atendimentos'], sorted(counts_result.items(), key=lambda x: (-x[1], x[0])), [20*cm, 6.7*cm])
        story.append(_p('Distribuição mensal', styles['h2']))
        _table(story, styles, ['Mês', 'Atendimentos'], sorted(counts_month.items()), [20*cm, 6.7*cm])
        story.append(Spacer(1, 10))
        story.append(_p('Critérios: cada atendimento salvo conta uma vez; pessoas distintas são contadas por identificador no período; novos cadastros usam a data de criação; preenchimento considera os campos registrados, inclusive valores "Não informado" quando selecionados. Os registros históricos são preservados, inclusive quando a pessoa foi posteriormente arquivada.', styles['tiny']))
        out = _build_pdf(story, label='Relatório quantitativo', wide=True)
        log_event('PDF_QUANT_EXPORTADO', f'{start.isoformat()}_{end.isoformat()}')
        db.session.commit()
        return _download(out, f'quantitativo_{start.isoformat()}_{end.isoformat()}.pdf')

    @app.get('/relatorios/registros.pdf')
    @roles('gestor', 'atendente')
    def report_pdf_records():
        start, end, start_utc, end_utc = _require_period()
        units, unit = _units_context()
        q = _attendance_query(start_utc, end_utc, unit)
        total = q.count()
        if total > MAX_LIST_RECORDS:
            abort(413, f'O período contém {total} registros; reduza o intervalo ou selecione uma unidade (máximo {MAX_LIST_RECORDS} por PDF).')
        org, unit_label = _org_and_unit(unit)
        unit_map = {u.id: u.name for u in units}
        rows = []
        for a in q.order_by(Attendance.created_at.desc()).all():
            data = decrypt_dict(a.encrypted_data)
            rows.append((
                _fmt_dt(a.created_at), a.person_id[:8],
                unit_map.get(a.unit_id, 'Unidade não identificada'),
                data.get('tipo') or 'Não informado',
                data.get('resultado') or 'Não informado',
                data.get('encaminhado_para') or '-',
            ))
        styles = _styles()
        story = [_p('Relatório operacional - registros preenchidos', styles['title'])]
        _meta(story, styles, [
            ('Organização', org), ('Abrangência', unit_label),
            ('Período', f'{start:%d/%m/%Y} a {end:%d/%m/%Y}'),
            ('Atendimentos', str(total)),
            ('Emissão', _fmt_dt(datetime.now(timezone.utc))),
        ], wide=True)
        story.append(_p('Listagem de atendimentos registrados', styles['h2']))
        _table(story, styles,
               ['Data/hora', 'Código pessoa', 'Unidade', 'Tipo', 'Resultado', 'Encaminhado para'],
               rows,
               [3.3*cm, 2.5*cm, 5.4*cm, 6.0*cm, 3.6*cm, 5.9*cm], font='tiny')
        story.append(Spacer(1, 8))
        story.append(_p('Para a ficha integral preenchida de cada atendimento, utilize o PDF individual no histórico da pessoa. Esta listagem não contém CPF nem observações livres.', styles['tiny']))
        out = _build_pdf(story, label='Relatório de registros', wide=True)
        log_event('PDF_REGISTROS_EXPORTADO', f'{start.isoformat()}_{end.isoformat()}')
        db.session.commit()
        return _download(out, f'registros_{start.isoformat()}_{end.isoformat()}.pdf')
