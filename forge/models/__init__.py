# -*- coding: utf-8 -*-

from sqlalchemy.sql import func, and_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement, text
from geoalchemy2.elements import WKBElement
from shapely.geometry import box, Point


class _interpolate_height_on_plane(FunctionElement):
    name = "_interpolate_height_on_plane"


class bgdi_watermask_rasterize(FunctionElement):
    name = "bgdi_watermask_rasterize"


class create_simplified_geom_table(FunctionElement):
    name = "create_simplified_geom_table"


@compiles(_interpolate_height_on_plane)
def _compile_interpolate_height(element, compiler, **kw):
    return "_interpolate_height_on_plane(%s)" % compiler.process(element.clauses)


@compiles(bgdi_watermask_rasterize)
def _compile_watermask(element, compiler, **kw):
    return "bgdi_watermask_rasterize(%s)" % compiler.process(element.clauses)


@compiles(create_simplified_geom_table)
def _compile_create_simplified_geom_table(element, compiler, **kw):
    return "create_simplified_geom_table(%s)" % compiler.process(element.clauses)


class Vector(object):

    @classmethod
    def primaryKeyColumn(cls):
        return cls.__mapper__.primary_key[0]

    @classmethod
    def geometryColumn(cls):
        return cls.__mapper__.columns['the_geom']

    """
    Returns a sqlalchemy.sql.functions.Function clipping function
    :param bbox: A list of 4 coordinates [minX, minY, maxX, maxY]
    :params srid: Spatial reference system numerical ID
    """
    @classmethod
    def bboxClippedGeom(cls, bbox, srid=4326):
        bboxGeom = shapelyBBox(bbox)
        wkbGeometry = WKBElement(buffer(bboxGeom.wkb), srid)
        geomColumn = cls.geometryColumn()
        return func.ST_Intersection(geomColumn, wkbGeometry)

    """
    Returns a slqalchemy.sql.functions.Function (interesects function)
    Use it as a filter to determine if a geometry should be returned (True or False)
    :params bbox: A list of 4 coordinates [minX, minX, maxX, maxY]
    :params fromSrid: Spatial reference system numerical ID of the bbox
    :params toSrid: Spatial reference system numerical ID of the table
    """
    @classmethod
    def bboxIntersects(cls, bbox, fromSrid=4326, toSrid=4326):
        bboxGeom = shapelyBBox(bbox)
        wkbGeometry = WKBElement(buffer(bboxGeom.wkb), fromSrid)
        if fromSrid != toSrid:
            wkbGeometry = func.ST_Transform(wkbGeometry, toSrid)
        geomColumn = cls.geometryColumn()
        return and_(
            geomColumn.intersects(wkbGeometry),
            func.ST_Intersects(geomColumn, wkbGeometry)
        )

    """
    Returns a slqalchemy.sql.functions.Function (interesects function)
    Use it as a filter to determine if a geometry should be returned (True or False)
    using a tolerance (in table unit). This function only works in 2 dimensions.
    :params bbox: A list of 4 coordinates [minX, minX, maxX, maxY]
    :params fromSrid: Spatial reference system numerical ID of the bbox
    :params toSrid: Spatial reference system numerical ID of the table
    :params tolerance: Tolerance in table unit
    """
    @classmethod
    def withinDistance2D(cls, bbox, fromSrid=4326, toSrid=4326, tolerance=0.):
        bboxGeom = shapelyBBox(bbox)
        wkbGeometry = WKBElement(buffer(bboxGeom.wkb), fromSrid)
        if fromSrid != toSrid:
            wkbGeometry = func.ST_Transform(wkbGeometry, toSrid)
        geomColumn = cls.geometryColumn()
        return func.ST_DWithin(geomColumn, wkbGeometry, tolerance)

    """
    Returns a slqalchemy.sql.functions.Function (interesects function)
    Use it as a point filter to determine if a geometry should be returned (True or False)
    :params point: A list of dim 3 representing one point [X, Y, Z]
    :params geomColumn: A sqlAlchemy Column representing a postgis geometry (Optional)
    :params srid: Spatial reference system numerical ID
    """
    @classmethod
    def pointIntersects(cls, point, geomColumn=None, srid=4326):
        pointGeom = Point(point)
        wkbGeometry = WKBElement(buffer(pointGeom.wkb), srid)
        geomColumn = cls.geometryColumn() if geomColumn is None else geomColumn
        return func.ST_Intersects(geomColumn, wkbGeometry)

    """
    Returns a slqalchemy.sql.functions.Function
    Use it as a point filter to determine if a geometry should be returned (True or False)
    :params point: A list of dim 3 representing one point [X, Y, Z]
    :params geomColumn: A sqlAlchemy Column representing a postgis geometry
    :params srid: Spatial reference system numerical ID
    """
    @classmethod
    def interpolateHeightOnPlane(cls, point, geomColumn=None, srid=4326):
        pointGeom = Point(point)
        wkbGeometry = WKBElement(buffer(pointGeom.wkb), srid)
        geomColumn = cls.geometryColumn() if geomColumn is None else geomColumn
        return func.ST_AsEWKB(_interpolate_height_on_plane(geomColumn, wkbGeometry))

    """
    Return a sqlalchemy.sql.functions.Function
    Use it to create watermasks using a bounding box and a tile width and height in px
    :params bbox: A list of 4 coordinates [minX, minX, maxX, maxY]
    :params width: The width of the image in px
    :params height: The height of the image in px
    :params srid: Spatial reference system numerical ID
    """
    @classmethod
    def watermaskRasterize(cls, bbox, width=256, height=256, srid=4326):
        geomColumn = cls.geometryColumn()
        bboxGeom = shapelyBBox(bbox)
        wkbGeometry = WKBElement(buffer(bboxGeom.wkb), srid)
        # ST_DumpValues(Raster, Band Number, True -> returns None
        # and False -> returns numerical vals)
        return func.ST_DumpValues(
            bgdi_watermask_rasterize(
                wkbGeometry, width, height,
                '.'.join((cls.__table_args__['schema'], cls.__tablename__)),
                geomColumn.name
            ), 1, False
        )


"""
Returns a shapely.geometry.polygon.Polygon
:param bbox: A list of 4 cooridinates [minX, minY, maxX, maxY]
"""


def shapelyBBox(bbox):
    return box(*bbox)


"""
Returns a sqlalchemy.sql.expression.text
:params schemaname: the schema name
:params tablename: the table name
:params srid: Spatial reference system numerical ID
"""


def tableExtentLiteral(schemaname, tablename, srid):
    return text("SELECT ST_XMin(r), ST_YMin(r), "
                "ST_XMax(r), ST_YMax(r) "
                "FROM (SELECT ST_Collect(ST_Transform(the_geom, %d)) AS r "
                "FROM %s.%s) AS foo" % (srid, schemaname, tablename)
                )
