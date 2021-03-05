#!/usr/bin/env python3

import os
import sys
import tarfile
import json
import uuid
from datetime import datetime
from pathlib import Path
from ftplib import FTP_TLS

import yaml
import pymysql
import docker

from ansible.module_utils.basic import AnsibleModule
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto import Random

ANSIBLE_METADATA = {
    'metadata_version': '0.1',
    'status': ['preview'],
    'supported_by': 'Alon Team'
}

DOCUMENTATION = '''
---
module: backup_restore
short_description: Module for controlling CEE backups
description:
     - A module for managing CEE backups including create, restore,
       list or delete oprations
options:
  action:
    description:
      - The action the module should take for the backups
    required: True
    type: str
    choices:
      - backup
      - restore
      - list
      - delete
      - export
      - import
      - show
  location:
    description:
      - Directory path where to store the backups or restore from
    required: True
    type: str
  backup_db_info:
    description:
      - A dictionary containing all information needed to cennt to
        backup database. Example structure:
        {
            'host': 'mariadb-server',
            'port': 3306,
            'user': 'mariadb_backup_database_user',
            'password': 'mariadb_backup_database_password',
        }
    required: True
    type: dict
  backup_mode:
    description:
      - Mode of backup that should be taken, it depends on backup domain and
        data type to backup, required for action=backup or action=restore
    required: False
    type: str
    default: directory
    choices:
      - directory
      - mariadb
  backupname:
    description:
      - An unique backup name for restore, export or delete operations
    required: False
    type: str
  backup_type:
    description:
      - Type of backup that should be taken, full or incremental, valid only
        for mysql mode
    required: False
    type: str
    default: full
    choices:
      - full
      - incremental
  append:
    description:
      - backup_id of of the backup set where current backup should be appended
        to. Useful for mutiple backup modes when directory and mariadb backups
        should be taken.
    required: False
    type: str
  backup_options:
    description:
      - A dict containing common params, it can be used for passing additional
        backup parameters like directory paths or backup domain
    required: False
    type: dict
    default: dict()
  query:
    description:
      - Regex allowing to select single or multiple backups for delete,
        list or export operations
    required: False
    type: str
  config_file:
    description:
      - Path to YAML configuration file describing backup and restore
        parameters
    required: False
    type: str
  append:
    description:
      - backup_id of existing backup to append new one. When multiple backup
        modes are used for particular backup you can add different backup mode
        to existing backup to create backup set
    required: False
    type: str
author: Alon Team

return:
  dict() - containing information about result status of backup or restore
           operations as well as its status (if possible). In case of list
           opration also return list of available backups and their types
'''

EXAMPLES = '''
'''

RETURN = '''
'''


def get_db_info(path_base):
    """
    Helper function for retrieving information about backup database.

    TODO: This will be change in future. All needed information for
    accessing backup database will be stored in separate database.
    """

    path_all = os.path.join(
        "/", path_base, "orchestrator", "ansible", "group_vars", "all.yml"
    )
    path_networks = os.path.join(
        "/", path_base, "config", "networks.yaml"
    )
    path_config = os.path.join(
            "/", "etc", "cee", "backups.yml"
        )
    path_pass = os.path.join(
        "/", path_base, "system", "lcm", "passwords.yml"
    )

    paths = (path_all, path_networks, path_config, path_pass)
    all_vars = ()
    for file in paths:
        with open(file) as f:
            all_vars += (yaml.load(f, Loader=yaml.FullLoader),)

    db_port = all_vars[0]['database_port']
    lcm_vip_ip = all_vars[
        1
    ]['networks'][0]['subnets'][0]['vips'][0]['address']
    db_pass = all_vars[3]['backup_db_password']
    cfg = all_vars[2]
    cfg['backup_db_credentials'].update(
        {'host': lcm_vip_ip, 'port': db_port, 'password': db_pass}
    )
    return cfg['backup_db_credentials']


class Cryptography():
    """
    This class is using the Cipher Block Chaining (CBC) mode.
    It is a confidentiality mode whose encryption process features
    the combining (“chaining”) of the plaintext blocks with the previous
    ciphertext blocks.
    """

    def __init__(self, password: str,
                 sourceFile: str, targetFile: str) -> None:
        """
        password is use to create key, a hash object.
        The secret key is use in the symmetric cipher.

        Example use:
        cipher1 = Cryptography(
            'jrslw PL zbaw', '/img/cee-P1A14.iso', './enc/enc.iso'
            )
        cipher1.encrypt()

        cipher2 = Cryptography(
            'jrslw PL zbaw', './enc/enc.iso', './img/cee-P1A14.iso'
            )
        cipher2.decrypt()
        """
        self.__key = SHA256.new(password.encode('utf-8')).digest()
        del password
        self.sourceFile = Path(sourceFile).absolute()
        self.targetFile = Path(targetFile).absolute()
        self.CHUNKSIZE = 64 * 1024

    def encrypt(self) -> None:
        """
        Encrypt data with the key set at initialization.

        The CBC mode requires an IV to combine with the first plaintext block.
        IV - The initialization vector to use for encryption or decryption.
        For MODE_CBC it must be 16 bytes long.
        """
        plainText = str(self.sourceFile.stat().st_size).zfill(16)
        IV = Random.new().read(16)

        encryptor = AES.new(self.__key, AES.MODE_CBC, IV)

        with open(self.sourceFile, 'rb') as inFile:
            with open(self.targetFile, 'wb') as outFile:
                outFile.write(plainText.encode('utf-8'))
                outFile.write(IV)

                while True:
                    chunk = inFile.read(self.CHUNKSIZE)
                    if len(chunk) == 0:
                        break
                    elif len(chunk) % 16 != 0:
                        size_to_end = 16 - (len(chunk) % 16)
                        chunk += b' ' * size_to_end

                    outFile.write(encryptor.encrypt(chunk))

        print(f"\tData encrypted: '{self.targetFile}'")

    def decrypt(self) -> None:
        """
        Decrypt data with the key set at initialization.

        The CBC mode requires an IV to combine with the first plaintext block.
        IV - The initialization vector to use for encryption or decryption.
        For MODE_CBC it must be 16 bytes long.
        """
        with open(self.sourceFile, 'rb') as inFile:
            filesize = int(inFile.read(16))  # plaintext
            IV = inFile.read(16)

            decryptor = AES.new(self.__key, AES.MODE_CBC, IV)

            with open(self.targetFile, 'wb') as outFile:
                while True:
                    chunk = inFile.read(self.CHUNKSIZE)
                    if len(chunk) == 0:
                        break
                    outFile.write(decryptor.decrypt(chunk))
                    outFile.truncate(filesize)
        print(f"\tData decrypted: '{self.targetFile}'")


class Backup_db():
    def __init__(
            self,
            src: dict = None,
            config_path: str = None,
            work_dir: str = None,
            ) -> None:
        '''Connects to database. Add src(dict) parameter to provide \
            connection details:
        Syntax: src = {'host': <HOST>, 'port': <PORT>, 'user': <USER>, \
            'password': <PWD>}
        Schema backup_schema will be created if not exists'''

        if src is None:
            if config_path is not None:
                with open(config_path) as config_file:
                    cfg = yaml.load(config_file.read(), Loader=yaml.Loader)
                    src = cfg['backup_db_info']
            elif work_dir is not None:
                src = get_db_info(work_dir)
            else:
                raise TypeError(
                    "No arguments were given. "
                    "To access database You need to provide: "
                    "src = {'host': <HOST>, 'port': <PORT>,"
                    " 'user': <USER>, 'password': <PWD>}"
                )

        self.connection = pymysql.connect(host=src.get('host'),
                                          port=int(src.get('port')),
                                          user=src.get('user'),
                                          password=src.get('password'))
        self.cursor = self.connection.cursor()
        if self.cursor.execute('SHOW DATABASES LIKE \'backup_schema\';') == 0:
            self.cursor.execute('CREATE DATABASE backup_schema;')
            self.connection.select_db('backup_schema')
            self.purge()
        self.connection.select_db('backup_schema')
        if self.connection.query("show tables;") != 3:
            self.purge()

    def purge(self, keep_logs: bool = False) -> None:
        '''Purging of database, ALL DATA WILL BE DELETED PERMANENTLY'''

        self.cursor.execute('''DROP TABLE IF EXISTS backups;''')
        self.cursor.execute('''CREATE TABLE backups (entry_uuid CHAR(32) \
            primary key, name TINYTEXT, domain VARCHAR(20), type VARCHAR(20), \
            parent CHAR(32), user_comments TEXT, created DATETIME, \
            status VARCHAR(20), exported DATETIME, export_location \
            TEXT, imported DATETIME, import_location TEXT, \
            schedule_id TEXT);''')

        self.cursor.execute('''DROP TABLE IF EXISTS backup_files;''')
        self.cursor.execute('''CREATE TABLE backup_files (entryfile_uuid \
            CHAR(32) primary key, entry_uuid CHAR(32), \
            mode VARCHAR(20), restore_path TEXT, location \
            TEXT, filename TEXT, encrypted BOOLEAN, checksum CHAR(32));''')

        if keep_logs is False:
            self.cursor.execute('''DROP TABLE IF EXISTS log;''')
            self.cursor.execute('''CREATE TABLE log (log_uuid CHAR(32) \
                primary key, entry_uuid CHAR(32), started DATETIME, \
                finished DATETIME, status VARCHAR(20), \
                operation VARCHAR(20));''')

        self.connection.commit()

    def add_entry(self, name: str, domain: str, type: str,
                  parent: str, created: datetime,
                  files_list: list, started: datetime, finished: datetime,
                  status: str, comments: str = None, exported: datetime =
                  None, export_location: str = None, imported: datetime = None,
                  import_location: str = None,
                  schedule_id: str = None) -> str(32):
        '''Creation of new entry, logged.
        Parameters:
        name: str
        domain: str
        type: str
        parent: str(32)
        created: datetime
        files_list: list of dicts, syntax: [{'entryfile_uuid': <str(32)>, \
            'mode': <str>, 'restore_path':\
            <str>, 'location': <str>, 'filename': <str>, 'encrypted': <bool>, \
            'checksum': <str(32)>},{...}]
        started: datetime
        finished: datetime
        status: str
        comments: str, optional
        exported: datetime, optional
        export_location: str, optional
        imported: datetime, optional
        import_location: str, optional
        schedule_id: str, optional
        returns entry_uuid'''

        entry_uuid = str(uuid.uuid4()).replace('-', '')
        self.cursor.execute('''INSERT INTO backups (entry_uuid, name, domain, \
            type, parent, user_comments, created, status, exported, \
            export_location, imported, import_location, schedule_id) \
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                            (entry_uuid, name, domain, type, parent, comments,
                             created, status, exported, export_location,
                             imported, import_location, schedule_id))

        for f in files_list:
            entryfile_uuid = str(uuid.uuid4()).replace('-', '')
            self.cursor.execute('''INSERT INTO backup_files (entryfile_uuid, \
                entry_uuid, mode, restore_path, location, \
                filename, encrypted, checksum) VALUES (%s, %s, %s, \
                %s, %s, %s, %s, %s )''',
                                (entryfile_uuid, entry_uuid,
                                 f.get("mode"),
                                 f.get("restore_path"), f.get("location"),
                                 f.get("filename"), f.get("encrypted"),
                                 f.get("checksum")))

        if imported is None:
            self.log_operation(entry_uuid, started, finished,
                               'SUCCESS', 'backup')

        self.connection.commit()
        print('Backup UUID: ', entry_uuid)
        return entry_uuid

    def add_file(self, entry_uuid: str(32), new_file: dict) -> str(32):
        '''Alters specific entry with new file.
        Parameters:
        entry_uuid: str(32)
        new_file: dict (syntax: {
            'mode': <str>, 'restore_path':\
            <str>, 'location': <str>, 'filename': <str>, 'encrypted': <bool>, \
            'checksum': <str(32)>}
        finished: datetime
        returns entryfile_uuid'''
        started = datetime.now()
        entryfile_uuid = str(uuid.uuid4()).replace('-', '')
        self.cursor.execute('''INSERT INTO backup_files (entryfile_uuid, \
                entry_uuid, mode, restore_path, location, \
                filename, encrypted, checksum) VALUES (%s, %s, \
                %s, %s, %s, %s, %s, %s )''',
                            (entryfile_uuid, entry_uuid,
                             new_file.get("mode"),
                             new_file.get("restore_path"),
                             new_file.get("location"),
                             new_file.get("filename"),
                             new_file.get("encrypted"),
                             new_file.get("checksum")))
        finished = datetime.now()
        self.log_operation(entry_uuid, started, finished, 'SUCCESS',
                           'add file')
        self.connection.commit()
        print('Added file to ', entry_uuid)
        return entryfile_uuid

    def change_status(self, entry_uuid: str(32), status: str) -> None:
        '''Alters specific entry with new status.
        Parameters:
        entry_uuid: str(32)
        status: str'''
        self.cursor.execute('''UPDATE backups SET status = %s \
                            WHERE entry_uuid = %s''', (status, entry_uuid,))
        self.connection.commit()

    def remove_file(self, entryfile_uuid: str(32)) -> None:
        '''Deleting file from backup.
        Parameter:
        entryfile_uuid: str(32)'''
        started = datetime.now()
        entry_uuid = self.cursor.execute('''SELECT entry_uuid FROM \
                                         backup_files WHERE \
                                         entryfile_uuid = \
                                         %s''', (entryfile_uuid,))
        self.cursor.execute('''DELETE FROM backup_files WHERE \
                            entryfile_uuid = \
                            %s''', (entryfile_uuid,))
        finished = datetime.now()
        self.log_operation(entry_uuid, started, finished, 'SUCCESS',
                           'remove file')

        self.connection.commit()

    def log_operation(self, entry_uuid: str(32), started: datetime, finished:
                      datetime, status: str, operation: str) -> str(32):
        '''Logging action of restoration
        Parameters:
        entry_uuid: str(32)
        started: datetime
        finished: datetime
        status: str
        operation: str
        returns log_uuid'''

        log_uuid = str(uuid.uuid4()).replace('-', '')
        self.cursor.execute('''INSERT INTO log (log_uuid, entry_uuid, \
            started, finished, status, operation) VALUES (%s, %s, %s, %s, %s, \
            %s)''', (log_uuid, entry_uuid, started, finished, status,
                     operation))

        self.connection.commit()
        print('Log UUID: ', log_uuid)
        return log_uuid

    def backup_list(self) -> list:
        '''Returning list of Backups'''
        self.cursor.execute('''SHOW COLUMNS FROM backups''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backups''')
        data = self.cursor.fetchall()
        return self.format_output(columns, data)

    def backup_show(self, entry_uuid: str(32)) -> dict:
        '''Returning general info on specific Backup
        Parameter:
        entry_uuid: str(32)'''
        self.cursor.execute('''SHOW COLUMNS FROM backups''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backups WHERE entry_uuid=%s''',
                            (entry_uuid,))
        data = self.cursor.fetchall()
        main_data = self.format_output(columns, data)
        self.cursor.execute('''SHOW COLUMNS FROM backup_files''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backup_files WHERE entry_uuid = \
            %s''', (main_data[0]['entry_uuid'],))
        data = self.cursor.fetchall()
        main_data[0]['files_list'] = self.format_output(columns, data)
        return main_data[0]

    def get_backup_files(self, entry_uuid: str) -> list:
        '''Return list of files for given backup UUID
        Parameters:
        entry_uuid: str'''
        backup_info = self.backup_show(entry_uuid)
        return backup_info["files_list"]

    def get_backup_filenames(self, backup_name: str) -> list:
        '''Return list of files names in backup
        Parameters:
        backup_name: str'''
        self.cursor.execute('''SELECT entry_uuid FROM backups WHERE name=%s''',
                            (backup_name,))
        entry_uuid = self.cursor.fetchall()
        self.cursor.execute('''SELECT filename FROM backup_files WHERE \
            entry_uuid = %s''', (entry_uuid,))
        data = self.cursor.fetchall()
        result_list = [file[0] if file else None for file in data]
        return result_list

    def get_backup_uuid(self, backup_name: str) -> str:
        '''Return backup UUID for given backup name
        Parameters:
        backup_name: str'''
        self.cursor.execute('''SHOW COLUMNS FROM backups''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backups WHERE name=%s''',
                            (backup_name,))
        data = self.cursor.fetchall()
        main_data = self.format_output(columns, data)
        try:
            return main_data[0]["entry_uuid"]
        except IndexError:
            return None
        except KeyError:
            return None
        except ValueError:
            return None

    def get_file_uuid(self, backup_name: str, filename: str) -> str:
        '''Return backupfile UUID for given backup name and filename
        Parameters:
        backup_name: str
        filename: str'''
        self.cursor.execute('''SHOW COLUMNS FROM backup_files''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backup_files WHERE \
                            entry_uuid=%s AND filename=%s''',
                            (self.get_backup_uuid(backup_name), filename))
        data = self.cursor.fetchall()
        main_data = self.format_output(columns, data)
        return main_data[0]["entryfile_uuid"]

    def get_newest_backupname(self, clustername: str,
                              type_bckp: str = 'full') -> str:
        '''Returning newest backup for specified clustername and type
        Parameter:
        clustername: str
        type_bckp: str'''
        self.cursor.execute('''SHOW columns FROM backups''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backups \
                            WHERE type=%s AND domain=%s \
                            ORDER BY created DESC LIMIT 1''',
                            (type_bckp, clustername))
        data = self.cursor.fetchall()
        main_data = self.format_output(columns, data)
        if main_data:
            return main_data[0]['name']
        else:
            return ''

    def count_incrementals(self, clustername: str) -> int:
        '''Counts how many incremental backups were created
        after newest full backup
        Parameter:
        clustername: str'''
        full_bckpname = self.get_newest_backupname(clustername, 'full')
        if not full_bckpname:
            return -1
        self.cursor.execute('''SELECT COUNT(DISTINCT name) FROM backups \
                            WHERE type='incremental' AND domain=%s \
                            AND parent=%s''',
                            (clustername, full_bckpname))
        incr_bckp_count = self.cursor.fetchall()
        self.connection.commit()
        return incr_bckp_count[0][0]

    def get_incrementals(self, clustername: str, fullbackup: str) -> list:
        self.cursor.execute('''SELECT name FROM backups WHERE \
                           type='incremental' AND domain=%s AND \
                           parent=%s''', (clustername, fullbackup))
        data = self.cursor.fetchall()
        incremental_list = [item for sublist in data for item in sublist]
        return incremental_list

    def get_oldest_full_backupname(self, clustername: str) -> str:
        '''Returning latest backup for specified clustername and type
        Parameter:
        clustername: str
        type_bckp: str'''
        self.cursor.execute('''SHOW columns FROM backups''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM backups \
                            WHERE type="full" AND domain=%s \
                            ORDER BY created ASC LIMIT 1''',
                            (clustername))
        data = self.cursor.fetchall()
        main_data = self.format_output(columns, data)
        if main_data:
            return main_data[0]['name']
        else:
            return ''

    def count_full_backups(self, clustername: str) -> int:
        '''Counts how many full backups were created
        includin newest backup, and if count bigger than
        config number delete latest
        Parameter:
        clustername: str'''
        self.cursor.execute('''SELECT COUNT(DISTINCT name) FROM backups \
                            WHERE type="full" AND domain=%s''',
                            (clustername))
        full_bckp_count = self.cursor.fetchall()
        self.connection.commit()
        return full_bckp_count[0][0]

    def delete_entry(self, entry_uuid: str(32)) -> None:
        '''Deleting backup and child backup files entries from database, \
            this cannot be undone.
        Parameter:
        entry_uuid: str(32)'''
        started = datetime.now()
        self.cursor.execute('''DELETE FROM backups WHERE entry_uuid = %s''',
                            (entry_uuid,))
        self.cursor.execute('''DELETE FROM backup_files WHERE entry_uuid = \
                            %s''', (entry_uuid,))

        finished = datetime.now()
        status = 'SUCCESS'
        self.log_operation(entry_uuid, started, finished, status, 'delete')

        self.connection.commit()

    def rebuild_from_metadata(self, location: str):
        self.purge(keep_logs=True)
        for filename in os.listdir(location):
            if filename.endswith(".json"):
                with open(f"{location}/{filename}", 'r') as jsonfile:
                    metadata = jsonfile.read()
                    self.import_entry(metadata)

    def export_metadata(self, entry_uuid: str(32)) -> str:
        '''Returns JSON string with all data related to demanded entry.
        Parameter:
        entry_uuid: str(32)'''
        metadata = self.backup_show(entry_uuid)
        return json.dumps(metadata, default=str)

    def export_entry(self, entry_uuid: str(32), export_location: str,
                     started: datetime, finished: datetime,
                     status: str) -> None:
        '''Alters specific entry with export_location and logs the event.
        Parameters:
        entry_uuid: str(32)
        export_location: str
        started: datetime
        finished: datetime
        status: str'''
        self.cursor.execute('''UPDATE backups SET exported = %s, \
            export_location = %s WHERE entry_uuid = \
            %s''', (finished, export_location, entry_uuid,))
        self.log_operation(entry_uuid, started, finished, status, 'export')
        self.connection.commit()
        print('Exported ', entry_uuid)
        return None

    def import_entry(self, metadata: str, import_location: str = None,
                     started: datetime = None, finished: datetime = None,
                     status: str = None) -> str(32):
        '''Adds new entry from import location. Logs event and
        returns entry_uuid.
        Parameters:
        metadata: str
        import_location: str
        started: datetime
        finished: datetime
        status: str'''
        # Important notice: Event logging is disabled.
        meta = json.loads(metadata)
        entry_uuid = meta.get('entry_uuid')
        name = meta.get('name')
        domain = meta.get('domain')
        metatype = meta.get('type')
        parent = meta.get('parent')
        created = datetime.strptime(meta.get('created'), '%Y-%m-%d %H:%M:%S')
        files_list = meta.get('files_list')
        comments = meta.get('user_comments')
        schedule_id = meta.get('schedule_id')
        if self.cursor.execute('''SELECT entry_uuid FROM backups WHERE \
                               entry_uuid = %s''', (entry_uuid,)) > 0:
            self.cursor.execute('''DELETE FROM backups WHERE \
                                entry_uuid = %s''', (entry_uuid,))
            self.cursor.execute('''DELETE FROM backup_files WHERE \
                                entry_uuid = %s''', (entry_uuid,))
        entry_uuid = self.add_entry(
            name, domain, metatype, parent, created, files_list,
            started, finished, status, comments, None,
            None, finished, import_location, schedule_id)
        print('Created new entry.')
        # self.log_operation(entry_uuid, started, finished, status, 'import')
        self.connection.commit()
        return entry_uuid

    def log_list(self) -> list:
        '''Returning list of all logs'''
        self.cursor.execute('''SHOW COLUMNS FROM log''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM log''')
        data = self.cursor.fetchall()
        return self.format_output(columns, data)

    def log_show(self, log_uuid: str(32)) -> dict:
        '''Returning info about specific log
        Parameter:
        log_uuid: str(32)'''
        self.cursor.execute('''SHOW COLUMNS FROM log''')
        columns = self.cursor.fetchall()
        self.cursor.execute('''SELECT * FROM log WHERE log_uuid = %s''',
                            (log_uuid,))
        data = self.cursor.fetchall()
        return self.format_output(columns, data)[0]

    def format_output(self, columns: tuple, data: tuple) -> list:
        '''internal function to format output into list of dicts'''
        formatted_list = []
        for i, element in enumerate(data):
            formatted_list.append({})
            for j, column in enumerate(columns):
                formatted_list[i][column[0]] = data[i][j]
        return formatted_list


class Backup():
    def __init__(self, params: dict, no_db: bool = False) -> None:
        '''Initialize all variables needed for backup operations'''
        self.backup_db_info = params.get("backup_db_info")
        self.location = params.get("location")
        self.backup_mode = params.get("backup_mode")
        self.backup_type = params.get("backup_type")
        self.backupname = params.get("backupname")
        self.backup_options = params.get("backup_options")
        self.clustername = params.get("clustername")
        self.backupdomain = params.get("backupdomain") or self.clustername
        if not no_db:
            self.bdb = Backup_db(self.backup_db_info)
            self.incrementals = self.backup_options.get("incrementals")
            if self.incrementals and self.bdb.count_incrementals(
                    self.clustername) >= int(self.incrementals):
                self.backup_type = "full"
            if self.backup_type == "incremental" \
                    and not self.backup_options.get("full_backupname"):
                self.backup_options["full_backupname"] = \
                    self.bdb.get_newest_backupname(self.clustername)
                if not self.backup_options["full_backupname"]:
                    self.backup_type = "full"
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.clustername = params.get("clustername")
        self.backupdomain = self.clustername
        self.uri = params.get("uri")
        self.append = params.get("append")
        if not self.backupname:
            if self.append:
                self.backupname = self.bdb.backup_show(self.append)["name"]
            else:
                self.backupname = f"{self.backupdomain}-{self.timestamp}"
        self.query = params.get("query") \
            if params.get("query") else self.backupname
        self.backup_id = self.bdb.get_backup_uuid(self.backupname) \
            if params.get("backupname") and not no_db else None
        self.encryption_password = params.get("encryption_password")
        self.directories = self.backup_options.get("directories")
        self.encrypted = params.get("encrypted")
        self.exclude_cmha = self.backup_options.get("exclude_cmha")

    def new_backup(self, backupname: str) -> (str, str):
        timestamp = datetime.now()
        file_list = []
        self.backup_id = self.bdb.add_entry(
            self.backupname, self.backupdomain, self.backup_type,
            self.backup_options.get("full_backupname"), timestamp,
            file_list, timestamp, timestamp, "ongoing",
            comments=self.backup_options.get("userdata"),
            schedule_id=self.backup_options.get("schedule_id"))
        jsonfile = open(f"{self.location}/{self.backupname}.json", "w")
        jsonfile.write(self.bdb.export_metadata(self.backup_id))
        jsonfile.close()
        return self.backup_id

    def append_to_backup(self, filenames: list):
        for filename in filenames:
            file_entry = {"mode": self.backup_mode,
                          "restore_path": self.location,
                          "location": self.backup_options.get(
                              "config_location"),
                          "filename": filename,
                          "encrypted": self.encrypted,
                          "checksum": ""}
            self.bdb.add_file(self.append, file_entry)
        jsonfile = open(f"{self.location}/{self.backupname}.json", "w")
        jsonfile.write(self.bdb.export_metadata(self.append))
        jsonfile.close()

    def backup_restore_container(self):
        container = docker.from_env().containers.run(
            self.backup_options.get("mariadb_image"),
            'bash',
            auto_remove=True,
            detach=True,
            tty=True,
            name='mariadb_backup',
            volumes={
                '/etc/kolla/mariabackup/': {
                    'bind': '/var/lib/kolla/config_files',
                    'mode': 'ro'},
                '/etc/localtime/': {'bind': '/etc/localtime/', 'mode': 'ro'},
                '/var/lib/mysql/': {'bind': '/var/lib/mysql', 'mode': 'rw'},
                self.location: {'bind': '/backup', 'mode': 'rw'},
                'kolla_logs': {'bind': '/var/log/kolla', 'mode': 'rw'}
            },
            environment={
                'KOLLA_CONFIG_STRATEGY': 'COPY_ALWAYS',
                'BACKUP_TYPE': 'full',
                'KOLLA_SERVICE_NAME': 'mariabackup',
            },
            network_mode='host',
            privileged=True,
        )
        return container

    def mariadb_backup(self):
        backup_container = self.backup_restore_container()
        run_cmd_in_container(backup_container.name,
                             'sudo -E kolla_set_configs')
        # name = datetime.now().strftime("%Y%m%d-%H%M%S")
        full_backup = self.backup_options.get("full_backupname")
        name = f"{self.backupname}-mariadb-{self.backup_type}"
        db_password = self.backup_options.get("db_pass")
        db_user = self.backup_options.get("db_user")
        db_host = self.backup_options.get("db_host")
        backup_filename = f'{name}.tar.gz'
        if self.exclude_cmha:
            run_cmd_in_container(
                backup_container.name,
                f'mysqldump -u {db_user} -p{db_password} \
                --host={db_host} --user={db_user} --password={db_password} \
                --no-data cmha > /backup/{name}-cmha.sql')
            if full_backup:
                run_cmd_in_container(
                    backup_container.name,
                    f'mariabackup --defaults-file=/etc/my.cnf \
                    --backup --stream=xbstream --host={db_host} \
                    --user={db_user} --password={db_password} \
                    --incremental-history-name={full_backup}-mariadb-full \
                    --databases-exclude="cmha" > \
                    /backup/{name}.qp.xbc.xbs')
            else:
                run_cmd_in_container(
                    backup_container.name,
                    f'mariabackup --defaults-file=/etc/my.cnf \
                    --backup --stream=xbstream --history={name} \
                    --host={db_host} \
                    --user={db_user} --password={db_password} \
                    --databases-exclude="cmha" > \
                    /backup/{name}.qp.xbc.xbs')
            run_cmd_in_container(
                backup_container.name,
                f'tar zcvf /backup/{backup_filename} \
                /backup/{name}-cmha.sql \
                /backup/{name}.qp.xbc.xbs')
        else:
            if full_backup:
                run_cmd_in_container(
                    backup_container.name,
                    f'mariabackup --defaults-file=/etc/my.cnf \
                    --backup --stream=xbstream --host={db_host} \
                    --user={db_user} --password={db_password} \
                    --incremental-history-name={full_backup}-mariadb-full \
                    > /backup/{name}.qp.xbc.xbs')
            else:
                run_cmd_in_container(
                    backup_container.name,
                    f'mariabackup --defaults-file=/etc/my.cnf \
                    --backup --stream=xbstream --history={name} \
                    --host={db_host} \
                    --user={db_user} --password={db_password} \
                    > /backup/{name}.qp.xbc.xbs')
            run_cmd_in_container(
                backup_container.name,
                f'tar zcvf /backup/{backup_filename} \
                /backup/{name}.qp.xbc.xbs')
        backup_container.stop()
        if self.encrypted:
            backup_filename = self.encrypt_backup(backup_filename)
        self.append_to_backup([backup_filename])
        return self.append, self.backupname

    def mariadb_restore(self):
        suffix = "-encrypted" if self.encrypted else ""
        restore_container = self.backup_restore_container()
        name = f"{self.backupname}-mariadb-{self.backup_type}{suffix}"
        if suffix:
            name = self.decrypt_backup(f"{name}.tar.gz").split(".tar.gz")[0]
        result = []
        if self.backup_type == "incremental":
            full_name = f"{self.backup_options.get('full_backupname')}" \
                f"-mariadb-full{suffix}"
            if suffix:
                full_name = self.decrypt_backup(
                    f"{full_name}.tar.gz").split(".tar.gz")[0]
            result.append(run_cmd_in_container(
                restore_container.name,
                f'rm -rf /backup/restore/* && mkdir -p /backup/restore/full \
                && mkdir -p /backup/restore/{name} \
                && tar zxvf /backup/{full_name}.tar.gz -C /backup \
                && tar zxvf /backup/{name}.tar.gz -C /backup'))
            result.append(run_cmd_in_container(
                restore_container.name,
                f'mbstream -x -C /backup/restore/full \
                < /backup/{full_name}.qp.xbc.xbs && \
                mbstream -x -C /backup/restore/{name} \
                < /backup/{name}.qp.xbc.xbs'))
            result.append(run_cmd_in_container(
                restore_container.name,
                f'mariabackup --defaults-file=/etc/my.cnf \
                --prepare --target-dir /backup/restore/full \
                && mariabackup --defaults-file=/etc/my.cnf \
                --prepare --target-dir /backup/restore/full \
                --incremental-dir /backup/restore/{name}'))
        else:
            result.append(run_cmd_in_container(
                restore_container.name,
                f'rm -rf /backup/restore/* && mkdir -p /backup/restore/full \
                && tar zxvf /backup/{name}.tar.gz -C /backup'))
            result.append(run_cmd_in_container(
                restore_container.name,
                f'mbstream -x -C /backup/restore/full \
                < /backup/{name}.qp.xbc.xbs'))
            result.append(run_cmd_in_container(
                restore_container.name,
                'mariabackup --defaults-file=/etc/my.cnf \
                --prepare --target-dir=/backup/restore/full'))
        result.append(run_cmd_in_container(
            restore_container.name,
            "mariabackup --defaults-file=/etc/my.cnf --copy-back \
            --target-dir /backup/restore/full"))
        if self.exclude_cmha:
            result.append(run_cmd_in_container(
                restore_container.name,
                f'cp /backup/{name}-cmha.sql /var/lib/mysql/'))
        restore_container.stop()
        return result

    def compress_backup(self, output_filename):
        with tarfile.open('%s/%s' % (self.location, output_filename),
                          "w:gz") as tar:
            for dir in self.directories:
                tar.add(dir)

    def extract_backup(self, input_filename):
        tar = tarfile.open(f"{self.location}/{input_filename}")
        tar.extractall(path="/")
        tar.close()

    def encrypt_backup(self, backup_file: str, suffix: bool = True):
        src_filename = f"{self.location}/{backup_file}"
        dst_filename = f"{self.location}/encrypted_backup"
        cipher = Cryptography(self.encryption_password,
                              src_filename, dst_filename)
        cipher.encrypt()
        os.remove(src_filename)
        if suffix:
            splitted_name = backup_file.split(".")
            splitted_name[0] = f"{splitted_name[0]}-encrypted"
            enc_filename = ".".join(splitted_name)
            os.rename(dst_filename, f"{self.location}/{enc_filename}")
            return enc_filename
        else:
            os.rename(dst_filename, src_filename)
            return backup_file

    def decrypt_backup(self, backup_file: str):
        src_filename = f"{self.location}/{backup_file}"
        dst_filename = f"{self.location}/decrypted_backup"
        cipher = Cryptography(self.encryption_password, src_filename,
                              dst_filename)
        cipher.decrypt()
        split_name = backup_file.split("-encrypted")
        backup_name = "".join(split_name)
        os.rename(dst_filename, f"{self.location}/{backup_name}")
        return backup_name

    def dirs_backup(self):
        tarfile_name = f"{self.backupname}-dirs.tar.gz"
        self.compress_backup(tarfile_name)
        if self.encrypted:
            backup_filename = self.encrypt_backup(tarfile_name)
        else:
            backup_filename = tarfile_name
        self.append_to_backup([backup_filename])
        return self.append, self.backupname

    def dirs_restore(self):
        suffix = "-encrypted" if self.encrypted else ""
        tarfile_name = f"{self.backupname}-dirs{suffix}.tar.gz"
        if self.encrypted:
            backup_filename = self.decrypt_backup(tarfile_name)
        else:
            backup_filename = tarfile_name
        self.extract_backup(backup_filename)

    def get_config(self, filename: str = "./brf_config.yml") -> dict:
        with open(filename) as config_file:
            config = yaml.load(config_file.read(), Loader=yaml.Loader)
        return config

    def get_config_value(self, config: dict, key: str):
        value = config
        for name in key.split("."):
            try:
                value = value[int(name)]
            except ValueError:
                value = value[name]
        return value

    def create_single_backup_package(self):
        output_filename = f"{self.backupname}_exported_backup_package.tar.gz"
        files_list = self.bdb.get_backup_filenames(self.backupname)
        files_list.append(f"{self.backupname}.json")
        with tarfile.open(f"{self.location}/{output_filename}", "w:gz") as tar:
            os.chdir(self.location)
            for filename in files_list:
                tar.add(filename)
        return output_filename


def restore_backup(params):
    backup = Backup(params, no_db=True)
    if params["backup_mode"] == "directory":
        result = backup.dirs_restore()
    else:
        result = backup.mariadb_restore()
    return result


def rebuild_database(params):
    backup = Backup(params)
    backup.bdb.rebuild_from_metadata(backup.location)


def create_backup(params):
    backup = Backup(params)
    backup_db = Backup_db(backup.backup_db_info)
    fulls = backup_db.count_full_backups(backup.clustername)
    oldest = backup_db.get_oldest_full_backupname(backup.clustername)
    if backup.append:
        pass
    else:
        backup.append = backup.new_backup(backup.backupname)
    if params["backup_mode"] == "directory":
        result = backup.dirs_backup()
    else:
        result = backup.mariadb_backup()
    filenames = backup.bdb.get_backup_filenames(backup.backupname)
    filenames.append(f"{backup.backupname}.json")
    backup.bdb.change_status(backup.append, "Complete")
    return result + (filenames, {"fulls": fulls, "oldest": oldest})


def delete_helper(backupname: str, backup):
    backup_files = backup.bdb.get_backup_filenames(backupname)
    for file in backup_files:
        os.remove(f"{backup.location}/{file}")
    os.remove(f"{backup.location}/{backupname}.json")
    backup_uuid = backup.bdb.get_backup_uuid(backupname)
    backup.bdb.delete_entry(backup_uuid)


def delete_backup(params):
    backup = Backup(params)
    incremental_backups = backup.bdb.get_incrementals(backup.clustername,
                                                      backup.backupname)
    if incremental_backups:
        for inc_backup in incremental_backups:
            delete_helper(inc_backup, backup)
    delete_helper(backup.backupname, backup)


def show_backup(params):
    backup = Backup(params)
    backup_uuid = backup.bdb.get_backup_uuid(backup.backupname)
    return backup.bdb.backup_show(backup_uuid)


def list_backup(params):
    backup = Backup(params)
    db_list = backup.bdb.backup_list()
    return_dict = {}
    for entry in db_list:
        if [entry.get("domain")][0] == backup.clustername:
            try:
                return_dict[entry.get("domain")]
            except KeyError:
                return_dict[entry.get("domain")] = \
                    {"latest": "", "backups": []}
            return_dict[entry.get("domain")]['backups'].append({
                "backupname": entry.get("name"),
                "backuptype": entry.get("type"),
                "parent": entry.get("parent"),
                "comments": entry.get("user_comments")})
    return return_dict


def backup_filelist(params):
    backup = Backup(params)
    return backup.bdb.get_backup_filenames(backup.backupname)


def parse_uri(uri: str) -> (str, str, str, str):
    host = uri.split("@")[-1].split("/")[0]
    path = uri.split(host)[-1]
    password = uri.split("@")[0].split(":")[-1]
    username = uri.split("@")[0].split(":")[:-1][-1].split("/")[-1]
    return host, username, password, path


def start_ftp_connection(ftps_uri):
    host, username, password, _ = parse_uri(ftps_uri)
    ftp = FTP_TLS(host)
    ftp.login(user=username, passwd=password)
    ftp.prot_p()
    return ftp


def export_backup(params):
    backup = Backup(params)
    result = []
    started = datetime.now()
    ftp = start_ftp_connection(backup.uri)
    _, _, _, export_path = parse_uri(backup.uri)
    filename = backup.create_single_backup_package()
    result.append(filename)
    if export_path.strip("/"):
        ftps_path = f"{export_path.strip('/')}/{filename}"
    else:
        ftps_path = filename
    with open(f"{backup.location}/{filename}", "rb") as bfile:
        bfile.seek(0)
        result.append(ftp.storbinary(f"STOR {ftps_path}", bfile))
    result.append(ftp.quit())
    finished = datetime.now()
    backup.bdb.export_entry(
        backup.bdb.get_backup_uuid(backup.backupname), backup.uri,
        started, finished, "Exported")
    os.remove(f"{backup.location}/{filename}")
    return result


def import_backup(params):
    backup = Backup(params)
    result = []
    started = datetime.now()
    ftp = start_ftp_connection(backup.uri)
    _, _, _, import_path = parse_uri(backup.uri)
    filename = os.path.basename(import_path)
    result.append(filename)
    local_filename = "/".join([backup.location, filename])
    with open(f"{local_filename}", "wb") as bfile:
        result.append(ftp.retrbinary(
            f"RETR {import_path.strip('/')}", bfile.write))
    result.append(ftp.quit())
    backup.backupname = filename.split("_exported_backup_package")[0]
    backup_exists = backup.bdb.get_backup_uuid(backup.backupname)
    if backup_exists:
        params["backupname"] = backup.backupname
        delete_backup(params)
    with tarfile.open(local_filename, 'r:gz') as tar:
        tar.extractall(path=backup.location)
    os.remove(local_filename)
    metafile = f"{backup.backupname}.json"
    with open(f"{backup.location}/{metafile}", "r") as bfile:
        metadata = bfile.read()
    finished = datetime.now()
    backup.bdb.import_entry(
        metadata, backup.uri, started, finished, "Imported")
    return result


def run_cmd_in_container(container_id_or_name: str, command: str) -> tuple:
    """
    Run a command inside this container. Similar to docker exec.

    Parameters:
        container_id_or_name (str) - Container name or ID.
        command (str) - Command to be executed.

    Returns:
        A tuple of (exit_code, output)
            exit_code: (int):
                Exit code for the executed command.

            output: (bytes):
                 A bytestring containing response data.

    Example use:
        run_cmd_in_container('mariadb', 'hostname')
        run_cmd_in_container('74024ed1b060', 'ls /etc/')
        print(run_cmd_in_container('mariadb', 'ls -l /etc/').output.decode())
    """
    container_obj = docker.from_env().containers.get(container_id_or_name)
    response = container_obj.exec_run(["/bin/bash", "-c", command])
    return response


def run_module():
    module_args = dict(
        encrypted=dict(type="bool", required=False, default="on"),
        action=dict(type="str", required=True),
        location=dict(type="str", required=False),
        clustername=dict(type="str", required=True),
        backupdomain=dict(type="str", required=False),
        backupname=dict(type="str", required=False),
        uri=dict(type="str", required=False),
        backup_mode=dict(type="str", required=False, default="directory"),
        backup_type=dict(type="str", required=False, default="full"),
        backup_options=dict(type="dict", required=False, default=dict()),
        encryption_password=dict(type="str", required=False),
        append=dict(type="str", required=False),
        backup_db_info=dict(type="dict", required=True),
        query=dict(type="str", required=False, default="*"),
        config_file=dict(type="str", required=False,
                         default="./brf_config.yml")
    )
    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )
    result = dict(
        changed=False,
        action=module.params["action"],
        result="Success",
        output=[],
        backup_list=[],
        options={}
    )

    if module.check_mode:
        module.exit_json(**result)
    if module.params["action"] == "restore":
        result["output"] = restore_backup(module.params)
        result["changed"] = True
    elif module.params["action"] == "rebuild":
        result["output"] = rebuild_database(module.params)
        result["changed"] = True
    elif module.params["action"] == "delete":
        delete_backup(module.params)
        result["changed"] = True
    elif module.params["action"] == "backup":
        result["id"], result["backupname"], result["backup_list"], \
            result["options"] = create_backup(module.params)
        result["changed"] = True
    elif module.params["action"] == "list":
        result["changed"] = False
        result["backup_list"] = list_backup(module.params)
    elif module.params["action"] == "show":
        result["changed"] = False
        result["output"] = show_backup(module.params)
    elif module.params["action"] == "export":
        result["changed"] = True
        result["output"] = export_backup(module.params)
    elif module.params["action"] == "import":
        result["changed"] = True
        result["output"] = import_backup(module.params)
    elif module.params["action"] == "filelist":
        result["changed"] = False
        result["backup_list"] = backup_filelist(module.params)
    else:
        print("ERROR! There is no such action!")
        sys.exit(1)
    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
