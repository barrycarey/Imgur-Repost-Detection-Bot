-- --------------------------------------------------------
-- Host:                         sr2.plxbx.com
-- Server version:               5.7.10-log - MySQL Community Server (GPL)
-- Server OS:                    Win64
-- HeidiSQL Version:             8.3.0.4694
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Dumping database structure for imgur_repost
DROP DATABASE IF EXISTS `imgur_repost`;
CREATE DATABASE IF NOT EXISTS `imgur_repost` /*!40100 DEFAULT CHARACTER SET latin1 */;
USE `imgur_repost`;


-- Dumping structure for table imgur_repost.imgur_reposts
DROP TABLE IF EXISTS `imgur_reposts`;
CREATE TABLE IF NOT EXISTS `imgur_reposts` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `image_id` varchar(100) NOT NULL DEFAULT '0',
  `date` datetime NOT NULL,
  `url` text NOT NULL,
  `hash` varchar(16) NOT NULL,
  `user` varchar(100) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- Data exporting was unselected.
/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
