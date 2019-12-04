"""The BuildManager sets up and manages a single build.

The only arguments to it are the originally executed command line.
This original command will contain the repository and commit id of
the kernel to build.

On construction:
  assign unique build ID from timestamp
  create log dir

On run:
  start build
  wait for build to complete
  notify ltm

The main usage of the class is:
x = BuildManager(cmd)
x.run()

On construction, if any misconfigurations are discovered (e.g. a lack of
available quota for VMs in the GCE project) or commit id is invalid,
errors may be thrown.

Under normal circumstances, run() will spawn a subprocess, which when
exited should have completed the kernel build.

The image is then added to the project GCS bucket.
"""
from datetime import datetime
import fcntl
import hashlib
import logging
from multiprocessing import Process
import os
import random
import shutil
import subprocess
from subprocess import call
import sys
from time import sleep
from urllib2 import HTTPError

import gce_funcs
from bldsrv import BLDSRV
from kbuild import Kbuild
from google.cloud import storage

class BuildManager(object):
  """BuildManager class.

  The BuildManager on construction will acqurie a unique buildid.
  After this, when the run() function is called, the
  buildmanager will spawn a child process in which it will manage the build.
  """

  def __init__(self, orig_cmd, opts=None):
    logging.info('Launching new build')
    logging.info('Getting unique build id..')
    build_id = get_datetime_build_id()
    logging.info('Creating new build with id %s', build_id)

    self.id = build_id
    self.orig_cmd = orig_cmd.strip()
    self.log_dir_path = BLDSRV.build_log_dir + '%s/' % build_id
    self.log_file_path = self.log_dir_path + 'run.log'

    BLDSRV.create_log_dir(self.log_dir_path)
    logging.info('Created new build with id %s', self.id)

    self.gs_bucket = gce_funcs.get_gs_bucket().strip()
    self.bucket_subdir = gce_funcs.get_bucket_subdir().strip()
    self.gs_kernel = None

    if opts and 'commit_id' in opts:
      self.commit = opts['commit_id'].strip()
    if opts and 'git_repo' in opts:
      self.repository = opts['git_repo'].strip()
    self.build_dir = make_kernel_dir(self.repository)
    self.build_path = BLDSRV.repo_cache_path + self.build_dir
    self.kernel_build = self.build_path + BLDSRV.image_path
    self.kernel_build_filename = BLDSRV.image_name

    logging.info('Cloning repository to %s', self.build_path)

    self.kbuild = Kbuild(self.repository, self.commit, self.build_dir, self.id,
      self.log_dir_path)

  def run(self):
    logging.info('Entered run()')
    logging.info('Spawning child process for build %s', self.id)
    self.process = Process(target=self.__run)
    self.process.start()
    return

  def get_info(self):
    """Get info about the build.

    Info includes the buildrunid, repository path, and commit id.

    Returns:
      info: a dictionary.
    """
    info = {}
    info['repository'] = self.repository
    info['commit'] = self.commit
    info['id'] = self.id
    return info

  def _setup_logging(self):
    logging.info('Move logging to build file %s', self.log_file_path)
    logging.getLogger().handlers = []  # clear log handlers
    logging.basicConfig(
        filename=self.log_file_path,
        format='[%(levelname)s:%(asctime)s %(filename)s:%(lineno)s-'
               '%(funcName)s()] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S', level=logging.DEBUG)
    sys.stderr = sys.stdout = open(self.log_file_path, 'a')

  def __run(self):
    """Main method for a testrun.
    """
    logging.info('Child process spawned for build %s', self.id)
    self._setup_logging()
    self.__start()
    self.__wait_for_build()
    self.__finish()
    logging.info('Exiting process for build %s', self.id)
    exit()

  def __start(self):
    """Launches the build

    This function will start the build.
    """
    logging.info('Entered start()')
    self.kbuild.run()
    if not self.kbuild.process:
      logging.warning('Build %s failed to start', self.id)
      logging.warning('Building %s from commit %s', self.repository, self.commit)
    else:
        logging.info('Started build %s', self.id)

    return

  def __wait_for_build(self):
    logging.info('Entered wait_for_build()')
    logging.info('Waiting for build %s', self.id)
    self.kbuild.process.join()
    return

  def __finish(self):
    """Completion method of the build manager after build is started.
    """
    logging.info('Entered finish()')
    self.__upload_build()
    self.__cleanup()
    logging.info('Done.')
    return

  def __upload_build(self):
    """uploads kernel build to GS bucket.
    """
    if os.path.isfile(self.kernel_build):
        storage_client = storage.Client()
        bucket = storage_client.lookup_bucket(self.gs_bucket)

        with open('%s' % (self.kernel_build), 'r') as f:
          bucket.blob(self.kernel_build_filename).upload_from_file(f)
    else:
        logging.info('Could not find bzImage to upload.')

  def __cleanup(self):
    """Cleanup to be done after the build is finished.

    Delete the bzImage.
    """
    logging.info('Entered cleanup')
    if os.path.isfile(self.kernel_build):
        os.remove(self.kernel_build)
    logging.info('Finished cleanup')
    return


### end class BuildManager

def make_kernel_dir(repository):
  """Create a unique directory name for the repository being cloned

  Need to create a unique name for each repository so that future
  clones of the same repository are copied to the same directory.

  Unique name created using md5 hash of the repository url

  Returns:
    kernel_dir: a string representing the directory name
  """
  kernel_dir = hashlib.md5(repository.encode()).hexdigest()
  return kernel_dir

def get_datetime_build_id():
  curtime = datetime.now()
  build_id = '%.4d%.2d%.2d%.2d%.2d%.2d' % (curtime.year, curtime.month,
                                              curtime.day, curtime.hour,
                                              curtime.minute,
                                              curtime.second)
  return build_id
