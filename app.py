"""Sistema de Atendimento PopRua - Flask/PostgreSQL (prototipo de producao controlada)."""
import os
import io
import csv
import json
import uuid
import secrets
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   session, abort, Response, jsonify)
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///development.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
SECRET_KEY = os.environ.get('SECRET_KEY')
DATA_ENCRYPTION_KEY = os.environ.get('DATA_ENCRYPTION_KEY')
IS_PRODUCTION = os.environ.get('APP_ENV', 'production').lower() == 'production'
if IS_PRODUCTION and (not SECRET_KEY or not DATA_ENCRYPTION_KEY or not DATABASE_URL.startswith('postgresql')):
    raise RuntimeError('Configure SECRET_KEY, DATA_ENCRYPTION_KEY e DATABASE_URL PostgreSQL em producao.')
if not SECRET_KEY: SECRET_KEY = secrets.token_urlsafe(48)
if not DATA_ENCRYPTION_KEY: DATA_ENCRYPTION_KEY = Fernet.generate_key().decode()
fernet = Fernet(DATA_ENCRYPTION_KEY.encode())

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=1024 * 1024,
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
csrf = CSRFProtect(app)
db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)

class Organization(db.Model):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    uf = db.Column(db.String(2), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Unit(db.Model):
    __tablename__ = 'units'
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    uf = db.Column(db.String(2), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    __table_args__ = (db.UniqueConstraint('org_id', 'name', 'city', name='uq_unit_org_name_city'),)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=True)
    name = db.Column(db.String(130), nullable=False)
    email = db.Column(db.String(190), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='atendente')
    active = db.Column(db.Boolean, default=True, nullable=False)
    failures = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Person(db.Model):
    __tablename__ = 'persons'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    encrypted_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False)

class Attendance(db.Model):
    __tablename__ = 'attendances'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, index=True)
    person_id = db.Column(db.String(36), db.ForeignKey('persons.id'), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('units.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    encrypted_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

class Audit(db.Model):
    __tablename__ = 'audit_log'
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, index=True, nullable=True)
    user_id = db.Column(db.Integer, nullable=True)
    event = db.Column(db.String(70), nullable=False)
    resource_id = db.Column(db.String(60))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    # Nunca registrar CPF, payload, notas, nomes ou IP no log.

FIELDS = {
    'Identificação e dados pessoais': [
        ('nome_social','Nome social / nome pelo qual deseja ser chamado','text'),
        ('nome_registro','Nome civil (se necessário)','text'),
        ('data_nascimento','Data de nascimento','date'),
        ('idade_aproximada','Idade aproximada (quando não houver documento)','number'),
        ('cpf','CPF (opcional; registrar apenas se necessário)','text'),
        ('nis','NIS (opcional)','text'),
        ('rg','RG / identificação (opcional)','text'),
        ('nome_mae','Nome da mãe (se necessário)','text'),
        ('telefone','Telefone de contato (se houver)','text'),
        ('contato_referencia','Contato de referência autorizado','text'),
        ('nacionalidade','Nacionalidade','text'),
        ('naturalidade','Naturalidade / cidade de origem','text'),
        ('uf_origem','UF de origem','uf'),
        ('idioma','Idioma principal / língua de atendimento','text'),
    ],
    'Identidade, pertencimento e diversidade': [
        ('sexo_registro','Sexo informado no documento','choice:Não informado|Feminino|Masculino|Intersexo|Prefere não responder'),
        ('identidade_genero','Identidade de gênero (autodeclaração)','choice:Mulher cis|Homem cis|Mulher trans|Homem trans|Travesti|Não binárie|Outra|Prefere não responder|Não informado'),
        ('orientacao_sexual','Orientação sexual (opcional, se relevante)','choice:Heterossexual|Homossexual|Bissexual|Pansexual|Assexual|Outra|Prefere não responder|Não informado'),
        ('raca_cor','Raça/cor (autodeclaração IBGE)','choice:Branca|Preta|Parda|Amarela|Indígena|Prefere não responder|Não informado'),
        ('povo_tradicional','Povo/comunidade tradicional','choice:Não se aplica|Indígena|Quilombola|Cigano/Romani|Ribeirinho|Comunidade de terreiro|Outro|Prefere não responder|Não informado'),
        ('povo_indigena','Povo indígena (qual, se autodeclarado)','text'),
        ('etnia','Etnia / comunidade específica (autodeclaração)','text'),
        ('necessidade_interprete','Necessita intérprete / mediação cultural?','choice:Sim|Não|Não informado'),
    ],
    'Trajetória e condições de rua': [
        ('situacao_atual','Situação atual','choice:Rua|Acolhimento institucional|Moradia provisória|Moradia própria/alugada|Outro|Não informado'),
        ('tempo_rua','Tempo acumulado em situação de rua','choice:Menos de 1 mês|1 a 6 meses|7 a 12 meses|1 a 3 anos|Mais de 3 anos|Não informado'),
        ('inicio_rua','Data aproximada de início da situação de rua','date'),
        ('primeira_vez','É a primeira vez em situação de rua?','choice:Sim|Não|Não informado'),
        ('motivo_rua','Principais motivos relatados (texto livre)','textarea'),
        ('local_pernoite','Principal local de pernoite','choice:Calçada/logradouro|Praça/parque|Viaduto/ponte|Terminal/rodoviária|Ocupação|Acolhimento|Outro|Não informado'),
        ('local_referencia','Território / local de referência (evitar endereço exato de pernoite)','text'),
        ('municipio_atual','Município de permanência','text'),
        ('uf_atual','UF de permanência','uf'),
        ('mobilidade','Deslocamento entre municípios/estados','choice:Frequente|Ocasional|Não|Não informado'),
        ('tempo_municipio','Tempo no município atual','text'),
        ('seguranca_rua','Relata exposição a risco / insegurança?','choice:Sim|Não|Prefere não responder|Não informado'),
    ],
    'Moradia, acolhimento e necessidades básicas': [
        ('moradia_anterior','Última condição de moradia','choice:Própria|Alugada|Cedida|Família/amigos|Instituição|Ocupação|Outra|Não informado'),
        ('retorno_moradia','Deseja apoio para acesso à moradia?','choice:Sim|Não|Não informado'),
        ('acesso_alimentacao','Acesso regular à alimentação','choice:Sim|Não|Parcial|Não informado'),
        ('acesso_agua','Acesso à água potável','choice:Sim|Não|Parcial|Não informado'),
        ('acesso_higiene','Acesso a banho/higiene','choice:Sim|Não|Parcial|Não informado'),
        ('guarda_pertences','Acesso a local para guardar pertences','choice:Sim|Não|Não informado'),
        ('acolhimento_interesse','Interesse em acolhimento institucional','choice:Sim|Não|Indeciso|Não informado'),
        ('possui_animais','Possui animal de companhia?','choice:Sim|Não|Não informado'),
        ('acessibilidade','Necessita de recurso de acessibilidade?','choice:Sim|Não|Não informado'),
        ('necessidades_urgentes','Necessidades prioritárias identificadas','textarea'),
    ],
    'Família, vínculos e rede de apoio': [
        ('estado_civil','Estado civil (autodeclaração)','choice:Solteiro(a)|Casado(a)|União estável|Separado(a)/divorciado(a)|Viúvo(a)|Não informado'),
        ('possui_filhos','Possui filhos?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('quantidade_filhos','Quantidade de filhos (se informado)','number'),
        ('familia_contato','Mantém contato com familiares?','choice:Sim|Não|Esporádico|Prefere não responder|Não informado'),
        ('familia_territorio','Familiares no município?','choice:Sim|Não|Não informado'),
        ('rede_apoio','Rede de apoio de confiança','textarea'),
        ('reintegracao_familiar','Deseja apoio para restabelecer vínculos?','choice:Sim|Não|Não informado'),
        ('acompanhado_criancas','Está acompanhado de criança/adolescente?','choice:Sim|Não|Não informado'),
        ('gestante','Gestação informada (opcional)','choice:Sim|Não|Não se aplica|Prefere não responder|Não informado'),
    ],
    'Documentação, cidadania e acesso digital': [
        ('certidao_nascimento','Possui certidão de nascimento','choice:Sim|Não|Não informado'),
        ('cpf_documento','Possui comprovante de CPF','choice:Sim|Não|Não informado'),
        ('rg_documento','Possui documento de identidade','choice:Sim|Não|Não informado'),
        ('titulo_eleitor','Possui título de eleitor','choice:Sim|Não|Não informado'),
        ('ctps','Possui Carteira de Trabalho','choice:Sim|Não|Não informado'),
        ('sus_cartao','Possui Cartão SUS','choice:Sim|Não|Não informado'),
        ('cadunico','Está inscrito no CadÚnico?','choice:Sim|Não|Não sabe|Não informado'),
        ('acesso_internet','Consegue acessar internet/celular?','choice:Sim|Não|Parcial|Não informado'),
        ('pendencia_documental','Demandas de emissão / regularização documental','textarea'),
    ],
    'Renda, trabalho, educação e benefícios': [
        ('escolaridade','Escolaridade','choice:Não alfabetizado|Fundamental incompleto|Fundamental completo|Médio incompleto|Médio completo|Superior incompleto|Superior completo|Não informado'),
        ('ocupacao','Atividade / ocupação principal','text'),
        ('trabalho_atual','Exerce atividade remunerada?','choice:Sim formal|Sim informal|Não|Não informado'),
        ('renda_faixa','Renda mensal aproximada','choice:Sem renda|Até R$ 500|R$ 501 a R$ 1.000|R$ 1.001 a R$ 2.000|Acima de R$ 2.000|Variável|Prefere não responder|Não informado'),
        ('beneficio','Recebe benefício / transferência de renda?','choice:Sim|Não|Não sabe|Prefere não responder|Não informado'),
        ('beneficio_tipo','Qual(is) benefício(s)? Ex.: Bolsa Família, BPC, aposentadoria','textarea'),
        ('beneficio_pendencia','Pendência de cadastro / acesso ao benefício','textarea'),
        ('capacitacao','Interesse em curso/qualificação/trabalho','choice:Sim|Não|Não informado'),
        ('economia_solidaria','Interesse em geração de renda / economia solidária','choice:Sim|Não|Não informado'),
    ],
    'Saúde e proteção (somente quando necessário ao atendimento)': [
        ('necessidade_saude','Relata necessidade de atendimento em saúde?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('ubs_referencia','UBS / serviço de saúde de referência','text'),
        ('saude_mental_apoio','Deseja acolhimento de saúde mental?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('uso_substancias_apoio','Deseja orientação/redução de danos?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('deficiencia','Autodeclara deficiência?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('deficiencia_apoio','Apoios de acessibilidade solicitados (sem diagnóstico)','textarea'),
        ('situacao_violencia','Relata violação de direitos?','choice:Sim|Não|Prefere não responder|Não informado'),
        ('violencia_encaminhamento','Providência/encaminhamento de proteção (evitar descrição íntima)','textarea'),
        ('necessidade_juridica','Solicita orientação jurídica / defesa de direitos?','choice:Sim|Não|Não informado'),
    ],
    'Preferências, escuta e acompanhamento': [
        ('demandas_relatadas','Demandas relatadas pela pessoa','textarea'),
        ('prioridades_pessoa','Prioridades definidas pela pessoa atendida','textarea'),
        ('acompanhamento','Deseja acompanhamento posterior?','choice:Sim|Não|Não informado'),
        ('preferencia_contato','Forma segura de contato autorizada','text'),
        ('observacoes','Observações estritamente necessárias (não incluir dados de terceiros)','textarea'),
    ],
}
ATTENDANCE_FIELDS = {
    'Registro do atendimento': [
        ('tipo','Tipo de atendimento','choice:Acolhimento/escuta|Cadastro/atualização|Documentação|Benefícios/CadÚnico|Saúde|Moradia/acolhimento|Trabalho/renda|Proteção de direitos|Encaminhamento|Retorno|Outro'),
        ('modalidade','Modalidade','choice:Presencial na unidade|Abordagem social|Remoto|Ação itinerante|Outro'),
        ('demanda','Demanda apresentada','textarea'),
        ('providencias','Providências executadas','textarea'),
        ('encaminhado_para','Serviço/órgão encaminhado','text'),
        ('protocolo','Protocolo / referência externa (opcional)','text'),
        ('resultado','Resultado','choice:Concluído|Encaminhado|Em acompanhamento|Não realizado|Recusado'),
        ('retorno','Data de retorno combinada','date'),
        ('observacao','Observações necessárias','textarea'),
    ]
}
UFS = 'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split()

def encrypt_dict(data):
    return fernet.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()

def decrypt_dict(blob):
    try: return json.loads(fernet.decrypt(blob.encode()).decode())
    except (InvalidToken, ValueError):
        logging.exception('Nao foi possivel descriptografar registro')
        abort(500, 'Chave de criptografia incompatível. Contate o administrador.')

def log_event(event, resource_id=None, org_id=None, user_id=None):
    db.session.add(Audit(event=event, resource_id=resource_id,
                         org_id=org_id if org_id is not None else session.get('org_id'),
                         user_id=user_id if user_id is not None else session.get('uid')))



def current_user():
    uid = session.get('uid')

    if not uid:
        return None

    user = db.session.get(User, uid)

    if not user or not user.active:
        session.clear()
        return None

    if user.role != 'superadmin' and user.org_id != session.get('org_id'):
        session.clear()
        return None

    return user



@app.context_processor
def ctx():
    return dict(me=current_user(), ufs=UFS, now=datetime.now(timezone.utc), fields=FIELDS, attendance_fields=ATTENDANCE_FIELDS)

def login_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not current_user(): return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return inner

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        @login_required
        def inner(*args, **kwargs):
            if current_user().role not in allowed: abort(403)
            return fn(*args, **kwargs)
        return inner
    return deco

def org_scope():
    user = current_user()
    if not user.org_id: abort(403)
    return user.org_id

def accessible_units():
    user = current_user()
    q = Unit.query.filter_by(org_id=org_scope(), active=True)
    if user.role in ('atendente', 'leitor'):
        q = q.filter_by(id=user.unit_id)
    return q.order_by(Unit.name).all()

def get_unit(unit_id):
    try: unit_id = int(unit_id)
    except (ValueError, TypeError): abort(400)
    unit = Unit.query.filter_by(id=unit_id, org_id=org_scope(), active=True).first_or_404()
    if current_user().role in ('atendente', 'leitor') and current_user().unit_id != unit.id:
        abort(403)
    return unit

def person_scope():
    q = Person.query.filter_by(org_id=org_scope(), archived=False)
    if current_user().role in ('atendente', 'leitor'):
        q = q.filter_by(unit_id=current_user().unit_id)
    return q

def get_person(person_id): return person_scope().filter_by(id=person_id).first_or_404()

def parse_fields(groups):
    data = {}
    for items in groups.values():
        for key, _, kind in items:
            value = request.form.get(key, '').strip()
            if len(value) > (3500 if kind == 'textarea' else 300):
                abort(400, 'Campo excedeu o tamanho permitido.')
            if kind == 'number' and value:
                try:
                    n = int(value)
                    if n < 0 or n > 130: raise ValueError()
                except ValueError: abort(400, 'Número inválido.')
            if kind.startswith('choice:') and value and value not in kind[7:].split('|'):
                abort(400, 'Opção inválida.')
            if kind == 'uf' and value and value not in UFS: abort(400)
            if kind == 'date' and value:
                try: datetime.strptime(value, '%Y-%m-%d')
                except ValueError: abort(400, 'Data inválida.')
            data[key] = value
    return data

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    if IS_PRODUCTION: resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return resp

@app.route('/health')
def health(): return jsonify(status='ok')

@app.route('/login', methods=['GET', 'POST'])

def login():
    if request.method == 'GET':
        session.permanent = True
        session.setdefault('login_session', secrets.token_urlsafe(16))

    if request.method == 'POST':

        email = request.form.get('email', '').strip().lower()
        pw = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        now = datetime.now(timezone.utc)
        locked = user and user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > now
        valid = user and user.active and not locked and check_password_hash(user.password_hash, pw)
        if not valid:
            if user and not locked:
                user.failures += 1
                if user.failures >= 5:
                    user.locked_until = now + timedelta(minutes=15)
                    user.failures = 0
                db.session.commit()
            flash('Credenciais inválidas ou acesso temporariamente bloqueado.', 'danger')
        else:
            user.failures = 0
            user.locked_until = None
            session.clear()
            session.permanent = True
            session['uid'], session['org_id'] = user.id, user.org_id
            log_event('LOGIN')
            db.session.commit()
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.post('/logout')
@login_required
def logout():
    log_event('LOGOUT')
    db.session.commit()
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    user = current_user()
    if user.role == 'superadmin':
        return render_template('superadmin.html', orgs=Organization.query.order_by(Organization.name).all(),
                               n_orgs=Organization.query.count(), n_units=Unit.query.count())
    ps = person_scope()
    unit_ids = [u.id for u in accessible_units()]
    ascope = Attendance.query.filter_by(org_id=org_scope())
    if user.role in ('atendente', 'leitor'):
        ascope = ascope.filter(Attendance.unit_id.in_(unit_ids))
    counts = db.session.query(Unit.id, Unit.name, Unit.city, Unit.uf, func.count(Person.id)).outerjoin(
        Person, (Person.unit_id == Unit.id) & (Person.archived.is_(False))).filter(
        Unit.org_id == org_scope(), Unit.id.in_(unit_ids)).group_by(Unit.id).order_by(Unit.uf, Unit.city).all()
    return render_template('dashboard.html', people=ps.count(), attendances=ascope.count(),
                           units=len(unit_ids), counts=counts,
                           recent=ps.order_by(Person.updated_at.desc()).limit(8).all(), decrypt=decrypt_dict)

@app.route('/pessoas')
@roles('gestor', 'atendente', 'leitor')
def people():
    page = max(1, request.args.get('page', 1, type=int))
    pagination = person_scope().order_by(Person.updated_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('people.html', pagination=pagination, decrypt=decrypt_dict)

@app.route('/pessoas/nova', methods=['GET', 'POST'])
@roles('gestor', 'atendente')
def new_person():
    units = accessible_units()
    if request.method == 'POST':
        unit = get_unit(request.form.get('unit_id'))
        data = parse_fields(FIELDS)
        if not (data['nome_social'] or data['nome_registro']):
            flash('Informe ao menos um nome ou nome de referência para o cadastro.', 'danger')
        else:
            p = Person(org_id=org_scope(), unit_id=unit.id, created_by=current_user().id,
                       encrypted_data=encrypt_dict(data))
            db.session.add(p)
            db.session.flush()
            log_event('PESSOA_CRIADA', p.id)
            db.session.commit()
            flash('Cadastro salvo com segurança.', 'success')
            return redirect(url_for('person_detail', person_id=p.id))
    return render_template('person_form.html', data={}, units=units, title='Novo cadastro', editing=False)

@app.route('/pessoas/<person_id>')
@roles('gestor', 'atendente', 'leitor')
def person_detail(person_id):
    p = get_person(person_id)
    entries = Attendance.query.filter_by(person_id=p.id, org_id=org_scope()).order_by(Attendance.created_at.desc()).all()
    log_event('PESSOA_VISUALIZADA', p.id)
    db.session.commit()
    return render_template('person_detail.html', p=p, data=decrypt_dict(p.encrypted_data),
                           entries=entries, decrypt=decrypt_dict)

@app.route('/pessoas/<person_id>/editar', methods=['GET', 'POST'])
@roles('gestor', 'atendente')
def edit_person(person_id):
    p = get_person(person_id)
    if request.method == 'POST':
        unit = get_unit(request.form.get('unit_id'))
        data = parse_fields(FIELDS)
        if not (data['nome_social'] or data['nome_registro']):
            flash('Informe ao menos um nome.', 'danger')
        else:
            p.unit_id = unit.id
            p.encrypted_data = encrypt_dict(data)
            p.updated_at = datetime.now(timezone.utc)
            log_event('PESSOA_ATUALIZADA', p.id)
            db.session.commit()
            flash('Cadastro atualizado.', 'success')
            return redirect(url_for('person_detail', person_id=p.id))
    return render_template('person_form.html', data=decrypt_dict(p.encrypted_data),
                           units=accessible_units(), title='Editar cadastro', editing=True, p=p)

@app.route('/pessoas/<person_id>/atendimentos/novo', methods=['GET', 'POST'])
@roles('gestor', 'atendente')
def new_attendance(person_id):
    p = get_person(person_id)
    if request.method == 'POST':
        data = parse_fields(ATTENDANCE_FIELDS)
        if not data.get('tipo'):
            flash('Informe o tipo de atendimento.', 'danger')
        else:
            a = Attendance(org_id=org_scope(), person_id=p.id, unit_id=p.unit_id,
                           user_id=current_user().id, encrypted_data=encrypt_dict(data))
            db.session.add(a)
            db.session.flush()
            log_event('ATENDIMENTO_CRIADO', a.id)
            db.session.commit()
            flash('Atendimento registrado.', 'success')
            return redirect(url_for('person_detail', person_id=p.id))
    return render_template('attendance_form.html', p=p, data=decrypt_dict(p.encrypted_data))

@app.post('/pessoas/<person_id>/arquivar')
@roles('gestor')
def archive_person(person_id):
    p = get_person(person_id)
    p.archived = True
    log_event('PESSOA_ARQUIVADA', p.id)
    db.session.commit()
    flash('Cadastro arquivado (não excluído).', 'success')
    return redirect(url_for('people'))

@app.route('/pessoas/<person_id>/exportar.json')
@roles('gestor')
def export_person(person_id):
    p = get_person(person_id)
    entries = Attendance.query.filter_by(org_id=org_scope(), person_id=p.id).all()
    payload = {'id': p.id, 'cadastro': decrypt_dict(p.encrypted_data),
               'atendimentos': [{'id': a.id, 'data': a.created_at.isoformat(),
                                  'dados': decrypt_dict(a.encrypted_data)} for a in entries]}
    log_event('PESSOA_EXPORTADA', p.id)
    db.session.commit()
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype='application/json',
                    headers={'Content-Disposition': f'attachment; filename="atendimento-{p.id}.json"'})

@app.route('/relatorios/uf.csv')
@roles('gestor')
def report_by_uf():
    # Relatório agregado sem identificação pessoal.
    totals = db.session.query(Unit.uf, func.count(Person.id)).join(
        Person, (Person.unit_id == Unit.id) & (Person.archived.is_(False))).filter(
        Unit.org_id == org_scope()).group_by(Unit.uf).order_by(Unit.uf).all()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['UF', 'Pessoas cadastradas'])
    writer.writerows(totals)
    log_event('RELATORIO_UF_EXPORTADO')
    db.session.commit()
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="relatorio_uf.csv"'})

@app.route('/gestao/usuarios', methods=['GET','POST'])
@roles('gestor')
def users():
    if request.method == 'POST':
        unit = get_unit(request.form.get('unit_id'))
        email = request.form.get('email', '').lower().strip()
        role = request.form.get('role')
        pw = request.form.get('password', '')
        name = request.form.get('name', '').strip()
        if role not in ('atendente','leitor','gestor') or len(pw) < 14 or not name or '@' not in email:
            flash('Revise os campos. A senha deve conter no mínimo 14 caracteres.', 'danger')
        else:
            u = User(org_id=org_scope(), unit_id=unit.id, name=name[:130], email=email[:190],
                     role=role, password_hash=generate_password_hash(pw))
            db.session.add(u)
            try:
                db.session.flush()
                log_event('USUARIO_CRIADO', str(u.id))
                db.session.commit()
                flash('Usuário criado.', 'success')
            except IntegrityError:
                db.session.rollback()
                flash('Este e-mail já está cadastrado.', 'danger')
    return render_template('users.html', users=User.query.filter_by(org_id=org_scope()).order_by(User.name).all(),
                           units=accessible_units())

@app.post('/gestao/usuarios/<int:user_id>/alternar')
@roles('gestor')
def toggle_user(user_id):
    u = User.query.filter_by(org_id=org_scope(), id=user_id).first_or_404()
    if u.id == current_user().id: abort(400, 'Não é permitido desativar a própria conta.')
    u.active = not u.active
    log_event('USUARIO_STATUS_ALTERADO', str(u.id))
    db.session.commit()
    return redirect(url_for('users'))

@app.route('/gestao/unidades', methods=['GET','POST'])
@roles('gestor')
def units():
    if request.method == 'POST':
        name = request.form.get('name','').strip()[:160]
        city = request.form.get('city','').strip()[:120]
        uf = request.form.get('uf', '')
        if not name or not city or uf not in UFS:
            flash('Informe unidade, cidade e UF.', 'danger')
        else:
            db.session.add(Unit(org_id=org_scope(), name=name, city=city, uf=uf))
            try:
                db.session.commit()
                flash('Unidade criada.', 'success')
            except IntegrityError:
                db.session.rollback()
                flash('Unidade já cadastrada para esta cidade.', 'danger')
    return render_template('units.html', units=Unit.query.filter_by(org_id=org_scope()).order_by(Unit.uf,Unit.name).all())

@app.route('/admin/organizacoes', methods=['POST'])
@roles('superadmin')
def create_org():
    name = request.form.get('name','').strip()[:160]
    email = request.form.get('email','').strip().lower()[:190]
    password = request.form.get('password','')
    admin_name = request.form.get('admin_name','').strip()[:130]
    if not name or not admin_name or '@' not in email or len(password)<14:
        flash('Preencha os campos (senha mínima de 14 caracteres).', 'danger')
    else:
        org = Organization(name=name)
        db.session.add(org)
        try:
            db.session.flush()
            u = User(org_id=org.id, name=admin_name, email=email, role='gestor',
                     password_hash=generate_password_hash(password))
            db.session.add(u)
            db.session.flush()
            log_event('ORGANIZACAO_CRIADA', str(org.id), org_id=org.id)
            db.session.commit()
            flash('Organização e gestor criados. O gestor deve cadastrar uma unidade antes de atender.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Organização ou e-mail já existe.', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/perfil/senha', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        u = current_user()
        old, new = request.form.get('old',''), request.form.get('new','')
        if not check_password_hash(u.password_hash, old) or len(new) < 14:
            flash('Senha atual incorreta ou nova senha com menos de 14 caracteres.', 'danger')
        else:
            u.password_hash = generate_password_hash(new)
            log_event('SENHA_ALTERADA')
            db.session.commit()
            session.clear()
            flash('Senha alterada. Entre novamente.', 'success')
            return redirect(url_for('login'))
    return render_template('password.html')

@app.errorhandler(403)
def error403(e): return render_template('error.html', message='Acesso não autorizado.'), 403
@app.errorhandler(404)
def error404(e): return render_template('error.html', message='Registro não encontrado.'), 404
@app.errorhandler(400)
def error400(e): return render_template('error.html', message='Requisição inválida.'), 400


def bootstrap():
    with app.app_context():
        db.create_all()  # Em expansão real, usar Alembic/Flask-Migrate.
        email = os.getenv('BOOTSTRAP_ADMIN_EMAIL', '').strip().lower()
        password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
        name = os.getenv('BOOTSTRAP_ADMIN_NAME', 'Administrador nacional').strip()
        if email and password:
            if len(password) < 14: raise RuntimeError('BOOTSTRAP_ADMIN_PASSWORD precisa de ao menos 14 caracteres.')
            if not User.query.filter_by(email=email).first():
                db.session.add(User(name=name, email=email, role='superadmin',
                                    password_hash=generate_password_hash(password)))
                try:
                    db.session.commit()
                    logging.info('Superadmin inicial criado.')
                except IntegrityError:
                    db.session.rollback()
            # REMOVA a variável BOOTSTRAP_ADMIN_PASSWORD após o provisionamento.

bootstrap()
if __name__ == '__main__':
    app.run(debug=not IS_PRODUCTION, port=int(os.getenv('PORT','5000')), host='0.0.0.0')
