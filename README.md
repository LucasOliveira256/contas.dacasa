# Casa em ordem — Finanças da família

Aplicação web local para organizar receitas, despesas, cartões, orçamento, projeções e poupanças pessoais. Não exige autenticação nem serviço externo durante o uso. O banco SQLite fica no volume persistente `/data`.

## Executar

```bash
docker compose up -d --build
```

Abra `http://IP-DO-SERVIDOR:8080` na rede local. No próprio servidor, use `http://localhost:8080`.

Para parar sem apagar os dados:

```bash
docker compose down
```

Depois, `docker compose up -d` volta a usar o mesmo volume. Para ver logs: `docker compose logs -f familia-financas`.

## Alterações nesta versão

- Pessoas podem ser editadas ou excluídas; pessoas que já aparecem no histórico são inativadas para preservar os lançamentos.
- Categorias podem ser excluídas. As excluídas saem dos formulários novos; o histórico antigo continua ligado à categoria inativa. A taxonomia `Lazer/Moto` é migrada para `Lazer`, com as subcategorias antigas inativadas.
- Descontos em folha têm os tipos Plano de saúde, INSS, IR, Vale e Outros. São informativos e não entram novamente no fluxo de caixa.
- Cartões têm tipos Crédito, Débito e Vale Alimentação. Só os cartões de crédito têm dias de fechamento/vencimento e fatura; os lançamentos de débito e vale usam a data da compra e não permitem parcelamento.
- A página **Poupança** permite criar contas de capital por pessoa, registrar depósitos, retiradas e juros de aplicações. O capital é calculado em centavos; retirada acima do saldo é recusada. O saldo inicial é informado ao criar a poupança.

## Regras importantes

- Valores financeiros são armazenados e calculados como centavos inteiros. O formulário aceita, por exemplo, `1.234,56`.
- A compra no cartão de crédito é classificada por sua data original para relatórios por categoria; a saída do caixa cai na data de vencimento da fatura. O cartão não gera uma segunda despesa de pagamento.
- Compra parcelada recebe uma linha por parcela/fatura; os centavos restantes são distribuídos nas primeiras parcelas para que a soma permaneça idêntica ao total da compra.
- Gastos fixos geram ocorrências mensais por até 12 meses à frente e não duplicam ocorrências já existentes. Edite uma ocorrência em **Gastos** para ajustar só aquele mês.
- Depósitos, retiradas e juros na página **Poupança** compõem um livro auxiliar de capital, separado de despesas/receitas do orçamento doméstico; assim, transferir dinheiro para a poupança não é contado como consumo.
- Plano de saúde, INSS, IR e demais descontos em folha ficam informativos e não entram como uma segunda despesa nem reduzem novamente o salário. Cadastre como salário o valor líquido que efetivamente entra na conta.
- A projeção considera as receitas cadastradas nas datas correspondentes. Ela não presume salários futuros automaticamente; lance as entradas futuras para vê-las na projeção.
- O backup usa o mecanismo de backup do SQLite para gerar um arquivo consistente, inclusive quando o banco está em uso.

## Arquitetura e operação

- Python 3.12, FastAPI, SQLAlchemy, SQLite, Jinja2 e templates responsivos.
- As tabelas são criadas na primeira execução. Categorias e pessoas iniciais são inseridas de forma idempotente; o banco existente recebe uma migração aditiva para o tipo do cartão, e novas tabelas de poupança são criadas sem apagar dados.
- Fuso horário do container: `America/Cuiaba`.
- Sem CDN: os gráficos são desenhados em canvas por um renderizador JavaScript local, e o adaptador HTMX usado em uma tela é local. O ambiente de geração não tinha acesso à rede para baixar as distribuições oficiais de Chart.js e HTMX; esses arquivos oficiais não estão embutidos. As telas e quatro gráficos continuam funcionando offline com as implementações locais incluídas, mas não são as distribuições upstream dessas bibliotecas.

## Segurança e rede

A aplicação não tem autenticação conforme solicitado. Exponha a porta 8080 apenas na rede confiável; não publique diretamente na internet.
