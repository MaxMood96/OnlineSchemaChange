"""
Copyright (c) 2017-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree.
"""


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging

from pyparsing import (
    Word,
    Literal,
    Optional,
    nums,
    Group,
    CaselessLiteral,
    alphanums,
    ZeroOrMore,
    QuotedString,
    Combine,
    ParseException,
    SkipTo,
    StringEnd,
    upcaseTokens,
    nestedExpr,
    delimitedList,
)

from . import models

log = logging.getLogger(__name__)


__all__ = ["parse_create", "ParseError"]


class ParseError(Exception):
    def __init__(self, msg, line=0, column=0):
        self._msg = msg
        self._line = line
        self._column = column

    def __str__(self):
        return "Line: {}, Column: {}\n {}".format(self._line, self._column, self._msg)


class CreateParser(object):
    """
    This class can take a plain "CREATE TABLE" SQL as input and parse it into
    a Table object, so that we have more insight on the detail of this SQL.

    Example:
    sql = 'create table foo ( bar int primary key )'
    parser = CreateParser(sql)
    try:
        tbl_obj = parser.parse()
    except ParseError:
        log.error("Failed to parse SQL")

    This set of BNF rules are basically translated from the MySQL manual:
    http://dev.mysql.com/doc/refman/5.6/en/create-table.html
    If you don't know how to change the rule or fix the bug,
    <Getting Started with Pyparsing> is probably the best book to start with.
    Also this wiki has all supported functions listed:
    https://pyparsing.wikispaces.com/HowToUsePyparsing
    If you want have more information how these characters are
    matching, add .setDebug(True) after the specific token you want to debug
    """

    _parser = None
    _partitions_parser = None

    # Basic token
    WORD_CREATE = CaselessLiteral("CREATE").suppress()
    WORD_TABLE = CaselessLiteral("TABLE").suppress()
    COMMA = Literal(",").suppress()
    DOT = Literal(".")
    LEFT_PARENTHESES = Literal("(").suppress()
    RIGHT_PARENTHESES = Literal(")").suppress()
    QUOTE = Literal("'") | Literal('"')
    BACK_QUOTE = Optional(Literal("`")).suppress()
    LENGTH = Word(nums)
    DECIMAL = Combine(Word(nums) + DOT + Word(nums))
    OBJECT_NAME = Word(alphanums + "_" + "-" + "<" + ">" + ":")
    QUOTED_STRING_WITH_QUOTE = QuotedString(
        quoteChar="'", escQuote="''", escChar="\\", multiline=True, unquoteResults=False
    ) | QuotedString(
        quoteChar='"', escQuote='""', escChar="\\", multiline=True, unquoteResults=False
    )
    QUOTED_STRING = QuotedString(
        quoteChar="'", escQuote="''", escChar="\\", multiline=True
    ) | QuotedString(quoteChar='"', escQuote='""', escChar="\\", multiline=True)
    # Start of a create table statement
    # Sample: this part of rule will match following section
    # `table_name` IF NOT EXISTS
    IF_NOT_EXIST = Optional(
        CaselessLiteral("IF") + CaselessLiteral("NOT") + CaselessLiteral("EXISTS")
    ).suppress()
    TABLE_NAME = (
        QuotedString(quoteChar="`", escQuote="``", escChar="\\", unquoteResults=True)
        | OBJECT_NAME
    )("table_name")

    # Column definition
    # Sample: this part of rule will match following section
    # `id` bigint(20) unsigned NOT NULL DEFAULT '0',
    COLUMN_NAME = (
        QuotedString(quoteChar="`", escQuote="``", escChar="\\", unquoteResults=True)
        | OBJECT_NAME
    )("column_name")
    COLUMN_NAME_WITH_QUOTE = (
        QuotedString(quoteChar="`", escQuote="``", escChar="\\", unquoteResults=False)
        | OBJECT_NAME
    )("column_name")
    UNSIGNED = Optional(CaselessLiteral("UNSIGNED"))("unsigned")
    ZEROFILL = Optional(CaselessLiteral("ZEROFILL"))("zerofill")
    COL_LEN = Combine(LEFT_PARENTHESES + LENGTH + RIGHT_PARENTHESES, adjacent=False)(
        "length"
    )
    INT_TYPE = (
        CaselessLiteral("TINYINT")
        | CaselessLiteral("SMALLINT")
        | CaselessLiteral("MEDIUMINT")
        | CaselessLiteral("INT")
        | CaselessLiteral("INTEGER")
        | CaselessLiteral("BIGINT")
        | CaselessLiteral("BINARY")
        | CaselessLiteral("BIT")
    )
    INT_DEF = INT_TYPE("column_type") + Optional(COL_LEN) + UNSIGNED + ZEROFILL
    VARBINARY_DEF = CaselessLiteral("VARBINARY")("column_type") + COL_LEN
    FLOAT_TYPE = (
        CaselessLiteral("REAL")
        | CaselessLiteral("DOUBLE")
        | CaselessLiteral("FLOAT")
        | CaselessLiteral("DECIMAL")
        | CaselessLiteral("NUMERIC")
    )
    FLOAT_LEN = Combine(
        LEFT_PARENTHESES + LENGTH + Optional(COMMA + LENGTH) + RIGHT_PARENTHESES,
        adjacent=False,
        joinString=", ",
    )("length")
    FLOAT_DEF = FLOAT_TYPE("column_type") + Optional(FLOAT_LEN) + UNSIGNED + ZEROFILL
    # time type definition. They contain type_name and an optional FSP section
    # Sample: DATETIME[(fsp)]
    FSP = COL_LEN
    DT_DEF = (
        Combine(CaselessLiteral("TIME") + Optional(CaselessLiteral("STAMP")))
        | CaselessLiteral("DATETIME")
    )("column_type") + Optional(FSP)
    SIMPLE_DEF = (
        CaselessLiteral("DATE")
        | CaselessLiteral("YEAR")
        | CaselessLiteral("TINYBLOB")
        | CaselessLiteral("BLOB")
        | CaselessLiteral("MEDIUMBLOB")
        | CaselessLiteral("LONGBLOB")
        | CaselessLiteral("BOOLEAN")
        | CaselessLiteral("BOOL")
    )("column_type")
    OPTIONAL_COL_LEN = Optional(COL_LEN)
    BINARY = Optional(CaselessLiteral("BINARY"))("binary")
    CHARSET_NAME = (
        Optional(QUOTE).suppress()
        + Word(alphanums + "_")("charset")
        + Optional(QUOTE).suppress()
    )
    COLLATION_NAME = (
        Optional(QUOTE).suppress()
        + Word(alphanums + "_")("collate")
        + Optional(QUOTE).suppress()
    )
    CHARSET_DEF = CaselessLiteral("CHARACTER SET").suppress() + CHARSET_NAME
    COLLATE_DEF = CaselessLiteral("COLLATE").suppress() + COLLATION_NAME
    CHAR_DEF = CaselessLiteral("CHAR")("column_type") + OPTIONAL_COL_LEN + BINARY
    VARCHAR_DEF = CaselessLiteral("VARCHAR")("column_type") + COL_LEN + BINARY
    TEXT_TYPE = (
        CaselessLiteral("TINYTEXT")
        | CaselessLiteral("TEXT")
        | CaselessLiteral("MEDIUMTEXT")
        | CaselessLiteral("LONGTEXT")
        | CaselessLiteral("DOCUMENT")
    )
    TEXT_DEF = TEXT_TYPE("column_type") + BINARY
    ENUM_VALUE_LIST = Group(
        QUOTED_STRING_WITH_QUOTE + ZeroOrMore(COMMA + QUOTED_STRING_WITH_QUOTE)
    )("enum_value_list")
    ENUM_DEF = (
        CaselessLiteral("ENUM")("column_type")
        + LEFT_PARENTHESES
        + ENUM_VALUE_LIST
        + RIGHT_PARENTHESES
    )
    SET_VALUE_LIST = Group(
        QUOTED_STRING_WITH_QUOTE + ZeroOrMore(COMMA + QUOTED_STRING_WITH_QUOTE)
    )("set_value_list")
    SET_DEF = (
        CaselessLiteral("SET")("column_type")
        + LEFT_PARENTHESES
        + SET_VALUE_LIST
        + RIGHT_PARENTHESES
    )
    DATA_TYPE = (
        INT_DEF
        | FLOAT_DEF
        | DT_DEF
        | SIMPLE_DEF
        | TEXT_DEF
        | CHAR_DEF
        | VARCHAR_DEF
        | ENUM_DEF
        | SET_DEF
        | VARBINARY_DEF
    )

    # Column attributes come after column type and length
    NULLABLE = CaselessLiteral("NULL") | CaselessLiteral("NOT NULL")
    DEFAULT_VALUE = CaselessLiteral("DEFAULT").suppress() + (
        Optional(Literal("b"))("is_bit") + QUOTED_STRING_WITH_QUOTE("default")
        | Combine(
            CaselessLiteral("CURRENT_TIMESTAMP")("default")
            + Optional(COL_LEN)("ts_len")
        )
        | DECIMAL("default")
        | Word(alphanums + "_" + "-" + "+")("default")
    )
    ON_UPDATE = (
        CaselessLiteral("ON")
        + CaselessLiteral("UPDATE")
        + (
            CaselessLiteral("CURRENT_TIMESTAMP")("on_update")
            + Optional(COL_LEN)("on_update_ts_len")
        )
    )
    AUTO_INCRE = CaselessLiteral("AUTO_INCREMENT")
    UNIQ_KEY = CaselessLiteral("UNIQUE") + Optional(CaselessLiteral("KEY")).suppress()
    PRIMARY_KEY = (
        CaselessLiteral("PRIMARY") + Optional(CaselessLiteral("KEY")).suppress()
    )
    COMMENT = Combine(
        CaselessLiteral("COMMENT").suppress() + QUOTED_STRING_WITH_QUOTE, adjacent=False
    )
    COLUMN_DEF = Group(
        COLUMN_NAME
        + DATA_TYPE
        + ZeroOrMore(
            NULLABLE("nullable")
            | DEFAULT_VALUE
            | ON_UPDATE
            | AUTO_INCRE("auto_increment")
            | UNIQ_KEY("uniq_key")
            | PRIMARY_KEY("primary")
            | COMMENT("comment")
            | CHARSET_DEF
            | COLLATE_DEF
        )
    )
    COLUMN_LIST = Group(COLUMN_DEF + ZeroOrMore(COMMA + COLUMN_DEF))("column_list")

    DOCUMENT_PATH = Combine(
        COLUMN_NAME_WITH_QUOTE + ZeroOrMore(DOT + COLUMN_NAME_WITH_QUOTE)
    )
    IDX_COL = (
        Group(
            DOCUMENT_PATH
            + CaselessLiteral("AS")
            + (CaselessLiteral("INT") | CaselessLiteral("STRING"))
            + Optional(COL_LEN, default="")
        )
    ) | (Group(COLUMN_NAME + Optional(COL_LEN, default="")))

    # Primary key section
    COL_NAME_LIST = Group(IDX_COL + ZeroOrMore(COMMA + IDX_COL))
    IDX_COLS = LEFT_PARENTHESES + COL_NAME_LIST + RIGHT_PARENTHESES
    WORD_PRI_KEY = (
        CaselessLiteral("PRIMARY").suppress() + CaselessLiteral("KEY").suppress()
    )
    KEY_BLOCK_SIZE = (
        CaselessLiteral("KEY_BLOCK_SIZE").suppress()
        + Optional(Literal("="))
        + Word(nums)("idx_key_block_size")
    )
    INDEX_USING = CaselessLiteral("USING").suppress() + (
        CaselessLiteral("BTREE") | CaselessLiteral("HASH")
    )("idx_using")

    INDEX_OPTION = ZeroOrMore(KEY_BLOCK_SIZE | COMMENT("idx_comment") | INDEX_USING)
    PRI_KEY_DEF = COMMA + WORD_PRI_KEY + IDX_COLS("pri_list") + INDEX_OPTION

    # Index section
    KEY_TYPE = (CaselessLiteral("FULLTEXT") | CaselessLiteral("SPATIAL"))("key_type")
    WORD_UNIQUE = CaselessLiteral("UNIQUE")("unique")
    WORD_KEY = CaselessLiteral("INDEX").suppress() | CaselessLiteral("KEY").suppress()
    IDX_NAME = Optional(COLUMN_NAME)
    IDX_DEF = (
        ZeroOrMore(
            Group(
                COMMA
                + Optional(WORD_UNIQUE | KEY_TYPE)
                + WORD_KEY
                + IDX_NAME("index_name")
                + IDX_COLS("index_col_list")
                + INDEX_OPTION
            )
        )
    )("index_section")

    # Constraint section as this is not a recommended way of using MySQL
    # we'll treat the whole section as a string
    CONSTRAINT = Combine(
        ZeroOrMore(
            COMMA
            + Optional(CaselessLiteral("CONSTRAINT"))
            +
            # foreign key name except the key word 'FOREIGN'
            Optional((~CaselessLiteral("FOREIGN") + COLUMN_NAME))
            + CaselessLiteral("FOREIGN")
            + CaselessLiteral("KEY")
            + LEFT_PARENTHESES
            + COL_NAME_LIST
            + RIGHT_PARENTHESES
            + CaselessLiteral("REFERENCES")
            + COLUMN_NAME
            + LEFT_PARENTHESES
            + COL_NAME_LIST
            + RIGHT_PARENTHESES
            + ZeroOrMore(Word(alphanums))
        ),
        adjacent=False,
        joinString=" ",
    )("constraint")

    # Table option section
    ENGINE = (
        CaselessLiteral("ENGINE").suppress()
        + Optional(Literal("=")).suppress()
        + COLUMN_NAME("engine").setParseAction(upcaseTokens)
    )
    DEFAULT_CHARSET = (
        Optional(CaselessLiteral("DEFAULT")).suppress()
        + (
            (
                CaselessLiteral("CHARACTER").suppress()
                + CaselessLiteral("SET").suppress()
            )
            | (CaselessLiteral("CHARSET").suppress())
        )
        + Optional(Literal("=")).suppress()
        + Word(alphanums + "_")("charset")
    )
    TABLE_COLLATE = (
        Optional(CaselessLiteral("DEFAULT")).suppress()
        + CaselessLiteral("COLLATE").suppress()
        + Optional(Literal("=")).suppress()
        + COLLATION_NAME
    )
    ROW_FORMAT = (
        CaselessLiteral("ROW_FORMAT").suppress()
        + Optional(Literal("=")).suppress()
        + Word(alphanums + "_")("row_format").setParseAction(upcaseTokens)
    )
    TABLE_KEY_BLOCK_SIZE = (
        CaselessLiteral("KEY_BLOCK_SIZE").suppress()
        + Optional(Literal("=")).suppress()
        + Word(nums)("key_block_size").setParseAction(lambda s, l, t: [int(t[0])])
    )
    COMPRESSION = (
        CaselessLiteral("COMPRESSION").suppress()
        + Optional(Literal("=")).suppress()
        + Word(alphanums + "_")("compression").setParseAction(upcaseTokens)
    )
    # Parse and make sure auto_increment is an integer
    # parseAction function is defined as fn( s, loc, toks ), where:
    # s is the original parse string
    # loc is the location in the string where matching started
    # toks is the list of the matched tokens, packaged as a ParseResults_
    # object
    TABLE_AUTO_INCRE = (
        CaselessLiteral("AUTO_INCREMENT").suppress()
        + Optional(Literal("=")).suppress()
        + Word(nums)("auto_increment").setParseAction(lambda s, l, t: [int(t[0])])
    )
    TABLE_COMMENT = (
        CaselessLiteral("COMMENT").suppress()
        + Optional(Literal("=")).suppress()
        + QUOTED_STRING_WITH_QUOTE("comment")
    )

    TABLE_OPTION = ZeroOrMore(
        (
            ENGINE
            | DEFAULT_CHARSET
            | TABLE_COLLATE
            | ROW_FORMAT
            | TABLE_KEY_BLOCK_SIZE
            | COMPRESSION
            | TABLE_AUTO_INCRE
            | TABLE_COMMENT
        )
        # Table attributes could be comma separated too.
        + Optional(COMMA).suppress()
    )

    # Partition section
    PARTITION = Optional(
        Combine(
            Combine(Optional(Literal("/*!") + Word(nums)))
            + CaselessLiteral("PARTITION")
            + CaselessLiteral("BY")
            + SkipTo(StringEnd()),
            adjacent=False,
            joinString=" ",
        )("partition")
    )

    # Parse partitions in detail
    # From https://dev.mysql.com/doc/refman/8.0/en/create-table.html
    PART_FIELD_NAME = (
        QuotedString(quoteChar="`", escQuote="``", escChar="\\", unquoteResults=True)
        | OBJECT_NAME
    )
    PART_FIELD_LIST = delimitedList(PART_FIELD_NAME)("field_list")

    # e.g 1, 2, 3
    # and 'a', 'b', 'c'
    PART_VALUE_LIST = Group(
        LEFT_PARENTHESES
        + (delimitedList(Word(nums)) | delimitedList(QUOTED_STRING_WITH_QUOTE))
        + RIGHT_PARENTHESES
    )
    PART_VALUES_IN = (CaselessLiteral("IN").suppress() + PART_VALUE_LIST)("p_values_in")

    # Note: No expr support although full syntax (allowed by mysql8) is
    # LESS THAN {(expr | value_list) | MAXVALUE}
    PART_VALUES_LESSTHAN = (
        CaselessLiteral("LESS").suppress()
        + CaselessLiteral("THAN").suppress()
        + (CaselessLiteral("MAXVALUE").setParseAction(upcaseTokens) | PART_VALUE_LIST)
    )("p_values_less_than")

    PART_NAME = (
        QuotedString(quoteChar="`", escQuote="``", escChar="\\", unquoteResults=True)
        | OBJECT_NAME
    )("part_name")

    # Options for partition definitions - engine/comments only for now.
    # DO NOT re-use QUOTED_STRING_WITH_QUOTE for these -
    # *seems* to trigger a pyparsing bug?
    P_ENGINE = QuotedString(
        quoteChar="'", escQuote="''", escChar="\\", unquoteResults=False
    ) | QuotedString(
        quoteChar='"', escQuote='""', escChar="\\", multiline=True, unquoteResults=False
    )

    P_COMMENT = QuotedString(
        quoteChar="'", escQuote="''", escChar="\\", multiline=True, unquoteResults=False
    ) | QuotedString(
        quoteChar='"', escQuote='""', escChar="\\", multiline=True, unquoteResults=False
    )

    P_OPT_ENGINE = (
        Optional(CaselessLiteral("STORAGE")).suppress()
        + CaselessLiteral("ENGINE").suppress()
        + Optional(Literal("=")).suppress()
        + P_ENGINE.setParseAction(upcaseTokens)("pdef_engine")
    )
    P_OPT_COMMENT = (
        CaselessLiteral("COMMENT").suppress()
        + Optional(Literal("=")).suppress()
        + P_COMMENT("pdef_comment")
    )
    PDEF_OPTIONS = ZeroOrMore((P_OPT_ENGINE | P_OPT_COMMENT))

    # e.g. PARTITION p99 VALUES (LESS THAN|IN) ...
    PART_DEFS = delimitedList(
        Group(
            CaselessLiteral("PARTITION").suppress()
            + PART_NAME
            + CaselessLiteral("VALUES").suppress()
            + (PART_VALUES_LESSTHAN | PART_VALUES_IN)
            + PDEF_OPTIONS
        )
    )

    # No fancy expressions yet, just a list of cols for now.
    PART_EXPR = (
        LEFT_PARENTHESES
        + delimitedList(
            QuotedString(
                quoteChar="`", escQuote="``", escChar="\\", unquoteResults=True
            )
            | OBJECT_NAME
        )("p_expr")
        + RIGHT_PARENTHESES
    )

    SUBTYPE_LINEAR = (Optional(CaselessLiteral("LINEAR")).setParseAction(upcaseTokens))(
        "p_subtype"
    )
    # Match: [LINEAR] HASH (expr)
    PTYPE_HASH = (
        SUBTYPE_LINEAR
        + (CaselessLiteral("HASH").setParseAction(upcaseTokens))("part_type")
        + nestedExpr()("p_hash_expr")  # Lousy approximation, needs post processing
    )

    # Match: [LINEAR] KEY [ALGORITHM=1|2] (column_list)
    PART_ALGO = (
        CaselessLiteral("ALGORITHM").suppress()
        + Literal("=").suppress()
        + Word(alphanums)
    )("p_algo")

    PTYPE_KEY = (
        SUBTYPE_LINEAR
        + (CaselessLiteral("KEY").setParseAction(upcaseTokens))("part_type")
        + Optional(PART_ALGO)
        + Literal("(")  # don't suppress here
        + Optional(PART_FIELD_LIST)  # e.g. `PARTITION BY KEY() PARTITIONS 2` is valid
        + Literal(")")
    )

    PART_COL_LIST = (
        (CaselessLiteral("COLUMNS").setParseAction(upcaseTokens))("p_subtype")
        + LEFT_PARENTHESES
        + PART_FIELD_LIST
        + RIGHT_PARENTHESES
    )

    PTYPE_RANGE = (CaselessLiteral("RANGE").setParseAction(upcaseTokens))(
        "part_type"
    ) + (PART_COL_LIST | PART_EXPR)

    PTYPE_LIST = (CaselessLiteral("LIST").setParseAction(upcaseTokens))("part_type") + (
        PART_COL_LIST | PART_EXPR
    )

    @classmethod
    def generate_rule(cls):
        # The final rule for the whole statement match
        return (
            cls.WORD_CREATE
            + cls.WORD_TABLE
            + cls.IF_NOT_EXIST
            + cls.TABLE_NAME
            + cls.LEFT_PARENTHESES
            + cls.COLUMN_LIST
            + Optional(cls.PRI_KEY_DEF)
            + cls.IDX_DEF
            + cls.CONSTRAINT
            + cls.RIGHT_PARENTHESES
            + cls.TABLE_OPTION("table_options")
            + cls.PARTITION
        )

    @classmethod
    def get_parser(cls):
        if not cls._parser:
            cls._parser = cls.generate_rule()
        return cls._parser

    @classmethod
    def gen_partitions_parser(cls):
        # Init full parts matcher only on demand
        return (
            CaselessLiteral("PARTITION")
            + CaselessLiteral("BY")
            + (cls.PTYPE_HASH | cls.PTYPE_KEY | cls.PTYPE_RANGE | cls.PTYPE_LIST)
            + Optional(CaselessLiteral("PARTITIONS") + Word(nums)("num_partitions"))
            + Optional(cls.LEFT_PARENTHESES + cls.PART_DEFS("part_defs") + cls.RIGHT_PARENTHESES)
        )

    @classmethod
    def get_partitions_parser(cls):
        if not cls._partitions_parser:
            cls._partitions_parser = cls.gen_partitions_parser()
        return cls._partitions_parser

    @classmethod
    def parse_partitions(cls, parts):
        try:
            return cls.get_partitions_parser().parseString(parts)
        except ParseException as e:
            raise ParseError(f"Error parsing partitions: {e.line}, {e.column}")

    @classmethod
    def parse(cls, sql):
        try:
            if not isinstance(sql, str):
                sql = sql.decode("utf-8")
            result = cls.get_parser().parseString(sql)
        except ParseException as e:
            raise ParseError(
                "Failed to parse SQL, unsupported syntax: {}".format(e),
                e.line,
                e.column,
            )

        inline_pri_exists = False
        table = models.Table()
        table.name = result.table_name
        table_options = [
            "engine",
            "charset",
            "collate",
            "row_format",
            "key_block_size",
            "compression",
            "auto_increment",
            "comment",
        ]
        for table_option in table_options:
            if table_option in result:
                setattr(table, table_option, result.get(table_option))
        if "partition" in result:
            # pyparsing will convert newline into two after parsing. So we
            # need to dedup here
            table.partition = result.partition.replace("\n\n", "\n")
        if "constraint" in result:
            table.constraint = result.constraint
        for column_def in result.column_list:
            if column_def.column_type == "ENUM":
                column = models.EnumColumn()
                for enum_value in column_def.enum_value_list:
                    column.enum_list.append(enum_value)
            elif column_def.column_type == "SET":
                column = models.SetColumn()
                for set_value in column_def.set_value_list:
                    column.set_list.append(set_value)
            elif column_def.column_type in ("TIMESTAMP", "DATETIME"):
                column = models.TimestampColumn()
                if "on_update" in column_def:
                    if "on_update_ts_len" in column_def:
                        column.on_update_current_timestamp = "{}({})".format(
                            column_def.on_update, column_def.on_update_ts_len
                        )
                    else:
                        column.on_update_current_timestamp = column_def.on_update
            else:
                column = models.Column()

            column.name = column_def.column_name
            column.column_type = column_def.column_type

            # We need to check whether each column property exist in the
            # create table string, because not specifying a "COMMENT" is
            # different from specifying "COMMENT" equals to empty string.
            # The former one will ends up being
            #   column=None
            # and the later one being
            #   column=''
            if "comment" in column_def:
                column.comment = column_def.comment
            if "nullable" in column_def:
                if column_def.nullable == "NULL":
                    column.nullable = True
                elif column_def.nullable == "NOT NULL":
                    column.nullable = False
            if "unsigned" in column_def:
                if column_def.unsigned == "UNSIGNED":
                    column.unsigned = True
            if "default" in column_def:
                if "ts_len" in column_def:
                    column.default = "{}({})".format(
                        column_def.default, column_def.ts_len
                    )
                else:
                    column.default = column_def.default
                if "is_bit" in column_def:
                    column.is_default_bit = True
            if "charset" in column_def:
                column.charset = column_def.charset
            if "length" in column_def:
                column.length = column_def.length
            if "collate" in column_def:
                column.collate = column_def.collate
            if "auto_increment" in column_def:
                column.auto_increment = True
            if "primary" in column_def:
                idx_col = models.IndexColumn()
                idx_col.name = column_def.column_name
                table.primary_key.column_list.append(idx_col)
                inline_pri_exists = True
            table.column_list.append(column)
        if "pri_list" in result:
            if inline_pri_exists:
                raise ParseError("Multiple primary keys defined")
            table.primary_key.name = "PRIMARY"
            for col in result.pri_list:
                for name, length in col:
                    idx_col = models.IndexColumn()
                    idx_col.name = name
                    if length:
                        idx_col.length = length
                    table.primary_key.column_list.append(idx_col)
            if "idx_key_block_size" in result:
                table.primary_key.key_block_size = result.pri_key_block_size
            if "idx_comment" in result:
                table.primary_key.comment = result.idx_comment
        if "index_section" in result:
            for idx_def in result.index_section:
                idx = models.TableIndex()
                idx.name = idx_def.index_name
                if "idx_key_block_size" in idx_def:
                    idx.key_block_size = idx_def.idx_key_block_size
                if "idx_comment" in idx_def:
                    idx.comment = idx_def.idx_comment
                if "idx_using" in idx_def:
                    idx.using = idx_def.idx_using
                if "key_type" in idx_def:
                    idx.key_type = idx_def.key_type
                if "unique" in idx_def:
                    idx.is_unique = True
                for col in idx_def.index_col_list:
                    for col_def in col:
                        if len(col_def) == 4 and col_def[1].upper() == "AS":
                            (document_path, word_as, key_type, length) = col_def
                            idx_col = models.DocStoreIndexColumn()
                            idx_col.document_path = document_path
                            idx_col.key_type = key_type
                            if length:
                                idx_col.length = length
                            idx.column_list.append(idx_col)
                        else:
                            (name, length) = col_def
                            idx_col = models.IndexColumn()
                            idx_col.name = name
                            if length:
                                idx_col.length = length
                            idx.column_list.append(idx_col)
                table.indexes.append(idx)
        return table


def parse_create(sql):
    return CreateParser.parse(sql)
