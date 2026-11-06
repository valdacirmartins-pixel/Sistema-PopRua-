# PopRua - módulo de relatórios PDF (implantação no Railway)

**Não substitua seu `app.py` atual pelo ZIP antigo.** Este pacote contém somente um complemento compatível com a estrutura entregue anteriormente. Ele não altera o banco, o login nem a política de segurança. Se a sua versão do aplicativo foi significativamente modificada, confira as alterações antes de publicar.

## Relatórios disponíveis

- **Ficha cadastral preenchida**: dados cadastrados de uma pessoa, agrupados pelas seções do formulário. Contém informações sensíveis; download apenas para gestor e atendente autorizados da organização/unidade.
- **PDF do atendimento individual**: protocolo interno, data, unidade, profissional, pessoa, demanda, providências, encaminhamento, resultado e retorno. Uma página/documento por registro (pode ocupar mais de uma página se o texto for longo).
- **Quantitativo por período e unidade**: total de atendimentos, pessoas distintas atendidas, novos cadastros, cadastros ativos, distribuição por unidade/UF, tipos, resultados, meses e completude dos campos.
- **Relatório operacional de registros preenchidos**: lista de atendimentos por período, sem nomes, CPF, anotações livres ou observações íntimas. Até 350 atendimentos por arquivo; para volumes maiores, reduza o período ou selecione uma unidade.

As exportações são geradas sob demanda em memória, com cabeçalho `Cache-Control: no-store` e trilha de auditoria. Não gravam PDFs no disco efêmero do Railway.

## Instalar no seu Codespaces (sem perder as correções do login)

1. Baixe o ZIP `PopRua_Atualizacao_Relatorios_PDF.zip` no ChatGPT.
2. Abra o Codespaces do repositório `Sistema-PopRua-`.
3. Arraste o arquivo ZIP para a lista de arquivos à esquerda (na **raiz** do projeto, ao lado de `app.py`). O VS Code Web pode oferecer Upload, dependendo do navegador. Se não permitir, use o explorador GitHub para adicionar o ZIP, depois volte ao Codespaces.
4. No terminal do Codespaces, execute:

   ```bash
   unzip -o PopRua_Atualizacao_Relatorios_PDF.zip
   python instalar_relatorios_pdf.py
   python -m py_compile app.py reports_pdf.py
   ```

5. Adicione só os arquivos relevantes; não envie chaves, banco, backups ou `.env`:

   ```bash
   git add app.py reports_pdf.py requirements.txt templates/base.html templates/person_detail.html templates/relatorios_pdf.html
   git commit -m "Adicionar relatorios PDF de atendimento e quantitativos"
   git pull --rebase origin main
   git push origin main
   ```

6. No Railway, aguarde a nova implantação Active e abra **Relatórios PDF** no menu do gestor ou atendente. O Railway instalará `reportlab` automaticamente a partir de `requirements.txt`.

**Atenção:** o `app.py.bak`, `instalar_relatorios_pdf.py` e o ZIP não precisam ser incluídos no commit. O instalador é idempotente: se já foi executado, não repete a inclusão das rotas nem dos botões.

## Como testar com dados fictícios

- Como gestor, crie uma unidade e uma pessoa fictícia, salve dois atendimentos de tipos diferentes e resultados diferentes.
- Na ficha da pessoa, clique em **PDF do cadastro** e em **PDF deste atendimento** em cada registro.
- No menu **Relatórios PDF**, selecione o mês atual e a unidade e baixe **Quantitativo** e **Listagem de registros**.
- Verifique se a contagem é 2 atendimentos e 1 pessoa distinta.
- Refaça o teste com outra unidade e um usuário atendente dessa unidade: ele não deve conseguir baixar dados de outra unidade.

## Segurança e uso institucional

- Gestor: relatórios da sua organização; pode escolher todas as unidades da organização.
- Atendente: sua unidade; PDF individual e relatórios agregados/lista.
- Leitor: sua unidade, apenas relatório quantitativo.
- Superadministrador: os relatórios de pessoas não ficam disponíveis nesse perfil, reduzindo o acesso central a dados sensíveis.
- O PDF de ficha cadastral é **sensível e identificável**; não deve ser enviado por e-mail ou mensagens sem canal oficial seguro e autorização institucional.
- Os valores de raça/cor, gênero, saúde e situação de rua devem ser tratados conforme LGPD e política institucional. O código não implementa homologação de segurança, governança de dados, classificação documental nem assinatura digital.
- A chave de criptografia `DATA_ENCRYPTION_KEY` não deve ser trocada sem planejamento de migração se houver cadastros já salvos.
- A fonte embutida padrão do ReportLab representa caracteres latinos do português. Nomes com escrita não latina poderão precisar de uma fonte Unicode licenciada e instalada no servidor.

## Rotas

- `GET /relatorios`
- `GET /relatorios/quantitativo.pdf?inicio=2026-11-01&fim=2026-11-30&unidade=todas`
- `GET /relatorios/registros.pdf?inicio=2026-11-01&fim=2026-11-30&unidade=2`
- `GET /pessoas/<id>/ficha.pdf`
- `GET /pessoas/<id>/atendimentos/<id_atendimento>/pdf`

Não existem migrations: a atualização usa as tabelas já existentes.
