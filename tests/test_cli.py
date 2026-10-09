import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ofx_para_csv import __version__  # noqa: E402
from ofx_para_csv.cli import main  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run(*args, stdin: bytes = b""):
    """Roda a CLI e devolve (código de saída, stdout, stderr)."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    err = io.StringIO()
    fake_stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
    with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
            mock.patch.object(sys, "stdin", fake_stdin):
        try:
            code = main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code
    out.flush()
    return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_csv_to_stdout(self):
        code, out, err = run(FIXTURES / "bank_sgml_cp1252.ofx")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("Data;Descrição;Valor;"))
        self.assertIn("15/01/2024;PIX ENVIADO MARIA EXEMPLO;-250,00;Transferência", out)
        self.assertEqual(err, "")

    def test_output_file_with_bom(self):
        target = self.tmp / "extrato.csv"
        code, out, err = run(FIXTURES / "bank_sgml_cp1252.ofx", FIXTURES / "overlapping.ofx", "--bom", "-o", target)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        raw = target.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbfData;"))
        self.assertEqual(raw.decode("utf-8-sig").count("\r\n"), 9)  # cabeçalho + 8 transações
        self.assertIn("8 transações gravadas", err)
        self.assertIn("3 transações repetidas", err)

    def test_json_format(self):
        code, out, _ = run(FIXTURES / "credit_card.ofx", "--formato", "json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["contas"][0]["tipo"], "cartao")
        self.assertEqual(len(data["transacoes"]), 3)

    def test_summary(self):
        code, out, _ = run(FIXTURES / "comma_amounts.ofx", "--resumo")
        self.assertEqual(code, 0)
        self.assertIn("Créditos:         R$ 2.500,00 (1)", out)
        self.assertIn("Débitos:          R$ 1.235,55 (2)", out)
        self.assertIn("Saldo do período: R$ 1.264,45", out)

    def test_summary_json(self):
        code, out, _ = run(FIXTURES / "comma_amounts.ofx", "--resumo", "-f", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["resumo"][0]["debitos"], 1235.55)

    def test_separator_aliases(self):
        code, out, _ = run(FIXTURES / "comma_amounts.ofx", "--separador", "tab", "--decimal", "ponto")
        self.assertEqual(code, 0)
        self.assertIn("04/03/2024\tTED RECEBIDA\t2500.00\t", out)

    def test_reads_stdin(self):
        data = (FIXTURES / "bank_xml.ofx").read_bytes()
        code, out, _ = run("-", stdin=data)
        self.assertEqual(code, 0)
        self.assertIn("Café Exemplo Ltda", out)

    def test_errors(self):
        code, _, err = run(FIXTURES / "not_ofx.csv")
        self.assertEqual(code, 1)
        self.assertIn("não parece ser um arquivo OFX", err)
        code, _, err = run(self.tmp / "nao-existe.ofx")
        self.assertEqual(code, 1)
        self.assertIn("arquivo não encontrado", err)

    def test_usage_errors(self):
        code, _, err = run(FIXTURES / "bank_xml.ofx", "--separador", ";;")
        self.assertEqual(code, 2)
        self.assertIn("separador inválido", err)
        code, _, err = run(FIXTURES / "bank_xml.ofx", "--formato", "xml")
        self.assertEqual(code, 2)
        self.assertIn("opção inválida", err)
        code, _, err = run()
        self.assertEqual(code, 2)
        self.assertIn("faltam argumentos obrigatórios", err)

    def test_never_overwrites_an_input(self):
        source = self.tmp / "extrato.ofx"
        shutil.copy(FIXTURES / "bank_xml.ofx", source)
        code, _, err = run(source, "-o", source)
        self.assertEqual(code, 2)
        self.assertIn("não pode ser um dos arquivos de entrada", err)
        self.assertEqual(source.read_bytes(), (FIXTURES / "bank_xml.ofx").read_bytes())

    def test_version(self):
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(__version__, out)


if __name__ == "__main__":
    unittest.main()
