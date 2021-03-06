-- this function requires postgis >= 2.0.0 with raster support
CREATE OR REPLACE FUNCTION public.bgdi_watermask_rasterize(bbox geometry, width integer, height integer, watermask_table regclass, watermask_geom_column text)
  RETURNS SETOF raster AS
$BODY$
DECLARE 
    sql     TEXT;
    xmin    float default xmin(bbox);
    ymin    float default ymin(bbox);
    xmax    float default xmax(bbox);
    ymax    float default ymax(bbox);
    scalex  float default (xmax-xmin)/width;
    scaley  float default -((ymax-ymin)/height);
    inside  integer;
    outside integer;
BEGIN
    IF EXISTS (
        SELECT * FROM information_schema.columns
        WHERE table_name=watermask_table::text
        AND column_name=watermask_geom_column
    ) THEN

    -- this query returns a raster with a stable extent of 256x256 pixels
    -- raster type is 8BUI
    -- pixel value 0: land
    -- pixel value 255: lake
    -- if the tile geometry lies completely inside a lake a raster with one pixel with value 1 will be returned
    -- if the tile geometry lies completely outside the lakes a raster with one pixel with value 0 will be returned
    EXECUTE format('SELECT count(1) FROM %I where ST_ContainsProperly(%I,%L)',watermask_table,watermask_geom_column,bbox) INTO inside;
    EXECUTE format('SELECT count(1) FROM %I where ST_Intersects(%L,%I)',watermask_table,bbox,watermask_geom_column) INTO outside;
    IF outside = 0 THEN
        --RAISE NOTICE 'tile lies completely outside lakes';
        sql := 'SELECT ST_AddBand(ST_MakeEmptyRaster(1, 1, 0, 0, 1, 1, 0, 0, 4326), ''8BUI''::text, 0, 0)';
        RETURN QUERY EXECUTE sql;
        RETURN;
    END IF;

    IF inside > 0 THEN
        --RAISE NOTICE 'tile lies completely inside a lake';
        sql := 'SELECT ST_AddBand(ST_MakeEmptyRaster(1, 1, 0, 0, 1, 1, 0, 0, 4326), ''8BUI''::text, 255, 0)';
        RETURN QUERY EXECUTE sql;
        RETURN;
    END IF;

    -- ST_Union not needed for single band rasters
    sql := '
    WITH input AS (
        SELECT ST_AddBand(ST_MakeEmptyRaster('|| width ||', '|| height ||', '|| xmin ||', '|| ymax ||', '|| scalex ||', '|| scaley ||', 0, 0, 4326), ''8BUI''::text, 255, 0) AS raster
    ),
    intersected AS (
        SELECT
          ST_AsRaster(ST_Intersection('|| watermask_geom_column ||', ST_Envelope(raster)), raster, ''8BUI''::text, 255, 0, true) AS raster
          FROM '|| watermask_table ||' AS vector, input
          WHERE ST_Intersects(vector.'|| watermask_geom_column ||', ST_Envelope(input.raster))
    )
    SELECT ST_MapAlgebra(
        r1.raster, 1,
        r2.raster, 1,
        ''[rast2.val]''::text,
        ''8BUI''::text,
        ''FIRST''::text,
        ''0''::text,
        ''0''::text,
        0
    )
    FROM input AS r1
    CROSS JOIN intersected AS r2
    ';

    --RAISE NOTICE 'function parameters: xmin: % ymin: % xmax: % ymax: % scalex: % scaley: % watermask_table: % watermask_column % ',xmin,ymin,xmax,ymax,scalex,scaley,watermask_table,watermask_geom_column;
    --RAISE NOTICE 'sql: %',sql;
    RETURN QUERY EXECUTE sql;
    ELSE
        RAISE NOTICE 'could not open column % in table % ',watermask_geom_column,watermask_table;
    END IF;
  
END
$BODY$
LANGUAGE plpgsql STABLE
COST 100;
