##
# Copyright (c) 2008-2012 Sprymix Inc.
# All rights reserved.
#
# See LICENSE for details.
##


import postgresql.string

from metamagic.utils import datastructures

from .. import common
from . import base
from . import composites
from . import ddl


class Table(composites.CompositeDBObject):
    def __init__(self, name):
        super().__init__(name)

        self.__columns = datastructures.OrderedSet()
        self._columns = []

        self.constraints = set()
        self.bases = set()
        self.data = []

    def columns(self, writable_only=False, only_self=False):
        cols = []
        tables = [self.__class__] if only_self else reversed(self.__class__.__mro__)
        for c in tables:
            if issubclass(c, Table):
                columns = getattr(self, '_' + c.__name__ + '__columns', [])
                if writable_only:
                    cols.extend(c for c in columns if not c.readonly)
                else:
                    cols.extend(columns)
        return cols

    def __iter__(self):
        return iter(self._columns)

    def add_columns(self, iterable):
        self.__columns.update(iterable)
        self._columns = self.columns()

    def get_type(self):
        return 'TABLE'

    def get_id(self):
        return common.qname(*self.name)


class Column(base.DBObject):
    def __init__(self, name, type, required=False, default=None, readonly=False, comment=None):
        self.name = name
        self.type = type
        self.required = required
        self.default = default
        self.readonly = readonly
        self.comment = comment

    def code(self, context, short=False):
        code = '{} {}'.format(common.quote_ident(self.name), self.type)
        if not short:
            default = 'DEFAULT {}'.format(self.default) if self.default is not None else ''
            code += ' {} {}'.format('NOT NULL' if self.required else '', default)
        return code

    def extra(self, context, alter_table):
        if self.comment is not None:
            col = TableColumn(table_name=alter_table.name, column=self)
            cmd = ddl.Comment(object=col, text=self.comment)
            return [cmd]

    def __repr__(self):
        return '<%s.%s "%s" %s>' % (self.__class__.__module__, self.__class__.__name__,
                                    self.name, self.type)


class TableColumn(base.DBObject):
    def __init__(self, table_name, column):
        self.table_name = table_name
        self.column = column

    def get_type(self):
        return 'COLUMN'

    def get_id(self):
        return common.qname(self.table_name[0], self.table_name[1], self.column.name)


class TableConstraint(base.DBObject):
    def __init__(self, table_name, column_name=None):
        self.table_name = table_name
        self.column_name = column_name

    def constraint_name(self):
        raise NotImplementedError

    def code(self, context):
        return None

    def rename_code(self, context):
        return None

    def extra(self, context, alter_table):
        return None

    def rename_extra(self, context, new_name):
        return None

    def get_type(self):
        return 'CONSTRAINT'

    def get_id(self):
        constr_id = self.constraint_name()

        if self.table_name:
            constr_id += ' ON {}'.format(common.qname(*self.table_name))

        return constr_id


class PrimaryKey(TableConstraint):
    def __init__(self, table_name, columns):
        super().__init__(table_name)
        self.columns = columns

    def code(self, context):
        code = 'PRIMARY KEY (%s)' % ', '.join(common.quote_ident(c) for c in self.columns)
        return code


class UniqueConstraint(TableConstraint):
    def __init__(self, table_name, columns):
        super().__init__(table_name)
        self.columns = columns

    def code(self, context):
        code = 'UNIQUE (%s)' % ', '.join(common.quote_ident(c) for c in self.columns)
        return code


class TableExists(base.Condition):
    def __init__(self, name):
        self.name = name

    def code(self, context):
        code = '''SELECT
                        tablename
                    FROM
                        pg_catalog.pg_tables
                    WHERE
                        schemaname = $1 AND tablename = $2'''
        return code, self.name


class TableInherits(base.Condition):
    def __init__(self, name, parent_name):
        self.name = name
        self.parent_name = parent_name

    def code(self, context):
        code = '''SELECT
                        c.relname
                    FROM
                        pg_class c
                        INNER JOIN pg_namespace ns ON ns.oid = c.relnamespace
                        INNER JOIN pg_inherits i ON i.inhrelid = c.oid
                        INNER JOIN pg_class pc ON i.inhparent = pc.oid
                        INNER JOIN pg_namespace pns ON pns.oid = pc.relnamespace
                    WHERE
                        ns.nspname = $1 AND c.relname = $2
                        AND pns.nspname = $3 AND pc.relname = $4
               '''
        return code, self.name + self.parent_name


class ColumnExists(base.Condition):
    def __init__(self, table_name, column_name):
        self.table_name = table_name
        self.column_name = column_name

    def code(self, context):
        code = '''SELECT
                        column_name
                    FROM
                        information_schema.columns
                    WHERE
                        table_schema = $1 AND table_name = $2 AND column_name = $3'''
        return code, self.table_name + (self.column_name,)


class CreateTable(ddl.SchemaObjectOperation):
    def __init__(self, table, temporary=False, *, conditions=None, neg_conditions=None, priority=0):
        super().__init__(table.name, conditions=conditions, neg_conditions=neg_conditions,
                         priority=priority)
        self.table = table
        self.temporary = temporary

    def code(self, context):
        elems = [c.code(context) for c in self.table.columns(only_self=True)]
        elems += [c.code(context) for c in self.table.constraints]

        name = common.qname(*self.table.name)
        cols = ', '.join(c for c in elems)
        temp = 'TEMPORARY ' if self.temporary else ''

        code = 'CREATE %sTABLE %s (%s)' % (temp, name, cols)

        if self.table.bases:
            code += ' INHERITS (' + ','.join(common.qname(*b) for b in self.table.bases) + ')'

        return code


class AlterTableBaseMixin:
    def __init__(self, name, contained=False, **kwargs):
        self.name = name
        self.contained = contained

    def prefix_code(self, context):
        return 'ALTER TABLE %s%s' % ('ONLY ' if self.contained else '', common.qname(*self.name))

    def __repr__(self):
        return '<%s.%s %s>' % (self.__class__.__module__, self.__class__.__name__, self.name)


class AlterTableBase(AlterTableBaseMixin, ddl.DDLOperation):
    def __init__(self, name, *, contained=False, conditions=None, neg_conditions=None, priority=0):
        ddl.DDLOperation.__init__(self, conditions=conditions, neg_conditions=neg_conditions,
                                  priority=priority)
        AlterTableBaseMixin.__init__(self, name=name, contained=contained)

    def get_attribute_term(self):
        return 'COLUMN'


class AlterTableFragment(ddl.DDLOperation):
    def get_attribute_term(self):
        return 'COLUMN'


class AlterTable(AlterTableBaseMixin, base.CompositeCommandGroup):
    def __init__(self, name, *, contained=False, conditions=None, neg_conditions=None, priority=0):
        base.CompositeCommandGroup.__init__(self, conditions=conditions,
                                            neg_conditions=neg_conditions,
                                            priority=priority)
        AlterTableBaseMixin.__init__(self, name=name, contained=contained)
        self.ops = self.commands

    add_operation = base.CompositeCommandGroup.add_command


class AlterTableAddParent(AlterTableFragment):
    def __init__(self, parent_name, **kwargs):
        super().__init__(**kwargs)
        self.parent_name = parent_name

    def code(self, context):
        return 'INHERIT %s' % common.qname(*self.parent_name)

    def __repr__(self):
        return '<%s.%s %s>' % (self.__class__.__module__, self.__class__.__name__, self.parent_name)


class AlterTableDropParent(AlterTableFragment):
    def __init__(self, parent_name):
        self.parent_name = parent_name

    def code(self, context):
        return 'NO INHERIT %s' % common.qname(*self.parent_name)

    def __repr__(self):
        return '<%s.%s %s>' % (self.__class__.__module__, self.__class__.__name__, self.parent_name)


class AlterTableAddColumn(composites.AlterCompositeAddAttribute, AlterTableFragment):
    pass


class AlterTableDropColumn(composites.AlterCompositeDropAttribute, AlterTableFragment):
    pass


class AlterTableAlterColumnType(composites.AlterCompositeAlterAttributeType, AlterTableFragment):
    pass


class AlterTableAlterColumnNull(AlterTableFragment):
    def __init__(self, column_name, null):
        self.column_name = column_name
        self.null = null

    def code(self, context):
        return 'ALTER COLUMN %s %s NOT NULL' % \
                (common.quote_ident(str(self.column_name)), 'DROP' if self.null else 'SET')

    def __repr__(self):
        return '<%s.%s "%s" %s NOT NULL>' % (self.__class__.__module__, self.__class__.__name__,
                                             self.column_name, 'DROP' if self.null else 'SET')


class AlterTableAlterColumnDefault(AlterTableFragment):
    def __init__(self, column_name, default):
        self.column_name = column_name
        self.default = default

    def code(self, context):
        if self.default is None:
            return 'ALTER COLUMN %s DROP DEFAULT' % (common.quote_ident(str(self.column_name)),)
        else:
            return 'ALTER COLUMN %s SET DEFAULT %s' % \
                    (common.quote_ident(str(self.column_name)),
                     postgresql.string.quote_literal(str(self.default)))

    def __repr__(self):
        return '<%s.%s "%s" %s DEFAULT%s>' % (self.__class__.__module__, self.__class__.__name__,
                                              self.column_name,
                                              'DROP' if self.default is None else 'SET',
                                              '' if self.default is None else ' %r' % self.default)


class TableConstraintCommand:
    pass


class TableConstraintExists(base.Condition):
    def __init__(self, table_name, constraint_name):
        self.table_name = table_name
        self.constraint_name = constraint_name

    def code(self, context):
        code = '''SELECT
                        True
                    FROM
                        pg_catalog.pg_constraint c
                        INNER JOIN pg_catalog.pg_class t ON c.conrelid = t.oid
                        INNER JOIN pg_catalog.pg_namespace ns ON t.relnamespace = ns.oid
                    WHERE
                        conname = $1 AND relname = $3 AND nspname = $2'''
        return code, (self.constraint_name,) + self.table_name


class AlterTableAddConstraint(AlterTableFragment, TableConstraintCommand):
    def __init__(self, constraint):
        self.constraint = constraint

    def code(self, context):
        return 'ADD  ' + self.constraint.code(context)

    def extra(self, context, alter_table):
        return self.constraint.extra(context, alter_table)

    def __repr__(self):
        return '<%s.%s %r>' % (self.__class__.__module__, self.__class__.__name__,
                               self.constraint)


class AlterTableRenameConstraint(AlterTableBase, TableConstraintCommand):
    def __init__(self, table_name, constraint, new_constraint, **kwargs):
        super().__init__(table_name, **kwargs)
        self.constraint = constraint
        self.new_constraint = new_constraint

    def code(self, context):
        return self.constraint.rename_code(context, self.new_constraint)

    def extra(self, context):
        return self.constraint.rename_extra(context, self.new_constraint)

    def __repr__(self):
        return '<%s.%s %r to %r>' % (self.__class__.__module__, self.__class__.__name__,
                                       self.constraint, self.new_constraint)


class AlterTableDropConstraint(AlterTableFragment, TableConstraintCommand):
    def __init__(self, constraint):
        self.constraint = constraint

    def code(self, context):
        return 'DROP CONSTRAINT ' + self.constraint.constraint_name()

    def __repr__(self):
        return '<%s.%s %r>' % (self.__class__.__module__, self.__class__.__name__,
                               self.constraint)


class AlterTableSetSchema(AlterTableBase):
    def __init__(self, name, schema, **kwargs):
        super().__init__(name, **kwargs)
        self.schema = schema

    def code(self, context):
        code = super().prefix_code(context)
        code += ' SET SCHEMA %s ' % common.quote_ident(self.schema)
        return code


class AlterTableRenameTo(AlterTableBase):
    def __init__(self, name, new_name, **kwargs):
        super().__init__(name, **kwargs)
        self.new_name = new_name

    def code(self, context):
        code = super().prefix_code(context)
        code += ' RENAME TO %s ' % common.quote_ident(self.new_name)
        return code


class AlterTableRenameColumn(composites.AlterCompositeRenameAttribute, AlterTableBase):
    pass


class DropTable(ddl.SchemaObjectOperation):
    def code(self, context):
        return 'DROP TABLE %s' % common.qname(*self.name)
