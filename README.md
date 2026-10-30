# Contas da Casa — Gestão Financeira Familiar

Aplicação web para controlar receitas, despesas, cartões, orçamento e poupanças familiares. Executa em um container Docker, com SQLite persistente e interface responsiva em português. Interface inspirada no sistema visual Stripi: navy profundo, índigo elétrico, gradientes atmosféricos, tipografia leve e números tabulares. Tema Dark padrão e alternativa Material Light.

## Funcionalidades

- Dashboard mensal com gráfico de linhas de entradas x saídas, histórico e projeção de 12 meses.
- Menu lateral expansível por hover no desktop e recolhível no celular; tema Dark e Material Light.
- Cartões visuais com cores por emissor e exibição opcional dos quatro últimos dígitos (o número completo não é armazenado).
- Receitas, despesas fixas/variáveis/planejadas e parcelamento no crédito.
- Receitas e descontos em folha (INSS, IR, plano de saúde, vale) com repetição mensal até um mês escolhido ou sem data final; edição e exclusão só do mês, do mês em diante ou da série toda. Os descontos são abatidos do saldo previsto.
- Cartão de crédito editável (limite, fechamento e vencimento): ao mudar fechamento ou vencimento, a fatura de todas as compras do cartão é recalculada.
- Cartões de crédito, débito e Vale Alimentação.
- Pessoas, categorias, contas, orçamentos e relatórios.
- Poupança por pessoa, com depósitos, retiradas e juros.
- Gráficos offline, exportação CSV e backup do banco.
- Login, gestão de usuários, troca obrigatória de senhas iniciais e proteção CSRF.

## Identidade visual

O frontend utiliza uma interpretação do `DESIGN-stripe.md`: paleta índigo/navy, malha de gradientes sem imagens externas, botões pill, cartões de 12px, campos compactos e números financeiros com algarismos tabulares. O shell da dashboard permanece escuro por padrão; Material Light pode ser selecionado no cabeçalho e a preferência fica salva no navegador. A fonte usa Inter/SF Pro Display ou fontes de sistema como fallback, sem requisições externas.

## Executar

Requer Docker Engine e Docker Compose.

```bash
git clone <URL-DO-REPOSITORIO>
cd contas.dacasa
cp .env.example .env
# Mantenha COOKIE_SECURE=true em produção e configure FORWARDED_ALLOW_IPS para o IP confiável do proxy.
docker compose up -d --build
```

A aplicação escuta a porta `8080`. Para acesso público, configure um proxy reverso com HTTPS e acesse pelo domínio HTTPS. **Não encaminhe a porta 8080 diretamente à internet.**

Se ainda não houver proxy HTTPS e for necessário configurar a senha inicial em rede local usando HTTP simples, defina temporariamente `COOKIE_SECURE=false` em `.env`, inicie a aplicação e acesse `http://localhost:8080`. Troque a senha antes de liberar o acesso público; configure HTTPS no proxy, volte `COOKIE_SECURE=true` e reinicie:

```bash
docker compose up -d --build
docker compose logs -f familia-financas
```

## Primeiro acesso e usuários

- Usuário inicial: `Admin`
- Senha provisória: `admin`
- O primeiro login exige uma nova senha com pelo menos 12 caracteres. Faça essa troca antes de liberar o acesso público.
- O Admin pode criar usuários e redefinir senhas na página **Usuários**. Senhas redefinidas são provisórias e exigem troca no próximo login.
- Todos os usuários podem alterar a própria senha. O Admin utiliza a ação **Redefinir senha** na conta desejada.

## Segurança e persistência

- Senhas protegidas por hash Argon2; sessões assinadas com validade de 8 horas; formulários protegidos contra CSRF; limite de tentativas de login.
- O processo web roda sem privilégios de root. Banco SQLite e segredo de sessão ficam no volume Docker `familia_financas_data`, com permissões restritas. O segredo é gerado automaticamente e persiste entre reinicializações; trocar a senha invalida sessões anteriores.
- Se o proxy reverso estiver em outro IP, defina `FORWARDED_ALLOW_IPS` em `.env` com o IP exato e confiável do proxy — nunca use `*`.
- No MikroTik, encaminhe as portas públicas HTTPS somente para o proxy reverso; não crie DST-NAT público para a porta `8080`.
- `docker compose down` preserva os dados. **Não use `docker compose down -v`**, pois isso remove o volume.
- O SQLite não é criptografado em repouso: restrinja o acesso ao host e proteja backups. Para risco de acesso físico ao disco, use criptografia de disco/volume no sistema operacional. Mantenha backups em local seguro.

## Atualização de bancos existentes

A migração é automática ao iniciar: a tabela `recurring_incomes` e as colunas `recurring_income_id` e `occurrence_month` em `incomes` são criadas sem alterar os lançamentos já existentes. Descontos antigos que também foram lançados como gasto passam a ser subtraídos duas vezes; use `python scripts/listar_descontos_duplicados.py copia.db` (somente leitura) para listá-los e cancele-os em Transações. Faça backup em `/backup.db` antes de editar fechamento ou vencimento de um cartão.

## Comandos úteis

```bash
docker compose logs -f familia-financas
docker compose down
docker compose up -d
```

## Licença

Defina a licença desejada antes de publicar o repositório (por exemplo, MIT).
