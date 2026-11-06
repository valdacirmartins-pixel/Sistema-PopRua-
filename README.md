# PopRua — sistema inicial de cadastro e atendimento

Sistema web Flask com PostgreSQL, isolamento por organização e unidade, dados pessoais criptografados no banco, histórico de atendimentos, painel de indicadores e gestão de acessos.

**STATUS: versão inicial de demonstração / piloto com dados fictícios. Não utilizar com dados reais sensíveis até passar por homologação de segurança, privacidade, governança e testes.** Não é sistema oficial do Ministério da Justiça ou de qualquer outro órgão.

## Arquivos
- `app.py`: modelo de dados, lógica do servidor e rotas
- `templates/`: páginas HTML
- `static/style.css`: interface responsiva
- `requirements.txt`: pacotes Python
- `Procfile`: inicialização no Railway
- `.env.example`: variáveis necessárias (não publique valores reais)

## Instalação no Railway
1. Crie um **repositório privado** no GitHub e envie todo o conteúdo desta pasta para a **raiz** do repositório; NÃO envie o ZIP diretamente para o editor de `app.py`.
2. No Railway, crie um projeto e adicione um serviço **PostgreSQL**.
3. Adicione um serviço Web conectado ao repositório privado.
4. Em **Variables** do serviço Web, defina:
   - `APP_ENV=production`
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (no editor Railway, use a referência de variável do serviço PostgreSQL; o nome pode variar)
   - `SECRET_KEY`: segredo aleatório grande
   - `DATA_ENCRYPTION_KEY`: chave Fernet (não substitua após registros existentes)
   - `BOOTSTRAP_ADMIN_EMAIL`: e-mail do superadministrador
   - `BOOTSTRAP_ADMIN_PASSWORD`: senha inicial exclusiva com 14+ caracteres
   - `BOOTSTRAP_ADMIN_NAME`: nome do superadministrador
5. Em **Settings → Deploy → Start Command**, se necessário, configure `gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 60 app:app`. O `Procfile` já contém esse comando.
6. Faça o deploy, configure o domínio HTTPS público do Railway e entre usando o superadministrador criado no primeiro boot.
7. **Após a criação da conta, remova `BOOTSTRAP_ADMIN_PASSWORD` e `BOOTSTRAP_ADMIN_EMAIL` das variáveis e redeploy** para reduzir a exposição de credenciais.
8. O superadministrador cria as organizações e gestores. O gestor cadastra as unidades e os profissionais. Só então pode cadastrar pessoas e registrar atendimentos.

Comandos para gerar valores no terminal **local** (um comando por variável):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**IMPORTANTE:** A `DATA_ENCRYPTION_KEY` deve ser guardada em cofre seguro e fazer parte dos procedimentos de recuperação. Se perdê-la, os dados criptografados não poderão ser lidos. Nunca imprima senhas ou dados pessoais nos logs. O Railway não é, sozinho, garantia de conformidade LGPD.

## Execução local (somente dados fictícios)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
# configure as variáveis em seu terminal; .env NÃO é carregado automaticamente
set APP_ENV=development
set BOOTSTRAP_ADMIN_EMAIL=admin@exemplo.org
set BOOTSTRAP_ADMIN_PASSWORD=SuaSenhaForteComMaisDe14Caracteres
python app.py
```

Em desenvolvimento, SQLite é usado apenas se `DATABASE_URL` não estiver configurado. A URL local é `http://127.0.0.1:5000`. Para Windows PowerShell, use `$env:VARIAVEL='valor'` no lugar de `set`.

## Perfis e isolamento
- **Superadmin:** cria organizações e gestores, sem visualizar cadastros individuais no painel normal.
- **Gestor:** cadastra unidades/profissionais e gerencia pessoas e atendimentos de todas as unidades de sua organização. Exporta prontuários em JSON e totais por UF em CSV.
- **Atendente:** vê e altera cadastros **da sua unidade**, registra atendimentos e vê indicadores de sua unidade.
- **Leitor:** consulta cadastros e indicadores de sua unidade, sem editar.

Há `audit_log` de login, visualização, alteração, exportação e arquivamento. Dados cadastrais e narrativas dos atendimentos são armazenados com criptografia simétrica Fernet; identificadores técnicos, vínculos de unidade e datas ficam fora do bloco criptografado.

## Limitações e itens obrigatórios antes da operação real
1. **LGPD / controlador:** estabelecer formalmente a finalidade, base legal apropriada (inclusive art. 11 para dados sensíveis), transparência, política de retenção, descarte, compartilhamento, direitos dos titulares e responsável pelos dados. O consentimento não deve ser presumido como base exclusiva para serviços públicos.
2. **Testes de segurança:** revisão externa de autorização, CSRF, sessão, isolamento multi-institucional, injeção, XSS, fluxo de recuperação de senha, vulnerabilidades de dependências e infraestrutura.
3. **Autenticação robusta:** acrescentar MFA/SSO institucional, recuperação segura de senha, controle de tentativas por IP via Redis, gestão de dispositivos/sessões, expiração e revogação de contas. A versão atual só faz bloqueio por conta após falhas.
4. **Proteção de produção:** backups PostgreSQL automatizados e testados; criptografia e backups gerenciados; segregação de ambientes; monitoramento de incidentes; política de chaves, rotação com migração e recuperação.
5. **Desenvolvimento:** migrations Alembic (em vez de `db.create_all`), testes automatizados e pipeline de CI/CD, trilhas de auditoria protegidas contra alteração, exportação com aprovação justificada, gestão de exclusão/retificação e retenção em registros já arquivados.
6. **Operação nacional:** normalização oficial de municípios pelo código IBGE, catálogo institucional de unidades, cadastro deduplicado com critérios éticos, lógica de encaminhamentos, perfis por órgão, acessibilidade verificada, relatórios anonimizados por porte/risco de reidentificação, e capacidade de lidar com milhares de registros.
7. **Proteção de crianças/adolescentes e dados de violência:** avaliação específica e fluxos restritos, com controle de perfis mais fino. Evite registrar detalhes íntimos ou dados de terceiros no campo livre.
8. **Sem uso offline, anexos, integração gov.br, importação legada ou identificação única nacional** nesta versão.

## Uso recomendado
Comece com dados inventados e equipe pequena. Confira se o perfil atendente vê apenas registros da sua unidade; se relatórios estão coerentes; se cada atendimento aparece uma única vez; se você consegue restaurar o banco e ler os dados usando a chave original. Faça avaliação de impacto quando apropriado.
