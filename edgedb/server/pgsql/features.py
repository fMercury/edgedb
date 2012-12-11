##
# Copyright (c) 2008-2012 Sprymix Inc.
# All rights reserved.
#
# See LICENSE for details.
##


"""Database features."""

import postgresql.exceptions

from metamagic.caos.backends.pgsql import deltadbops


class UuidFeature(deltadbops.Feature):
    source = '%(pgpath)s/contrib/uuid-ossp.sql'

    def __init__(self, schema='caos'):
        super().__init__(name='uuid', schema=schema)

    def get_extension_name(self):
        return 'uuid-ossp'


class HstoreFeature(deltadbops.Feature):
    source = '%(pgpath)s/contrib/hstore.sql'

    def __init__(self, schema='caos'):
        super().__init__(name='hstore', schema=schema)

    @classmethod
    def init_feature(cls, db):
        try:
            db.typio.identify(contrib_hstore='caos.hstore')
        except postgresql.exceptions.SchemaNameError:
            pass


class FuzzystrmatchFeature(deltadbops.Feature):
    source = '%(pgpath)s/contrib/fuzzystrmatch.sql'

    def __init__(self, schema='caos'):
        super().__init__(name='fuzzystrmatch', schema=schema)


class ProductAggregateFeature(deltadbops.Feature):
    def __init__(self, schema='caos'):
        super().__init__(name='agg_product', schema=schema)

    def code(self, context):
        return """
            CREATE AGGREGATE {schema}.agg_product(double precision) (SFUNC=float8mul, STYPE=double precision, INITCOND=1);
            CREATE AGGREGATE {schema}.agg_product(numeric) (SFUNC=numeric_mul, STYPE=numeric, INITCOND=1);
        """.format(schema=self.schema)


class KnownRecordMarkerFeature(deltadbops.Feature):
    def __init__(self, schema='caos'):
        super().__init__(name='known_record_marker_t', schema=schema)

    def code(self, context):
        return """
            CREATE DOMAIN {schema}.known_record_marker_t AS text;
        """.format(schema=self.schema)

    @classmethod
    def init_feature(cls, db):
        ps = db.prepare('''
            SELECT
                t.oid
            FROM
                pg_type t INNER JOIN pg_namespace ns ON t.typnamespace = ns.oid
            WHERE
                t.typname = 'known_record_marker_t'
                AND ns.nspname = 'caos'
        ''')
        oid = ps.first()
        if oid is not None:
            db._sx_known_record_marker_oid_ = oid
