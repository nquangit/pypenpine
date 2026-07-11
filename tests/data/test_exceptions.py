from penpine.data.exceptions import DataError, ExtractError, TemplateError
from penpine.exceptions import PenpineError


def test_hierarchy():
    for cls in (ExtractError, TemplateError):
        assert issubclass(cls, DataError)
    assert issubclass(DataError, PenpineError)
