# Casa em Ordem — Finanças da Família

Aplicação web para organizar as finanças de um casal: receitas, despesas, cartões, orçamento e poupanças, em um único container Docker. Interface em português, sem login e sem serviços externos.

## Recursos

- Dashboard mensal, histórico e projeção financeira de 12 meses.
- Receitas, descontos informativos em folha, despesas fixas, variáveis e planejadas.
- Cartões de crédito parcelados, cartões de débito e Vale Alimentação.
- Categorias, pessoas, contas, orçamentos e relatórios.
- Poupança por pessoa com depósitos, retiradas e juros de aplicações.
- Gráficos locais, exportação CSV e backup do banco SQLite.

## Tecnologias

Python 3.12 · FastAPI · SQLAlchemy · SQLite · Jinja2 · HTMX adaptado localmente · CSS responsivo · Docker Compose.

## Executar

Requer Docker Engine e Docker Compose.

```bash
git clone <URL-DO-REPOSITORIO>
cd familia-financas
docker compose up -d --build
```

Acesse **http://localhost:8080** ou `http://IP-DO-SERVIDOR:8080` na rede local.

Para acompanhar os logs:

```bash
docker compose logs -f familia-financas
```

Para parar a aplicação sem apagar os dados:

```bash
docker compose down
```

## Dados e segurança

O banco SQLite fica no volume Docker `familia_financas_data` e é preservado ao executar `docker compose down`. Não use `docker compose down -v` caso queira manter os dados.

A aplicação não possui autenticação. Mantenha o acesso restrito à sua rede local confiável e não exponha a porta diretamente à internet.

## Licença

Defina aqui a licença do projeto antes de publicá-lo (por exemplo, MIT).
