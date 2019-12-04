import base64
import binascii
import logging
import os
import traceback
from ltm import LTM
from ltm_login import User
from testrunmanager import TestRunManager
from multiprocessing import Process
from subprocess import call
from time import sleep
import gce_funcs
import googleapiclient.discovery
import googleapiclient.errors
from google.cloud import storage
import requests
import json

class BldsrvManager(object):

    def __init__(self, cmd_json, orig_cmd, opts=None):
        logging.info('Starting new Build Run')
        launch_bldsrv_cmd = ['gce-xfstests', 'launch-bldsrv']
        self.launch_bldsrv_cmd = launch_bldsrv_cmd
        self.gce_proj_id = gce_funcs.get_proj_id()
        self.gce_project = gce_funcs.get_proj_id().strip()
        self.gce_zone = gce_funcs.get_gce_zone()
        self.gce_region = self.gce_zone[:-2]
        self.gs_bucket = gce_funcs.get_gs_bucket().strip()
        self.instance_name = 'xfstests-bldsrv'
        self.orig_cmd = orig_cmd
        self.cmd_json = cmd_json
        self.opts = opts
        # end __init__

    def run(self):
        logging.info('Starting launching build server')
        self.process = Process(target=self.__run)
        self.process.start()
    
    def __run(self):
        logging.info('Entered run()')
        started = self.__start()

        if not started:
            logging.error('Build server failed to start')
        else:
            logging.info('Successfully launched build server')
            # waiting for build server to set up
            for _ in range(120):
                sleep(1.0)
            # get build server ip address
            bldsrv_ip = self.__get_bldsrv_ip()          
            # login and send cmdline to bldsrv
            sent = self.__send_to_bldsrv(bldsrv_ip)
            if sent == 'false':
                logging.error('Failed to send cmd to build server')
        exit()

    def __start(self):
        logging.info('Staring subprocess to launch build server')
        logging.info('Calling command %s', str(self.launch_bldsrv_cmd))
        returned = call(self.launch_bldsrv_cmd)
        logging.info('Command returned %s', returned)
        return returned == 0

    def __get_bldsrv_ip(self):
        self.compute = googleapiclient.discovery.build('compute','v1')
        bldsrv_info = self.compute.instances().get(
                project=self.gce_project, zone=self.gce_zone,
                instance=self.instance_name).execute()
        bldsrv_ip = bldsrv_info['networkInterfaces'][-1]['accessConfigs'][0]['natIP']
        logging.info('Build server ip address: %s', bldsrv_ip)
        return bldsrv_ip

    def __send_to_bldsrv(self, bldsrv_ip):
        with open('pwd.json', 'r') as f:
            pwd = json.load(f)
        logging.info('Build server password: %s', pwd)
        logging.info('gce-xfstests original command line: %s', self.cmd_json)
        header = {'Content-Type': 'application/json'}
        with requests.Session() as s:
            url_login = 'https://' + bldsrv_ip + '//login'
            r = s.post(url_login, json=pwd, headers=header, verify=False)
            logging.info('log in request return: %s', r.content)
            url_gce = 'https://' + bldsrv_ip + '//gce-xfstests'
            r = s.post(url_gce, json=self.cmd_json, headers=header, verify=False)
            logging.info('gce cmd request return: %s', r.content)
            logging.info('returned status %s', r.content['status'])
        return r.content.split('"status":')[1].split('}')[0]
