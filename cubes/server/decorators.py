# -*- coding: utf-8 -*-
from contextlib import contextmanager
from functools import wraps
from typing import Callable

from flask import Blueprint, Flask, Response, current_app, g, request

from ..auth import NotAuthorized
from ..calendar import CalendarMemberConverter
from ..errors import *
from ..query.cells import Cell, cut_from_dict, cuts_from_string
from ..query.constants import SPLIT_DIMENSION_NAME
from ..workspace import Workspace
from .errors import *
from .local import *
from .utils import *

# Utils
# -----


def prepare_cell(argname="cut", target="cell", restrict=False):
    """Sets `g.cell` with a `Cell` object from argument with name `argname`"""
    # Used by prepare_browser_request and in /aggregate for the split cell

    # TODO: experimental code, for now only for dims with time role
    converters = {"time": CalendarMemberConverter(workspace.calendar)}

    cuts = []
    for cut_string in request.args.getlist(argname):
        cuts += cuts_from_string(g.cube, cut_string, role_member_converters=converters)

    if cuts:
        cell = Cell(cuts)
    else:
        cell = None

    if restrict:
        if workspace.authorizer:
            cell = workspace.authorizer.restricted_cell(
                g.auth_identity, cube=g.cube, cell=cell
            )
    setattr(g, target, cell)


def requires_cube(f: Callable) -> Callable:
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "lang" in request.args:
            g.locale = request.args.get("lang")
        else:
            g.locale = None

        cube_name = request.view_args.get("cube_name")
        try:
            g.cube = authorized_cube(cube_name, locale=g.locale)
        except NoSuchCubeError:
            raise NotFoundError(cube_name, "cube", "Unknown cube '%s'" % cube_name)

        return f(*args, **kwargs)

    return wrapper


def requires_browser(f: Callable) -> Callable:
    """Prepares three global variables: `g.cube`, `g.browser` and `g.cell`.

    Also athorizes the cube using `authorize()`.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if "lang" in request.args:
            g.locale = request.args.get("lang")
        else:
            g.locale = None

        cube_name = request.view_args.get("cube_name")
        if cube_name:
            cube = authorized_cube(cube_name, g.locale)
        else:
            cube = None

        g.cube = cube
        g.browser = workspace.browser(g.cube)

        prepare_cell(restrict=True)

        if "page" in request.args:
            try:
                g.page = int(request.args.get("page"))
            except ValueError:
                raise RequestError("'page' should be a number")
        else:
            g.page = None

        if "pagesize" in request.args:
            try:
                g.page_size = int(request.args.get("pagesize"))
            except ValueError:
                raise RequestError("'pagesize' should be a number")
        else:
            g.page_size = None

        # Collect orderings:
        # order is specified as order=<field>[:<direction>]
        #
        g.order = []
        for orders in request.args.getlist("order"):
            for order in orders.split(","):
                split = order.split(":")
                if len(split) == 1:
                    g.order.append((order, None))
                else:
                    g.order.append((split[0], split[1]))

        return f(*args, **kwargs)

    return wrapper


# Get authorized cube
# ===================


def authorized_cube(cube_name, locale):
    """Returns a cube `cube_name`.

    Handle cube authorization if required.
    """

    try:
        cube = workspace.cube(cube_name, g.auth_identity, locale=locale)
    except NotAuthorized:
        ident = "'%s'" % g.auth_identity if g.auth_identity else "unspecified identity"
        raise NotAuthorizedError(
            f"Authorization of cube '{cube_name}' failed for {ident}"
        )
    return cube


# Query Logging
# =============


def log_request(action: str, attrib_field: str = "attributes") -> Callable:
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            rlogger = current_app.slicer.request_logger

            # TODO: move this to request wrapper (same code as in aggregate)
            ddlist = request.args.getlist("drilldown")
            drilldown = []
            if ddlist:
                for ddstring in ddlist:
                    drilldown += ddstring.split("|")

            other = {
                "split": request.args.get("split"),
                "drilldown": drilldown,
                "page": g.page,
                "page_size": g.page_size,
                "format": request.args.get("format"),
                "header": request.args.get("header"),
                "attributes": request.args.get(attrib_field),
            }

            with rlogger.log_time(action, g.browser, g.cell, g.auth_identity, **other):
                retval = f(*args, **kwargs)

            return retval

        return wrapper

    return decorator
