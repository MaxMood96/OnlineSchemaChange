-- Copyright (c) 2017-present, Facebook, Inc.
-- All rights reserved.
-- 
-- This source code is licensed under the BSD-style license found in the
-- LICENSE file in the root directory of this source tree.

drop TABLE IF EXISTS `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` ;
CREATE TABLE IF NOT EXISTS `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` (
  `id` bigint(20) unsigned NOT NULL DEFAULT '0' ,
  `data` mediumtext COLLATE latin1_bin NOT NULL,
  PRIMARY KEY (`id`) COMMENT 'id'
);
insert into aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa values (1,'a');
insert into aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa values (2,'b');
