import penpine
from penpine.data import (
    Context, NamespacedView, DataProfile, Extract, capture, CaptureInterceptor,
    render, build_mapping, Identity, DataError, ExtractError, TemplateError,
)


def test_data_exports_exist():
    assert all([Context, NamespacedView, DataProfile, Extract, capture,
                CaptureInterceptor, render, build_mapping, Identity,
                DataError, ExtractError, TemplateError])


def test_top_level_reexports():
    assert penpine.Identity is Identity
    assert penpine.Context is Context
