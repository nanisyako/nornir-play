#!/usr/bin/env python
#from gevent import monkey; monkey.patch_all()
from nornir import InitNornir
from nornir.core.filter import F
from nornir.plugins.tasks.files import write_file
from nornir.plugins.tasks.networking import netmiko_send_command
from nornir.core.exceptions import NornirSubTaskError
from netmiko import NetMikoAuthenticationException, NetMikoTimeoutException
import time
from datetime import datetime
import re
#from creds import insert_creds


BACKUPDIR = '../configs'
DIFFDIR = '../diffs'


def config_filter_cisco_ios(cfg):
    """Filter unneeded items that change from the config."""

    # Strip the header line
    header_line1_re = r"^Building configuration.*$"
    header_line2_re = r"^Current configuration.*$"
    header_line3_re = r"^!Running configuration.*$"

    # Strip the service timestamps comments
    service_timestamps1_re = r"^! Last configuration change at.*$"
    service_timestamps2_re = r"^! NVRAM config last updated at.*$"
    service_timestamps3_re = r"^! No configuration change since last restart.*$"

    # Strip misc
    misc1_re = r'^ntp clock-period.*$'
    misc2_re = r'^!Time.*$'

    for pattern in [header_line1_re, header_line2_re, header_line3_re,
                    service_timestamps1_re, service_timestamps2_re, 
                    service_timestamps3_re, misc1_re, misc2_re]:
        cfg = re.sub(pattern, "", cfg, flags=re.M).lstrip()
    return cfg


def backup(task):
  host = task.host
  last_exception = None

  retries = 0
  while retries <= 2:
    try:
      data = task.run(task=netmiko_send_command,
                     command_string='show running-config',
                     enable=True)

      # check if config incomplete
      # could also look for commands typically found at the end of configs
      if len(data.result) < 100:
        raise ValueError('Config unexpectedly short')
        
      break
    
    except NornirSubTaskError as e:
        last_exception = e.result.exception
        if isinstance(e.result.exception, NetMikoTimeoutException):
          #Looking for Timed-out reading channel 
          if 'reading channel' or 'existing session' in e.result[0].result:
            if retries == 2:
              raise e         
          else:
            raise e

        if isinstance(e.result.exception, NetMikoAuthenticationException):
          #Looking for cisco_nxos
          if 'cisco_nxos' in e.result[0].result:
            if retries == 2:
              raise e         
          else:
            raise e

        if isinstance(e.result.exception, ValueError):
          #Looking for Failed to enter enable mode
          if 'enable mode' in e.result[0].result:
            if retries == 2:
              raise e         
          else:
            raise e  

        if isinstance(e.result.exception, OSError):
          if 'Search pattern' in e.result[0].result:
            net_connect = task.host.get_connection("netmiko", task.nornir.config)
            print(f'{host} prompt problem = {net_connect.find_prompt()}')
            if retries == 2:
              raise e         
          else:
            raise e

        if isinstance(e.result.exception, EOFError):
          if 'closed by remote device' in e.result[0].result:
            if retries == 2:
              raise e         
          else:
            raise e

        print(f'{host} hit error {last_exception} - retrying...')
        task.results.pop()
        time.sleep(5)

    except ValueError as e:
      last_exception = e
      if 'unexpectedly short' in e:
        if retries == 2:
          raise e
      else:
        raise e

      print(f'{host} hit error {last_exception} - retrying...')
      task.results.pop()   
      time.sleep(5)

    retries += 1

  host.close_connections()
  data.result = config_filter_cisco_ios(data.result)

  #occassionly an empty line appears in the middle of IOS config not sure why
  #just get rid of them all
  if host.platform == 'cisco_ios':
    data.result = re.sub(r'^\s*$', "", data.result, flags=re.M)

  task.run(write_file,
           filename=f'{BACKUPDIR}/{host}.cfg',
           content=data.result)
 

def main():
  nr = InitNornir(config_file='../config.yaml',
                  core={'num_workers': 50},
                  )
  #insert_creds(nr.inventory)
  ios_filt = ~F(platform="cisco_wlc")
  ios = nr.filter(ios_filt)
  start_time = datetime.now()
  result = ios.run(task=backup)
  elapsed_time = datetime.now() - start_time

  print('-'*50)
  print("Results")
  print('-'*50)
  for host, multiresult in result.items():
    if multiresult.failed:
        print(f'{host} - failed, check nornir.log')
        continue
    for r in multiresult:
      if r.name == 'write_file':
        if r.changed:
          #print(f'{host} - differences found since last backup')
          diff_time = datetime.now()
          filename = f'{DIFFDIR}/{host}--{diff_time.strftime("%d-%m-%y-%X")}.txt'
          with open(filename, 'w') as f:
            f.write(r.diff)
  print('-'*50)
  print("Elapsed time: {}".format(elapsed_time))


if __name__ == "__main__":
  main()

""""
Issues.  With 20 workers on 1300 devices I experienced the following random errors (low rate)
1.NetMikoTimeoutException: Timed-out reading channel, data not available.
2.ValueError: Failed to enter enable mode. Please ensure you pass the 'secret' argument to ConnectHandler
3.Corrupt backups < 100 characters
4.NetMikoAuthenticationException, primarily on cisco_nxos as they as they don't like tacacs+ timeouts, 
  and may have fallen back to local
Plus others if we increase workers.

Possible Fixes?
- use latest Netmiko
or 
- keep reducing num_workers
or
- two retries, as in above code
  - catch errors and retry
  - check if len(data.result) < 100 and retry
or
- look into your AAA server
or
- close connections within task
or
- use Netmiko global delay factor of 2 or more
or
- increase Netmiko conn_timeout to 20s or more
or
- enter - from gevent import monkey; monkey.patch_all() - as the very first line of code - well on the particular server I was having trouble with it fixed the issues
  if there is nothing wrong with your server, then running this may actually make the task run sligtly slower than without
or
- if Nornir 3, try gevent runner - again, same issue with monkey above
 - https://github.com/no-such-anthony/nornir3_play/blob/master/gevent_runner.py
 - https://github.com/no-such-anthony/nornir3_play/blob/master/gevent-runner-test.py
or
- run script on a different server...surprisingly this can sometimes work and none of the above needed...

Diff Issues
A lot of Cisco devices will show these in the diffs...hence the filter before write_file

-!Time: Wed Oct  9 11:02:39 2019
+!Time: Wed Oct  9 14:53:31 2019
and
-ntp clock-period 36028974
+ntp clock-period 36028975

"""
