from penpine.exceptions import PenpineError
from penpine.data.exceptions import DataError, ExtractError, TemplateError


def test_hierarchy():
    for cls in (ExtractError, TemplateError):
        assert issubclass(cls, DataError)
    assert issubclass(DataError, PenpineError)
