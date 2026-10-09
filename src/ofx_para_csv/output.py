"""Formatos de saída: CSV, JSON e resumo do período."""

from __future__ import annotations

import csv
import io
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from .parser import Account, OFXDate, Transaction

TYPE_LABELS = {
    "CREDIT": "Crédito",
    "DEBIT": "Débito",
    "INT": "Juros",
    "DIV": "Dividendos",
    "FEE": "Tarifa",
    "SRVCHG": "Taxa de serviço",
    "DEP": "Depósito",
    "ATM": "Caixa eletrônico",
    "POS": "Compra",
    "XFER": "Transferência",
    "CHECK": "Cheque",
    "PAYMENT": "Pagamento",
    "CASH": "Saque",
    "DIRECTDEP": "Depósito direto",
    "DIRECTDEBIT": "Débito automático",
    "REPEATPMT": "Pagamento recorrente",
    "HOLD": "Valor bloqueado",
    "OTHER": "Outros",
}

CSV_HEADER = ["Data", "Descrição", "Valor", "Tipo", "Documento", "FITID", "Banco", "Conta"]


def type_label(code: str) -> str:
    return TYPE_LABELS.get(code, code)


def format_amount(value: Decimal, decimal: str = ",") -> str:
    """Valor com pelo menos duas casas e sem separador de milhar (bom para planilhas)."""
    if value.as_tuple().exponent > -2:
        value = value.quantize(Decimal("0.01"))
    if value == 0:
        value = abs(value)
    text = format(value, "f")
    return text.replace(".", ",") if decimal == "," else text


def format_money(value: Decimal, currency: str = "BRL") -> str:
    """Formato brasileiro: R$ 1.234,56 e -R$ 1.234,56."""
    value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, cents = f"{abs(value):.2f}".split(".")
    integer = f"{int(integer):,}".replace(",", ".")
    symbol = "R$" if currency in ("", "BRL") else currency
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol} {integer},{cents}"


def _number(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(abs(value) if value == 0 else value)


def _iso(date: Optional[OFXDate]) -> Optional[str]:
    return date.iso() if date else None


def duplicates_message(count: int) -> str:
    if count == 1:
        return "1 transação repetida entre arquivos foi ignorada."
    return f"{count} transações repetidas entre arquivos foram ignoradas."


# ---------------------------------------------------------------- CSV e JSON

def to_csv(
    transactions: List[Transaction],
    separator: str = ";",
    decimal: str = ",",
    date_style: str = "br",
) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=separator, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for t in transactions:
        date = ""
        if t.date:
            date = t.date.br() if date_style == "br" else t.date.iso()
        writer.writerow([
            date,
            t.description,
            format_amount(t.amount, decimal),
            type_label(t.type),
            t.document,
            t.fitid,
            t.bank_id,
            t.account_id,
        ])
    return buffer.getvalue()


def _account_dict(account: Account) -> dict:
    return {
        "tipo": account.kind,
        "banco": account.bank_id,
        "agencia": account.branch_id,
        "conta": account.account_id,
        "tipo_conta": account.account_type,
        "moeda": account.currency,
        "inicio": _iso(account.start),
        "fim": _iso(account.end),
        "saldo": _number(account.ledger_balance),
        "saldo_data": _iso(account.ledger_date),
        "saldo_disponivel": _number(account.available_balance),
        "saldo_disponivel_data": _iso(account.available_date),
        "transacoes": len(account.transactions),
        "arquivos": account.sources,
    }


def _transaction_dict(t: Transaction) -> dict:
    return {
        "data": _iso(t.date),
        "valor": _number(t.amount),
        "tipo": t.type,
        "tipo_descricao": type_label(t.type),
        "descricao": t.description,
        "nome": t.name,
        "memo": t.memo,
        "fitid": t.fitid,
        "documento": t.checknum,
        "referencia": t.refnum,
        "banco": t.bank_id,
        "conta": t.account_id,
        "arquivo": t.source,
    }


def to_json(accounts: List[Account], transactions: List[Transaction], duplicates: int = 0) -> str:
    data = {
        "contas": [_account_dict(a) for a in accounts],
        "transacoes": [_transaction_dict(t) for t in transactions],
        "duplicadas_removidas": duplicates,
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------- resumo

def summarize(transactions: List[Transaction], start=None, end=None) -> dict:
    """Totais do período. Sem DTSTART/DTEND, usa a primeira e a última transação."""
    credits = [t.amount for t in transactions if t.amount > 0]
    debits = [t.amount for t in transactions if t.amount < 0]
    dates = [t.date for t in transactions if t.date]
    if start is None and dates:
        start = min(dates, key=OFXDate.sort_key)
    if end is None and dates:
        end = max(dates, key=OFXDate.sort_key)
    return {
        "quantidade": len(transactions),
        "creditos": sum(credits, Decimal("0")),
        "qtd_creditos": len(credits),
        "debitos": abs(sum(debits, Decimal("0"))),
        "qtd_debitos": len(debits),
        "saldo_periodo": sum((t.amount for t in transactions), Decimal("0")),
        "inicio": start,
        "fim": end,
    }


def _summaries(accounts: List[Account], transactions: List[Transaction]) -> List[tuple]:
    """Lista de (conta ou None para o total geral, resumo, moeda)."""
    parts = [(a, summarize(a.transactions, a.start, a.end), a.currency) for a in accounts]
    if len(accounts) > 1:
        starts = [a.start for a in accounts if a.start] + [t.date for t in transactions if t.date]
        ends = [a.end for a in accounts if a.end] + [t.date for t in transactions if t.date]
        total = summarize(
            transactions,
            min(starts, key=OFXDate.sort_key) if starts else None,
            max(ends, key=OFXDate.sort_key) if ends else None,
        )
        currencies = {a.currency for a in accounts}
        parts.append((None, total, currencies.pop() if len(currencies) == 1 else ""))
    return parts


def _account_title(account: Account) -> str:
    if account.kind == "cartao":
        return f"Cartão {account.account_id or '(sem número)'}"
    details = []
    if account.bank_id:
        details.append(f"banco {account.bank_id}")
    if account.branch_id:
        details.append(f"agência {account.branch_id}")
    title = f"Conta {account.account_id or '(sem número)'}"
    return f"{title} ({', '.join(details)})" if details else title


def render_summary(accounts: List[Account], transactions: List[Transaction], duplicates: int = 0) -> str:
    lines = []
    for account, s, currency in _summaries(accounts, transactions):
        period = f"{s['inicio'].br()} a {s['fim'].br()}" if s["inicio"] and s["fim"] else "não informado"
        lines.append(_account_title(account) if account else "Total geral")
        lines.append(f"  Período:          {period}")
        lines.append(f"  Transações:       {s['quantidade']}")
        lines.append(f"  Créditos:         {format_money(s['creditos'], currency)} ({s['qtd_creditos']})")
        lines.append(f"  Débitos:          {format_money(s['debitos'], currency)} ({s['qtd_debitos']})")
        lines.append(f"  Saldo do período: {format_money(s['saldo_periodo'], currency)}")
        if account is not None and account.ledger_balance is not None:
            when = f" em {account.ledger_date.br()}" if account.ledger_date else ""
            lines.append(f"  Saldo informado:  {format_money(account.ledger_balance, currency)}{when}")
        lines.append("")
    if duplicates:
        lines.append(duplicates_message(duplicates))
    return "\n".join(lines).rstrip("\n") + "\n"


def summary_to_json(accounts: List[Account], transactions: List[Transaction], duplicates: int = 0) -> str:
    items = []
    for account, s, currency in _summaries(accounts, transactions):
        item = {
            "tipo": account.kind if account else "total",
            "banco": account.bank_id if account else None,
            "conta": account.account_id if account else None,
            "moeda": currency,
            "inicio": _iso(s["inicio"]),
            "fim": _iso(s["fim"]),
            "quantidade": s["quantidade"],
            "creditos": _number(s["creditos"]),
            "debitos": _number(s["debitos"]),
            "saldo_periodo": _number(s["saldo_periodo"]),
        }
        if account is not None:
            item["saldo_informado"] = _number(account.ledger_balance)
        items.append(item)
    data = {"resumo": items, "duplicadas_removidas": duplicates}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
