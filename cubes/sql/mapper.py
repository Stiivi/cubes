# -*- encoding: utf-8 -*-
"""Logical to Physical Mappers"""

import re

from typing import (
        Collection,
        Dict,
        List,
        Mapping,
        Optional,
        Pattern,
        Tuple,
        Type,
        TypeVar,
        Union,
    )

from collections import defaultdict

from ..types import JSONType

from ..errors import ModelError
from ..datastructures import AttributeDict

from ..metadata.physical import ColumnReference

from ..metadata.cube import Cube
from ..metadata.attributes import AttributeBase
from ..metadata.dimension import Dimension

from ..settings import Setting, SettingType

# Note about the future of this module:
#
# Mapper should map the whole schema – mutliple facts and multiple dimensions.
# It should be decoupled from the cube and probably associated with the store
# (or store associated with the mapping)
#

__all__ = (
    "distill_naming",
    "DEFAULT_KEY_FIELD",

    "Mapper",
    "StarSchemaMapper",
    "DenormalizedMapper",
    "map_base_attributes",
)


DEFAULT_KEY_FIELD = "id"

DEFAULT_FACT_KEY = 'id'
DEFAULT_DIMENSION_KEY = 'id'

# Note: Only keys in this dictionary are allowed in the `naming` dictionary.
# All other keys are ignored.

NAMING_DEFAULTS = {
    "fact_prefix": None,
    "fact_suffix": None,
    "dimension_prefix": None,
    "dimension_suffix": None,
    "dimension_key_prefix": None,
    "dimension_key_suffix": None,

    "denormalized_prefix": None,
    "denormalized_suffix": None,

    "aggregated_prefix": None,
    "aggregated_suffix": None,

    "fact_key": DEFAULT_FACT_KEY,
    "dimension_key": DEFAULT_DIMENSION_KEY,
    "explicit_dimension_primary": False,

    "schema": None,
    "fact_schema": None,
    "dimension_schema": None,
    "aggregate_schema": None,
}


# TODO: [typing] Make this aligned with some common value type shared with
# settings.
NamingDict = Dict[str, Union[str, bool, None]]

# TODO: [typing][2.0] analyse whether this is still needed, looks lie Store is
# using it
def distill_naming(dictionary: Dict[str,str]) -> NamingDict:
    """Distill only keys and values related to the naming conventions."""
    d = {key: value for key, value in dictionary.items()
         if key in NAMING_DEFAULTS}

    return d


def _match_names(pattern: Pattern, names: Collection[str]) \
        -> Collection[Tuple[str,str]]:
    """Match names to patterns and return a tuple of matching name with
    extracted value (stripped of suffix/prefix)."""

    result: List[Tuple[str,str]] = []

    for name in names:
        match = pattern.match(name)
        if match:
            result.append((name, match.group("name")))

    return result

T = TypeVar("T", Optional[str], Optional[bool])

def _naming_default(naming: NamingDict, key: str) -> T:
    return naming.get(key, NAMING_DEFAULTS.get(key))


class _ObsoleteNaming:
    """Naming conventions for SQL tables. Naming properties can be accessed as
    a dictionary keys or as direct attributes. The naming properties are:

    * `fact_prefix` – prefix for fact tables
    * `fact_suffix` – suffix for fact tables
    * `dimension_prefix` – prefix for dimension tables
    * `dimension_suffix` – suffix for dimension tables
    * `dimension_key_prefix` – prefix for dimension foreign keys
    * `dimension_key_suffix` – suffix for dimension foreign keys
    * `fact_key` – name of fact table primary key (defaults to ``id`` if not
      specified)
    * `dimension_key` – name of dimension table primary key (defaults to
      ``id`` if not specified)
    * `explicit_dimension_primary` – whether the primary key of dimension
      table contains dimension name explicitly.

    If the `explicit_dimension_primary` is `True`, then all dimension tables
    are expected to have the primary key in the same format as foreign
    dimension keys. For example if the foreign dimension keys are
    ``customer_key`` then primary key of customer dimension table is also
    ``customer_key`` as oposed to just ``key``. The `dimension_key` naming
    property is ignored.


    Additional information that can be used by the mapper:

    * `schema` – default schema
    * `fact_schema` – schema where all fact tables are stored
    * `dimension_schema` – schema where dimension tables are stored

    Recommended values: `fact_prefix` = ``ft_``, `dimension_prefix` =
    ``dm_``, `explicit_dimension_primary` = ``True``.
    """

    fact_key: Optional[str]
    dimension_key: Optional[str]
    explicit_dimension_primary: bool
    schema: Optional[str]
    fact_schema: Optional[str]
    dimension_schema: Optional[str]

    dim_name_pattern: Pattern
    fact_name_pattern: Pattern
    dim_key_pattern: Pattern

    def __init__(self, naming: NamingDict) -> None:
        """Creates a `Naming` object instance from a dictionary. If `fact_key`
        or `dimension_key` are not specified, then they are set to ``id`` by
        default."""

        def get_default(key: str) -> Union[str, bool, None]:
            return NAMING_DEFAULTS.get(key)

        self.fact_key = _naming_default(naming, "fact_key")
        self.dimension_key = _naming_default(naming, "dimension_key")
        self.explicit_dimension_primary = _naming_default(naming, "explicit_dimension_primary")


    def denormalized_table_name(self, name: str) -> str:
        """Constructs a physical fact table name for fact/cube `name`"""

        table_name = "{}{}{}".format(self.denormalized_prefix or "",
                                     name,
                                     self.denormalized_suffix or "")
        return table_name

    def dimension_primary_key(self, name:str ) -> str:
        """Constructs a dimension primary key name for dimension `name`"""

        if self.explicit_dimension_primary:
            key = "{}{}{}".format(self.dimension_key_prefix or "",
                                  name,
                                  self.dimension_key_suffix or "")
            return key
        else:
            return self.dimension_key

    def dimension_keys(self, keys: List[str]) -> Collection[Tuple[str, str]]:
        """Return a list of tuples (`key`, `dimension`) for every key in
        `keys` that matches dimension key naming. Useful when trying to
        identify dimensions and their foreign keys in a fact table that
        follows the naming convetion."""

        return _match_names(self.dim_key_pattern, keys)

    def dimensions(self, table_names: List[str]) -> Collection[Tuple[str, str]]:
        """Return a list of tuples (`table`, `dimension`) for all tables that
        match dimension naming scheme. Usefult when trying to identify
        dimension tables in a database that follow the naming convention."""

        return _match_names(self.dim_name_pattern, table_names)

    def facts(self, table_names: List[str]) -> Collection[Tuple[str, str]]:
        """Return a list of tuples (`table`, `fact`) for all tables that
        match fact table naming scheme. Useful when trying to identify fact
        tables in a database that follow the naming convention."""

        return _match_names(self.fact_name_pattern, table_names)


class Mapper:
    """A dictionary-like object that provides physical column references for
    cube attributes. Does implicit mapping of an attribute.

    .. versionchanged:: 1.1
    """

    locale: Optional[str]
    mappings: JSONType
    fact_name: str

    # From Naming:
    fact_prefix: Optional[str]
    fact_suffix: Optional[str]
    dimension_prefix: Optional[str]
    dimension_suffix: Optional[str]
    aggregated_prefix: Optional[str]
    aggregated_suffix: Optional[str]

    dimension_key_prefix: Optional[str]
    dimension_key_suffix: Optional[str]

    schema: Optional[str]
    aggergate_schema: Optional[str]
    fact_schema: Optional[str]
    dimension_schema: Optional[str]

    dim_name_pattern: Pattern
    fact_name_pattern: Pattern
    dim_key_pattern: Pattern


    def __init__(self, cube: Cube, naming: NamingDict,
            locale: str=None) -> None:
        """Creates a mapping for `cube` using `naming` conventions within
        optional `locale`. `naming` is a dictionary of naming conventions.  """

        self.locale = locale
        self.mappings = cube.mappings or {}

        self.dimension_prefix = _naming_default(naming, "dimension_prefix")
        self.dimension_suffix = _naming_default(naming, "dimension_suffix")

        self.fact_prefix = _naming_default(naming, "fact_prefix")
        self.fact_suffix = _naming_default(naming, "fact_suffix")

        self.aggregated_prefix = _naming_default(naming, "aggregated_prefix")
        self.aggregated_suffix = _naming_default(naming, "aggregated_suffix")

        # TODO: Is this still used?
        self.dimension_key_prefix = _naming_default(naming, "dimension_key_prefix")
        self.dimension_key_suffix = _naming_default(naming, "dimension_key_suffix")

        self.schema = _naming_default(naming, "schema")
        self.fact_schema = _naming_default(naming, "fact_schema")
        self.dimension_schema = _naming_default(naming, "dimension_schema")
        self.aggregate_schema = _naming_default(naming, "aggregate_schema")

        self.dim_name_pattern = re.compile("^{}(?P<name>.*){}$"
                                      .format(self.dimension_prefix or "",
                                              self.dimension_suffix or ""))

        self.fact_name_pattern = re.compile("^{}(?P<name>.*){}$"
                                       .format(self.fact_prefix or "",
                                       self.fact_suffix or ""))

        self.dim_key_pattern = re.compile("^{}(?P<name>.*){}$"
                                     .format(self.dimension_key_prefix or "",
                                             self.dimension_key_suffix or ""))

        self.fact_name = cube.fact or self.fact_table_name(cube.name)

    def dimension_table_name(self, name: str) -> str:
        """Constructs a physical dimension table name for dimension `name`"""

        table_name = "{}{}{}".format(self.dimension_prefix or "",
                                     name,
                                     self.dimension_suffix or "")
        return table_name

    def fact_table_name(self, name: str) -> str:
        """Constructs a physical fact table name for fact/cube `name`"""

        table_name = "{}{}{}".format(self.fact_prefix or "",
                                     name,
                                     self.fact_suffix or "")
        return table_name

    # TODO: require list of dimensions here
    def aggregated_table_name(self, name: str) -> str:
        """Constructs a physical fact table name for fact/cube `name`"""

        table_name = "{}{}{}".format(self.aggregated_prefix or "",
                                     name,
                                     self.aggregated_suffix or "")
        return table_name



    def __getitem__(self, attribute: AttributeBase) -> ColumnReference:
        """Returns implicit physical column reference for `attribute`, which
        should be an instance of :class:`cubes.model.Attribute`. If there is
        no dimension specified in attribute, then fact table is assumed. The
        returned reference has attributes `schema`, `table`, `column`,
        `extract`.  """

        column_name = attribute.name

        if attribute.is_localizable():
            locale = self.locale if self.locale in attribute.locales \
                                else attribute.locales[0]

            column_name = "{}_{}".format(column_name, locale)

        schema, table = self.attribute_table(attribute)

        return ColumnReference(column=column_name, table=table, schema=schema)

    def attribute_table(self, attribute: AttributeBase) -> Tuple[Optional[str], str]:
        """Return a tuple (schema, table) for attribute."""

        # TODO: Attribute.dimension is a candidate for removal.
        dimension: Optional[Dimension]
        dimension = attribute.dimension

        if dimension is not None:
            schema: Optional[str]
            schema = self.dimension_schema or self.schema
            if dimension.is_flat and not dimension.has_details:
                table = self.fact_name
            else:
                table = self.dimension_table_name(dimension.name)

        else:
            table = self.fact_name
            schema = self.schema

        return (schema, table)


class DenormalizedMapper(Mapper):
    def __getitem__(self, attribute: AttributeBase) -> ColumnReference:
        if attribute.expression is not None:
            raise ModelError("Attribute '{}' has an expression, it can not "
                             "have a direct physical representation"
                             .format(attribute.name))

        return super().__getitem__(attribute)


class StarSchemaMapper(Mapper):
    def __getitem__(self, attribute: AttributeBase) -> ColumnReference:
        """Find physical reference for a star schema as follows:

        1. if there is mapping for `dimension.attribute`, use the mapping
        2. if there is no mapping or no mapping was found, then use table
        `dimension` or fact table, if attribute does not belong to a
        dimension and column `attribute`

        If table prefixes and suffixes are used, then they are
        prepended/appended to the table tame in the implicit mapping.

        If localization is requested and the attribute is localizable, then
        suffix in the form `_LOCALE` where `LOCALE` is the locale name will be
        added to search for mapping or for implicit attribute creation such as
        `name_sk` for attribute `name` and locale `sk`.
        """

        if attribute.expression is not None:
            raise ModelError("Attribute '{}' has an expression, it can not "
                             "have a direct physical representation"
                             .format(attribute.name))

        # Fix locale: if attribute is not localized, use none, if it is
        # localized, then use specified if exists otherwise use default
        # locale of the attribute (first one specified in the list)

        locale: Optional[str]
        if attribute.is_localizable():
            locale = self.locale if self.locale in attribute.locales \
                                else attribute.locales[0]
        else:
            locale = None

        logical = attribute.localized_ref(locale)

        physical = self.mappings.get(logical)

        if physical is not None:
            # TODO: Should we not get defaults here somehow?
            return ColumnReference.from_dict(physical)
        else:
            # No mappings exist or no mapping was found - we are going to
            # create default physical reference
            return super(StarSchemaMapper, self).__getitem__(attribute)


def map_base_attributes(
        cube: Cube,
        mapper_class: Type[Mapper],
        naming: NamingDict,
        locale: Optional[str]=None) -> Tuple[str, Mapping[str, ColumnReference]]:
    """Map all base attributes of `cube` using mapping function `mapper`.
    `naming` is a naming convention object. Returns a tuple (`fact_name`,
    `mapping`) where `fact_name` is a fact table name and `mapping` is a
    dictionary of attribute references and their physical column
    references."""

    base = [attr for attr in cube.all_attributes if attr.is_base]

    mapper: Mapper
    mapper = mapper_class(cube=cube, naming=naming, locale=locale)
    mapped = {attr.ref:mapper[attr] for attr in base}

    return (mapper.fact_name, mapped)

