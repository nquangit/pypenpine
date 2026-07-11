"""Identity: an actor bundling auth/manager + data + context."""

from __future__ import annotations

from penpine.data.capture import capture
from penpine.data.context import Context
from penpine.data.exceptions import DataError
from penpine.data.profile import DataProfile
from penpine.data.template import build_mapping, render


class Identity:
    def __init__(
        self, name, *, auth_profile=None, manager=None, data=None, context=None, **manager_kw
    ):
        self.name = name
        self.auth_profile = auth_profile
        if manager is not None:
            self._manager = manager
        elif auth_profile is not None:
            self._manager = auth_profile.manager(**manager_kw)
        else:
            self._manager = None
        self.data = data if data is not None else DataProfile(name)
        self.ctx = context if context is not None else Context()

    @property
    def manager(self):
        return self._manager

    async def send(self, request, **kwargs):
        if self._manager is None:
            raise DataError(f"identity {self.name!r} has no manager to send with")
        return await self._manager.send(request, **kwargs)

    def send_sync(self, request, **kwargs):
        if self._manager is None:
            raise DataError(f"identity {self.name!r} has no manager to send with")
        return self._manager.send_sync(request, **kwargs)

    def render(self, request, *, strict=True):
        mapping = build_mapping(context=self.ctx, data=self.data)
        return render(request, mapping, strict=strict)

    def capture(self, response, specs):
        return capture(self.ctx, response, specs)
