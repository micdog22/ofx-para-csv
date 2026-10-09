import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ofx_para_csv.parser import (  # noqa: E402
    OFXError,
    build_tree,
    decode_bytes,
    merge,
    parse_amount,
    parse_date,
    parse_ofx,
    parse_ofx_file,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def minimal_ofx(transactions: str, header: str = "OFXHEADER:100\nDATA:OFXSGML\nCHARSET:1252\n\n") -> str:
    return (
        header
        + "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>BRL"
        + "<BANKACCTFROM><BANKID>999<ACCTID>1-1<ACCTTYPE>CHECKING</BANKACCTFROM>"
        + "<BANKTRANLIST>" + transactions + "</BANKTRANLIST>"
        + "</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
    )


class DateTests(unittest.TestCase):
    def test_full_date_with_brackets(self):
        d = parse_date("20240105143015.123[-3:BRT]")
        self.assertEqual(d.iso(), "2024-01-05T14:30:15.123-03:00")
        self.assertEqual(d.br(), "05/01/2024")

    def test_date_only(self):
        d = parse_date("20240229")
        self.assertFalse(d.has_time)
        self.assertEqual(d.iso(), "2024-02-29")
        self.assertEqual(d.br(), "29/02/2024")

    def test_shorter_forms_and_offsets(self):
        self.assertEqual(parse_date("202401051430").iso(), "2024-01-05T14:30:00")
        self.assertEqual(parse_date("20240105000000").iso(), "2024-01-05T00:00:00")
        self.assertEqual(parse_date("20240105120000[0:GMT]").iso(), "2024-01-05T12:00:00+00:00")
        self.assertEqual(parse_date("20240105120000[-03:BRT]").iso(), "2024-01-05T12:00:00-03:00")
        self.assertEqual(parse_date("20240105120000[+5.30:IST]").value.utcoffset(), timedelta(hours=5, minutes=30))
        self.assertEqual(parse_date("20240105120000[-3.5]").value.utcoffset(), -timedelta(hours=3, minutes=30))

    def test_local_date_is_kept_without_timezone_conversion(self):
        # 23h em Brasília já é dia seguinte em UTC, mas o extrato mostra o dia local.
        self.assertEqual(parse_date("20240131230000[-3:BRT]").br(), "31/01/2024")

    def test_empty_and_invalid(self):
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("   "))
        for raw in ("2024-01-05", "20240231", "20241305", "abc", "20240105120000[-30:XYZ]"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_date(raw)


class AmountTests(unittest.TestCase):
    def test_dot_and_comma(self):
        cases = {
            "-150.00": "-150.00",
            "-150,00": "-150.00",
            "1.234,56": "1234.56",
            "1,234.56": "1234.56",
            "+3500": "3500",
            " -0,99 ": "-0.99",
            "1.234.567": "1234567",
            ".50": "0.50",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_amount(raw), Decimal(expected))

    def test_invalid(self):
        for raw in ("", "abc", "1e5", "R$ 10,00", "--5", "1,2,3.4.5"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_amount(raw)


class EncodingTests(unittest.TestCase):
    def test_cp1252_declared(self):
        data = "OFXHEADER:100\nCHARSET:1252\n<OFX>SÃO PAULO".encode("cp1252")
        text, encoding = decode_bytes(data)
        self.assertIn("SÃO PAULO", text)
        self.assertEqual(encoding, "cp1252")

    def test_utf8_declared_as_1252_is_recovered(self):
        data = "OFXHEADER:100\nCHARSET:1252\n<OFX>AÇÃO".encode("utf-8")
        self.assertIn("AÇÃO", decode_bytes(data)[0])

    def test_utf8_declared_but_latin1_bytes_falls_back(self):
        data = "OFXHEADER:100\nENCODING:UTF-8\n<OFX>CAFÉ".encode("cp1252")
        self.assertIn("CAFÉ", decode_bytes(data)[0])

    def test_bom_is_removed(self):
        text, _ = decode_bytes(b"\xef\xbb\xbf<OFX></OFX>")
        self.assertTrue(text.startswith("<OFX>"))

    def test_unknown_declared_charset_does_not_break(self):
        data = b"OFXHEADER:100\nCHARSET:XYZ-999\n<OFX>\xe9"
        self.assertIn("é", decode_bytes(data)[0])


class TreeTests(unittest.TestCase):
    def test_unclosed_leaf_tags(self):
        root = build_tree("<STMTTRN><TRNAMT>-10.00\n<MEMO>PADARIA\n</STMTTRN>")
        trn = root.find("STMTTRN")
        self.assertEqual(trn.text("TRNAMT"), "-10.00")
        self.assertEqual(trn.text("MEMO"), "PADARIA")

    def test_empty_unclosed_tag_does_not_swallow_siblings(self):
        root = build_tree("<STMTTRN><NAME>\n<MEMO>PADARIA\n<FITID>9\n</STMTTRN>")
        trn = root.find("STMTTRN")
        self.assertEqual(trn.text("NAME"), "")
        self.assertEqual(trn.text("MEMO"), "PADARIA")
        self.assertEqual(trn.text("FITID"), "9")

    def test_empty_tag_followed_by_closed_sibling_with_same_name(self):
        root = build_tree("<STMTTRN><NAME>\n<MEMO>X\n<NAME>Y</NAME><FITID>1</STMTTRN>")
        trn = root.find("STMTTRN")
        self.assertEqual(trn.text("MEMO"), "X")
        self.assertEqual(trn.text("FITID"), "1")

    def test_unknown_aggregate_is_kept_apart(self):
        root = build_tree("<STMTTRN><EXTRA.INFO><NAME>INTERNO</EXTRA.INFO><NAME>LOJA</STMTTRN>")
        trn = root.find("STMTTRN")
        self.assertEqual(trn.text("NAME"), "LOJA")
        self.assertEqual(trn.find("EXTRA.INFO").text("NAME"), "INTERNO")

    def test_entities_lowercase_tags_and_comments(self):
        root = build_tree("<!-- comentário --><stmttrn><memo>A &amp; B &lt;3&gt; &#231;</memo><name/></stmttrn>")
        trn = root.find("STMTTRN")
        self.assertEqual(trn.text("MEMO"), "A & B <3> ç")
        self.assertEqual(trn.text("NAME"), "")

    def test_ampersand_without_entity_is_preserved(self):
        root = build_tree("<MEMO>R&COPY P&G AT&T")
        self.assertEqual(root.text("MEMO"), "R&COPY P&G AT&T")


class FixtureTests(unittest.TestCase):
    def test_sgml_bank_statement_cp1252(self):
        [account] = parse_ofx_file(FIXTURES / "bank_sgml_cp1252.ofx")
        self.assertEqual(account.kind, "banco")
        self.assertEqual((account.bank_id, account.branch_id, account.account_id), ("999", "0001", "12345-6"))
        self.assertEqual(account.account_type, "CHECKING")
        self.assertEqual(account.currency, "BRL")
        self.assertEqual(account.start.iso(), "2024-01-01T00:00:00-03:00")
        self.assertEqual(account.end.br(), "31/01/2024")
        self.assertEqual(account.ledger_balance, Decimal("4105.20"))
        self.assertEqual(account.available_balance, Decimal("4005.20"))
        self.assertEqual(len(account.transactions), 5)
        salary, light, snack, pix, fee = account.transactions
        self.assertEqual(salary.memo, "SALÁRIO EMPRESA EXEMPLO")
        self.assertEqual(salary.refnum, "778899")
        self.assertEqual(light.checknum, "000123")
        self.assertEqual(light.memo, "CONTA DE LUZ - SÃO PAULO")
        self.assertEqual(snack.name, "LANCHONETE EXEMPLO & CIA")
        self.assertEqual(snack.description, "LANCHONETE EXEMPLO & CIA - COMPRA NO DÉBITO")
        self.assertEqual(pix.memo, "PIX ENVIADO MARIA EXEMPLO")
        self.assertEqual(fee.type, "FEE")
        self.assertEqual(fee.amount, Decimal("-12.90"))

    def test_xml_bank_statement(self):
        [account] = parse_ofx_file(FIXTURES / "bank_xml.ofx")
        self.assertEqual(account.account_type, "SAVINGS")
        deposit, payment, interest = account.transactions
        self.assertEqual(deposit.date.iso(), "2024-02-02T09:30:15.250-03:00")
        self.assertEqual(deposit.memo, "Depósito em dinheiro")
        self.assertEqual(payment.name, "Café Exemplo Ltda")  # veio de PAYEE/NAME
        self.assertEqual(payment.memo, "")
        self.assertEqual(interest.amount, Decimal("5.32"))
        self.assertEqual(account.ledger_balance, Decimal("854.57"))

    def test_credit_card_statement(self):
        [card] = parse_ofx_file(FIXTURES / "credit_card.ofx")
        self.assertEqual(card.kind, "cartao")
        self.assertEqual(card.account_id, "0000********1234")
        self.assertEqual(card.account_type, "CREDITCARD")
        self.assertEqual([t.amount for t in card.transactions], [Decimal("-59.90"), Decimal("-320.00"), Decimal("1200.00")])
        self.assertEqual(card.ledger_balance, Decimal("-379.90"))

    def test_comma_amounts_and_compact_file(self):
        [account] = parse_ofx_file(FIXTURES / "comma_amounts.ofx")
        self.assertEqual([t.amount for t in account.transactions], [Decimal("2500.00"), Decimal("-1234.56"), Decimal("-0.99")])
        self.assertEqual(account.transactions[1].memo, "BOLETO ALUGUEL MARÇO")
        self.assertEqual(account.ledger_balance, Decimal("1264.45"))
        self.assertEqual(account.start.iso(), "2024-03-01")

    def test_multiple_accounts_in_one_file(self):
        accounts = parse_ofx_file(FIXTURES / "multiple_accounts.ofx")
        self.assertEqual([(a.kind, a.account_id) for a in accounts], [
            ("banco", "11111-1"), ("banco", "22222-2"), ("cartao", "0000********9876"),
        ])
        self.assertEqual(accounts[0].transactions[0].memo, "DEPÓSITO")
        self.assertEqual(accounts[0].transactions[0].name, "")

    def test_non_ofx_input(self):
        with self.assertRaises(OFXError) as ctx:
            parse_ofx_file(FIXTURES / "not_ofx.csv")
        self.assertIn("não parece ser um arquivo OFX", str(ctx.exception))
        self.assertIn("not_ofx.csv", str(ctx.exception))

    def test_ofx_without_statements(self):
        with self.assertRaises(OFXError) as ctx:
            parse_ofx(b"OFXHEADER:100\n<OFX><SIGNONMSGSRSV1></SIGNONMSGSRSV1></OFX>")
        self.assertIn("nenhum extrato", str(ctx.exception))

    def test_invalid_amount_and_date_are_reported(self):
        bad_amount = minimal_ofx("<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20240101<TRNAMT>dez reais<FITID>77</STMTTRN>")
        with self.assertRaises(OFXError) as ctx:
            parse_ofx(bad_amount.encode())
        self.assertIn("TRNAMT", str(ctx.exception))
        self.assertIn("77", str(ctx.exception))
        bad_date = minimal_ofx("<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20241399<TRNAMT>-1.00<FITID>78</STMTTRN>")
        with self.assertRaises(OFXError) as ctx:
            parse_ofx(bad_date.encode())
        self.assertIn("DTPOSTED", str(ctx.exception))


class MergeTests(unittest.TestCase):
    def load(self, *names):
        return [parse_ofx_file(FIXTURES / name) for name in names]

    def test_duplicates_across_files_are_removed(self):
        accounts, transactions, duplicates = merge(self.load("bank_sgml_cp1252.ofx", "overlapping.ofx"))
        self.assertEqual(duplicates, 3)
        self.assertEqual(len(transactions), 8)
        fitids = [t.fitid for t in transactions if t.fitid]
        self.assertEqual(len(fitids), len(set(fitids)))
        # As duas compras iguais sem FITID no mesmo arquivo são mantidas.
        self.assertEqual(sum(1 for t in transactions if t.memo == "CAFÉ DA ESQUINA"), 2)
        [account] = accounts
        self.assertEqual(account.start.br(), "01/01/2024")
        self.assertEqual(account.end.br(), "10/02/2024")
        self.assertEqual(account.ledger_balance, Decimal("4240.20"))  # o saldo mais recente
        self.assertEqual(account.sources, ["bank_sgml_cp1252.ofx", "overlapping.ofx"])

    def test_same_file_twice_adds_nothing(self):
        _, transactions, duplicates = merge(self.load("overlapping.ofx", "overlapping.ofx"))
        self.assertEqual(len(transactions), 6)
        self.assertEqual(duplicates, 6)

    def test_fallback_key_counts_occurrences(self):
        one = minimal_ofx("<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20240105<TRNAMT>-5.00<MEMO>CAFÉ</STMTTRN>")
        three = minimal_ofx(
            "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20240105<TRNAMT>-5.00<MEMO>CAFÉ</STMTTRN>" * 3
        )
        _, transactions, duplicates = merge([parse_ofx(one.encode()), parse_ofx(three.encode())])
        self.assertEqual(len(transactions), 3)
        self.assertEqual(duplicates, 1)

    def test_same_fitid_in_different_accounts_is_not_duplicate(self):
        _, transactions, duplicates = merge(self.load("multiple_accounts.ofx"))
        self.assertEqual(len(transactions), 3)
        self.assertEqual(duplicates, 0)

    def test_sorted_by_date_across_files(self):
        _, transactions, _ = merge(self.load("comma_amounts.ofx", "bank_xml.ofx", "credit_card.ofx"))
        keys = [t.date.sort_key() for t in transactions]
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main()
