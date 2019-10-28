"""Build class to build kernel from repository and commit.

Builds are created by the buildmanager.

Calling run() on this object will spawn a subprocess to do the build.

The subprocess runs a shell script that executes the build.

The build process then waits for the build run to
complete, by checking for the existence of image every 60 seconds.
When the image is ready, the shell script will upload it into GCS
before exiting the process.
"""
import io
import logging
from multiprocessing import Process
import os
import shutil
import subprocess
from subprocess import call
import sys
from time import sleep
import gce_funcs
from google.cloud import storage


class Kbuild(object):
  """Build class."""

  def __init__(self, repository, commit, build_id,
               log_dir_path):

    self.repository = repository
    self.commit = commit
    self.id = build_id
    self.image_file_path = '/root/builds/linux/arch/x86/boot/bzImage'

    # LOG/RESULTS VARIABLES
    self.log_file_path = log_dir_path + self.id
    self.buildlog_file_path = self.log_file_path + '.buildlog'

    logging.debug('Starting build %s', self.id)
  # end __init__

  def run(self):
    logging.info('Spawning child process for build %s', self.id)
    self.process = Process(target=self.__run)
    self.process.start()
    return

  def _setup_logging(self):
    logging.info('Move logging to build file %s', self.log_file_path)
    logging.getLogger().handlers = []  # clear handlers for new process
    logging.basicConfig(
        filename=self.log_file_path,
        format='[%(levelname)s:%(asctime)s %(filename)s:%(lineno)s-'
               '%(funcName)s()] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
    sys.stderr = sys.stdout = open(self.log_file_path, 'a+')

  def __run(self):
    """Main function for a build

    This function will be called in a separate running process, after
    run is called. The function makes an explicit call to exit() after
    finishing the procedure to exit the process.
    This function should not be called directly.
    """
    logging.info('Child process spawned for build %s', self.id)
    self._setup_logging()
    started = self.__start()
    if not started:
      logging.error('Build %s failed to start', self.id)
      logging.error('Build was %s commit=%s', self.repository, self.commit)
    else:
      successful = self.__monitor()
      self.__finish(successful)
    logging.info('Exiting monitor process for build %s', self.id)
    exit()

  def __start(self):
    logging.debug('opening log file %s', self.buildlog_file_path)
    f = open(self.buildlog_file_path, 'w')
    logging.info('Building %s commit=%s', self.repository, self.commit)
    process = subprocess.Popen(['/usr/local/lib/buildkernel.sh', self.repository, self.commit],
      stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    returncode = process.wait()
    f.close()
    logging.info('Build returned %s', returncode)
    return returncode == 0

  def __monitor(self):
    """Main monitor loop of build process.

    This function looks for the built image every 60 seconds.

    When the build is detected to have completed, it will return True.

    If the build is not complete after 30 minutes, this will return False.

    Returns:
      boolean value: True if the build finished. False if not.
    """
    logging.info('Entered monitor.')
    logging.info('Waiting for build to complete...')

    while True:
      for _ in range(30):
        sleep(1.0)
      logging.info('Querying build %s', self.id)
      if os.path.isfile(self.image_file_path):
        break
    return True

  def __finish(self, successful):
    """
    Args:
      successful: whether or not the monitor loop had succeeded or failed.
    """
    if os.path.isfile(self.image_file_path):
        os.remove(self.image_file_path)

    logging.info('Finished')
    return


### end class Build
