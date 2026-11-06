"""Instalador conservador dos relatórios PDF no repositório PopRua.

Uso: python instalar_relatorios_pdf.py
- NÃO substitui o app.py inteiro.
- NÃO altera banco de dados, chaves ou rotas de login.
- Faz um backup local do app.py para rollback se algo der errado.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app.py'
REQUIREMENTS = ROOT / 'requirements.txt'
BASE = ROOT / 'templates' / 'base.html'
DETAIL = ROOT / 'templates' / 'person_detail.html'
REPORTS_MODULE = ROOT / 'reports_pdf.py'
REPORTS_HTML = ROOT / 'templates' / 'relatorios_pdf.html'

if not all(p.exists() for p in (APP, REQUIREMENTS, BASE, DETAIL, REPORTS_MODULE, REPORTS_HTML)):
    sys.exit('Arquivos não encontrados. Extraia o ZIP na RAIZ do repositório (onde está app.py) e tente novamente.')

content = APP.read_text(encoding='utf-8')
registration = '''\n# Relatórios PDF: módulo independente; mantém intacto o fluxo de login.\nfrom reports_pdf import register_pdf_routes\nregister_pdf_routes(app, db, Person, Attendance, Unit, Organization, User,\n                    roles, current_user, org_scope, accessible_units,\n                    get_person, decrypt_dict, log_event, FIELDS, ATTENDANCE_FIELDS)\n'''
if 'register_pdf_routes(app, db, Person, Attendance' not in content:
    marker = '\nbootstrap()\n'
    if marker not in content:
        sys.exit('Não localizei bootstrap() isolado no final de app.py. Nenhum arquivo foi alterado. Peça integração manual.')
    shutil.copy2(APP, APP.with_suffix('.py.bak'))
    content = content.replace(marker, '\n' + registration + marker, 1)
    APP.write_text(content, encoding='utf-8')
    print('OK: registrei as novas rotas no app.py; fiz backup app.py.bak')
else:
    print('OK: rotas já estavam integradas; não dupliquei.')

requirements = REQUIREMENTS.read_text(encoding='utf-8')
if not any(line.strip().lower().startswith('reportlab') for line in requirements.splitlines()):
    REQUIREMENTS.write_text(requirements.rstrip() + '\nreportlab>=4.2,<5\n', encoding='utf-8')
    print('OK: dependência ReportLab adicionada.')
else:
    print('OK: ReportLab já consta em requirements.txt.')

base = BASE.read_text(encoding='utf-8')
if 'reports_pdf_index' not in base:
    anchor = '<a href="{{ url_for(\'people\') }}">Pessoas</a>'
    if anchor in base:
        base = base.replace(anchor, anchor + '<a href="{{ url_for(\'reports_pdf_index\') }}">Relatórios PDF</a>', 1)
        BASE.write_text(base, encoding='utf-8')
        print('OK: link Relatórios PDF no menu.')
    else:
        print('AVISO: menu alterado; inclua manualmente o link para reports_pdf_index.')
else:
    print('OK: link do menu já existe.')

detail = DETAIL.read_text(encoding='utf-8')
if 'report_pdf_person' not in detail:
    anchor = '<a class="button" href="{{url_for(\'edit_person\',person_id=p.id)}}">Editar cadastro</a>'
    if anchor in detail:
        detail = detail.replace(anchor, anchor + '<a class="button" href="{{url_for(\'report_pdf_person\',person_id=p.id)}}">PDF do cadastro</a>', 1)
        print('OK: botão PDF do cadastro.')
    else:
        print('AVISO: botão PDF do cadastro deve ser inserido manualmente na página de pessoa.')
if 'report_pdf_attendance' not in detail:
    # A versão original mostra cada atendimento dentro do div.history.
    anchor = "{{d.get('retorno') or 'Não informado'}}</p></div>"
    if anchor in detail:
        extra = "{{d.get('retorno') or 'Não informado'}}</p>{% if me.role != 'leitor' %}<a class=\"button\" href=\"{{url_for('report_pdf_attendance',person_id=p.id,attendance_id=a.id)}}\">PDF deste atendimento</a>{% endif %}</div>"
        detail = detail.replace(anchor, extra, 1)
        print('OK: botão PDF do atendimento.')
    else:
        print('AVISO: botão PDF do atendimento deve ser inserido manualmente no histórico.')
DETAIL.write_text(detail, encoding='utf-8')

print('\nInstalação concluída. Confirme com: python -m py_compile app.py reports_pdf.py')
print('Depois: git add app.py reports_pdf.py requirements.txt templates/base.html templates/person_detail.html templates/relatorios_pdf.html')
print('AVISO: app.py.bak é backup local; NÃO envie para o GitHub público.')
