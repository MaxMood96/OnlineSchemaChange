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

import copy
from enum import Enum

from .models import is_equal, escape, TimestampColumn, EnumColumn, SetColumn


class BaseAlterType(Enum):
    pass


# Side note the algorithm that could be chosen for DDL. See https://fburl.com/bxftsout
class ColAlterType(BaseAlterType):
    CHANGE_COL_DEFAULT_VAL = "change_col_default_val"  # instant
    REORDER_COL = "reorder_col"  # rebuild
    ADD_COL = "add_col"  # instant
    ADD_AUTO_INC_COL = "add_auto_inc_col"  # inplace
    DROP_COL = "drop_col"  # rebuild
    CHANGE_COL_DATA_TYPE = "change_col_data_type"  # copy
    CHANGE_NULL = "change_null"  # rebuild
    CHANGE_ENUM = "change_enum"  # instant/copy
    CHANGE_SET = "change_set"  # instant/copy
    CHANGE_COL_CHARSET = "change_col_charset"
    CHANGE_COL_COLLATE = "change_col_collate"
    CHANGE_COL_COMMENT = "change_col_comment"


class IndexAlterType(BaseAlterType):
    CHANGE_INDEX_TYPE = "change_index_type"  # instant. index type is hash/btree
    CHANGE_UNIQUE_CONSTRAINT = "change_unique_constraint"
    CHANGE_INDEX_KEY_BLOCK_SIZE = "change_index_key_block_size"
    CHANGE_KEY_TYPE = "change_key_type"  # key type is FULLTEXT/SPATIAL
    CHANGE_INDEX_COMMENT = "change_index_comment"
    ADD_INDEX = "add_index"  # inplace
    DROP_INDEX = "drop_index"  # inplace, metadata only
    CHANGE_PK = "change_pk"  # copy


class TableAlterType(BaseAlterType):
    CHANGE_ROW_FORMAT = "change_row_format"
    CHANGE_TABLE_KEY_BLOCK_SIZE = "change_table_key_block_size"
    CHANGE_TABLE_CHARSET = "change_table_charset"
    CHANGE_TABLE_COLLATE = "change_table_collate"
    CHANGE_TABLE_COMMENT = "change_table_comment"
    CHANGE_ENGINE = "change_engine"
    CHANGE_AUTO_INC_VAL = "change_auto_inc_val"  # inplace


INSTANT_DDLS = {
    ColAlterType.CHANGE_COL_DEFAULT_VAL,
    ColAlterType.ADD_COL,
    IndexAlterType.CHANGE_INDEX_TYPE,
}


class TableOptionDiff(object):
    def __init__(self, option_name, value):
        self.option_name = option_name
        self.value = value

    def to_sql(self):
        return "{}={}".format(self.option_name, self.value)


class SchemaDiff(object):
    """
    Representing the difference between two Table object
    """

    def __init__(self, left, right, ignore_partition=False):
        self.left = left
        self.right = right
        self.attrs_to_check = [
            "charset",
            "collate",
            "comment",
            "engine",
            "key_block_size",
            "name",
            "row_format",
        ]
        if not ignore_partition:
            self.attrs_to_check.append("partition")
        self._alter_types = set()

    def _calculate_diff(self):
        diffs = {
            "removed": [],
            "added": [],
            # Customized messages
            "msgs": [],
            # Any attributes that were modified
            "attrs_modified": [],
        }
        # We are copying here since we want to change the col list.
        # Shallow copy should be enough here
        col_left_copy = copy.copy(self.left.column_list)
        col_right_copy = copy.copy(self.right.column_list)
        for col in self.left.column_list:
            if col not in self.right.column_list:
                diffs["removed"].append(col)
                col_left_copy.remove(col)

        for col in self.right.column_list:
            if col not in self.left.column_list:
                diffs["added"].append(col)
                col_right_copy.remove(col)

        # Two tables have different col order
        if sorted(col_left_copy, key=lambda col: col.name) == sorted(
            col_right_copy, key=lambda col: col.name
        ):
            old_order = []
            new_order = []
            for col1, col2 in zip(col_left_copy, col_right_copy):
                if col1 != col2:
                    old_order.append(col1.name)
                    new_order.append(col2.name)
            if old_order:
                diffs["msgs"].append("Column order mismatch was detected:")
                diffs["msgs"].append("- " + ", ".join(old_order))
                diffs["msgs"].append("+ " + ", ".join(new_order))

        for idx in self.left.indexes:
            if idx not in self.right.indexes:
                diffs["removed"].append(idx)
        for idx in self.right.indexes:
            if idx not in self.left.indexes:
                diffs["added"].append(idx)

        if self.left.primary_key != self.right.primary_key:
            if self.left.primary_key.column_list:
                diffs["removed"].append(self.left.primary_key)
            if self.right.primary_key.column_list:
                diffs["added"].append(self.right.primary_key)

        for attr in self.attrs_to_check:
            tbl_option_old = getattr(self.left, attr)
            tbl_option_new = getattr(self.right, attr)
            if not is_equal(tbl_option_old, tbl_option_new):
                diffs["removed"].append(TableOptionDiff(attr, tbl_option_old))
                diffs["added"].append(TableOptionDiff(attr, tbl_option_new))
                diffs["attrs_modified"].append(attr)

        return diffs

    def __str__(self):
        if self.left == self.right:
            return "No difference"
        else:
            diff_strs = []
            diffs = self._calculate_diff()
            for diff in diffs["removed"]:
                diff_strs.append("- " + diff.to_sql())
            for diff in diffs["added"]:
                diff_strs.append("+ " + diff.to_sql())
            for diff in diffs["msgs"]:
                diff_strs.append(diff)
            for attr in diffs["attrs_modified"]:
                diff_strs.append(f"attrs_modified: {attr}")
            diff_str = "\n".join(diff_strs)
            return diff_str

    def diffs(self):
        return self._calculate_diff()

    @property
    def alter_types(self):
        if not self._alter_types:
            self.to_sql()
        return self._alter_types

    def add_alter_type(self, ddl_alter_type):
        self._alter_types.add(ddl_alter_type)

    def _gen_col_sql(self):
        """
        Generate the column section for ALTER TABLE statement
        """
        segments = []
        old_columns = {col.name: col for col in self.left.column_list}
        new_columns = {col.name: col for col in self.right.column_list}
        old_column_names = [col.name for col in self.left.column_list]
        new_column_names = [col.name for col in self.right.column_list]

        # Drop columns
        for col in self.left.column_list:
            if col.name not in new_columns.keys():
                segments.append("DROP `{}`".format(escape(col.name)))
                old_column_names.remove(col.name)
                self.add_alter_type(ColAlterType.DROP_COL)

        # Add columns
        # If the added column is not at the end, recognize that as reordering columns
        handled_cols = []
        for idx, col in enumerate(self.right.column_list):
            if col.name not in old_columns.keys():
                if idx == 0:
                    position = "FIRST"
                    if (
                        old_column_names
                        and ColAlterType.DROP_COL not in self._alter_types
                    ):
                        self.add_alter_type(ColAlterType.REORDER_COL)
                    old_column_names = [col.name] + old_column_names
                else:
                    position = "AFTER `{}`".format(
                        escape(self.right.column_list[idx - 1].name)
                    )
                    new_idx = (
                        old_column_names.index(self.right.column_list[idx - 1].name) + 1
                    )
                    if (
                        new_idx != len(old_column_names)
                        and ColAlterType.DROP_COL not in self._alter_types
                    ):
                        self.add_alter_type(ColAlterType.REORDER_COL)
                    old_column_names = (
                        old_column_names[:new_idx]
                        + [col.name]
                        + old_column_names[new_idx:]
                    )
                handled_cols.append(col.name)
                self.add_alter_type(ColAlterType.ADD_COL)
                if col.auto_increment:
                    self.add_alter_type(ColAlterType.ADD_AUTO_INC_COL)
                segments.append("ADD {} {}".format(col.to_sql(), position))

        # Adjust position
        # The idea here is to compare column ancestor if they are the same between
        # old and new column list, this means the position of this particular
        # column hasn't been changed. Otherwise add a MODIFY clause to change the
        # position
        for idx, col_name in enumerate(new_column_names):
            # If the column is recently added, then skip because it's already
            # in the DDL
            if col_name in handled_cols:
                continue
            # Get column definition
            col = new_columns[col_name]
            old_pos = old_column_names.index(col_name)

            # If the first column is diferent, we need to adjust the sequence
            if idx == 0:
                if old_pos == 0:
                    continue
                segments.append("MODIFY {} FIRST".format(col.to_sql()))
                handled_cols.append(col_name)
                self.add_alter_type(ColAlterType.REORDER_COL)
                continue

            # If this column has the same ancestor then it means there's no sequence
            # adjustment needed
            if new_column_names[idx - 1] == old_column_names[old_pos - 1]:
                continue

            segments.append(
                "MODIFY {} AFTER `{}`".format(
                    col.to_sql(), escape(new_column_names[idx - 1])
                )
            )
            handled_cols.append(col_name)
            self.add_alter_type(ColAlterType.REORDER_COL)

        # Modify columns
        for col in self.right.column_list:
            if col.name in old_columns and col != old_columns[col.name]:
                # If the column has been taken care of because of sequence change
                # previously we can skip the work here
                if col.name in handled_cols:
                    continue
                self._update_col_attrs_changes(col, old_columns[col.name])
                segments.append("MODIFY {}".format(col.to_sql()))
        return segments

    def _is_null_change(self, old_col, new_col):
        if isinstance(old_col, TimestampColumn):
            old_col.explicit_ts_default()
        if isinstance(new_col, TimestampColumn):
            new_col.explicit_ts_default()
        return old_col.nullable != new_col.nullable

    def _is_col_default_change(self, old_col, new_col):
        if isinstance(old_col, TimestampColumn):
            old_col.explicit_ts_default()
        if isinstance(new_col, TimestampColumn):
            new_col.explicit_ts_default()
        return not old_col.has_same_default(new_col)

    def _update_col_attrs_changes(self, new_col, old_col):
        if (
            new_col.column_type != old_col.column_type
            or new_col.length != old_col.length
        ):
            self.add_alter_type(ColAlterType.CHANGE_COL_DATA_TYPE)
        if (
            self._is_col_default_change(old_col, new_col)
            and ColAlterType.CHANGE_COL_DATA_TYPE not in self._alter_types
        ):
            self.add_alter_type(ColAlterType.CHANGE_COL_DEFAULT_VAL)
        if (
            self._is_null_change(old_col, new_col)
            and ColAlterType.CHANGE_COL_DATA_TYPE not in self._alter_types
        ):
            self.add_alter_type(ColAlterType.CHANGE_NULL)
        if (
            isinstance(new_col, EnumColumn)
            and isinstance(old_col, EnumColumn)
            and new_col.enum_list != old_col.enum_list
        ):
            self.add_alter_type(ColAlterType.CHANGE_ENUM)
        if (
            isinstance(new_col, SetColumn)
            and isinstance(old_col, SetColumn)
            and new_col.set_list != old_col.set_list
        ):
            self.add_alter_type(ColAlterType.CHANGE_SET)
        if new_col.charset != old_col.charset:
            self.add_alter_type(ColAlterType.CHANGE_COL_CHARSET)
        if new_col.collate != old_col.collate:
            self.add_alter_type(ColAlterType.CHANGE_COL_COLLATE)
        if new_col.comment != old_col.comment:
            self.add_alter_type(ColAlterType.CHANGE_COL_COMMENT)

    def _gen_idx_sql(self):
        """
        Generate the index section for ALTER TABLE statement
        """
        segments = []

        # Drop index
        for idx in self.left.indexes:
            if idx not in self.right.indexes:
                segments.append("DROP KEY `{}`".format(escape(idx.name)))
                self.add_alter_type(IndexAlterType.DROP_INDEX)

        # Add index
        for idx in self.right.indexes:
            if idx not in self.left.indexes:
                segments.append("ADD {}".format(idx.to_sql()))
                self.add_alter_type(IndexAlterType.ADD_INDEX)
                self._update_index_attrs_changes(idx.name)

        if self.left.primary_key and not self.right.primary_key:
            segments.append("DROP PRIMARY KEY")
            self.add_alter_type(IndexAlterType.CHANGE_PK)
        elif (
            not self.left.primary_key.column_list and self.right.primary_key.column_list
        ):
            segments.append("ADD {}".format(self.right.primary_key.to_sql()))
            self.add_alter_type(IndexAlterType.CHANGE_PK)
        elif self.left.primary_key != self.right.primary_key:
            segments.append("DROP PRIMARY KEY")
            segments.append("ADD {}".format(self.right.primary_key.to_sql()))
            self.add_alter_type(IndexAlterType.CHANGE_PK)

        return segments

    def _update_index_attrs_changes(self, idx_name):
        old_indexes = {idx.name: idx for idx in self.left.indexes}
        new_indexes = {idx.name: idx for idx in self.right.indexes}
        if not (idx_name in old_indexes and idx_name in new_indexes):
            return
        attrs = ["key_block_size", "comment", "is_unique", "key_type", "using"]
        for attr in attrs:
            if not is_equal(
                getattr(old_indexes[idx_name], attr),
                getattr(new_indexes[idx_name], attr),
            ):
                if attr == "key_block_size":
                    self.add_alter_type(IndexAlterType.CHANGE_INDEX_KEY_BLOCK_SIZE)
                elif attr == "comment":
                    self.add_alter_type(IndexAlterType.CHANGE_INDEX_COMMENT)
                elif attr == "is_unique":
                    self.add_alter_type(IndexAlterType.CHANGE_UNIQUE_CONSTRAINT)
                elif attr == "key_type":
                    self.add_alter_type(IndexAlterType.CHANGE_KEY_TYPE)
                elif attr == "using":
                    self.add_alter_type(IndexAlterType.CHANGE_INDEX_TYPE)

    def _gen_tbl_attr_sql(self):
        """
        Generate the table attribute section for ALTER TABLE statement
        """
        segments = []

        for attr in self.attrs_to_check:
            tbl_option_old = getattr(self.left, attr)
            tbl_option_new = getattr(self.right, attr)
            if not is_equal(tbl_option_old, tbl_option_new):
                # when tbl_option_new is None, do "alter table xxx attr=None" won't work
                if attr == "comment" and tbl_option_new is None:
                    segments.append("{}={}".format(attr, "''"))
                elif attr == "row_format" and tbl_option_new is None:
                    segments.append("{}={}".format(attr, "default"))
                else:
                    segments.append("{}={}".format(attr, tbl_option_new))

                # populate alter types data
                if attr == "row_format":
                    self.add_alter_type(TableAlterType.CHANGE_ROW_FORMAT)
                elif attr == "key_block_size":
                    self.add_alter_type(TableAlterType.CHANGE_TABLE_KEY_BLOCK_SIZE)
                elif attr == "charset":
                    self.add_alter_type(TableAlterType.CHANGE_TABLE_CHARSET)
                elif attr == "collate":
                    self.add_alter_type(TableAlterType.CHANGE_TABLE_COLLATE)
                elif attr == "comment":
                    self.add_alter_type(TableAlterType.CHANGE_TABLE_COMMENT)
                elif attr == "engine":
                    self.add_alter_type(TableAlterType.CHANGE_ENGINE)

        # we don't want to alter auto_increment value in db, just record the alter type
        if not is_equal(self.left.auto_increment, self.right.auto_increment):
            self.add_alter_type(TableAlterType.CHANGE_AUTO_INC_VAL)
        return segments

    def to_sql(self):
        """
        Generate an ALTER TABLE statement that can bring the schema from left to
        right
        """
        segments = []

        segments.extend(self._gen_col_sql())
        segments.extend(self._gen_idx_sql())
        segments.extend(self._gen_tbl_attr_sql())
        if segments:
            return "ALTER TABLE `{}` {}".format(
                escape(self.right.name), ", ".join(segments)
            )


def get_type_conv_columns(old_obj, new_obj):
    """
    Return a list of columns that involve type conversion when transit from left to
    right
    """
    type_conv_cols = []

    current_cols = {c.name: c for c in old_obj.column_list}
    new_cols = {c.name: c for c in new_obj.column_list}

    # find columns that will involve type conversions
    for name, old_col in current_cols.items():
        new_col = new_cols.get(name)

        # this column isn't in the new schema, so it
        # doesn't matter
        if new_col is None:
            continue

        # Type changes are considered as type conversion
        if new_col.column_type != old_col.column_type:
            type_conv_cols.append(old_col)
        else:
            # Length change also considered as type conversion
            if new_col.length != old_col.length:
                type_conv_cols.append(old_col)
    return type_conv_cols


def need_default_ts_bootstrap(old_obj, new_obj):
    """
    Check when going from old schema to new, whether bootstraping column using
    CURRENT_TIMESTAMP is involved. This is normally dangerous thing to do out of
    replication and will be disallowed by default from OSC perspective
    """
    current_cols = {c.name: c for c in old_obj.column_list}
    new_cols = {c.name: c for c in new_obj.column_list}

    # find columns that will involve type conversions
    for name, new_col in new_cols.items():
        old_col = current_cols.get(name)

        # This check only applies to column types that support default ts value
        if new_col.column_type not in ["TIMESTAMP", "DATE", "DATETIME"]:
            continue
        if new_col.column_type == "TIMESTAMP":
            new_col.explicit_ts_default()

        # Nothing to worry if a vulnerable column type doesn't use current time
        # as default
        if str(new_col.column_type) == "TIMESTAMP":
            # Cases for TIMESTAMP type
            if (
                str(new_col.default).upper() != "CURRENT_TIMESTAMP"
                and str(new_col.on_update_current_timestamp).upper()
                != "CURRENT_TIMESTAMP"
            ):
                continue
        else:
            # Cases for DATE and DATETIME type
            if str(new_col.default).upper() != "CURRENT_TIMESTAMP":
                continue

        # Adding timestamp column with defaults is considered unsafe
        # out of replication bootstraping
        if not old_col:
            return True

        # At this point we know this column in new schema need default value setting
        # to curernt ts. We will need to further confirm if old schema does the same
        # or not. If not, this will be consider as dangerous for replication
        if (
            str(new_col.default).upper() == "CURRENT_TIMESTAMP"
            and str(old_col.default).upper() != "CURRENT_TIMESTAMP"
        ):
            return True

        if (
            str(new_col.on_update_current_timestamp).upper() == "CURRENT_TIMESTAMP"
            and str(old_col.on_update_current_timestamp).upper() != "CURRENT_TIMESTAMP"
        ):
            return True

    return False
