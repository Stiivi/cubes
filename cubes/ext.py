# -*- coding: utf-8 -*-
from .common import decamelize, to_identifier, coalesce_options
from .errors import *
from collections import defaultdict
from pkg_resources import iter_entry_points


__all__ = [
    "EXTENSION_TYPES",
    "ExtensionFinder",
]

# Known extension types.
# Keys:
#     base: extension base class name
#     suffix: extension class suffix to be removed for default name (same as
#         base class nameif not specified)
#     modules: a dictionary of extension names and module name to be loaded
#         laily


EXTENSION_TYPES = [
    "browser",
    "store",
    "provider",
    "formatter",
    "authorizer",
    "authenticators",
    "request_log_handlers",
]

# Information about built-in extensions. Supposedly faster loading (?).
#
_BUILTIN_EXTENSIONS = {
    "authenticators": {
        "admin_admin": "cubes.server.auth:AdminAdminAuthenticator",
        "pass_parameter": "cubes.server.auth:PassParameterAuthenticator",
        "http_basic_proxy": "cubes.server.auth:HTTPBasicProxyAuthenticator",
    },
    "authorizers": {
        "simple": "cubes.auth:SimpleAuthorizer",
    },
    "browsers": {
        "sql":"cubes.sql.browser:SQLBrowser",
        "slicer":"cubes.server.browser:SlicerBrowser",
    },
    "formatters": {
        "text_table": "cubes.formatters:TextTableFormatter",
        "simple_data_table": "cubes.formatters:SimpleDataTableFormatter",
        "text_data_table": "cubes.formatters:TextDataTableFormatter",
        "cross_data_table": "cubes.formatters:CrossTableFormatter",
        "html_cross_data_table": "cubes.formatters:HTMLCrossTableFormatter",
        "simple_html_table": "cubes.formatters:SimpleHtmlTableFormatter",
        "rickshaw_multi_series": "cubes.formatters:RickshawMultiSeriesFormatter",
    },
    "providers": {
        "default":"cubes.providers:StaticModelProvider",
        "slicer":"cubes.server.store:SlicerProvider",
    },
    "request_log_handlers": {
        "default":"cubes.server.logging:DefaultRequestLogger",
        "csv":"cubes.server.logging:CSVRequestLogger",
        "json":"cubes.server.logging:JSONRequestLogger",
        "sql":"cubes.sql.logging:SQLRequestLogger",
    },
    "stores": {
        "sql":"cubes.sql.store:SQLStore",
        "slicer":"cubes.server.store:SlicerStore",
    },
}

_DEFAULT_OPTIONS = {
}

class _Extension(object):
    """
    Cubes Extension wrapper.

    `options` – List of extension options.  The options is a list of
    dictionaries with keys:

    * `name` – option name
    * `type` – option data type (default is ``string``)
    * `description` – description (optional)
    * `label` – human readable label (optional)
    * `values` – valid values for the option.
    """
    def __init__(self, type_, entry=None, name=None):
        self.type_ = type_
        self.entry = entry
        self.name = name or entry.name

        # After loading...
        self.options = []
        self.option_types = {}
        self.factory = None

    def load(self):
        self.set_factory(self.entry.load())

    def set_factory(self, factory):
        self.factory = factory
        defaults = _DEFAULT_OPTIONS.get(self.type_, [])

        if hasattr(self.factory, "__options__"):
            options = self.factory.__options__ or []
        else:
            options = []

        self.options = {}
        for option in defaults + options:
            name = option["name"]
            self.options[name] = option
            self.option_types[name] = option.get("type", "string")

        self.option_types = self.option_types or {}

    def create(self, *args, **kwargs):
        """Creates an extension. First argument should be extension's name."""
        if not self.factory:
            self.load()

        kwargs = coalesce_options(dict(kwargs),
                                  self.option_types)

        return self.factory(*args, **kwargs)


class ExtensionFinder(object):
    def __init__(self, type_):
        self.type_ = type_
        self.group = "cubes.{}".format(type_)
        self.extensions = {}

        self.builtins = _BUILTIN_EXTENSIONS.get(self.type_, {})

    def discover(self, name=None):
        """Find all entry points."""
        for obj in iter_entry_points(group=self.group, name=name):
            ext = _Extension(self.type_, obj)
            self.extensions[ext.name] = ext

        return ext

    def builtin(self, name):
        try:
            ext_mod = self.builtins[name]
        except KeyError:
            return None

        (modname, attr) = ext_mod.split(":")
        module = _load_module(modname)
        ext = _Extension(self.type_, name=name)
        ext.set_factory(getattr(module, attr))
        self.extensions[name] = ext

        return ext

    def _get(self, name):
        """Return extenson object by name. Load if necessary."""
        ext = self.extensions.get(name)

        if not ext:
            ext = self.builtin(name)

        if not ext:
            import pdb; pdb.set_trace()
            raise Exception("nono")
            self.discover()
            try:
                ext = self.extensions[name]
            except KeyError:
                raise InternalError("Unknown '{}' extension '{}'"
                                    .format(self.type_, name))
        return ext

    def __call__(self, _ext_name, *args, **kwargs):
        return self.create(_ext_name, *args, **kwargs)

    def factory(self, name):
        """Return extension factory."""
        ext = self._get(name)
        return ext.factory

    def create(self, _ext_name, *args, **kwargs):
        """Create an instance of extension `_ext_name` with given arguments.
        The keyword arguments are converted to their appropriate types
        according to extensions `__options__` list. This allows options to be
        specified as strings in a configuration files or configuration
        variables."""
        ext = self._get(_ext_name)
        return ext.create(*args, **kwargs)


def _load_module(modulepath):
    """Load module `modulepath` and return the last module object in the
    module path."""

    mod = __import__(modulepath)
    path = []
    for token in modulepath.split(".")[1:]:
       path.append(token)
       mod = getattr(mod, token)
    return mod


authenticator = ExtensionFinder("authenticators")
authorizer = ExtensionFinder("authorizers")
browser = ExtensionFinder("browsers")
formatter = ExtensionFinder("formatters")
model_provider = ExtensionFinder("providers")
request_log_handler = ExtensionFinder("request_log_handlers")
store = ExtensionFinder("stores")
