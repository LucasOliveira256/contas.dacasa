#!/usr/bin/env python3
"""Lista, SEM ALTERAR NADA, gastos que provavelmente duplicam descontos em folha.

Desde que os descontos passaram a abater o saldo, um desconto (INSS, IR, plano de saúde, vale)
que também foi lançado como gasto em /transacoes é subtraído duas vezes.

Uso (sempre numa CÓPIA do banco; o arquivo é aberto somente para leitura):
    python scripts/listar_descontos_duplicados.py caminho/para/copia.db

Revise a lista e cancele cada gasto duplicado em /transacoes (botão Cancelar). Gastos cancelados
saem dos cálculos e o histórico é preservado.
"""
import re
import sqlite3
import sys
from collections import defaultdict

KEYWORDS = re.compile(r"\b(inss|irrf?|imposto de renda|plano de sa[uú]de|conv[eê]nio|unimed|vale)\b", re.I)


def main(path: str) -> None:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    deductions = db.execute(
        "SELECT happened_on, kind, amount_cents FROM incomes WHERE included_in_cashflow = 0").fetchall()
    amounts_by_month = defaultdict(set)
    for row in deductions:
        amounts_by_month[row["happened_on"][:7]].add(row["amount_cents"])
    rows = db.execute("""
        SELECT t.id, t.purchase_date, t.cashflow_date, t.description, t.amount_cents, t.status,
               c.name AS category, p.name AS category_parent
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        LEFT JOIN categories p ON p.id = c.parent_id
        WHERE t.status != 'cancelado'
        ORDER BY t.cashflow_date, t.id""").fetchall()
    found = 0
    for row in rows:
        reasons = []
        if "(informativo)" in (row["category"] or "").lower():
            reasons.append("categoria marcada como informativa")
        if KEYWORDS.search(row["description"] or "") or KEYWORDS.search(row["category"] or ""):
            reasons.append("descrição/categoria cita desconto em folha")
        if row["amount_cents"] in amounts_by_month.get(row["cashflow_date"][:7], set()):
            reasons.append("mesmo valor de um desconto do mês")
        if reasons:
            found += 1
            print(f"#{row['id']:<5} {row['cashflow_date']}  R$ {row['amount_cents'] / 100:>10,.2f}  "
                  f"{row['status']:<9} {row['category_parent'] + ' > ' if row['category_parent'] else ''}{row['category']} "
                  f"| {row['description']}\n        motivo: {'; '.join(reasons)}")
    print(f"\n{found} gasto(s) candidato(s) em {len(rows)} ativos. Nada foi alterado.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
