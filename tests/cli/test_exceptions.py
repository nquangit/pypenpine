from penpine.cli.exceptions import CliError, ScaffoldError, VenvError
from penpine.exceptions import PenpineError


def test_cli_errors_subclass_penpine_error():
    assert issubclass(CliError, PenpineError)
    assert issubclass(ScaffoldError, CliError)
    assert issubclass(VenvError, CliError)


def test_errors_carry_message():
    assert str(ScaffoldError("boom")) == "boom"
