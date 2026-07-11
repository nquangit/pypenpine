import penpine
from penpine.data import (
    CaptureInterceptor,
    Context,
    DataError,
    DataProfile,
    Extract,
    ExtractError,
    Identity,
    NamespacedView,
    TemplateError,
    build_mapping,
    capture,
    render,
)


def test_data_exports_exist():
    assert all(
        [
            Context,
            NamespacedView,
            DataProfile,
            Extract,
            capture,
            CaptureInterceptor,
            render,
            build_mapping,
            Identity,
            DataError,
            ExtractError,
            TemplateError,
        ]
    )


def test_top_level_reexports():
    assert penpine.Identity is Identity
    assert penpine.Context is Context
