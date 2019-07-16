# -*- encoding: utf-8 -*-

import copy
import re
from collections import OrderedDict
from typing import Any, Collection, Dict, List, Optional, Set, Sized, Tuple, Union, cast

from ..common import get_localizable_attributes
from ..errors import (
    ArgumentError,
    HierarchyError,
    ModelError,
    ModelInconsistencyError,
    NoSuchAttributeError,
    TemplateRequired,
)
from ..types import JSONType
from .attributes import Attribute, expand_attribute_metadata
from .base import ModelObject, object_dict

__all__ = [
    "Dimension",
    "Hierarchy",
    "Level",
    "HierarchyPath",
    "string_to_dimension_level",
]


# FIXME: See #354
_DEFAULT_LEVEL_ROLES = {
    "time": [
        "year",
        "quarter",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "week",
        "weeknum",
        "dow",
        "isoyear",
        "isoweek",
        "isoweekday",
    ]
}

HierarchyPath = List[str]


class Level(ModelObject):
    """Object representing a hierarchy level. Holds all level attributes.

    This object is immutable, except localization. You have to set up all
    attributes in the initialisation process.

    Attributes:

    * `name`: level name
    * `attributes`: list of all level attributes. Raises `ModelError` when
      `attribute` list is empty.
    * `key`: name of level key attribute (for example: ``customer_number`` for
      customer level, ``region_code`` for region level, ``month`` for month
      level).  key will be used as a grouping field for aggregations. Key
      should be unique within level. If not specified, then the first
      attribute is used as key.
    * `order`: ordering of the level. `asc` for ascending, `desc` for
      descending or might be unspecified.
    * `order_attribute`: name of attribute that is going to be used for
      sorting, default is first attribute (usually key)
    * `label_attribute`: name of attribute containing label to be displayed
      (for example: ``customer_name`` for customer level, ``region_name`` for
      region level, ``month_name`` for month level)
    * `label`: human readable label of the level
    * `role`: role of the level within a special dimension
    * `info`: custom information dictionary, might be used to store
      application/front-end specific information
    * `cardinality` – approximation of the number of level's members. Used
      optionally by backends and front ends.
    * `nonadditive` – kind of non-additivity of the level. Possible
      values: `None` (fully additive, default), ``time`` (non-additive for
      time dimensions) or ``all`` (non-additive for any other dimension)

    Cardinality values:

    * ``tiny`` – few values, each value can have it's representation on the
      screen, recommended: up to 5.
    * ``low`` – can be used in a list UI element, recommended 5 to 50 (if sorted)
    * ``medium`` – UI element is a search/text field, recommended for more than 50
      elements
    * ``high`` – backends might refuse to yield results without explicit
      pagination or cut through this level.

    Note: the `attributes` are going to be owned by the `dimension`.
    """

    localizable_attributes = ["label", "description"]
    localizable_lists = ["attributes"]

    def __init__(
        self,
        name: str,
        attributes: List[Attribute],
        key: Optional[str] = None,
        order_attribute: Optional[str] = None,
        order: Optional[str] = None,
        label_attribute: Optional[str] = None,
        label: Optional[str] = None,
        info: Optional[JSONType] = None,
        cardinality: Optional[str] = None,
        role: Optional[str] = None,
        nonadditive: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:

        super().__init__(name, label, description, info)

        self.cardinality = cardinality
        self.role = role

        if not attributes:
            raise ModelError("Attribute list should not be empty")

        self.attributes = attributes

        # Note: synchronize with Measure.__init__ if relevant/necessary
        if not nonadditive or nonadditive == "none":
            self.nonadditive = None
        elif nonadditive in ["all", "any"]:
            self.nonadditive = "all"
        elif nonadditive != "time":
            raise ModelError("Unknown non-additive diension type '%s'" % nonadditive)
        self.nonadditive = nonadditive

        if key:
            self.key = self.attribute(key)
        elif len(self.attributes) >= 1:
            self.key = self.attributes[0]
        else:
            raise ModelInconsistencyError("Attribute list should not be empty")

        # Set second attribute to be label attribute if label attribute is not
        # set. If dimension is flat (only one attribute), then use the only
        # key attribute as label.

        if label_attribute:
            self.label_attribute = self.attribute(label_attribute)
        else:
            if len(self.attributes) > 1:
                self.label_attribute = self.attributes[1]
            else:
                self.label_attribute = self.key

        # Set first attribute to be order attribute if order attribute is not
        # set

        if order_attribute:
            try:
                self.order_attribute = self.attribute(order_attribute)
            except NoSuchAttributeError:
                raise NoSuchAttributeError(
                    "Unknown order attribute {} in "
                    "level {}".format(order_attribute, self.name)
                )
        else:
            self.order_attribute = self.attributes[0]

        self.order = order

        self.cardinality = cardinality

    @classmethod
    def from_metadata(
        cls, metadata: JSONType, name: str = None, dimension: "Dimension" = None
    ) -> "Level":
        """Create a level object from metadata.

        `name` can override level name in the metadata.
        """

        level_name: str

        metadata = dict(expand_level_metadata(metadata))

        if name is None and "name" not in metadata:
            raise ModelError("No name specified in level metadata")
        else:
            level_name = name or metadata["name"]

        attributes = []
        for attr_metadata in metadata.pop("attributes", []):
            attr = Attribute(dimension=dimension, **attr_metadata)
            attributes.append(attr)

        return cls(
            name=level_name,
            attributes=attributes,
            key=metadata.get("key"),
            order_attribute=metadata.get("order_attribute"),
            order=metadata.get("order"),
            label_attribute=metadata.get("label_attribute"),
            label=metadata.get("label"),
            info=metadata.get("info"),
            cardinality=metadata.get("cardinality"),
            role=metadata.get("role"),
            nonadditive=metadata.get("nonadditive"),
            description=metadata.get("description"),
        )

    def __eq__(self, other: Any) -> bool:
        if not other or type(other) != type(self):
            return False
        elif (
            self.name != other.name
            or self.label != other.label
            or self.key != other.key
            or self.cardinality != other.cardinality
            or self.role != other.role
            or self.label_attribute != other.label_attribute
            or self.order_attribute != other.order_attribute
            or self.nonadditive != other.nonadditive
            or self.attributes != other.attributes
        ):
            return False

        return True

    def __hash__(self) -> int:
        return hash(self.name)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return str(self.to_dict())

    def __deepcopy__(self, memo: Any) -> "Level":
        order_attribute: Optional[str]

        if self.order_attribute:
            order_attribute = self.order_attribute.name
        else:
            order_attribute = None

        return Level(
            self.name,
            attributes=copy.deepcopy(self.attributes, memo),
            key=self.key.name,
            order_attribute=order_attribute,
            order=self.order,
            label_attribute=self.label_attribute.name,
            info=copy.copy(self.info),
            label=copy.copy(self.label),
            cardinality=self.cardinality,
            nonadditive=self.nonadditive,
            role=self.role,
        )

    def to_dict(self, **options: Any) -> JSONType:
        """Convert to dictionary."""

        full_attribute_names = cast(bool, options.get("full_attribute_names"))

        out = super().to_dict(**options)

        out["role"] = self.role

        if full_attribute_names:
            out["key"] = self.key.ref
            out["label_attribute"] = self.label_attribute.ref
            out["order_attribute"] = self.order_attribute.ref
        else:
            out["key"] = self.key.name
            out["label_attribute"] = self.label_attribute.name
            out["order_attribute"] = self.order_attribute.name

        out["order"] = self.order
        out["cardinality"] = self.cardinality
        out["nonadditive"] = self.nonadditive

        out["attributes"] = [attr.to_dict(**options) for attr in self.attributes]
        return out

    def attribute(self, name: str) -> Attribute:
        """Get attribute by `name`"""

        attrs = [attr for attr in self.attributes if attr.name == name]

        if attrs:
            return attrs[0]
        else:
            raise NoSuchAttributeError(name)

    @property
    def has_details(self) -> bool:
        """Is ``True`` when level has more than one attribute, for all levels
        with only one attribute it is ``False``."""

        return len(self.attributes) > 1

    def localizable_dictionary(self) -> JSONType:
        locale: JSONType = {}
        locale.update(get_localizable_attributes(self))

        adict: JSONType = {}
        locale["attributes"] = adict

        for attribute in self.attributes:
            adict[attribute.name] = attribute.localizable_dictionary()

        return locale


def string_to_dimension_level(astring: str) -> Tuple[str, str, str]:
    """Converts `astring` into a dimension level tuple (`dimension`,
    `hierarchy`, `level`). The string should have a format:
    ``dimension@hierarchy:level``. Hierarchy and level are optional.

    Raises `ArgumentError` when `astring` does not match expected
    pattern.
    """

    if not astring:
        raise ArgumentError("Drilldown string should not be empty")

    ident = r"[\w\d_]"
    pattern = r"(?P<dim>{}+)(@(?P<hier>{}+))?(:(?P<level>{}+))?".format(
        ident, ident, ident
    )
    match = re.match(pattern, astring)

    if match:
        d = match.groupdict()
        return (d["dim"], d["hier"], d["level"])
    else:
        raise ArgumentError(
            "String '%s' does not match drilldown level "
            "pattern 'dimension@hierarchy:level'" % astring
        )


class Hierarchy(ModelObject, Sized):

    localizable_attributes = ["label", "description"]

    levels: List[Level]
    _levels: Dict[str, Level]

    def __init__(
        self,
        name: str,
        levels: List[Level],
        label: Optional[str] = None,
        info: Optional[JSONType] = None,
        description: Optional[str] = None,
    ) -> None:
        """Dimension hierarchy - specifies order of dimension levels.

        Attributes:

        * `name`: hierarchy name
        * `levels`: ordered list of levels or level names from `dimension`

        * `label`: human readable name
        * `description`: user description of the hierarchy
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information

        Note: The `levels` should have attributes already owned by a
        dimension.
        """

        super().__init__(name, label, description, info)

        if not levels:
            raise ModelInconsistencyError(
                "Hierarchy level list should not be empty (in %s)" % self.name
            )

        if any(isinstance(level, str) for level in levels):
            raise ModelInconsistencyError(
                "Levels should not be provided as strings to Hierarchy."
            )

        self._levels = object_dict(levels)

    def __deepcopy__(self, memo: Any) -> "Hierarchy":
        return Hierarchy(
            self.name,
            label=self.label,
            description=self.description,
            info=copy.deepcopy(self.info, memo),
            levels=copy.deepcopy(self.levels, memo),
        )

    @property
    def levels(self) -> List[Level]:
        return list(self._levels.values())

    # FIXME: Remove setter
    @levels.setter
    def levels(self, levels: List[Level]) -> None:
        self._levels.clear()
        for level in levels:
            self._levels[level.name] = level

    @property
    def level_names(self) -> List[str]:
        return list(self._levels)

    def keys(self, depth: Optional[int] = None) -> List[Attribute]:
        """Return names of keys for all levels in the hierarchy to `depth`.

        If `depth` is `None` then all levels are returned.
        """
        levels: Collection[Level]

        if depth is not None:
            levels = self.levels[0:depth]
        else:
            levels = self.levels

        return [level.key for level in levels]

    def __eq__(self, other: Any) -> bool:
        if not other or type(other) != type(self):
            return False

        return (
            self.name == other.name
            and self.label == other.label
            and self.levels == other.levels
        )

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.name)

    def __str__(self) -> str:
        return self.name

    def __len__(self) -> int:
        return len(self.levels)

    def __getitem__(self, item: str) -> Level:
        try:
            return self._levels[item]
        except IndexError:
            raise HierarchyError(
                "Hierarchy '%s' has only %d levels, "
                "asking for deeper level" % (self.name, len(self._levels))
            )

    def __contains__(self, item: Level) -> bool:
        if item in self.levels:
            return True
        return item in [level.name for level in self.levels]

    def levels_for_depth(self, depth: int, drilldown: bool = False) -> List[Level]:
        """Returns levels for given `depth`.

        If `path` is longer than hierarchy levels, `cubes.ArgumentError`
        exception is raised
        """

        extend = 1 if drilldown else 0

        if depth + extend > len(self.levels):
            raise HierarchyError(
                "Depth %d is longer than hierarchy "
                "levels %s (drilldown: %s)" % (depth, self._levels, drilldown)
            )

        return self.levels[0 : depth + extend]

    def next_level(self, level: Optional[Level]) -> Optional[Level]:
        """Returns next level in hierarchy after `level`.

        If `level` is last level, returns ``None``. If `level` is
        ``None``, then the first level is returned.
        """

        if not level:
            return self.levels[0]

        index = list(self._levels).index(str(level))
        if index + 1 >= len(self.levels):
            return None
        else:
            return self.levels[index + 1]

    def previous_level(self, level: Optional[Level]) -> Optional[Level]:
        """Returns previous level in hierarchy after `level`.

        If `level` is first level or ``None``, returns ``None``
        """

        if level is None:
            return None

        index = list(self._levels).index(str(level))
        if index == 0:
            return None
        else:
            return self.levels[index - 1]

    def level_index(self, name: str) -> int:
        """Get order index of level `name`.

        Can be used for ordering and comparing levels within hierarchy.
        """
        try:
            return list(self._levels).index(name)
        except ValueError:
            raise HierarchyError(
                f"Level {name} is not part of hierarchy " f"{self.name}"
            )

    def is_last(self, level: Level) -> bool:
        """Returns `True` if `level` is last level of the hierarchy."""

        return level == self.levels[-1]

    def rollup(self, path: HierarchyPath, level: Optional[Level] = None) -> List[str]:
        """Rolls-up the path to the `level`. If `level` is ``None`` then path
        is rolled-up only one level.

        If `level` is deeper than last level of `path` the
        `cubes.HierarchyError` exception is raised. If `level` is the
        same as `path` level, nothing happens.
        """

        last: Optional[int]

        if level is not None:
            last = self.level_index(level.name) + 1
            if last > len(path):
                raise HierarchyError(
                    "Can not roll-up: level '%s' – it is "
                    "deeper than deepest element of path %s" % (str(level), path)
                )
        else:
            if len(path) > 0:
                last = len(path) - 1
            else:
                last = None

        if last is None:
            return []
        else:
            return path[0:last]

    def path_is_base(self, path: HierarchyPath) -> bool:
        """Returns True if path is base path for the hierarchy. Base path is a.

        path where there are no more levels to be added - no drill down
        possible.
        """

        return path is not None and len(path) == len(self.levels)

    def key_attributes(self) -> List[Attribute]:
        """Return all dimension key attributes as a single list."""

        return [level.key for level in self.levels]

    @property
    def all_attributes(self) -> List[Attribute]:
        """Return all dimension attributes as a single list."""

        attributes: List[Attribute] = []
        for level in self.levels:
            attributes.extend(level.attributes)

        return attributes

    def to_dict(self, **options: Any) -> JSONType:
        """Convert to dictionary. Keys:

        * `name`: hierarchy name
        * `label`: human readable label (localizable)
        * `levels`: level names
        """
        depth = cast(int, options.get("depth"))

        out = super().to_dict(**options)

        levels = [str(l) for l in self.levels]

        if depth:
            out["levels"] = levels[0:depth]
        else:
            out["levels"] = levels
        out["info"] = self.info

        return out

    def localizable_dictionary(self) -> JSONType:
        locale = {}
        locale.update(get_localizable_attributes(self))

        return locale


def expand_dimension_metadata(
    metadata: JSONType, expand_levels: bool = False
) -> JSONType:
    """Expands `metadata` to be as complete as possible dimension metadata.

    If `expand_levels` is `True` then levels metadata are expanded as
    well.
    """

    if isinstance(metadata, str):
        metadata = {"name": metadata, "levels": [metadata]}
    else:
        metadata = dict(metadata)

    if not "name" in metadata:
        raise ModelError("Dimension has no name")

    name = metadata["name"]

    # Fix levels
    levels = metadata.get("levels", [])
    if not levels and expand_levels:
        attributes = [
            "attributes",
            "key",
            "order_attribute",
            "order",
            "label_attribute",
        ]
        level = {}
        for attr in attributes:
            if attr in metadata:
                level[attr] = metadata[attr]

        level["cardinality"] = metadata.get("cardinality")

        # Default: if no attributes, then there is single flat attribute
        # whith same name as the dimension
        level["name"] = name
        level["label"] = metadata.get("label")

        levels = [level]

    if levels:
        levels = [expand_level_metadata(level) for level in levels]
        metadata["levels"] = levels

    # Fix hierarchies
    if "hierarchy" in metadata and "hierarchies" in metadata:
        raise ModelInconsistencyError(
            "Both 'hierarchy' and 'hierarchies' specified. Use only one"
        )

    hierarchy = metadata.get("hierarchy")
    if hierarchy:
        hierarchies = [{"name": "default", "levels": hierarchy}]
    else:
        hierarchies = metadata.get("hierarchies")

    if hierarchies:
        metadata["hierarchies"] = hierarchies

    return metadata


def expand_hierarchy_metadata(metadata: JSONType) -> JSONType:
    """Returns a hierarchy metadata as a dictionary.

    Makes sure that required properties are present. Raises exception on
    missing values.
    """

    try:
        name = metadata["name"]
    except KeyError:
        raise ModelError("Hierarchy has no name")

    if not "levels" in metadata:
        raise ModelError("Hierarchy '%s' has no levels" % name)

    return metadata


def expand_level_metadata(metadata: JSONType) -> JSONType:
    """Returns a level description as a dictionary.

    If provided as string, then it is going to be used as level name and
    as its only attribute. If a dictionary is provided and has no
    attributes, then level will contain only attribute with the same
    name as the level name.
    """
    if isinstance(metadata, str):
        metadata = {"name": metadata, "attributes": [metadata]}
    else:
        metadata = dict(metadata)

    try:
        name = metadata["name"]
    except KeyError:
        raise ModelError("Level has no name")

    attributes = metadata.get("attributes")

    if not attributes:
        attribute = {"name": name, "label": metadata.get("label")}

        attributes = [attribute]

    # TODO: this should belong to attributes.py
    metadata["attributes"] = [expand_attribute_metadata(a) for a in attributes]

    # TODO: Backward compatibility – depreciate later
    if "cardinality" not in metadata:
        info = metadata.get("info", {})
        if "high_cardinality" in info:
            metadata["cardinality"] = "high"

    return metadata


class Dimension(ModelObject):
    """Cube dimension."""

    localizable_attributes = ["label", "description"]
    localizable_lists = ["levels", "hierarchies"]

    _attributes: Dict[str, Attribute]
    _attributes_by_ref: Dict[str, Attribute]
    _levels: Dict[str, Level]
    _hierarchies: Dict[str, Hierarchy]
    _default_hierarchy: Hierarchy

    default_hierarchy_name: str
    label: str
    description: Optional[str]
    info: JSONType
    role: Optional[str]
    cardinality: Optional[str]
    category: Optional[str]
    master: Optional["Dimension"]
    nonadditive: Optional[str]

    # TODO: new signature: __init__(self, name, *attributes, **kwargs):
    def __init__(
        self,
        name: str,
        levels: Optional[List[Level]] = None,
        hierarchies: Optional[List[Hierarchy]] = None,
        default_hierarchy_name: Optional[str] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        info: Optional[JSONType] = None,
        role: Optional[str] = None,
        cardinality: Optional[str] = None,
        category: Optional[str] = None,
        master: Optional["Dimension"] = None,
        nonadditive: Optional[str] = None,
        attributes: Optional[List[Attribute]] = None,
        **desc: Any,
    ) -> None:

        """Create a new dimension.

        Attributes:

        * `name`: dimension name
        * `levels`: list of dimension levels (see: :class:`cubes.Level`)
        * `hierarchies`: list of dimension hierarchies. If no hierarchies are
          specified, then default one is created from ordered list of `levels`.
        * `default_hierarchy_name`: name of a hierarchy that will be used when
          no hierarchy is explicitly specified
        * `label`: dimension name that will be displayed (human readable)
        * `description`: human readable dimension description
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information (icon, color, ...)
        * `role` – one of recognized special dimension types. Currently
          supported is only ``time``.
        * `cardinality` – cardinality of the dimension members. Used
          optionally by the backends for load protection and frontends for
          better auto-generated front-ends. See :class:`Level` for more
          information, as this attribute is inherited by the levels, if not
          specified explicitly in the level.
        * `category` – logical dimension group (user-oriented metadata)
        * `nonadditive` – kind of non-additivity of the dimension. Possible
          values: `None` (fully additive, default), ``time`` (non-additive for
          time dimensions) or ``all`` (non-additive for any other dimension)
        * `attributes` – attributes for dimension. Use either this or levels,
          not both.

        Dimension class is not meant to be mutable. All level attributes will
        have new dimension assigned.

        Note that the dimension will claim ownership of levels and their
        attributes. You should make sure that you pass a copy of levels if you
        are cloning another dimension.


        Note: The hierarchy will be owned by the dimension.
        """

        super().__init__(name, label, description, info)

        self.role = role
        self.cardinality = cardinality
        self.category = category

        # Master dimension – dimension that this one was derived from, for
        # example by limiting hierarchies
        # TODO: not yet documented
        # TODO: probably replace the limit using limits in-dimension instead
        # of replacement of instance variables with limited content (?)
        self.master = master

        # Note: synchronize with Measure.__init__ if relevant/necessary
        if not nonadditive or nonadditive == "none":
            self.nonadditive = None
        elif nonadditive in ["all", "any"]:
            self.nonadditive = "all"
        elif nonadditive != "time":
            raise ModelError("Unknown non-additive diension type '%s'" % nonadditive)

        self.nonadditive = nonadditive

        if not levels and not attributes:
            raise ModelError("No levels or attriutes specified for dimension %s" % name)
        elif levels and attributes:
            raise ModelError("Both levels and attributes specified")

        if attributes:
            # TODO: pass all level initialization arguments here
            level = Level(name, attributes=attributes)
            levels = [level]

        # Own the levels and their attributes
        self._levels = object_dict(levels or [])

        # FIXME: See #354
        default_roles: List[str]
        if self.role is not None:
            default_roles = _DEFAULT_LEVEL_ROLES.get(self.role, [])
        else:
            default_roles = []

        # Set default roles
        for level in self._levels.values():
            if default_roles and level.name in default_roles:
                level.role = level.name

        # Collect attributes
        self._attributes = OrderedDict()
        self._attributes_by_ref = OrderedDict()
        self._attributes = OrderedDict()
        for level in self.levels:
            for a in level.attributes:
                # Own the attribute
                if a.dimension is not None and a.dimension is not self:
                    raise ModelError(
                        "Dimension '%s' can not claim attribute "
                        "'%s' because it is owned by another "
                        "dimension '%s'." % (self.name, a.name, a.dimension.name)
                    )
                a.dimension = self
                self._attributes[a.name] = a
                self._attributes_by_ref[a.ref] = a

        # The hierarchies receive levels with already owned attributes
        if hierarchies:
            error_message = "Duplicate hierarchy '{key}' in cube '{cube}'"
            error_dict = {"cube": self.name}
            self._hierarchies = object_dict(
                hierarchies, error_message=error_message, error_dict=error_dict
            )
        else:
            default = Hierarchy("default", self.levels)
            self._hierarchies = object_dict([default])

        # Set default hierarchy specified by ``default_hierarchy_name``, if
        # the variable is not set then get a hierarchy with name *default* or
        # the first hierarchy in the hierarchy list.

        default_name = default_hierarchy_name or "default"
        hierarchy = self._hierarchies.get(
            default_name, list(self._hierarchies.values())[0]
        )

        self._default_hierarchy = hierarchy
        self.default_hierarchy_name = hierarchy.name

    @classmethod
    def from_metadata(
        cls, metadata: JSONType, templates: Dict[str, "Dimension"] = None
    ) -> "Dimension":
        """Create a dimension from a `metadata` dictionary.  Some rules:

        * ``levels`` might contain level names as strings – names of levels to
          inherit from the template
        * ``hierarchies`` might contain hierarchies as strings – names of
          hierarchies to inherit from the template
        * all levels that are not covered by hierarchies are not included in the
          final dimension
        """

        template: Optional[Dimension]
        default_hierarchy_name: Optional[str]
        label: Optional[str]
        levels: List[Level]
        hierarchies: List[Hierarchy]
        description: Optional[str]
        cardinality: Optional[str]
        role: Optional[str]
        category: Optional[str]
        info: JSONType
        nonadditive: Optional[str]

        templates = templates or {}

        if "template" in metadata:
            template_name = metadata["template"]
            try:
                template = templates[template_name]
            except KeyError:
                raise TemplateRequired(template_name)

            levels = [copy.deepcopy(level) for level in template.levels]

            # Create copy of template's hierarchies, but reference newly
            # created copies of level objects
            hierarchies = []
            level_dict = {level.name: level for level in levels}

            for hier in template._hierarchies.values():
                hier_levels = [level_dict[level.name] for level in hier.levels]
                hier_copy = Hierarchy(
                    hier.name,
                    hier_levels,
                    label=hier.label,
                    info=copy.deepcopy(hier.info),
                )
                hierarchies.append(hier_copy)

            default_hierarchy_name = template.default_hierarchy_name
            label = template.label
            description = template.description
            info = template.info
            cardinality = template.cardinality
            role = template.role
            category = template.category
            nonadditive = template.nonadditive
        else:
            template = None
            levels = []
            hierarchies = []
            default_hierarchy_name = None
            label = None
            description = None
            cardinality = None
            role = None
            category = None
            info = {}
            nonadditive = None

        # Fix the metadata, but don't create default level if the template
        # provides levels.
        metadata = expand_dimension_metadata(metadata, expand_levels=not bool(levels))

        name = metadata.get("name")

        label = metadata.get("label", label)
        description = metadata.get("description") or description
        info = metadata.get("info", info)
        role = metadata.get("role", role)
        category = metadata.get("category", category)
        nonadditive = metadata.get("nonadditive", nonadditive)

        # Backward compatibility with an experimental feature
        cardinality = metadata.get("cardinality", cardinality)

        # Backward compatibility with an experimental feature:
        if not cardinality:
            info = metadata.get("info", {})
            if "high_cardinality" in info:
                cardinality = "high"

        # Levels
        # ------

        # We are guaranteed to have "levels" key from expand_dimension_metadata()

        if "levels" in metadata:
            # Assure level inheritance
            levels = []
            for level_md in metadata["levels"]:
                if isinstance(level_md, str):
                    if not template:
                        raise ModelError(
                            "Can not specify just a level name "
                            "(%s) if there is no template for "
                            "dimension %s" % (level_md, name)
                        )
                    level = template.level(level_md)
                else:
                    level = Level.from_metadata(level_md)
                    # raise NotImplementedError("Merging of levels is not yet supported")

                # Update the level's info dictionary
                if template:
                    try:
                        templevel = template.level(level.name)
                    except KeyError:
                        pass
                    else:
                        new_info = copy.deepcopy(templevel.info)
                        new_info.update(level.info)
                        level.info = new_info

                levels.append(level)

        # Hierarchies
        # -----------
        if "hierarchies" in metadata:
            hierarchies = _create_hierarchies(metadata["hierarchies"], levels, template)
        else:
            # Keep only hierarchies which include existing levels
            level_names = {level.name for level in levels}
            keep = []
            for hier in hierarchies:
                if any(level.name not in level_names for level in hier.levels):
                    continue
                else:
                    keep.append(hier)
            hierarchies = keep

        default_hierarchy_name = metadata.get(
            "default_hierarchy_name", default_hierarchy_name
        )

        if not hierarchies:
            # Create single default hierarchy
            hierarchies = [Hierarchy("default", levels=levels)]

        # Recollect levels – keep only those levels that are present in
        # hierarchies. Retain the original level order
        used_level_names: Set[str] = set()
        for hier in hierarchies:
            used_level_names |= {level.name for level in hier.levels}

        levels = [level for level in levels if level.name in used_level_names]

        return cls(
            name=name,
            levels=levels,
            hierarchies=hierarchies,
            default_hierarchy_name=default_hierarchy_name,
            label=label,
            description=description,
            info=info,
            cardinality=cardinality,
            role=role,
            category=category,
            nonadditive=nonadditive,
        )

    def __eq__(self, other: Any) -> bool:
        if other is None or type(other) != type(self):
            return False

        cond = (
            self.name == other.name
            and self.role == other.role
            and self.label == other.label
            and self.description == other.description
            and self.cardinality == other.cardinality
            and self.category == other.category
            and self.default_hierarchy_name == other.default_hierarchy_name
            and self._levels == other._levels
            and self._hierarchies == other._hierarchies
        )

        return cond

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    @property
    def has_details(self) -> bool:
        """Returns ``True`` when each level has only one attribute, usually
        key."""

        if self.master:
            return self.master.has_details

        return any([level.has_details for level in self._levels.values()])

    @property
    def levels(self) -> List[Level]:
        """Get list of all dimension levels.

        Order is not guaranteed, use a hierarchy to have known order.
        """
        return list(self._levels.values())

    @levels.setter
    def levels(self, levels: List[Level]) -> None:
        self._levels.clear()
        for level in levels:
            self._levels[level.name] = level

    @property
    def hierarchies(self) -> List[Hierarchy]:
        """Get list of dimension hierarchies."""
        return list(self._hierarchies.values())

    @hierarchies.setter
    def hierarchies(self, hierarchies: List[Hierarchy]) -> None:
        self._hierarchies.clear()
        for hier in hierarchies:
            self._hierarchies[hier.name] = hier

    @property
    def level_names(self) -> List[str]:
        """Get list of level names.

        Order is not guaranteed, use a hierarchy to have known order.
        """
        return list(self._levels.keys())

    def level(self, obj: Union[Level, str]) -> Level:
        """Get level by name or as Level object.

        This method is used for coalescing value
        """
        if isinstance(obj, str):
            if obj not in self._levels:
                raise KeyError(f"No level {obj} in dimension {self.name}")
            return self._levels[obj]
        elif isinstance(obj, Level):
            return obj
        else:
            raise ValueError(
                "Unknown level object %s (should be a string or Level)" % obj
            )

    def hierarchy(self, obj: Optional[Union[Hierarchy, str]] = None) -> Hierarchy:
        """Get hierarchy object either by name or as `Hierarchy`.

        If `obj` is ``None`` then default hierarchy is returned.
        """

        if obj is None:
            return self._default_hierarchy
        elif isinstance(obj, str):
            if obj not in self._hierarchies:
                raise ModelError(f"No hierarchy {obj} in dimension {self.name}")
            return self._hierarchies[obj]
        elif isinstance(obj, Hierarchy):
            return obj
        else:
            raise ValueError(
                "Unknown hierarchy object %s (should be a "
                "string or Hierarchy instance)" % obj
            )

    def attribute(self, name: str, by_ref: bool = False) -> Attribute:
        """Get dimension attribute.

        `name` is an attribute name (default) or attribute reference if
        `by_ref` is `True`.`.
        """

        if by_ref:
            return self._attributes_by_ref[name]
        else:
            try:
                return self._attributes[name]
            except KeyError:
                raise NoSuchAttributeError(
                    "Unknown attribute '{}' "
                    "in dimension '{}'".format(name, self.name),
                    name,
                )

    @property
    def is_flat(self) -> bool:
        """Is true if dimension has only one level."""
        if self.master:
            return self.master.is_flat

        return len(self.levels) == 1

    @property
    def key_attributes(self) -> List[Attribute]:
        """Return all dimension key attributes, regardless of hierarchy.

        Order is not guaranteed, use a hierarchy to have known order.
        """

        return [level.key for level in self._levels.values()]

    @property
    def attributes(self) -> List[Attribute]:
        """Return all dimension attributes regardless of hierarchy.

        Order is not guaranteed, use
        :meth:`cubes.Hierarchy.all_attributes` to get known order. Order
        of attributes within level is preserved.
        """

        return list(self._attributes.values())

    def clone(
        self,
        hierarchies: Optional[List[str]] = None,
        exclude_hierarchies: Optional[List[str]] = None,
        nonadditive: Optional[str] = None,
        default_hierarchy_name: Optional[str] = None,
        cardinality: Optional[str] = None,
        alias: Optional[str] = None,
        **extra: Any,
    ) -> "Dimension":
        """Returns a clone of the receiver with some modifications. `master` of
        the clone is set to the receiver.

        * `hierarchies` – limit hierarchies only to those specified in
          `hierarchies`. If default hierarchy name is not in the new hierarchy
          list, then the first hierarchy from the list is used.
        * `exclude_hierarchies` – all hierarchies are preserved except the
          hierarchies in this list
        * `nonadditive` – non-additive value for the dimension
        * `alias` – name of the cloned dimension
        """

        name: str

        if hierarchies == []:
            raise ModelInconsistencyError(
                "Can not remove all hierarchies from a dimension (%s)." % self.name
            )

        linked: List[Hierarchy] = []

        if hierarchies:
            for name in hierarchies:
                linked.append(self.hierarchy(name))
        elif exclude_hierarchies:
            for hierarchy in self._hierarchies.values():
                if hierarchy.name not in exclude_hierarchies:
                    linked.append(hierarchy)
        else:
            linked = list(self._hierarchies.values())

        cloned_hierarchies = [copy.deepcopy(hier) for hier in linked]

        if not cloned_hierarchies:
            raise ModelError("No hierarchies to clone. %s")

        # Get relevant levels
        levels = []
        seen: Set[str] = set()

        # Get only levels used in the hierarchies
        for hier in cloned_hierarchies:
            for level in hier.levels:
                if level.name in seen:
                    continue

                levels.append(level)
                seen.add(level.name)

        # Dis-own the level attributes (we already have a copy)
        for level in levels:
            for attribute in level.attributes:
                attribute.dimension = None

        nonadditive = nonadditive or self.nonadditive
        cardinality = cardinality or self.cardinality

        # We are not checking whether the default hierarchy name provided is
        # valid here, as it was specified explicitly with user's knowledge and
        # we might fail later. However, we need to check the existing default
        # hierarchy name and replace it with first available hierarchy if it
        # is invalid.

        if not default_hierarchy_name:
            if any(
                hier.name == self.default_hierarchy_name for hier in cloned_hierarchies
            ):
                default_hierarchy_name = self.default_hierarchy_name
            else:
                default_hierarchy_name = cloned_hierarchies[0].name

        # TODO: should we do deppcopy on info?
        name = alias or self.name

        return Dimension(
            name=name,
            levels=levels,
            hierarchies=cloned_hierarchies,
            default_hierarchy_name=default_hierarchy_name,
            label=self.label,
            description=self.description,
            info=self.info,
            role=self.role,
            cardinality=cardinality,
            master=self,
            nonadditive=nonadditive,
            **extra,
        )

    def to_dict(self, **options: Any) -> JSONType:
        """Return dictionary representation of the dimension."""

        out = super().to_dict(**options)

        hierarchy_limits = options.get("hierarchy_limits")

        out["default_hierarchy_name"] = self.hierarchy().name

        out["role"] = self.role
        out["cardinality"] = self.cardinality
        out["category"] = self.category

        out["levels"] = [level.to_dict(**options) for level in self.levels]

        # Collect hierarchies and apply hierarchy depth restrictions
        hierarchies = []
        hierarchy_limits = hierarchy_limits or {}
        for name, hierarchy in self._hierarchies.items():
            if name in hierarchy_limits:
                level = hierarchy_limits[name]
                if level:
                    depth = hierarchy.level_index(level) + 1
                    restricted = hierarchy.to_dict(depth=depth, **options)
                    hierarchies.append(restricted)
                else:
                    # we ignore the hierarchy
                    pass
            else:
                hierarchies.append(hierarchy.to_dict(**options))

        out["hierarchies"] = hierarchies

        # Use only for reading, during initialization these keys are ignored,
        # as they are derived
        # They are provided here for convenience.
        out["is_flat"] = self.is_flat
        out["has_details"] = self.has_details

        return out

    # TODO: Change to List[ValidationResult]
    def validate(self) -> List[Any]:
        """Validate dimension.

        See Model.validate() for more information.
        """
        results = []

        if not self.levels:
            results.append(("error", "No levels in dimension '%s'" % (self.name)))
            return results

        if not self._hierarchies:
            msg = "No hierarchies in dimension '%s'" % (self.name)
            if self.is_flat:
                level = self.levels[0]
                results.append(
                    ("default", msg + ", flat level '%s' will be used" % (level.name))
                )
            elif len(self.levels) > 1:
                results.append(
                    (
                        "error",
                        msg + ", more than one levels exist (%d)" % len(self.levels),
                    )
                )
            else:
                results.append(("error", msg))
        else:  # if self._hierarchies
            if not self.default_hierarchy_name:
                if len(self._hierarchies) > 1 and "default" not in self._hierarchies:
                    results.append(
                        (
                            "error",
                            "No defaut hierarchy specified, there is "
                            "more than one hierarchy in dimension "
                            "'%s'" % self.name,
                        )
                    )

        if self.default_hierarchy_name and not self._hierarchies.get(
            self.default_hierarchy_name
        ):
            results.append(
                (
                    "error",
                    "Default hierarchy '%s' does not exist in "
                    "dimension '%s'" % (self.default_hierarchy_name, self.name),
                )
            )

        attributes: Set[str] = set()
        first_occurence: Dict[str, str] = {}

        for level_name, level in self._levels.items():
            if not level.attributes:
                results.append(
                    (
                        "error",
                        "Level '%s' in dimension '%s' has no "
                        "attributes" % (level.name, self.name),
                    )
                )
                continue

            if not level.key:
                attr = level.attributes[0]
                results.append(
                    (
                        "default",
                        "Level '%s' in dimension '%s' has no key "
                        "attribute specified, first attribute will "
                        "be used: '%s'" % (level.name, self.name, attr),
                    )
                )

            if level.attributes and level.key:
                if level.key.name not in [a.name for a in level.attributes]:
                    results.append(
                        (
                            "error",
                            "Key '%s' in level '%s' in dimension "
                            "'%s' is not in level's attribute list"
                            % (level.key, level.name, self.name),
                        )
                    )

            for attribute in level.attributes:
                attr_name = attribute.ref
                if attr_name in attributes:
                    first = first_occurence[attr_name]
                    results.append(
                        (
                            "error",
                            "Duplicate attribute '%s' in dimension "
                            "'%s' level '%s' (also defined in level "
                            "'%s')" % (attribute, self.name, level_name, first),
                        )
                    )
                else:
                    attributes.add(attr_name)
                    first_occurence[attr_name] = level_name

                if not isinstance(attribute, Attribute):
                    results.append(
                        (
                            "error",
                            "Attribute '%s' in dimension '%s' is "
                            "not instance of Attribute" % (attribute, self.name),
                        )
                    )

                if attribute.dimension is not self:
                    results.append(
                        (
                            "error",
                            "Dimension (%s) of attribute '%s' does "
                            "not match with owning dimension %s"
                            % (attribute.dimension, attribute, self.name),
                        )
                    )

        return results

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<dimension: {{name: '{self.name}', levels: {self._levels}}}>"

    def localizable_dictionary(self) -> Dict[str, Any]:
        locale: Dict[str, Any] = {}
        locale.update(get_localizable_attributes(self))

        ldict: Dict[str, Any] = {}
        locale["levels"] = ldict

        for level in self.levels:
            ldict[level.name] = level.localizable_dictionary()

        hdict: Dict[str, Any] = {}
        locale["hierarchies"] = hdict

        for hier in self._hierarchies.values():
            hdict[hier.name] = hier.localizable_dictionary()

        return locale


def _create_hierarchies(
    metadata: JSONType, levels: List[Level], template: Optional[Dimension]
) -> List[Hierarchy]:
    """Create dimension hierarchies from `metadata` (a list of dictionaries or
    strings) and possibly inherit from `template` dimension."""

    # Convert levels do an ordered dictionary for access by name
    levels_by_name: Dict[str, Level]
    levels_by_name = object_dict(levels)
    hierarchies = []

    # Construct hierarchies and assign actual level objects
    for md in metadata:
        if isinstance(md, str):
            if template is not None:
                hier = template.hierarchy(md)
            else:
                raise ModelError(
                    "Can not specify just a hierarchy name "
                    "({}) if there is no template".format(md)
                )
        else:
            md = dict(md)
            level_names = md.pop("levels")
            hier_levels = [levels_by_name[level] for level in level_names]
            hier = Hierarchy(levels=hier_levels, **md)

        hierarchies.append(hier)

    return hierarchies
