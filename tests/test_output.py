import csv
import io
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ofx_para_csv.output import (  # noqa: E402
    CSV_HEADER,
    format_amount,
    format_money,
    render_summary,
    summarize,
    summary_to_json,
    to_csv,
    to_json,
    type_label,
)
from ofx_para_csv.parser import merge, parse_ofx_file  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(*names):
    return merge([parse_ofx_file(FIXTURES / name) for name in names])


class FormatTests(unittest.TestCase):
    def test_format_amount(self):
        self.assertEqual(format_amount(Decimal("-150")), "-150,00")
        self.assertEqual(format_amount(Decimal("1234.5")), "1234,50")
        self.assertEqual(format_amount(Decimal("0.001")), "0,001")
        self.assertEqual(format_amount(Decimal("-0.00")), "0,00")
        self.assertEqual(format_amount(Decimal("1234.56"), "."), "1234.56")

    def test_format_money(self):
        self.assertEqual(format_money(Decimal("1234.56")), "R$ 1.234,56")
        self.assertEqual(format_money(Decimal("-1234567.8")), "-R$ 1.234.567,80")
        self.assertEqual(format_money(Decimal("0.005")), "R$ 0,01")
        self.assertEqual(format_money(Decimal("10"), "USD"), "USD 10,00")

    def test_type_labels(self):
        self.assertEqual(type_label("XFER"), "Transferência")
        self.assertEqual(type_label("SRVCHG"), "Taxa de serviço")
        self.assertEqual(type_label("NOVOTIPO"), "NOVOTIPO")


class CsvTests(unittest.TestCase):
    def test_default_is_excel_br(self):
        _, transactions, _ = load("bank_sgml_cp1252.ofx")
        text = to_csv(transactions)
        lines = text.split("\r\n")
        self.assertEqual(lines[0], ";".join(CSV_HEADER))
        self.assertEqual(lines[1], "05/01/2024;SALÁRIO EMPRESA EXEMPLO;3500,00;Crédito;778899;202401050001;999;12345-6")
        self.assertIn("08/01/2024;CONTA DE LUZ - SÃO PAULO;-89,90;Débito;000123;", lines[2])

    def test_custom_separator_decimal_and_iso_dates(self):
        _, transactions, _ = load("bank_sgml_cp1252.ofx")
        rows = list(csv.reader(io.StringIO(to_csv(transactions, ",", ".", "iso"))))
        self.assertEqual(rows[1][0], "2024-01-05T10:00:00-03:00")
        self.assertEqual(rows[1][2], "3500.00")
        self.assertEqual(rows[2][2], "-89.90")

    def test_fields_with_separator_are_quoted(self):
        _, transactions, _ = load("bank_xml.ofx")
        text = to_csv(transactions, separator=",", decimal=",")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][2], "1000,00")
        self.assertEqual(len(rows[1]), len(CSV_HEADER))


class JsonTests(unittest.TestCase):
    def test_structure(self):
        accounts, transactions, duplicates = load("bank_sgml_cp1252.ofx", "overlapping.ofx")
        data = json.loads(to_json(accounts, transactions, duplicates))
        self.assertEqual(data["duplicadas_removidas"], 3)
        self.assertEqual(len(data["transacoes"]), 8)
        first = data["transacoes"][0]
        self.assertEqual(first["data"], "2024-01-05T10:00:00-03:00")
        self.assertEqual(first["valor"], 3500.0)
        self.assertEqual(first["tipo"], "CREDIT")
        self.assertEqual(first["tipo_descricao"], "Crédito")
        [account] = data["contas"]
        self.assertEqual(account["saldo"], 4240.2)
        self.assertEqual(account["inicio"], "2024-01-01T00:00:00-03:00")
        self.assertEqual(account["arquivos"], ["bank_sgml_cp1252.ofx", "overlapping.ofx"])

    def test_keeps_accents(self):
        accounts, transactions, _ = load("bank_xml.ofx")
        self.assertIn("Depósito em dinheiro", to_json(accounts, transactions))


class SummaryTests(unittest.TestCase):
    def test_summarize_values(self):
        accounts, transactions, _ = load("bank_sgml_cp1252.ofx")
        s = summarize(transactions, accounts[0].start, accounts[0].end)
        self.assertEqual(s["quantidade"], 5)
        self.assertEqual(s["creditos"], Decimal("3500.00"))
        self.assertEqual(s["debitos"], Decimal("395.30"))
        self.assertEqual(s["saldo_periodo"], Decimal("3104.70"))
        self.assertEqual((s["qtd_creditos"], s["qtd_debitos"]), (1, 4))

    def test_period_falls_back_to_transactions(self):
        _, transactions, _ = load("credit_card.ofx")
        s = summarize(transactions)
        self.assertEqual(s["inicio"].br(), "07/02/2024")
        self.assertEqual(s["fim"].br(), "20/02/2024")

    def test_no_debits_is_zero_not_negative_zero(self):
        _, transactions, _ = load("credit_card.ofx")
        credits_only = [t for t in transactions if t.amount > 0]
        self.assertEqual(str(summarize(credits_only)["debitos"]), "0")

    def test_render_text(self):
        accounts, transactions, duplicates = load("bank_sgml_cp1252.ofx", "overlapping.ofx")
        text = render_summary(accounts, transactions, duplicates)
        self.assertIn("Conta 12345-6 (banco 999, agência 0001)", text)
        self.assertIn("Período:          01/01/2024 a 10/02/2024", text)
        self.assertIn("Créditos:         R$ 3.650,00 (2)", text)
        self.assertIn("Débitos:          R$ 410,30 (6)", text)
        self.assertIn("Saldo do período: R$ 3.239,70", text)
        self.assertIn("Saldo informado:  R$ 4.240,20 em 10/02/2024", text)
        self.assertIn("3 transações repetidas entre arquivos foram ignoradas.", text)
        self.assertNotIn("Total geral", text)

    def test_total_for_multiple_accounts(self):
        accounts, transactions, _ = load("multiple_accounts.ofx")
        text = render_summary(accounts, transactions)
        self.assertIn("Cartão 0000********9876", text)
        self.assertIn("Total geral", text)
        data = json.loads(summary_to_json(accounts, transactions))
        total = data["resumo"][-1]
        self.assertEqual(total["tipo"], "total")
        self.assertEqual(total["quantidade"], 3)
        self.assertEqual(total["creditos"], 200.0)
        self.assertEqual(total["debitos"], 45.0)
        self.assertEqual(total["saldo_periodo"], 155.0)


if __name__ == "__main__":
    unittest.main()
