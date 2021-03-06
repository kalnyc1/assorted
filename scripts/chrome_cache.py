#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Script to parse Chrome Cache files."""

from __future__ import print_function
import argparse
import datetime
import logging
import os
import sys

import construct

import hexdump


def SuperFastHash(key):
  """Function to calculate the super fast hash.

  Args:
    key (bytes): key for which to calculate the hash.

  Returns:
    int: hash of the key.
  """
  if not key:
    return 0

  key_length = len(key)
  hash_value = key_length & 0xffffffff
  remainder = key_length & 0x00000003
  key_length -= remainder

  for key_index in xrange(0, key_length, 4):
    hash_value = (
        (hash_value + ord(key[key_index]) + (ord(key[key_index + 1]) << 8)) &
        0xffffffff)

    temp_value = ord(key[key_index + 2]) + (ord(key[key_index + 3]) << 8)

    temp_value = ((temp_value << 11) & 0xffffffff) ^ hash_value
    hash_value = ((hash_value << 16) & 0xffffffff) ^ temp_value

    hash_value = (hash_value + (hash_value >> 11)) & 0xffffffff

  key_index = key_length

  if remainder == 3:
    hash_value = (
        (hash_value + ord(key[key_index]) + (ord(key[key_index + 1]) << 8)) &
        0xffffffff)
    hash_value ^= (hash_value << 16) & 0xffffffff
    hash_value ^= (ord(key[key_index + 2]) << 18) & 0xffffffff
    hash_value = (hash_value + (hash_value >> 11)) & 0xffffffff

  elif remainder == 2:
    hash_value = (
        (hash_value + ord(key[key_index]) + (ord(key[key_index + 1]) << 8)) &
        0xffffffff)
    hash_value ^= (hash_value << 11) & 0xffffffff
    hash_value = (hash_value + (hash_value >> 17)) & 0xffffffff

  elif remainder == 1:
    hash_value = (hash_value + ord(key[key_index])) & 0xffffffff
    hash_value ^= (hash_value << 10) & 0xffffffff
    hash_value = (hash_value + (hash_value >> 1)) & 0xffffffff

  # Force "avalanching" of final 127 bits.
  hash_value ^= (hash_value << 3) & 0xffffffff
  hash_value = (hash_value + (hash_value >> 5)) & 0xffffffff
  hash_value ^= (hash_value << 4) & 0xffffffff
  hash_value = (hash_value + (hash_value >> 17)) & 0xffffffff
  hash_value ^= (hash_value << 25) & 0xffffffff
  hash_value = (hash_value + (hash_value >> 6)) & 0xffffffff

  return hash_value


class CacheAddress(object):
  """Class that contains a cache address.

  Attributes:
    block_number (int): block data file number.
    block_offset (int): offset within the block data file.
    block_size (int): block size.
    filename (str): name of the block data file.
    value (int): cache address.
  """
  FILE_TYPE_SEPARATE = 0
  FILE_TYPE_BLOCK_RANKINGS = 1
  FILE_TYPE_BLOCK_256 = 2
  FILE_TYPE_BLOCK_1024 = 3
  FILE_TYPE_BLOCK_4096 = 4

  _BLOCK_DATA_FILE_TYPES = [
      FILE_TYPE_BLOCK_RANKINGS,
      FILE_TYPE_BLOCK_256,
      FILE_TYPE_BLOCK_1024,
      FILE_TYPE_BLOCK_4096]

  _FILE_TYPE_DESCRIPTIONS = [
      u'Separate file',
      u'Rankings block file',
      u'256 byte block file',
      u'1024 byte block file',
      u'4096 byte block file']

  _FILE_TYPE_BLOCK_SIZES = [0, 36, 256, 1024, 4096]

  def __init__(self, cache_address):
    """Initializes a cache address object.

    Args:
      cache_address (int): cache address.
    """
    super(CacheAddress, self).__init__()
    self.block_number = None
    self.block_offset = None
    self.block_size = None
    self.filename = None
    self.value = cache_address

    if cache_address & 0x80000000:
      self.is_initialized = u'True'
    else:
      self.is_initialized = u'False'

    self.file_type = (cache_address & 0x70000000) >> 28
    if not cache_address == 0x00000000:
      if self.file_type == self.FILE_TYPE_SEPARATE:
        file_selector = cache_address & 0x0fffffff
        self.filename = u'f_{0:06x}'.format(file_selector)

      elif self.file_type in self._BLOCK_DATA_FILE_TYPES:
        file_selector = (cache_address & 0x00ff0000) >> 16
        self.filename = u'data_{0:d}'.format(file_selector)

        file_block_size = self._FILE_TYPE_BLOCK_SIZES[self.file_type]
        self.block_number = cache_address & 0x0000ffff
        self.block_size = (cache_address & 0x03000000) >> 24
        self.block_size *= file_block_size
        self.block_offset = 8192 + (self.block_number * file_block_size)

  def GetDebugString(self):
    """Retrieves a debug string of the cache address object.

    Return:
      str: debug string of the cache address object.
    """
    if self.file_type <= 4:
      file_type_description = self._FILE_TYPE_DESCRIPTIONS[self.file_type]
    else:
      file_type_description = u'Unknown'

    if self.value == 0x00000000:
      return u'0x{0:08x} (uninitialized)'.format(self.value)

    if self.file_type == 0:
      return (
          u'0x{0:08x} (initialized: {1:s}, file type: {2:s}, '
          u'filename: {3:s})').format(
              self.value, self.is_initialized, file_type_description,
              self.filename)

    # TODO: print reserved bits.
    return (
        u'0x{0:08x} (initialized: {1:s}, file type: {2:s}, '
        u'filename: {3:s}, block number: {4:d}, block offset: 0x{5:08x}, '
        u'block size: {6:d})').format(
            self.value, self.is_initialized, file_type_description,
            self.filename, self.block_number, self.block_offset,
            self.block_size)


class CacheEntry(object):
  """Class that contains a cache entry.

  Attributes:
    creation_time (int): creation time, in number of micro seconds since
        January 1, 1970, 00:00:00 UTC.
    hash (int): super fast hash of the key.
    key (byte): data of the key.
    next (int): cache address of the next cache entry.
    rankings_node (int): cache address of the rankings node.
  """

  def __init__(self):
    """Initializes a cache entry object."""
    super(CacheEntry, self).__init__()
    self.creation_time = None
    self.hash = None
    self.key = None
    self.next = None
    self.rankings_node = None


class IndexFile(object):
  """Class that contains an index file."""

  SIGNATURE = 0xc103cac3

  _FILE_HEADER = construct.Struct(
      u'chrome_cache_index_file_header',
      construct.ULInt32(u'signature'),
      construct.ULInt16(u'minor_version'),
      construct.ULInt16(u'major_version'),
      construct.ULInt32(u'number_of_entries'),
      construct.ULInt32(u'stored_data_size'),
      construct.ULInt32(u'last_created_file_number'),
      construct.ULInt32(u'unknown1'),
      construct.ULInt32(u'unknown2'),
      construct.ULInt32(u'table_size'),
      construct.ULInt32(u'unknown3'),
      construct.ULInt32(u'unknown4'),
      construct.ULInt64(u'creation_time'),
      construct.Padding(208))

  _LRU_DATA = construct.Struct(
      u'chrome_cache_index_file_lru_data',
      construct.Padding(8),
      construct.ULInt32(u'filled_flag'),
      construct.Array(5, construct.ULInt32(u'sizes')),
      construct.Array(5, construct.ULInt32(u'head_addresses')),
      construct.Array(5, construct.ULInt32(u'tail_addresses')),
      construct.ULInt32(u'transaction_address'),
      construct.ULInt32(u'operation'),
      construct.ULInt32(u'operation_list'),
      construct.Padding(28))

  def __init__(self, debug=False):
    """Initializes the index file object.

    Args:
      debug (Optional[bool]): True if debug information should be printed.
    """
    super(IndexFile, self).__init__()
    self._debug = debug
    self._file_object = None
    self._file_object_opened_in_object = False
    self.creation_time = None
    self.version = None
    self.index_table = {}

  def _ReadFileHeader(self):
    """Reads the file header.

    Raises:
      IOError: if the file header cannot be read.
    """
    if self._debug:
      print(u'Seeking file header offset: 0x{0:08x}'.format(0))

    self._file_object.seek(0, os.SEEK_SET)

    file_header_data = self._file_object.read(self._FILE_HEADER.sizeof())

    if self._debug:
      print(u'Index file header data:')
      print(hexdump.Hexdump(file_header_data))

    try:
      file_header = self._FILE_HEADER.parse(file_header_data)
    except construct.FieldError as exception:
      raise IOError(u'Unable to parse file header with error: {0:s}'.format(
          exception))

    signature = file_header.get(u'signature')

    if signature != self.SIGNATURE:
      raise IOError(u'Unsupported index file signature')

    self.version = u'{0:d}.{1:d}'.format(
        file_header.get(u'major_version'),
        file_header.get(u'minor_version'))

    if self.version not in [u'2.0', u'2.1']:
      raise IOError(u'Unsupported index file version: {0:s}'.format(
          self.version))

    self.creation_time = file_header.get(u'creation_time')

    if self._debug:
      print(u'Signature\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(signature))

      print(u'Version\t\t\t\t\t\t\t\t\t: {0:s}'.format(self.version))

      print(u'Number of entries\t\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'number_of_entries')))

      print(u'Stored data size\t\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'stored_data_size')))

      print(u'Last created file number\t\t\t\t\t\t: f_{0:06x}'.format(
          file_header.get(u'last_created_file_number')))

      print(u'Unknown1\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          file_header.get(u'unknown1')))

      print(u'Unknown2\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          file_header.get(u'unknown2')))

      print(u'Table size\t\t\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'table_size')))

      print(u'Unknown3\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          file_header.get(u'unknown3')))

      print(u'Unknown4\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          file_header.get(u'unknown4')))

      date_string = (
          datetime.datetime(1601, 1, 1) +
          datetime.timedelta(microseconds=self.creation_time))

      print(u'Creation time\t\t\t\t\t\t\t\t: {0!s} (0x{1:08x})'.format(
          date_string, self.creation_time))

      print(u'')

  def _ReadLruData(self):
    """Reads the LRU data."""
    lru_data = self._file_object.read(self._LRU_DATA.sizeof())

    if self._debug:
      print(u'Index file LRU data:')
      print(hexdump.Hexdump(lru_data))

    try:
      index_file_lru = self._LRU_DATA.parse(lru_data)
    except construct.FieldError as exception:
      raise IOError(u'Unable to parse LRU data with error: {0:s}'.format(
          exception))

    if self._debug:
      print(u'Filled flag\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          index_file_lru.get(u'filled_flag')))

      for value in index_file_lru.get(u'sizes'):
        print(u'Size\t\t\t\t\t\t\t\t\t: {0:d}'.format(value))

      cache_address_index = 0
      for value in index_file_lru.get(u'head_addresses'):
        cache_address = CacheAddress(value)
        print(u'Head address: {0:d}\t\t\t\t\t\t\t\t: {1:s}'.format(
            cache_address_index, cache_address.GetDebugString()))
        cache_address_index += 1

      cache_address_index = 0
      for value in index_file_lru.get(u'tail_addresses'):
        cache_address = CacheAddress(value)
        print(u'Tail address: {0:d}\t\t\t\t\t\t\t\t: {1:s}'.format(
            cache_address_index, cache_address.GetDebugString()))
        cache_address_index += 1

      cache_address = CacheAddress(index_file_lru.get(u'transaction_address'))
      print(u'Transaction address\t\t\t\t\t\t\t: {0:s}'.format(
          cache_address.GetDebugString()))

      print(u'Operation\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          index_file_lru.get(u'operation')))

      print(u'Operation list\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          index_file_lru.get(u'operation_list')))

      print(u'')

  def _ReadIndexTable(self):
    """Reads the index table."""
    cache_address_index = 0
    cache_address_data = self._file_object.read(4)

    while len(cache_address_data) == 4:
      value = construct.ULInt32(u'cache_address').parse(cache_address_data)

      if value:
        cache_address = CacheAddress(value)

        if self._debug:
          print(u'Cache address: {0:d}\t\t\t\t\t\t\t: {1:s}'.format(
              cache_address_index, cache_address.GetDebugString()))

        self.index_table[cache_address_index] = cache_address

      cache_address_index += 1
      cache_address_data = self._file_object.read(4)

    if self._debug:
      print(u'')

  def Close(self):
    """Closes the index file."""
    if self._file_object_opened_in_object:
      self._file_object.close()
    self._file_object = None

  def Open(self, filename):
    """Opens the index file.

    Args:
      filename (str): path of the file.
    """
    self._file_object = open(filename, 'rb')
    self._file_object_opened_in_object = True
    self._ReadFileHeader()
    self._ReadLruData()
    self._ReadIndexTable()

  def OpenFileObject(self, file_object):
    """Opens the index file-like object.

    Args:
      file_object (file): file-like object.
    """
    self._file_object = file_object
    self._file_object_opened_in_object = False
    self._ReadFileHeader()
    self._ReadLruData()
    self._ReadIndexTable()


class DataBlockFile(object):
  """Class that contains a data block file."""

  SIGNATURE = 0xc104cac3

  # TODO: update emtpy, hints, updating and user.
  _FILE_HEADER = construct.Struct(
      u'chrome_cache_data_file_header',
      construct.ULInt32(u'signature'),
      construct.ULInt16(u'minor_version'),
      construct.ULInt16(u'major_version'),
      construct.ULInt16(u'file_number'),
      construct.ULInt16(u'next_file_number'),
      construct.ULInt32(u'block_size'),
      construct.ULInt32(u'number_of_entries'),
      construct.ULInt32(u'maximum_number_of_entries'),
      construct.Array(4, construct.ULInt32(u'emtpy')),
      construct.Array(4, construct.ULInt32(u'hints')),
      construct.ULInt32(u'updating'),
      construct.Array(5, construct.ULInt32(u'user')),
      construct.Array(2028, construct.ULInt32(u'allocation_bitmap')))

  _CACHE_ENTRY = construct.Struct(
      u'chrome_cache_entry',
      construct.ULInt32(u'hash'),
      construct.ULInt32(u'next_address'),
      construct.ULInt32(u'rankings_node_address'),
      construct.ULInt32(u'reuse_count'),
      construct.ULInt32(u'refetch_count'),
      construct.ULInt32(u'state'),
      construct.ULInt64(u'creation_time'),
      construct.ULInt32(u'key_size'),
      construct.ULInt32(u'long_key_address'),
      construct.Array(4, construct.ULInt32(u'data_stream_sizes')),
      construct.Array(4, construct.ULInt32(u'data_stream_addresses')),
      construct.ULInt32(u'flags'),
      construct.Padding(16),
      construct.ULInt32(u'self_hash'),
      construct.Array(160, construct.UBInt8(u'key')))

  def __init__(self, debug=False):
    """Initializes the data block file object.

    Args:
      debug (Optional[bool]): True if debug information should be printed.
    """
    super(DataBlockFile, self).__init__()
    self._debug = debug
    self._file_object = None
    self._file_object_opened_in_object = False
    self.creation_time = None
    self.block_size = None
    self.number_of_entries = None
    self.version = None

  def _ReadFileHeader(self):
    """Reads the file header.

    Raises:
      IOError: if the file header cannot be read.
    """
    if self._debug:
      print(u'Seeking file header offset: 0x{0:08x}'.format(0))

    self._file_object.seek(0, os.SEEK_SET)

    file_header_data = self._file_object.read(self._FILE_HEADER.sizeof())

    if self._debug:
      print(u'Data block file header data:')
      print(hexdump.Hexdump(file_header_data))

    try:
      file_header = self._FILE_HEADER.parse(file_header_data)
    except construct.FieldError as exception:
      raise IOError(u'Unable to parse file header with error: {0:s}'.format(
          exception))

    signature = file_header.get(u'signature')

    if signature != self.SIGNATURE:
      raise IOError(u'Unsupported data block file signature')

    self.version = u'{0:d}.{1:d}'.format(
        file_header.get(u'major_version'),
        file_header.get(u'minor_version'))

    if self.version not in [u'2.0', u'2.1']:
      raise IOError(u'Unsupported data block file version: {0:s}'.format(
          self.version))

    self.version = u'{0:d}.{1:d}'.format(
        file_header.get(u'major_version'), file_header.get(u'minor_version'))

    self.block_size = file_header.get(u'block_size')
    self.number_of_entries = file_header.get(u'number_of_entries')

    if self._debug:
      print(u'Signature\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(signature))

      print(u'Version\t\t\t\t\t\t\t\t\t: {0:s}'.format(self.version))

      print(u'File number\t\t\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'file_number')))

      print(u'Next file number\t\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'next_file_number')))

      print(u'Block size\t\t\t\t\t\t\t\t: {0:d}'.format(self.block_size))

      print(u'Number of entries\t\t\t\t\t\t\t: {0:d}'.format(
          self.number_of_entries))

      print(u'Maximum number of entries\t\t\t\t\t\t: {0:d}'.format(
          file_header.get(u'maximum_number_of_entries')))

      # TODO: print emtpy, hints, updating and user.

      block_number = 0
      block_range_start = 0
      block_range_end = 0
      in_block_range = False
      for value_32bit in file_header.get(u'allocation_bitmap'):
        for unused_bit in range(0, 32):
          if value_32bit & 0x00000001:
            if not in_block_range:
              block_range_start = block_number
              block_range_end = block_number
              in_block_range = True

            block_range_end += 1

          elif in_block_range:
            in_block_range = False

            if self._debug:
              print(u'Block range\t: {0:d} - {1:d} ({2:d})'.format(
                  block_range_start, block_range_end,
                  block_range_end - block_range_start))

          value_32bit >>= 1
          block_number += 1

      print(u'')

  def ReadCacheEntry(self, block_offset):
    """Reads a cache entry.

    Args:
      block_offset (int): offset of the block that contains the cache entry.
    ""
    if self._debug:
      print(u'Seeking cache entry offset: 0x{0:08x}'.format(block_offset))

    self._file_object.seek(block_offset, os.SEEK_SET)

    cache_entry_data = self._file_object.read(self._CACHE_ENTRY.sizeof())

    if self._debug:
      print(u'Data block file cache entry data:')
      print(hexdump.Hexdump(cache_entry_data))

    try:
      cache_entry_struct = self._CACHE_ENTRY.parse(cache_entry_data)
    except construct.FieldError as exception:
      raise IOError(u'Unable to parse cache entry with error: {0:s}'.format(
          exception))

    cache_entry = CacheEntry()

    cache_entry.hash = cache_entry_struct.get(u'hash')

    cache_entry.next = CacheAddress(cache_entry_struct.get(u'next_address'))
    cache_entry.rankings_node = CacheAddress(cache_entry_struct.get(
        u'rankings_node_address'))

    cache_entry.creation_time = cache_entry_struct.get(u'creation_time')

    byte_array = cache_entry_struct.get(u'key')
    byte_string = b''.join(map(chr, byte_array))
    cache_entry.key, _, _ = byte_string.partition(b'\x00')

    if self._debug:
      print(u'Hash\t\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(cache_entry.hash))

      print(u'Next address\t\t\t\t\t\t\t\t: {0:s}'.format(
          cache_entry.next.GetDebugString()))

      print(u'Rankings node address\t\t\t\t\t\t\t: {0:s}'.format(
          cache_entry.rankings_node.GetDebugString()))

      print(u'Reuse count\t\t\t\t\t\t\t\t: {0:d}'.format(
          cache_entry_struct.get(u'reuse_count')))

      print(u'Refetch count\t\t\t\t\t\t\t\t: {0:d}'.format(
          cache_entry_struct.get(u'refetch_count')))

      print(u'State\t\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          cache_entry_struct.get(u'state')))

      date_string = (datetime.datetime(1601, 1, 1) +
                     datetime.timedelta(microseconds=cache_entry.creation_time))

      print(u'Creation time\t\t\t\t\t\t\t\t: {0!s} (0x{1:08x})'.format(
          date_string, cache_entry.creation_time))

      for value in cache_entry_struct.get(u'data_stream_sizes'):
        print(u'Data stream size\t\t\t\t\t\t\t: {0:d}'.format(value))

      cache_address_index = 0
      for value in cache_entry_struct.get(u'data_stream_addresses'):
        cache_address = CacheAddress(value)
        print(u'Data stream address: {0:d}\t\t\t\t\t\t\t: {1:s}'.format(
            cache_address_index, cache_address.GetDebugString()))
        cache_address_index += 1

      print(u'Flags\t\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          cache_entry_struct.get(u'flags')))

      print(u'Self hash\t\t\t\t\t\t\t\t: 0x{0:08x}'.format(
          cache_entry_struct.get(u'self_hash')))

      try:
        cache_entry_key = cache_entry.key.decode(u'ascii')
      except UnicodeDecodeError:
        logging.warning((
            u'Unable to decode cache entry key at cache address: '
            u'0x{0:08x}. Characters that cannot be decoded will be '
            u'replaced with "?" or "\\ufffd".').format(cache_address.value))
        cache_entry_key = cache_entry.key.decode(u'ascii', errors=u'replace')

      print(u'Key\t\t\t\t\t\t\t\t\t: {0:s}'.format(cache_entry_key))

      # TODO: calculate and verify hash.

      print(u'')

    return cache_entry

  def Close(self):
    """Closes the data block file."""
    if self._file_object_opened_in_object:
      self._file_object.close()
    self._file_object = None

  def Open(self, filename):
    """Opens the data block file.

    Args:
      filename (str): path of the file.
    """
    self._file_object = open(filename, 'rb')
    self._file_object_opened_in_object = True
    self._ReadFileHeader()

  def OpenFileObject(self, file_object):
    """Opens the data block file.

    Args:
      file_object (file): file-like object.
    """
    self._file_object = file_object
    self._file_object_opened_in_object = False
    self._ReadFileHeader()


def Main():
  """The main program function.

  Returns:
    bool: True if successful or False if not.
  """
  argument_parser = argparse.ArgumentParser(description=(
      u'Extracts information from Chrome Cache files.'))

  argument_parser.add_argument(
      u'-d', u'--debug', dest=u'debug', action=u'store_true', default=False,
      help=u'enable debug output.')

  argument_parser.add_argument(
      u'source', nargs=u'?', action=u'store', metavar=u'PATH',
      default=None, help=u'path of the Chrome Cache file(s).')

  options = argument_parser.parse_args()

  if not options.source:
    print(u'Source file missing.')
    print(u'')
    argument_parser.print_help()
    print(u'')
    return False

  logging.basicConfig(
      level=logging.INFO, format=u'[%(levelname)s] %(message)s')

  if os.path.isdir(options.source):
    index_file_path = os.path.join(options.source, u'index')
    if not os.path.exists(index_file_path):
      logging.error(u'Missing index file: {0:s}'.format(index_file_path))
      return False

    index_file = IndexFile(debug=options.debug)
    index_file.Open(index_file_path)

    data_block_files = {}
    have_all_data_block_files = True
    for cache_address in iter(index_file.index_table.values()):
      if cache_address.filename not in data_block_files:
        data_block_file_path = os.path.join(
            options.source, cache_address.filename)

        if not os.path.exists(data_block_file_path):
          logging.error(u'Missing data block file: {0:s}'.format(
              data_block_file_path))
          have_all_data_block_files = False

        else:
          data_block_file = DataBlockFile(debug=options.debug)
          data_block_file.Open(data_block_file_path)

          data_block_files[cache_address.filename] = data_block_file

    if have_all_data_block_files:
      # TODO: read the cache entries from the data block files
      for cache_address in iter(index_file.index_table.values()):
        cache_address_chain_length = 0
        while cache_address.value != 0x00000000:
          if cache_address_chain_length >= 64:
            logging.error(
                u'Maximum allowed cache address chain length reached.')
            break

          data_file = data_block_files.get(cache_address.filename, None)
          if not data_file:
            logging.warning(
                u'Cache address: 0x{0:08x} missing filename.'.format(
                    cache_address.value))
            break

          # print(u'Cache address\t: {0:s}'.format(
          #     cache_address.GetDebugString()))
          cache_entry = data_file.ReadCacheEntry(cache_address.block_offset)

          try:
            cache_entry_key = cache_entry.key.decode(u'ascii')
          except UnicodeDecodeError:
            logging.warning((
                u'Unable to decode cache entry key at cache address: '
                u'0x{0:08x}. Characters that cannot be decoded will be '
                u'replaced with "?" or "\\ufffd".').format(cache_address.value))
            cache_entry_key = cache_entry.key.decode(
                u'ascii', errors=u'replace')

          # TODO: print(u'Url\t\t: {0:s}'.format(cache_entry_key))
          _ = cache_entry_key

          date_string = (datetime.datetime(1601, 1, 1) + datetime.timedelta(
              microseconds=cache_entry.creation_time))

          # print(u'Creation time\t: {0!s}'.format(date_string))

          # print(u'')

          print(u'{0!s}\t{1:s}'.format(date_string, cache_entry.key))

          cache_address = cache_entry.next
          cache_address_chain_length += 1

    for data_block_file in iter(data_block_files.values()):
      data_block_file.Close()

    index_file.Close()

    if not have_all_data_block_files:
      return False

  else:
    file_object = open(options.source, 'rb')

    signature_data = file_object.read(4)
    signature = construct.ULInt32(u'signature').parse(signature_data)

    if signature == IndexFile.SIGNATURE:
      index_file = IndexFile(debug=options.debug)
      index_file.Read(file_object)
      index_file.OpenFileObject(file_object)
      index_file.Close()

    elif signature == DataBlockFile.SIGNATURE:
      data_block_file = DataBlockFile(debug=options.debug)
      data_block_file.OpenFileObject(file_object)
      data_block_file.Close()

    file_object.close()

  return True


if __name__ == '__main__':
  if not Main():
    sys.exit(1)
  else:
    sys.exit(0)
