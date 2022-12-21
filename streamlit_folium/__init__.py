from __future__ import annotations

import hashlib
import os
import re
import warnings
from textwrap import dedent
from typing import Dict, Iterable, List

import branca
import folium
import folium.plugins
import streamlit.components.v1 as components
from jinja2 import UndefinedError

# Create a _RELEASE constant. We'll set this to False while we're developing
# the component, and True when we're ready to package and distribute it.
_RELEASE = True

if not _RELEASE:
    _component_func = components.declare_component(
        "st_folium", url="http://localhost:3001"
    )
else:
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(parent_dir, "frontend/build")
    _component_func = components.declare_component("st_folium", path=build_dir)


def generate_js_hash(js_string: str, key: str = None) -> str:
    """
    Generate a standard key from a javascript string representing a series
    of folium-generated leaflet objects by replacing the hash's at the end
    of variable names (e.g. "marker_5f9d46..." -> "marker"), and returning
    the hash.

    Also strip maps/<random_hash>, which is generated by google earth engine
    """
    pattern = r"(_[a-z0-9]+)"
    standardized_js = re.sub(pattern, "", js_string) + str(key)
    url_pattern = r"(maps\/[-a-z0-9]+\/)"
    standardized_js = re.sub(url_pattern, "", standardized_js) + str(key)
    s = hashlib.sha256(standardized_js.encode()).hexdigest()
    return s


def folium_static(
    fig: folium.Figure | folium.Map,
    width: int = 700,
    height: int = 500,
):
    """
    Renders `folium.Figure` or `folium.Map` in a Streamlit app. This method is
    a static Streamlit Component, meaning, no information is passed back from
    Leaflet on browser interaction.
    Parameters
    ----------
    fig  : folium.Map or folium.Figure
        Geospatial visualization to render
    width : int
        Width of result
    Height : int
        Height of result
    Note
    ----
    If `height` is set on a `folium.Map` or `folium.Figure` object,
    that value supersedes the values set with the keyword arguments of this function.

    Example
    -------
    >>> m = folium.Map(location=[45.5236, -122.6750])
    >>> folium_static(m)
    """
    warnings.warn(
        dedent(
            """
        folium_static is deprecated and will be removed in a future release, or
        simply replaced with with st_folium which always passes
        returned_objects=[] to the component.
        Please try using st_folium instead, and
        post an issue at https://github.com/randyzwitch/streamlit-folium/issues
        if you experience issues with st_folium.
        """
        ),
        DeprecationWarning,
    )
    # if Map, wrap in Figure
    if isinstance(fig, folium.Map):
        fig = folium.Figure().add_child(fig)
        return components.html(
            fig.render(), height=(fig.height or height) + 10, width=width
        )

    # if DualMap, get HTML representation
    elif isinstance(fig, folium.plugins.DualMap) or isinstance(
        fig, branca.element.Figure
    ):
        return components.html(fig._repr_html_(), height=height + 10, width=width)
    return st_folium(fig, width=width, height=height, returned_objects=[])


def st_folium(
    fig: folium.MacroElement,
    key: str | None = None,
    height: int = 700,
    width: int = 500,
    returned_objects: Iterable[str] | None = None,
    zoom: int | None = None,
    center: tuple[float, float] | None = None,
    feature_group_to_add: folium.FeatureGroup | None = None,
):
    """Display a Folium object in Streamlit, returning data as user interacts
    with app.
    Parameters
    ----------
    fig  : folium.Map or folium.Figure
        Geospatial visualization to render
    key: str or None
        An optional key that uniquely identifies this component. If this is
        None, and the component's arguments are changed, the component will
        be re-mounted in the Streamlit frontend and lose its current state.
    returned_objects: Iterable
        A list of folium objects (as keys of the returned dictionart) that will be
        returned to the user when they interact with the map. If None, all folium
        objects will be returned. This is mainly useful for when you only want your
        streamlit app to rerun under certain conditions, and not every time the user
        interacts with the map. If an object not in returned_objects changes on the map,
        the app will not rerun.
    zoom: int or None
        The zoom level of the map. If None, the zoom level will be set to the
        default zoom level of the map. NOTE that if this zoom level is changed, it
        will *not* reload the map, but simply dynamically change the zoom level.
    center: tuple(float, float) or None
        The center of the map. If None, the center will be set to the default
        center of the map. NOTE that if this center is changed, it will *not* reload
        the map, but simply dynamically change the center.
    feature_group_to_add: folium.FeatureGroup or None
        If you want to dynamically add features to a feature group, you can pass
        the feature group here. NOTE that if you add a feature to the map, it
        will *not* reload the map, but simply dynamically add the feature.
    Returns
    -------
    dict
        Selected data from Folium/leaflet.js interactions in browser
    """
    # Call through to our private component function. Arguments we pass here
    # will be sent to the frontend, where they'll be available in an "args"
    # dictionary.
    #
    # "default" is a special argument that specifies the initial return
    # value of the component before the user has interacted with it.

    # handle the case where you pass in a figure rather than a map
    # this assumes that a map is the first child
    fig.render()

    if not (isinstance(fig, folium.Map) or isinstance(fig, folium.plugins.DualMap)):
        fig = list(fig._children.values())[0]

    leaflet = generate_leaflet_string(fig, base_id="map_div")

    children = list(fig.get_root()._children.values())

    html = ""
    if len(children) > 1:
        for child in children[1:]:
            try:
                html += child._template.module.html() + "\n"
            except Exception:
                pass

    # Replace the folium generated map_{random characters} variables
    # with map_div and map_div2 (these end up being both the assumed)
    # div id where the maps are inserted into the DOM, and the names of
    # the variables themselves.
    if isinstance(fig, folium.plugins.DualMap):
        m_id = get_full_id(fig.m1)
        m2_id = get_full_id(fig.m2)
        leaflet = leaflet.replace(m2_id, "map_div2")
    else:
        m_id = get_full_id(fig)

    # Get rid of the annoying popup
    leaflet = leaflet.replace("alert(coords);", "")

    if "drawnItems" not in leaflet:
        leaflet += "\nvar drawnItems = [];"

    def bounds_to_dict(bounds_list: List[List[float]]) -> Dict[str, Dict[str, float]]:
        southwest, northeast = bounds_list
        return {
            "_southWest": {
                "lat": southwest[0],
                "lng": southwest[1],
            },
            "_northEast": {
                "lat": northeast[0],
                "lng": northeast[1],
            },
        }

    try:
        bounds = fig.get_bounds()
    except AttributeError:
        bounds = [[None, None], [None, None]]

    _defaults = {
        "last_clicked": None,
        "last_object_clicked": None,
        "all_drawings": None,
        "last_active_drawing": None,
        "bounds": bounds_to_dict(bounds),
        "zoom": fig.options.get("zoom") if hasattr(fig, "options") else {},
        "last_circle_radius": None,
        "last_circle_polygon": None,
    }

    # If the user passes a custom list of returned objects, we'll only return those

    defaults = {
        k: v
        for k, v in _defaults.items()
        if returned_objects is None or k in returned_objects
    }

    # Convert the feature group to a javascript string which can be used to create it
    # on the frontend.
    feature_group_string = None
    if feature_group_to_add is not None:
        feature_group_to_add._id = "feature_group"
        feature_group_to_add.add_to(fig)
        feature_group_string = generate_leaflet_string(
            feature_group_to_add, base_id="feature_group"
        )
        m_id = get_full_id(fig)
        feature_group_string = feature_group_string.replace(m_id, "map_div")
        feature_group_string += """
        map_div.addLayer(feature_group_feature_group);
        window.feature_group = feature_group_feature_group;
        """

    component_value = _component_func(
        script=leaflet,
        html=html,
        id=m_id,
        key=generate_js_hash(leaflet, key),
        height=height,
        width=width,
        returned_objects=returned_objects,
        default=defaults,
        zoom=zoom,
        center=center,
        feature_group=feature_group_string,
    )

    return component_value


def get_full_id(m: folium.MacroElement) -> str:
    if isinstance(m, folium.plugins.DualMap):
        m = m.m1
    return f"{m._name.lower()}_{m._id}"


def _generate_leaflet_string(
    m: folium.MacroElement,
    nested: bool = True,
    base_id: str = "0",
    mappings: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    if mappings is None:
        mappings = {}

    mappings[m._id] = base_id

    m._id = base_id

    if isinstance(m, folium.plugins.DualMap):
        if not nested:
            return _generate_leaflet_string(m.m1, nested=False, mappings=mappings)
        # Generate the script for map1
        leaflet, _ = _generate_leaflet_string(m.m1, nested=nested, mappings=mappings)
        # Add the script for map2
        leaflet += (
            "\n" + _generate_leaflet_string(m.m2, nested=nested, mappings=mappings)[0]
        )
        # Add the script that syncs them together
        leaflet += m._template.module.script(m)
        return leaflet, mappings

    try:
        leaflet = m._template.module.script(m)
    except UndefinedError:
        # Correctly render Popup elements, and perhaps others. Not sure why
        # this is necessary. Some deep magic related to jinja2 templating, perhaps.
        leaflet = m._template.render(this=m, kwargs={})

    if not nested:
        return leaflet, mappings

    for idx, child in enumerate(m._children.values()):
        try:
            leaflet += (
                "\n"
                + _generate_leaflet_string(
                    child, base_id=f"{base_id}_{idx}", mappings=mappings
                )[0]
            )
        except (UndefinedError, AttributeError):
            pass

    return leaflet, mappings


def generate_leaflet_string(
    m: folium.MacroElement, nested: bool = True, base_id: str = "0"
) -> str:
    """
    Call the _generate_leaflet_string function, and then replace the
    folium generated var {thing}_{random characters} variables with
    standardized variables, in case any didn't already get replaced
    (e.g. in the case of a LayerControl, it still has a reference
    to the old variable for the tile_layer_{random_characters}).

    This also allows the output to be more testable, since the
    variable names are consistent.
    """
    leaflet, mappings = _generate_leaflet_string(m, nested=nested, base_id=base_id)

    for k, v in mappings.items():
        leaflet = leaflet.replace(k, v)

    return leaflet
