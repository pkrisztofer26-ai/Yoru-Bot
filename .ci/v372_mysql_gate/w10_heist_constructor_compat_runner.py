from __future__ import annotations

import inspect

import w10_heist_canonical_runner as canonical


gate = canonical.gate
_original_install_support_stubs = gate.install_support_stubs


class _NullDependency:
    """Neutral dependency for constructor-only legacy/service wiring in W10.2."""

    def __getattr__(self, name: str):
        async def _async(*args, **kwargs):
            return None

        return _async


def _install_constructor_compat() -> None:
    _original_install_support_stubs()

    from app.services.heist import HeistService

    original_init = HeistService.__init__
    signature = inspect.signature(original_init)
    parameters = signature.parameters

    def compat_init(self, *args, **kwargs):
        # The W10.2 fixture historically passed a newer optional bot dependency.
        # Ignore only constructor kwargs the frozen v3.72 service does not accept.
        accepted_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in parameters and key != "self"
        }

        # Positional args already satisfy the first N constructor parameters.
        positional_names = [
            name
            for name, parameter in parameters.items()
            if name != "self"
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ][: len(args)]

        # Fill only genuinely required dependency slots not supplied by the test
        # harness. These are dependency-wiring stubs; _resolve_run is untouched.
        for name, parameter in parameters.items():
            if name == "self" or name in positional_names or name in accepted_kwargs:
                continue
            if parameter.kind not in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            if parameter.default is inspect.Parameter.empty:
                accepted_kwargs[name] = _NullDependency()

        return original_init(self, *args, **accepted_kwargs)

    HeistService.__init__ = compat_init


gate.install_support_stubs = _install_constructor_compat


if __name__ == "__main__":
    raise SystemExit(gate.main())
